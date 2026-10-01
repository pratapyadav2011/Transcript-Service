"""
Packages the YouTube-cookie browser extension for download from the UI.

Chrome has not allowed a web page to install an extension since 2018 (inline
installation was removed), and a self-hosted .crx is rejected outside the Web
Store. So the best a self-hosted service can do is hand over a zip to load
unpacked — with the service URL already written into config.js so the user does
not have to type it after installing.
"""
from __future__ import annotations
import io
import os
import json
import zipfile
import logging

logger = logging.getLogger(__name__)

EXTENSION_DIR = os.path.join("tools", "youtube-cookies-extension")
# Everything the browser needs; the folder's README is left out of the download.
BUNDLED_FILES = ("manifest.json", "popup.html", "popup.js", "config.js")
CONFIG_TEMPLATE = (
    "// Written by the transcript service when you downloaded this extension.\n"
    "window.TS_CONFIG = %s;\n"
)


def available() -> bool:
    return all(os.path.isfile(os.path.join(EXTENSION_DIR, name)) for name in BUNDLED_FILES)


def build_zip(service_url: str, auth_token: str = "") -> bytes:
    """Return the extension as a zip, pre-configured for this server.

    `auth_token` is a signed token minted for whoever downloaded the zip, so the
    popup never has to ask anyone for credentials. It is empty when the service
    runs without auth.
    """
    if not available():
        raise FileNotFoundError(f"Extension sources are missing from {EXTENSION_DIR}")

    config = CONFIG_TEMPLATE % json.dumps(
        {"serviceUrl": service_url.rstrip("/"), "authToken": auth_token}
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in BUNDLED_FILES:
            if name == "config.js":
                archive.writestr(name, config)
                continue
            with open(os.path.join(EXTENSION_DIR, name), encoding="utf-8") as fh:
                archive.writestr(name, fh.read())
    logger.info("Packaged cookie extension for %s", service_url)
    return buffer.getvalue()
