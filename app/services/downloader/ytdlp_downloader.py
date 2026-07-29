"""Downloads audio from any URL using yt-dlp."""
from __future__ import annotations
import os
import subprocess
import logging
import tempfile
from collections import deque
from typing import Callable

from app.core.config import settings
from app.services.downloader.binary_finder import find_ffmpeg

logger = logging.getLogger(__name__)

# Prefer a separate audio-only stream when the site offers one (e.g. YouTube).
# For progressive files (Granicus/CivicClerk mp4) there is no audio-only stream,
# so we fall back to `best` and strip the video with ffmpeg below.
FORMAT_SELECTOR = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
AUDIO_FORMAT = "mp3"


def download_audio(
    binary: str,
    url: str,
    progress_callback: Callable[[str], None] | None = None,
) -> str:
    """
    Download a URL and return the path to an AUDIO-ONLY file.
    yt-dlp extracts the audio track (via ffmpeg) so we never keep or upload the
    video. Caller is responsible for cleanup.
    """
    tmp_dir = tempfile.mkdtemp(prefix="transcript_ytdlp_")
    output_template = os.path.join(tmp_dir, "audio.%(ext)s")

    args = [
        binary,
        "--js-runtimes", "node",
        "--format", FORMAT_SELECTOR,
        "--extract-audio",                 # strip video → audio only
        "--audio-format", AUDIO_FORMAT,
        "--audio-quality", "5",            # ~128 kbps VBR — plenty for speech
        "--no-playlist",
        "--no-warnings",
        "--newline",           # one progress line per update (easier to parse)
        "--output", output_template,
        url,
    ]

    # yt-dlp needs ffmpeg for audio extraction; point it at ours if known.
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        args[1:1] = ["--ffmpeg-location", ffmpeg]

    # Prefer YouTube player clients that usually dodge the PO-token / bot wall that
    # the default web client hits from datacenter IPs. Namespaced to the youtube
    # extractor, so it's a harmless no-op for other sites.
    if settings.YTDLP_PLAYER_CLIENT:
        args[1:1] = [
            "--extractor-args",
            f"youtube:player_client={settings.YTDLP_PLAYER_CLIENT}",
        ]

    # YouTube blocks datacenter/VM IPs ("confirm you're not a bot"). Cookies (from a
    # file or a local browser) and/or a residential proxy get past it. A cookies
    # file wins over browser extraction when both are set.
    if settings.YTDLP_COOKIES_FILE:
        if not os.path.isfile(settings.YTDLP_COOKIES_FILE):
            raise RuntimeError(
                "YTDLP_COOKIES_FILE is configured but is not readable inside "
                f"the worker container: {settings.YTDLP_COOKIES_FILE}"
            )
        args[1:1] = ["--cookies", settings.YTDLP_COOKIES_FILE]
    elif settings.YTDLP_COOKIES_FROM_BROWSER:
        args[1:1] = ["--cookies-from-browser", settings.YTDLP_COOKIES_FROM_BROWSER]
    if settings.MEDIA_PROXY_URL:
        args[1:1] = ["--proxy", settings.MEDIA_PROXY_URL]

    if progress_callback:
        progress_callback(f"Running yt-dlp on: {url}")

    logger.info("yt-dlp cmd: %s", " ".join(args))

    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Keep the last few non-progress lines so a failure can report the real cause
    # (e.g. "HTTP Error 403", "fragment not found") instead of just "exit code 1".
    tail: deque[str] = deque(maxlen=12)
    for line in process.stdout:
        line = line.rstrip()
        if line:
            logger.debug("yt-dlp: %s", line)
            if not line.startswith("[download]"):
                tail.append(line)
            if progress_callback and ("[download]" in line or "[info]" in line):
                progress_callback(line)

    process.wait()
    if process.returncode != 0:
        reason = " | ".join(l for l in tail if "ERROR" in l or "WARNING" in l) or " / ".join(tail)
        # YouTube's bot wall surfaces as a "confirm you're not a bot" /
        # "Requested format is not available" pair (the latter is downstream — no
        # formats get extracted). Point the operator at the real remedy instead of
        # a cryptic exit code + format error.
        lowered = reason.lower()
        if "not a bot" in lowered or "sign in to confirm" in lowered or (
            "requested format is not available" in lowered
            and not settings.YTDLP_COOKIES_FILE
            and not settings.YTDLP_COOKIES_FROM_BROWSER
        ):
            raise RuntimeError(
                "yt-dlp was blocked by YouTube's bot check (datacenter/VM IP). "
                "Set YTDLP_COOKIES_FILE (or YTDLP_COOKIES_FROM_BROWSER) from a "
                "logged-in account, add MEDIA_PROXY_URL (residential), and update "
                f"yt-dlp. Details: {reason[:300]}"
            )
        raise RuntimeError(f"yt-dlp exited with code {process.returncode}: {reason[:400]}")

    # Find the produced file — prefer the extracted audio over any leftover.
    files = [f for f in os.listdir(tmp_dir) if f.startswith("audio.")]
    if not files:
        raise RuntimeError("yt-dlp did not produce an audio file")
    files.sort(key=lambda f: 0 if f.endswith(f".{AUDIO_FORMAT}") else 1)

    return os.path.join(tmp_dir, files[0])
