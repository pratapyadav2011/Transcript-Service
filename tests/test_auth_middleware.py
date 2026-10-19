import pytest
from fastapi.testclient import TestClient

from app.core import job_store
from app.core.config import settings
from app.core.security import SESSION_COOKIE, make_token

SECRET = "s" * 64


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_SERVICE_TOKEN", SECRET)
    monkeypatch.setattr(job_store, "list_jobs", lambda limit=100: [])
    from app.main import app
    return TestClient(app)


@pytest.fixture
def ui_open(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)


@pytest.fixture
def ui_locked(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)


@pytest.mark.parametrize("mode", ["ui_open", "ui_locked"])
def test_api_needs_credentials_regardless_of_ui_mode(client, request, mode):
    request.getfixturevalue(mode)
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/transcript/meeting", json={}).status_code == 401
    assert client.get("/htmx/jobs").status_code == 401
    assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize("mode", ["ui_open", "ui_locked"])
def test_api_key_and_tokens_work(client, request, mode):
    request.getfixturevalue(mode)
    assert client.get("/api/jobs", headers={"X-API-Key": SECRET}).status_code == 200
    assert client.get("/api/jobs", headers={"X-API-Key": "wrong"}).status_code == 401
    token = make_token(60)
    assert client.get("/api/jobs", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get(f"/api/jobs?token={token}").status_code == 200


def test_open_ui_hands_out_session_for_its_own_api_calls(client, ui_open):
    page = client.get("/jobs")
    assert page.status_code == 200
    assert SESSION_COOKIE in page.cookies
    # The browser (TestClient keeps cookies) can now use the API the page calls.
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/htmx/jobs").status_code == 200


def test_locked_ui_needs_login(client, ui_locked):
    assert client.get("/jobs").status_code == 401
    assert client.get(f"/jobs?token={make_token(60)}").status_code == 200
    assert client.get("/api/jobs").status_code == 200  # session cookie from the link


def test_expired_session_cookie_is_rejected_by_api(client, ui_open):
    client.cookies.set(SESSION_COOKIE, make_token(-10))
    assert client.get("/api/jobs").status_code == 401


def test_no_secret_means_everything_open(client, monkeypatch, ui_locked):
    monkeypatch.setattr(settings, "API_SERVICE_TOKEN", "")
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/jobs").status_code == 200
