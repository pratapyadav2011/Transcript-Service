"""
"Skip the audio + Gemini pipeline" fast-paths: reuse captions/subtitles that
already exist for a URL. Each returns a finished result dict, or None to tell
the task to fall back to downloading audio.
"""
from __future__ import annotations

from app.core.job_store import (
    set_job_done, STEP_TRANSCRIBING, STEP_DOWNLOADING, STEP_SAVING,
)
from app.tasks import hooks
from app.services.transcriber.youtube_captions import fetch_captions
from app.services.transcriber.subtitle_extractor import fetch_subtitles


def _finalize(job_id, meeting_id, transcript_id, actor, url, text, source) -> dict:
    hooks.on_success(meeting_id, transcript_id, text, actor, source_label=url)
    set_job_done(job_id, text)
    return {"status": "done", "transcript": text, "source": source}


def try_captions(job_id, log, url, meeting_id, transcript_id, actor) -> dict | None:
    """YouTube captions via youtube-transcript-api."""
    log(STEP_TRANSCRIBING, "Checking for existing YouTube captions...")
    captions = fetch_captions(url, log=lambda m: log(STEP_TRANSCRIBING, m))
    if not captions:
        log(STEP_DOWNLOADING, "No captions found — downloading audio for Gemini...")
        return None
    log(STEP_SAVING, f"Using YouTube captions ({len(captions)} chars)...")
    return _finalize(job_id, meeting_id, transcript_id, actor, url, captions, "captions")


def try_subtitles(job_id, log, url, meeting_id, transcript_id, actor) -> dict | None:
    """Embedded subtitles (e.g. Granicus HLS VTT) via yt-dlp — no media download."""
    log(STEP_TRANSCRIBING, "Checking for embedded captions/subtitles...")
    subs = fetch_subtitles(url, log=lambda m: log(STEP_TRANSCRIBING, m))
    if not subs:
        log(STEP_DOWNLOADING, "No usable captions — downloading audio for Gemini...")
        return None
    log(STEP_SAVING, f"Using embedded captions ({len(subs)} chars)...")
    return _finalize(job_id, meeting_id, transcript_id, actor, url, subs, "subtitles")
