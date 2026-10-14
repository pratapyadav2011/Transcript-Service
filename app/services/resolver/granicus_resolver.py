"""Resolves a Granicus player page URL to ranked direct media candidates."""
from __future__ import annotations
import logging
import re
from urllib.parse import urlparse, parse_qs
from app.services.resolver.html_scraper import fetch_text, extract_media_urls
from app.services.resolver.url_classifier import is_media_url, GRANICUS_VIDEOS_PATH

logger = logging.getLogger(__name__)


def _score(url: str) -> int:
    """Lower score = higher priority. Prefer audio-only files to avoid
    downloading the full video when the page exposes an audio rendition."""
    u = url.lower()
    if u.endswith(".m4a"):
        return 0
    if u.endswith(".mp3"):
        return 1
    if u.endswith(".mp4"):
        return 2
    if u.endswith(".m3u8"):
        return 3
    return 4


def normalize(page_url: str) -> str:
    """Map the newer /videos/{id}[/player] pages to /player/clip/{id}.

    They are the same clip, but /videos/{id}/player only exposes the HLS stream,
    while /player/clip/{id} also lists the downloadable MP3/MP4 — which is what
    lets the download skip the (often VM-blocked) stream.
    """
    parsed = urlparse(page_url)
    match = GRANICUS_VIDEOS_PATH.match(parsed.path)
    if not match:
        return page_url
    return f"{parsed.scheme or 'https'}://{parsed.hostname}/player/clip/{match.group(1)}"


def resolve(page_url: str) -> list[str]:
    """
    Returns a ranked list of media candidates for a Granicus player URL.
    Tries the JSON API first; falls back to HTML scraping.
    """
    page_url = normalize(page_url)
    parsed = urlparse(page_url)
    parts = parsed.path.split("/")
    clip_id = next((p for i, p in enumerate(parts) if parts[i - 1] == "clip" and p), None)

    # 1. JSON API
    if clip_id:
        api_url = f"https://{parsed.hostname}/api/clips/{clip_id}"
        try:
            import json
            raw = fetch_text(api_url, timeout=10)
            data = json.loads(raw)
            media = (
                data.get("clip_response", {}).get("mediaUrl")
                or data.get("mediaUrl")
                or data.get("media_url")
                or data.get("file")
                or data.get("mp4")
                or data.get("mp3")
            )
            if media and is_media_url(media):
                logger.info("Granicus JSON API resolved: %s", media)
                return sorted([media], key=_score)
        except Exception as exc:
            logger.debug("Granicus JSON API failed (%s), falling back to HTML", exc)

    # 2. HTML scraping
    html = fetch_text(page_url)
    candidates = [
        u for u in extract_media_urls(html)
        if "granicus.com" in urlparse(u).hostname
    ]
    if not candidates:
        raise ValueError(f"Could not extract media URL from Granicus page: {page_url}")
    ranked = sorted(set(candidates), key=_score)
    logger.info("Granicus HTML scrape found %d candidates: %s", len(ranked), ranked)
    return ranked


def clip_id(page_url: str) -> str | None:
    """Clip id from /player/clip/{id}, /videos/{id}[/player] or MediaPlayer.php?clip_id={id}."""
    parsed = urlparse(page_url)
    match = GRANICUS_VIDEOS_PATH.match(parsed.path) or re.search(r"/player/clip/(\d+)", parsed.path)
    if match:
        return match.group(1)
    ids = {k.lower(): v for k, v in parse_qs(parsed.query).items()}.get("clip_id")
    return ids[0] if ids and ids[0].isdigit() else None


def fetch_captions(page_url: str) -> str | None:
    """Return the clip's published captions.vtt, or None.

    Every clip exposes /videos/{id}/captions.vtt, but many are empty (just the
    WEBVTT header) or only a short fragment, so the caller must validate it.
    """
    cid = clip_id(page_url)
    if not cid:
        return None
    url = f"https://{urlparse(page_url).hostname}/videos/{cid}/captions.vtt"
    try:
        logger.info("Granicus captions: %s", url)
        return fetch_text(url, timeout=60)
    except Exception as exc:
        logger.warning("Granicus caption fetch failed for %s: %s", url, exc)
        return None
