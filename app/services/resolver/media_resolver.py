"""
Entry point for URL resolution.
Given any URL, returns an ordered list of media candidates to try.
"""
from __future__ import annotations
import logging
from app.services.resolver.url_classifier import (
    is_granicus_player, is_civicclerk_url, is_youtube_url,
)
from app.services.resolver.granicus_resolver import resolve as resolve_granicus
from app.services.resolver.civicclerk_resolver import resolve as resolve_civicclerk

logger = logging.getLogger(__name__)


def resolve_candidates(url: str) -> list[str]:
    """
    Returns a ranked list of candidate media URLs to attempt downloading.
    For plain URLs (YouTube, direct files) the original URL is returned as-is —
    yt-dlp handles them natively.
    """
    try:
        if is_granicus_player(url):
            logger.info("[Resolver] Granicus player URL detected")
            return resolve_granicus(url)

        if is_civicclerk_url(url):
            logger.info("[Resolver] CivicClerk URL detected")
            resolved = resolve_civicclerk(url)
            return [resolved]

        if is_youtube_url(url):
            logger.info("[Resolver] YouTube URL detected")
            return [url]

    except Exception as exc:
        logger.warning("[Resolver] Platform resolution failed (%s); using original URL", exc)

    # Generic URL — return as-is and let yt-dlp / direct download handle it
    logger.info("[Resolver] Generic URL: %s", url)
    return [url]
