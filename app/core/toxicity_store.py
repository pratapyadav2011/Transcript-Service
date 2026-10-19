"""
Read side of the toxicity scorer's check history, plus the test-box call.

The scorer (toxicity/app.py) writes, per scored comment:
  toxicity:check:{id}  — JSON { id, ts, source, text, chars, batch_size,
                                duration_ms, top_label, top_score, scores{label: score} }
                         expiring after TOXICITY_HISTORY_DAYS
  toxicity:checks      — sorted set  score=ts, member=id

Keep these key names in sync with toxicity/app.py.
"""
from __future__ import annotations

import json
import time

import httpx

from app.core.config import settings
from app.core.redis_client import get_redis

INDEX_KEY = "toxicity:checks"
ITEM_PREFIX = "toxicity:check:"
MODEL_PATH = "/models/unitary/unbiased-toxic-roberta"

# The labels the website acts on, in display order. The other 9 are identity
# labels, shown only on a check's detail page.
POLICY_LABELS = [
    ("toxicity", "Toxic"),
    ("severe_toxicity", "Severe"),
    ("obscene", "Obscene"),
    ("threat", "Threat"),
    ("insult", "Insult"),
    ("identity_attack", "Identity"),
    ("sexual_explicit", "Sexual"),
]

# How many history entries to read from Redis per round trip while filtering.
_SCAN_CHUNK = 200


def max_policy_score(check: dict) -> float:
    scores = check.get("scores", {})
    return max((scores.get(label, 0.0) for label, _ in POLICY_LABELS), default=0.0)


def _matches(check: dict, source: str, q: str, min_score: float) -> bool:
    if source and check.get("source") != source:
        return False
    if q and q not in check.get("text", "").lower():
        return False
    if min_score and max_policy_score(check) < min_score:
        return False
    return True


def list_checks(
    *, source: str = "", q: str = "", min_score: float = 0.0,
    limit: int = 50, cursor: int = 0,
) -> tuple[list[dict], int | None]:
    """Newest-first checks matching the filters.

    `cursor` is a position in the index (0 = newest). Returns the page and the
    cursor for the next page, or None when there are no older matches.
    """
    r = get_redis()
    q = q.strip().lower()
    found: list[dict] = []
    pos = cursor
    while len(found) < limit:
        ids = r.zrevrange(INDEX_KEY, pos, pos + _SCAN_CHUNK - 1)
        if not ids:
            return found, None
        raw = r.mget([ITEM_PREFIX + i for i in ids])
        for offset, item in enumerate(raw):
            if item is None:  # expired, index not yet pruned
                continue
            check = json.loads(item)
            if _matches(check, source, q, min_score):
                found.append(check)
                if len(found) == limit:
                    next_pos = pos + offset + 1
                    return found, next_pos if r.zcard(INDEX_KEY) > next_pos else None
        pos += len(ids)
    return found, None


def get_check(check_id: str) -> dict | None:
    raw = get_redis().get(ITEM_PREFIX + check_id)
    return json.loads(raw) if raw else None


def stats() -> dict:
    r = get_redis()
    now = time.time()
    return {
        "total": r.zcard(INDEX_KEY),
        "last_hour": r.zcount(INDEX_KEY, now - 3600, "+inf"),
        "last_day": r.zcount(INDEX_KEY, now - 86400, "+inf"),
    }


class ScorerError(Exception):
    pass


def score_manual(text: str) -> tuple[list[dict], str | None]:
    """Score `text` with the scorer, recorded in history as a manual check.

    Returns all 16 labels (highest first) and the new check's id, if saved.
    """
    if not settings.API_SERVICE_TOKEN:
        raise ScorerError("API_SERVICE_TOKEN is not set for the web container")
    try:
        resp = httpx.post(
            settings.TOXICITY_URL.rstrip("/") + MODEL_PATH,
            json={"inputs": text, "parameters": {"top_k": None}},
            headers={
                "Authorization": f"Bearer {settings.API_SERVICE_TOKEN}",
                "X-Check-Source": "manual",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise ScorerError(f"scorer unreachable at {settings.TOXICITY_URL}: {type(exc).__name__}")
    if resp.status_code != 200:
        try:
            detail = resp.json().get("error", resp.text)
        except ValueError:
            detail = resp.text
        raise ScorerError(f"scorer returned {resp.status_code}: {detail}")
    return resp.json(), resp.headers.get("X-Check-Id") or None
