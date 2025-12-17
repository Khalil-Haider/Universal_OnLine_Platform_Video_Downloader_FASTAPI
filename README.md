# Universal Video Downloader API

A powerful, production-ready FastAPI application for downloading videos from **YouTube, Instagram, TikTok**, and Facebook platforms using `yt-dlp`.

## 🚀 Features

- **Universal Support**: Downloads from YouTube, Instagram (Reels/Posts), TikTok, Twitter/X, Facebook, and more.
- **Smart Format Detection**: Automatically picks the best video/audio quality.
- **Audio Extraction**: Convert any video to high-quality MP3 (320kbps).
- **Metadata**: Fetches detailed info like resolution, codec, duration, and file size.
- **Robustness**: Handles "None" values and edge cases gracefully (especially for Instagram).

## 🛠️ Installation

1.  **Clone the repository** (or download the files):
    ```bash
    git clone https://github.com/Khalil-Haider/Universal_OnLine_Platform_Video_Downloader_FASTAPI.git
    cd Universal_OnLine_Platform_Video_Downloader_FASTAPI
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Install FFmpeg**:
    - This project requires FFmpeg for audio conversion and video merging.
    - **Windows**: Download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), extract, and add the `bin` folder to your System PATH.
    - **Linux**: `sudo apt install ffmpeg`
    - **macOS**: `brew install ffmpeg`

## ▶️ Usage

1.  **Start the Server**:
    ```bash
    uvicorn main:app --reload
    ```

2.  **Access Documentation**:
    Open your browser to **http://localhost:8000/docs**.
    You will see the interactive Swagger UI where you can test the endpoints directly.

3.  **API Endpoints**:
    - `POST /formats`: Get a list of available formats for a URL.
    - `POST /download`: Download a specific format or let the system choose the best one.

