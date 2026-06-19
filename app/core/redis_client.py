from __future__ import annotations

import redis
from app.core.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return a shared Redis client (lazy init, thread-safe)."""
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client
