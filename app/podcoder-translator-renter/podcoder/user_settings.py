#!/usr/bin/env python3
"""Per-user settings. Theme choice and an optional Grok model id. No secrets and no rent."""
from __future__ import annotations

import json
import re
from pathlib import Path

_BASE = {"ok": True, "vast_calls": 0, "destroyed": False}
_MANIFEST = Path(__file__).resolve().parent.parent / "local" / "themes" / "manifest.json"


def manifest() -> dict:
    try:
        doc = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        doc = {}
    themes = doc.get("themes") if isinstance(doc, dict) else None
    if not isinstance(themes, list) or not themes:
        themes = [
            {"id": "reef-live", "name": "Reef Live"},
            {"id": "reef-still", "name": "Reef Still"},
            {"id": "plain", "name": "No theme / Plain"},
        ]
    default = str((doc or {}).get("default") or themes[0].get("id") or "reef-live")
    return {"default": default, "themes": themes}


def theme_ids() -> set[str]:
    return {str(item.get("id") or "") for item in manifest()["themes"] if item.get("id")}


def _safe_user(user: str) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "_", (user or "").strip().lower())
    return cleaned or "user"


def _path(state: Path, user: str) -> Path:
    return state / "settings" / f"{_safe_user(user)}.json"


def _read(state: Path, user: str) -> dict:
    path = _path(state, user)
    if not path.is_file():
        return {}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return saved if isinstance(saved, dict) else {}


def _write(state: Path, user: str, saved: dict) -> None:
    path = _path(state, user)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")


def get_theme(state: Path, user: str) -> dict:
    saved = _read(state, user)
    candidate = str(saved.get("theme") or "")
    theme = candidate if candidate in theme_ids() else None
    return {**_BASE, "theme": theme, "default": manifest()["default"]}


def set_theme(state: Path, user: str, theme_id: str) -> dict:
    choice = str(theme_id or "").strip()
    if choice not in theme_ids():
        return {**_BASE, "ok": False, "error": "unknown theme", "theme": None}
    saved = _read(state, user)
    saved["theme"] = choice
    _write(state, user, saved)
    return {**_BASE, "theme": choice, "default": manifest()["default"]}


def get_llm_model(state: Path, user: str) -> str:
    """Optional Grok model id. Never an API key."""
    candidate = str(_read(state, user).get("xai_model") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", candidate) and "key" not in candidate.lower():
        return candidate
    return ""


def set_llm_model(state: Path, user: str, model: str) -> dict:
    choice = str(model or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", choice) or "key" in choice.lower():
        return {**_BASE, "ok": False, "error": "model id is not valid", "xai_model": ""}
    saved = _read(state, user)
    saved["xai_model"] = choice
    _write(state, user, saved)
    return {**_BASE, "xai_model": choice}


EXPERIMENTAL_FLAGS = {"desktop_lab": False}

def get_feature_flags(state: Path, user: str) -> dict:
    saved = _read(state,user).get("experimental", {})
    return {name:bool(saved.get(name,default)) for name,default in EXPERIMENTAL_FLAGS.items()}

def set_feature_flag(state: Path, user: str, name: str, enabled: bool) -> dict:
    if name not in EXPERIMENTAL_FLAGS or not isinstance(enabled,bool):
        return {"ok":False,"error":"unknown flag or non-boolean value"}
    saved = _read(state,user)
    saved.setdefault("experimental", {})[name]=enabled
    _write(state,user,saved)
    return {"ok":True,"experimental":get_feature_flags(state,user)}
