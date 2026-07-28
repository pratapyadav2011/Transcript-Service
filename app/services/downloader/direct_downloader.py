"""Downloads a direct media file URL over HTTP(S)."""
from __future__ import annotations
import os
import logging
import tempfile
from urllib.parse import urlparse
from typing import Callable
import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "audio/*,video/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}
CHUNK_SIZE = 1024 * 1024  # 1 MB


def _ext_from_url(url: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lstrip(".").lower() or "mp4"


def _header_variants(*referers: str | None) -> list[dict[str, str]]:
    variants = [dict(HEADERS)]
    for referer in dict.fromkeys(ref for ref in referers if ref):
        with_referer = dict(HEADERS)
        with_referer["Referer"] = referer
        variants.append(with_referer)
    return variants


def _granicus_referer(url: str) -> str | None:
    """Derive the tenant player origin required by Granicus anti-hotlinking.

    Direct archive-video URLs use their first path segment as the tenant name,
    e.g. /danville-ca/file.mp4 -> https://danville-ca.granicus.com/.
    """
    parsed = urlparse(url)
    if parsed.hostname != "archive-video.granicus.com":
        return None
    tenant = next((part for part in parsed.path.split("/") if part), "")
    if not tenant or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in tenant.lower()):
        return None
    return f"https://{tenant.lower()}.granicus.com/"


def download_direct(
    url: str,
    progress_callback: Callable[[str], None] | None = None,
    referer: str | None = None,
) -> str:
    """
    Download a direct media URL to a temp file.
    Returns the local file path. Caller handles cleanup.
    """
    ext = _ext_from_url(url)
    tmp_dir = tempfile.mkdtemp(prefix="transcript_direct_")
    dest = os.path.join(tmp_dir, f"media.{ext}")

    if progress_callback:
        progress_callback(f"Direct HTTP download: {url}")

    logger.info("Downloading direct media: %s", url)

    proxies = None
    if settings.MEDIA_PROXY_URL:
        proxies = {
            "http": settings.MEDIA_PROXY_URL,
            "https": settings.MEDIA_PROXY_URL,
        }

    last_error: Exception | None = None
    supplied_referer = referer if referer and referer != url else None
    # Granicus can reject its full player URL while accepting the tenant origin,
    # so always try the derived origin even when the caller supplied a referer.
    for headers in _header_variants(supplied_referer, _granicus_referer(url)):
        try:
            with requests.get(
                url,
                headers=headers,
                proxies=proxies,
                stream=True,
                timeout=300,
            ) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total:
                            pct = int(downloaded / total * 100)
                            progress_callback(
                                f"Downloading... {pct}% ({downloaded // 1024 // 1024} MB)"
                            )
                last_error = None
                break
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else "unknown"
            logger.warning("Direct media request failed with HTTP %s for %s", status, url)
            if status not in (403, 429):
                break

    if last_error:
        raise last_error

    if os.path.getsize(dest) == 0:
        raise RuntimeError(f"Downloaded file is empty: {url}")

    logger.info("Downloaded %d bytes to %s", os.path.getsize(dest), dest)
    return dest
