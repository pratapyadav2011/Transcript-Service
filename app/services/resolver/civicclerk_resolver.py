"""Resolves a CivicClerk event page to a direct media URL via their JSON API."""
from __future__ import annotations
import json
import logging
from urllib.parse import urlparse
from app.services.resolver.html_scraper import fetch_text

logger = logging.getLogger(__name__)


def resolve(page_url: str) -> str:
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
    raw = fetch_text(api_url)
    data = json.loads(raw)

    video_url = data.get("videoUrl") or data.get("externalVideoUrl")
    if not video_url:
        raise ValueError(f"No video URL found in CivicClerk API response for event {event_id}")
    logger.info("CivicClerk resolved: %s", video_url)
    return video_url
