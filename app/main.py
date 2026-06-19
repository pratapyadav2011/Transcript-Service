"""
FastAPI application entry point.

Wires together routers, static assets and templates. Run with:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
The Celery worker is a separate process (see README / docker-compose).
"""
from __future__ import annotations
import os
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.middleware import auth_middleware
from app.api.routers import (
    health_router, transcript_router, jobs_router, ui_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# Ensure runtime directories exist.
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
os.makedirs(settings.LOG_DIR, exist_ok=True)

app = FastAPI(title="Transcript Service", version="1.0.0")

# Auth gate — every request must carry a valid API key or signed token.
app.middleware("http")(auth_middleware)

# Static assets (CSS / JS used by the templates).
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# API + UI routers.
app.include_router(health_router.router)
app.include_router(transcript_router.router)
app.include_router(jobs_router.router)
app.include_router(ui_router.router)


@app.get("/ping", include_in_schema=False)
def ping():
    return {"pong": True}
