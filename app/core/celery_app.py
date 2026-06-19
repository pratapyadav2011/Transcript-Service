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
    # Each worker process reserves just one task at a time (no greedy prefetch),
    # so N jobs run truly in parallel where N = --concurrency. Fair for long,
    # IO/CPU-heavy audio jobs.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_track_started=True,
    # Revoke (stop) support
    task_reject_on_worker_lost=True,
)
