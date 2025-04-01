#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# Metadata
# Version: 1.0.1
# Author/Dev: Gerald Hasani
# Name: GH Twitter/Youtube Video Downloader
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

    def handle_index_page(self) -> None:
        try:
            with open(APP_ROOT / 'index.html', 'r', encoding='utf-8') as f:
                html = f.read()
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode())
        except Exception as e:
            self.send_json_response(500, {'ok': False, 'reason': f'Fehler beim Laden der Startseite: {e}'})

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
        url = query.get('url', [''])[0]
        format_param = query.get('format', ['mp4'])[0].lower()

        # YOUTUBE
        if 'youtube.com' in url or 'youtu.be' in url:
            file_ext = 'mp3' if format_param == 'mp3' else 'mp4'
            video_title = self.get_youtube_title(url)
            if not video_title:
                self.send_json_response(500, {'ok': False, 'reason': 'Konnte Videotitel nicht abrufen.'})
                return

            filename = f"{video_title}.{file_ext}"
            ascii_filename = filename.encode('ascii', 'ignore').decode('ascii')
            utf8_filename = quote(filename)

            cmd = ['yt-dlp', *pipe_args]
            if format_param == 'mp3':
                cmd += ['--extract-audio', '--audio-format', 'mp3', '--output', '-', url]
                content_type = 'audio/mpeg'
            else:
                cmd += ['--format', 'mp4', '--output', '-', url]
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

        # TWITTER
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

        if parsed_path.path == '/':
            self.handle_index_page()
        elif parsed_path.path == '/download':
            query = urllib.parse.parse_qs(parsed_path.query)
            self.handle_download_request(query)
        else:
            self.send_json_response(404, {'ok': False, 'reason': f"Unbekannte Anfrage: {self.command} {self.path}"})

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
