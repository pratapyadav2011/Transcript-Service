"""
Direct-first, proxy-on-block policy shared by every downloader.

Every request first goes out from the server's own IP. Only when the failure
looks like the site blocking that (datacenter) IP — 401/403/429, YouTube's bot
wall, Vimeo's logged-in-only error — is it retried once through
MEDIA_PROXY_URL (e.g. the home residential proxy). Ordinary failures such as
404s or missing formats are never retried, so the proxy's (home) bandwidth is
only spent on requests that need it.
"""
from __future__ import annotations

import requests

from app.core.config import settings

BLOCKED_STATUS_CODES = {401, 403, 429}

# Lower-cased substrings that mean "this IP was refused" in yt-dlp output,
# requests errors and youtube-transcript-api exception names.
BLOCK_MARKERS = (
    "http error 401", "http error 403", "http error 429",
    "401 unauthorized", "403 forbidden", "429 too many requests",
    "401 client error", "403 client error", "429 client error",
    "too many requests",
    "not a bot", "sign in to confirm",
    "only works when logged-in",
    "requestblocked", "ipblocked",
    # Downstream symptom of YouTube's bot wall: no formats get extracted.
    "requested format is not available",
)


def proxy_url() -> str:
    return settings.MEDIA_PROXY_URL


def is_blocked(error: BaseException | str) -> bool:
    """True when `error` looks like the site refusing this server's IP."""
    if isinstance(error, requests.HTTPError) and error.response is not None:
        if error.response.status_code in BLOCKED_STATUS_CODES:
            return True
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    text = text.lower()
    return any(marker in text for marker in BLOCK_MARKERS)


def should_retry_via_proxy(error: BaseException | str) -> bool:
    """True when a proxy is configured and `error` is an IP block."""
    return bool(proxy_url()) and is_blocked(error)


def short_reason(error: BaseException | str, limit: int = 120) -> str:
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return text.strip().splitlines()[0][:limit] if text.strip() else "blocked"
