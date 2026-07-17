"""
Chunked long-form transcription.

Gemini cannot transcribe multi-hour audio in one request — it returns almost
nothing (e.g. 4 lines for a 5-hour recording). So we split the audio into
fixed-length chunks, transcribe each chunk fully with Gemini, force-align each
chunk to its own audio (accurate timestamps), offset every cue by the chunk's
start time, and stitch the results into one SRT.

If alignment fails for a chunk, that chunk falls back to Gemini's own (rougher,
but chunk-local) timestamps — still offset correctly by the chunk start.
"""
from __future__ import annotations
import os
import glob
import shutil
import logging
import subprocess
import tempfile
from typing import Callable

from app.core.config import settings
from app.services.downloader.binary_finder import find_ffmpeg
from app.services.transcriber.caption_generator import get_caption_cues, to_srt
from app.services.aligner.aeneas_aligner import align_fragments_to_cues

logger = logging.getLogger(__name__)


def generate_chunked_aligned_srt(
    file_path: str,
    chunk_seconds: int | None = None,
    language: str = "eng",
    log: Callable[[str], None] | None = None,
) -> str:
    """Transcribe `file_path` chunk-by-chunk and return one stitched SRT."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for chunked transcription")
    chunk_seconds = chunk_seconds or settings.TRANSCRIBE_CHUNK_MINUTES * 60

    tmp = tempfile.mkdtemp(prefix="transcript_chunks_")
    try:
        chunks = _split_audio(ffmpeg, file_path, chunk_seconds, tmp, log)
        _log(log, f"Split into {len(chunks)} chunk(s) of ~{chunk_seconds // 60} min.")

        all_cues: list[dict] = []
        offset = 0.0
        for i, chunk in enumerate(chunks, 1):
            duration = _duration(ffmpeg, chunk) or chunk_seconds
            _log(log, f"Chunk {i}/{len(chunks)} [{_hms(offset)}–{_hms(offset + duration)}]: transcribing...")

            cues = get_caption_cues(chunk, log=log)
            fragments = [c["text"] for c in cues if c["text"].strip()]
            if fragments:
                try:
                    aligned = align_fragments_to_cues(chunk, fragments, language=language, log=log)
                except Exception as exc:
                    logger.warning("Alignment failed on chunk %d (%s); using Gemini times", i, exc)
                    _log(log, f"Chunk {i}: alignment failed, using Gemini timestamps for this chunk.")
                    aligned = [{"start": c["start"], "end": c["end"], "text": c["text"]} for c in cues]
                for c in aligned:
                    all_cues.append({
                        "start": c["start"] + offset,
                        "end": c["end"] + offset,
                        "text": c["text"],
                        "speaker": "",
                    })
                _log(log, f"Chunk {i}: {len(aligned)} lines.")
            else:
                _log(log, f"Chunk {i}: no speech.")

            offset += duration

        if not all_cues:
            raise RuntimeError("No speech was transcribed from any chunk")
        _log(log, f"Stitched {len(all_cues)} lines across {len(chunks)} chunks.")
        return to_srt(all_cues)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _split_audio(ffmpeg: str, file_path: str, chunk_seconds: int, out_dir: str, log) -> list[str]:
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


def _duration(ffmpeg: str, path: str) -> float | None:
    d = os.path.dirname(ffmpeg)
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


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _log(log: Callable[[str], None] | None, msg: str) -> None:
    logger.info(msg)
    if log:
        log(msg)
