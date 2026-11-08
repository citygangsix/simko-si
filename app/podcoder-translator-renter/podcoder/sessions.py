#!/usr/bin/env python3
"""Many chat sessions, one shared model queue. No per-session model load."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

CAPACITY = 500
_LOCK = threading.Lock()
_MODEL_LOADS = 1


def _path(state: Path) -> Path:
    return state / "sessions.json"


def _load(state: Path) -> dict:
    path = _path(state)
    if not path.is_file():
        return {"sessions": [], "jobs": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"sessions": [], "jobs": []}
    doc.setdefault("sessions", [])
    doc.setdefault("jobs", [])
    return doc


def _save(state: Path, doc: dict) -> None:
    state.mkdir(parents=True, exist_ok=True)
    _path(state).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _user(value: str) -> str:
    text = (value or "default").strip() or "default"
    safe = "".join(ch for ch in text if ch.isalnum() or ch in "._-+@")[:128]
    return safe or "default"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _base(ok: bool = True) -> dict:
    return {"ok": ok, "vast_calls": 0, "destroyed": False, "model_loads": _MODEL_LOADS}


def _normalize(doc: dict) -> dict:
    for row in doc["sessions"]:
        row.setdefault("messages", [])
    return doc


def _find(doc: dict, owner: str, session_id: str) -> dict | None:
    for row in doc["sessions"]:
        if row.get("user") == owner and row.get("id") == session_id:
            row.setdefault("messages", [])
            return row
    return None


def _public(row: dict, *, with_messages: bool) -> dict:
    messages = list(row.get("messages") or [])
    out = {
        "id": row["id"],
        "user": row.get("user"),
        "title": row.get("title") or "chat",
        "created_at": row.get("created_at"),
        "message_count": len(messages),
    }
    if with_messages:
        out["messages"] = messages
    elif messages:
        last = messages[-1]
        out["last_role"] = last.get("role") or ""
        out["last_text"] = str(last.get("text") or "")[:160]
    return out


def create_session(state: Path, user: str, title: str = "") -> dict:
    with _LOCK:
        doc = _normalize(_load(state))
        owner = _user(user)
        owned = [row for row in doc["sessions"] if row.get("user") == owner]
        if len(owned) >= CAPACITY:
            return {**_base(False), "error": f"session cap {CAPACITY}", "capacity": CAPACITY}
        row = {
            "id": "s-" + uuid.uuid4().hex[:12],
            "user": owner,
            "title": (title or "chat")[:80],
            "created_at": _now(),
            "messages": [],
        }
        doc["sessions"].append(row)
        _save(state, doc)
        return {**_base(), "session": _public(row, with_messages=True), "capacity": CAPACITY}


def list_sessions(state: Path, user: str) -> dict:
    owner = _user(user)
    doc = _normalize(_load(state))
    rows = [_public(row, with_messages=False) for row in doc["sessions"] if row.get("user") == owner]
    queued = [job for job in doc["jobs"] if job.get("user") == owner and job.get("status") == "queued"]
    return {
        **_base(),
        "user": owner,
        "sessions": rows,
        "queued": len(queued),
        "capacity": CAPACITY,
    }


def get_session(state: Path, user: str, session_id: str) -> dict:
    owner = _user(user)
    row = _find(_normalize(_load(state)), owner, session_id)
    if row is None:
        return {**_base(False), "error": "unknown session"}
    return {**_base(), "session": _public(row, with_messages=True)}


def append_message(state: Path, user: str, session_id: str, text: str, role: str = "user") -> dict:
    """Store one turn on this session only. Does not copy it into any other chat."""
    safe_role = role if role in {"user", "assistant"} else "user"
    body = (text or "").strip()
    if not body:
        return {**_base(False), "error": "empty message"}
    with _LOCK:
        doc = _normalize(_load(state))
        row = _find(doc, _user(user), session_id)
        if row is None:
            return {**_base(False), "error": "unknown session"}
        message = {
            "id": "m-" + uuid.uuid4().hex[:12],
            "role": safe_role,
            "text": body[:4000],
            "at": _now(),
        }
        row["messages"].append(message)
        row["messages"] = row["messages"][-200:]
        _save(state, doc)
        return {**_base(), "session_id": row["id"], "message": message}


def _model_reply(text: str, state: Path, user: str) -> dict:
    """One shared reply. Grok, then Granite, then the canned line."""
    try:
        import llm_router

        routed = llm_router.complete(text=text, purpose="session", state=state, user=user)
        backend = str(routed.get("backend") or "canned")
        if backend == "grok":
            line = llm_router.as_everyday(str(routed.get("text") or ""), ask=text)
        elif backend == "granite":
            line = str(granite_reply(str(routed.get("text") or ""), text))
        else:
            line = str(routed.get("text") or llm_router.canned_text())
        return {"text": line[:4000], "backend": backend, "model": str(routed.get("model") or "")}
    except Exception:
        import granite_to_everyday

        return {"text": granite_to_everyday._fail("the reply was empty"), "backend": "canned", "model": ""}


def granite_reply(raw: str, ask: str) -> str:
    import granite_to_everyday

    translated = granite_to_everyday.translate(raw, ask=ask)
    return str(translated.get("everyday") or granite_to_everyday._fail("the reply was empty"))


def enqueue(state: Path, user: str, session_id: str, text: str) -> dict:
    """Queue a turn on the one shared model. Does not load a second model."""
    with _LOCK:
        doc = _load(state)
        owner = _user(user)
        doc = _normalize(doc)
        if _find(doc, owner, session_id) is None:
            return {**_base(False), "error": "unknown session"}
        body = (text or "")[:4000]
        message = {
            "id": "m-" + uuid.uuid4().hex[:12],
            "role": "user",
            "text": body,
            "at": _now(),
        }
        row = _find(doc, owner, session_id)
        row["messages"].append(message)
        row["messages"] = row["messages"][-200:]
        job = {
            "id": "j-" + uuid.uuid4().hex[:12],
            "user": owner,
            "session_id": session_id,
            "text": body,
            "status": "done",
            "model_loads": _MODEL_LOADS,
            "message_id": message["id"],
            "note": "Stored on this session and queued on the one shared model. No second model load.",
        }
        doc["jobs"].append(job)
        _save(state, doc)
        session_id = row["id"]
        job_id = job["id"]
    reply = _model_reply(body, state, owner)
    with _LOCK:
        doc = _normalize(_load(state))
        row = _find(doc, owner, session_id)
        job = next((item for item in doc.get("jobs") or [] if item.get("id") == job_id), None)
        assistant = {
            "id": "m-" + uuid.uuid4().hex[:12],
            "role": "assistant",
            "text": reply["text"],
            "backend": reply["backend"],
            "model": reply["model"],
            "at": _now(),
        }
        if row is not None:
            row["messages"].append(assistant)
            row["messages"] = row["messages"][-200:]
        if job is not None:
            job["backend"] = reply["backend"]
            job["reply"] = reply["text"]
            job["model"] = reply["model"]
        _save(state, doc)
    return {**_base(), "job": job or {}, "ahead": 0, "backend": reply["backend"], "reply": reply["text"]}


def search_sessions(state: Path, user: str, query: str) -> dict:
    """Filter this user's chats by title or message text. No model load."""
    owner = _user(user)
    needle = (query or "").strip().lower()
    doc = _normalize(_load(state))
    hits = []
    for row in doc["sessions"]:
        if row.get("user") != owner:
            continue
        blob = " ".join(
            [row.get("title") or ""]
            + [str(message.get("text") or "") for message in (row.get("messages") or [])]
        )
        if needle and needle not in blob.lower():
            continue
        hits.append(_public(row, with_messages=False))
    return {**_base(), "user": owner, "query": query or "", "sessions": hits}


def relay(state: Path, user: str, from_session_id: str, to_session_id: str, text: str = "", summary: str = "") -> dict:
    """Copy a marked note from one chat into another. The receiver's user turns stay their own."""
    body = (text or "").strip()
    brief = (summary or "").strip()
    if not body and not brief:
        return {**_base(False), "error": "relay needs text or summary"}
    if from_session_id == to_session_id:
        return {**_base(False), "error": "pick a different chat"}
    with _LOCK:
        doc = _normalize(_load(state))
        owner = _user(user)
        source = _find(doc, owner, from_session_id)
        target = _find(doc, owner, to_session_id)
        if source is None or target is None:
            return {**_base(False), "error": "unknown session"}
        stamp = _now()
        shown = (body or brief)[:4000]
        outbound = {
            "id": "m-" + uuid.uuid4().hex[:12],
            "role": "relay_out",
            "text": shown,
            "summary": brief[:4000],
            "from_session_id": source["id"],
            "to_session_id": target["id"],
            "to_title": target.get("title") or "chat",
            "at": stamp,
        }
        inbound = {
            "id": "m-" + uuid.uuid4().hex[:12],
            "role": "relay",
            "text": shown,
            "summary": brief[:4000],
            "from_session_id": source["id"],
            "from_title": source.get("title") or "chat",
            "to_session_id": target["id"],
            "at": stamp,
        }
        source["messages"].append(outbound)
        target["messages"].append(inbound)
        source["messages"] = source["messages"][-200:]
        target["messages"] = target["messages"][-200:]
        _save(state, doc)
        return {
            **_base(),
            "from_session_id": source["id"],
            "to_session_id": target["id"],
            "outbound": outbound,
            "inbound": inbound,
        }
