"""Resolves a Swagit video page (e.g. dublinca.new.swagit.com/videos/403163).

Swagit pages play from archive-stream.granicus.com (HLS + RTMP), which returns
403 to datacenter IPs; yt-dlp then falls back to the RTMP format and fails. Two
better sources exist on every video page:

* ``/videos/{id}/download`` redirects to a signed S3 MP4 (valid ~1 hour).
* ``/videos/{id}/transcript`` serves the published transcript as plain text,
  which lets us skip downloading media entirely.
"""
from __future__ import annotations
import logging
import re
from urllib.parse import urlparse

import requests

from app.services.resolver.html_scraper import HEADERS, fetch_text, extract_media_urls
from app.services.resolver.url_classifier import is_media_url

logger = logging.getLogger(__name__)

VIDEO_PATH_RE = re.compile(r"^/videos/(\d+)")
TIMESTAMP_LINE_RE = re.compile(r"^\[\d{1,2}:\d{2}:\d{2}\]$")


def _video_base(page_url: str) -> str:
    parsed = urlparse(page_url)
    match = VIDEO_PATH_RE.match(parsed.path)
    if not match:
        raise ValueError(f"Cannot parse Swagit video ID from URL: {page_url}")
    return f"https://{parsed.hostname}/videos/{match.group(1)}"


def _signed_download_url(base: str) -> str | None:
    resp = requests.get(f"{base}/download", headers=HEADERS, timeout=15, allow_redirects=False)
    location = resp.headers.get("Location")
    if resp.is_redirect and location and is_media_url(location):
        return location
    return None


def resolve(page_url: str) -> list[str]:
    """Return ranked candidates: signed S3 MP4 first, then the page's HLS stream."""
    base = _video_base(page_url)
    candidates: list[str] = []
    try:
        mp4 = _signed_download_url(base)
        if mp4:
            candidates.append(mp4)
    except Exception as exc:
        logger.warning("Swagit download link failed for %s: %s", base, exc)
    try:
        candidates += [u for u in extract_media_urls(fetch_text(base)) if ".m3u8" in u]
    except Exception as exc:
        logger.warning("Swagit page scrape failed for %s: %s", base, exc)
    if not candidates:
        raise ValueError(f"No media found for Swagit video: {page_url}")
    logger.info("Swagit resolved: %s", candidates)
    return list(dict.fromkeys(candidates))


def fetch_transcript(page_url: str) -> str | None:
    """Return the published transcript as plain text, or None."""
    try:
        raw = fetch_text(f"{_video_base(page_url)}/transcript", timeout=60)
    except Exception as exc:
        logger.warning("Swagit transcript fetch failed for %s: %s", page_url, exc)
        return None
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        # Drop the "* This transcript was created by voice-to-text..." disclaimer
        # and the bare [HH:MM:SS] markers; agenda headings like "[3.1 ...]" stay.
        if not line or line.startswith("* ") or TIMESTAMP_LINE_RE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip() or None
