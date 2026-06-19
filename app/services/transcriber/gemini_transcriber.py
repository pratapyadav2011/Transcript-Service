"""
Uploads an audio/video file to the Gemini Files API and generates a transcript.
Single Responsibility: given a local file path → return transcript text.

Uses the current `google-genai` SDK (the older `google-generativeai` package is
deprecated and no longer maintained).
"""
from __future__ import annotations
import os
import time
import logging
from typing import Callable

from google import genai
from google.genai import types

from app.core.config import settings
from app.services.transcriber.mime_types import ext_to_mime

logger = logging.getLogger(__name__)

TRANSCRIPT_PROMPT = (
    "Transcribe this public meeting audio accurately. "
    "Return only the transcript text, with speaker labels when they are clear. "
    "Do not add summaries, introductions, or any commentary."
)


def _client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def transcribe_file(
    file_path: str,
    log: Callable[[str], None] | None = None,
) -> str:
    """Upload `file_path` to the Gemini Files API and return the transcript text."""
    client = _client()
    mime = ext_to_mime(os.path.splitext(file_path)[1])

    _log(log, f"Uploading to Gemini Files API ({mime}): {os.path.basename(file_path)}")
    uploaded = client.files.upload(
        file=file_path, config=types.UploadFileConfig(mime_type=mime)
    )
    logger.info("Gemini file uploaded: %s state=%s", uploaded.name, uploaded.state)

    # Wait for the file to finish server-side processing.
    while uploaded.state and uploaded.state.name == "PROCESSING":
        time.sleep(3)
        uploaded = client.files.get(name=uploaded.name)
        _log(log, f"Gemini processing... state={uploaded.state.name}")

    if uploaded.state and uploaded.state.name == "FAILED":
        raise RuntimeError("Gemini rejected the audio file during processing.")

    _log(log, "Gemini file ready — generating transcript...")
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=[TRANSCRIPT_PROMPT, uploaded],
    )

    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty transcript.")
    return text


def transcribe_youtube_url(
    youtube_url: str, log: Callable[[str], None] | None = None
) -> str:
    """
    Ask Gemini to transcribe a YouTube video directly by URL, without downloading.
    Gemini fetches the media internally.
    """
    client = _client()
    _log(log, f"Sending YouTube URL directly to Gemini: {youtube_url}")
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=types.Content(parts=[
            types.Part(text=TRANSCRIPT_PROMPT),
            types.Part.from_uri(file_uri=youtube_url, mime_type="video/mp4"),
        ]),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty transcript for the YouTube URL.")
    return text


def transcribe_media_url(
    media_url: str,
    mime_type: str,
    log: Callable[[str], None] | None = None,
) -> str:
    """
    Ask Gemini to transcribe a publicly reachable media URL directly.
    Useful when the app server's IP is blocked by the media CDN.
    """
    client = _client()
    _log(log, f"Sending media URL directly to Gemini: {media_url}")
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=types.Content(parts=[
            types.Part(text=TRANSCRIPT_PROMPT),
            types.Part.from_uri(file_uri=media_url, mime_type=mime_type),
        ]),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty transcript for the media URL.")
    return text


def _log(log: Callable[[str], None] | None, msg: str) -> None:
    logger.info(msg)
    if log:
        log(msg)
