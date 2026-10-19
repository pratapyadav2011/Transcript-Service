"""
Auth gate for every request.

A request is allowed if ANY of these hold:
  • X-API-Key header matches the shared secret        (server → server)
  • Authorization: Bearer <token> is a valid token    (programmatic)
  • ?token=<token> query param is valid                (entry link from your site)
  • ts_session cookie is a valid token                 (subsequent UI requests)

A valid `?token=` also sets the session cookie, so your website only needs to
link a user in once (e.g. https://transcripts.example.com/?token=XYZ).

The API (/api/..., /htmx/...) always needs one of the above once
API_SERVICE_TOKEN is set. AUTH_ENABLED only controls the UI pages:

  • AUTH_ENABLED=true  — UI pages need one of the above too.
  • AUTH_ENABLED=false — UI pages are open, and opening one hands the browser a
    session cookie so the UI's own buttons (which call /api/...) keep working.
    Anyone who opens the UI can therefore still do whatever the UI does; this
    only stops direct API calls that don't come through the UI.

If API_SERVICE_TOKEN is unset, everything is open (local dev only).
"""
from __future__ import annotations
import logging

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import settings
from app.core.security import make_token, verify_token, verify_api_key, SESSION_COOKIE

logger = logging.getLogger(__name__)

PUBLIC_PREFIXES = ("/static", "/favicon")
PUBLIC_PATHS = {"/api/health", "/ping"}
COOKIE_MAX_AGE = 8 * 3600  # how long the browser session cookie lasts


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def _is_api(path: str) -> bool:
    return path.startswith("/api") or path.startswith("/htmx")


def _set_session(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=COOKIE_MAX_AGE,
        httponly=True, samesite="lax",
    )


async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Dev fallback: no secret configured.
    if not settings.API_SERVICE_TOKEN:
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
        _set_session(response, qtoken)
        return response

    # 4. Session cookie from a previous valid entry.
    if verify_token(request.cookies.get(SESSION_COOKIE, "")):
        return await call_next(request)

    # 5. Open UI: serve the page and give the browser a session so the page's
    #    own /api and /htmx calls are allowed.
    if not settings.AUTH_ENABLED and not _is_api(path):
        response = await call_next(request)
        _set_session(response, make_token(COOKIE_MAX_AGE))
        return response

    # Unauthorized.
    if _is_api(path):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return PlainTextResponse(
        "Unauthorized. Open this service through your website's secure link.",
        status_code=401,
    )
