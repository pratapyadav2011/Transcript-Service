from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core import job_store
from app.api.routers.transcript_router import reject_if_in_progress
from app.tasks import transcript_task


def _ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat(timespec="seconds")


def _job(job_id, status, meeting_id="", source="https://x.granicus.com/player/clip/1", updated=None):
    return {"job_id": job_id, "status": status, "meeting_id": meeting_id,
            "source": source, "updated_at": updated or _ago(minutes=1)}


@pytest.fixture
def jobs(monkeypatch):
    store = []
    monkeypatch.setattr(job_store, "list_jobs", lambda limit=100: list(store))
    return store


def test_running_job_for_same_meeting_blocks_resubmit(jobs):
    jobs.append(_job("abc12345-1", "TRANSCRIBING", meeting_id="m1"))
    with pytest.raises(HTTPException) as err:
        reject_if_in_progress(meeting_id="m1", source="https://other")
    assert err.value.status_code == 409
    assert "already transcribing" in err.value.detail
    assert err.value.headers["X-Active-Job-Id"] == "abc12345-1"


def test_queued_job_blocks_even_when_old(jobs):
    jobs.append(_job("q", "QUEUED", meeting_id="m1", updated=_ago(hours=10)))
    assert job_store.find_active_job(meeting_id="m1")["job_id"] == "q"


def test_same_url_blocks_when_no_meeting(jobs):
    jobs.append(_job("u", "DOWNLOADING", source="https://a/clip/9"))
    assert job_store.find_active_job(source="https://a/clip/9")["job_id"] == "u"
    assert job_store.find_active_job(source="https://a/clip/10") is None


@pytest.mark.parametrize("status", ["DONE", "FAILED", "STOPPED"])
def test_finished_jobs_do_not_block(jobs, status):
    jobs.append(_job("f", status, meeting_id="m1"))
    reject_if_in_progress(meeting_id="m1")  # no exception


def test_silent_running_job_is_treated_as_dead(jobs):
    jobs.append(_job("dead", "DOWNLOADING", meeting_id="m1", updated=_ago(hours=4)))
    assert job_store.find_active_job(meeting_id="m1") is None


def test_other_meeting_does_not_block(jobs):
    jobs.append(_job("x", "TRANSCRIBING", meeting_id="m2"))
    reject_if_in_progress(meeting_id="m1")


@pytest.mark.parametrize("status,expected", [("DONE", True), ("FAILED", True), ("STOPPED", True),
                                             ("QUEUED", False), ("TRANSCRIBING", False)])
def test_redelivered_task_of_finished_job_is_skipped(monkeypatch, status, expected):
    monkeypatch.setattr(transcript_task, "get_job", lambda job_id: {"status": status})
    assert transcript_task._already_finished("job") is expected


def test_visibility_timeout_exceeds_default_hour():
    from app.core.celery_app import celery_app
    assert celery_app.conf.broker_transport_options["visibility_timeout"] >= 6 * 3600
