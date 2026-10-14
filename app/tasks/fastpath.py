"""
"Skip the audio + Gemini pipeline" fast-paths: reuse captions/subtitles that
already exist for a URL. Each returns a finished result dict, or None to tell
the task to fall back to downloading audio.
"""
from __future__ import annotations

import re

from app.core.job_store import (
    set_job_done, STEP_TRANSCRIBING, STEP_DOWNLOADING, STEP_SAVING,
)
from app.tasks import hooks
from app.services.transcriber.youtube_captions import fetch_captions
from app.services.transcriber.subtitle_extractor import (
    fetch_subtitles, _to_text, MIN_CAPTION_CHARS,
)
from app.services.resolver.civicclerk_resolver import fetch_closed_captions
from app.services.resolver import swagit_resolver, granicus_resolver


def _finalize(job_id, meeting_id, transcript_id, actor, url, text, source) -> dict:
    hooks.on_success(meeting_id, transcript_id, text, actor, source_label=url, job_id=job_id)
    set_job_done(job_id, text)
    return {"status": "done", "transcript": text, "source": source}


def try_captions(job_id, log, url, meeting_id, transcript_id, actor) -> dict | None:
    """YouTube captions via youtube-transcript-api."""
    log(STEP_TRANSCRIBING, "Checking for existing YouTube captions...")
    captions = fetch_captions(url, log=lambda m: log(STEP_TRANSCRIBING, m))
    if not captions:
        log(STEP_TRANSCRIBING, "No captions via transcript API — trying yt-dlp...")
        return None
    log(STEP_SAVING, f"Using YouTube captions ({len(captions)} chars)...")
    return _finalize(job_id, meeting_id, transcript_id, actor, url, captions, "captions")


def try_subtitles(job_id, log, url, meeting_id, transcript_id, actor) -> dict | None:
    """Embedded subtitles (e.g. Granicus HLS VTT) via yt-dlp — no media download."""
    log(STEP_TRANSCRIBING, "Checking for embedded captions/subtitles...")
    subs = fetch_subtitles(url, log=lambda m: log(STEP_TRANSCRIBING, m))
    if not subs:
        log(STEP_DOWNLOADING, "No usable captions — downloading audio for transcription...")
        return None
    log(STEP_SAVING, f"Using embedded captions ({len(subs)} chars)...")
    return _finalize(job_id, meeting_id, transcript_id, actor, url, subs, "subtitles")


def try_civicclerk_captions(job_id, log, url, meeting_id, transcript_id, actor) -> dict | None:
    """CivicClerk's published closed-caption SRT — avoids multi-GB video downloads."""
    log(STEP_TRANSCRIBING, "Checking for CivicClerk closed captions...")
    raw = fetch_closed_captions(url)
    text = _to_text(raw) if raw else ""
    if len(text) < MIN_CAPTION_CHARS:
        log(STEP_TRANSCRIBING, "No usable CivicClerk captions.")
        return None
    log(STEP_SAVING, f"Using CivicClerk closed captions ({len(text)} chars)...")
    return _finalize(job_id, meeting_id, transcript_id, actor, url, text, "captions")


def try_swagit_transcript(job_id, log, url, meeting_id, transcript_id, actor) -> dict | None:
    """Swagit's published transcript — avoids the IP-blocked Granicus stream."""
    log(STEP_TRANSCRIBING, "Checking for Swagit transcript...")
    text = swagit_resolver.fetch_transcript(url) or ""
    if len(text) < MIN_CAPTION_CHARS:
        log(STEP_TRANSCRIBING, "No usable Swagit transcript.")
        return None
    log(STEP_SAVING, f"Using Swagit transcript ({len(text)} chars)...")
    return _finalize(job_id, meeting_id, transcript_id, actor, url, text, "captions")


# A caption track that starts this far in is a fragment (e.g. a captioner joined
# late), not the meeting — transcribing the audio gives the full record instead.
MAX_CAPTION_START_SECONDS = 10 * 60
# A silence between captions longer than this means a chunk of the meeting has
# no captions (a recess or short break stays well under it).
MAX_CAPTION_GAP_SECONDS = 20 * 60
_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,]\d+"
_CUE_RE = re.compile(rf"^{_TS}\s*-->\s*{_TS}", re.MULTILINE)


def _cue_times(vtt: str) -> list[tuple[int, int]]:
    """(start, end) seconds of every cue, in file order."""
    def secs(h, m, s):
        return int(h or 0) * 3600 + int(m) * 60 + int(s)
    return [(secs(*g[:3]), secs(*g[3:])) for g in _CUE_RE.findall(vtt)]


def _hms(seconds: int) -> str:
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _caption_coverage_problem(vtt: str) -> str | None:
    """Why this caption track doesn't cover the meeting, or None if it does."""
    cues = _cue_times(vtt)
    if not cues:
        return None
    if cues[0][0] > MAX_CAPTION_START_SECONDS:
        return f"only start at {_hms(cues[0][0])}"
    for (_, prev_end), (start, _) in zip(cues, cues[1:]):
        if start - prev_end > MAX_CAPTION_GAP_SECONDS:
            return f"are missing from {_hms(prev_end)} to {_hms(start)}"
    return None


def try_granicus_captions(job_id, log, url, meeting_id, transcript_id, actor) -> dict | None:
    """Granicus /videos/{id}/captions.vtt — used only when it is a real, full
    track; empty files and late-starting fragments fall back to audio."""
    log(STEP_TRANSCRIBING, "Checking for Granicus captions...")
    raw = granicus_resolver.fetch_captions(url) or ""
    text = _to_text(raw) if raw else ""
    if len(text) < MIN_CAPTION_CHARS:
        log(STEP_TRANSCRIBING, f"Granicus captions are empty ({len(text)} chars) — using audio.")
        return None
    problem = _caption_coverage_problem(raw)
    if problem:
        log(STEP_TRANSCRIBING, f"Granicus captions {problem} — partial track, using audio.")
        return None
    log(STEP_SAVING, f"Using Granicus captions ({len(text)} chars)...")
    return _finalize(job_id, meeting_id, transcript_id, actor, url, text, "captions")
