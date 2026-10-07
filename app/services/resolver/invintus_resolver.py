"""Resolve pages embedding the Invintus player (e.g. cvtv.org) to media URLs.

The page only carries a placeholder ``<div class="invintus-player"
data-eventid=...>`` plus the client ID in ``invintusConfig``; the player's JS
fetches the real media from Invintus's Event/getDetailed API. yt-dlp has no
extractor for it, so we call the same API the player uses.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from urllib.parse import parse_qs, urlparse

import requests

from app.services.resolver.html_scraper import HEADERS, fetch_text
from app.services.resolver.url_classifier import is_media_url

logger = logging.getLogger(__name__)

API_URL = "https://api.v3.invintus.com/v2/Event/getDetailed"
# Public key embedded in https://player.invintus.com/app.js (embedderAuth).
API_HEADERS = {
    **HEADERS,
    "Content-Type": "application/json",
    "authorization": "embedder",
    "wsc-api-key": "7WhiEBzijpritypp8bqcU7pfU9uicDR",
}

PLAYER_DIV_RE = re.compile(r"<div[^>]*class=\"[^\"]*invintus-player[^\"]*\"[^>]*>", re.IGNORECASE)
ATTR_RE = re.compile(r"data-(eventid|customid|clientid)=\"([^\"]+)\"", re.IGNORECASE)
CONFIG_CLIENT_RE = re.compile(r"\"clientId\"\s*:\s*\"(\d+)\"", re.IGNORECASE)


def is_invintus_player_url(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "").lower() == "player.invintus.com"
    except Exception:
        return False


def _ids_from_player_url(url: str) -> dict[str, str]:
    q = {k.lower(): v[0] for k, v in parse_qs(urlparse(url).query).items()}
    return {
        k: q[k.lower()] for k in ("clientID", "eventID", "customID") if q.get(k.lower())
    }


def _ids_from_page(page: str) -> dict[str, str]:
    div = PLAYER_DIV_RE.search(page)
    if not div:
        return {}
    attrs = {k.lower(): v for k, v in ATTR_RE.findall(div.group(0))}
    ids: dict[str, str] = {}
    if attrs.get("eventid"):
        ids["eventID"] = attrs["eventid"]
    if attrs.get("customid"):
        ids["customID"] = attrs["customid"]
    client = attrs.get("clientid")
    if not client:
        m = CONFIG_CLIENT_RE.search(page)
        client = m.group(1) if m else None
    if client:
        ids["clientID"] = client
    return ids


def page_has_invintus_player(page: str) -> bool:
    return bool(PLAYER_DIV_RE.search(page))


def resolve(page_url: str, page: str | None = None) -> list[str]:
    """Return ranked media candidates: audio MP3, video MP4, then HLS."""
    if is_invintus_player_url(page_url):
        ids = _ids_from_player_url(page_url)
    else:
        if page is None:
            page = fetch_text(page_url)
        ids = _ids_from_page(html_lib.unescape(page))

    if not ids.get("clientID") or not (ids.get("eventID") or ids.get("customID")):
        raise ValueError(f"No Invintus client/event ID found at: {page_url}")

    body = {**ids, "showStreams": True, "showDownloadLinks": True,
            "showMediaAssets": True, "includePrivate": False}
    resp = requests.post(API_URL, json=body, headers=API_HEADERS, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if (payload.get("errors") or {}).get("hasError"):
        raise ValueError(f"Invintus API error: {payload['errors'].get('message')}")
    data = payload.get("data") or {}

    downloads = data.get("downloadLinks") or {}
    streams = data.get("streamingURIs") or {}
    candidates = [
        downloads.get("audioDownloadURI"),
        downloads.get("videoDownloadURI"),
        *(a.get("fileUrl") for a in data.get("mediaAssets") or [] if a.get("type") == "video"),
        streams.get("main"),
        streams.get("backup"),
    ]
    ranked = list(dict.fromkeys(c for c in candidates if c and is_media_url(c)))
    if not ranked:
        raise ValueError(f"Invintus event has no media yet: {ids}")
    logger.info("Invintus resolved %s -> %s", ids, ranked)
    return ranked
