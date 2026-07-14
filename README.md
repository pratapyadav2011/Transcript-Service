# Transcript Service

A self-hosted Python app that takes **any video URL** (YouTube / YouTube Live,
Granicus, CivicClerk, or any page with a media stream) **or an uploaded
audio/video file**, extracts the audio, and generates a transcript with
Google **Gemini**. Every job runs in the background with a live, step-by-step
log and a dashboard to pause / resume / stop / rerun jobs.

## Architecture

```
Browser ──HTTP──► FastAPI (web)  ──enqueue──►  Redis  ──►  Celery worker
   ▲                  │                                        │
   │  HTMX polling    │ step logs + status (Redis)             │ resolve → download
   └──────────────────┴────────────────────────────────────────┘ extract → Gemini → save
```

- **FastAPI** — REST API + server-rendered UI (Jinja2 + HTMX, no JS build step).
- **Celery + Redis** — background job queue; one job = one Celery task.
- **Redis job store** — per-job status, capped step log, cooperative control flag.
- **yt-dlp / ffmpeg / direct HTTP** — layered audio-acquisition strategies.
- **Gemini Files API** — audio → transcript.
- **MongoDB (optional)** — writes transcript/status back to the Next.js app's collections.

Code is modular (SOLID, one responsibility per file, every file < 200 lines).

## Pipeline steps (shown live in the UI)

`QUEUED → RESOLVING (search) → FOUND → DOWNLOADING / EXTRACTING → UPLOADING → TRANSCRIBING → SAVING → DONE`

**YouTube fast-path:** if a YouTube video already has a caption track, the
transcript is pulled directly (free, instant) via `youtube-transcript-api` and
the audio-download + Gemini steps are skipped. Anything without captions
(YouTube Live, Granicus, CivicClerk, uploads) goes through the full audio →
Gemini pipeline.

Transcription uses the current **`google-genai`** SDK (the older
`google-generativeai` package is deprecated).

## Run with Docker (recommended for a VM)

```bash
cp .env.example .env          # fill in GEMINI_API_KEY (MongoDB optional)
docker compose up -d --build  # starts redis + web + worker + flower
```

- App UI:        http://SERVER_IP:8000
- All jobs:      http://SERVER_IP:8000/jobs
- Flower (queue) http://SERVER_IP:5555
- Health check:  http://SERVER_IP:8000/api/health

Scale workers (for concurrent jobs): `docker compose up -d --scale worker=3`.

## Run locally (without Docker)

Requires Python 3.11, `ffmpeg`, and `yt-dlp` on PATH, plus a running Redis.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set GEMINI_API_KEY

# Terminal 1 — web
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# Terminal 2 — worker
celery -A app.core.celery_app worker --loglevel=info --concurrency=2
# Terminal 3 — (optional) queue monitor
celery -A app.core.celery_app flower --port=5555
```

## Securing the service (no login)

The whole service is gated by a single shared secret, `API_SECRET_KEY`. There
are no user accounts — your website is the only thing that can let people in.

1. Set a strong secret in `.env`: `API_SECRET_KEY=$(openssl rand -hex 32)`.
2. Put the **same value** in your website's backend env (e.g. `TRANSCRIPT_API_SECRET`).
3. Restart. Unauthenticated requests now get `401`; `/api/health` and `/static`
   stay public. (If the secret is left blank, auth is disabled for local dev.)

A request is authorized by any of: the `X-API-Key` header, an
`Authorization: Bearer <token>` header, a `?token=` query param, or the
`ts_session` cookie a valid `?token=` sets.

**Token = HMAC-SHA256 of an expiry timestamp**, so your website mints it locally
without calling this service:

```
token = "<expiry_unix>.<hmac_sha256(API_SECRET_KEY, expiry_unix)>"
```

Next.js / Node:

```js
import crypto from "crypto";
const SECRET = process.env.TRANSCRIPT_API_SECRET;

export function makeTranscriptToken(ttlSeconds = 3600) {
  const expiry = String(Math.floor(Date.now() / 1000) + ttlSeconds);
  const sig = crypto.createHmac("sha256", SECRET).update(expiry).digest("hex");
  return `${expiry}.${sig}`;
}
```

Use it:

```js
// A) server → service: just send the static secret
fetch("https://transcripts.example.com/api/transcript/url", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": SECRET },
  body: JSON.stringify({ url }),
});

// B) send a user into the dashboard (sets an 8h cookie automatically)
redirect(`https://transcripts.example.com/?token=${makeTranscriptToken(28800)}`);
```

- `X-API-Key` never expires — server-to-server only, never expose to browsers.
- Signed tokens expire — safe to put in a URL handed to a browser.
- Quick local test token: `python -m app.gen_token 3600`.

## API

| Method | Path                       | Purpose                          |
|--------|----------------------------|----------------------------------|
| POST   | `/api/transcript/url`      | Submit a URL job                 |
| POST   | `/api/transcript/upload`   | Submit a file-upload job         |
| GET    | `/api/jobs`                | List jobs                        |
| GET    | `/api/jobs/{id}/logs`      | Full step log                    |
| GET    | `/api/jobs/{id}/transcript` | Get the complete saved transcript |
| POST   | `/api/jobs/{id}/pause`     | Pause a running job              |
| POST   | `/api/jobs/{id}/resume`    | Resume a paused job              |
| POST   | `/api/jobs/{id}/stop`      | Stop a job                       |
| POST   | `/api/jobs/{id}/rerun`     | Requeue a URL job                |
| POST   | `/api/jobs/{id}/retry-transcription` | Retry Gemini using preserved audio after a temporary 503 |
| DELETE | `/api/jobs/{id}`           | Delete a job                     |

## Notes on pause/stop

Celery cannot natively pause a *running* task, so tasks call `checkpoint()`
between steps (`app/tasks/control.py`). **Pause** takes effect at the next step
boundary and holds the worker slot while waiting — run multiple workers if you
need other jobs to keep moving. **Stop** also force-terminates the worker
process for an immediate halt.
