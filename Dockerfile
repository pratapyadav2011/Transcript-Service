FROM python:3.11-slim

# ffmpeg   → audio extraction / HLS streams
# espeak   → aeneas forced alignment (phoneme timing); libespeak-dev + build tools
#            are needed to compile aeneas' C extension at pip-install time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg ca-certificates \
       espeak libespeak-dev build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# aeneas builds a C extension via the legacy numpy.distutils, which imports
# distutils.msvccompiler. Modern setuptools hides Python's stdlib distutils behind
# a vendored copy that dropped that module, so force stdlib distutils. Build aeneas
# without isolation so it sees the numpy/setuptools we install here, then install
# the rest of requirements normally (aeneas is already satisfied by then).
ENV SETUPTOOLS_USE_DISTUTILS=stdlib
RUN pip install --no-cache-dir "setuptools<81" wheel numpy==1.26.4 \
    && pip install --no-cache-dir --no-build-isolation aeneas==1.7.3.0 \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Created at runtime too, but make sure they exist.
RUN mkdir -p uploads logs

EXPOSE 8000

# Default command runs the web server; the worker overrides this in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
