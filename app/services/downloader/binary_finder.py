"""Locates yt-dlp and ffmpeg binaries on the system."""
from __future__ import annotations
import os
import shutil
import subprocess
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


def find_ytdlp() -> str | None:
    candidates = [
        settings.YTDLP_PATH,
        shutil.which("yt-dlp"),
        "/usr/local/bin/yt-dlp",
        "/usr/bin/yt-dlp",
        "/opt/homebrew/bin/yt-dlp",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            logger.info("yt-dlp found at: %s", path)
            return path
    logger.warning("yt-dlp not found on this system")
    return None


def find_ffmpeg() -> str | None:
    candidates = [
        settings.FFMPEG_PATH,
        shutil.which("ffmpeg"),
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            # Quick canary check
            try:
                result = subprocess.run(
                    [path, "-version"], capture_output=True, timeout=5
                )
                if result.returncode == 0:
                    logger.info("ffmpeg found at: %s", path)
                    return path
            except Exception:
                continue
    logger.warning("ffmpeg not found on this system")
    return None
