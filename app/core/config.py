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

    # Optional HTTP/SOCKS proxy for yt-dlp (subtitle fetches AND audio download).
    # Leave empty to fetch directly; set it when a CDN/YouTube blocks the server IP.
    MEDIA_PROXY_URL: str = os.getenv("MEDIA_PROXY_URL", "")

    # Path to a Netscape-format cookies.txt exported from a browser logged in to
    # YouTube. Required because YouTube blocks datacenter/VM IPs with "Sign in to
    # confirm you're not a bot". Point this at a file on a mounted volume.
    YTDLP_COOKIES_FILE: str = os.getenv("YTDLP_COOKIES_FILE", "")

    # Alternative to a cookies file: pull cookies straight from a locally installed
    # browser, e.g. "chrome", "firefox", or "firefox:/path/to/profile". Only works
    # if that browser profile lives on the same host as the worker. Ignored when
    # YTDLP_COOKIES_FILE is set (a file takes precedence).
    YTDLP_COOKIES_FROM_BROWSER: str = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "")

    # yt-dlp YouTube player clients to try, passed as
    # --extractor-args "youtube:player_client=<value>". yt-dlp aggregates formats
    # across the listed clients: `default` keeps the audio-only DASH streams (best
    # for speech), while tv / web_safari / mweb are fallbacks that often dodge the
    # PO-token + bot wall the web client hits from datacenter IPs. Order matters —
    # keep `default` first so audio-only formats stay preferred when it works.
    # Comma-separated. Empty = leave yt-dlp's own default.
    YTDLP_PLAYER_CLIENT: str = os.getenv(
        "YTDLP_PLAYER_CLIENT", "default,tv,web_safari,mweb"
    )

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
    # Peak RAM scales with batch size. On CPU int8 a larger batch mostly trades
    # memory for a little throughput, and multi-hour audio + word timestamps can
    # OOM-kill the worker. Keep this modest; raise only if the box has headroom.
    WHISPER_BATCH_SIZE: int = int(os.getenv("WHISPER_BATCH_SIZE", "4"))
    WHISPER_BEAM_SIZE: int = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
    WHISPER_LANGUAGE: str = os.getenv("WHISPER_LANGUAGE", "en")
    WHISPER_MODEL_DIR: str = os.getenv("WHISPER_MODEL_DIR", "/models/whisper")
    WHISPER_INITIAL_PROMPT: str = os.getenv("WHISPER_INITIAL_PROMPT", "")

    # Give up on a task after this many broker deliveries. task_acks_late means a
    # worker killed mid-task (e.g. OOM SIGKILL) has its message redelivered and the
    # job restarts from scratch; without a cap a deterministic crash loops forever.
    # 2 tolerates one benign worker loss (deploy/restart) before failing the job.
    MAX_TASK_DELIVERIES: int = int(os.getenv("MAX_TASK_DELIVERIES", "2"))

    # Recycle a worker child once its resident memory exceeds this (MB) — a
    # belt-and-suspenders guard against gradual leaks across tasks. 0 disables.
    # It does NOT stop a single task from OOMing; the delivery cap handles that.
    WORKER_MAX_MEMORY_MB: int = int(os.getenv("WORKER_MAX_MEMORY_MB", "0"))

    # Master switch for the auth middleware. Disable only for trusted/local use.
    AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "true").lower() in {
        "1", "true", "yes", "on",
    }

    # Shared secret for Next.js → Python service calls. Keep the old environment
    # name as a migration fallback so existing deployments do not lock users out.
    TRANSCRIPT_SECRET_KEY: str = (
        os.getenv("TRANSCRIPT_SECRET_KEY", "") or os.getenv("API_SECRET_KEY", "")
    )


settings = Settings()


def transcription_queue(engine: str | None = None) -> str | None:
    """Route local-ASR jobs to the dedicated single-concurrency CPU worker."""
    selected = engine or settings.TRANSCRIPTION_ENGINE
    if selected in {"whisper", "whisper_gemini_fallback"}:
        return "whisper"
    return None
