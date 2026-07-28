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
    # Revoke (stop) support. NOTE: reject_on_worker_lost re-queues a task whose
    # worker died (incl. OOM SIGKILL). Combined with acks_late that can loop a
    # deterministic crash forever, so tasks cap redeliveries via MAX_TASK_DELIVERIES.
    task_reject_on_worker_lost=True,
)

# Recycle a child that has grown past the configured resident-memory ceiling.
# Guards against gradual leaks across tasks; does not interrupt a single task.
if settings.WORKER_MAX_MEMORY_MB > 0:
    celery_app.conf.worker_max_memory_per_child = settings.WORKER_MAX_MEMORY_MB * 1024  # KiB
