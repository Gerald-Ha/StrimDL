# StrimDL Version 3.0.5

<img src="https://github.com/user-attachments/assets/a5c797b8-5ea2-44d3-a2fd-1fd24dbfad43" width="600" height="auto">
&nbsp;

A simple, modern web interface to download media from **YouTube** and **X (formerly Twitter)** using [yt-dlp](https://github.com/yt-dlp/yt-dlp) and Python.

Supports direct downloads as:

* 🎬 **YouTube videos (.mp4)**
* 🎵 **YouTube audio (.mp3)**
* 📥 **Twitter/X videos** (as `.mp4`)

---

## 🚀 Features

* 🎯 Clean and responsive dark UI
* 🔐 **Login Authentication**: Optional authentication to restrict access (default username `admin` / password `admin`)
* 🔎 Automatic YouTube title as filename
* 🧠 Smart MP4/MP3 selection (only enabled for YouTube)
* ⚡️ No persistent storage required (downloads stream to browser)
* 🐳 Easy deployment via Docker & Docker Compose
* ⚙️ Customizable download path and filename patterns

---

## 📦 Installation

1. Clone this repository:

   ```bash
   git clone https://github.com/<your-username>/strimdl.git
   cd strimdl
   ```

2. Copy the example environment file and configure your settings:

   ```bash
   cp .env.example .env
   ```

3. Edit the `.env` file and set:

   ```dotenv
   DOWNLOAD_PATH=/path/to/your/downloads
   TZ=Europe/Berlin
   LANG=en_US.UTF-8
   VIDEO_NAMING_PATTERN={userId}@twitter-{tweetId}
   IMAGE_NAMING_PATTERN={userId}@twitter-{tweetId}
   STRIMDL_USER=admin
   STRIMDL_PASS=admin
   YTDLP_COOKIES_DIR=./cookies
   YTDLP_COOKIES_PATH=/cookies/youtube.txt
   YTDLP_UPDATE_ON_START=true
   STRIMDL_UPDATE_DEVMODE=false
   STRIMDL_UPDATE_SERVER_URL=https://update.gerald-hasani.com
   FFMPEG_VIDEO_PRESET=veryfast
   FFMPEG_VIDEO_CRF=24
   FFMPEG_MAX_HEIGHT=1440
   ```

   > **Note:** By default, login is required with username `admin` and password `admin`. Change `STRIMDL_USER` and `STRIMDL_PASS` to secure your instance.
   > If YouTube asks yt-dlp to confirm you are not a bot, export browser cookies to `./cookies/youtube.txt` and keep `YTDLP_COOKIES_PATH=/cookies/youtube.txt`.

4. Start via Docker Compose:

   ```bash
   docker compose up -d --build
   ```

   Or build and run with Docker:

   ```bash
   docker build -t strimdl .
   docker run --rm -p 10001:10001 --env-file .env -v ${DOWNLOAD_PATH}:/download strimdl
   ```

5. Open your browser and go to:

   ```
   http://localhost:10001/
   ```

---

## 🧑‍💻 Usage

1. Access the login page if prompted.
2. Log in with your credentials.
3. Paste a YouTube or X (Twitter) URL.
4. Choose format and quality (for YouTube).
5. Click **Start Download**.

---

## StrimDL Update Check

StrimDL checks Gerald Hasani's Update Center once per day and shows a notice in the web UI when a new version is available.

For testing, enable dev mode to check every 3 minutes:

```dotenv
STRIMDL_UPDATE_DEVMODE=true
```

The public StrimDL Update Center API key is built into the app.

---

## Conversion Performance

YouTube often serves high resolutions as AV1 or VP9. For browser-compatible MP4 output StrimDL re-encodes those videos to H.264, and 1440p/2160p re-encoding can take several minutes.

These `.env` values control that conversion:

```dotenv
FFMPEG_VIDEO_PRESET=veryfast
FFMPEG_VIDEO_CRF=24
FFMPEG_MAX_HEIGHT=1440
```

`FFMPEG_VIDEO_PRESET` controls speed. Use `ultrafast` for faster but larger files, `veryfast` as a good default, or `medium` for smaller files at the cost of time.

`FFMPEG_VIDEO_CRF` controls quality/size. Lower values look better and create larger files. Common values are `23` to `26`.

`FFMPEG_MAX_HEIGHT` caps the output height during re-encoding. The default `1440` prevents very slow 2160p conversions. Set it to `0` if you want to keep the source height.

---

## YouTube Cookies

If YouTube returns `Sign in to confirm you’re not a bot`, yt-dlp needs browser cookies from a signed-in browser session.

1. Create a local cookies directory:

   ```bash
   mkdir -p cookies
   ```

2. Export YouTube cookies in Netscape `cookies.txt` format and save them as:

   ```text
   ./cookies/youtube.txt
   ```

3. Set these values in `.env`:

   ```dotenv
   YTDLP_COOKIES_DIR=./cookies
   YTDLP_COOKIES_PATH=/cookies/youtube.txt
   YTDLP_UPDATE_ON_START=true
   ```

4. Recreate the container:

   ```bash
   docker compose up -d --build
   ```

Keep the cookie file private. It can grant access to your browser session.

`YTDLP_UPDATE_ON_START=true` checks for the latest stable yt-dlp release whenever the container starts. This avoids stale Docker build-cache layers after YouTube changes.

---

## 🛠️ Built With

* [yt-dlp](https://github.com/yt-dlp/yt-dlp)
* Python 3.11+
* HTML & JavaScript (no frameworks)
* Docker & Docker Compose

---

## 📄 Change Log

* **v3.0.5**
- Added update server integration to notify users when a new version is available.
- Changed the main action button to show a red `Cancel` state while a download or conversion is running.
- Added a visible activity indicator with elapsed time during long-running download/conversion steps.
- Made ffmpeg conversion behavior configurable through `.env`.
- Improved conversion performance defaults for AV1/VP9 YouTube videos:
  - `FFMPEG_VIDEO_PRESET=veryfast`
  - `FFMPEG_VIDEO_CRF=24`
  - `FFMPEG_MAX_HEIGHT=1440`
- Avoided unnecessary re-encoding when the cached video can be copied directly.
- Cleaned up partial cache files after cancelled downloads.
- Updated StrimDL version to `3.0.5`.
- Centralized version display so the footer reads from backend `APP_VERSION` instead of hardcoding the version in `index.html`.
- Rebuilt and smoke-tested the Docker container.

* **v3.0.1** 
– Switched audio download from CBR/ABR to VBR (Variable Bitrate), providing significantly better quality and bitrate as it always selects the best available quality during download. Improved UI with custom dropdown for format selection, real-time status updates via Server-Side Events (SSE), playlist link detection, and enhanced spacing between UI elements.
YouTube downloads are working again after they stopped working following the update on the YouTube platform.

* **v2.0.0** 
– Added login authentication, improved Docker support, updated UI and README.

---

## 📝 License

This project is licensed under the [MIT License](LICENSE).
