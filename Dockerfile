FROM python:3.11-slim

# ffmpeg is required for audio extraction / HLS streams.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Created at runtime too, but make sure they exist.
RUN mkdir -p uploads logs

EXPOSE 8000

# Default command runs the web server; the worker overrides this in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
