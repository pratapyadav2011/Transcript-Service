"""
MongoDB side-effects for transcript tasks.

Keeps the Celery task modules thin: all "write status/transcript back to the
Next.js collections" logic lives here. Each function is a no-op unless a
meeting_id is provided, and every Mongo write on the failure/stop paths is
guarded so a DB hiccup can never mask the real job error.
"""
from __future__ import annotations

import logging

from app.services import mongo_writer

logger = logging.getLogger(__name__)

SUCCESS_TAG = "MEETING_TRANSCRIPT_GENERATED"
FAILURE_TAG = "MEETING_TRANSCRIPT_GENERATE_FAILED"
STOPPED_TAG = "MEETING_TRANSCRIPT_GENERATION_STOPPED"
STOP_MESSAGE = "Transcript generation stopped by user."


def on_generating(meeting_id: str) -> str:
    """Resolve (find-or-create) the meeting's transcript and mark it generating.
    Returns the transcript_id, or "" when no meeting is linked."""
    if not meeting_id:
        return ""
    transcript_id = mongo_writer.ensure_transcript(meeting_id)
    mongo_writer.set_transcript_generating(meeting_id)
    return transcript_id


def on_success(
    meeting_id: str,
    transcript_id: str,
    transcript: str,
    actor: str,
    source_label: str,
    job_id: str = "",
) -> None:
    if not (meeting_id and transcript_id):
        return
    mongo_writer.update_transcript_text(transcript_id, transcript)
    mongo_writer.set_transcript_generated(meeting_id)
    mongo_writer.write_log(
        tag=SUCCESS_TAG,
        message="Meeting transcript generated successfully",
        actor=actor,
        meeting_id=meeting_id,
        status="succeeded",
        correlation_id=job_id,
        details={"jobId": job_id, "source": source_label},
    )


def on_failure(meeting_id: str, error_msg: str, actor: str, job_id: str = "") -> None:
    """Mark the meeting failed + write an error log. Guarded so a Mongo problem
    can never mask the original job error (matches `.catch(() => {})` in TS)."""
    _mark_failed(meeting_id, error_msg, actor, job_id, FAILURE_TAG, "error", "failed")


def on_stopped(meeting_id: str, actor: str, job_id: str = "") -> None:
    """A stopped job is terminal too — mark the meeting failed so it never hangs
    in `generating` (the status enum has no `stopped`)."""
    _mark_failed(meeting_id, STOP_MESSAGE, actor, job_id, STOPPED_TAG, "warn", "failed")


def _mark_failed(
    meeting_id: str, message: str, actor: str, job_id: str,
    tag: str, log_type: str, status: str,
) -> None:
    if not meeting_id:
        return
    try:
        mongo_writer.set_transcript_failed(meeting_id, message)
    except Exception:
        logger.exception("[hooks] set_transcript_failed failed for %s", meeting_id)
    try:
        mongo_writer.write_log(
            tag=tag, message=message, actor=actor,
            meeting_id=meeting_id, log_type=log_type,
            status=status, correlation_id=job_id,
            error={"message": message} if log_type == "error" else None,
            details={"jobId": job_id},
        )
    except Exception:
        logger.exception("[hooks] failure log write failed for %s", meeting_id)
