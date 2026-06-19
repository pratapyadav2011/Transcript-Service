"""Downloads audio from any URL using yt-dlp."""
from __future__ import annotations
import os
import subprocess
import logging
import tempfile
from typing import Callable

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

    if progress_callback:
        progress_callback(f"Running yt-dlp on: {url}")

    logger.info("yt-dlp cmd: %s", " ".join(args))

    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    for line in process.stdout:
        line = line.rstrip()
        if line:
            logger.debug("yt-dlp: %s", line)
            if progress_callback and ("[download]" in line or "[info]" in line):
                progress_callback(line)

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"yt-dlp exited with code {process.returncode} for {url}")

    # Find the produced file — prefer the extracted audio over any leftover.
    files = [f for f in os.listdir(tmp_dir) if f.startswith("audio.")]
    if not files:
        raise RuntimeError("yt-dlp did not produce an audio file")
    files.sort(key=lambda f: 0 if f.endswith(f".{AUDIO_FORMAT}") else 1)

    return os.path.join(tmp_dir, files[0])
