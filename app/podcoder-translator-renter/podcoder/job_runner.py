#!/usr/bin/env python3
"""Persistent job queue. SQLite is the source of truth. Supabase is a local mirror note only."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

import local_db
import offline_sync

REDACT = ("password", "secret", "token", "ssn", "passphrase", "api_key", "authorization", "hf_token")


def _now() -> str:
    from auth_accounts import _now as stamp
    return stamp()


def _user(value: str) -> str:
    text = (value or "default").strip() or "default"
    return "".join(ch for ch in text if ch.isalnum() or ch in "@._+-")[:128] or "default"


def redact(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if any(part in str(key).lower() for part in REDACT):
                out[key] = "[redacted]"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _row(row) -> dict:
    payload = json.loads(row["payload"] or "{}")
    result = json.loads(row["result"] or "{}") if row["result"] else {}
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "kind": row["kind"],
        "status": row["status"],
        "payload": redact(payload),
        "result": redact(result) if isinstance(result, (dict, list)) else result,
        "error": row["error"],
        "attempts": row["attempts"],
        "max_attempts": row["max_attempts"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "vast_calls": 0,
        "destroyed": False,
    }


def _mirror(state: Path, public: dict) -> dict:
    if offline_sync.refused_project():
        return {"mirrored": False, "cloud": False, "refused": offline_sync.FORBIDDEN_PROJECT_REF}
    offline_sync.note(state, "podcoder_jobs", public)
    return {"mirrored": True, "cloud": False, "refused": ""}


def create_job(state: Path, user: str, kind: str, payload: dict | None = None, max_attempts: int = 3) -> dict:
    ident = secrets.token_hex(8)
    owner = _user(user)
    body = payload if isinstance(payload, dict) else {}
    stamp = _now()
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute(
                "insert into jobs (id, user_id, kind, status, payload, result, error, attempts, max_attempts, created_at, updated_at) values (?, ?, ?, ?, ?, '', '', 0, ?, ?, ?)",
                (ident, owner, (kind or "task").strip() or "task", "queued", json.dumps(body), max(1, int(max_attempts)), stamp, stamp),
            )
            conn.execute(
                "insert into job_logs (job_id, at, line) values (?, ?, ?)",
                (ident, stamp, "queued"),
            )
            conn.commit()
            row = conn.execute("select * from jobs where id = ?", (ident,)).fetchone()
        finally:
            conn.close()
    public = _row(row)
    mirror = _mirror(state, {key: public[key] for key in ("id", "user_id", "kind", "status", "created_at")})
    if (offline_sync.cloud_url() and "cloud" == _profile()):
        mirror["write_through"] = True
    public["mirror"] = mirror
    public["ok"] = True
    return public


def _profile() -> str:
    import os
    raw = (os.environ.get("PODCODER_PROFILE") or "").strip().lower()
    if raw in {"aspire", "cloud"}:
        return raw
    if (os.environ.get("PODCODER_COMPUTE") or "").strip().lower() == "cloud":
        return "cloud"
    return "aspire"


def list_jobs(state: Path, user: str = "") -> dict:
    owner = _user(user) if user else ""
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            if owner:
                rows = conn.execute("select * from jobs where user_id = ? order by created_at desc", (owner,)).fetchall()
            else:
                rows = conn.execute("select * from jobs order by created_at desc").fetchall()
        finally:
            conn.close()
    jobs = [_row(row) for row in rows]
    return {"ok": True, "jobs": jobs, "vast_calls": 0, "destroyed": False}


def get_job(state: Path, job_id: str) -> dict:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            row = conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
            logs = conn.execute("select at, line from job_logs where job_id = ? order by id", (job_id,)).fetchall() if row else []
        finally:
            conn.close()
    if not row:
        return {"ok": False, "error": "job not found", "vast_calls": 0, "destroyed": False}
    public = _row(row)
    public["ok"] = True
    public["logs"] = [{"at": item["at"], "line": item["line"]} for item in logs]
    return public


def log(state: Path, job_id: str, line: str) -> None:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute("insert into job_logs (job_id, at, line) values (?, ?, ?)", (job_id, _now(), line[:2000]))
            conn.commit()
        finally:
            conn.close()


def set_status(state: Path, job_id: str, status: str, result: dict | None = None, error: str = "") -> dict:
    stamp = _now()
    encoded = json.dumps(redact(result or {}))
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute(
                "update jobs set status = ?, result = ?, error = ?, updated_at = ? where id = ?",
                (status, encoded, error[:500], stamp, job_id),
            )
            conn.commit()
        finally:
            conn.close()
    log(state, job_id, status if not error else f"{status}: {error[:180]}")
    return get_job(state, job_id)


def cancel_job(state: Path, job_id: str) -> dict:
    current = get_job(state, job_id)
    if not current.get("ok"):
        return current
    if current["status"] == "done":
        return {"ok": False, "error": "job already finished", "vast_calls": 0, "destroyed": False}
    updated = set_status(state, job_id, "cancelled")
    updated["ok"] = True
    return updated


def retry_job(state: Path, job_id: str) -> dict:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            row = conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "job not found", "vast_calls": 0, "destroyed": False}
            if row["status"] not in {"failed", "cancelled"}:
                return {"ok": False, "error": "only a failed or cancelled job can be retried", "vast_calls": 0, "destroyed": False}
            attempts = int(row["attempts"]) + 1
            conn.execute(
                "update jobs set status = 'queued', attempts = ?, error = '', updated_at = ? where id = ?",
                (attempts, _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()
    log(state, job_id, "retry queued")
    public = get_job(state, job_id)
    public["ok"] = True
    return public


def execute(state: Path, job_id: str, workspace: Path | None = None, runner=None) -> dict:
    current = get_job(state, job_id)
    if not current.get("ok"):
        return current
    if current["status"] in {"cancelled", "needs_approval", "done"}:
        current["ok"] = True
        return current
    set_status(state, job_id, "running")
    raw = _load_payload(state, job_id)
    kind = current["kind"]
    try:
        if kind == "aider":
            import subprocess
            import aider_job
            if raw.get("engine") == "grok":
                import grok_coder
                outcome = grok_coder.run(state, job_id, raw, workspace)
            else:
                outcome = aider_job.run(state, job_id, raw, workspace, runner or subprocess.run)
        elif kind == "agent":
            import agent_loop
            outcome = agent_loop.run(state, job_id, raw, workspace, user=current.get("user_id") or "")
        elif kind == "scrape":
            import scrape_job
            outcome = scrape_job.run(state, job_id, raw)
        elif kind == "chart":
            import charts
            outcome = charts.run(state, job_id, raw)
        elif kind == "transcript":
            import transcripts
            outcome = transcripts.run(state, job_id, raw, current["user_id"])
        else:
            outcome = {"ok": False, "error": f"unknown job kind {kind}"}
    except Exception as exc:
        outcome = {"ok": False, "error": str(exc)}
    if outcome.get("status") == "needs_approval":
        return get_job(state, job_id)
    if outcome.get("ok"):
        finished = set_status(state, job_id, "done", outcome)
        import notify
        import backups
        notify.send(state, "job_done", f"Job {job_id} done", f"{kind} finished")
        backups.after_write(state, "job")
        finished["ok"] = True
        return finished
    return _fail_or_requeue(state, job_id, str(outcome.get("error") or "job failed"), outcome)


def _load_payload(state: Path, job_id: str) -> dict:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            row = conn.execute("select payload from jobs where id = ?", (job_id,)).fetchone()
        finally:
            conn.close()
    if not row:
        return {}
    try:
        parsed = json.loads(row["payload"] or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fail_or_requeue(state: Path, job_id: str, error: str, outcome: dict | None = None) -> dict:
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            row = conn.execute("select attempts, max_attempts from jobs where id = ?", (job_id,)).fetchone()
            attempts = int(row["attempts"]) + 1 if row else 1
            status = "queued" if row and attempts < int(row["max_attempts"]) else "failed"
            if outcome:
                # Keep the failure record (error, file, line, output) so the chat can explain it.
                conn.execute(
                    "update jobs set status = ?, attempts = ?, error = ?, result = ?, updated_at = ? where id = ?",
                    (status, attempts, error[:500], json.dumps(redact(outcome)), _now(), job_id),
                )
            else:
                conn.execute(
                    "update jobs set status = ?, attempts = ?, error = ?, updated_at = ? where id = ?",
                    (status, attempts, error[:500], _now(), job_id),
                )
            conn.commit()
        finally:
            conn.close()
    log(state, job_id, f"{status}: {error[:180]}")
    public = get_job(state, job_id)
    public["ok"] = status == "queued"
    return public
