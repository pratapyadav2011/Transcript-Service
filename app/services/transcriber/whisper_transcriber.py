"""CPU/GPU local transcription with faster-whisper and word-level SRT timing."""
from __future__ import annotations

import logging
import os
from typing import Callable

from app.core.config import settings
from app.services.transcriber.whisper_srt_formatter import segments_to_srt

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
    pipeline = _load_pipeline()
    _log(
        log,
        f"Running local Whisper model {settings.WHISPER_MODEL} "
        f"({settings.WHISPER_DEVICE} {settings.WHISPER_COMPUTE_TYPE})...",
    )
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
    _log(log, f"Whisper detected {info.language}; formatting {len(segments)} segments as SRT...")
    result = segments_to_srt(segments)
    _log(log, f"Local Whisper produced {result.count('-->')} caption cues.")
    return result


def _log(callback, message: str) -> None:
    logger.info(message)
    if callback:
        callback(message)
