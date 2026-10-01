"""
Stores the Netscape cookies.txt that yt-dlp uses for YouTube.

YouTube blocks datacenter/VM IPs with "Sign in to confirm you're not a bot", and
the only fix that does not need a residential proxy is a logged-in cookie jar.
A browser page cannot read youtube.com cookies (they are cross-origin and
HttpOnly), so the user exports them with a cookies.txt browser extension and
hands the file to the UI; this module is where that file lands.

The worker reads the same path through the shared uploads volume, so an upload
takes effect on the next job without a restart.
"""
from __future__ import annotations
import os
import time
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

COOKIE_FILENAME = "youtube-cookies.txt"
NETSCAPE_HEADER = "# Netscape HTTP Cookie File"
MAX_COOKIES_BYTES = 1024 * 1024  # a real cookies.txt is a few KB

# Any one of these means the export came from a signed-in session. Google splits
# the session across several names and rotates them, so accept any.
LOGIN_COOKIE_NAMES = {
    "SID", "__Secure-1PSID", "__Secure-3PSID", "SAPISID", "__Secure-3PAPISID",
    "SSID", "HSID", "LOGIN_INFO", "APISID",
}
COOKIE_DOMAINS = ("youtube.com", "google.com")


class InvalidCookiesFile(ValueError):
    """Raised when the uploaded text is not a usable Netscape cookies.txt."""


def upload_path() -> str:
    """Where a UI-supplied cookies file is stored."""
    return os.path.join(settings.UPLOAD_DIR, COOKIE_FILENAME)


def active_path() -> str | None:
    """Return the cookies file yt-dlp should use, or None when there is none.

    An explicit YTDLP_COOKIES_FILE wins so existing deployments keep working; a
    file uploaded through the UI is the fallback. A configured-but-missing path
    is not fatal: it is the normal state before anyone has uploaded cookies, and
    YouTube's own error tells the user what to do.
    """
    configured = settings.YTDLP_COOKIES_FILE
    if configured:
        if os.path.isfile(configured):
            return configured
        logger.info("YTDLP_COOKIES_FILE %s does not exist yet", configured)
    uploaded = upload_path()
    return uploaded if os.path.isfile(uploaded) else None


def _parse(text: str) -> list[dict]:
    """Return the cookie rows of a Netscape cookies.txt (ignoring comments)."""
    rows = []
    for line in text.splitlines():
        # A leading #HttpOnly_ prefix is part of the format, not a comment.
        stripped = line.strip()
        if stripped.startswith("#HttpOnly_"):
            stripped = stripped[len("#HttpOnly_"):]
        elif not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split("\t")
        if len(fields) != 7:
            continue
        rows.append({
            "domain": fields[0].lstrip("."),
            "expires": int(fields[4]) if fields[4].isdigit() else 0,
            "name": fields[5],
        })
    return rows


def validate(text: str) -> dict:
    """Check that `text` is a usable YouTube cookie jar; return a summary."""
    if len(text.encode("utf-8")) > MAX_COOKIES_BYTES:
        raise InvalidCookiesFile("That file is too large to be a cookies.txt.")

    rows = _parse(text)
    if not rows:
        raise InvalidCookiesFile(
            "No cookies found. Export in Netscape format — a cookies.txt browser "
            "extension does this; a copied JSON blob will not work."
        )

    relevant = [r for r in rows if r["domain"].endswith(COOKIE_DOMAINS)]
    if not relevant:
        found = sorted({r["domain"] for r in rows})[:3]
        raise InvalidCookiesFile(
            f"No youtube.com or google.com cookies in that file (found: {', '.join(found)}). "
            "Export the cookies while youtube.com is the open tab."
        )

    names = {r["name"] for r in relevant}
    if not (names & LOGIN_COOKIE_NAMES):
        raise InvalidCookiesFile(
            "These cookies are not from a signed-in session. Log in to YouTube "
            "first, then export the cookies again."
        )

    # Report the soonest expiry among session cookies so the UI can warn early.
    expiries = [r["expires"] for r in relevant if r["name"] in LOGIN_COOKIE_NAMES and r["expires"]]
    return {"count": len(relevant), "expires_at": min(expiries) if expiries else 0}


def save(text: str) -> dict:
    """Validate and store cookies.txt. Returns the same shape as `status()`."""
    summary = validate(text)

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    dest = upload_path()
    tmp = f"{dest}.tmp"
    if not text.startswith("#"):
        text = f"{NETSCAPE_HEADER}\n{text}"
    if not text.endswith("\n"):
        text += "\n"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    # Cookies are login credentials — keep them owner-readable only.
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)

    logger.info("Stored %d YouTube cookies at %s", summary["count"], dest)
    return status()


def delete() -> bool:
    """Remove stored cookies. Returns True when a file was actually removed."""
    try:
        os.remove(upload_path())
        return True
    except FileNotFoundError:
        return False


def status() -> dict:
    """Describe the cookies currently available to the worker."""
    path = active_path()
    if not path:
        return {"present": False}

    info: dict = {
        "present": True,
        "path": path,
        "managed": path == upload_path(),  # False = set by env, UI cannot replace it
        "updated_at": int(os.path.getmtime(path)),
    }
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            summary = validate(fh.read())
        info.update(summary)
        if summary["expires_at"]:
            info["expired"] = summary["expires_at"] < time.time()
    except (OSError, InvalidCookiesFile) as exc:
        info["warning"] = str(exc)
    return info
