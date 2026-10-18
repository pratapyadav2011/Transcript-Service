FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# CPU-only torch first. The default PyPI wheel drags in ~2.5GB of CUDA.
COPY requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.9.1 \
 && pip install -r requirements.txt

# Bake the model into the image so the container never downloads at runtime.
# Pinned to a commit so rebuilds are reproducible; see README to update it.
ARG MODEL_REVISION=36295dd80b422dc49f40052021430dae76241adc
RUN python -c "from huggingface_hub import snapshot_download; \
snapshot_download('unitary/unbiased-toxic-roberta', revision='${MODEL_REVISION}', local_dir='/opt/model', \
allow_patterns=['config.json', 'pytorch_model.bin', 'vocab.json', 'merges.txt', 'tokenizer_config.json', 'special_tokens_map.json'])" \
 && rm -rf /opt/model/.cache /root/.cache

ENV MODEL_DIR=/opt/model \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY app.py .
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# One worker: the model is ~500MB resident and inference is CPU-bound, so
# extra workers multiply memory for no throughput gain.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
