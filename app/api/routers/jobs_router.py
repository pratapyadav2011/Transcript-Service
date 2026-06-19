"""
REST endpoints for job management.
GET    /api/jobs              — list all jobs
GET    /api/jobs/{id}         — job meta + status
GET    /api/jobs/{id}/logs    — full step log
POST   /api/jobs/{id}/pause   — cooperatively pause a running job
POST   /api/jobs/{id}/resume  — resume a paused job
POST   /api/jobs/{id}/stop    — stop (revoke) a job
POST   /api/jobs/{id}/rerun   — requeue a URL job with the same parameters
DELETE /api/jobs/{id}         — remove from store
"""
from __future__ import annotations
import uuid
from fastapi import APIRouter, HTTPException

from app.core.celery_app import celery_app
from app.core import job_store
from app.core.job_store import (
    set_control, clear_control, set_job_stopped,
    CONTROL_PAUSED, CONTROL_RUNNING, CONTROL_STOPPED, TERMINAL_STATUSES,
)
from app.tasks.transcript_task import transcribe_url_task
from app.tasks import hooks

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _require_job(job_id: str) -> dict:
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("")
def list_jobs():
    return {"jobs": job_store.list_jobs(limit=200)}


@router.get("/{job_id}")
def get_job(job_id: str):
    return _require_job(job_id)


@router.get("/{job_id}/logs")
def get_logs(job_id: str):
    _require_job(job_id)
    return {"job_id": job_id, "logs": job_store.get_job_logs(job_id)}


@router.post("/{job_id}/pause")
def pause_job(job_id: str):
    job = _require_job(job_id)
    if job["status"] in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Job already finished")
    set_control(job_id, CONTROL_PAUSED)
    return {"status": "pausing", "job_id": job_id}


@router.post("/{job_id}/resume")
def resume_job(job_id: str):
    _require_job(job_id)
    set_control(job_id, CONTROL_RUNNING)
    return {"status": "resuming", "job_id": job_id}


@router.post("/{job_id}/stop")
def stop_job(job_id: str):
    job = _require_job(job_id)
    # Signal cooperative stop, then forcibly terminate the worker process.
    set_control(job_id, CONTROL_STOPPED)
    celery_app.control.revoke(job_id, terminate=True, signal="SIGTERM")
    set_job_stopped(job_id)
    # Update Mongo here too — terminate=True may kill the worker before its own
    # checkpoint runs, so the meeting would otherwise hang in "generating".
    if job["status"] not in TERMINAL_STATUSES:
        hooks.on_stopped(job.get("meeting_id", ""), job.get("actor", "system"))
    return {"status": "stopped", "job_id": job_id}


@router.post("/{job_id}/rerun")
def rerun_job(job_id: str):
    job = _require_job(job_id)
    if job.get("source_type") != "url":
        raise HTTPException(
            status_code=400,
            detail="Only URL jobs can be rerun (uploaded files are deleted after processing).",
        )
    new_id = str(uuid.uuid4())
    job_store.create_job(
        job_id=new_id,
        source_type="url",
        source=job["source"],
        meeting_id=job.get("meeting_id", ""),
        actor=job.get("actor", "system"),
    )
    transcribe_url_task.apply_async(
        args=[new_id, job["source"]],
        kwargs={
            "meeting_id": job.get("meeting_id", ""),
            "actor": job.get("actor", "system"),
        },
        task_id=new_id,
    )
    return {"status": "queued", "job_id": new_id, "rerun_of": job_id}


@router.delete("/{job_id}")
def delete_job(job_id: str):
    job = _require_job(job_id)
    set_control(job_id, CONTROL_STOPPED)
    celery_app.control.revoke(job_id, terminate=True)
    if job["status"] not in TERMINAL_STATUSES:
        hooks.on_stopped(job.get("meeting_id", ""), job.get("actor", "system"))
    clear_control(job_id)
    job_store.delete_job(job_id)
    return {"deleted": True, "job_id": job_id}
