"""
MongoDB side-effects for transcript tasks.

Keeps the Celery task modules thin: all "write status/transcript back to the
Next.js collections" logic lives here. Each function is a no-op unless a
meeting_id (and transcript_id, where relevant) is provided.
"""
from __future__ import annotations

from app.services import mongo_writer


def on_generating(meeting_id: str, transcript_id: str) -> None:
    if meeting_id and transcript_id:
        mongo_writer.set_transcript_generating(meeting_id)


def on_success(
    meeting_id: str,
    transcript_id: str,
    transcript: str,
    actor: str,
    source_label: str,
) -> None:
    if not (meeting_id and transcript_id):
        return
    mongo_writer.update_transcript_text(transcript_id, transcript)
    mongo_writer.set_transcript_generated(meeting_id)
    mongo_writer.write_log(
        tag="MEETING_AUDIO_GEMINI_TRANSCRIPT_GENERATED",
        message=f"Transcript generated with Gemini ({source_label})",
        actor=actor,
        meeting_id=meeting_id,
    )


def on_failure(meeting_id: str, error_msg: str, actor: str) -> None:
    if not meeting_id:
        return
    mongo_writer.set_transcript_failed(meeting_id, error_msg)
    mongo_writer.write_log(
        tag="MEETING_AUDIO_GEMINI_TRANSCRIPT_FAILED",
        message=error_msg,
        actor=actor,
        meeting_id=meeting_id,
        log_type="error",
    )
