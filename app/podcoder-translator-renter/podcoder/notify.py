#!/usr/bin/env python3
"""Job notifications. Web push and SMTP stay stubbed until env is set. No secrets in the log."""
from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from auth_accounts import _now


def _blank(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _log_path(state: Path) -> Path:
    return state / "notifications.json"


def _append(state: Path, row: dict) -> None:
    path = _log_path(state)
    rows: list = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                rows = loaded
        except Exception:
            rows = []
    rows.append(row)
    path.write_text(json.dumps(rows[-200:], indent=2) + "\n", encoding="utf-8")


def _push(title: str, detail: str) -> str:
    public = _blank("VAPID_PUBLIC_KEY")
    private = _blank("VAPID_PRIVATE_KEY")
    if not public or not private:
        return "stub"
    endpoint = _blank("PUSH_ENDPOINT")
    if not endpoint or os.environ.get("PODCODER_PUSH_LIVE") != "1":
        return "prepared"
    return "prepared"


def _email(to: str, title: str, detail: str) -> str:
    import smtp_transport
    result = smtp_transport.send(to, title, detail)
    return "stub" if result == "dev" else result


def desktop(title: str, detail: str) -> str:
    if os.environ.get("SIMKO_NOTIFICATIONS") != "1":
        return "disabled"
    try:
        from plyer import notification
        notification.notify(title=title, message=detail, app_name="Simko SI", timeout=10)
        return "desktop"
    except Exception:
        pass
    import sys
    import subprocess
    try:
        if sys.platform == "darwin":
            script = 'on run argv\n display notification (item 2 of argv) with title (item 1 of argv)\nend run'
            subprocess.run(["osascript", "-e", script, title, detail], check=True, timeout=10, capture_output=True)
        elif sys.platform.startswith("linux"):
            subprocess.run(["notify-send", "--", title, detail], check=True, timeout=10, capture_output=True)
        else:
            return "unavailable"  # Windows uses plyer's Windows toast backend.
        return "desktop"
    except Exception:
        return "unavailable"


def send(state: Path, kind: str, title: str, detail: str, to: str = "") -> dict:
    """Record a notification. Unset VAPID and SMTP stay on the local stub."""
    state.mkdir(parents=True, exist_ok=True)
    native = desktop(title, detail)
    push = _push(title, detail)
    email = _email(to, title, detail)
    delivered = "stub" if push == "stub" and email == "stub" else "mixed" if push != email else push
    if push == "prepared" and email == "stub":
        delivered = "prepared"
    row = {
        "desktop": native,
        "kind": kind,
        "title": title,
        "detail": detail,
        "push": push,
        "email": email,
        "delivered": delivered,
        "at": _now(),
    }
    _append(state, row)
    return {
        "ok": email != "error",
        "desktop": native,
        "delivered": "desktop" if native == "desktop" and delivered == "stub" else delivered,
        "push": push,
        "email": email,
        "vast_calls": 0,
        "destroyed": False,
    }
