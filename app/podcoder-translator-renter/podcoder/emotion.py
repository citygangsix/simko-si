#!/usr/bin/env python3
"""Response style. A system prompt plus a qualitative fruit tag. No scores. Users can turn it off."""
from __future__ import annotations

import json
from pathlib import Path

FRUITS = (
    "love",
    "joy",
    "peace",
    "patience",
    "kindness",
    "goodness",
    "gentleness",
    "faithfulness",
    "self-control",
)
HINTS = {
    "love": ("love", "care", "caring"),
    "joy": ("joy", "glad", "delight"),
    "peace": ("peace", "calm"),
    "patience": ("patience", "patient"),
    "kindness": ("kindness", "kind "),
    "goodness": ("goodness",),
    "gentleness": ("gentleness", "gentle"),
    "faithfulness": ("faithfulness", "faithful"),
    "self-control": ("self-control", "self control"),
}


def _path(state: Path) -> Path:
    return state / "emotion.json"


def enabled(state: Path) -> bool:
    path = _path(state)
    if not path.is_file():
        return True
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("enabled", True))
    except Exception:
        return True


def set_enabled(state: Path, on: bool) -> dict:
    state.mkdir(parents=True, exist_ok=True)
    _path(state).write_text(json.dumps({"enabled": bool(on)}, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "enabled": bool(on), "vast_calls": 0, "destroyed": False}


def system_prompt(category: str, on: bool = True) -> str:
    if not on:
        return ""
    area = category or "everyday life"
    fruits = ", ".join(FRUITS)
    return (
        f"Speak with the fruits of the Spirit: {fruits}. "
        f"This chat is in the Lifebook area {area}. "
        "Be gentle and hopeful. Do not grade the person and do not use percentages."
    )


def tag_fruit(text: str) -> dict:
    hay = f" {(text or '').lower()} "
    found = []
    for fruit, words in HINTS.items():
        if any(word in hay for word in words):
            found.append(fruit)
    return {"ok": True, "fruits": found, "enabled": True, "vast_calls": 0, "destroyed": False}


def shape(state: Path, text: str, category: str = "", on: bool | None = None) -> dict:
    active = enabled(state) if on is None else bool(on)
    if not active:
        return {"ok": True, "enabled": False, "reply": text, "system": "", "fruits": [], "vast_calls": 0, "destroyed": False}
    tagged = tag_fruit(text)
    return {
        "ok": True,
        "enabled": True,
        "reply": text,
        "system": system_prompt(category, True),
        "fruits": tagged["fruits"],
        "category": category,
        "vast_calls": 0,
        "destroyed": False,
    }
