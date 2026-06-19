"""
POST /api/transcript/url     — submit a URL job
POST /api/transcript/upload  — submit a file upload job
Both return {job_id, status} immediately; processing is async.
"""
from __future__ import annotations
import os
import uuid
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, AnyHttpUrl

from app.core.config import settings
from app.core import job_store
from app.tasks.transcript_task import transcribe_url_task, transcribe_upload_task

router = APIRouter(prefix="/api/transcript", tags=["transcript"])
logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v"}


class UrlRequest(BaseModel):
    url: str
    meeting_id: str = ""
    transcript_id: str = ""
    actor: str = "system"


@router.post("/url")
def submit_url(body: UrlRequest):
    job_id = str(uuid.uuid4())
    job_store.create_job(
        job_id=job_id,
        source_type="url",
        source=body.url,
        meeting_id=body.meeting_id,
        transcript_id=body.transcript_id,
        actor=body.actor,
    )
    transcribe_url_task.apply_async(
        args=[job_id, body.url],
        kwargs={
            "meeting_id": body.meeting_id,
            "transcript_id": body.transcript_id,
            "actor": body.actor,
        },
        task_id=job_id,
    )
    logger.info("URL job queued: %s → %s", job_id, body.url)
    return {"job_id": job_id, "status": "queued"}


@router.post("/upload")
async def submit_upload(
    file: UploadFile = File(...),
    meeting_id: str = Form(""),
    transcript_id: str = Form(""),
    actor: str = Form("system"),
):
    if file.size and file.size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    job_id = str(uuid.uuid4())
    _, ext = os.path.splitext(file.filename or "")
    dest = os.path.join(settings.UPLOAD_DIR, f"{job_id}{ext}")

    content = await file.read()
    with open(dest, "wb") as fh:
        fh.write(content)

    is_video = ext.lower() in VIDEO_EXTENSIONS

    job_store.create_job(
        job_id=job_id,
        source_type="upload",
        source=file.filename or "uploaded_file",
        meeting_id=meeting_id,
        transcript_id=transcript_id,
        actor=actor,
    )
    transcribe_upload_task.apply_async(
        args=[job_id, dest, file.filename or ""],
        kwargs={
            "is_video": is_video,
            "meeting_id": meeting_id,
            "transcript_id": transcript_id,
            "actor": actor,
        },
        task_id=job_id,
    )
    logger.info("Upload job queued: %s → %s (video=%s)", job_id, file.filename, is_video)
    return {"job_id": job_id, "status": "queued", "is_video": is_video}
