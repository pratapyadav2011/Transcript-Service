"""Convert faster-whisper word timings into compact CivicClerk-style SRT."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimedWord:
    start: float
    end: float
    text: str


def segments_to_srt(
    segments,
    max_line_chars: int = 42,
    max_cue_seconds: float = 7.0,
    preferred_cue_seconds: float = 3.5,
) -> str:
    words = _timed_words(segments)
    cues = _build_cues(words, max_line_chars, max_cue_seconds, preferred_cue_seconds)
    if not cues:
        raise RuntimeError("Whisper returned no spoken words.")

    blocks = []
    for index, cue in enumerate(cues, 1):
        lines = _wrap_two_lines(cue[2], max_line_chars)
        blocks.append(
            f"{index}\n{_timestamp(cue[0])} --> {_timestamp(cue[1])}\n{lines}"
        )
    return "\n\n".join(blocks).strip() + "\n"


def _timed_words(segments) -> list[TimedWord]:
    result: list[TimedWord] = []
    for segment in segments:
        segment_words = getattr(segment, "words", None) or []
        if segment_words:
            for word in segment_words:
                text = str(getattr(word, "word", "")).strip()
                if text:
                    result.append(TimedWord(float(word.start), float(word.end), text))
            continue

        # Defensive fallback if a backend omits word timestamps: distribute the
        # segment's words across its duration so SRT generation can still finish.
        tokens = str(getattr(segment, "text", "")).strip().split()
        if not tokens:
            continue
        start, end = float(segment.start), float(segment.end)
        step = max(0.01, (end - start) / len(tokens))
        for i, token in enumerate(tokens):
            result.append(TimedWord(start + i * step, min(end, start + (i + 1) * step), token))
    return result


def _build_cues(words, width, max_seconds, preferred_seconds):
    cues: list[tuple[float, float, str]] = []
    current: list[TimedWord] = []
    max_chars = width * 2

    def flush():
        if current:
            cues.append((current[0].start, current[-1].end, _join(current)))
            current.clear()

    for word in words:
        if current:
            candidate = _join(current + [word])
            duration = word.end - current[0].start
            gap = word.start - current[-1].end
            if gap >= 1.25 or len(candidate) > max_chars or duration > max_seconds:
                flush()
        current.append(word)
        text = _join(current)
        duration = current[-1].end - current[0].start
        if duration >= preferred_seconds and text.endswith((".", "?", "!", ";", ":")):
            flush()
        elif len(text) >= int(max_chars * 0.85) and text.endswith((",", ".", "?", "!")):
            flush()
    flush()
    return cues


def _join(words: list[TimedWord]) -> str:
    text = " ".join(word.text for word in words)
    for punctuation in (".", ",", "?", "!", ";", ":", "%", ")", "]"):
        text = text.replace(" " + punctuation, punctuation)
    return text.replace("( ", "(").replace("[ ", "[").strip()


def _wrap_two_lines(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    words = text.split()
    candidates = []
    for i in range(1, len(words)):
        left, right = " ".join(words[:i]), " ".join(words[i:])
        if len(left) <= width and len(right) <= width:
            candidates.append((abs(len(left) - len(right)), left, right))
    if candidates:
        _, left, right = min(candidates, key=lambda item: item[0])
        return f"{left}\n{right}"
    # A single unusually long word or phrase may exceed the visual target.
    midpoint = max(1, len(words) // 2)
    return " ".join(words[:midpoint]) + "\n" + " ".join(words[midpoint:])


def _timestamp(seconds: float) -> str:
    milliseconds = int(round(max(0.0, seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
