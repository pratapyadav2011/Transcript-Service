"""
Job state + step-by-step log storage in Redis.

Each job has:
  job:{id}:meta   — hash  { status, source_type, source, meeting_id, transcript_id,
                            actor, created_at, updated_at, error, transcript_preview }
  job:{id}:logs   — list  [ "{iso_ts} [STEP] message", ... ]  (capped at MAX_LOG_ENTRIES)
  jobs:index      — sorted set  score=created_at_ts, member=job_id
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.redis_client import get_redis

TTL = settings.RESULT_TTL_SECONDS
MAX_LOGS = settings.MAX_LOG_ENTRIES

# ── Step constants (used in task for display) ─────────────────────────────────
STEP_QUEUED = "QUEUED"
STEP_RESOLVING = "RESOLVING"
STEP_FOUND = "FOUND"
STEP_DOWNLOADING = "DOWNLOADING"
STEP_EXTRACTING = "EXTRACTING"
STEP_UPLOADING = "UPLOADING"
STEP_TRANSCRIBING = "TRANSCRIBING"
STEP_SAVING = "SAVING"
STEP_DONE = "DONE"
STEP_FAILED = "FAILED"
STEP_STOPPED = "STOPPED"
STEP_PAUSED = "PAUSED"

# ── Control actions (cooperative pause/stop) ──────────────────────────────────
CONTROL_RUNNING = "running"
CONTROL_PAUSED = "paused"
CONTROL_STOPPED = "stopped"

# Statuses that mean the job is finished and cannot be controlled.
TERMINAL_STATUSES = {STEP_DONE, STEP_FAILED, STEP_STOPPED}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meta_key(job_id: str) -> str:
    return f"job:{job_id}:meta"


def _log_key(job_id: str) -> str:
    return f"job:{job_id}:logs"


def _control_key(job_id: str) -> str:
    return f"job:{job_id}:control"


def create_job(
    job_id: str,
    source_type: str,       # "url" | "upload"
    source: str,            # original URL or filename
    meeting_id: str = "",
    transcript_id: str = "",
    actor: str = "system",
) -> dict:
    r = get_redis()
    now = _ts()
    meta = {
        "job_id": job_id,
        "status": STEP_QUEUED,
        "source_type": source_type,
        "source": source,
        "meeting_id": meeting_id,
        "transcript_id": transcript_id,
        "actor": actor,
        "created_at": now,
        "updated_at": now,
        "error": "",
        "transcript_preview": "",
    }
    pipe = r.pipeline()
    pipe.hset(_meta_key(job_id), mapping=meta)
    pipe.expire(_meta_key(job_id), TTL)
    pipe.expire(_log_key(job_id), TTL)
    pipe.zadd("jobs:index", {job_id: time.time()})
    pipe.expire("jobs:index", TTL)
    pipe.execute()
    return meta


def log_step(job_id: str, step: str, message: str, level: str = "info") -> None:
    r = get_redis()
    prefix = "ERROR" if level == "error" else "WARN" if level == "warn" else "INFO"
    entry = f"{_ts()} [{step}] {prefix}: {message}"
    pipe = r.pipeline()
    pipe.rpush(_log_key(job_id), entry)
    pipe.ltrim(_log_key(job_id), -MAX_LOGS, -1)
    pipe.hset(_meta_key(job_id), mapping={"status": step, "updated_at": _ts()})
    pipe.expire(_log_key(job_id), TTL)
    pipe.expire(_meta_key(job_id), TTL)
    pipe.execute()


def set_job_failed(job_id: str, error: str) -> None:
    r = get_redis()
    short_error = str(error)[:500]
    r.hset(_meta_key(job_id), mapping={"status": STEP_FAILED, "error": short_error, "updated_at": _ts()})
    log_step(job_id, STEP_FAILED, short_error, level="error")


def set_job_done(job_id: str, transcript_preview: str) -> None:
    r = get_redis()
    preview = transcript_preview[:300]
    r.hset(_meta_key(job_id), mapping={"status": STEP_DONE, "transcript_preview": preview, "updated_at": _ts()})
    log_step(job_id, STEP_DONE, "Transcript saved successfully.")


def set_job_stopped(job_id: str) -> None:
    r = get_redis()
    r.hset(_meta_key(job_id), mapping={"status": STEP_STOPPED, "updated_at": _ts()})
    log_step(job_id, STEP_STOPPED, "Job was stopped by user.")


def set_job_paused(job_id: str) -> None:
    r = get_redis()
    r.hset(_meta_key(job_id), mapping={"status": STEP_PAUSED, "updated_at": _ts()})


# ── Cooperative control flag (read by the running task at checkpoints) ─────────

def set_control(job_id: str, action: str) -> None:
    r = get_redis()
    r.set(_control_key(job_id), action, ex=TTL)


def get_control(job_id: str) -> str:
    r = get_redis()
    return r.get(_control_key(job_id)) or CONTROL_RUNNING


def clear_control(job_id: str) -> None:
    get_redis().delete(_control_key(job_id))


def get_job(job_id: str) -> dict | None:
    r = get_redis()
    meta = r.hgetall(_meta_key(job_id))
    return meta if meta else None


def get_job_logs(job_id: str) -> list[str]:
    r = get_redis()
    return r.lrange(_log_key(job_id), 0, -1)


def list_jobs(limit: int = 100) -> list[dict]:
    r = get_redis()
    job_ids = r.zrevrange("jobs:index", 0, limit - 1)
    jobs = []
    for jid in job_ids:
        meta = r.hgetall(_meta_key(jid))
        if meta:
            jobs.append(meta)
    return jobs


def delete_job(job_id: str) -> None:
    r = get_redis()
    pipe = r.pipeline()
    pipe.delete(_meta_key(job_id))
    pipe.delete(_log_key(job_id))
    pipe.delete(_control_key(job_id))
    pipe.zrem("jobs:index", job_id)
    pipe.execute()
