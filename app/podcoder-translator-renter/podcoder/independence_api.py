#!/usr/bin/env python3
"""Routes for the independence pack. No Vast calls and no new chat chrome."""
from __future__ import annotations

from pathlib import Path

import approvals
import backups
import charts
import connectors
import emotion
import humor
import job_runner
import memories
import scheduler
import transcripts


def _user(body: dict) -> str:
    return str(body.get("user") or "default")


def try_handle(method: str, path: str, body: dict | None, state: Path):
    method = (method or "GET").upper()
    path = path.rstrip("/") or "/"
    body = body or {}
    if path == "/api/jobs" or path.startswith("/api/jobs/"):
        return _jobs(method, path, body, state)
    if path == "/api/routines":
        return _routines(method, body, state)
    if method == "POST" and path == "/api/approvals":
        result = approvals.confirm(state, str(body.get("job_id") or ""), str(body.get("action") or ""), str(body.get("confirm") or ""))
        return (200 if result.get("ok") else 400), result
    if method == "POST" and path == "/api/charts":
        source = str(body.get("source") or "")
        template = str(body.get("template") or "")
        data = dict(body.get("data") or {})
        if source == "lifebook":
            data = charts.from_lifebook(state, _user(body))
            template = template or "ringMetrics"
        elif source == "crm":
            data = charts.from_crm()
            template = template or "barChart"
        drawn = charts.build(template, data)
        return (200 if drawn.get("ok") else 400), drawn
    if method == "POST" and path == "/api/memories":
        op = (body.get("op") or "recall").strip().lower()
        if op == "add":
            return 200, memories.add_memory(
                state,
                _user(body),
                str(body.get("text") or ""),
                str(body.get("type") or "fact"),
                str(body.get("session_id") or ""),
                body.get("categories") or None,
            )
        return 200, memories.recall(state, _user(body), str(body.get("category") or ""))
    if path == "/api/quotes":
        return 200, transcripts.search(state, str(body.get("q") or ""), str(body.get("speaker") or ""), str(body.get("category") or ""))
    if method == "POST" and path == "/api/emotion":
        op = (body.get("op") or "check").strip().lower()
        if op == "set":
            return 200, emotion.set_enabled(state, bool(body.get("enabled", True)))
        if op == "status":
            return 200, {"ok": True, "enabled": emotion.enabled(state), "vast_calls": 0, "destroyed": False}
        return 200, emotion.shape(state, str(body.get("text") or ""), str(body.get("category") or ""), body.get("enabled") if "enabled" in body else None)
    if method == "POST" and path == "/api/humor":
        op = (body.get("op") or "list").strip().lower()
        if op == "add":
            return 200, humor.add_bit(state, str(body.get("text") or ""), body.get("tags") or [], str(body.get("category") or ""), str(body.get("tone") or "light"), bool(body.get("clean", True)))
        if op == "pick":
            return 200, humor.pick(state, str(body.get("category") or ""), str(body.get("tone") or ""), str(body.get("context") or ""))
        return 200, humor.list_bits(state)
    if method == "GET" and path == "/api/connectors":
        return connectors.listing()
    if method == "POST" and path == "/api/backup":
        op = (body.get("op") or "run").strip().lower()
        if op == "restore":
            dest = Path(str(body.get("dest") or (state / "restored")))
            return 200, backups.restore(state, str(body.get("id") or ""), dest)
        if op == "due":
            return 200, backups.maybe_due(state)
        return 200, backups.backup(state, str(body.get("reason") or "manual"))
    return None


def _jobs(method: str, path: str, body: dict, state: Path):
    ident = path.split("/api/jobs/", 1)[1] if path.startswith("/api/jobs/") else ""
    if method == "GET" and ident:
        code = 200 if job_runner.get_job(state, ident).get("ok") else 404
        return code, job_runner.get_job(state, ident)
    if method == "GET":
        return 200, job_runner.list_jobs(state, str(body.get("user") or ""))
    op = (body.get("op") or "create").strip().lower()
    if op == "list":
        return 200, job_runner.list_jobs(state, str(body.get("user") or ""))
    if op == "get":
        found = job_runner.get_job(state, str(body.get("job_id") or ident))
        return (200 if found.get("ok") else 404), found
    if op == "cancel":
        result = job_runner.cancel_job(state, str(body.get("job_id") or ""))
        return (200 if result.get("ok") else 400), result
    if op == "retry":
        result = job_runner.retry_job(state, str(body.get("job_id") or ""))
        return (200 if result.get("ok") else 400), result
    if op == "run":
        workspace = Path(str(body.get("workspace") or (state / "workspace")))
        result = job_runner.execute(state, str(body.get("job_id") or ""), workspace)
        return (200 if result.get("ok") else 400), result
    created = job_runner.create_job(state, str(body.get("user") or "default"), str(body.get("kind") or "task"), body.get("payload") or {}, int(body.get("max_attempts") or 3))
    return 200, created


def _routines(method: str, body: dict, state: Path):
    if method == "GET":
        return 200, scheduler.list_routines(state, str(body.get("user") or ""))
    op = (body.get("op") or "list").strip().lower()
    if op == "create":
        return 200, scheduler.create_routine(state, str(body.get("user") or "default"), str(body.get("name") or ""), str(body.get("kind") or "cron"), body.get("spec") or {})
    if op == "delete":
        return 200, scheduler.delete_routine(state, str(body.get("id") or ""))
    if op == "tick":
        from datetime import datetime
        raw = str(body.get("at") or "")
        when = datetime.strptime(raw, "%Y-%m-%dT%H:%M") if raw else None
        return 200, scheduler.tick(state, when)
    return 200, scheduler.list_routines(state, str(body.get("user") or ""))
