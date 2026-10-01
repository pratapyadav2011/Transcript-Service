import io
import json
import zipfile

import pytest

from app.services import extension_packager


def test_zip_contains_every_browser_file():
    archive = zipfile.ZipFile(io.BytesIO(extension_packager.build_zip("https://ts.example.com")))
    assert set(archive.namelist()) == set(extension_packager.BUNDLED_FILES)
    # The folder README is documentation for us, not part of the extension.
    assert "README.md" not in archive.namelist()


def test_service_url_is_baked_into_config():
    archive = zipfile.ZipFile(io.BytesIO(extension_packager.build_zip("https://ts.example.com/")))
    config = archive.read("config.js").decode()

    assert '"serviceUrl": "https://ts.example.com"' in config  # trailing slash trimmed
    assert "window.TS_CONFIG" in config


def test_open_service_bakes_an_empty_token():
    archive = zipfile.ZipFile(io.BytesIO(extension_packager.build_zip("http://localhost:8000")))
    assert '"authToken": ""' in archive.read("config.js").decode()


def test_secured_service_bakes_the_token():
    archive = zipfile.ZipFile(
        io.BytesIO(extension_packager.build_zip("https://ts.example.com", auth_token="1234.abcd"))
    )
    assert '"authToken": "1234.abcd"' in archive.read("config.js").decode()


def test_popup_never_asks_for_credentials():
    archive = zipfile.ZipFile(io.BytesIO(extension_packager.build_zip("http://localhost:8000")))
    assert "X-API-Key" not in archive.read("popup.html").decode()


def test_manifest_stays_valid_json_with_cookie_permission():
    archive = zipfile.ZipFile(io.BytesIO(extension_packager.build_zip("http://localhost:8000")))
    manifest = json.loads(archive.read("manifest.json"))

    assert manifest["manifest_version"] == 3
    assert "cookies" in manifest["permissions"]


def test_missing_sources_raise(monkeypatch):
    monkeypatch.setattr(extension_packager, "EXTENSION_DIR", "/nonexistent")
    assert extension_packager.available() is False
    with pytest.raises(FileNotFoundError):
        extension_packager.build_zip("http://localhost:8000")
