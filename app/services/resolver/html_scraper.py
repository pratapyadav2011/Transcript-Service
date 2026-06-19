"""Fetches HTML and extracts media URLs from a page."""
from __future__ import annotations
import re
import logging
import requests
from app.services.resolver.url_classifier import is_media_url

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

HTML_ENTITY_MAP = {
    "&amp;": "&", "&#x2F;": "/", "&#x3A;": ":",
    "&#x3F;": "?", "&#x3D;": "=",
}


def fetch_text(url: str, timeout: int = 15) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        logger.warning("fetch_text failed for %s: %s", url, exc)
        raise


def decode_entities(text: str) -> str:
    for entity, char in HTML_ENTITY_MAP.items():
        text = text.replace(entity, char)
    return text


def extract_media_urls(html: str) -> list[str]:
    decoded = decode_entities(html)
    raw = re.findall(r"https?://[^\s\"'<>\\]+", decoded)
    seen: set[str] = set()
    result: list[str] = []
    for url in raw:
        url = re.sub(r"[),;.]+$", "", url)
        if url not in seen and is_media_url(url):
            seen.add(url)
            result.append(url)
    return result
