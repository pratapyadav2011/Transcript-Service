import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    MONGODB_URI: str = os.getenv("MONGODB_URI", "")

    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")

    # Max upload size — default 2 GB
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))

    # How many log lines to keep per job in Redis
    MAX_LOG_ENTRIES: int = 500

    # Job result TTL in Redis — 7 days
    RESULT_TTL_SECONDS: int = 7 * 24 * 3600

    # Optional binary overrides
    YTDLP_PATH: str = os.getenv("YTDLP_PATH", "")
    FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "")

    # Optional HTTP/SOCKS proxy for yt-dlp subtitle fetches. Leave empty to fetch
    # directly; set it only when a media CDN blocks the server's IP.
    MEDIA_PROXY_URL: str = os.getenv("MEDIA_PROXY_URL", "")

    # Keep the downloaded audio after a successful job so the transcription step
    # can be rerun (e.g. to verify prompt/alignment changes) without downloading
    # the media again. Uses disk under UPLOAD_DIR/retry-cache; set to "false" to
    # disable if disk is tight.
    KEEP_AUDIO_FOR_RERUN: bool = os.getenv("KEEP_AUDIO_FOR_RERUN", "true").lower() == "true"

    # API key for Next.js → Python service calls
    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "")


settings = Settings()
