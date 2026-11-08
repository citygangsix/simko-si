#!/usr/bin/env python3
"""Cron routines and notify-me-when triggers. Tick enqueues jobs. No network."""
from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path

import job_runner
import local_db


def _now() -> str:
    from auth_accounts import _now as stamp
    return stamp()


def _field_match(field: str, value: int) -> bool:
    for part in (field or "").split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:] or "1")
            if step and value % step == 0:
                return True
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            if int(start) <= value <= int(end):
                return True
            continue
        if int(part) == value:
            return True
    return False


def cron_match(expr: str, when: datetime) -> bool:
    fields = (expr or "").split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    cron_dow = (when.weekday() + 1) % 7
    return (
        _field_match(minute, when.minute)
        and _field_match(hour, when.hour)
        and _field_match(dom, when.day)
        and _field_match(month, when.month)
        and _field_match(dow, cron_dow)
    )


def create_routine(state: Path, user: str, name: str, kind: str, spec: dict) -> dict:
    ident = secrets.token_hex(8)
    stamp = _now()
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute(
                "insert into routines (id, user_id, name, kind, spec, last_run, created_at) values (?, ?, ?, ?, ?, '', ?)",
                (ident, user or "default", name or "routine", kind, json.dumps(spec or {}), stamp),
            )
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "id": ident, "kind": kind, "vast_calls": 0, "destroyed": False}


def list_routines(state: Path, user: str = "") -> dict:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            if user:
                rows = conn.execute("select * from routines where user_id = ? order by created_at", (user,)).fetchall()
            else:
                rows = conn.execute("select * from routines order by created_at").fetchall()
        finally:
            conn.close()
    items = []
    for row in rows:
        items.append({
            "id": row["id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "kind": row["kind"],
            "spec": json.loads(row["spec"] or "{}"),
            "last_run": row["last_run"],
        })
    return {"ok": True, "routines": items, "vast_calls": 0, "destroyed": False}


def delete_routine(state: Path, routine_id: str) -> dict:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute("delete from routines where id = ?", (routine_id,))
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "deleted": routine_id, "vast_calls": 0, "destroyed": False}


def _stamp_run(state: Path, routine_id: str, mark: str) -> None:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute("update routines set last_run = ? where id = ?", (mark, routine_id))
            conn.commit()
        finally:
            conn.close()


def tick(state: Path, when: datetime | None = None) -> dict:
    moment = when or datetime.now().astimezone()
    minute_key = moment.strftime("%Y-%m-%dT%H:%M")
    created = []
    listed = list_routines(state).get("routines") or []
    for routine in listed:
        spec = routine["spec"] or {}
        if routine["kind"] == "cron":
            if not cron_match(str(spec.get("expr") or ""), moment):
                continue
            if routine["last_run"] == minute_key:
                continue
            job = job_runner.create_job(state, routine["user_id"], str(spec.get("job_kind") or "task"), spec.get("payload") or {})
            _stamp_run(state, routine["id"], minute_key)
            created.append(job["id"])
            import notify
            notify.send(state, "routine", routine["name"], str(spec.get("message") or "Routine queued"), str(spec.get("email") or ""))
        elif routine["kind"] == "when":
            name = str(spec.get("flag") or "")
            if not name or Path(name).name != name or "\\" in name or name in {".", ".."}:
                continue
            flag = state / "flags" / name
            if not flag.is_file():
                continue
            mark = str(flag.stat().st_mtime)
            if routine["last_run"] == mark:
                continue
            job = job_runner.create_job(state, routine["user_id"], str(spec.get("job_kind") or "task"), spec.get("payload") or {})
            _stamp_run(state, routine["id"], mark)
            created.append(job["id"])
            import notify
            notify.send(state, "routine", routine["name"], str(spec.get("message") or "Routine queued"), str(spec.get("email") or ""))
    return {"ok": True, "enqueued": created, "vast_calls": 0, "destroyed": False}


def start_background(state: Path):
    """Opt-in scheduler runs only while the app is open; returns a stop event."""
    import os
    import threading
    stop = threading.Event()
    routines = os.environ.get("SIMKO_ROUTINES") == "1"
    # Opt-in retries of queued memory sync / encrypted backup uploads (backoff inside).
    background = (os.environ.get("SIMKO_MEMORY_SYNC") == "1" and os.environ.get("SIMKO_MEMORY_SYNC_AUTO") == "1") \
        or os.environ.get("SIMKO_CLOUD_BACKUP") == "1"
    if not routines and not background:
        return stop
    def work():
        while not stop.is_set():
            if routines:
                try:
                    tick(state)
                except Exception:
                    pass
            if background:
                try:
                    import offline_sync
                    import cloud_backup
                    offline_sync.maybe_sync(state)
                    cloud_backup.maybe_flush(state)
                except Exception:
                    pass
            stop.wait(30)
    threading.Thread(target=work, daemon=True, name="simko-routines").start()
    return stop
