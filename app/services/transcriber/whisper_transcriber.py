"""CPU/GPU local transcription with faster-whisper and word-level SRT timing."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Callable

from app.core.config import settings
from app.services.transcriber.audio_chunking import split_audio, probe_duration, hms
from app.services.transcriber.whisper_srt_formatter import (
    segments_to_srt, words_to_srt, timed_words_from_segments,
)

logger = logging.getLogger(__name__)
_model = None
_pipeline = None


def _load_pipeline():
    global _model, _pipeline
    if _pipeline is not None:
        return _pipeline

    from faster_whisper import BatchedInferencePipeline, WhisperModel

    os.makedirs(settings.WHISPER_MODEL_DIR, exist_ok=True)
    logger.info(
        "Loading faster-whisper model=%s device=%s compute=%s threads=%d",
        settings.WHISPER_MODEL, settings.WHISPER_DEVICE,
        settings.WHISPER_COMPUTE_TYPE, settings.WHISPER_CPU_THREADS,
    )
    _model = WhisperModel(
        settings.WHISPER_MODEL,
        device=settings.WHISPER_DEVICE,
        compute_type=settings.WHISPER_COMPUTE_TYPE,
        cpu_threads=settings.WHISPER_CPU_THREADS,
        num_workers=1,
        download_root=settings.WHISPER_MODEL_DIR,
    )
    _pipeline = BatchedInferencePipeline(model=_model)
    return _pipeline


def transcribe_to_srt(
    file_path: str,
    log: Callable[[str], None] | None = None,
) -> str:
    """Transcribe `file_path` to SRT. faster-whisper decodes the whole file into
    RAM before inference, so multi-hour audio is split into chunks and stitched —
    otherwise the worker OOMs. Short audio takes the single-pass route unchanged."""
    _log(
        log,
        f"Running local Whisper model {settings.WHISPER_MODEL} "
        f"({settings.WHISPER_DEVICE} {settings.WHISPER_COMPUTE_TYPE})...",
    )
    chunk_seconds = max(0, settings.TRANSCRIBE_CHUNK_MINUTES) * 60
    duration = probe_duration(file_path) or 0.0
    # Only chunk when clearly long, so typical short files keep the exact
    # single-pass behavior (and cross-chunk boundary effects are avoided).
    if chunk_seconds and duration > chunk_seconds * 1.5:
        return _transcribe_chunked(file_path, chunk_seconds, duration, log)

    segments = _transcribe_segments(file_path, log)
    result = segments_to_srt(segments)
    _log(log, f"Local Whisper produced {result.count('-->')} caption cues.")
    return result


def _transcribe_segments(file_path: str, log: Callable[[str], None] | None) -> list:
    """Run the model on one file and return its materialized segment list."""
    pipeline = _load_pipeline()
    kwargs = dict(
        language=settings.WHISPER_LANGUAGE or None,
        batch_size=settings.WHISPER_BATCH_SIZE,
        beam_size=settings.WHISPER_BEAM_SIZE,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    if settings.WHISPER_INITIAL_PROMPT:
        kwargs["initial_prompt"] = settings.WHISPER_INITIAL_PROMPT

    segment_stream, info = pipeline.transcribe(file_path, **kwargs)
    segments = []
    next_progress = 300.0
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    for segment in segment_stream:
        segments.append(segment)
        position = float(getattr(segment, "end", 0.0) or 0.0)
        if position >= next_progress:
            if duration:
                _log(log, f"Whisper progress: {position / 60:.0f}/{duration / 60:.0f} minutes")
            else:
                _log(log, f"Whisper processed {position / 60:.0f} minutes of audio")
            next_progress += 300.0
    _log(log, f"Whisper detected {info.language}; {len(segments)} segments.")
    return segments


def _transcribe_chunked(
    file_path: str,
    chunk_seconds: int,
    total_duration: float,
    log: Callable[[str], None] | None,
) -> str:
    """Split long audio, transcribe each chunk (bounding peak RAM to one chunk),
    offset each chunk's words by its start time, and stitch into one SRT."""
    tmp = tempfile.mkdtemp(prefix="whisper_chunks_")
    try:
        chunks = split_audio(file_path, chunk_seconds, tmp, log)
        _log(
            log,
            f"Long audio ({total_duration / 60:.0f} min): transcribing in "
            f"{len(chunks)} chunk(s) of ~{chunk_seconds // 60} min to bound memory.",
        )
        all_words = []
        offset = 0.0
        for i, chunk in enumerate(chunks, 1):
            chunk_duration = probe_duration(chunk) or float(chunk_seconds)
            _log(
                log,
                f"Chunk {i}/{len(chunks)} [{hms(offset)}–{hms(offset + chunk_duration)}]: "
                "transcribing...",
            )
            segments = _transcribe_segments(chunk, log)
            all_words.extend(timed_words_from_segments(segments, offset=offset))
            del segments  # release the chunk's segments before decoding the next
            offset += chunk_duration
        if not all_words:
            raise RuntimeError("Whisper produced no words from any chunk")
        _log(log, f"Stitching {len(all_words)} words across {len(chunks)} chunks into SRT...")
        result = words_to_srt(all_words)
        _log(log, f"Local Whisper produced {result.count('-->')} caption cues.")
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _log(callback, message: str) -> None:
    logger.info(message)
    if callback:
        callback(message)
