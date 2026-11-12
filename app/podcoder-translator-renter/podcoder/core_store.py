#!/usr/bin/env python3
"""Simco SI core store: one local JSON file per user under <state>/core/.

Holds daily metrics (long format), conversation memory entries, goals,
timeline events, recommendations, feedback and bandit arms. Offline only:
no network, no live DDL. The Supabase shape lives in sql/002_simco_core.sql
(file only, never applied by this code).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

_LOCK = threading.RLock()
DEMO_USER = "demo_dana"


def user_key(value: str) -> str:
    text = (value or "default").strip() or "default"
    safe = "".join(ch for ch in text if ch.isalnum() or ch in "._-")[:64]
    return safe or "default"


def path_for(state: Path, user: str) -> Path:
    return Path(state) / "core" / f"{user_key(user)}.json"


def empty(user: str) -> dict:
    return {
        "user": user_key(user),
        "display_name": "",
        "synthetic": False,
        "metrics": [],        # {day, metric_key, value, source, synthetic}
        "memories": [],       # {id, day, at, session_id, text, categories, status, type, synthetic}
        "goals": [],          # {id, category, title, start, end, progress:{day: 0..1}, synthetic}
        "events": [],         # {id, day, end_day, kind, category, title, detail, synthetic}
        "manifest": {},
        "recs": {},           # day -> [rec]
        "feedback": [],       # {rec_id, template_id, category, action, reason, at, day}
        "arms": {},           # template_id -> {alpha, beta}
    }


def load(state: Path, user: str, *, autoseed: bool = True) -> dict:
    path = path_for(state, user)
    with _LOCK:
        if not path.is_file():
            if autoseed and user_key(user) == DEMO_USER:
                from seed import seed_demo
                seed_demo.write(state)
            else:
                return empty(user)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return empty(user)
    base = empty(user)
    for key, value in base.items():
        doc.setdefault(key, value)
    return doc


def save(state: Path, doc: dict) -> Path:
    path = path_for(state, doc["user"])
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")
        tmp.replace(path)
    return path


def lock():
    return _LOCK


def days_in(doc: dict) -> list[str]:
    found = {row["day"] for row in doc.get("metrics", [])}
    found |= {row["day"] for row in doc.get("memories", [])}
    return sorted(found)


def metric_series(doc: dict) -> dict[str, dict[str, float]]:
    """metric_key -> {day: value}. Missing values are simply absent."""
    out: dict[str, dict[str, float]] = {}
    for row in doc.get("metrics", []):
        value = row.get("value")
        if value is None:
            continue
        out.setdefault(row["metric_key"], {})[row["day"]] = float(value)
    return out
