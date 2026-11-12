#!/usr/bin/env python3
"""Lifebook-13 score engine. Transparent rubric in RUBRIC.md. Stdlib only."""
from __future__ import annotations

from datetime import date, timedelta

import lifebook_memory

RUBRIC_VERSION = "lifebook-rubric-v1"
WORDS = [(75, "Thriving"), (60, "Growing"), (45, "Steady"), (0, "Needs care")]
LEVELS = ["Needs care", "Steady", "Growing", "Thriving"]  # ascending, index = level
NO_DATA = "Not discussed"
TONE = {"doing well": 1.0, "in play": 0.0, "strained": -1.0}
WINDOW = 7
QUIET_DAYS = 14
SHRINK = 0.5  # pseudo-weight pulling memory tone toward neutral

CATEGORY_METRICS = {
    "health_fitness": ["sleep_hours", "steps", "exercise_min", "sleep_quality"],
    "emotional_life": ["mood", "stress"],
    "quality_of_life": ["sleep_quality", "stress"],
    "career": ["focus"],
    "intellectual_life": ["focus"],
    "financial_life": ["spending"],
}


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def word_for(score) -> str:
    if score is None:
        return NO_DATA
    for floor, word in WORDS:
        if score >= floor:
            return word
    return "Needs care"


def level_for(word: str):
    return LEVELS.index(word) if word in LEVELS else None


def _d(day: str) -> date:
    return date.fromisoformat(day)


def normalize(metric: str, value: float, spend_median: float = 50.0) -> float:
    if metric == "sleep_hours":
        if 7 <= value <= 9:
            return 1.0
        gap = (7 - value) if value < 7 else (value - 9)
        return _clamp(1 - gap)  # 1h outside band -> 0, 2h -> -1
    if metric == "steps":
        return _clamp((value - 6000) / 4000)
    if metric == "exercise_min":
        return _clamp((value - 20) / 20)
    if metric == "stress":
        return _clamp((5.5 - value) / 4.5)
    if metric == "spending":
        med = spend_median or 50.0
        return _clamp((med - value) / med)
    return _clamp((value - 5.5) / 4.5)  # 1-10 scales: mood, focus, sleep_quality


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


class _Index:
    """Pre-indexes a core doc for fast per-day scoring."""

    def __init__(self, doc: dict):
        self.series: dict[str, dict[str, float]] = {}
        for row in doc.get("metrics", []):
            if row.get("value") is not None:
                self.series.setdefault(row["metric_key"], {})[row["day"]] = float(row["value"])
        self.mem_by_cat: dict[str, list[dict]] = {c: [] for c in lifebook_memory.IDS}
        for mem in doc.get("memories", []):
            for cat in mem.get("categories") or []:
                if cat in self.mem_by_cat:
                    self.mem_by_cat[cat].append(mem)
        self.goals_by_cat: dict[str, list[dict]] = {}
        for goal in doc.get("goals", []):
            self.goals_by_cat.setdefault(goal["category"], []).append(goal)


def score_day(doc: dict, category: str, day: str, index: _Index | None = None) -> dict:
    """Score one category on one day. Returns score, word, level, components and evidence ids."""
    idx = index or _Index(doc)
    today = _d(day)
    start = today - timedelta(days=WINDOW - 1)
    missing = []

    # M: memory tone
    num = den = 0.0
    mem_ids, recent_any = [], False
    for mem in idx.mem_by_cat.get(category, []):
        age = (today - _d(mem["day"])).days
        if 0 <= age < QUIET_DAYS:
            recent_any = True
        if 0 <= age < WINDOW:
            w = 0.85 ** age
            num += w * TONE.get(mem.get("status") or "in play", 0.0)
            den += w
            mem_ids.append(mem["id"])
    m_part = num / (den + SHRINK) if den else 0.0
    if not den:
        missing.append("memory")

    # X: metrics
    metric_parts, metric_detail = [], {}
    for metric in CATEGORY_METRICS.get(category, []):
        series = idx.series.get(metric, {})
        vals = [series[(start + timedelta(days=k)).isoformat()] for k in range(WINDOW)
                if (start + timedelta(days=k)).isoformat() in series]
        if len(vals) < 3:
            metric_detail[metric] = {"readings": len(vals), "used": False}
            continue
        med = 50.0
        if metric == "spending":
            hist = [v for d, v in series.items() if 0 <= (today - _d(d)).days < 30]
            med = _median(hist) or 50.0
        norm = sum(normalize(metric, v, med) for v in vals) / len(vals)
        metric_parts.append(norm)
        metric_detail[metric] = {"readings": len(vals), "avg": round(sum(vals) / len(vals), 2), "normalized": round(norm, 3), "used": True}
    x_part = sum(metric_parts) / len(metric_parts) if metric_parts else 0.0
    if CATEGORY_METRICS.get(category) and not metric_parts:
        missing.append("metrics")

    # G: goals
    goal_parts, goal_detail = [], []
    for goal in idx.goals_by_cat.get(category, []):
        prog = goal.get("progress", {})
        known = [d for d in prog if d <= day]
        if not known or day < goal["start"]:
            continue
        span = max(1, (_d(goal["end"]) - _d(goal["start"])).days + 1)
        expected = min(1.0, ((today - _d(goal["start"])).days + 1) / span)
        actual = prog[max(known)]
        part = _clamp(2 * (actual - expected))
        goal_parts.append(part)
        goal_detail.append({"goal_id": goal["id"], "progress": actual, "expected": round(expected, 3), "part": round(part, 3)})
    g_part = sum(goal_parts) / len(goal_parts) if goal_parts else 0.0

    has_data = recent_any or bool(metric_parts) or bool(goal_parts)
    if not has_data:
        score = None
    else:
        score = int(round(max(0.0, min(100.0, 50 + 25 * m_part + 25 * x_part + 10 * g_part))))
    word = word_for(score)
    return {
        "category": category,
        "day": day,
        "score": score,
        "word": word,
        "level": level_for(word),
        "components": {
            "base": 50,
            "memory": {"value": round(m_part, 3), "weight": 25, "tags_in_window": len(mem_ids)},
            "metrics": {"value": round(x_part, 3), "weight": 25, "detail": metric_detail},
            "goals": {"value": round(g_part, 3), "weight": 10, "detail": goal_detail},
            "missing": missing,
        },
        "evidence": {"memory_ids": mem_ids[-5:]},
        "rubric": RUBRIC_VERSION,
    }


def calendar(doc: dict) -> list[str]:
    days = {r["day"] for r in doc.get("metrics", [])} | {m["day"] for m in doc.get("memories", [])}
    if not days:
        return []
    lo, hi = _d(min(days)), _d(max(days))
    return [(lo + timedelta(days=i)).isoformat() for i in range((hi - lo).days + 1)]


def score_range(doc: dict, days: list[str] | None = None, categories: list[str] | None = None) -> dict[str, dict[str, dict]]:
    """day -> category -> score_day result."""
    idx = _Index(doc)
    cats = categories or [c["id"] for c in lifebook_memory.CATEGORIES]
    out = {}
    for day in days or calendar(doc):
        out[day] = {cat: score_day(doc, cat, day, idx) for cat in cats}
    return out


def trend_word(history: list) -> str:
    """history: scores (or None), oldest first, ending today; uses last 14."""
    last = [s for s in history[-7:] if s is not None]
    prev = [s for s in history[-14:-7] if s is not None]
    if len(last) < 3 or len(prev) < 3:
        return "new"
    delta = sum(last) / len(last) - sum(prev) / len(prev)
    if delta >= 5:
        return "rising"
    if delta <= -5:
        return "slipping"
    return "holding"


def _public(row: dict, details: bool) -> dict:
    out = {"category": row["category"], "label": lifebook_memory.LABELS[row["category"]], "word": row["word"], "level": row["level"]}
    if details:
        out["score"] = row["score"]
        out["components"] = row["components"]
        out["rubric"] = row["rubric"]
    return out


def today_payload(doc: dict, day: str | None = None, details: bool = False) -> dict:
    cal = calendar(doc)
    if not cal:
        return {"day": day, "categories": [], "empty": True}
    day = day or cal[-1]
    window = [d for d in cal if d <= day][-14:]
    scored = score_range(doc, window)
    cats = []
    for cat in lifebook_memory.CATEGORIES:
        row = scored[day][cat["id"]] if day in scored else score_day(doc, cat["id"], day)
        item = _public(row, details)
        item["trend"] = trend_word([scored[d][cat["id"]]["score"] for d in window]) if row["score"] is not None else "quiet"
        item["summary"] = summary_line(row)
        cats.append(item)
    return {"day": day, "categories": cats, "empty": False}


def summary_line(row: dict) -> str:
    """One short sentence in words. No Lifebook numbers (raw metric readings are fine)."""
    comp = row["components"]
    bits = []
    detail = comp["metrics"]["detail"]
    if detail.get("sleep_hours", {}).get("used"):
        bits.append(f"sleep has averaged {detail['sleep_hours']['avg']:.1f} h this week")
    elif detail.get("mood", {}).get("used"):
        bits.append("mood check-ins are " + ("bright" if comp["metrics"]["value"] > 0.2 else "low" if comp["metrics"]["value"] < -0.2 else "mixed"))
    tags = comp["memory"]["tags_in_window"]
    if tags:
        tone = comp["memory"]["value"]
        feel = "mostly upbeat" if tone > 0.15 else "mostly strained" if tone < -0.15 else "mixed"
        bits.append(f"{'one chat' if tags == 1 else 'several chats' if tags < 5 else 'many chats'} this week, {feel}")
    if comp["goals"]["detail"]:
        ahead = sum(1 for g in comp["goals"]["detail"] if g["part"] > 0.1)
        behind = sum(1 for g in comp["goals"]["detail"] if g["part"] < -0.1)
        bits.append("goals ahead of pace" if ahead > behind else "goals behind pace" if behind > ahead else "goals on pace")
    if not bits:
        return "Not discussed lately." if row["score"] is None else "No chats this week; based on earlier chats."
    text = "; ".join(bits)
    return text[0].upper() + text[1:] + "."


def category_payload(doc: dict, category: str, day: str | None = None, days: int = 30, details: bool = False) -> dict:
    cal = calendar(doc)
    day = day or (cal[-1] if cal else None)
    span = [d for d in cal if d <= day][-max(14, days):] if day else []
    window = span[-max(1, days):]
    scored = score_range(doc, span, [category])
    history = []
    for d in window:
        row = scored[d][category]
        item = {"day": d, "word": row["word"], "level": row["level"]}
        if details:
            item["score"] = row["score"]
        history.append(item)
    current = scored[day][category] if day in scored else None
    mem = [m for m in doc.get("memories", []) if category in (m.get("categories") or []) and (not day or m["day"] <= day)]
    return {
        "day": day,
        "current": {**_public(current, details), "summary": summary_line(current),
                    "trend": trend_word([scored[d][category]["score"] for d in span]) if current["score"] is not None else "quiet"} if current else None,
        "history": history,
        "recent_memories": [{"id": m["id"], "day": m["day"], "text": m["text"], "status": m["status"],
                             "synthetic": bool(m.get("synthetic"))} for m in mem[-8:]][::-1],
        "goals": [{"id": g["id"], "title": g["title"], "progress_word": _progress_word(g, day), **({"progress": g["progress"].get(day)} if details else {})}
                  for g in doc.get("goals", []) if g["category"] == category],
        "metrics": CATEGORY_METRICS.get(category, []),
    }


def _progress_word(goal: dict, day: str | None) -> str:
    if not day or day not in goal.get("progress", {}):
        return "not started"
    span = max(1, (_d(goal["end"]) - _d(goal["start"])).days + 1)
    expected = min(1.0, ((_d(day) - _d(goal["start"])).days + 1) / span)
    actual = goal["progress"][day]
    if actual >= 0.999:
        return "done"
    if actual - expected > 0.05:
        return "ahead of pace"
    if actual - expected < -0.05:
        return "behind pace"
    return "on pace"
