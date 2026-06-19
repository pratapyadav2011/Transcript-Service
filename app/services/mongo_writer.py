"""
Writes transcript results back to the same MongoDB collections
that the Next.js app uses.

Mirrors:
  MeetingTranscriptStatusService.ts  → meetings collection
  MeetingTranscriptService.ts        → transcripts collection
  MeetingLogService.ts + applicationLog.ts → applicationlogs collection
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from bson import ObjectId
from app.core.mongo_client import get_db

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Read the meeting's source video URL ──────────────────────────────────────

def get_meeting_video_url(meeting_id: str) -> str:
    """Return the meeting's DirectVideoURL, or raise if missing."""
    db = get_db()
    meeting = db.meetings.find_one(
        {"_id": ObjectId(meeting_id)}, {"DirectVideoURL": 1}
    )
    if not meeting:
        raise ValueError(f"Meeting {meeting_id} not found")
    url = (meeting.get("DirectVideoURL") or "").strip()
    if not url:
        raise ValueError(f"Meeting {meeting_id} has no DirectVideoURL")
    return url


# ── Find-or-create the transcript linked to a meeting ────────────────────────

def ensure_transcript(meeting_id: str) -> str:
    """
    Return the transcript_id for a meeting, creating + linking a transcript
    document if the meeting doesn't have one yet. Caller passes only meeting_id.
    """
    db = get_db()
    meeting = db.meetings.find_one(
        {"_id": ObjectId(meeting_id)}, {"transcript_id": 1}
    )
    if not meeting:
        raise ValueError(f"Meeting {meeting_id} not found")

    existing = meeting.get("transcript_id")
    if existing:
        return str(existing)

    now = _now()
    result = db.transcripts.insert_one(
        {"textString": "", "createdAt": now, "updatedAt": now, "__v": 0}
    )
    db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {"transcript_id": result.inserted_id, "updatedAt": now}},
    )
    logger.info("[mongo] created transcript %s for meeting %s", result.inserted_id, meeting_id)
    return str(result.inserted_id)


# ── Meeting transcript status (mirrors MeetingTranscriptStatusService.ts) ────

def set_transcript_generating(meeting_id: str) -> None:
    db = get_db()
    db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {
            "transcriptStatus": "generating",
            "processingError": "",
            "videoUrlType": "audio_gemini",
            "updatedAt": _now(),
        }},
    )
    logger.info("[mongo] meeting %s → transcriptStatus=generating", meeting_id)


def set_transcript_generated(meeting_id: str) -> None:
    db = get_db()
    db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {
            "transcriptStatus": "generated",
            "processingError": "",
            "updatedAt": _now(),
        }},
    )
    logger.info("[mongo] meeting %s → transcriptStatus=generated", meeting_id)


def set_transcript_failed(meeting_id: str, error: str) -> None:
    db = get_db()
    db.meetings.update_one(
        {"_id": ObjectId(meeting_id)},
        {"$set": {
            "transcriptStatus": "failed",
            "processingError": str(error)[:500],
            "updatedAt": _now(),
        }},
    )
    logger.info("[mongo] meeting %s → transcriptStatus=failed", meeting_id)


# ── Transcript text (mirrors MeetingTranscriptService.ts) ────────────────────

def update_transcript_text(transcript_id: str, text: str) -> None:
    db = get_db()
    db.transcripts.update_one(
        {"_id": ObjectId(transcript_id)},
        {"$set": {"textString": text, "updatedAt": _now()}},
    )
    logger.info("[mongo] transcript %s updated (%d chars)", transcript_id, len(text))


# ── Application log (mirrors MeetingLogService.ts + writeLog) ────────────────

def write_log(
    tag: str,
    message: str,
    actor: str,
    meeting_id: str = "",
    log_type: str = "info",
    details: dict | None = None,
) -> None:
    db = get_db()
    try:
        db.applicationlogs.insert_one({
            "applicationName": "Meetings",
            "tag": tag,
            "type": log_type,
            "message": message,
            "creator": actor,
            "creator_id": actor,
            "entityType": "meeting",
            "entityId": meeting_id,
            "details": details or None,
            "time": _now(),
        })
    except Exception as exc:
        logger.error("[mongo] Failed to write log: %s", exc)
