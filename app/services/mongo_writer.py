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
            "details": details or {},
            "time": _now(),
        })
    except Exception as exc:
        logger.error("[mongo] Failed to write log: %s", exc)
