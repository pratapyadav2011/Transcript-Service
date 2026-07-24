from __future__ import annotations

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

    # Long audio is split into chunks of this many minutes before transcription —
    # Gemini can't transcribe multi-hour audio in one request. Each chunk is
    # transcribed and force-aligned independently, then stitched with its offset.
    TRANSCRIBE_CHUNK_MINUTES: int = int(os.getenv("TRANSCRIBE_CHUNK_MINUTES", "30"))

    # Transcription backend. Supported values: gemini, whisper,
    # whisper_gemini_fallback. Whisper is CPU-only by default.
    TRANSCRIPTION_ENGINE: str = os.getenv("TRANSCRIPTION_ENGINE", "whisper").lower()
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small.en")
    WHISPER_DEVICE: str = os.getenv("WHISPER_DEVICE", "cpu")
    WHISPER_COMPUTE_TYPE: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    WHISPER_CPU_THREADS: int = int(os.getenv("WHISPER_CPU_THREADS", "8"))
    WHISPER_BATCH_SIZE: int = int(os.getenv("WHISPER_BATCH_SIZE", "8"))
    WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
    WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "en")
    WHISPER_MODEL_DIR: str = os.getenv("WHISPER_MODEL_DIR", "/models/whisper")
    WHISPER_INITIAL_PROMPT: str = os.getenv("WHISPER_INITIAL_PROMPT", "")

    # API key for Next.js → Python service calls
    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "")


settings = Settings()


def transcription_queue(engine: str | None = None) -> str | None:
    """Route local-ASR jobs to the dedicated single-concurrency CPU worker."""
    selected = engine or settings.TRANSCRIPTION_ENGINE
    if selected in {"whisper", "whisper_gemini_fallback"}:
        return "whisper"
    return None
