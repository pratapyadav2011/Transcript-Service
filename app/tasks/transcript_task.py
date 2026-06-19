"""
Celery tasks for transcript generation.

Each step emits a step-log to Redis (job_store) and calls `checkpoint()` so the
job can be paused or stopped between steps. MongoDB side-effects are delegated
to `hooks`, keeping this module small and single-purpose.
"""
from __future__ import annotations
import os
import logging
from celery import Task

from app.core.celery_app import celery_app
from app.core.job_store import (
    set_job_done, set_job_failed, set_job_stopped, clear_control, set_transcript_id,
    STEP_RESOLVING, STEP_FOUND, STEP_DOWNLOADING,
    STEP_EXTRACTING, STEP_UPLOADING, STEP_TRANSCRIBING, STEP_SAVING, STEP_FAILED,
)
from app.tasks.control import checkpoint, make_logger, StopRequested
from app.tasks import hooks
from app.services.resolver.media_resolver import resolve_candidates
from app.services.resolver.url_classifier import is_direct_media_url, is_youtube_url
from app.services.transcriber.youtube_captions import fetch_captions
from app.services.downloader.audio_pipeline import acquire_audio, cleanup
from app.services.downloader.ffmpeg_extractor import extract_audio_from_upload
from app.services.downloader.binary_finder import find_ffmpeg
from app.services.transcriber.gemini_transcriber import transcribe_file, transcribe_media_url
from app.services.transcriber.mime_types import ext_to_mime

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="transcript.from_url", max_retries=0)
def transcribe_url_task(
    self: Task,
    job_id: str,
    url: str,
    meeting_id: str = "",
    actor: str = "system",
) -> dict:
    """Process a video URL end-to-end: resolve → download → transcribe → save."""
    log = make_logger(job_id, logger)
    audio_path: str | None = None
    try:
        transcript_id = _begin(job_id, meeting_id)

        checkpoint(job_id)
        log(STEP_RESOLVING, f"Searching for video at: {url}")
        candidates = resolve_candidates(url)
        log(STEP_FOUND, f"Found {len(candidates)} media candidate(s): {candidates[0]}")

        # Fast-path: reuse existing YouTube captions instead of audio + Gemini.
        checkpoint(job_id)
        if is_youtube_url(url):
            captions = _try_captions(job_id, log, url, meeting_id, transcript_id, actor)
            if captions is not None:
                return captions

        checkpoint(job_id)
        log(STEP_DOWNLOADING, "Downloading / extracting audio...")
        try:
            audio_path = acquire_audio(
                candidates=candidates,
                original_url=url,
                log=lambda msg: log(STEP_DOWNLOADING, msg),
            )
        except Exception as exc:
            remote_result = _try_remote_media_transcription(
                job_id, log, candidates, url, meeting_id, transcript_id, actor, exc
            )
            if remote_result is not None:
                return remote_result
            raise
        size_mb = os.path.getsize(audio_path) / 1024 / 1024
        log(STEP_EXTRACTING, f"Audio ready: {os.path.basename(audio_path)} ({size_mb:.1f} MB)")

        checkpoint(job_id)
        transcript = _transcribe(job_id, log, audio_path)

        log(STEP_SAVING, f"Saving transcript ({len(transcript)} chars)...")
        hooks.on_success(meeting_id, transcript_id, transcript, actor, source_label=url)
        set_job_done(job_id, transcript)
        return {"status": "done", "transcript": transcript}

    except StopRequested:
        set_job_stopped(job_id)
        hooks.on_stopped(meeting_id, actor)
        return {"status": "stopped"}
    except Exception as exc:
        _fail(job_id, str(exc), meeting_id, actor, log)
        raise
    finally:
        clear_control(job_id)
        if audio_path:
            cleanup(audio_path)


@celery_app.task(bind=True, name="transcript.from_upload", max_retries=0)
def transcribe_upload_task(
    self: Task,
    job_id: str,
    file_path: str,
    original_filename: str,
    is_video: bool = False,
    meeting_id: str = "",
    actor: str = "system",
) -> dict:
    """Process an uploaded audio or video file."""
    log = make_logger(job_id, logger)
    audio_path: str | None = None
    try:
        transcript_id = _begin(job_id, meeting_id)

        checkpoint(job_id)
        log(STEP_FOUND, f"Received file: {original_filename}")
        audio_path = _prepare_upload(job_id, log, file_path, original_filename, is_video)

        checkpoint(job_id)
        transcript = _transcribe(job_id, log, audio_path)

        log(STEP_SAVING, f"Saving transcript ({len(transcript)} chars)...")
        hooks.on_success(meeting_id, transcript_id, transcript, actor, source_label=original_filename)
        set_job_done(job_id, transcript)
        return {"status": "done", "transcript": transcript}

    except StopRequested:
        set_job_stopped(job_id)
        hooks.on_stopped(meeting_id, actor)
        return {"status": "stopped"}
    except Exception as exc:
        _fail(job_id, str(exc), meeting_id, actor, log)
        raise
    finally:
        clear_control(job_id)
        _cleanup_upload(file_path, audio_path, is_video)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _begin(job_id: str, meeting_id: str) -> str:
    """Resolve the meeting's transcript (find-or-create), mark it generating, and
    record the id on the job for display. Returns "" when no meeting is linked."""
    transcript_id = hooks.on_generating(meeting_id)
    if transcript_id:
        set_transcript_id(job_id, transcript_id)
    return transcript_id


def _try_captions(job_id, log, url, meeting_id, transcript_id, actor) -> dict | None:
    """Use existing YouTube captions if present. Returns a result dict or None."""
    log(STEP_TRANSCRIBING, "Checking for existing YouTube captions...")
    captions = fetch_captions(url, log=lambda m: log(STEP_TRANSCRIBING, m))
    if not captions:
        log(STEP_DOWNLOADING, "No captions found — downloading audio for Gemini...")
        return None
    log(STEP_SAVING, f"Using YouTube captions ({len(captions)} chars)...")
    hooks.on_success(meeting_id, transcript_id, captions, actor, source_label=url)
    set_job_done(job_id, captions)
    return {"status": "done", "transcript": captions, "source": "captions"}


def _prepare_upload(job_id, log, file_path, original_filename, is_video) -> str:
    """Return the audio path to transcribe, extracting from video when needed."""
    if not is_video:
        log(STEP_EXTRACTING, "Audio file — no extraction needed")
        return file_path
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to extract audio from video but was not found.")
    log(STEP_EXTRACTING, f"Extracting audio from video: {original_filename}")
    audio_path = extract_audio_from_upload(ffmpeg, file_path)
    log(STEP_EXTRACTING, f"Audio extracted: {os.path.basename(audio_path)}")
    return audio_path


def _transcribe(job_id, log, audio_path: str) -> str:
    size_mb = os.path.getsize(audio_path) / 1024 / 1024
    log(STEP_UPLOADING, f"Uploading {size_mb:.1f} MB to Gemini Files API...")
    log(STEP_TRANSCRIBING, "Generating transcript with Gemini...")
    return transcribe_file(audio_path, log=lambda msg: log(STEP_TRANSCRIBING, msg))


def _try_remote_media_transcription(
    job_id,
    log,
    candidates: list[str],
    original_url: str,
    meeting_id: str,
    transcript_id: str,
    actor: str,
    download_error: Exception,
) -> dict | None:
    media_url = next((c for c in candidates if is_direct_media_url(c)), None)
    if not media_url:
        return None

    _, ext = os.path.splitext(media_url)
    mime = ext_to_mime(ext)
    log(
        STEP_TRANSCRIBING,
        "Server download failed; asking Gemini to fetch the media URL directly.",
        level="warn",
    )
    logger.warning("Falling back to Gemini URL transcription after download failure: %s", download_error)
    transcript = transcribe_media_url(
        media_url,
        mime,
        log=lambda msg: log(STEP_TRANSCRIBING, msg),
    )
    log(STEP_SAVING, f"Saving transcript ({len(transcript)} chars)...")
    hooks.on_success(meeting_id, transcript_id, transcript, actor, source_label=original_url)
    set_job_done(job_id, transcript)
    return {"status": "done", "transcript": transcript, "source": "gemini_url"}


def _fail(job_id, error_msg, meeting_id, actor, log) -> None:
    log(STEP_FAILED, error_msg, level="error")
    set_job_failed(job_id, error_msg)
    hooks.on_failure(meeting_id, error_msg, actor)


def _cleanup_upload(file_path, audio_path, is_video) -> None:
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
    if is_video and audio_path and audio_path != file_path:
        cleanup(audio_path)
