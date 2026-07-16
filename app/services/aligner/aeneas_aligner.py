"""
Forced alignment with aeneas: given the correct transcript text and the audio,
compute an accurate timestamp for every line and emit an SRT.

This is the "when" half of the transcript. Gemini supplies the "what" (the words);
aeneas anchors each line to the audio waveform. Because it is *given* the correct
text, it only has to find WHERE each line is spoken — far more accurate than any
model estimating time from scratch.

aeneas is invoked via its CLI (`aeneas.tools.execute_task`) with plain-text input,
one fragment per line, and produces an SRT directly.
"""
from __future__ import annotations
import os
import sys
import shutil
import logging
import subprocess
import tempfile
from typing import Callable

logger = logging.getLogger(__name__)

# aeneas can be slow on long audio; cap so a stuck run cannot hang a worker forever.
_ALIGN_TIMEOUT_SEC = 1800


def align_fragments_to_srt(
    audio_path: str,
    fragments: list[str],
    language: str = "eng",
    log: Callable[[str], None] | None = None,
) -> str:
    """Force-align `fragments` (one caption line each) to `audio_path` → SRT text.

    Raises RuntimeError on any failure so the caller can fall back to another
    timestamp source.
    """
    clean = [f.strip().replace("\n", " ") for f in fragments if f and f.strip()]
    if not clean:
        raise ValueError("No text fragments to align")

    tmp = tempfile.mkdtemp(prefix="transcript_align_")
    try:
        text_path = os.path.join(tmp, "fragments.txt")
        srt_path = os.path.join(tmp, "aligned.srt")
        with open(text_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(clean))

        # is_text_type=plain → each input LINE is one alignment fragment / cue.
        config = f"task_language={language}|is_text_type=plain|os_task_file_format=srt"
        args = [
            sys.executable, "-m", "aeneas.tools.execute_task",
            audio_path, text_path, config, srt_path,
        ]

        if log:
            log(f"Forced-aligning {len(clean)} lines to the audio (aeneas)...")
        logger.info("aeneas cmd: %s", " ".join(args))

        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=_ALIGN_TIMEOUT_SEC
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise RuntimeError(f"aeneas alignment failed (exit {proc.returncode}): {detail}")

        if not os.path.exists(srt_path) or os.path.getsize(srt_path) == 0:
            raise RuntimeError("aeneas produced no SRT output")

        with open(srt_path, encoding="utf-8") as fh:
            srt = fh.read().strip()
        if not srt:
            raise RuntimeError("aeneas produced an empty SRT")

        if log:
            log("Forced alignment complete — timestamps anchored to the audio.")
        return srt + "\n"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
