"""Resolves a CivicClerk event page to a direct media URL via their JSON API."""
from __future__ import annotations
import json
import logging
from urllib.parse import urlparse
from app.services.resolver.html_scraper import fetch_text

logger = logging.getLogger(__name__)


def _fetch_event_media(page_url: str) -> dict:
    parsed = urlparse(page_url)
    tenant = parsed.hostname.split(".")[0]
    parts = [p for p in parsed.path.split("/") if p]

    try:
        event_idx = parts.index("event")
        event_id = parts[event_idx + 1]
    except (ValueError, IndexError):
        raise ValueError(f"Cannot parse CivicClerk event ID from URL: {page_url}")

    api_url = f"https://{tenant}.api.civicclerk.com/v1/EventsMedia/{event_id}"
    logger.info("CivicClerk API: %s", api_url)
    data = json.loads(fetch_text(api_url))
    data["_event_id"] = event_id
    return data


def resolve(page_url: str) -> str:
    data = _fetch_event_media(page_url)
    video_url = data.get("videoUrl") or data.get("externalVideoUrl")
    if not video_url:
        raise ValueError(f"No video URL found in CivicClerk API response for event {data['_event_id']}")
    logger.info("CivicClerk resolved: %s", video_url)
    return video_url


def fetch_closed_captions(page_url: str) -> str | None:
    """Return the raw SRT CivicClerk publishes for the event, or None.

    Meeting videos are often full-bitrate 1080p (a 2h meeting can be 17 GB), so
    using this caption file avoids downloading the media entirely.
    """
    try:
        data = _fetch_event_media(page_url)
        caption_url = data.get("closedCaptionUrl") or data.get("transcriptionUrl")
        if not caption_url:
            return None
        logger.info("CivicClerk captions: %s", caption_url)
        return fetch_text(caption_url, timeout=60)
    except Exception as exc:
        logger.warning("CivicClerk caption fetch failed for %s: %s", page_url, exc)
        return None
