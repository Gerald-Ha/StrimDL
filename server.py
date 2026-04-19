#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# Metadata
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
import urllib.request
import uuid
import platform
import signal
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
APP_VERSION = '3.0.5'
VIDEO_NAMING_PATTERN = os.environ.get('VIDEO_NAMING_PATTERN', '{userId}@twitter-{tweetId}')

YTDLP_COOKIES_PATH = os.environ.get('YTDLP_COOKIES_PATH', '').strip()

YTDLP_UPDATE_ON_START = os.environ.get('YTDLP_UPDATE_ON_START', 'true').strip().lower() in ('1', 'true', 'yes', 'on')

STRIMDL_UPDATE_DEVMODE = os.environ.get('STRIMDL_UPDATE_DEVMODE', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

STRIMDL_UPDATE_SERVER_URL = os.environ.get('STRIMDL_UPDATE_SERVER_URL', 'https://update.gerald-hasani.com').strip().rstrip('/')

STRIMDL_UPDATE_API_KEY = 'upd_9148c16e00fc1a55c0c8f8d4ea7f3001de1f217fed16b33be0e129ebaa4ba588'
STRIMDL_UPDATE_PROJECT_ID = 'strimdl'
UPDATE_CHECK_INTERVAL_SECONDS = 180 if STRIMDL_UPDATE_DEVMODE else 86400
FFMPEG_VIDEO_PRESET = os.environ.get('FFMPEG_VIDEO_PRESET', 'veryfast').strip() or 'veryfast'
FFMPEG_VIDEO_CRF = os.environ.get('FFMPEG_VIDEO_CRF', '24').strip() or '24'
FFMPEG_MAX_HEIGHT_RAW = os.environ.get('FFMPEG_MAX_HEIGHT', '1440').strip()

FFMPEG_MAX_HEIGHT = int(FFMPEG_MAX_HEIGHT_RAW) if FFMPEG_MAX_HEIGHT_RAW.isdigit() and int(FFMPEG_MAX_HEIGHT_RAW) > 0 else None
CACHE_DIR = Path(APP_ROOT / 'cache')

CACHE_DIR.mkdir(exist_ok=True)

INSTANCE_ID_FILE = CACHE_DIR / 'instance_id'
def get_instance_id() -> str:
    try:
        if INSTANCE_ID_FILE.exists():
            stored = INSTANCE_ID_FILE.read_text(encoding='utf-8').strip()

            uuid.UUID(stored)

            return stored
    except Exception:
        pass
    instance_id = str(uuid.uuid4())

    try:
        INSTANCE_ID_FILE.write_text(instance_id, encoding='utf-8')

    except Exception as e:
        logger.warning(f"Could not persist update instance id: {e}")

    return instance_id
download_status: Dict[str, Queue] = {}

status_buffer: Dict[str, List[str]] = {}

status_lock = threading.Lock()

update_status: Dict[str, Any] = {
    'ok': True,
    'status': 'unchecked',
    'current_version': APP_VERSION,
    'devmode': STRIMDL_UPDATE_DEVMODE,
    'check_interval_seconds': UPDATE_CHECK_INTERVAL_SECONDS,
}

update_status_checked_at = 0.0
update_status_lock = threading.Lock()

active_processes: Dict[str, subprocess.Popen] = {}

cancelled_sessions = set()

process_lock = threading.Lock()

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
    def is_session_cancelled(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        with process_lock:
            return session_id in cancelled_sessions
    def cancel_download_session(self, session_id: str) -> bool:
        killed = False
        with process_lock:
            cancelled_sessions.add(session_id)

            process = active_processes.get(session_id)

        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)

                killed = True
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.warning(f"Could not terminate process for session {session_id}: {e}")

        self.send_status_update(session_id, "Download cancelled")

        return killed
    def cleanup_download_session(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        with process_lock:
            active_processes.pop(session_id, None)

            cancelled_sessions.discard(session_id)

    def run_managed_command(
        self,
        cmd: List[str],
        session_id: Optional[str] = None,
        timeout: Optional[int] = None,
        text: bool = False
    ) -> subprocess.CompletedProcess:
        if self.is_session_cancelled(session_id):
            empty = '' if text else b''
            return subprocess.CompletedProcess(cmd, -signal.SIGTERM, empty, 'Cancelled' if text else b'Cancelled')

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            start_new_session=True
        )

        if session_id:
            with process_lock:
                active_processes[session_id] = process
        try:
            stdout, stderr = process.communicate(timeout=timeout)

        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)

                stdout, stderr = process.communicate(timeout=5)

            except Exception:
                try:
                    os.killpg(process.pid, signal.SIGKILL)

                except Exception:
                    pass
                stdout, stderr = process.communicate()

            timeout_msg = 'Command timed out'
            if text:
                stderr = f"{stderr or ''}\n{timeout_msg}".strip()

            else:
                stderr = (stderr or b'') + f"\n{timeout_msg}".encode()

            return subprocess.CompletedProcess(cmd, 124, stdout, stderr)

        finally:
            if session_id:
                with process_lock:
                    if active_processes.get(session_id) is process:
                        active_processes.pop(session_id, None)

        if self.is_session_cancelled(session_id) and process.returncode != 0:
            if text:
                stderr = f"{stderr or ''}\nCancelled".strip()

            else:
                stderr = (stderr or b'') + b'\nCancelled'
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)

    def check_for_strimdl_update(self, force: bool = False) -> Dict[str, Any]:
        global update_status_checked_at, update_status
        now = time.time()

        with update_status_lock:
            if not force and update_status_checked_at and now - update_status_checked_at < UPDATE_CHECK_INTERVAL_SECONDS:
                cached = dict(update_status)

                cached['cached'] = True
                cached['next_check_seconds'] = max(0, int(UPDATE_CHECK_INTERVAL_SECONDS - (now - update_status_checked_at)))

                return cached
        request_id = str(uuid.uuid4())

        payload = {
            'project': {
                'id': STRIMDL_UPDATE_PROJECT_ID,
                'instance_id': get_instance_id(),
            },
            'current': {
                'version': APP_VERSION,
            },
            'channel': 'stable',
            'platform': {
                'os': platform.system().lower() or 'linux',
                'arch': platform.machine(),
                'container': 'docker',
            },
            'capabilities': {
                'accept_prerelease': False,
                'supports_delta': False,
            },
        }

        endpoint = f"{STRIMDL_UPDATE_SERVER_URL}/api/updates/v1/updates/check"
        body = json.dumps(payload).encode('utf-8')

        request = urllib.request.Request(
            endpoint,
            data=body,
            method='POST',
            headers={
                'Authorization': f'Bearer {STRIMDL_UPDATE_API_KEY}',
                'Content-Type': 'application/json',
                'X-Request-ID': request_id,
                'User-Agent': f'StrimDL/{APP_VERSION}',
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))

            normalized = {
                'ok': True,
                'status': data.get('status', 'unknown'),
                'current_version': data.get('current', {}).get('version', APP_VERSION),
                'project': data.get('project') or {},
                'update': data.get('update'),
                'message': data.get('message'),
                'server_time': data.get('server_time'),
                'request_id': data.get('request_id', request_id),
                'devmode': STRIMDL_UPDATE_DEVMODE,
                'check_interval_seconds': UPDATE_CHECK_INTERVAL_SECONDS,
                'cached': False,
                'next_check_seconds': UPDATE_CHECK_INTERVAL_SECONDS,
            }

            logger.info(f"StrimDL update check: {normalized['status']}")

        except urllib.error.HTTPError as e:
            try:
                error_data = json.loads(e.read().decode('utf-8'))

            except Exception:
                error_data = {'message': str(e)}

            normalized = {
                'ok': False,
                'status': error_data.get('status', 'error'),
                'current_version': APP_VERSION,
                'message': error_data.get('message', str(e)),
                'devmode': STRIMDL_UPDATE_DEVMODE,
                'check_interval_seconds': UPDATE_CHECK_INTERVAL_SECONDS,
                'cached': False,
                'next_check_seconds': UPDATE_CHECK_INTERVAL_SECONDS,
            }

            logger.warning(f"StrimDL update check failed: {normalized['message']}")

        except Exception as e:
            normalized = {
                'ok': False,
                'status': 'error',
                'current_version': APP_VERSION,
                'message': f'Update check unavailable: {e}',
                'devmode': STRIMDL_UPDATE_DEVMODE,
                'check_interval_seconds': UPDATE_CHECK_INTERVAL_SECONDS,
                'cached': False,
                'next_check_seconds': UPDATE_CHECK_INTERVAL_SECONDS,
            }

            logger.warning(f"StrimDL update check failed: {e}")

        with update_status_lock:
            update_status = normalized
            update_status_checked_at = time.time()

        return dict(normalized)

    def build_yt_dlp_cmd(self, *args: str) -> List[str]:
        cmd = ['yt-dlp', *pipe_args]
        if YTDLP_COOKIES_PATH:
            cmd.extend(['--cookies', YTDLP_COOKIES_PATH])

        cmd.extend(args)

        return cmd
    def clean_yt_dlp_error(self, stderr: str) -> str:
        error_msg = stderr.strip() or 'yt-dlp failed without an error message.'
        if 'Sign in to confirm' in error_msg and '--cookies' in error_msg:
            if YTDLP_COOKIES_PATH:
                error_msg += f"\n\nCookies are configured via YTDLP_COOKIES_PATH={YTDLP_COOKIES_PATH}. Make sure the file is mounted into the container and still valid."
            else:
                error_msg += "\n\nYouTube is asking for browser cookies. Export a cookies.txt file and set YTDLP_COOKIES_PATH to its path inside the container."
        return error_msg
    def send_json_response(self, status_code: int, data: Dict[str, Any]) -> None:
        self.send_response(status_code)

        self.send_header('Content-type', 'application/json')

        self.end_headers()

        self.wfile.write(json.dumps(data).encode())

    def send_status_update(self, session_id: str, status: str) -> None:
        """Sende Status-Update an SSE-Client"""
        with status_lock:
                        if session_id in download_status:
                download_status[session_id].put(status)

                        if session_id not in status_buffer:
                status_buffer[session_id] = []
            status_buffer[session_id].append(status)

                        if len(status_buffer[session_id]) > 10:
                status_buffer[session_id] = status_buffer[session_id][-10:]
    def get_status_queue(self, session_id: str) -> Queue:
        """Hole oder erstelle Status-Queue für Session"""
        with status_lock:
            if session_id not in download_status:
                download_status[session_id] = Queue()

                                if session_id in status_buffer:
                    for buffered_status in status_buffer[session_id]:
                        download_status[session_id].put(buffered_status)

            return download_status[session_id]
    def cleanup_status_queue(self, session_id: str) -> None:
        """Entferne Status-Queue nach Download"""
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

        elif parsed_path.path == '/cancel':
            if not self.is_authenticated():
                self.send_json_response(401, {'ok': False, 'reason': 'Not authenticated'})

                return
            content_length = int(self.headers.get('Content-Length', 0))

            body = self.rfile.read(content_length) if content_length else b'{}'
            try:
                data = json.loads(body)

            except Exception:
                data = {}

            session_id = data.get('session_id', '')

            if not session_id:
                self.send_json_response(400, {'ok': False, 'reason': 'Missing session_id'})

                return
            killed = self.cancel_download_session(session_id)

            self.send_json_response(200, {'ok': True, 'cancelled': True, 'killed_process': killed})

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
                html = f.read().replace('{{APP_VERSION}}', APP_VERSION)

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
    def get_youtube_title(self, url: str, session_id: Optional[str] = None) -> Optional[str]:
        try:
            result = self.run_managed_command(
                self.build_yt_dlp_cmd('--get-title', url),
                session_id=session_id,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

            return result.stdout.strip().replace('"', "'")

        except subprocess.CalledProcessError as e:
            logger.error(f"Could not fetch YouTube title: {self.clean_yt_dlp_error(e.stderr or '')}")

            return None
    def get_cache_key(self, url: str, quality: Optional[str] = None) -> str:
        """Generiere einen Cache-Key basierend auf der URL und Qualität"""
        key_string = url
        if quality:
            key_string += f"_{quality}"
        return hashlib.md5(key_string.encode()).hexdigest()

    def get_cached_video_path(self, url: str, quality: Optional[str] = None) -> Path:
        """Gibt den Pfad zum gecachten Video zurück"""
        cache_key = self.get_cache_key(url, quality)

        return CACHE_DIR / f"{cache_key}.mp4"
    def clear_cache_for_url(self, url: str) -> None:
        """Löscht alle Cache-Dateien für eine URL (alle Qualitäten)"""
        try:
            url_hash = hashlib.md5(url.encode()).hexdigest()

            for cache_file in CACHE_DIR.glob(f"{url_hash}*.mp4"):
                cache_file.unlink()

                logger.info(f"Deleted cache file: {cache_file}")

        except Exception as e:
            logger.error(f"Error clearing cache: {e}")

    def download_and_cache_video(self, url: str, quality: Optional[str] = None, session_id: Optional[str] = None) -> Optional[Path]:
        """Lädt Video in gewählter Qualität herunter und cached es, gibt den Pfad zurück"""
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
                cmd = self.build_yt_dlp_cmd('-f', format_spec, '--merge-output-format', 'mp4', '-o', str(cache_path), url)

        logger.info(f"Running: {' '.join(cmd)}")

        result = self.run_managed_command(cmd, session_id=session_id, timeout=1800)

        if result.returncode == 0 and cache_path.exists():
            logger.info(f"Video cached successfully: {cache_path}")

            if session_id:
                self.send_status_update(session_id, "Video downloaded successfully")

            return cache_path
        else:
            error_msg = self.clean_yt_dlp_error(result.stderr.decode('utf-8', errors='ignore'))

            if self.is_session_cancelled(session_id):
                logger.info(f"Download cancelled while caching: {url}")

                for partial_file in CACHE_DIR.glob(f"{cache_path.stem}*"):
                    try:
                        partial_file.unlink()

                    except Exception as e:
                        logger.warning(f"Could not remove partial cache file {partial_file}: {e}")

            else:
                logger.error(f"Failed to cache video: {error_msg}")

            if session_id:
                self.send_status_update(session_id, "Download cancelled" if self.is_session_cancelled(session_id) else "Download failed")

            return None
    def convert_cached_video(self, cache_path: Path, output_format: str, quality: Optional[str] = None, url: Optional[str] = None, session_id: Optional[str] = None) -> Optional[bytes]:
        """Konvertiert gecachtes Video zu MP3 oder MP4 mit spezifischer Qualität"""
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
                        '-y',                          str(tmp_path)

                    ]
                    result = self.run_managed_command(cmd, session_id=session_id, timeout=1800)

                    if result.returncode == 0 and tmp_path.exists():
                                                with open(tmp_path, 'rb') as f:
                            output_data = f.read()

                        logger.info(f"MP3 conversion successful, size: {len(output_data)} bytes")

                                                tmp_path.unlink()

                        return output_data
                    else:
                        error_msg = result.stderr.decode('utf-8', errors='ignore')

                        if self.is_session_cancelled(session_id):
                            logger.info("MP3 conversion cancelled")

                        else:
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
                source_height = None
                if probe_result.returncode == 0:
                    probe_info = json.loads(probe_result.stdout)

                    for stream in probe_info.get('streams', []):
                        if stream.get('codec_type') == 'video':
                            codec = stream.get('codec_name', '').lower()

                            source_height = stream.get('height')

                            target_height = source_height
                            if codec in ['vp9', 'av1', 'vp8']:
                                needs_recode = True
                                logger.info(f"Non-H.264 codec detected ({codec}), re-encoding to H.264")

                                if quality and url:
                    try:
                        result = subprocess.run(
                            self.build_yt_dlp_cmd('--no-warnings', '--skip-download', '-j', '-f', quality, url),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=10
                        )

                        if result.returncode == 0:
                            fmt_info = json.loads(result.stdout)

                            target_height = fmt_info.get('height')

                            if target_height:
                                logger.info(f"Target height from quality: {target_height}p")

                    except Exception as e:
                        logger.warning(f"Could not get quality info: {e}")

                if target_height and FFMPEG_MAX_HEIGHT and target_height > FFMPEG_MAX_HEIGHT:
                    logger.info(f"Limiting target height from {target_height}p to {FFMPEG_MAX_HEIGHT}p via FFMPEG_MAX_HEIGHT")

                    target_height = FFMPEG_MAX_HEIGHT
                if target_height and (source_height is None or target_height != source_height):
                    needs_recode = True
                                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4', dir=str(CACHE_DIR)) as tmp_file:
                    tmp_path = Path(tmp_file.name)

                try:
                    if needs_recode:
                                                cmd = ['ffmpeg', '-i', str(cache_path)]
                                                if target_height and (source_height is None or target_height != source_height):
                            cmd.extend(['-vf', f'scale=-2:{target_height}'])

                        cmd.extend([
                            '-c:v', 'libx264', '-preset', FFMPEG_VIDEO_PRESET, '-crf', FFMPEG_VIDEO_CRF,
                            '-c:a', 'aac', '-b:a', '128k',
                            '-movflags', '+faststart',                              '-pix_fmt', 'yuv420p',
                            '-y',                              str(tmp_path)

                        ])

                    else:
                                                cmd = ['ffmpeg', '-i', str(cache_path), '-c', 'copy', '-movflags', '+faststart', '-y', str(tmp_path)]
                    logger.info(f"Running: {' '.join(cmd)}")

                    result = self.run_managed_command(cmd, session_id=session_id, timeout=1800)

                    if result.returncode == 0 and tmp_path.exists():
                                                with open(tmp_path, 'rb') as f:
                            output_data = f.read()

                        logger.info(f"Video conversion successful, size: {len(output_data)} bytes")

                                                tmp_path.unlink()

                        return output_data
                    else:
                        error_msg = result.stderr.decode('utf-8', errors='ignore')

                        if self.is_session_cancelled(session_id):
                            logger.info("Video conversion cancelled")

                        else:
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
            video_title = self.get_youtube_title(url, session_id)

            if self.is_session_cancelled(session_id):
                logger.info("Download cancelled while fetching title")

                self.cleanup_status_queue(session_id)

                self.cleanup_download_session(session_id)

                self.send_json_response(499, {'ok': False, 'reason': 'Download cancelled.'})

                return
            if not video_title:
                logger.error("Could not fetch video title")

                self.cleanup_status_queue(session_id)

                self.cleanup_download_session(session_id)

                self.send_json_response(500, {'ok': False, 'reason': 'Could not fetch video title.'})

                return
            file_ext = 'mp3' if format_param == 'mp3' else 'mp4'
            filename = f"{video_title}.{file_ext}"
            ascii_filename = filename.encode('ascii', 'ignore').decode('ascii')

            utf8_filename = quote(filename)

                        cache_path = self.download_and_cache_video(url, quality if quality else None, session_id)

            if not cache_path:
                if self.is_session_cancelled(session_id):
                    logger.info("Download cancelled")

                    self.cleanup_status_queue(session_id)

                    self.cleanup_download_session(session_id)

                    self.send_json_response(499, {'ok': False, 'reason': 'Download cancelled.'})

                    return
                logger.error("Failed to download/cache video")

                self.cleanup_status_queue(session_id)

                self.cleanup_download_session(session_id)

                self.send_json_response(500, {'ok': False, 'reason': 'Failed to download video. Check logs for details.'})

                return
                        content_type = 'audio/mpeg' if format_param == 'mp3' else 'video/mp4'
            output_data = self.convert_cached_video(cache_path, format_param, quality, url, session_id)

            if not output_data:
                if self.is_session_cancelled(session_id):
                    logger.info("Download cancelled during conversion")

                    self.cleanup_status_queue(session_id)

                    self.cleanup_download_session(session_id)

                    self.send_json_response(499, {'ok': False, 'reason': 'Download cancelled.'})

                    return
                logger.error("Failed to convert video")

                self.cleanup_status_queue(session_id)

                self.cleanup_download_session(session_id)

                self.send_json_response(500, {'ok': False, 'reason': 'Video conversion failed. The video may be corrupted or the format is not supported. Check server logs for details.'})

                return
                        self.send_status_update(session_id, "Processing complete")

            time.sleep(0.1)              self.cleanup_status_queue(session_id)

            self.cleanup_download_session(session_id)

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
            self.cleanup_status_queue(session_id)

            self.cleanup_download_session(session_id)

            self.send_json_response(400, {'ok': False, 'reason': f"Ungültige URL: '{url}'"})

            return
        user_id, tweet_id = url_info
        output_file_name = f"{VIDEO_NAMING_PATTERN.format(userId=user_id, tweetId=tweet_id)}.mp4"
        ascii_filename = output_file_name.encode('ascii', 'ignore').decode('ascii')

        utf8_filename = quote(output_file_name)

        cmd = self.build_yt_dlp_cmd('--output', '-', url)

        result = self.run_managed_command(cmd, session_id=session_id, timeout=1800)

        if result.returncode == 0:
            self.send_status_update(session_id, "Processing complete")

            time.sleep(0.1)

            self.cleanup_status_queue(session_id)

            self.cleanup_download_session(session_id)

            self.send_response(200)

            self.send_header('Content-Type', 'video/mp4')

            self.send_header(
                'Content-Disposition',
                f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_filename}'
            )

            self.end_headers()

            self.wfile.write(result.stdout)

        else:
            if self.is_session_cancelled(session_id):
                self.cleanup_status_queue(session_id)

                self.cleanup_download_session(session_id)

                self.send_json_response(499, {'ok': False, 'reason': 'Download cancelled.'})

                return
            self.cleanup_status_queue(session_id)

            self.cleanup_download_session(session_id)

            self.send_json_response(500, {'ok': False, 'reason': self.clean_yt_dlp_error(result.stderr.decode('utf-8', errors='ignore'))})

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

            self.send_header('X-Accel-Buffering', 'no')              self.end_headers()

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
                                                if status in ["Processing complete", "Download failed", "Download cancelled"]:
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

        elif parsed_path.path == '/app-update':
            if not self.is_authenticated():
                self.send_json_response(401, {'ok': False, 'reason': 'Not authenticated'})

                return
            query = urllib.parse.parse_qs(parsed_path.query)

            force = query.get('force', [''])[0].lower() in ('1', 'true', 'yes')

            self.send_json_response(200, self.check_for_strimdl_update(force))

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
                    self.build_yt_dlp_cmd('--no-warnings', '--skip-download', '-j', url),
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

            except subprocess.CalledProcessError as e:
                error_msg = self.clean_yt_dlp_error(e.stderr or '')

                logger.error(f"Failed to fetch YouTube qualities: {error_msg}")

                self.send_json_response(200, {'ok': False, 'reason': error_msg})

            except Exception as e:
                logger.error(f"Failed to fetch YouTube qualities: {e}")

                self.send_json_response(500, {'ok': False, 'reason': str(e)})

        else:
            self.send_json_response(
                404,
                {'ok': False, 'reason': f"Unbekannte Anfrage: {self.command} {self.path}"}

            )

def get_yt_dlp_version() -> str:
    result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)

    return result.stdout.strip()

def update_yt_dlp() -> None:
    if not YTDLP_UPDATE_ON_START:
        return
    try:
        result = subprocess.run(['yt-dlp', '-U'], capture_output=True, text=True, timeout=120)

        output = (result.stdout or result.stderr).strip()

        if result.returncode == 0:
            logger.info(f"yt-dlp update check: {output}")

        else:
            logger.warning(f"yt-dlp update check failed: {output}")

    except Exception as e:
        logger.warning(f"yt-dlp update check failed: {e}")

update_yt_dlp()

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

    print(f"  ffmpeg preset: {FFMPEG_VIDEO_PRESET}, CRF: {FFMPEG_VIDEO_CRF}, max height: {FFMPEG_MAX_HEIGHT or 'source'}")

    if YTDLP_COOKIES_PATH:
        cookies_status = "found" if Path(YTDLP_COOKIES_PATH).is_file() else "missing"
        print(f"  yt-dlp cookies: {YTDLP_COOKIES_PATH} ({cookies_status})")

    print()

    httpd.serve_forever()
