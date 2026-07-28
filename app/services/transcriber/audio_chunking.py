"""Split long audio into fixed-length chunks with ffmpeg.

Shared by both chunked transcription paths: Gemini (which can't transcribe
multi-hour audio in one request) and local Whisper (which decodes the whole file
into RAM up front and OOMs on multi-hour audio). Each chunk is transcribed
independently and its timestamps are offset by the chunk's start.
"""
from __future__ import annotations
import glob
import logging
import os
import subprocess
from typing import Callable

from app.services.downloader.binary_finder import find_ffmpeg

logger = logging.getLogger(__name__)


def split_audio(
    file_path: str,
    chunk_seconds: int,
    out_dir: str,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    """Segment `file_path` into ~`chunk_seconds` mp3 chunks under `out_dir`."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for chunked transcription")
    pattern = os.path.join(out_dir, "chunk_%04d.mp3")
    _log(log, f"Splitting audio into {chunk_seconds // 60}-minute chunks...")
    proc = subprocess.run(
        [
            ffmpeg, "-i", file_path, "-vn",
            "-f", "segment", "-segment_time", str(chunk_seconds),
            "-c", "copy", "-y", pattern,
        ],
        capture_output=True, text=True, timeout=3600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Audio splitting failed: {(proc.stderr or '')[-400:]}")
    chunks = sorted(glob.glob(os.path.join(out_dir, "chunk_*.mp3")))
    if not chunks:
        raise RuntimeError("Audio splitting produced no chunks")
    return chunks


def probe_duration(path: str) -> float | None:
    """Return the media duration in seconds via ffprobe, or None if unavailable."""
    ffmpeg = find_ffmpeg()
    d = os.path.dirname(ffmpeg) if ffmpeg else ""
    ffprobe = os.path.join(d, "ffprobe") if d else "ffprobe"
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _log(log: Callable[[str], None] | None, msg: str) -> None:
    logger.info(msg)
    if log:
        log(msg)
