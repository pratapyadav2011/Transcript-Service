"""
Orchestrates audio acquisition strategies in priority order:
  1. Direct HTTP download — works for plain CDN files
  2. yt-dlp  — handles YouTube, Granicus (with extractor), generic pages
  3. ffmpeg  — needed for HLS (.m3u8) playlists
Raises RuntimeError if all strategies fail.
"""
from __future__ import annotations
import os
import logging
import shutil
from typing import Callable

from app.services.downloader.binary_finder import find_ytdlp, find_ffmpeg
from app.services.downloader.ytdlp_downloader import download_audio
from app.services.downloader.direct_downloader import download_direct
from app.services.downloader.ffmpeg_extractor import extract_audio
from app.services.resolver.url_classifier import is_direct_media_url, is_hls_url

logger = logging.getLogger(__name__)

Step = Callable[[str], None]

# Containers a direct download may hand us as full video. We strip these to an
# audio-only MP3 before returning so Gemini isn't asked to ingest a multi-GB file
# (large uploads fail the Files API finalize with KeyError('file')).
_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".flv", ".ts", ".mpg", ".mpeg"}


def _unique(urls: list[str]) -> list[str]:
    return list(dict.fromkeys(urls))


def _ensure_audio(path: str, ffmpeg: str | None, log: Step) -> str:
    """If `path` is a video container, extract audio to a small MP3 and drop the
    original. Audio files are returned unchanged."""
    if os.path.splitext(path)[1].lower() not in _VIDEO_EXTS:
        return path
    if not ffmpeg:
        log("ffmpeg not found — uploading the full video as-is (large; may be slow).")
        return path
    log("Extracting audio from the downloaded video to shrink the upload...")
    audio = extract_audio(ffmpeg, path, progress_callback=log)
    shutil.rmtree(os.path.dirname(path), ignore_errors=True)  # free the big video
    log(f"Audio extracted: {os.path.basename(audio)}")
    return audio


def acquire_audio(
    candidates: list[str],
    original_url: str,
    log: Step,
) -> str:
    """
    Try each strategy in order and return the path to the downloaded audio file.
    `candidates` is the ranked list from media_resolver.
    """
    errors: list[str] = []
    ytdlp = find_ytdlp()
    ffmpeg = find_ffmpeg()

    urls_to_try = _unique(candidates + [original_url])

    # ── Strategy 1: Direct HTTP download (non-HLS media files) ──────────────
    for candidate in urls_to_try:
        if is_hls_url(candidate):
            continue
        if not is_direct_media_url(candidate):
            continue
        try:
            log(f"Trying direct download: {candidate}")
            path = download_direct(
                candidate,
                progress_callback=log,
                referer=original_url,
            )
            log(f"Direct download succeeded: {path}")
            return _ensure_audio(path, ffmpeg, log)
        except Exception as exc:
            msg = f"Direct download failed for {candidate}: {str(exc)[:200]}"
            errors.append(msg)
            log(msg)

    # ── Strategy 2: yt-dlp ──────────────────────────────────────────────────
    if ytdlp:
        # Resolved candidates first (e.g. a direct audio .mp3), with the original
        # URL as a last-resort fallback. For platform pages (Granicus/CivicClerk)
        # the original URL is a player page yt-dlp turns into a slow, fragile HLS
        # stream (thousands of fragments), so the direct file must win.
        for url in urls_to_try:
            try:
                log(f"Trying yt-dlp on: {url}")
                path = download_audio(ytdlp, url, progress_callback=log)
                log(f"yt-dlp succeeded: {path}")
                return path
            except Exception as exc:
                msg = f"yt-dlp failed for {url}: {str(exc)[:200]}"
                errors.append(msg)
                log(msg)
    else:
        errors.append("yt-dlp not found on this server")
        log("yt-dlp not found — skipping")

    # ── Strategy 3: ffmpeg (HLS / fallback) ──────────────────────────────────
    if ffmpeg:
        hls = next((c for c in candidates if is_hls_url(c)), None)
        target = hls or candidates[0] if candidates else original_url
        try:
            log(f"Trying ffmpeg on: {target}")
            path = extract_audio(ffmpeg, target, progress_callback=log)
            log(f"ffmpeg succeeded: {path}")
            return path
        except Exception as exc:
            msg = f"ffmpeg failed for {target}: {str(exc)[:200]}"
            errors.append(msg)
            log(msg)
    else:
        errors.append("ffmpeg not found on this server")
        log("ffmpeg not found — skipping")

    raise RuntimeError(
        f"All audio acquisition strategies failed. "
        f"Original URL: {original_url}. "
        f"Errors: {' | '.join(errors)}"
    )


def cleanup(path: str) -> None:
    """Remove the temp directory containing the audio file."""
    import os
    try:
        parent = os.path.dirname(path)
        if parent and os.path.isdir(parent):
            shutil.rmtree(parent, ignore_errors=True)
    except Exception:
        pass
