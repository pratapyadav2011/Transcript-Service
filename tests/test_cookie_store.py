import time

import pytest

from app.core.config import settings
from app.services.downloader import cookie_store
from app.services.downloader.cookie_store import InvalidCookiesFile


FUTURE = int(time.time()) + 30 * 24 * 3600


def _jar(name="SID", domain=".youtube.com", expires=FUTURE) -> str:
    return (
        "# Netscape HTTP Cookie File\n"
        f"{domain}\tTRUE\t/\tTRUE\t{expires}\t{name}\tvalue123\n"
        f"{domain}\tTRUE\t/\tTRUE\t{expires}\tPREF\tf1=40000000\n"
    )


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "YTDLP_COOKIES_FILE", "")
    return tmp_path


def test_save_then_status_reports_present():
    cookie_store.save(_jar())
    status = cookie_store.status()

    assert status["present"] is True
    assert status["managed"] is True
    assert status["count"] == 2
    assert status.get("expired") is False


def test_saved_file_is_owner_only_readable(upload_dir):
    cookie_store.save(_jar())
    mode = (upload_dir / cookie_store.COOKIE_FILENAME).stat().st_mode
    assert mode & 0o077 == 0


def test_httponly_prefixed_lines_are_parsed():
    jar = f"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t{FUTURE}\t__Secure-3PSID\tabc\n"
    assert cookie_store.save(jar)["count"] == 1


def test_rejects_file_without_login_cookies():
    with pytest.raises(InvalidCookiesFile, match="not from a signed-in session"):
        cookie_store.validate(_jar(name="VISITOR_INFO1_LIVE"))


def test_rejects_unrelated_domain():
    with pytest.raises(InvalidCookiesFile, match="No youtube.com or google.com"):
        cookie_store.validate(_jar(domain=".example.com"))


def test_rejects_json_export():
    with pytest.raises(InvalidCookiesFile, match="Netscape format"):
        cookie_store.validate('[{"name": "SID", "value": "x"}]')


def test_expired_jar_is_flagged():
    cookie_store.save(_jar(expires=int(time.time()) - 60))
    assert cookie_store.status()["expired"] is True


def test_status_absent_before_upload():
    assert cookie_store.status() == {"present": False}


def test_delete_removes_file():
    cookie_store.save(_jar())
    assert cookie_store.delete() is True
    assert cookie_store.delete() is False
    assert cookie_store.status()["present"] is False


def test_env_configured_file_takes_precedence(tmp_path, monkeypatch):
    env_file = tmp_path / "env-cookies.txt"
    env_file.write_text(_jar())
    monkeypatch.setattr(settings, "YTDLP_COOKIES_FILE", str(env_file))
    cookie_store.save(_jar())

    assert cookie_store.active_path() == str(env_file)
    assert cookie_store.status()["managed"] is False


def test_missing_env_file_falls_back_to_upload(monkeypatch):
    monkeypatch.setattr(settings, "YTDLP_COOKIES_FILE", "/nonexistent/cookies.txt")
    cookie_store.save(_jar())
    assert cookie_store.active_path() == cookie_store.upload_path()
