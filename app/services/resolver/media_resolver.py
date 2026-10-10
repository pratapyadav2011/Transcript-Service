"""
Entry point for URL resolution.
Given any URL, returns an ordered list of media candidates to try.
"""
from __future__ import annotations
import logging
from app.services.resolver.url_classifier import (
    is_granicus_player, is_civicclerk_url, is_youtube_url, is_vimeo_url, is_media_url,
    is_swagit_url,
)
from app.services.resolver.html_scraper import fetch_text
from app.services.resolver.granicus_resolver import resolve as resolve_granicus
from app.services.resolver.civicclerk_resolver import resolve as resolve_civicclerk
from app.services.resolver.vimeo_resolver import resolve as resolve_vimeo
from app.services.resolver import invintus_resolver, swagit_resolver

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

        if is_vimeo_url(url):
            logger.info("[Resolver] Vimeo URL detected")
            return [resolve_vimeo(url)]

        if is_swagit_url(url):
            logger.info("[Resolver] Swagit URL detected")
            return swagit_resolver.resolve(url)

        if invintus_resolver.is_invintus_player_url(url):
            logger.info("[Resolver] Invintus player URL detected")
            return invintus_resolver.resolve(url)

    except Exception as exc:
        logger.warning("[Resolver] Platform resolution failed (%s); using original URL", exc)

    # Pages embedding the Invintus player (e.g. cvtv.org) load media via JS,
    # which yt-dlp cannot see.
    if not (is_media_url(url) or is_youtube_url(url) or is_vimeo_url(url)
            or is_granicus_player(url) or is_civicclerk_url(url) or is_swagit_url(url)):
        try:
            page = fetch_text(url, timeout=10)
            if invintus_resolver.page_has_invintus_player(page):
                logger.info("[Resolver] Embedded Invintus player detected")
                return invintus_resolver.resolve(url, page)
        except Exception as exc:
            logger.debug("[Resolver] Embedded-player check failed (%s)", exc)

    # Generic URL — return as-is and let yt-dlp / direct download handle it
    logger.info("[Resolver] Generic URL: %s", url)
    return [url]
