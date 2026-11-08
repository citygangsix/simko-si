#!/usr/bin/env python3
"""Lifebook-13 tags for conversation lines. Not grades and not a notes system."""
from __future__ import annotations

import json
import time
from pathlib import Path

# Canonical 12 from this repo's Lifebook taxonomy, plus category 13
# (sex and sensuality) as Jon and Missy Butcher describe it publicly.
CATEGORIES = [
    {"id": "health_fitness", "label": "Health and Fitness"},
    {"id": "intellectual_life", "label": "Intellectual Life"},
    {"id": "emotional_life", "label": "Emotional Life"},
    {"id": "character", "label": "Character"},
    {"id": "spiritual_life", "label": "Spiritual Life"},
    {"id": "love_relationship", "label": "Love Relationship"},
    {"id": "parenting", "label": "Parenting"},
    {"id": "social_life", "label": "Social Life"},
    {"id": "financial_life", "label": "Financial Life"},
    {"id": "career", "label": "Career"},
    {"id": "quality_of_life", "label": "Quality of Life"},
    {"id": "life_vision", "label": "Life Vision"},
    {"id": "sex_and_sensuality", "label": "Sex and Sensuality"},
]
IDS = {row["id"] for row in CATEGORIES}
LABELS = {row["id"]: row["label"] for row in CATEGORIES}
HINTS = [
    ("health_fitness", ("health", "fitness", "workout", "sleep", "gym")),
    ("intellectual_life", ("learn", "read", "study", "book", "idea")),
    ("emotional_life", ("feel", "anxious", "sad", "happy", "emotion")),
    ("character", ("honest", "integrity", "habit", "discipline")),
    ("spiritual_life", ("pray", "faith", "spirit", "meaning")),
    ("love_relationship", ("love", "partner", "marriage", "relationship")),
    ("parenting", ("kid", "child", "parent", "son", "daughter")),
    ("social_life", ("friend", "party", "social", "community")),
    ("financial_life", ("money", "budget", "bill", "invest", "rent")),
    ("career", ("work", "job", "career", "ship", "code")),
    ("quality_of_life", ("home", "rest", "travel", "comfort")),
    ("life_vision", ("goal", "dream", "vision", "future", "plan")),
    ("sex_and_sensuality", ("sex", "sensual", "intimate", "desire")),
]


def _user(value: str) -> str:
    text = (value or "default").strip() or "default"
    safe = "".join(ch for ch in text if ch.isalnum() or ch in "._-")[:64]
    return safe or "default"


def _path(state: Path, user: str) -> Path:
    return state / "memory" / f"{_user(user)}.json"


def _load(state: Path, user: str) -> dict:
    path = _path(state, user)
    if not path.is_file():
        return {"user": _user(user), "notes": {row["id"]: [] for row in CATEGORIES}, "tags": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        doc = {}
    notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
    for row in CATEGORIES:
        notes.setdefault(row["id"], [])
    tags = doc.get("tags") if isinstance(doc.get("tags"), list) else []
    return {"user": _user(user), "notes": notes, "tags": tags}


def _save(state: Path, doc: dict) -> None:
    path = _path(state, doc["user"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def categorize(text: str) -> str:
    """Pick one Lifebook category for a line. Empty when nothing matches."""
    hay = f" {(text or '').lower()} "
    for category, words in HINTS:
        if any(f" {word} " in hay for word in words):
            return category
    return ""


WELL = ("well", "good", "great", "better", "proud", "happy", "strong")
STRAINED = ("stuck", "anxious", "worried", "hard", "tired", "behind", "stress", "struggling")


def _tone(text: str) -> str:
    hay = f" {(text or '').lower()} "
    if any(f" {word} " in hay for word in STRAINED):
        return "strained"
    if any(f" {word} " in hay for word in WELL):
        return "doing well"
    return "in play"


def _stamp(value: str):
    from datetime import datetime, timezone
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _statuses(tags: list) -> dict:
    found = {row["id"]: "not discussed" for row in CATEGORIES}
    for tag in tags:
        category = tag.get("category")
        if category in found:
            found[category] = tag.get("status") or "in play"
    return found


def dominance_note(tags: list) -> str:
    """Words only. Set when one category is the main topic in the last 10 sessions or 10 days."""
    from datetime import datetime, timedelta, timezone
    if not tags:
        return ""
    sessions = []
    for tag in tags:
        key = tag.get("session_id") or tag.get("at") or ""
        if key and key not in sessions:
            sessions.append(key)
    recent_sessions = set(sessions[-10:])
    cutoff = datetime.now(timezone.utc) - timedelta(days=10)
    window = []
    for tag in tags:
        key = tag.get("session_id") or tag.get("at") or ""
        stamp = _stamp(tag.get("at") or "")
        if key in recent_sessions or (stamp is not None and stamp >= cutoff):
            window.append(tag)
    counts: dict[str, int] = {}
    for tag in window:
        category = tag.get("category") or ""
        if category in IDS:
            counts[category] = counts.get(category, 0) + 1
    if not counts:
        return ""
    top = max(counts, key=counts.get)
    top_n = counts[top]
    others = sum(counts.values()) - top_n
    if top_n >= 3 and top_n > others:
        return f"{LABELS[top]} has been the main topic in recent chats."
    return ""


def list_memory(state: Path, user: str) -> dict:
    doc = _load(state, user)
    tags = doc["tags"]
    return {
        "ok": True,
        "user": doc["user"],
        "categories": CATEGORIES,
        "notes": doc["notes"],
        "tags": tags,
        "statuses": _statuses(tags),
        "dominance_note": dominance_note(tags),
        "vast_calls": 0,
        "destroyed": False,
    }


def add_note(state: Path, user: str, category: str, note: str) -> dict:
    if category not in IDS:
        return {"ok": False, "error": "unknown lifebook category", "categories": CATEGORIES}
    text = (note or "").strip()
    if not text:
        return {"ok": False, "error": "empty note"}
    doc = _load(state, user)
    doc["notes"][category].append({
        "text": text[:2000],
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    _save(state, doc)
    return {
        "ok": True,
        "user": doc["user"],
        "category": category,
        "count": len(doc["notes"][category]),
        "vast_calls": 0,
        "destroyed": False,
    }


def tag_turn(state: Path, user: str, text: str, session_id: str = "", category: str = "") -> dict:
    """Tag one conversation line. No score."""
    excerpt = (text or "").strip()[:240]
    if not excerpt:
        return {"ok": False, "error": "empty text", "tagged": False, "vast_calls": 0, "destroyed": False}
    chosen = category if category in IDS else categorize(excerpt)
    if not chosen:
        return {
            "ok": True,
            "tagged": False,
            "category": "",
            "label": "",
            "vast_calls": 0,
            "destroyed": False,
        }
    doc = _load(state, user)
    row = {
        "category": chosen,
        "label": LABELS[chosen],
        "text": excerpt,
        "session_id": (session_id or "")[:80],
        "status": _tone(excerpt),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    doc["tags"].append(row)
    doc["tags"] = doc["tags"][-200:]
    _save(state, doc)
    import offline_sync
    offline_sync.note(state, "podcoder_lifebook_tags", row)
    return {
        "ok": True,
        "tagged": True,
        "user": doc["user"],
        "category": chosen,
        "label": LABELS[chosen],
        "tag": row,
        "vast_calls": 0,
        "destroyed": False,
    }


def retag_last(state: Path, user: str, category: str) -> dict:
    if category not in IDS:
        return {"ok": False, "error": "unknown lifebook category", "vast_calls": 0, "destroyed": False}
    doc = _load(state, user)
    if not doc["tags"]:
        return {"ok": False, "error": "nothing to tag", "vast_calls": 0, "destroyed": False}
    doc["tags"][-1]["category"] = category
    doc["tags"][-1]["label"] = LABELS[category]
    _save(state, doc)
    import offline_sync
    offline_sync.note(state, "podcoder_lifebook_tags", doc["tags"][-1])
    return {
        "ok": True,
        "tagged": True,
        "category": category,
        "label": LABELS[category],
        "tag": doc["tags"][-1],
        "vast_calls": 0,
        "destroyed": False,
    }
