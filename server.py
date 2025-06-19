#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# Metadata
# Version: 2.0.0
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

APP_ROOT = Path(__file__).resolve().parent
HOSTNAME = '0.0.0.0'
PORT = 10001
VIDEO_NAMING_PATTERN = os.environ.get('VIDEO_NAMING_PATTERN', '{userId}@twitter-{tweetId}')

pipe_args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def send_json_response(self, status_code: int, data: Dict[str, Any]) -> None:
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

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

    def handle_download_request(self, query: Dict[str, List[str]]) -> None:
        if not self.is_authenticated():
            self.send_json_response(401, {'ok': False, 'reason': 'Not authenticated'})
            return
        url = query.get('url', [''])[0]
        format_param = query.get('format', ['mp4'])[0].lower()
        quality = query.get('quality', [''])[0]

        # YOUTUBE Code zeile -------------->
        if 'youtube.com' in url or 'youtu.be' in url:
            file_ext = 'mp3' if format_param == 'mp3' else 'mp4'
            video_title = self.get_youtube_title(url)
            if not video_title:
                self.send_json_response(500, {'ok': False, 'reason': 'Could not fetch video title.'})
                return

            filename = f"{video_title}.{file_ext}"
            ascii_filename = filename.encode('ascii', 'ignore').decode('ascii')
            utf8_filename = quote(filename)

            cmd = ['yt-dlp', *pipe_args]
            if format_param == 'mp3':
                cmd += ['--extract-audio', '--audio-format', 'mp3', '--output', '-', url]
                content_type = 'audio/mpeg'
            else:
                if not quality:
                    # Hole alle Formate und wähle das mit größter filesize_approx
                    try:
                        result = subprocess.run(
                            ['yt-dlp', '--no-warnings', '--skip-download', '-j', url],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            check=True
                        )
                        info = json.loads(result.stdout)
                        best_fmt = None
                        best_size = 0
                        for fmt in info.get('formats', []):
                            size = fmt.get('filesize_approx') or 0
                            if size and size > best_size:
                                best_fmt = fmt.get('format_id')
                                best_size = size
                        if best_fmt:
                            quality = best_fmt
                    except Exception as e:
                        pass  # Fallback: kein quality setzen, Standardformat nehmen
                if quality:
                    cmd += ['-f', quality]
                else:
                    cmd += ['--format', 'mp4']
                cmd += ['--output', '-', url]
                content_type = 'video/mp4'

            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if result.returncode == 0:
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header(
                    'Content-Disposition',
                    f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{utf8_filename}'
                )
                self.end_headers()
                self.wfile.write(result.stdout)
            else:
                self.send_json_response(500, {'ok': False, 'reason': result.stderr.decode('utf-8')})
            return

        # TWITTER Code zeile -------------->
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

        # ────────────────────────────────────────────────────────────────────
        if parsed_path.path.startswith('/css/') or parsed_path.path.startswith('/image/'):
            return super().do_GET()
        # ────────────────────────────────────────────────────────────────────

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

        elif parsed_path.path == '/yt-qualities':
            query = urllib.parse.parse_qs(parsed_path.query)
            url = query.get('url', [''])[0]
            if not url or ('youtube.com' not in url and 'youtu.be' not in url):
                self.send_json_response(400, {'ok': False, 'reason': 'Invalid YouTube URL'})
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

with socketserver.TCPServer((HOSTNAME, PORT), RequestHandler) as httpd:
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
