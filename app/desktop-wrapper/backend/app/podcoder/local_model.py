#!/usr/bin/env python3
"""One Granite tag for this computer (Windows field test, Nov 17 2026).

Before this, the probe said granite4.2:8b-q5_0, install status said granite4.2:8b-q8_0, chat used
granite4.2:8b and Aider was pinned to the un-pulled q5_0 tag. resolve() maps any wanted tag to the one
Ollama really has (setup_flow.pick_installed), so probe, setup, chat and Aider all name the same model.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

DEFAULT = "granite4.2:8b"  # Q4_K_M: the CPU / small-GPU default
_CACHE: dict = {}


def ollama_base() -> str:
    return (os.environ.get("OLLAMA_API_BASE") or "http://127.0.0.1:11434").strip().rstrip("/")


def installed(ttl: float = 30.0) -> list[str]:
    now = time.time()
    if _CACHE.get("at") and now - _CACHE["at"] < ttl:
        return list(_CACHE.get("names") or [])
    names: list[str] = []
    try:
        with urllib.request.urlopen(ollama_base() + "/api/tags", timeout=3) as resp:
            doc = json.loads(resp.read().decode("utf-8") or "{}")
        names = [str(m.get("name") or m.get("model") or "") for m in doc.get("models") or [] if isinstance(m, dict)]
        names = [n for n in names if n]
    except Exception:
        names = []
    _CACHE.update(at=now, names=names)
    return list(names)


def resolve(want: str | None = None) -> str:
    """The installed tag closest to `want` (or the override / default). Unchanged when Ollama has nothing."""
    override = (os.environ.get("SIMKOSI_GRANITE_MODEL") or "").strip()
    tag = (override or want or DEFAULT).strip()
    if tag.startswith("ollama_chat/"):
        tag = tag[len("ollama_chat/"):]
    names = installed()
    if not names or tag in names:
        return tag
    try:
        import setup_flow

        return setup_flow.pick_installed(tag, names) or tag
    except Exception:
        return tag
