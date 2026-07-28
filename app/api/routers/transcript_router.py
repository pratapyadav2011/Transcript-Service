"""
POST /api/transcript/url     — submit a URL job
POST /api/transcript/upload  — submit a file upload job
Both return {job_id, status} immediately; processing is async.
"""
from __future__ import annotations
import os
import uuid
import logging
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, AnyHttpUrl

from app.core.config import settings, transcription_queue
from app.core import job_store
from app.services import mongo_writer
from app.services.resolver.media_resolver import resolve_candidates
from app.services.resolver.url_classifier import is_media_url
from app.tasks.transcript_task import transcribe_url_task, transcribe_upload_task

router = APIRouter(prefix="/api/transcript", tags=["transcript"])
logger = logging.getLogger(__name__)


def _queue_options() -> dict:
    queue = transcription_queue()
    return {"queue": queue} if queue else {}

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v",
    ".mpeg", ".mpg", ".ts", ".m2ts", ".mts", ".3gp", ".ogv", ".vob",
}


class MeetingRequest(BaseModel):
    meeting_id: str
    actor: str = "system"


class UrlRequest(BaseModel):
    url: str
    meeting_id: str = ""
    actor: str = "system"


@router.post("/media-links")
def find_media_links(body: UrlRequest):
    """Resolve a player/page URL into links the user's browser can download."""
    parsed = urlparse(body.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Enter a valid HTTP(S) URL")
    try:
        candidates = resolve_candidates(body.url)
    except Exception as exc:
        logger.warning("Media-link resolution failed for %s: %s", body.url, exc)
        raise HTTPException(status_code=422, detail="No downloadable media links found") from exc

    links = []
    for url in dict.fromkeys(candidates):
        if not is_media_url(url):
            continue
        ext = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
        links.append({
            "url": url,
            "format": ext.upper() or "MEDIA",
            "downloadable": ext != "m3u8",
        })
    if not links:
        raise HTTPException(status_code=404, detail="No downloadable media links found")
    return {"source_url": body.url, "links": links}


@router.post("/meeting")
def submit_meeting(body: MeetingRequest):
    """Single entry point for the Next.js app: send a meeting_id, the service
    reads its DirectVideoURL from MongoDB and runs the transcript pipeline."""
    try:
        url = mongo_writer.get_meeting_video_url(body.meeting_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    job_id = str(uuid.uuid4())
    job_store.create_job(
        job_id=job_id,
        source_type="url",
        source=url,
        meeting_id=body.meeting_id,
        actor=body.actor,
    )
    transcribe_url_task.apply_async(
        args=[job_id, url],
        kwargs={"meeting_id": body.meeting_id, "actor": body.actor},
        task_id=job_id,
        **_queue_options(),
    )
    logger.info("Meeting job queued: %s → meeting %s → %s", job_id, body.meeting_id, url)
    return {"job_id": job_id, "status": "queued", "meeting_id": body.meeting_id, "url": url}


@router.post("/url")
def submit_url(body: UrlRequest):
    job_id = str(uuid.uuid4())
    job_store.create_job(
        job_id=job_id,
        source_type="url",
        source=body.url,
        meeting_id=body.meeting_id,
        actor=body.actor,
    )
    transcribe_url_task.apply_async(
        args=[job_id, body.url],
        kwargs={
            "meeting_id": body.meeting_id,
            "actor": body.actor,
        },
        task_id=job_id,
        **_queue_options(),
    )
    logger.info("URL job queued: %s → %s", job_id, body.url)
    return {"job_id": job_id, "status": "queued"}


@router.post("/upload")
async def submit_upload(
    file: UploadFile = File(...),
    meeting_id: str = Form(""),
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
        actor=actor,
    )
    transcribe_upload_task.apply_async(
        args=[job_id, dest, file.filename or ""],
        kwargs={
            "is_video": is_video,
            "meeting_id": meeting_id,
            "actor": actor,
        },
        task_id=job_id,
        **_queue_options(),
    )
    logger.info("Upload job queued: %s → %s (video=%s)", job_id, file.filename, is_video)
    return {"job_id": job_id, "status": "queued", "is_video": is_video}
