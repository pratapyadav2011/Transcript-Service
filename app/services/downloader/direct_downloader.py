"""Downloads a direct media file URL over HTTP(S)."""
from __future__ import annotations
import os
import logging
import tempfile
from urllib.parse import urlparse
from typing import Callable
import requests

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

    headers = dict(HEADERS)
    if referer and referer != url:
        headers["Referer"] = referer

    logger.info("Downloading direct media: %s", url)

    with requests.get(url, headers=headers, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    pct = int(downloaded / total * 100)
                    progress_callback(f"Downloading... {pct}% ({downloaded // 1024 // 1024} MB)")

    if os.path.getsize(dest) == 0:
        raise RuntimeError(f"Downloaded file is empty: {url}")

    logger.info("Downloaded %d bytes to %s", os.path.getsize(dest), dest)
    return dest
