#!/usr/bin/env python3
"""Recommendations engine (research brief A3).

Pipeline:
  1. Rules propose candidates. Each template is eligible only when it is tied to an
     analytics finding/early signal on its metrics, or to a category whose word is
     "Needs care" / trend "slipping", or a goal behind pace.
  2. Every candidate gets evidence links (finding | metric | memory | goal). A
     candidate with no evidence is dropped: it can never be shown.
  3. Beta-Bernoulli Thompson sampling ranks candidates per template:
     Beta(alpha, beta) with alpha = 1 + completes + 0.5*accepts, beta = 1 + ignores.
     The draw is multiplied by a relevance weight from the rule that fired.
  4. Top 3, one per category, with a cooldown: a template ignored in the last 3 days
     or completed yesterday/today is skipped.
Feedback (accept | ignore | complete) updates the arm and the rec's status.
"""
from __future__ import annotations

import hashlib
import random
import time
from datetime import date, timedelta

import lifebook_memory
import scoring
from analytics import correlate

MAX_PER_DAY = 3
ACTIONS = {"accept": (0.5, 0.0), "complete": (1.0, 0.0), "ignore": (0.0, 1.0)}
COOLDOWN_IGNORE_DAYS = 3

# template_id -> definition. `metrics` are the lever metrics the action moves;
# a finding links to a template when its predictor is one of them.
TEMPLATES = {
    "sleep_anchor": {
        "category": "health_fitness", "metrics": ["sleep_hours", "sleep_quality"], "effort": "low",
        "text": "Set a lights-out time of 10:45 PM tonight and put the phone across the room.",
        "measure": {"metric": "sleep_hours", "window_days": 7, "success": "7-day average sleep rises toward 7.5 h"},
    },
    "move_20": {
        "category": "health_fitness", "metrics": ["exercise_min", "steps"], "effort": "medium",
        "text": "Take a 20-minute brisk walk or easy run before 6 PM.",
        "measure": {"metric": "exercise_min", "window_days": 7, "success": "4+ days with 20+ minutes; watch sleep quality the same night"},
    },
    "spend_pause": {
        "category": "financial_life", "metrics": ["spending"], "effort": "low",
        "text": "Use a 24-hour pause on any non-essential purchase today.",
        "measure": {"metric": "spending", "window_days": 7, "success": "fewer spend spikes above your usual day; watch next-day stress"},
    },
    "focus_block": {
        "category": "career", "metrics": ["focus"], "effort": "medium",
        "text": "Do one 50-minute phone-away focus block on your most important task.",
        "measure": {"metric": "focus", "window_days": 7, "success": "focus check-ins hold at 6+ on block days"},
    },
    "evening_reflect": {
        "category": "emotional_life", "metrics": ["mood", "stress"], "effort": "low",
        "text": "Write three lines tonight: what drained you, what helped, one thing for tomorrow.",
        "measure": {"metric": "mood", "window_days": 7, "success": "mood check-ins steady or rising; fewer strained chats"},
    },
    "reach_out": {
        "category": "social_life", "metrics": [], "effort": "low",
        "text": "Text one friend to set a time to meet this week.",
        "measure": {"metric": "social_life chats", "window_days": 7, "success": "one meet-up logged this week"},
    },
    "partner_time": {
        "category": "love_relationship", "metrics": [], "effort": "medium",
        "text": "Plan 30 phone-free minutes with your partner tonight.",
        "measure": {"metric": "love_relationship chats", "window_days": 7, "success": "fewer strained relationship chats"},
    },
    "kid_time": {
        "category": "parenting", "metrics": [], "effort": "low",
        "text": "Give your kid 15 minutes of one-on-one time doing what they pick.",
        "measure": {"metric": "parenting chats", "window_days": 7, "success": "one upbeat parenting chat this week"},
    },
    "read_20": {
        "category": "intellectual_life", "metrics": ["focus"], "effort": "low",
        "text": "Read 20 pages before bed instead of scrolling.",
        "measure": {"metric": "book goal progress", "window_days": 7, "success": "reading goal back on pace"},
    },
    "quiet_10": {
        "category": "spiritual_life", "metrics": [], "effort": "low",
        "text": "Take 10 quiet minutes this morning with no input: walk, pray or sit.",
        "measure": {"metric": "spiritual_life chats", "window_days": 7, "success": "3 quiet sessions logged this week"},
    },
    "habit_one": {
        "category": "character", "metrics": [], "effort": "low",
        "text": "Pick one small habit to keep today and tick it off tonight.",
        "measure": {"metric": "character chats", "window_days": 7, "success": "habit kept 5 of 7 days"},
    },
    "home_reset": {
        "category": "quality_of_life", "metrics": ["stress", "sleep_quality"], "effort": "low",
        "text": "Do a 15-minute home reset: one surface, one bag out, lights low after 9.",
        "measure": {"metric": "stress", "window_days": 7, "success": "stress check-ins ease by the weekend"},
    },
    "vision_review": {
        "category": "life_vision", "metrics": [], "effort": "medium",
        "text": "Spend 15 minutes checking this week's plan against your one-year vision.",
        "measure": {"metric": "goal progress", "window_days": 14, "success": "goals behind pace move back on pace"},
    },
    "intimacy_talk": {
        "category": "sex_and_sensuality", "metrics": [], "effort": "medium",
        "text": "Make time for an unhurried check-in with your partner about closeness.",
        "measure": {"metric": "sex_and_sensuality chats", "window_days": 14, "success": "one upbeat chat in two weeks"},
    },
}


def arm_for(doc: dict, template_id: str) -> dict:
    arm = doc.setdefault("arms", {}).setdefault(template_id, {"alpha": 1.0, "beta": 1.0})
    return arm


def _rng(user: str, day: str, salt: str) -> random.Random:
    digest = hashlib.sha256(f"{user}|{day}|{salt}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _cooldown(doc: dict, template_id: str, day: str) -> str:
    today = date.fromisoformat(day)
    for fb in doc.get("feedback", []):
        if fb.get("template_id") != template_id:
            continue
        age = (today - date.fromisoformat(fb["day"])).days
        if fb["action"] == "ignore" and 0 <= age < COOLDOWN_IGNORE_DAYS:
            return "ignored recently"
        if fb["action"] == "complete" and 0 <= age <= 1:
            return "done recently"
    return ""


def candidates(doc: dict, day: str, analysis: dict, today: dict) -> list[dict]:
    words = {c["category"]: c for c in today["categories"]}
    stats = analysis.get("findings", []) + analysis.get("early_signals", [])
    series = {}
    for row in doc.get("metrics", []):
        if row.get("value") is not None:
            series.setdefault(row["metric_key"], {})[row["day"]] = row["value"]
    out = []
    for tid, tpl in TEMPLATES.items():
        cat = tpl["category"]
        evidence, relevance, reasons = [], 0.0, []
        # (a) analytics where this template's lever metric is the predictor
        for f in stats:
            if f["predictor"] in tpl["metrics"]:
                evidence.append({"kind": "finding", "ref_id": f["id"], "snippet": f["statement"],
                                 "strength": f["strength"], "rho": f["rho"], "q": f["q"], "n": f["n"]})
                relevance += 1.0 if f["strength"] == "finding" else 0.4
                reasons.append(f"{f['strength']}: {f['predictor']} -> {f['outcome']}")
        # (b) category needs care / slipping
        state = words.get(cat)
        if state and (state["word"] == "Needs care" or state.get("trend") == "slipping"):
            relevance += 0.8 if state["word"] == "Needs care" else 0.5
            reasons.append(f"{state['label']} is {state['word'].lower()}, trend {state.get('trend')}")
            evidence.append({"kind": "category", "ref_id": f"{cat}@{day}",
                             "snippet": f"{state['label']}: {state['word']} ({state.get('trend')}). {state.get('summary', '')}"})
        # (c) goals behind pace
        for goal in doc.get("goals", []):
            if goal["category"] == cat and scoring.engine._progress_word(goal, day) == "behind pace":
                relevance += 0.4
                reasons.append(f"goal behind pace: {goal['title']}")
                evidence.append({"kind": "goal", "ref_id": goal["id"], "snippet": f"Goal '{goal['title']}' is behind pace."})
        if relevance <= 0:
            continue
        # (d) memory and metric context for the evidence trail
        recent = [m for m in doc.get("memories", []) if cat in m.get("categories", [])
                  and 0 <= (date.fromisoformat(day) - date.fromisoformat(m["day"])).days < 14]
        for mem in recent[-2:]:
            evidence.append({"kind": "memory", "ref_id": mem["id"], "snippet": f"{mem['day']}: \"{mem['text']}\""})
        for metric in tpl["metrics"][:1]:
            vals = [series.get(metric, {}).get((date.fromisoformat(day) - timedelta(days=k)).isoformat()) for k in range(7)]
            vals = [v for v in vals if v is not None]
            if vals:
                evidence.append({"kind": "metric", "ref_id": f"{metric}@7d:{day}",
                                 "snippet": f"7-day average {metric.replace('_', ' ')}: {sum(vals) / len(vals):.1f} ({len(vals)} readings)"})
        out.append({"template_id": tid, "category": cat, "relevance": round(relevance, 3), "reasons": reasons, "evidence": evidence})
    return out


def build_today(doc: dict, day: str | None = None, refresh: bool = False) -> dict:
    """Return (and cache in doc['recs'][day]) at most 3 recs for the day. Caller saves doc."""
    cal = scoring.engine.calendar(doc)
    if not cal:
        return {"day": day, "recs": [], "caveat": correlate.CAVEAT, "candidates": 0}
    day = day or cal[-1]
    cached = doc.setdefault("recs", {}).get(day)
    if cached and not refresh:
        return {"day": day, "recs": cached, "caveat": correlate.CAVEAT, "cached": True}
    series = {}
    for row in doc.get("metrics", []):
        if row.get("value") is not None:
            series.setdefault(row["metric_key"], {})[row["day"]] = float(row["value"])
    analysis = correlate.analyze(series, cal, until=day)
    today = scoring.today_payload(doc, day)
    pool = candidates(doc, day, analysis, today)
    ranked = []
    for cand in pool:
        if not any(e["kind"] in {"finding", "metric", "memory", "goal", "category"} for e in cand["evidence"]):
            continue  # integrity: never show a rec without evidence
        why_not = _cooldown(doc, cand["template_id"], day)
        if why_not:
            continue
        arm = arm_for(doc, cand["template_id"])
        draw = _rng(doc["user"], day, f"{cand['template_id']}|{arm['alpha']}|{arm['beta']}").betavariate(arm["alpha"], arm["beta"])
        ranked.append((draw * (0.5 + min(cand["relevance"], 2.0) / 2.0), draw, cand))
    ranked.sort(key=lambda r: r[0], reverse=True)
    picked, seen = [], set()
    for priority, draw, cand in ranked:
        if cand["category"] in seen:
            continue
        seen.add(cand["category"])
        tpl = TEMPLATES[cand["template_id"]]
        picked.append({
            "id": f"rec-{day}-{cand['template_id']}",
            "day": day,
            "rank": len(picked) + 1,
            "template_id": cand["template_id"],
            "category": cand["category"],
            "category_label": lifebook_memory.LABELS[cand["category"]],
            "text": tpl["text"],
            "effort": tpl["effort"],
            "measurement": tpl["measure"],
            "why": cand["reasons"][:3],
            "evidence": cand["evidence"][:5],
            "status": "shown",
            "sampling": {"method": "thompson-beta", "draw": round(draw, 4), "priority": round(priority, 4),
                         "relevance": cand["relevance"]},
            "synthetic": bool(doc.get("synthetic")),
        })
        if len(picked) >= MAX_PER_DAY:
            break
    doc["recs"][day] = picked
    return {"day": day, "recs": picked, "caveat": correlate.CAVEAT, "candidates": len(pool), "cached": False}


def record_feedback(doc: dict, rec_id: str, action: str, reason: str = "") -> dict:
    action = (action or "").strip().lower()
    if action not in ACTIONS:
        return {"ok": False, "error": "action must be accept, ignore, or complete"}
    found = None
    for day, recs in doc.get("recs", {}).items():
        for rec in recs:
            if rec["id"] == rec_id:
                found = rec
                break
        if found:
            break
    if not found:
        return {"ok": False, "error": "unknown rec_id"}
    da, db = ACTIONS[action]
    arm = arm_for(doc, found["template_id"])
    arm["alpha"] = round(arm["alpha"] + da, 3)
    arm["beta"] = round(arm["beta"] + db, 3)
    found["status"] = {"accept": "accepted", "ignore": "ignored", "complete": "completed"}[action]
    entry = {"rec_id": rec_id, "template_id": found["template_id"], "category": found["category"], "action": action,
             "reason": (reason or "")[:500], "day": found["day"], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    doc.setdefault("feedback", []).append(entry)
    mean = arm["alpha"] / (arm["alpha"] + arm["beta"])
    return {"ok": True, "rec": found, "feedback": entry, "arm": {**arm, "mean": round(mean, 3)}}
