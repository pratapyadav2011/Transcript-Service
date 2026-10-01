import json
from unittest.mock import patch

from app.services.resolver.civicclerk_resolver import fetch_closed_captions, resolve


PAGE_URL = "https://escambiacofl.portal.civicclerk.com/event/2871/media"
API_URL = "https://escambiacofl.api.civicclerk.com/v1/EventsMedia/2871"
VIDEO_URL = "https://cpmedia.azureedge.net/escambiacofl/meeting.mp4"
CAPTION_URL = "https://cpmedia.azureedge.net/escambiacofl/ClosedCaption/meeting.srt"
SRT = "1\n00:00:01,000 --> 00:00:02,000\nCall to order.\n"


def _fake_fetch(api_payload: dict):
    def fetch(url, timeout=15):
        if url == API_URL:
            return json.dumps(api_payload)
        if url == CAPTION_URL:
            return SRT
        raise AssertionError(f"unexpected fetch: {url}")
    return fetch


def test_resolve_returns_video_url():
    fetch = _fake_fetch({"videoUrl": VIDEO_URL})
    with patch("app.services.resolver.civicclerk_resolver.fetch_text", side_effect=fetch):
        assert resolve(PAGE_URL) == VIDEO_URL


def test_fetch_closed_captions_downloads_srt():
    fetch = _fake_fetch({"videoUrl": VIDEO_URL, "closedCaptionUrl": CAPTION_URL})
    with patch("app.services.resolver.civicclerk_resolver.fetch_text", side_effect=fetch):
        assert fetch_closed_captions(PAGE_URL) == SRT


def test_fetch_closed_captions_none_when_missing():
    fetch = _fake_fetch({"videoUrl": VIDEO_URL, "closedCaptionUrl": None})
    with patch("app.services.resolver.civicclerk_resolver.fetch_text", side_effect=fetch):
        assert fetch_closed_captions(PAGE_URL) is None


def test_fetch_closed_captions_swallows_errors():
    with patch("app.services.resolver.civicclerk_resolver.fetch_text", side_effect=OSError("down")):
        assert fetch_closed_captions(PAGE_URL) is None
