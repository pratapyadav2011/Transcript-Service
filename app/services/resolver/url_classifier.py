"""Classifies and normalises URLs before resolution."""
from __future__ import annotations
import re
from urllib.parse import urlparse


MEDIA_EXTENSIONS = re.compile(
    r"\.(m3u8|mp4|m4a|mp3|webm|aac|wav|flac|ogg|opus)$", re.IGNORECASE
)
DIRECT_EXTENSIONS = re.compile(
    r"\.(mp4|m4a|mp3|webm|aac|wav|flac|ogg|opus)$", re.IGNORECASE
)
YOUTUBE_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/watch\?.*v=|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def is_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_PATTERN.match(url))


def is_granicus_player(url: str) -> bool:
    try:
        p = urlparse(url)
        return ".granicus.com" in p.hostname and "/player/clip/" in p.path
    except Exception:
        return False


def is_civicclerk_url(url: str) -> bool:
    try:
        return urlparse(url).hostname.endswith(".portal.civicclerk.com")
    except Exception:
        return False


def is_platform_url(url: str) -> bool:
    """URLs whose media CDN requires server-side auth (cannot be fetched by Gemini directly)."""
    return is_granicus_player(url) or is_civicclerk_url(url)


def is_media_url(url: str) -> bool:
    try:
        return bool(MEDIA_EXTENSIONS.search(urlparse(url).path))
    except Exception:
        return False


def is_direct_media_url(url: str) -> bool:
    """Direct downloadable file (no HLS playlist)."""
    try:
        return bool(DIRECT_EXTENSIONS.search(urlparse(url).path))
    except Exception:
        return False


def is_hls_url(url: str) -> bool:
    try:
        return ".m3u8" in urlparse(url).path.lower()
    except Exception:
        return False
