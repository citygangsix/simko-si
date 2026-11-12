#!/usr/bin/env python3
"""Seed a fictional demo user, "Demo Dana", for Simco SI. EVERYTHING HERE IS SYNTHETIC.

Deterministic (random.Random(seed)), stdlib only, offline. Writes:
  * <state>/core/demo_dana.json   - metrics (long format), memory entries, goals,
                                    timeline events and a seed manifest
  * the existing memory stores, so the rest of the app sees Dana's chats:
      - lifebook_memory JSON (<state>/memory/demo_dana.json, newest 200 tags)
      - local_db sqlite `memories` table (one row per memory entry)

Signal model (per research brief A1): each metric = AR(1) baseline + weekly cycle
+ planted effects, then about 10% values dropped at random, a 3-day "vacation" gap
and some skipped weekend check-ins. Planted effects (recorded in the manifest so
tests can check the analytics engine finds them):
  sleep_hours(t-1)  -> mood(t)            positive
  exercise_min(t)   -> sleep_quality(t)   positive
  spending(t)       -> stress(t+1)        positive
  steps(t)          -> focus(t)           NULL control (no effect planted)

Usage:  python3 seed/seed_demo.py [--state DIR] [--days 45] [--end 2026-10-30] [--seed 20261030]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PODCODER = HERE.parent
if str(PODCODER) not in sys.path:
    sys.path.insert(0, str(PODCODER))

import core_store  # noqa: E402
import lifebook_memory  # noqa: E402

USER = core_store.DEMO_USER
DISPLAY = "Demo Dana (fictional, synthetic)"
DEFAULT_SEED = 20261030
DEFAULT_DAYS = 45

METRICS = {
    "sleep_hours": {"label": "Sleep", "unit": "h", "min": 3, "max": 11},
    "sleep_quality": {"label": "Sleep quality", "unit": "1-10", "min": 1, "max": 10},
    "steps": {"label": "Steps", "unit": "steps", "min": 0, "max": 25000},
    "exercise_min": {"label": "Exercise", "unit": "min", "min": 0, "max": 150},
    "mood": {"label": "Mood", "unit": "1-10", "min": 1, "max": 10},
    "focus": {"label": "Focus", "unit": "1-10", "min": 1, "max": 10},
    "stress": {"label": "Stress", "unit": "1-10", "min": 1, "max": 10},
    "spending": {"label": "Spending", "unit": "USD", "min": 0, "max": 1000},
}

PLANTED = [
    {"predictor": "sleep_hours", "outcome": "mood", "lag": 1, "sign": "+", "note": "last night's sleep lifts today's mood"},
    {"predictor": "exercise_min", "outcome": "sleep_quality", "lag": 0, "sign": "+", "note": "exercise days sleep better"},
    {"predictor": "spending", "outcome": "stress", "lag": 1, "sign": "+", "note": "big spend days raise next-day stress"},
]
NULL_CONTROLS = [{"predictor": "steps", "outcome": "focus", "lag": 0, "note": "no effect planted"}]

WORKOUTS = ["Run 5 km", "Strength", "Yoga", "Swim", "Bike 20 km", "Long walk"]

# Conversation lines per category: (doing well, in play, strained). Each line carries a
# Lifebook HINTS word so the existing tagger agrees, and a tone word for lifebook_memory._tone.
LINES = {
    "health_fitness": (
        "Slept {sleep}h and the workout felt strong today.",
        "Logged {steps} steps, the gym plan is still on.",
        "Only {sleep}h of sleep, I feel tired and the workout was hard.",
    ),
    "intellectual_life": (
        "Read two chapters of my book, feeling good about it.",
        "Want to study the stats course a bit more this week.",
        "Hard to read anything today, my head feels stuck.",
    ),
    "emotional_life": (
        "I feel happy and calm tonight.",
        "Trying to name what I feel before I react.",
        "I feel anxious and a bit sad today.",
    ),
    "character": (
        "Kept my morning habit, proud of the discipline.",
        "Thinking about being honest with my team on the delay.",
        "Broke my habit again, feel behind on discipline.",
    ),
    "spiritual_life": (
        "Ten quiet minutes on meaning this morning felt good.",
        "Went back to my faith notes for a few minutes.",
        "Hard week, I feel stuck on what gives this meaning.",
    ),
    "love_relationship": (
        "Great evening with my partner, we laughed a lot.",
        "Planning a date night with my partner.",
        "Tense talk with my partner, we are both stressed and worried.",
    ),
    "parenting": (
        "My kid read to me tonight, proud moment.",
        "Helping my daughter with the school project.",
        "Hard bedtime with my kid, I am tired.",
    ),
    "social_life": (
        "Dinner with a friend, felt great to catch up.",
        "Thinking of joining the community run club.",
        "Skipped my friend's party again, I feel behind socially.",
    ),
    "financial_life": (
        "Stayed under budget this week, feels good.",
        "Reviewed the budget and the rent is set.",
        "Spent ${spend} today and I am worried about the budget.",
    ),
    "career": (
        "Shipped the feature at work, team was happy.",
        "Planning the next sprint at work.",
        "Work deadline stress, I feel behind on the code.",
    ),
    "quality_of_life": (
        "Clean home and a slow morning, great rest.",
        "Rearranged the home office for more comfort.",
        "No rest this week, the home is a mess and I am tired.",
    ),
    "life_vision": (
        "Wrote my one-year vision, feels strong.",
        "Sketched a plan for next quarter's goal.",
        "Not sure the goal still fits, feel stuck.",
    ),
    "sex_and_sensuality": (
        "Felt close and intimate this week, good.",
        "Talked about desire and what we each want.",
        "Low desire lately, I am tired and stressed.",
    ),
}
# How often (per day) each category comes up. Some are rare on purpose (gaps).
TOPIC_WEIGHTS = {
    "health_fitness": 6, "career": 6, "emotional_life": 5, "financial_life": 3,
    "intellectual_life": 3, "love_relationship": 3, "social_life": 2, "quality_of_life": 2,
    "life_vision": 2, "character": 2, "spiritual_life": 1, "parenting": 1, "sex_and_sensuality": 0.5,
}

GOALS = [
    {"id": "g-sleep", "category": "health_fitness", "title": "Average 7.5h sleep", "pace": 1.0},
    {"id": "g-5k", "category": "health_fitness", "title": "Run a 5 km without stopping", "pace": 1.1},
    {"id": "g-save", "category": "financial_life", "title": "Save $1,500 for the coast trip", "pace": 0.7},
    {"id": "g-book", "category": "intellectual_life", "title": "Finish 3 books", "pace": 0.9},
    {"id": "g-friends", "category": "social_life", "title": "See a friend every week", "pace": 0.5},
    {"id": "g-vision", "category": "life_vision", "title": "Write a one-year vision", "pace": 1.3},
]


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _iso(day: date) -> str:
    return day.isoformat()


def generate(days: int = DEFAULT_DAYS, end: date | None = None, seed: int = DEFAULT_SEED) -> dict:
    """Return the full synthetic core document for Demo Dana. Pure, deterministic."""
    days = max(45, int(days))
    end = end or date.today()
    rng = random.Random(seed)
    start = end - timedelta(days=days - 1)
    calendar = [start + timedelta(days=i) for i in range(days)]
    vacation = set(range(days // 2 - 2, days // 2 + 1))  # 3-day gap mid-series

    # Latent AR(1) drivers.
    sleep, exercise, spend, focus_ar, mood_ar, stress_ar = [], [], [], 0.0, 0.0, 0.0
    sleep_dev = 0.0
    raw: list[dict] = []
    for i, day in enumerate(calendar):
        weekend = day.weekday() >= 5
        sleep_dev = 0.5 * sleep_dev + rng.gauss(0, 0.85)
        s = _clip(7.0 + (0.6 if weekend else 0.0) + sleep_dev, 4.0, 10.0)
        workout = rng.random() < (0.35 if weekend else 0.5)
        ex = _clip(rng.gauss(42, 14), 10, 90) if workout else 0.0
        sp = _clip(math.exp(rng.gauss(3.7, 0.7)) * (1.6 if weekend else 1.0), 5, 600)
        steps = _clip(5200 + 95 * ex + rng.gauss(0, 1400), 800, 22000)
        sq = _clip(5.4 + 0.045 * (ex - 20) + rng.gauss(0, 0.9), 1, 10)
        prev_sleep = sleep[-1] if sleep else 7.0
        mood_ar = 0.4 * mood_ar + rng.gauss(0, 0.6)
        mood = _clip(6.0 + 0.95 * (prev_sleep - 7.0) + mood_ar, 1, 10)
        focus_ar = 0.5 * focus_ar + rng.gauss(0, 0.9)
        focus = _clip(6.2 + (-0.8 if day.weekday() == 0 else 0.0) + focus_ar, 1, 10)
        prev_spend = spend[-1] if spend else 40.0
        stress_ar = 0.3 * stress_ar + rng.gauss(0, 0.7)
        stress = _clip(4.6 + 0.012 * (prev_spend - 50) + stress_ar, 1, 10)
        sleep.append(s)
        exercise.append(ex)
        spend.append(sp)
        raw.append({
            "sleep_hours": round(s, 1), "sleep_quality": round(sq, 1), "steps": int(round(steps, -1)),
            "exercise_min": int(round(ex)), "mood": round(mood, 1), "focus": round(focus, 1),
            "stress": round(stress, 1), "spending": round(sp, 2), "_workout": rng.choice(WORKOUTS) if workout else None,
        })

    # Missingness: ~10% random, vacation gap (only steps survive), skipped weekend check-ins.
    metrics = []
    missing_log = {"random": 0, "vacation_days": sorted(_iso(calendar[i]) for i in vacation), "weekend_skips": 0}
    for i, (day, row) in enumerate(zip(calendar, raw)):
        skip_checkin = day.weekday() == 6 and rng.random() < 0.4
        for key in METRICS:
            value = row[key]
            if i in vacation and key != "steps":
                value = None
            elif skip_checkin and key in {"mood", "focus", "stress"}:
                value = None
                missing_log["weekend_skips"] += 1
            elif rng.random() < 0.10:
                value = None
                missing_log["random"] += 1
            metrics.append({"day": _iso(day), "metric_key": key, "value": value, "source": "synthetic", "synthetic": True})

    # Conversations -> memory entries tagged with Lifebook categories.
    memories = []
    cats = list(TOPIC_WEIGHTS)
    weights = [TOPIC_WEIGHTS[c] for c in cats]
    for i, (day, row) in enumerate(zip(calendar, raw)):
        if i in vacation:
            continue  # no chats on vacation: a real gap
        if day.weekday() == 6 and rng.random() < 0.5:
            continue  # skipped weekend journaling
        session = f"s-demo-{_iso(day)}"
        count = rng.choice([1, 2, 2, 3])
        picked = []
        for _ in range(count):
            cat = rng.choices(cats, weights)[0]
            if cat not in picked:
                picked.append(cat)
        for n, cat in enumerate(picked):
            tone = _tone_for(cat, row, rng)
            template = LINES[cat][{"doing well": 0, "in play": 1, "strained": 2}[tone]]
            text = template.format(sleep=row["sleep_hours"], steps=f"{row['steps']:,}", spend=int(row["spending"]))
            hour = 8 + 5 * n + rng.randint(0, 3)
            memories.append({
                "id": f"mem-{_iso(day)}-{n}",
                "day": _iso(day),
                "at": f"{_iso(day)}T{hour:02d}:{rng.randint(0, 59):02d}:00Z",
                "session_id": session,
                "text": text,
                "categories": [cat],
                "status": tone,  # intended tone (lifebook_memory._tone misses words next to punctuation)
                "type": "event",
                "synthetic": True,
            })

    goals = []
    for goal in GOALS:
        progress = {}
        for i, day in enumerate(calendar):
            frac = (i + 1) / days
            value = _clip(frac * goal["pace"] + rng.gauss(0, 0.03), 0, 1)
            if i in vacation and progress:
                value = list(progress.values())[-1]
            progress[_iso(day)] = round(value, 3)
        goals.append({
            "id": goal["id"], "category": goal["category"], "title": goal["title"],
            "start": _iso(start), "end": _iso(end), "progress": progress, "synthetic": True,
        })

    events = _events(calendar, raw, vacation)
    return {
        "user": USER,
        "display_name": DISPLAY,
        "synthetic": True,
        "metric_meta": METRICS,
        "metrics": metrics,
        "memories": memories,
        "goals": goals,
        "events": events,
        "manifest": {
            "seed": seed, "days": days, "start": _iso(start), "end": _iso(end),
            "planted_effects": PLANTED, "null_controls": NULL_CONTROLS, "missing": missing_log,
            "generator": "podcoder/seed/seed_demo.py", "synthetic": True,
        },
        "recs": {}, "feedback": [], "arms": {},
    }


def _tone_for(cat: str, row: dict, rng: random.Random) -> str:
    """Tone follows the metrics where a metric exists, so memory and metrics agree."""
    signal = None
    if cat == "health_fitness" and row["sleep_hours"] is not None:
        signal = (row["sleep_hours"] - 6.8) / 1.2 + (0.5 if row["exercise_min"] else -0.2)
    elif cat in {"emotional_life", "love_relationship", "sex_and_sensuality"}:
        signal = (row["mood"] - 6.0) / 1.2
    elif cat in {"career", "intellectual_life"}:
        signal = (row["focus"] - 6.0) / 1.2
    elif cat == "financial_life":
        signal = (60 - row["spending"]) / 40
    elif cat == "quality_of_life":
        signal = (5.5 - row["stress"]) / 1.2
    if signal is None:
        signal = rng.gauss(0.1, 1.0)
    signal += rng.gauss(0, 0.5)
    if signal > 0.5:
        return "doing well"
    if signal < -0.5:
        return "strained"
    return "in play"


def _events(calendar: list[date], raw: list[dict], vacation: set[int]) -> list[dict]:
    n = len(calendar)
    plan = [
        (2, "milestone", "intellectual_life", "Started the 6-week reading plan", ""),
        (5, "milestone", "health_fitness", "Started couch-to-5k", "Goal: run 5 km without stopping"),
        (9, "life_event", "love_relationship", "Tense week with partner", "Several strained chats"),
        (14, "milestone", "career", "Shipped the portfolio site", ""),
        (min(vacation), "gap", "quality_of_life", "Vacation, no tracking", "3 days with no check-ins or chats"),
        (n // 2 + 4, "milestone", "financial_life", "Budget reset", "Moved $200 to the trip fund"),
        (n - 15, "life_event", "career", "Big work launch", "Long days and late nights"),
        (n - 9, "milestone", "health_fitness", "First 5 km run", ""),
        (n - 4, "milestone", "life_vision", "Wrote the one-year vision", ""),
        (n - 2, "milestone", "social_life", "Booked the coast trip with friends", ""),
    ]
    out = []
    for idx, kind, cat, title, detail in plan:
        idx = max(0, min(n - 1, idx))
        row = {
            "id": f"ev-{calendar[idx].isoformat()}-{cat}",
            "day": calendar[idx].isoformat(),
            "end_day": calendar[max(vacation)].isoformat() if kind == "gap" else calendar[idx].isoformat(),
            "kind": kind, "category": cat, "title": title, "detail": detail, "synthetic": True,
        }
        out.append(row)
    for i, (day, row) in enumerate(zip(calendar, raw)):
        if row["_workout"] and i not in vacation:
            out.append({
                "id": f"ev-{day.isoformat()}-workout", "day": day.isoformat(), "end_day": day.isoformat(),
                "kind": "workout", "category": "health_fitness", "title": row["_workout"],
                "detail": f"{row['exercise_min']} min", "synthetic": True,
            })
    out.sort(key=lambda r: (r["day"], r["kind"]))
    return out


def write(state: Path, days: int = DEFAULT_DAYS, end: date | None = None, seed: int = DEFAULT_SEED, mirror: bool = True) -> dict:
    """Generate and write Dana to the core store, and mirror chats into the existing memory stores."""
    state = Path(state)
    doc = generate(days=days, end=end, seed=seed)
    path = core_store.save(state, doc)
    mirrored = {"lifebook_tags": 0, "sqlite_memories": 0}
    if mirror:
        mirrored = _mirror(state, doc)
    return {
        "ok": True, "user": USER, "path": str(path), "synthetic": True,
        "days": doc["manifest"]["days"], "start": doc["manifest"]["start"], "end": doc["manifest"]["end"],
        "metrics": len(doc["metrics"]), "memories": len(doc["memories"]), "events": len(doc["events"]),
        "goals": len(doc["goals"]), **mirrored, "vast_calls": 0, "destroyed": False,
    }


def _mirror(state: Path, doc: dict) -> dict:
    """Write Dana's chats through the existing Lifebook-13 memory stores (offline)."""
    import local_db

    tags = []
    for mem in doc["memories"]:
        cat = mem["categories"][0]
        tags.append({
            "category": cat, "label": lifebook_memory.LABELS[cat], "text": mem["text"][:240],
            "session_id": mem["session_id"], "status": mem["status"], "at": mem["at"], "synthetic": True,
        })
    lb = lifebook_memory._load(state, USER)
    lb["tags"] = [t for t in lb["tags"] if not t.get("synthetic")] + tags
    lb["tags"] = lb["tags"][-200:]
    lifebook_memory._save(state, lb)

    with local_db.lock():
        conn = local_db.connect(state)
        try:
            conn.execute("delete from memories where user_id = ? and id like 'mem-%'", (USER,))
            conn.executemany(
                "insert or replace into memories (id, user_id, text, type, categories, source_session, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                [(m["id"], USER, m["text"], m["type"], json.dumps(m["categories"]), m["session_id"], m["at"]) for m in doc["memories"]],
            )
            conn.commit()
        finally:
            conn.close()
    return {"lifebook_tags": len(lb["tags"]), "sqlite_memories": len(doc["memories"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default=None, help="state dir (default $PODCODER_STATE_DIR or ./status)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--end", default="", help="last day, YYYY-MM-DD (default today)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--no-mirror", action="store_true", help="only write the core JSON")
    args = parser.parse_args(argv)
    import os
    state = Path(args.state or os.environ.get("PODCODER_STATE_DIR") or (PODCODER / "status"))
    end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else None
    print(json.dumps(write(state, args.days, end, args.seed, mirror=not args.no_mirror), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
