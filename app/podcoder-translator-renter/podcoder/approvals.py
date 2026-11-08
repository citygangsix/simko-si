#!/usr/bin/env python3
"""One confirm step for spend, send, and delete. Never auto-approves."""
from __future__ import annotations

import secrets
from pathlib import Path

import local_db
import notify

WORDS = {"spend": "SPEND", "send": "SEND", "delete": "DELETE", "run": "RUN"}


def _now() -> str:
    from auth_accounts import _now as stamp
    return stamp()


def request(state: Path, job_id: str, action: str, summary: str, user: str = "") -> dict:
    gate = (action or "").strip().lower()
    if gate not in WORDS:
        return {"ok": False, "error": "action must be spend, send, delete, or run", "approved": False, "vast_calls": 0, "destroyed": False}
    ident = secrets.token_hex(8)
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute(
                "insert into approvals (id, job_id, action, summary, status, created_at) values (?, ?, ?, ?, ?, ?)",
                (ident, job_id, gate, summary[:500], "pending", _now()),
            )
            conn.execute(
                "update jobs set status = ?, updated_at = ? where id = ?",
                ("needs_approval", _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()
    note = notify.send(state, "needs_approval", f"Approval needed: {gate}", summary[:240], to=user if "@" in user else "")
    return {
        "ok": True,
        "approved": False,
        "status": "needs_approval",
        "action": gate,
        "approval_id": ident,
        "job_id": job_id,
        "delivered": note["delivered"],
        "vast_calls": 0,
        "destroyed": False,
    }


def confirm(state: Path, job_id: str, action: str, word: str) -> dict:
    gate = (action or "").strip().lower()
    expected = WORDS.get(gate)
    if not expected:
        return {"ok": False, "approved": False, "error": "unknown action", "vast_calls": 0, "destroyed": False}
    if (word or "").strip() != expected:
        return {
            "ok": False,
            "approved": False,
            "error": f"confirm must be {expected}",
            "status": "needs_approval",
            "vast_calls": 0,
            "destroyed": False,
        }
    with local_db.lock():
        conn = local_db.connect(state)
        try:
            row = conn.execute(
                "select id from approvals where job_id = ? and action = ? and status = 'pending' order by created_at desc limit 1",
                (job_id, gate),
            ).fetchone()
            if not row:
                return {"ok": False, "approved": False, "error": "nothing is waiting", "vast_calls": 0, "destroyed": False}
            conn.execute("update approvals set status = 'approved' where id = ?", (row["id"],))
            conn.execute(
                "update jobs set status = ?, updated_at = ? where id = ?",
                ("approved", _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()
    return {
        "ok": True,
        "approved": True,
        "status": "approved",
        "action": gate,
        "job_id": job_id,
        "performed": False,
        "vast_calls": 0,
        "destroyed": False,
    }
