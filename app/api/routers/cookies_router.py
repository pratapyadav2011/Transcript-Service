"""
GET    /api/cookies  — is a YouTube cookie jar available to the worker?
GET    /api/cookies/extension.zip — the one-click helper extension, pre-configured
POST   /api/cookies  — upload a cookies.txt file, or paste its contents
DELETE /api/cookies  — remove the stored cookies
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import Response

from app.core.config import settings
from app.core.security import make_token
from app.services import extension_packager
from app.services.downloader import cookie_store
from app.services.downloader.cookie_store import InvalidCookiesFile

router = APIRouter(prefix="/api/cookies", tags=["cookies"])
# The extension is installed once and used for months; a short TTL would mean
# silently re-downloading it every few hours.
EXTENSION_TOKEN_TTL_SECONDS = 180 * 24 * 3600
logger = logging.getLogger(__name__)


@router.get("")
def get_cookies_status():
    return cookie_store.status()


@router.get("/extension.zip")
def download_extension(request: Request):
    """Hand over the browser extension with this server's URL baked in.

    Browsers no longer let a page install an extension, so the user loads this
    unpacked — but they never have to type the service URL.
    """
    base = str(request.base_url).rstrip("/")
    # Same condition as auth_middleware: no secret configured means auth is off.
    # This request is already authenticated, so minting a token for the extension
    # grants nothing the downloader does not already have. Rotating
    # TRANSCRIPT_SECRET_KEY revokes every token handed out this way.
    auth_token = ""
    if settings.AUTH_ENABLED and settings.TRANSCRIPT_SECRET_KEY:
        auth_token = make_token(EXTENSION_TOKEN_TTL_SECONDS)
    try:
        payload = extension_packager.build_zip(base, auth_token=auth_token)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="youtube-cookies-extension.zip"'},
    )


@router.post("")
async def upload_cookies(
    file: UploadFile | None = File(default=None),
    text: str = Form(default=""),
):
    """Accept the cookie jar as an uploaded file or pasted text."""
    if file is not None:
        raw = await file.read()
        if len(raw) > cookie_store.MAX_COOKIES_BYTES:
            raise HTTPException(status_code=413, detail="That file is too large to be a cookies.txt.")
        content = raw.decode("utf-8", errors="replace")
    else:
        content = text
    if not content.strip():
        raise HTTPException(status_code=400, detail="Attach a cookies.txt file or paste its contents.")

    try:
        return cookie_store.save(content)
    except InvalidCookiesFile as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("")
def delete_cookies():
    return {"deleted": cookie_store.delete(), **cookie_store.status()}
