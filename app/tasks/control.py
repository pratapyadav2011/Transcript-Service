"""
Cooperative pause/stop checkpoint for running tasks.

Celery cannot natively "pause" a running task, so the task calls `checkpoint()`
between major steps. The API writes a control flag to Redis; the checkpoint reads
it and either:
  • continues (running),
  • blocks in a poll-loop until resumed or stopped (paused),
  • raises StopRequested (stopped) so the task can exit cleanly.

Note: a paused job holds its Celery worker slot while waiting. With a single
worker this blocks other jobs — scale workers if you need concurrent pauses.
"""
from __future__ import annotations

import time
from typing import Callable

from app.core.job_store import (
    get_control, set_job_paused, log_step,
    CONTROL_PAUSED, CONTROL_STOPPED, STEP_PAUSED,
)

# How often (seconds) a paused task re-checks the control flag.
POLL_INTERVAL = 2.0


class StopRequested(Exception):
    """Raised inside a task when the user requested a stop at a checkpoint."""


def checkpoint(job_id: str) -> None:
    """
    Inspect the control flag for `job_id`.

    Returns immediately when running. Blocks while paused. Raises StopRequested
    when stopped. Call this between expensive steps in a task.
    """
    action = get_control(job_id)

    if action == CONTROL_STOPPED:
        raise StopRequested()

    if action != CONTROL_PAUSED:
        return  # running — carry on

    # Enter pause loop.
    set_job_paused(job_id)
    log_step(job_id, STEP_PAUSED, "Job paused by user — waiting to resume...", level="warn")

    while True:
        time.sleep(POLL_INTERVAL)
        action = get_control(job_id)
        if action == CONTROL_STOPPED:
            raise StopRequested()
        if action != CONTROL_PAUSED:
            log_step(job_id, STEP_PAUSED, "Resumed by user.")
            return


def make_logger(job_id: str, base_logger) -> Callable[[str, str, str], None]:
    """Factory for a step logger bound to a job id (keeps tasks DRY)."""

    def log(step: str, msg: str, level: str = "info") -> None:
        log_step(job_id, step, msg, level=level)
        base_logger.info("[%s] [%s] %s", job_id, step, msg)

    return log
