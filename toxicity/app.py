"""Self-hosted toxicity scoring that speaks the Hugging Face text-classification
wire protocol, as a drop-in for the HF Inference API endpoint

    POST /models/unitary/unbiased-toxic-roberta

The model is multi-label: every score is an independent sigmoid over its own
logit. Do NOT switch this to softmax -- scores would sum to 1, shrink as more
labels fire, and the caller's thresholds (e.g. toxicity > 0.85) would quietly
stop triggering.

All policy (thresholds, label filtering) lives in the caller. This service
only turns text into numbers.

If REDIS_URL is set, each scored input (including its text) is also kept in
Redis for HISTORY_DAYS so the transcript UI's /toxicity page can list it. The
text is never written to the logs.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional, Union

import redis
import torch
from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_ID = "unitary/unbiased-toxic-roberta"
MODEL_DIR = os.environ.get("MODEL_DIR", "/opt/model")
MAX_LENGTH = 512  # model has 514 positions; 2 are reserved for RoBERTa's offset
MAX_BATCH = int(os.environ.get("MAX_BATCH", "32"))
TORCH_THREADS = int(os.environ.get("TORCH_THREADS", "2"))
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", "")

REDIS_URL = os.environ.get("REDIS_URL", "")
HISTORY_DAYS = float(os.environ.get("HISTORY_DAYS", "7"))
HISTORY_MAX = int(os.environ.get("HISTORY_MAX", "20000"))
# Read by the transcript app (app/core/toxicity_store.py); keep the names in sync.
HISTORY_INDEX = "toxicity:checks"  # sorted set: score = unix ts, member = check id
HISTORY_ITEM = "toxicity:check:"  # + id -> JSON record, expires after HISTORY_DAYS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("toxicity")

if len(SERVICE_TOKEN) < 32:
    # Fail fast: running without auth on a public endpoint is never intended.
    log.error("SERVICE_TOKEN is missing or too short (need >= 32 chars); refusing to start")
    sys.exit(1)


class _Model:
    def __init__(self) -> None:
        self.tokenizer = None
        self.model = None
        self.labels: list[str] = []
        self.loaded = threading.Event()
        # Serialise inference: concurrent forward passes would each grab
        # TORCH_THREADS threads and oversubscribe the CPUs for no gain.
        self.lock = threading.Lock()

    def load(self) -> None:
        started = time.perf_counter()
        try:
            torch.set_num_threads(TORCH_THREADS)
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
            self.model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)
            self.model.eval()
            self.labels = [self.model.config.id2label[i] for i in range(self.model.config.num_labels)]
            # Warm-up pass so the first real request doesn't pay for lazy init.
            self.score(["warm up"])
        except Exception:
            log.exception("model load failed; exiting so the container restarts")
            os._exit(1)
        self.loaded.set()
        log.info(
            "model loaded in %.0f ms (%d labels, %d threads)",
            (time.perf_counter() - started) * 1000,
            len(self.labels),
            torch.get_num_threads(),
        )

    def score(self, texts: list[str]) -> list[list[dict]]:
        """Return, per text, every label with its sigmoid score, highest first."""
        with self.lock, torch.inference_mode():
            enc = self.tokenizer(
                texts,
                truncation=True,
                max_length=MAX_LENGTH,
                padding=True,
                return_tensors="pt",
            )
            probs = torch.sigmoid(self.model(**enc).logits).tolist()
        results = []
        for row in probs:
            pairs = sorted(zip(self.labels, row), key=lambda p: p[1], reverse=True)
            results.append([{"label": label, "score": score} for label, score in pairs])
        return results


MODEL = _Model()


class _History:
    """Best-effort record of every check. Never fails or slows a scoring request
    by more than the short Redis timeout."""

    def __init__(self) -> None:
        self.client = (
            redis.from_url(REDIS_URL, socket_timeout=0.5, socket_connect_timeout=0.5)
            if REDIS_URL else None
        )

    def save(self, texts: list[str], results: list[list[dict]], source: str, duration_ms: float) -> list[str]:
        if self.client is None:
            return []
        now = time.time()
        ttl = int(HISTORY_DAYS * 86400)
        ids = []
        try:
            pipe = self.client.pipeline(transaction=False)
            for text, scores in zip(texts, results):
                check_id = uuid.uuid4().hex
                ids.append(check_id)
                record = {
                    "id": check_id,
                    "ts": now,
                    "source": source,
                    "text": text,
                    "chars": len(text),
                    "batch_size": len(texts),
                    "duration_ms": round(duration_ms, 1),
                    "top_label": scores[0]["label"],
                    "top_score": scores[0]["score"],
                    "scores": {s["label"]: s["score"] for s in scores},
                }
                pipe.set(HISTORY_ITEM + check_id, json.dumps(record), ex=ttl)
                pipe.zadd(HISTORY_INDEX, {check_id: now})
            pipe.zremrangebyscore(HISTORY_INDEX, "-inf", now - ttl)
            pipe.zremrangebyrank(HISTORY_INDEX, 0, -(HISTORY_MAX + 1))
            pipe.execute()
        except redis.RedisError as exc:
            log.warning("history not saved: %s", type(exc).__name__)
            return []
        return ids


HISTORY = _History()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load in the background so /health can answer 503 while loading.
    threading.Thread(target=MODEL.load, name="model-loader", daemon=True).start()
    if HISTORY.client is None:
        log.info("REDIS_URL not set; check history disabled")
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# ---------------------------------------------------------------------------
# Errors: every non-200 carries {"error": "..."}
# ---------------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse({"error": "invalid request"}, status_code=400)


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    return JSONResponse({"error": "internal error"}, status_code=500)


# ---------------------------------------------------------------------------
# Request logging: one line per request. Never logs the input text.
# ---------------------------------------------------------------------------


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        ms = (time.perf_counter() - started) * 1000
        state = request.state
        if request.url.path == "/health" and status == 200:
            pass  # Docker healthchecks every 30s would drown the useful lines.
        elif hasattr(state, "top_label"):
            log.info(
                "%s %s %d %.0fms inputs=%d chars=%d top=%s:%.4f",
                request.method, request.url.path, status, ms,
                state.n_inputs, state.input_chars, state.top_label, state.top_score,
            )
        else:
            log.info("%s %s %d %.0fms", request.method, request.url.path, status, ms)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class _Parameters(BaseModel):
    model_config = ConfigDict(extra="ignore")
    top_k: Optional[int] = None


class _ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")  # HF clients may send "options" etc.
    inputs: Union[str, list[str]]
    parameters: Optional[_Parameters] = None


_REQUEST = TypeAdapter(_ScoreRequest)


def require_token(request: Request) -> None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), SERVICE_TOKEN.encode()):
        raise HTTPException(401, "invalid or missing bearer token", headers={"WWW-Authenticate": "Bearer"})


@app.get("/health")
async def health():
    if not MODEL.loaded.is_set():
        return JSONResponse({"ok": False, "model_loaded": False, "error": "model loading"}, status_code=503)
    return {"ok": True, "model_loaded": True}


@app.post(f"/models/{MODEL_ID}", dependencies=[Depends(require_token)])
async def score(request: Request):
    # Body is parsed here (not via a FastAPI body param) so auth always runs
    # before we look at the payload.
    try:
        body = _REQUEST.validate_python(json.loads(await request.body()))
    except (ValueError, ValidationError):
        raise HTTPException(400, 'body must be JSON: {"inputs": "<text>" | ["<text>", ...], "parameters": {"top_k": <int>}}')

    batch = isinstance(body.inputs, list)
    texts = body.inputs if batch else [body.inputs]
    if not texts:
        raise HTTPException(400, "inputs must not be empty")
    if len(texts) > MAX_BATCH:
        raise HTTPException(400, f"at most {MAX_BATCH} inputs per request")
    if any(not t.strip() for t in texts):
        raise HTTPException(400, "inputs must not be empty or whitespace-only")

    top_k = body.parameters.top_k if body.parameters else None
    if top_k is not None and top_k < 1:
        raise HTTPException(400, "parameters.top_k must be >= 1")

    if not MODEL.loaded.is_set():
        raise HTTPException(503, "model loading")

    started = time.perf_counter()
    results = await run_in_threadpool(MODEL.score, texts)
    duration_ms = (time.perf_counter() - started) * 1000
    # The transcript UI's test box marks its own checks so they're told apart
    # from the website's.
    source = "manual" if request.headers.get("x-check-source") == "manual" else "api"
    ids = await run_in_threadpool(HISTORY.save, texts, results, source, duration_ms)

    if top_k is not None and top_k < len(MODEL.labels):
        results = [r[:top_k] for r in results]

    request.state.n_inputs = len(texts)
    request.state.input_chars = sum(len(t) for t in texts)
    request.state.top_label = results[0][0]["label"]
    request.state.top_score = results[0][0]["score"]

    headers = {"X-Check-Id": ",".join(ids)} if ids else None
    return JSONResponse(results if batch else results[0], headers=headers)
