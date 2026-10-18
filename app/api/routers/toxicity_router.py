"""Toxicity check history (/toxicity) and the test-a-comment box.

The scorer itself runs in the separate `toxicity` container (toxicity/); this
router only reads what it recorded in Redis and forwards test-box requests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core import toxicity_store
from app.core.config import settings

router = APIRouter(tags=["toxicity"])
templates = Jinja2Templates(directory="app/templates")

PAGE_SIZE = 50
SOURCES = {"", "api", "manual"}
MIN_SCORES = {"": 0.0, "0.5": 0.5, "0.85": 0.85}
POLICY = {label for label, _ in toxicity_store.POLICY_LABELS}


def _checktime(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _score_class(score: float) -> str:
    # Display-only shading. Thresholds that act on scores live in the website.
    if score >= 0.85:
        return "score-high"
    if score >= 0.5:
        return "score-mid"
    return "score-low"


templates.env.filters["checktime"] = _checktime
templates.env.filters["score_class"] = _score_class


def _filters(request: Request) -> dict:
    p = request.query_params
    source = p.get("source", "")
    min_score = p.get("min", "")
    return {
        "q": p.get("q", "")[:200],
        "source": source if source in SOURCES else "",
        "min": min_score if min_score in MIN_SCORES else "",
    }


def _cursor(request: Request) -> int:
    try:
        return max(0, int(request.query_params.get("cursor", "0")))
    except ValueError:
        return 0


def _table_context(request: Request) -> dict:
    f = _filters(request)
    cursor = _cursor(request)
    checks, next_cursor = toxicity_store.list_checks(
        source=f["source"], q=f["q"], min_score=MIN_SCORES[f["min"]],
        limit=PAGE_SIZE, cursor=cursor,
    )
    active = {k: v for k, v in f.items() if v}
    return {
        "request": request,
        "checks": checks,
        "labels": toxicity_store.POLICY_LABELS,
        "f": f,
        "filtered": bool(active),
        "cursor": cursor,
        "qs": urlencode(active),
        "next_qs": urlencode({**active, "cursor": next_cursor}) if next_cursor else "",
    }


def _sorted_scores(scores: dict) -> tuple[list, list]:
    """Split a {label: score} map into policy and identity labels, each highest first."""
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return (
        [kv for kv in ranked if kv[0] in POLICY],
        [kv for kv in ranked if kv[0] not in POLICY],
    )


@router.get("/toxicity", response_class=HTMLResponse)
def ui_toxicity(request: Request):
    ctx = _table_context(request)
    ctx["stats"] = toxicity_store.stats()
    ctx["days"] = f"{settings.TOXICITY_HISTORY_DAYS:g}"
    return templates.TemplateResponse("toxicity_list.html", ctx)


@router.get("/htmx/toxicity/checks", response_class=HTMLResponse)
def htmx_toxicity_checks(request: Request):
    return templates.TemplateResponse("partials/toxicity_table.html", _table_context(request))


@router.get("/toxicity/{check_id}", response_class=HTMLResponse)
def ui_toxicity_check(request: Request, check_id: str):
    check = toxicity_store.get_check(check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found (it may have expired)")
    policy, identity = _sorted_scores(check["scores"])
    return templates.TemplateResponse(
        "toxicity_detail.html",
        {"request": request, "check": check, "policy": policy, "identity": identity},
    )


@router.post("/htmx/toxicity/test", response_class=HTMLResponse)
def htmx_toxicity_test(request: Request, text: str = Form("")):
    ctx: dict = {"request": request}
    if not text.strip():
        ctx["error"] = "Enter some text to score."
    else:
        try:
            results, check_id = toxicity_store.score_manual(text)
        except toxicity_store.ScorerError as exc:
            ctx["error"] = str(exc)
        else:
            ctx["policy"], ctx["identity"] = _sorted_scores(
                {r["label"]: r["score"] for r in results}
            )
            ctx["check_id"] = check_id
    response = templates.TemplateResponse("partials/toxicity_test_result.html", ctx)
    if "error" not in ctx:
        response.headers["HX-Trigger"] = "toxChecked"  # refresh the history table
    return response
