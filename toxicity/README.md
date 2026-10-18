# Comment toxicity scorer

A CPU-only toxicity scorer for comments that runs
[`unitary/unbiased-toxic-roberta`](https://huggingface.co/unitary/unbiased-toxic-roberta).
It runs as the `toxicity` container in this repo's `docker-compose.yml`, and
the existing Caddy exposes it over HTTPS on the same domain as the transcript
service.

It speaks the Hugging Face Inference API text-classification protocol exactly,
so the website only needs a base-URL and token change. It scores text and
returns numbers. Thresholds and label filtering stay in the website.

Every check, **including the comment text**, is kept in Redis for 7 days
(`TOXICITY_HISTORY_DAYS`). You can browse it on the transcript UI's
**/toxicity** page; see [Check history page](#check-history-page).

It is a separate image from the transcript app because it needs torch, which
the transcript image doesn't. It shares nothing with the transcript app except
Caddy.

## API

```
POST /models/unitary/unbiased-toxic-roberta
Authorization: Bearer <TOXICITY_SERVICE_TOKEN>
Content-Type: application/json

{ "inputs": "text to score", "parameters": { "top_k": 20 } }
```

The response is a flat array sorted highest score first, with all 16 labels:

```json
[{"label": "toxicity", "score": 0.9972}, {"label": "insult", "score": 0.9964}, ...]
```

- Scores are an independent **sigmoid** per label, because the model is
  multi-label. They do not sum to 1. Don't change this to softmax: the
  website's thresholds would quietly stop firing.
- `top_k` set to `null`, missing, or ≥ 16 returns all labels. Unknown
  parameters (and HF's `options`) are ignored.
- `inputs` may also be an array of up to 32 strings. The response is then an
  array of arrays, one per input.
- Inputs longer than 512 tokens are truncated, not rejected.
- Errors always carry `{"error": "..."}`: 400 for bad or empty input, 401 for a
  bad or missing token, 503 while the model is still loading.
- `GET /health` needs no auth. It returns `200 {"ok":true,"model_loaded":true}`,
  or 503 until the model has loaded. (The transcript app's own health check is
  `/api/health`.)

Each request is logged as one line (status, duration, input count, character
count, top label and score). **The input text never goes to the logs.** It is
stored only in the Redis check history described below.

Successful responses carry an `X-Check-Id` header with the id of the saved
check. A batch request gets a comma-separated list of ids.

```
INFO POST /models/unitary/unbiased-toxic-roberta 200 107ms inputs=1 chars=50 top=toxicity:0.9972
```

## How it fits into this repo

| File | Role |
|---|---|
| `toxicity/app.py` | FastAPI service. Loads the model once at startup in a background thread, so `/health` can answer 503 while loading. |
| `toxicity/requirements.txt` | Pinned dependencies, separate from the transcript app's. |
| `toxicity/Dockerfile` | `python:3.11-slim`, CPU-only torch, model baked in at build time, non-root, with a `HEALTHCHECK`. |
| `docker-compose.yml` → `toxicity` | 2 CPUs, `mem_limit: 2g`, internal port 8000 only. |
| `Caddyfile` | Sends `/health` and `/models/unitary/unbiased-toxic-roberta` to `toxicity:8000` and everything else to `web:8000`. |
| `.env` | `TOXICITY_SERVICE_TOKEN` (required), `TOXICITY_CPUS`, `TOXICITY_HISTORY_DAYS`. |
| `app/core/toxicity_store.py`, `app/api/routers/toxicity_router.py`, `app/templates/toxicity_*.html` | The **/toxicity** page in the transcript UI. |

The root `.dockerignore` excludes `toxicity/`, so the transcript image doesn't
pick it up.

## Deploy on the VM

HTTPS comes from the Caddy overlay (`docker-compose.caddy.yml`). Without it, the
scorer can't be reached from outside the VM at all.

```bash
git pull
openssl rand -hex 32                 # → TOXICITY_SERVICE_TOKEN in .env
$EDITOR .env                         # also TOXICITY_CPUS (whole number, default 2)
chmod 600 .env

docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d --build
docker compose ps toxicity           # should show "(healthy)"
```

The first build downloads about 1.2 GB: CPU torch, plus the 477 MB model,
which is baked into the image. After that the container starts with no network
access needed.

`docker compose` refuses to run while `TOXICITY_SERVICE_TOKEN` is unset. That
applies to every service in the file, so set it before the next deploy.

The VM needs about 1 GB of free RAM for the scorer, on top of the transcript
services.

### Firewall

Allow only SSH, 80, and 443:

```bash
sudo ufw default deny incoming
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

The scorer's port 8000 is never published (`expose`, not `ports`). Keep it
that way: **Docker-published ports bypass ufw**.

## Check history page

Open **`https://$DOMAIN/toxicity`** (the "Toxicity" link in the nav). It sits
behind the transcript service's usual login, the same as `/jobs`.

- **List:** every check from the last `TOXICITY_HISTORY_DAYS` days, newest
  first. Each row shows the time, the source, the comment, the 7 labels the
  website uses, and the scoring time. The list refreshes every 10 seconds.
- **Filters:** search the comment text, filter by source (`api` = the website,
  `manual` = the test box), or show only checks where any of the 7 labels is
  ≥ 0.5 or ≥ 0.85.
- **Detail page:** click a row to see the full comment and all 16 scores as
  bars, with the identity labels shown separately.
- **Test a comment:** paste any text and see its scores immediately. These
  checks are saved as `manual`.

The colour shading (≥ 0.5 amber, ≥ 0.85 red) is only there to make the list
easier to read. What actually gets held is decided by the website's own
thresholds.

How it works: the scorer writes each check to the existing Redis as
`toxicity:check:{id}` (JSON, expiring after `TOXICITY_HISTORY_DAYS`) and indexes
it in the `toxicity:checks` sorted set, capped at 20,000 entries. If Redis is
down, scoring still works and the check just isn't saved. The test box calls
the scorer directly at `http://toxicity:8000` with `TOXICITY_SERVICE_TOKEN`.
The web container reads that token from `.env`.

To stop storing comment text, remove `REDIS_URL` from the `toxicity` service in
`docker-compose.yml`. To delete all history now:
`docker compose exec redis sh -c "redis-cli --scan --pattern 'toxicity:check*' | xargs -r redis-cli del"`.

## Point the website at it

Replace the HF base URL with `https://$DOMAIN` (the transcript service's
domain), and the HF token with `TOXICITY_SERVICE_TOKEN`. The path, request
body, and response shape are unchanged.

## Acceptance tests

```bash
export HOST=<DOMAIN> TOKEN=<TOXICITY_SERVICE_TOKEN>
P=https://$HOST/models/unitary/unbiased-toxic-roberta

curl -s https://$HOST/health                                     # {"ok":true,"model_loaded":true}
curl -s -o /dev/null -w '%{http_code}\n' -X POST $P \
  -H 'Content-Type: application/json' -d '{"inputs":"hello"}'     # 401
curl -s -X POST $P -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"inputs":"Thanks for covering the council meeting, this was helpful.","parameters":{"top_k":20}}'
                                                                 # toxicity ~0.0004
curl -s -X POST $P -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"inputs":"you are a complete idiot and nobody wants you here","parameters":{"top_k":20}}'
                                                                 # toxicity ~0.997, insult ~0.996, sum ~2.0
curl -s -o /dev/null -w '%{http_code}\n' -X POST $P -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"inputs\":\"$(python3 -c 'print("spam "*3000)')\"}"   # 200
curl -s -X POST $P -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"inputs":"   "}'                                          # 400 {"error":...}
docker compose restart toxicity && sleep 30 && curl -s https://$HOST/health
```

## Operations

**Read logs**

```bash
docker compose logs -f toxicity            # one line per request
docker compose logs toxicity | grep ' 401 '
```

**Rebuild after a code change**

```bash
docker compose up -d --build toxicity
```

**Update the model**

The model is pinned to a Hugging Face commit through `MODEL_REVISION` in
`toxicity/Dockerfile`, so rebuilds are reproducible. To move to a newer commit:

1. Get the new commit SHA:
   `curl -s https://huggingface.co/api/models/unitary/unbiased-toxic-roberta | jq -r .sha`
2. Update `ARG MODEL_REVISION=...`.
3. Run `docker compose up -d --build toxicity`, then rerun the acceptance
   tests. Tests 3 and 4 matter most, because a model change can shift scores
   against the website's thresholds.

To roll back, set the old SHA and rebuild.

**Rotate the token**

```bash
openssl rand -hex 32                  # new token
$EDITOR .env                          # replace TOXICITY_SERVICE_TOKEN
docker compose up -d toxicity         # recreates the container with the new env
```

Use `up -d`, not `restart`. `restart` keeps the old environment. Update the
website's secret immediately afterwards. Requests made with the old token get
401 until it switches.

## Measurements

These were measured on a MacBook (Apple Silicon, arm64) with Docker Desktop, the
container limited to `--cpus 2 --memory 2g`. **Re-measure on the VM.** x86 VM
cores are usually slower per core, and a cold disk read of the weights adds
time on first boot.

| Metric | Value |
|---|---|
| Image size | 2.27 GB (torch CPU + deps ~850 MB, model 477 MB) |
| Model load inside the process | 1.2 s first start, 0.2 s with warm page cache |
| Restart → healthy through Caddy | 2.5 s |
| Container memory once warm (`docker stats`) | ~290 MiB (weights are mmapped, so part shows as page cache) |
| Latency, 20 sequential ~200-word requests | p50 473 ms, p95 495 ms |
| Latency, short comment (~10 words) | ~80–110 ms |
| Latency, 15,000 chars (truncated to 512 tokens) | ~750 ms |

To measure latency on the VM:

```bash
python3 - <<'EOF'
import json, os, random, statistics, time, urllib.request
url = f"https://{os.environ['HOST']}/models/unitary/unbiased-toxic-roberta"
w = "council meeting budget roads parks library zoning residents voted agenda public schools water".split()
lat = []
for _ in range(20):
    body = json.dumps({"inputs": " ".join(random.choice(w) for _ in range(200))}).encode()
    req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {os.environ['TOKEN']}", "Content-Type": "application/json"})
    t = time.perf_counter(); urllib.request.urlopen(req).read(); lat.append((time.perf_counter() - t) * 1000)
lat.sort(); print(f"p50={statistics.median(lat):.0f}ms p95={lat[18]:.0f}ms")
EOF
docker stats --no-stream $(docker compose ps -q toxicity)
```

Requests are served one at a time: a lock serialises inference so concurrent
requests don't oversubscribe the CPUs. At about 0.5 s per long comment, that
is roughly 2 long comments per second at 2 CPUs. If that becomes a
bottleneck, raise `TOXICITY_CPUS` first.
