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


def is_vimeo_url(url: str) -> bool:
    try:
        hostname = (urlparse(url).hostname or "").lower()
        return hostname == "vimeo.com" or hostname.endswith(".vimeo.com")
    except Exception:
        return False


def is_granicus_player(url: str) -> bool:
    try:
        p = urlparse(url)
        if not p.hostname or not p.hostname.lower().endswith(".granicus.com"):
            return False
        path = p.path.lower()
        if "/player/clip/" in path:
            return True
        # Legacy Granicus sites expose downloadLinks from MediaPlayer.php.
        return path.endswith("/mediaplayer.php") and bool(
            re.search(r"(?:^|&)clip_id=\d+(?:&|$)", p.query, re.IGNORECASE)
        )
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
