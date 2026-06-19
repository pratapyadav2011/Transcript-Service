from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "transcript_service",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.transcript_task"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=settings.RESULT_TTL_SECONDS,
    # One task at a time per worker — audio processing is IO/CPU heavy
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_track_started=True,
    # Revoke (stop) support
    task_reject_on_worker_lost=True,
)
