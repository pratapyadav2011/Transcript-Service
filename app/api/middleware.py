"""
Auth gate for every request.

A request is allowed if ANY of these hold:
  • X-API-Key header matches the shared secret        (server → server)
  • Authorization: Bearer <token> is a valid token    (programmatic)
  • ?token=<token> query param is valid                (entry link from your site)
  • ts_session cookie is a valid token                 (subsequent UI requests)

A valid `?token=` also sets the session cookie, so your website only needs to
link a user in once (e.g. https://transcripts.example.com/?token=XYZ).

If API_SECRET_KEY is unset, auth is DISABLED (open) so local dev works — always
set the secret in production.
"""
from __future__ import annotations
import logging

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import settings
from app.core.security import verify_token, verify_api_key, SESSION_COOKIE

logger = logging.getLogger(__name__)

PUBLIC_PREFIXES = ("/static", "/favicon")
PUBLIC_PATHS = {"/api/health", "/ping"}
COOKIE_MAX_AGE = 8 * 3600  # how long the browser session cookie lasts


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Dev fallback: no secret configured → don't block anything.
    if not settings.API_SECRET_KEY:
        return await call_next(request)

    if _is_public(path):
        return await call_next(request)

    # 1. Static shared secret (server-to-server).
    if verify_api_key(request.headers.get("x-api-key", "")):
        return await call_next(request)

    # 2. Bearer token.
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and verify_token(auth[7:]):
        return await call_next(request)

    # 3. Query-param token → authorize this request AND set a session cookie.
    qtoken = request.query_params.get("token")
    if qtoken and verify_token(qtoken):
        response = await call_next(request)
        response.set_cookie(
            SESSION_COOKIE, qtoken, max_age=COOKIE_MAX_AGE,
            httponly=True, samesite="lax",
        )
        return response

    # 4. Session cookie from a previous valid entry.
    if verify_token(request.cookies.get(SESSION_COOKIE, "")):
        return await call_next(request)

    # Unauthorized.
    if path.startswith("/api") or path.startswith("/htmx"):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return PlainTextResponse(
        "Unauthorized. Open this service through your website's secure link.",
        status_code=401,
    )
