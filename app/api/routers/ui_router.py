"""Server-rendered UI routes (Jinja2 templates)."""
from __future__ import annotations
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.core import job_store

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def ui_home(request: Request):
    return templates.TemplateResponse("new_job.html", {"request": request})


@router.get("/jobs", response_class=HTMLResponse)
def ui_jobs(request: Request):
    jobs = job_store.list_jobs(limit=200)
    return templates.TemplateResponse("jobs_list.html", {"request": request, "jobs": jobs})


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def ui_job_detail(request: Request, job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    logs = job_store.get_job_logs(job_id)
    display_transcript = (
        job_store.get_job_transcript(job_id)
        if not job.get("meeting_id") else job.get("transcript_preview", "")
    )
    return templates.TemplateResponse(
        "job_detail.html",
        {"request": request, "job": job, "logs": logs, "display_transcript": display_transcript},
    )


# ── HTMX partial fragments (polled every few seconds) ────────────────────────

@router.get("/htmx/jobs", response_class=HTMLResponse)
def htmx_jobs(request: Request):
    jobs = job_store.list_jobs(limit=200)
    return templates.TemplateResponse(
        "partials/jobs_table.html", {"request": request, "jobs": jobs}
    )


@router.get("/htmx/jobs/{job_id}/status", response_class=HTMLResponse)
def htmx_job_status(request: Request, job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        return HTMLResponse("<span class='badge badge-error'>Not found</span>")
    return templates.TemplateResponse(
        "partials/job_status_badge.html", {"request": request, "job": job}
    )


@router.get("/htmx/jobs/{job_id}/logs", response_class=HTMLResponse)
def htmx_job_logs(request: Request, job_id: str):
    logs = job_store.get_job_logs(job_id)
    job = job_store.get_job(job_id) or {}
    return templates.TemplateResponse(
        "partials/job_logs.html",
        {"request": request, "logs": logs, "job": job},
    )
