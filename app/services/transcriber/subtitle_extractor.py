"""
Fast-path for non-YouTube URLs: pull an existing caption/subtitle track via
yt-dlp (e.g. Granicus HLS exposes an `en` VTT) WITHOUT downloading the media,
and convert it to plain transcript text.

Many Granicus clips advertise a subtitle slot that is actually empty, so we only
return text when it clears MIN_CAPTION_CHARS; otherwise the caller falls back to
the audio → Gemini pipeline.
"""
from __future__ import annotations
import os
import re
import glob
import shutil
import tempfile
import logging
import subprocess
from typing import Callable

from app.core.config import settings
from app.services.downloader.binary_finder import find_ytdlp

logger = logging.getLogger(__name__)

# Below this, treat the subtitle track as an empty/placeholder slot.
MIN_CAPTION_CHARS = 200
TIMESTAMP_RE = re.compile(r"-->")
INDEX_RE = re.compile(r"^\d+$")
TAG_RE = re.compile(r"<[^>]+>")


def fetch_subtitles(url: str, log: Callable[[str], None] | None = None) -> str | None:
    """Return plain caption text for `url`, or None when no real captions exist."""
    ytdlp = find_ytdlp()
    if not ytdlp:
        return None

    tmp = tempfile.mkdtemp(prefix="transcript_subs_")
    args = [
        ytdlp, "--skip-download", "--write-subs",
        "--sub-langs", "en.*", "--sub-format", "vtt/srt/best",
        "--no-warnings", "-o", os.path.join(tmp, "s.%(ext)s"), url,
    ]
    if settings.MEDIA_PROXY_URL:
        args[1:1] = ["--proxy", settings.MEDIA_PROXY_URL]

    try:
        subprocess.run(args, capture_output=True, text=True, timeout=120)
        files = glob.glob(os.path.join(tmp, "*.vtt")) + glob.glob(os.path.join(tmp, "*.srt"))
        if not files:
            return None
        with open(files[0], encoding="utf-8", errors="ignore") as fh:
            text = _to_text(fh.read())
        if len(text) < MIN_CAPTION_CHARS:
            if log:
                log(f"Subtitle track is empty/placeholder ({len(text)} chars).")
            return None
        if log:
            log(f"Found embedded captions ({len(text)} chars) — skipping audio download.")
        return text
    except Exception as exc:
        logger.warning("Subtitle fetch failed for %s: %s", url, exc)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _to_text(raw: str) -> str:
    """Strip WEBVTT/SRT scaffolding to plain text, de-duping repeated lines."""
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.startswith("NOTE"):
            continue
        if TIMESTAMP_RE.search(line) or INDEX_RE.match(line):
            continue
        line = TAG_RE.sub("", line).strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return "\n".join(out).strip()
