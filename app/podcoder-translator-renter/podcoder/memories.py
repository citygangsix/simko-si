#!/usr/bin/env python3
"""Local memory mirror. Categories come from Lifebook words. No numeric grades."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import lifebook_memory
import local_db
import offline_sync

TYPES = {"fact", "preference", "goal", "event"}


def _now() -> str:
    from auth_accounts import _now as stamp
    return stamp()


def tag_categories(text: str, tagger=None) -> list[str]:
    if tagger:
        found = tagger(text)
        if isinstance(found, str):
            found = [found] if found else []
    else:
        one = lifebook_memory.categorize(text)
        found = [one] if one else []
    clean = []
    for item in found:
        if item in lifebook_memory.IDS and item not in clean:
            clean.append(item)
    return clean


def add_memory(state: Path, user: str, text: str, kind: str, session_id: str = "", categories: list | None = None, tagger=None) -> dict:
    memory_type = (kind or "fact").strip().lower()
    if memory_type not in TYPES:
        return {"ok": False, "error": "type must be fact, preference, goal, or event", "vast_calls": 0, "destroyed": False}
    body = (text or "").strip()
    if not body:
        return {"ok": False, "error": "text required", "vast_calls": 0, "destroyed": False}
    chosen = [item for item in (categories or []) if item in lifebook_memory.IDS] or tag_categories(body, tagger)
    ident = secrets.token_hex(8)
    stamp = _now()
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute(
                "insert into memories (id, user_id, text, type, categories, source_session, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                (ident, user or "default", body, memory_type, json.dumps(chosen), session_id or "", stamp),
            )
            conn.commit()
        finally:
            conn.close()
    if chosen:
        lifebook_memory.tag_turn(state, user or "default", body, session_id or ident, chosen[0])
    if not offline_sync.refused_project():
        offline_sync.note(state, "podcoder_memories", {
            "id": ident,
            "user_id": user or "default",
            "text": body,
            "type": memory_type,
            "categories": chosen,
            "source_session": session_id or "",
            "created_at": stamp,
        })
    return {
        "ok": True,
        "id": ident,
        "type": memory_type,
        "categories": chosen,
        "source_session": session_id or "",
        "created_at": stamp,
        "vast_calls": 0,
        "destroyed": False,
    }


def recall(state: Path, user: str, category: str = "", limit: int = 10) -> dict:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            rows = conn.execute(
                "select * from memories where user_id = ? order by created_at desc",
                (user or "default",),
            ).fetchall()
        finally:
            conn.close()
    items = []
    for row in rows:
        cats = json.loads(row["categories"] or "[]")
        items.append({
            "id": row["id"],
            "user_id": row["user_id"],
            "text": row["text"],
            "type": row["type"],
            "categories": cats,
            "source_session": row["source_session"],
            "created_at": row["created_at"],
        })
    if category:
        preferred = [item for item in items if category in item["categories"]]
        rest = [item for item in items if category not in item["categories"]]
        items = preferred + rest
    return {"ok": True, "memories": items[: max(1, limit)], "vast_calls": 0, "destroyed": False}


def merge_remote(state: Path, user: str, records: list) -> int:
    """Keep local and cloud variants on conflict, with stable IDs for idempotence."""
    import hashlib
    added = 0
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            for record in records:
                if record.get("user_id") != user or record.get("type") not in TYPES or not record.get("text"):
                    continue
                ident = str(record.get("id") or "")
                if not ident:
                    continue
                row = conn.execute("select text, type, categories from memories where id=?", (ident,)).fetchone()
                categories = [c for c in record.get("categories",[]) if c in lifebook_memory.IDS]
                if row:
                    if row["text"] == record["text"] and row["type"] == record["type"] and json.loads(row["categories"]) == categories:
                        continue
                    ident += "-conflict-" + hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()[:12]
                count = conn.execute("insert or ignore into memories values (?, ?, ?, ?, ?, ?, ?)",
                    (ident,user,record["text"],record["type"],json.dumps(categories),record.get("source_session", ""),record.get("created_at") or _now())).rowcount
                added += count
            conn.commit()
        finally:
            conn.close()
    return added
