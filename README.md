# StrimDL

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
   ```

   > **Note:** By default, login is required with username `admin` and password `admin`. Change `STRIMDL_USER` and `STRIMDL_PASS` to secure your instance.

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

## 🛠️ Built With

* [yt-dlp](https://github.com/yt-dlp/yt-dlp)
* Python 3.11+
* HTML & JavaScript (no frameworks)
* Docker & Docker Compose

---

## 📄 Change Log

* **v3.0.1** – Switched audio download from CBR/ABR to VBR (Variable Bitrate), providing significantly better quality and bitrate as it always selects the best available quality during download. Improved UI with custom dropdown for format selection, real-time status updates via Server-Side Events (SSE), playlist link detection, and enhanced spacing between UI elements.
YouTube downloads are working again after they stopped working following the update on the YouTube platform.

* **v2.0.0** – Added login authentication, improved Docker support, updated UI and README.

---

## 📝 License

This project is licensed under the [MIT License](LICENSE).
