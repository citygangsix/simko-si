#!/usr/bin/env python3
"""Desktop-app routes: first-run setup screen, xAI key (OS keychain), setup steps, logs folder.

POSTs need the X-Simko-Desktop header, which a web page on another site cannot send without a CORS
preflight that server.py refuses, so random websites can't trigger downloads or change the key.
The key is never returned, logged or written into the app bundle.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import setup_steps
import xai_client

HERE = Path(__file__).resolve().parent
SETUP_HTML = HERE.parent / "local" / "setup.html"
JSON = "application/json"


def _key_state() -> dict:
    if (os.environ.get("XAI_API_KEY") or "").strip():
        return {"set": True, "where": "environment"}
    if xai_client.keychain_key():
        return {"set": True, "where": "keychain"}
    if xai_client._read_external_key():
        return {"set": True, "where": "file"}
    return {"set": False, "where": ""}


def _save_key(key: str) -> dict:
    key = (key or "").strip()
    if not key or len(key) < 20 or len(key) > 300 or any(c.isspace() for c in key):
        return {"ok": False, "error": "That doesn't look like an xAI API key."}
    try:
        import keyring
        keyring.set_password(xai_client.KEYCHAIN_SERVICE, xai_client.KEYCHAIN_USER, key)
        if xai_client.keychain_key() == key:
            return {"ok": True, "where": "keychain"}
    except Exception:
        pass
    # No usable keychain (some Linux desktops): private file readable only by this user.
    f = setup_steps.data_dir() / "xai.env"
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(f), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"XAI_API_KEY={key}\n")
    return {"ok": True, "where": "file"}


def _clear_key() -> dict:
    try:
        import keyring
        keyring.delete_password(xai_client.KEYCHAIN_SERVICE, xai_client.KEYCHAIN_USER)
    except Exception:
        pass
    (setup_steps.data_dir() / "xai.env").unlink(missing_ok=True)
    return {"ok": True}


def _open_folder(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def try_handle(method: str, raw_path: str, body: dict | None, headers=None):
    """Return (code, payload, content_type) or None when the route isn't ours."""
    path = urlparse(raw_path).path.rstrip("/") or "/"
    if method == "GET":
        if path == "/setup":
            return 200, SETUP_HTML.read_bytes(), "text/html; charset=utf-8"
        if path == "/api/simkosi/setup":
            st = setup_steps.status()
            st["key"] = _key_state()
            return 200, st, JSON
        if path == "/api/simkosi/key":
            return 200, {"ok": True, **_key_state()}, JSON
        return None
    if method == "POST" and path.startswith("/api/simkosi/"):
        if headers is not None and headers.get("X-Simko-Desktop") != "1":
            return 403, {"ok": False, "error": "desktop header missing"}, JSON
        body = body or {}
        if path == "/api/simkosi/key":
            return (200, _clear_key(), JSON) if body.get("clear") else (200, _save_key(str(body.get("key") or "")), JSON)
        if path == "/api/simkosi/setup/run":
            res = setup_steps.start(str(body.get("step") or ""))
            return (200 if res.get("ok") else 400), res, JSON
        if path == "/api/simkosi/open-logs":
            _open_folder(setup_steps.data_dir() / "logs")
            return 200, {"ok": True}, JSON
    return None
