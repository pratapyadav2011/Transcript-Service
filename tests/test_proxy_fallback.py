import pytest
import requests

from app.core.config import settings
from app.services.downloader import proxy_fallback
from app.services.downloader.audio_pipeline import _direct_first

PROXY = "http://user:pass@cf-proxy:8888"


def _http_error(status: int) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PROXY_URL", PROXY)


@pytest.mark.parametrize("error", [
    _http_error(403),
    _http_error(401),
    _http_error(429),
    "ERROR: [vimeo] 1234: Unable to download webpage: HTTP Error 401: Unauthorized",
    "ERROR: [youtube] abc: Sign in to confirm you're not a bot",
    "ERROR: [vimeo] 1234: The web client only works when logged-in.",
    "ERROR: [generic] 403163: Failed to download m3u8 information: HTTP Error 403: Forbidden",
])
def test_ip_blocks_are_detected(error):
    assert proxy_fallback.is_blocked(error)


def test_transcript_api_block_exceptions_are_detected():
    from youtube_transcript_api import IpBlocked, RequestBlocked
    assert proxy_fallback.is_blocked(RequestBlocked("abc"))
    assert proxy_fallback.is_blocked(IpBlocked("abc"))


@pytest.mark.parametrize("error", [
    _http_error(404),
    _http_error(500),
    "ERROR: RTMP download detected but \"rtmpdump\" could not be run",
    "ffmpeg exited with code 183",
    RuntimeError("yt-dlp did not produce an audio file"),
])
def test_ordinary_failures_are_not_blocks(error):
    assert not proxy_fallback.is_blocked(error)


def test_no_retry_without_configured_proxy(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PROXY_URL", "")
    assert not proxy_fallback.should_retry_via_proxy(_http_error(403))


def test_success_from_server_ip_never_uses_proxy(proxy):
    calls = []
    assert _direct_first(lambda p: calls.append(p) or "audio.mp3", log=lambda m: None) == "audio.mp3"
    assert calls == [None]


def test_block_retries_once_via_proxy(proxy):
    calls, logs = [], []

    def attempt(p):
        calls.append(p)
        if p is None:
            raise _http_error(403)
        return "audio.mp3"

    assert _direct_first(attempt, log=logs.append) == "audio.mp3"
    assert calls == [None, PROXY]
    assert any("retrying via proxy" in m for m in logs)


def test_ordinary_failure_is_not_retried(proxy):
    calls = []

    def attempt(p):
        calls.append(p)
        raise _http_error(404)

    with pytest.raises(requests.HTTPError):
        _direct_first(attempt, log=lambda m: None)
    assert calls == [None]


def test_proxy_failure_is_reported_as_such(proxy):
    def attempt(p):
        raise _http_error(403) if p is None else RuntimeError("407 Proxy Authentication Required")

    with pytest.raises(RuntimeError, match="via proxy: 407"):
        _direct_first(attempt, log=lambda m: None)
