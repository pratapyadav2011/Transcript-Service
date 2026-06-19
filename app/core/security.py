"""
Stateless auth for the transcript service — no user accounts, no login.

Two ways to authenticate a request:
  1. Static shared secret in the `X-API-Key` header  (server → server, e.g. your
     Next.js backend calling the API).
  2. A short-lived HMAC-signed token your website mints with the same secret
     (used by the browser UI via `?token=` / cookie / `Authorization: Bearer`).

Token format:  "<expiry_unix>.<hmac_sha256(secret, expiry_unix)>"
Because it is just an HMAC over an expiry timestamp, your website can generate
it locally with the shared secret — it never has to call this service.
"""
from __future__ import annotations
import hmac
import hashlib
import time

from app.core.config import settings

SESSION_COOKIE = "ts_session"


def _sign(payload: str) -> str:
    return hmac.new(
        settings.API_SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def make_token(ttl_seconds: int = 3600) -> str:
    """Mint a signed token valid for `ttl_seconds`. Needs API_SECRET_KEY set."""
    if not settings.API_SECRET_KEY:
        raise RuntimeError("API_SECRET_KEY is not configured.")
    expiry = str(int(time.time()) + ttl_seconds)
    return f"{expiry}.{_sign(expiry)}"


def verify_token(token: str) -> bool:
    """True if `token` is well-formed, correctly signed, and not expired."""
    if not token or "." not in token or not settings.API_SECRET_KEY:
        return False
    expiry, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(expiry)):
        return False
    try:
        return int(expiry) >= int(time.time())
    except ValueError:
        return False


def verify_api_key(key: str) -> bool:
    """Constant-time comparison against the static shared secret."""
    if not settings.API_SECRET_KEY:
        return False
    return hmac.compare_digest(key or "", settings.API_SECRET_KEY)
