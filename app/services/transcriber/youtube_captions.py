"""
Fast-path transcript source for YouTube: if the video already has a caption
track, fetch it directly (free, instant) instead of downloading audio and
paying for a Gemini transcription.

Returns None whenever captions are unavailable so the caller can fall back to
the audio → Gemini pipeline.
"""
from __future__ import annotations
import logging
from typing import Callable

from youtube_transcript_api import (
    YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound,
)
from app.services.resolver.url_classifier import YOUTUBE_PATTERN

logger = logging.getLogger(__name__)

PREFERRED_LANGS = ["en", "en-US", "en-GB"]


def _video_id(url: str) -> str | None:
    match = YOUTUBE_PATTERN.match(url)
    return match.group(1) if match else None


def fetch_captions(url: str, log: Callable[[str], None] | None = None) -> str | None:
    """Return the joined caption text for a YouTube URL, or None if unavailable."""
    video_id = _video_id(url)
    if not video_id:
        return None
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=PREFERRED_LANGS)
        text = "\n".join(s.text for s in fetched if s.text and s.text.strip())
        text = text.strip()
        if text and log:
            log(f"Found YouTube captions ({len(text)} chars).")
        return text or None
    except (TranscriptsDisabled, NoTranscriptFound):
        if log:
            log("No caption track for this video.")
        return None
    except Exception as exc:  # network / parsing / blocked — fall back to audio
        logger.warning("Caption fetch failed for %s: %s", video_id, exc)
        if log:
            log(f"Caption fetch failed ({str(exc)[:120]}); falling back to audio.")
        return None
