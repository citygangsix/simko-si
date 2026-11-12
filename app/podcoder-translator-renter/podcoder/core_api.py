#!/usr/bin/env python3
"""Simco SI core routes: Lifebook scores, timeline, recommendations. Offline, local JSON.

GET  /api/lifebook/today              ?user=&day=&details=1
GET  /api/lifebook/category/<id>      ?user=&day=&days=30&details=1
GET  /api/timeline                    ?user=&start=&end=&days=45&categories=a,b&details=1
GET  /api/recs/today                  ?user=&day=&refresh=1
POST /api/recs/feedback               {user|token, rec_id, action: accept|ignore|complete, reason?}

Words by default; 0-100 numbers only with details=1. All read routes also accept
POST with the same keys in a JSON body. `token` (signed-in) wins over `user`.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import core_store
import lifebook_memory
import recs
import scoring
from analytics import correlate

TIMELINE_SCHEMA = "simco.timeline.v1"
TODAY_SCHEMA = "simco.lifebook.today.v1"
DISPLAY_RULE = "Words first. Numbers (0-100) only in the details view: add details=1."
METRIC_META = {
    "sleep_hours": {"label": "Sleep", "unit": "h", "min": 3, "max": 11},
    "sleep_quality": {"label": "Sleep quality", "unit": "1-10", "min": 1, "max": 10},
    "steps": {"label": "Steps", "unit": "steps", "min": 0, "max": 25000},
    "exercise_min": {"label": "Exercise", "unit": "min", "min": 0, "max": 150},
    "mood": {"label": "Mood", "unit": "1-10", "min": 1, "max": 10},
    "focus": {"label": "Focus", "unit": "1-10", "min": 1, "max": 10},
    "stress": {"label": "Stress", "unit": "1-10", "min": 1, "max": 10},
    "spending": {"label": "Spending", "unit": "USD", "min": 0, "max": 1000},
}
ROUTES = ("/api/lifebook/today", "/api/lifebook/category/", "/api/timeline", "/api/recs/today", "/api/recs/feedback")


def _base(ok: bool = True) -> dict:
    return {"ok": ok, "vast_calls": 0, "destroyed": False}


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _day(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError("day must be YYYY-MM-DD")


def _resolve_user(state: Path, body: dict) -> tuple[str | None, dict | None]:
    token = str(body.get("token") or "").strip()
    if token:
        import auth_accounts
        user = auth_accounts.email_for_token(state, token)
        if not user:
            return None, {**_base(False), "error": "sign in required"}
        return core_store.user_key(user), None
    return core_store.user_key(str(body.get("user") or "default")), None


def handles(path: str) -> bool:
    return any(path == r or (r.endswith("/") and path.startswith(r)) for r in ROUTES)


def try_handle(method: str, path: str, body: dict | None, state: Path):
    method = (method or "GET").upper()
    path = path.rstrip("/") or "/"
    if not handles(path):
        return None
    body = body or {}
    user, err = _resolve_user(state, body)
    if err:
        return 401, err
    try:
        if path == "/api/recs/feedback":
            if method != "POST":
                return 405, {**_base(False), "error": "POST only"}
            return feedback(state, user, str(body.get("rec_id") or ""), str(body.get("action") or ""), str(body.get("reason") or ""))
        if method not in {"GET", "POST"}:
            return 405, {**_base(False), "error": "GET or POST"}
        details = _truthy(body.get("details"))
        day = _day(body.get("day"))
        if path == "/api/lifebook/today":
            return 200, lifebook_today(state, user, day, details)
        if path.startswith("/api/lifebook/category/"):
            name = path.rsplit("/", 1)[-1]
            return category(state, user, name, day, int(body.get("days") or 30), details)
        if path == "/api/timeline":
            cats = [c for c in str(body.get("categories") or "").split(",") if c.strip()]
            return timeline(state, user, _day(body.get("start")), _day(body.get("end")) or day,
                            int(body.get("days") or 0), cats, details)
        if path == "/api/recs/today":
            return 200, recs_today(state, user, day, _truthy(body.get("refresh")))
    except ValueError as exc:
        return 400, {**_base(False), "error": str(exc)}
    return None


# ---------- handlers ----------

def lifebook_today(state: Path, user: str, day: str | None = None, details: bool = False) -> dict:
    doc = core_store.load(state, user)
    payload = scoring.today_payload(doc, day, details)
    return {
        **_base(), "schema": TODAY_SCHEMA, "user": doc["user"], "display_name": doc.get("display_name") or "",
        "synthetic": bool(doc.get("synthetic")), "details": details, "day": payload["day"],
        "levels": scoring.LEVELS, "display_rule": DISPLAY_RULE,
        "categories": payload["categories"], "empty": payload.get("empty", False),
        **({"rubric": scoring.RUBRIC_VERSION} if details else {}),
    }


def category(state: Path, user: str, name: str, day: str | None, days: int, details: bool):
    name = (name or "").strip().lower().replace("-", "_")
    by_label = {row["label"].lower().replace(" ", "_"): row["id"] for row in lifebook_memory.CATEGORIES}
    name = by_label.get(name, name)
    if name not in lifebook_memory.IDS:
        return 404, {**_base(False), "error": "unknown lifebook category", "categories": lifebook_memory.CATEGORIES}
    doc = core_store.load(state, user)
    payload = scoring.category_payload(doc, name, day, max(1, min(days, 366)), details)
    cal = scoring.engine.calendar(doc)
    findings = []
    if cal and payload["day"]:
        analysis = correlate.analyze(core_store.metric_series(doc), cal, until=payload["day"])
        findings = [f for f in analysis["findings"] + analysis["early_signals"] if name in f["categories"]]
        findings = [{"id": f["id"], "statement": f["statement"], "strength": f["strength"], "lag": f["lag"],
                     "n": f["n"], **({"rho": f["rho"], "q": f["q"], "ci95": f["ci95"]} if details else {})} for f in findings]
    return 200, {
        **_base(), "schema": "simco.lifebook.category.v1", "user": doc["user"], "synthetic": bool(doc.get("synthetic")),
        "details": details, "category": name, "label": lifebook_memory.LABELS[name], "levels": scoring.LEVELS,
        "display_rule": DISPLAY_RULE, **payload, "patterns": findings, "caveat": correlate.CAVEAT,
    }


def timeline(state: Path, user: str, start: str | None = None, end: str | None = None, days: int = 0,
             categories: list[str] | None = None, details: bool = False):
    doc = core_store.load(state, user)
    cal = scoring.engine.calendar(doc)
    cats = [c for c in (categories or []) if c in lifebook_memory.IDS] or [c["id"] for c in lifebook_memory.CATEGORIES]
    if categories and len(cats) != len(categories):
        return 400, {**_base(False), "error": "unknown category in categories", "categories": lifebook_memory.CATEGORIES}
    if not cal:
        return 200, _timeline_doc(doc, [], {}, cats, details, None, None)
    end = end or cal[-1]
    if start is None:
        span = max(1, min(days or 45, 366))
        start = (date.fromisoformat(end) - timedelta(days=span - 1)).isoformat()
    if start > end:
        return 400, {**_base(False), "error": "start is after end"}
    window = [(date.fromisoformat(start) + timedelta(days=i)).isoformat()
              for i in range((date.fromisoformat(end) - date.fromisoformat(start)).days + 1)]
    if len(window) > 366:
        return 400, {**_base(False), "error": "range is limited to 366 days"}
    scored = scoring.score_range(doc, window, cats)
    return 200, _timeline_doc(doc, window, scored, cats, details, start, end)


def _timeline_doc(doc: dict, window: list[str], scored: dict, cats: list[str], details: bool, start, end) -> dict:
    metric_rows: dict[str, dict] = {}
    seen_metrics = []
    for row in doc.get("metrics", []):
        if row["metric_key"] not in seen_metrics:
            seen_metrics.append(row["metric_key"])
        metric_rows.setdefault(row["day"], {})[row["metric_key"]] = row.get("value")
    keys = [k for k in METRIC_META if k in seen_metrics] + [k for k in seen_metrics if k not in METRIC_META]
    events_by_day: dict[str, list] = {}
    gap_days = set()
    for ev in doc.get("events", []):
        events_by_day.setdefault(ev["day"], []).append({
            "id": ev["id"], "kind": ev["kind"], "category": ev.get("category") or "", "title": ev["title"],
            "detail": ev.get("detail") or "", "day": ev["day"], "end_day": ev.get("end_day") or ev["day"],
            "synthetic": bool(ev.get("synthetic")),
        })
        if ev["kind"] == "gap":
            d = date.fromisoformat(ev["day"])
            while d.isoformat() <= (ev.get("end_day") or ev["day"]):
                gap_days.add(d.isoformat())
                d += timedelta(days=1)
    mem_count: dict[str, int] = {}
    for mem in doc.get("memories", []):
        mem_count[mem["day"]] = mem_count.get(mem["day"], 0) + 1
    out_days = []
    for day in window:
        lifebook = {}
        for cat in cats:
            row = scored[day][cat]
            cell = {"word": row["word"], "level": row["level"]}
            if details:
                cell["score"] = row["score"]
            lifebook[cat] = cell
        evs = sorted(events_by_day.get(day, []), key=lambda e: (e["kind"] != "milestone", e["kind"]))
        milestone = next((e["title"] for e in evs if e["kind"] in {"milestone", "life_event"}), None)
        workout = next((e["title"] for e in evs if e["kind"] == "workout"), None)
        out_days.append({
            "day": day,
            "weekday": date.fromisoformat(day).strftime("%a"),
            "lifebook": lifebook,
            "metrics": {k: metric_rows.get(day, {}).get(k) for k in keys},
            "events": evs,
            "milestone": milestone,
            "workout": workout,
            "chats": mem_count.get(day, 0),
            "gap": day in gap_days,
        })
    return {
        **_base(),
        "schema": TIMELINE_SCHEMA,
        "user": doc["user"],
        "display_name": doc.get("display_name") or "",
        "synthetic": bool(doc.get("synthetic")),
        "details": details,
        "range": {"start": start, "end": end, "days": len(window)},
        "levels": scoring.LEVELS,
        "no_data_word": scoring.engine.NO_DATA,
        "categories": [{"id": c, "label": lifebook_memory.LABELS[c]} for c in cats],
        "metrics": [{"key": k, **METRIC_META.get(k, {"label": k, "unit": "", "min": None, "max": None})} for k in keys],
        "event_kinds": ["milestone", "life_event", "workout", "gap"],
        "display_rule": DISPLAY_RULE,
        "days": out_days,
    }


def recs_today(state: Path, user: str, day: str | None = None, refresh: bool = False) -> dict:
    with core_store.lock():
        doc = core_store.load(state, user)
        result = recs.build_today(doc, day, refresh)
        if doc.get("metrics") or doc.get("memories"):
            core_store.save(state, doc)
    return {**_base(), "schema": "simco.recs.today.v1", "user": doc["user"], "synthetic": bool(doc.get("synthetic")),
            "max_per_day": recs.MAX_PER_DAY, **result}


def feedback(state: Path, user: str, rec_id: str, action: str, reason: str = ""):
    with core_store.lock():
        doc = core_store.load(state, user)
        result = recs.record_feedback(doc, rec_id, action, reason)
        if not result.get("ok"):
            code = 404 if result.get("error") == "unknown rec_id" else 400
            return code, {**_base(False), **result}
        core_store.save(state, doc)
    return 200, {**_base(), **result}
