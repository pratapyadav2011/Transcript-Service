"""Extracts audio from a video file or HLS stream using ffmpeg."""
from __future__ import annotations
import os
import subprocess
import logging
import tempfile
from typing import Callable

logger = logging.getLogger(__name__)


def extract_audio(
    binary: str,
    source: str,
    progress_callback: Callable[[str], None] | None = None,
) -> str:
    """
    Extract audio track to a temp MP3 file.
    `source` can be a local file path or an HLS/HTTPS URL.
    Returns the path to the extracted audio file.
    """
    tmp_dir = tempfile.mkdtemp(prefix="transcript_ffmpeg_")
    output_path = os.path.join(tmp_dir, "audio.mp3")

    args = [
        binary,
        "-i", source,
        "-vn",                    # no video
        "-acodec", "libmp3lame",
        "-q:a", "4",              # VBR quality ~165 kbps
        "-y",                     # overwrite without asking
        output_path,
    ]

    if progress_callback:
        progress_callback(f"Extracting audio with ffmpeg from: {os.path.basename(source)}")

    logger.info("ffmpeg cmd: %s", " ".join(args))

    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    for line in process.stdout:
        line = line.rstrip()
        if line:
            logger.debug("ffmpeg: %s", line)
            if progress_callback and ("time=" in line or "size=" in line):
                progress_callback(f"ffmpeg: {line}")

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg exited with code {process.returncode}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("ffmpeg produced no output audio file")

    return output_path


def extract_audio_from_upload(binary: str, file_path: str) -> str:
    """Convenience wrapper for uploaded video files."""
    return extract_audio(binary, file_path)
