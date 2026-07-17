"""
Generates a subtitle/caption file (SRT or WebVTT) from an audio/video file
using Gemini.

This asks Gemini for time-coded *cues* — each with a start and end time — using
JSON mode, then formats them either as a plain timestamped transcript (for
storage) or as a standard SRT/WebVTT caption file.

Why JSON mode + temperature 0:
  - Structured output gives machine-parseable start/end times instead of
    free-text we would have to regex out of prose.
  - Temperature 0 keeps Gemini faithful (verbatim) instead of paraphrasing,
    which is what makes the output match the real spoken words / captions.
"""
from __future__ import annotations
import json
import logging
from typing import Callable

from google.genai import types

from app.core.config import settings
from app.services.transcriber.gemini_transcriber import _client, upload_and_wait

logger = logging.getLogger(__name__)

CAPTION_PROMPT = (
    "You are creating a closed-caption file for this public meeting recording.\n"
    "Transcribe the audio VERBATIM — word for word, exactly as spoken. Do not "
    "paraphrase, summarise, translate, correct grammar, or skip any speech.\n"
    "Split the transcript into short caption cues, each one or two sentences "
    "(roughly 2–7 seconds of speech), the way broadcast subtitles are segmented.\n"
    "For every cue return:\n"
    "  - start: seconds elapsed from the very start of the audio when the cue "
    "begins (0 = the first instant of the file).\n"
    "  - end: seconds elapsed when the cue ends.\n"
    "  - speaker: the speaker's name or role if clearly identifiable (e.g. "
    "'Chair', 'Mr. Smith'); otherwise an empty string.\n"
    "  - text: only the exact words spoken during this cue — no speaker name, "
    "label, or prefix.\n"
    "Cover the ENTIRE recording from start to finish with no gaps; timestamps "
    "must be in order and never overlap. Mark unclear audio as [inaudible] "
    "rather than guessing."
)

# Schema Gemini must return: an ordered array of caption cues.
_CAPTION_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        required=["start", "end", "text"],
        properties={
            "start": types.Schema(type=types.Type.NUMBER),
            "end": types.Schema(type=types.Type.NUMBER),
            "speaker": types.Schema(type=types.Type.STRING),
            "text": types.Schema(type=types.Type.STRING),
        },
    ),
)


_FORMATTERS = {}  # populated below, after the formatter funcs are defined


def generate_captions(
    file_path: str,
    fmt: str = "text",
    log: Callable[[str], None] | None = None,
) -> str:
    """Upload `file_path` and return time-coded output as text.

    `fmt`:
      - "text" (default): a plain timestamped transcript ([HH:MM:SS] Speaker: …),
        suitable for saving straight into Mongo/Redis like a normal transcript.
      - "srt" / "vtt": a standard subtitle file to attach as a sidecar.
    """
    if fmt not in _FORMATTERS:
        raise ValueError(
            f"Unsupported format: {fmt!r} (use {', '.join(sorted(_FORMATTERS))})"
        )

    client = _client()
    uploaded = upload_and_wait(client, file_path, log)

    _log(log, "Gemini file ready — generating time-coded captions...")
    try:
        return _generate_and_format(client, [CAPTION_PROMPT, uploaded], fmt, log)
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass


def generate_captions_from_url(
    media_url: str,
    mime_type: str,
    fmt: str = "text",
    log: Callable[[str], None] | None = None,
) -> str:
    """Same verbatim, time-coded output as `generate_captions`, but Gemini fetches
    a publicly reachable media URL directly instead of us uploading a local file.

    Used as the fallback when the server cannot download the media itself.
    """
    if fmt not in _FORMATTERS:
        raise ValueError(
            f"Unsupported format: {fmt!r} (use {', '.join(sorted(_FORMATTERS))})"
        )

    client = _client()
    _log(log, f"Asking Gemini to caption the media URL directly: {media_url}")
    contents = types.Content(parts=[
        types.Part(text=CAPTION_PROMPT),
        types.Part.from_uri(file_uri=media_url, mime_type=mime_type),
    ])
    return _generate_and_format(client, contents, fmt, log)


def generate_aligned_srt(
    file_path: str,
    language: str = "eng",
    log: Callable[[str], None] | None = None,
) -> str:
    """Best-accuracy SRT: Gemini supplies the words, forced alignment (aeneas)
    supplies the timestamps by anchoring each line to the audio waveform.

    Raises if alignment is unavailable/fails so the caller can fall back to
    Gemini's own (approximate) timestamps.
    """
    from app.services.aligner.aeneas_aligner import align_fragments_to_srt

    cues = get_caption_cues(file_path, log)
    fragments = [c["text"] for c in cues if c["text"].strip()]
    _log(log, f"Gemini transcribed {len(fragments)} lines; force-aligning to audio...")
    if len(fragments) < 5:
        _log(log, "Warning: Gemini returned very few lines — the audio may be "
                  "near-silent, music, or only partially transcribed.")
    return align_fragments_to_srt(file_path, fragments, language=language, log=log)


def get_caption_cues(
    file_path: str,
    log: Callable[[str], None] | None = None,
) -> list[dict]:
    """Upload `file_path` and return Gemini's caption cues (start/end/speaker/text).

    Exposed so the forced-alignment path can take just the *words* and re-time them
    against the audio, ignoring Gemini's own (approximate) timestamps.
    """
    client = _client()
    uploaded = upload_and_wait(client, file_path, log)
    _log(log, "Gemini file ready — generating transcript text...")
    try:
        return _generate_cues(client, [CAPTION_PROMPT, uploaded], log)
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass


def _generate_cues(client, contents, log) -> list[dict]:
    """Run Gemini with the caption prompt/schema and return parsed cues."""
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=_CAPTION_SCHEMA,
            max_output_tokens=65536,
            # Transcription needs no reasoning. gemini-2.5-flash thinks by default,
            # and those tokens count against max_output_tokens — which was starving
            # the JSON and truncating it mid-string. Disable thinking entirely.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    cues = _parse_cues(response.text)
    if not cues:
        raise RuntimeError("Gemini returned no caption cues.")

    if _was_truncated(response):
        _log(log, f"Gemini output hit the token limit; kept the first {len(cues)} "
                  f"cues. Very long recordings may transcribe only partially.")
    return cues


def _generate_and_format(client, contents, fmt: str, log) -> str:
    """Run Gemini and format the cues to `fmt`."""
    cues = _generate_cues(client, contents, log)
    _log(log, f"Formatting {len(cues)} caption cues as {fmt}...")
    return _FORMATTERS[fmt](cues)


def _was_truncated(response) -> bool:
    """True when Gemini stopped because it hit the output token limit."""
    try:
        return "MAX_TOKENS" in str(response.candidates[0].finish_reason)
    except (AttributeError, IndexError, TypeError):
        return False


def _loads_lenient(raw: str | None) -> list:
    """json.loads, but tolerate a truncated array by keeping the complete objects.

    When Gemini's output is cut off at the token limit the trailing object is
    half-written; we back up to the last complete `}` and close the array so the
    finished cues are still usable.
    """
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        pass
    cut = text.rfind("}")
    while cut != -1:
        try:
            return json.loads(text[: cut + 1] + "]")
        except json.JSONDecodeError:
            cut = text.rfind("}", 0, cut)
    return []


def _parse_cues(raw: str | None) -> list[dict]:
    """Parse Gemini's JSON, keep only sane cues, and sort by start time."""
    data = _loads_lenient(raw)

    cues: list[dict] = []
    for item in data:
        try:
            start = float(item["start"])
            end = float(item["end"])
            text = str(item.get("text", "")).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not text or end < start:
            continue
        cues.append({
            "start": max(0.0, start),
            "end": max(start, end),
            "speaker": str(item.get("speaker", "")).strip(),
            "text": text,
        })
    cues.sort(key=lambda c: c["start"])
    return cues


def _fmt_ts(seconds: float, sep: str) -> str:
    """Format seconds as HH:MM:SS<sep>mmm ("," for SRT, "." for VTT)."""
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _fmt_clock(seconds: float) -> str:
    """Format seconds as HH:MM:SS (no milliseconds), for readable transcript text."""
    s = int(round(max(0.0, seconds)))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def to_transcript_text(cues: list[dict]) -> str:
    """Format cues as a plain timestamped transcript for storage: one line per
    caption cue, "[HH:MM:SS] spoken words" — the exact words from the audio, with
    no speaker names or labels added.
    """
    lines = [f"[{_fmt_clock(cue['start'])}] {cue['text']}" for cue in cues]
    return "\n".join(lines).strip() + "\n"


def to_srt(cues: list[dict]) -> str:
    """Format cues as SubRip (.srt) — index / start --> end / text, exactly the
    shape a CivicClerk caption file uses. No speaker labels are added."""
    blocks = []
    for i, cue in enumerate(cues, 1):
        head = f"{_fmt_ts(cue['start'], ',')} --> {_fmt_ts(cue['end'], ',')}"
        blocks.append(f"{i}\n{head}\n{cue['text']}\n")
    return "\n".join(blocks).strip() + "\n"


def to_vtt(cues: list[dict]) -> str:
    """Format cues as WebVTT (.vtt)."""
    out = ["WEBVTT", ""]
    for cue in cues:
        out.append(f"{_fmt_ts(cue['start'], '.')} --> {_fmt_ts(cue['end'], '.')}")
        out.append(f"<v {cue['speaker']}>{cue['text']}" if cue["speaker"] else cue["text"])
        out.append("")
    return "\n".join(out).strip() + "\n"


_FORMATTERS.update({
    "text": to_transcript_text,
    "srt": to_srt,
    "vtt": to_vtt,
})


def _log(log: Callable[[str], None] | None, msg: str) -> None:
    logger.info(msg)
    if log:
        log(msg)
