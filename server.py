#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# Metadata
# Version: 3.0.1
# Author/Dev: Gerald Hasani
# Name: StrimDL - YouTube & X Downloader
# Email: contact@gerald-hasani.com
# GitHub: https://github.com/Gerald-Ha
# ------------------------------------------------------------------------------

import os
import sys
from pathlib import Path
import http.server
import socketserver
import json
import urllib.parse
import subprocess
from urllib.parse import quote
from typing import Dict, Any, Optional, Tuple, List
import hashlib
import logging
import time
from datetime import datetime
import threading
from queue import Queue

class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

APP_ROOT = Path(__file__).resolve().parent
HOSTNAME = '0.0.0.0'
PORT = 10001
VIDEO_NAMING_PATTERN = os.environ.get('VIDEO_NAMING_PATTERN', '{userId}@twitter-{tweetId}')
CACHE_DIR = Path(APP_ROOT / 'cache')
CACHE_DIR.mkdir(exist_ok=True)

download_status: Dict[str, Queue] = {}
status_buffer: Dict[str, List[str]] = {}
status_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

pipe_args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def send_json_response(self, status_code: int, data: Dict[str, Any]) -> None:
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def send_status_update(self, session_id: str, status: str) -> None:
        with status_lock:
            if session_id in download_status:
                download_status[session_id].put(status)
            if session_id not in status_buffer:
                status_buffer[session_id] = []
            status_buffer[session_id].append(status)
            if len(status_buffer[session_id]) > 10:
                status_buffer[session_id] = status_buffer[session_id][-10:]
    
    def get_status_queue(self, session_id: str) -> Queue:
        with status_lock:
            if session_id not in download_status:
                download_status[session_id] = Queue()
                if session_id in status_buffer:
                    for buffered_status in status_buffer[session_id]:
                        download_status[session_id].put(buffered_status)
            return download_status[session_id]
    
    def cleanup_status_queue(self, session_id: str) -> None:
        with status_lock:
            if session_id in download_status:
                del download_status[session_id]
            if session_id in status_buffer:
                del status_buffer[session_id]

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/login':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                username = data.get('username', '')
                password = data.get('password', '')
                env_user = os.environ.get('STRIMDL_USER', '')
                env_pass = os.environ.get('STRIMDL_PASS', '')
                if username == env_user and password == env_pass:

                    session = hashlib.sha256(f'{username}:{password}'.encode()).hexdigest()
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Set-Cookie', f'session={session}; Path=/; HttpOnly')
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True}).encode())
                else:
                    self.send_json_response(401, {'ok': False, 'reason': 'Invalid credentials'})
            except Exception as e:
                self.send_json_response(400, {'ok': False, 'reason': str(e)})
        elif parsed_path.path == '/logout':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Set-Cookie', 'session=deleted; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True}).encode())
        else:
            self.send_json_response(404, {'ok': False, 'reason': f'Unknown POST endpoint: {self.path}'})

    def is_authenticated(self):
        env_user = os.environ.get('STRIMDL_USER', '')
        env_pass = os.environ.get('STRIMDL_PASS', '')
        if not env_user or not env_pass:
            return True
        cookie = self.headers.get('Cookie', '')
        session = hashlib.sha256(f'{env_user}:{env_pass}'.encode()).hexdigest()
        return f'session={session}' in cookie

    def handle_index_page(self) -> None:
        if not self.is_authenticated():
            try:
                with open(APP_ROOT / 'login.html', 'r', encoding='utf-8') as f:
                    html = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(html.encode())
            except Exception as e:
                self.send_json_response(500, {'ok': False, 'reason': f'Error loading login page: {e}'})
            return
        try:
            with open(APP_ROOT / 'index.html', 'r', encoding='utf-8') as f:
                html = f.read()
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode())
        except Exception as e:
            self.send_json_response(500, {'ok': False, 'reason': f'Error loading index page: {e}'})

    def parse_twitter_url(self, url: str) -> Optional[Tuple[str, str]]:
        parsed_url = urllib.parse.urlparse(url)
        path_parts = parsed_url.path.split('/')
        if len(path_parts) >= 4 and path_parts[2] == 'status':
            return path_parts[1], path_parts[3]
        return None

    def get_youtube_title(self, url: str) -> Optional[str]:
        try:
            result = subprocess.run(
                ['yt-dlp', '--get-title', url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            return result.stdout.strip().replace('"', "'")
        except subprocess.CalledProcessError:
            return None

    def get_cache_key(self, url: str, quality: Optional[str] = None) -> str:
        key_string = url
        if quality:
            key_string += f"_{quality}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def get_cached_video_path(self, url: str, quality: Optional[str] = None) -> Path:
        cache_key = self.get_cache_key(url, quality)
        return CACHE_DIR / f"{cache_key}.mp4"
    
    def clear_cache_for_url(self, url: str) -> None:
        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            for cache_file in CACHE_DIR.glob(f"{url_hash}*.mp4"):
                cache_file.unlink()
                logger.info(f"Deleted cache file: {cache_file}")
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")

    def download_and_cache_video(self, url: str, quality: Optional[str] = None, session_id: Optional[str] = None) -> Optional[Path]:
        cache_path = self.get_cached_video_path(url, quality)
        
        if cache_path.exists():
            logger.info(f"Using cached video: {cache_path}")
            if session_id:
                self.send_status_update(session_id, "Using cached video")
            return cache_path
        
        logger.info(f"Downloading video to cache: {url}, quality: {quality}")
        
        if quality:
            format_spec = f'{quality}+bestaudio/best'
        else:
            format_spec = 'bestvideo+bestaudio/best'
        
        cmd = ['yt-dlp', *pipe_args, '-f', format_spec, '--merge-output-format', 'mp4', '-o', str(cache_path), url]
        
        logger.info(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
        
        if result.returncode == 0 and cache_path.exists():
            logger.info(f"Video cached successfully: {cache_path}")
            if session_id:
                self.send_status_update(session_id, "Video downloaded successfully")
            return cache_path
        else:
            error_msg = result.stderr.decode('utf-8', errors='ignore')
            logger.error(f"Failed to cache video: {error_msg}")
            if session_id:
                self.send_status_update(session_id, "Download failed")
            return None

    def convert_cached_video(self, cache_path: Path, output_format: str, quality: Optional[str] = None, url: Optional[str] = None, session_id: Optional[str] = None) -> Optional[bytes]:
        import tempfile
        
        try:
            if output_format == 'mp3':
                logger.info(f"Converting to MP3 with best quality: {cache_path}")
                if session_id:
                    self.send_status_update(session_id, "Start converting...")
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3', dir=str(CACHE_DIR)) as tmp_file:
                    tmp_path = Path(tmp_file.name)
                
                try:
                    cmd = [
                        'ffmpeg', '-i', str(cache_path),
                        '-codec:a', 'libmp3lame', '-q:a', '0', '-write_xing', '1',
                        '-ar', '44100', '-ac', '2', '-id3v2_version', '3',
                        '-y',  # Überschreibe Output-Datei
                        str(tmp_path)
                    ]
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
                    
                    if result.returncode == 0 and tmp_path.exists():
                        with open(tmp_path, 'rb') as f:
                            output_data = f.read()
                        logger.info(f"MP3 conversion successful, size: {len(output_data)} bytes")
                        tmp_path.unlink()
                        return output_data
                    else:
                        error_msg = result.stderr.decode('utf-8', errors='ignore')
                        logger.error(f"MP3 conversion failed: {error_msg}")
                        if tmp_path.exists():
                            tmp_path.unlink()
                        return None
                except Exception as e:
                    logger.error(f"Error during MP3 conversion: {e}")
                    if tmp_path.exists():
                        tmp_path.unlink()
                    return None
            else:
                logger.info(f"Converting video with quality: {quality}")
                if session_id:
                    self.send_status_update(session_id, "Start converting...")
                
                probe_cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(cache_path)]
                probe_result = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                needs_recode = False
                target_height = None
                
                if probe_result.returncode == 0:
                    probe_info = json.loads(probe_result.stdout)
                    for stream in probe_info.get('streams', []):
                        codec = stream.get('codec_name', '').lower()
                        if codec in ['vp9', 'av1', 'vp8']:
                            needs_recode = True
                            logger.info(f"Non-H.264 codec detected ({codec}), re-encoding to H.264")
                        if stream.get('codec_type') == 'video':
                            target_height = stream.get('height')
                
                if quality and url:
                    try:
                        result = subprocess.run(
                            ['yt-dlp', '--no-warnings', '--skip-download', '-j', '-f', quality, url],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=10
                        )
                        if result.returncode == 0:
                            fmt_info = json.loads(result.stdout)
                            target_height = fmt_info.get('height')
                            if target_height:
                                needs_recode = True  # Skalierung erfordert Re-Encoding
                                logger.info(f"Target height from quality: {target_height}p")
                    except Exception as e:
                        logger.warning(f"Could not get quality info: {e}")
                
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4', dir=str(CACHE_DIR)) as tmp_file:
                    tmp_path = Path(tmp_file.name)
                
                try:
                    if needs_recode or (quality and target_height):
                        cmd = ['ffmpeg', '-i', str(cache_path)]
                        
                        if target_height:
                            cmd.extend(['-vf', f'scale=-2:{target_height}'])
                        
                        cmd.extend([
                            '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                            '-c:a', 'aac', '-b:a', '128k',
                            '-movflags', '+faststart',
                            '-pix_fmt', 'yuv420p',
                            '-y',
                            str(tmp_path)
                        ])
                    else:
                        cmd = ['ffmpeg', '-i', str(cache_path), '-c', 'copy', '-movflags', '+faststart', '-y', str(tmp_path)]
                    
                    logger.info(f"Running: {' '.join(cmd)}")
                    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
                    
                    if result.returncode == 0 and tmp_path.exists():
                        with open(tmp_path, 'rb') as f:
                            output_data = f.read()
                        logger.info(f"Video conversion successful, size: {len(output_data)} bytes")
                        tmp_path.unlink()
                        return output_data
                    else:
                        error_msg = result.stderr.decode('utf-8', errors='ignore')
                        logger.error(f"Video conversion failed: {error_msg}")
                        if tmp_path.exists():
                            tmp_path.unlink()
                        return None
                except Exception as e:
                    logger.error(f"Error during conversion: {e}")
                    if tmp_path.exists():
                        tmp_path.unlink()
                    return None
        except subprocess.TimeoutExpired:
            logger.error("Conversion timeout")
            return None
        except Exception as e:
            logger.error(f"Error converting video: {e}")
            return None

    def handle_download_request(self, query: Dict[str, List[str]]) -> None:
        if not self.is_authenticated():
            self.send_json_response(401, {'ok': False, 'reason': 'Not authenticated'})
            return
        
        url = query.get('url', [''])[0]
        format_param = query.get('format', ['mp4'])[0].lower()
        quality = query.get('quality', [''])[0]

        logger.info(f"Download request: url={url}, format={format_param}, quality={quality}")

        session_id = query.get('session_id', [''])[0]
        if not session_id:
            session_id = hashlib.md5(f"{url}_{quality}_{format_param}_{time.time()}".encode()).hexdigest()
        self.get_status_queue(session_id)
        
        self.send_status_update(session_id, "Starting download...")

        if 'youtube.com' in url or 'youtu.be' in url:
            video_title = self.get_youtube_title(url)
            if not video_title:
                logger.error("Could not fetch video title")
                self.cleanup_status_queue(session_id)
                self.send_json_response(500, {'ok': False, 'reason': 'Could not fetch video title.'})
                return

            file_ext = 'mp3' if format_param == 'mp3' else 'mp4'
            filename = f"{video_title}.{file_ext}"
            ascii_filename = filename.encode('ascii', 'ignore').decode('ascii')
            utf8_filename = quote(filename)
            
            cache_path = self.download_and_cache_video(url, quality if quality else None, session_id)
            
            if not cache_path:
                logger.error("Failed to download/cache video")
                self.cleanup_status_queue(session_id)
                self.send_json_response(500, {'ok': False, 'reason': 'Failed to download video. Check logs for details.'})
                return

            content_type = 'audio/mpeg' if format_param == 'mp3' else 'video/mp4'
            output_data = self.convert_cached_video(cache_path, format_param, quality, url, session_id)
            
            self.send_status_update(session_id, "Processing complete")
            time.sleep(0.1)
            self.cleanup_status_queue(session_id)
            
            if not output_data:
                logger.error("Failed to convert video")
                self.send_json_response(500, {'ok': False, 'reason': 'Video conversion failed. The video may be corrupted or the format is not supported. Check server logs for details.'})
                return

            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('X-Session-ID', session_id)
            self.send_header(
                'Content-Disposition',
                f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_filename}'
            )
            self.end_headers()
            self.wfile.write(output_data)
            logger.info(f"Successfully sent {format_param} file: {filename}")
            return

        url_info = self.parse_twitter_url(url)
        if not url_info:
            self.send_json_response(400, {'ok': False, 'reason': f"Ungültige URL: '{url}'"})
            return

        user_id, tweet_id = url_info
        output_file_name = f"{VIDEO_NAMING_PATTERN.format(userId=user_id, tweetId=tweet_id)}.mp4"
        ascii_filename = output_file_name.encode('ascii', 'ignore').decode('ascii')
        utf8_filename = quote(output_file_name)

        cmd = ['yt-dlp', *pipe_args, '--output', '-', url]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode == 0:
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header(
                'Content-Disposition',
                f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_filename}'
            )
            self.end_headers()
            self.wfile.write(result.stdout)
        else:
            self.send_json_response(500, {'ok': False, 'reason': result.stderr.decode('utf-8')})

    def do_GET(self) -> None:
        parsed_path = urllib.parse.urlparse(self.path)

        if parsed_path.path.startswith('/css/') or parsed_path.path.startswith('/image/'):
            return super().do_GET()

        if parsed_path.path == '/':
            self.handle_index_page()

        elif parsed_path.path == '/login.html':
            try:
                with open(APP_ROOT / 'login.html', 'r', encoding='utf-8') as f:
                    html = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(html.encode())
            except Exception as e:
                self.send_json_response(500, {'ok': False, 'reason': f'Error loading login page: {e}'})
            return

        elif parsed_path.path == '/download':
            query = urllib.parse.parse_qs(parsed_path.query)
            self.handle_download_request(query)

        elif parsed_path.path == '/status':
            if not self.is_authenticated():
                self.send_json_response(401, {'ok': False, 'reason': 'Not authenticated'})
                return
            query = urllib.parse.parse_qs(parsed_path.query)
            session_id = query.get('session_id', [''])[0]
            if not session_id:
                self.send_json_response(400, {'ok': False, 'reason': 'Missing session_id'})
                return
            
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            
            try:
                status_queue = self.get_status_queue(session_id)
                timeout_count = 0
                max_timeout = 300
                
                try:
                    self.wfile.write(b": connection established\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, OSError):
                    logger.info("SSE client disconnected immediately")
                    return
                
                while timeout_count < max_timeout:
                    try:
                        status = status_queue.get(timeout=1)
                        timeout_count = 0
                        
                        try:
                            self.wfile.write(f"data: {json.dumps({'status': status})}\n\n".encode())
                            self.wfile.flush()
                        except (BrokenPipeError, OSError):
                            logger.info("SSE client disconnected")
                            break
                        
                        if status in ["Processing complete", "Download failed"]:
                            break
                    except:
                        timeout_count += 1
                        try:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                        except (BrokenPipeError, OSError):
                            logger.info("SSE client disconnected (keepalive)")
                            break
            except Exception as e:
                logger.error(f"SSE error: {e}")
            finally:
                pass
            return

        elif parsed_path.path == '/cache-reset':
            if not self.is_authenticated():
                self.send_json_response(401, {'ok': False, 'reason': 'Not authenticated'})
                return
            query = urllib.parse.parse_qs(parsed_path.query)
            url = query.get('url', [''])[0]
            if url:
                self.clear_cache_for_url(url)
                logger.info(f"Cache reset for URL: {url}")
            self.send_json_response(200, {'ok': True})

        elif parsed_path.path == '/yt-qualities':
            query = urllib.parse.parse_qs(parsed_path.query)
            url = query.get('url', [''])[0]
            if not url or ('youtube.com' not in url and 'youtu.be' not in url):
                self.send_json_response(400, {'ok': False, 'reason': 'Invalid YouTube URL'})
                return
            
            parsed_url = urllib.parse.urlparse(url)
            query_params_url = urllib.parse.parse_qs(parsed_url.query)
            if 'list' in query_params_url:
                self.send_json_response(400, {'ok': False, 'reason': 'Playlist links are not supported. Please use a single video URL.'})
                return
            
            try:
                result = subprocess.run(
                    ['yt-dlp', '--no-warnings', '--skip-download', '-j', url],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True
                )
                info = json.loads(result.stdout)

                qualities: List[Dict[str, Any]] = []
                for fmt in info.get('formats', []):
                    fmt_id = fmt.get('format_id')
                    height = fmt.get('height')
                    note = fmt.get('format_note') or (f"{height}p" if height else '')
                    ext = fmt.get('ext', '')
                    size = fmt.get('filesize_approx') or 0

                    if ext == 'mhtml' or 'storyboard' in (note or '').lower():
                        continue

                    if height:
                        if note:
                            label = f"{note} ({ext})"
                        else:
                            label = f"{height}p ({ext})"
                        if size:
                            label += f" ~{size//1024//1024}MB"
                        qualities.append({'format_id': fmt_id, 'label': label})

                self.send_json_response(200, {'ok': True, 'qualities': qualities})

            except Exception as e:
                self.send_json_response(500, {'ok': False, 'reason': str(e)})

        else:
            self.send_json_response(
                404,
                {'ok': False, 'reason': f"Unbekannte Anfrage: {self.command} {self.path}"}
            )

def get_yt_dlp_version() -> str:
    result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
    return result.stdout.strip()

with ThreadingHTTPServer((HOSTNAME, PORT), RequestHandler) as httpd:
    print(f"Server läuft auf http://{HOSTNAME}:{PORT}/")
    print()
    print(f"Benutzung:")
    print(f"  Web-Interface:")
    print(f"    http://{HOSTNAME}:{PORT}/")
    print()
    print(f"  Async-Download via URL:")
    print(f"    GET http://{HOSTNAME}:{PORT}/download?url=https://...")
    print()
    print(f"Versionen:")
    print(f"  yt-dlp: {get_yt_dlp_version()}")
    print()

    httpd.serve_forever()
