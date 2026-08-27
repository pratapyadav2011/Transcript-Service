"""Resolve a public Vimeo page to its embedded, hashed player URL.

Some Vimeo pages fail in yt-dlp's page extractor while their embedded player
works normally.  The player URL also preserves the privacy hash required by
unlisted videos, so it must not be reconstructed from the numeric ID alone.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from urllib.parse import urlparse

from app.services.resolver.html_scraper import fetch_text

logger = logging.getLogger(__name__)

PLAYER_URL_RE = re.compile(
    r"https://player\.vimeo\.com/video/\d+(?:\?[^\s\"'<>\\]+)?",
    re.IGNORECASE,
)


def resolve(page_url: str) -> str:
    """Return Vimeo's embedded player URL, or the input if it is one already."""
    parsed = urlparse(page_url)
    if (parsed.hostname or "").lower() == "player.vimeo.com":
        return page_url

    page = html_lib.unescape(fetch_text(page_url)).replace(r"\/", "/")
    match = PLAYER_URL_RE.search(page)
    if not match:
        raise ValueError(f"No embedded Vimeo player URL found at: {page_url}")

    player_url = match.group(0).rstrip("),;.")
    logger.info("Vimeo resolved: %s", player_url)
    return player_url
