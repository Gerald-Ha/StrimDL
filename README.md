# GH Media Downloader UI

A simple, modern web interface to download media from **YouTube** and **X (formerly Twitter)** using [yt-dlp](https://github.com/yt-dlp/yt-dlp) and Python.

Supports direct downloads as:
- 🎬 **YouTube videos (.mp4)**
- 🎵 **YouTube audio (.mp3)**
- 📥 **Twitter/X videos** (as `.mp4`)

---

## 🚀 Features

- 🎯 Clean and responsive dark UI
- 🔎 Automatic YouTube title as filename
- 🧠 Smart MP4/MP3 selection (only enabled for YouTube)
- ⚡️ No persistent storage required (downloads stream to browser)
- 🐳 Easy deployment via Docker

---

## 📦 Installation

Build the image locally:
```bash
docker build -t gh-media-downloader-ui .
```

Run the container:
```bash
docker run --rm -p 10001:10001 gh-media-downloader-ui
```

Then open your browser at:
```
http://localhost:10001/
```

---

## 🧑‍💻 Usage

1. Paste a video URL from YouTube or X (Twitter)
2. If it's a YouTube link, choose between **mp4** or **mp3**
3. Click **Start Download**
4. The file will be streamed directly to your browser

---

## 🛠️ Built With

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- Python 3.11+
- HTML + JavaScript (no frameworks)
- Docker (optional but recommended)

---

## 📝 License

This project is licensed under the [MIT License](LICENSE).

---