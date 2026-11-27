#!/usr/bin/env python3
"""Legacy connector catalog plus initial read-only desktop OAuth adapters."""
from __future__ import annotations

import os

CONNECTORS = {
    "gmail": {"auth": "https://accounts.google.com/o/oauth2/v2/auth", "env_id": "GMAIL_CLIENT_ID", "env_secret": "GMAIL_CLIENT_SECRET"},
    "github": {"auth": "https://github.com/login/oauth/authorize", "env_id": "GITHUB_CLIENT_ID", "env_secret": "GITHUB_CLIENT_SECRET"},
    "dropbox": {"auth": "https://www.dropbox.com/oauth2/authorize", "env_id": "DROPBOX_CLIENT_ID", "env_secret": "DROPBOX_CLIENT_SECRET"},
    "rest": {"auth": "", "env_id": "REST_CONNECTOR_BASE_URL", "env_secret": ""},
}


def _set(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def describe(name: str) -> dict:
    spec = CONNECTORS.get(name)
    if not spec:
        return {"ok": False, "error": "unknown connector", "vast_calls": 0, "destroyed": False}
    return {
        "ok": True,
        "name": name,
        "stub": True,
        "configured": False,
        "client_id_set": _set(spec["env_id"]) if spec.get("env_id") else False,
        "auth": spec["auth"],
        "vast_calls": 0,
        "destroyed": False,
    }


def listing() -> dict:
    import connector_oauth
    implemented = connector_oauth.listing()["connectors"]
    return {"ok": True, "connectors": implemented + [describe(name) for name in CONNECTORS if name != "github"], "vast_calls": 0, "destroyed": False}


def crm_rows() -> list[dict]:
    return [{"label": "Open", "value": 2}, {"label": "Waiting", "value": 1}]
