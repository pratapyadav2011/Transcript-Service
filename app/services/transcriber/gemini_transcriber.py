"""
Gemini Files API helpers: build a client and upload a local media file, blocking
until Gemini has finished processing it. Transcript/caption generation itself
lives in caption_generator, which consumes the uploaded handle returned here.

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


def _client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def upload_and_wait(
    client: genai.Client,
    file_path: str,
    log: Callable[[str], None] | None = None,
):
    """Upload a local file to the Gemini Files API and block until it is ready.

    Shared by the plain-transcript and caption paths. Returns the uploaded file
    handle; the caller is responsible for deleting it when done.
    """
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

    return uploaded


def _log(log: Callable[[str], None] | None, msg: str) -> None:
    logger.info(msg)
    if log:
        log(msg)
