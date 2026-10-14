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
import html
import glob
import shutil
import tempfile
import logging
import subprocess
from typing import Callable

from app.services.downloader.binary_finder import find_ytdlp
from app.services.downloader.ytdlp_downloader import access_args
from app.services.downloader import proxy_fallback
from app.services.resolver.url_classifier import is_youtube_url

logger = logging.getLogger(__name__)

# Below this, treat the subtitle track as an empty/placeholder slot.
MIN_CAPTION_CHARS = 200
TIMESTAMP_RE = re.compile(r"-->")
INDEX_RE = re.compile(r"^\d+$")
HEADER_RE = re.compile(r"^(Kind|Language):", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def fetch_subtitles(url: str, log: Callable[[str], None] | None = None) -> str | None:
    """Return plain caption text for `url`, or None when no real captions exist."""
    ytdlp = find_ytdlp()
    if not ytdlp:
        return None

    tmp = tempfile.mkdtemp(prefix="transcript_subs_")

    def run(proxy: str | None) -> tuple[list[str], list[str]]:
        args = [
            ytdlp, "--skip-download", "--write-subs",
            "--sub-langs", "en.*", "--sub-format", "vtt/srt/best",
            "-o", os.path.join(tmp, "s.%(ext)s"), url,
        ]
        if is_youtube_url(url):
            # Many YouTube meeting videos only have auto-generated captions;
            # yt-dlp still prefers a manual track when one exists.
            args[1:1] = ["--write-auto-subs"]
        # Caption listing hits the same bot wall as the media download on YouTube.
        args[1:1] = access_args(proxy)
        proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
        files = glob.glob(os.path.join(tmp, "*.vtt")) + glob.glob(os.path.join(tmp, "*.srt"))
        errs = [l for l in (proc.stderr or "").splitlines() if "ERROR" in l or "WARNING" in l]
        return files, errs

    try:
        files, errs = run(None)
        if not files and errs and proxy_fallback.should_retry_via_proxy(" ".join(errs)):
            if log:
                log(f"Subtitles blocked from this server's IP "
                    f"({proxy_fallback.short_reason(errs[-1])}) — retrying via proxy...")
            files, errs = run(proxy_fallback.proxy_url())
        if not files:
            # Surface yt-dlp's reason (bot wall, 429, missing PO token...) instead
            # of silently reporting "no captions".
            if errs:
                logger.warning("yt-dlp found no subtitles for %s: %s", url, " | ".join(errs[-3:]))
                if log:
                    log(f"yt-dlp subtitle fetch: {errs[-1][:200]}")
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
        if not line or line == "WEBVTT" or line.startswith("NOTE") or HEADER_RE.match(line):
            continue
        if TIMESTAMP_RE.search(line) or INDEX_RE.match(line):
            continue
        line = html.unescape(TAG_RE.sub("", line)).strip()
        if line and (not out or out[-1] != line):
            out.append(line)
    return "\n".join(out).strip()
