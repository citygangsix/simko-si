#!/usr/bin/env python3
"""Offline tests for the Simco SI core: seed, scoring, analytics, recs, APIs, SQL file.

Run:  cd podcoder-translator-renter/podcoder && python3 -m pytest -q test_simco_core.py
No network, no GPU, no live database.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import threading
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pytest

import core_api
import core_store
import lifebook_memory
import product_api
import recs
import scoring
from analytics import correlate
from seed import seed_demo

ROOT = Path(__file__).resolve().parent
END = date(2026, 10, 30)
USER = core_store.DEMO_USER


@pytest.fixture()
def state(tmp_path):
    seed_demo.write(tmp_path, end=END)
    return tmp_path


@pytest.fixture(scope="module")
def doc():
    return seed_demo.generate(end=END)


def _days(d):
    return sorted({r["day"] for r in d["metrics"]})


# ---------- seed ----------

def test_seed_is_deterministic_synthetic_and_45_days(doc):
    again = seed_demo.generate(end=END)
    assert json.dumps(doc, sort_keys=True) == json.dumps(again, sort_keys=True)
    assert doc["synthetic"] is True and "fictional" in doc["display_name"].lower()
    days = _days(doc)
    assert len(days) >= 45 and days[-1] == END.isoformat()
    for key in ("metrics", "memories", "goals", "events"):
        assert doc[key], key
        assert all(row.get("synthetic") is True for row in doc[key]), key
    keys = {r["metric_key"] for r in doc["metrics"]}
    assert {"sleep_hours", "steps", "mood", "focus", "exercise_min"} <= keys


def test_seed_memories_use_lifebook_categories_and_cover_most(doc):
    cats = {c for m in doc["memories"] for c in m["categories"]}
    assert cats <= lifebook_memory.IDS
    assert len(cats) >= 11
    assert {m["status"] for m in doc["memories"]} <= {"doing well", "in play", "strained"}
    assert len(doc["memories"]) >= 45


def test_seed_has_gaps_and_missing_values(doc):
    values = [r["value"] for r in doc["metrics"]]
    share = sum(v is None for v in values) / len(values)
    assert 0.08 <= share <= 0.30
    gap = [e for e in doc["events"] if e["kind"] == "gap"]
    assert gap and gap[0]["end_day"] > gap[0]["day"]
    vac = set(doc["manifest"]["missing"]["vacation_days"])
    assert len(vac) == 3
    assert not any(m["day"] in vac for m in doc["memories"])
    assert doc["manifest"]["planted_effects"] and doc["manifest"]["null_controls"]


def test_seed_writes_through_existing_memory_stores(state):
    listed = lifebook_memory.list_memory(state, USER)
    assert listed["tags"] and all(t.get("synthetic") for t in listed["tags"])
    import memories
    recalled = memories.recall(state, USER, "health_fitness", limit=500)
    assert len(recalled["memories"]) >= 45
    assert recalled["memories"][0]["categories"] == ["health_fitness"]


# ---------- analytics ----------

def test_spearman_and_pvalue_basics():
    assert correlate.spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7]) == pytest.approx(0.8207826816681233)
    assert correlate.ranks([10, 20, 20, 30]) == [1, 2.5, 2.5, 4]
    # scipy.stats.pearsonr-equivalent t-test: r=0.5, n=30 -> p ~= 0.00490
    assert correlate.p_value(0.5, 30) == pytest.approx(0.00490, abs=2e-4)
    assert correlate.p_value(0.0, 30) == pytest.approx(1.0)
    lo, hi = correlate.fisher_ci(0.5, 30)
    assert lo < 0.5 < hi and lo > 0


def test_bh_fdr_matches_reference():
    p = [0.01, 0.04, 0.03, 0.005, 0.2]
    # reference from statsmodels multipletests(method="fdr_bh")
    assert correlate.bh_fdr(p) == pytest.approx([0.025, 0.05, 0.05, 0.025, 0.2])


def test_planted_effects_found_and_null_control_not(doc):
    result = correlate.analyze(core_store.metric_series(doc), _days(doc))
    found = {(f["predictor"], f["outcome"]): f for f in result["findings"]}
    for eff in doc["manifest"]["planted_effects"]:
        f = found.get((eff["predictor"], eff["outcome"]))
        assert f is not None, eff
        assert f["lag"] == eff["lag"] and f["rho"] > 0
        assert f["n"] >= correlate.FINDING_PAIRS and f["q"] < correlate.MAX_Q
    for ctl in doc["manifest"]["null_controls"]:
        assert (ctl["predictor"], ctl["outcome"]) not in found
    assert result["caveat"] == correlate.CAVEAT and "not causation" in result["caveat"].lower()
    assert all("not causation" in f["statement"].lower() for f in result["findings"])
    assert {t["lag"] for t in result["tests"]} == {0, 1, 2, 3}


def test_missing_data_gate_and_min_pairs():
    days = [(END - timedelta(days=i)).isoformat() for i in range(30)][::-1]
    sparse = {"sleep_hours": {d: 7.0 + (i % 3) for i, d in enumerate(days) if i % 2 == 0},
              "mood": {d: 5.0 + (i % 4) for i, d in enumerate(days) if i % 2 == 0}}
    out = correlate.analyze(sparse, days, pairs=[("sleep_hours", "mood")])
    assert out["tests_run"] == 0
    assert out["skipped"] and out["skipped"][0]["reason"] == "missing-data gate"
    short = days[:10]
    dense = {"sleep_hours": {d: float(i) for i, d in enumerate(short)}, "mood": {d: float(i) for i, d in enumerate(short)}}
    out = correlate.analyze(dense, short, pairs=[("sleep_hours", "mood")])
    assert out["tests_run"] == 0 and "fewer than 14" in out["skipped"][0]["reason"]


# ---------- scoring ----------

@pytest.mark.parametrize("score,word", [(100, "Thriving"), (75, "Thriving"), (74, "Growing"), (60, "Growing"),
                                        (59, "Steady"), (45, "Steady"), (44, "Needs care"), (0, "Needs care"),
                                        (None, "Not discussed")])
def test_word_thresholds(score, word):
    assert scoring.word_for(score) == word


def test_scores_cover_13_categories_every_day_in_range(doc):
    scored = scoring.score_range(doc)
    assert len(scored) >= 45
    for day, cats in scored.items():
        assert set(cats) == lifebook_memory.IDS
        for row in cats.values():
            assert row["score"] is None or 0 <= row["score"] <= 100
            assert row["word"] == scoring.word_for(row["score"])
    words = {row["word"] for cats in scored.values() for row in cats.values()}
    assert {"Growing", "Steady", "Needs care"} <= words


def test_score_rubric_is_transparent(doc):
    row = scoring.score_day(doc, "health_fitness", END.isoformat())
    c = row["components"]
    expect = 50 + 25 * c["memory"]["value"] + 25 * c["metrics"]["value"] + 10 * c["goals"]["value"]
    assert row["score"] == int(round(max(0, min(100, expect)))) or abs(row["score"] - expect) <= 1
    assert (ROOT / "scoring" / "RUBRIC.md").is_file()


def test_no_data_category_is_not_discussed():
    empty = core_store.empty("nobody")
    empty["metrics"] = [{"day": "2026-10-01", "metric_key": "mood", "value": 6, "source": "t"}]
    row = scoring.score_day(empty, "parenting", "2026-10-01")
    assert row["score"] is None and row["word"] == "Not discussed" and row["level"] is None


# ---------- APIs ----------

def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def test_lifebook_today_words_by_default_numbers_with_details(state):
    code, out = product_api.try_handle("GET", "/api/lifebook/today", {"user": USER}, state)
    assert code == 200 and out["ok"] and out["day"] == END.isoformat()
    assert len(out["categories"]) == 13
    keys = set(_walk_keys(out))
    assert "score" not in keys and "components" not in keys
    assert "%" not in json.dumps(out)
    assert all(c["word"] in scoring.LEVELS + ["Not discussed"] for c in out["categories"])
    code, det = product_api.try_handle("GET", "/api/lifebook/today", {"user": USER, "details": "1"}, state)
    assert all("score" in c for c in det["categories"])
    assert [c["word"] for c in det["categories"]] == [c["word"] for c in out["categories"]]


def test_lifebook_category_route(state):
    code, out = product_api.try_handle("GET", "/api/lifebook/category/health_fitness", {"user": USER, "days": "14"}, state)
    assert code == 200 and out["category"] == "health_fitness" and len(out["history"]) == 14
    assert "score" not in set(_walk_keys(out["history"]))
    assert any(p["strength"] == "finding" for p in out["patterns"])
    assert "not causation" in out["caveat"].lower()
    code, _ = product_api.try_handle("GET", "/api/lifebook/category/astrology", {"user": USER}, state)
    assert code == 404
    code, out = product_api.try_handle("GET", "/api/lifebook/category/financial-life", {"user": USER, "details": "1"}, state)
    assert code == 200 and "score" in out["history"][-1]


def test_timeline_schema_is_stable(state):
    code, out = product_api.try_handle("GET", "/api/timeline", {"user": USER}, state)
    assert code == 200 and out["schema"] == "simco.timeline.v1"
    for key in ("user", "display_name", "synthetic", "details", "range", "levels", "no_data_word", "categories",
                "metrics", "event_kinds", "display_rule", "days"):
        assert key in out, key
    days = out["days"]
    assert len(days) == 45 == out["range"]["days"]
    for a, b in zip(days, days[1:]):
        assert date.fromisoformat(b["day"]) - date.fromisoformat(a["day"]) == timedelta(days=1)
    for d in days:
        assert set(d) == {"day", "weekday", "lifebook", "metrics", "events", "milestone", "workout", "chats", "gap"}
        assert set(d["lifebook"]) == lifebook_memory.IDS
        assert set(d["metrics"]) == {m["key"] for m in out["metrics"]}
        for cell in d["lifebook"].values():
            assert set(cell) == {"word", "level"}
    assert sum(d["gap"] for d in days) == 3
    assert any(d["milestone"] for d in days) and any(d["workout"] for d in days)
    code, det = product_api.try_handle("GET", "/api/timeline", {"user": USER, "days": "7", "details": "1",
                                                                "categories": "career,health_fitness"}, state)
    assert len(det["days"]) == 7 and set(det["days"][0]["lifebook"]) == {"career", "health_fitness"}
    assert "score" in det["days"][0]["lifebook"]["career"]
    code, _ = product_api.try_handle("GET", "/api/timeline", {"user": USER, "categories": "nope"}, state)
    assert code == 400
    code, _ = product_api.try_handle("GET", "/api/timeline", {"user": USER, "start": "2026-10-30", "end": "2026-10-01"}, state)
    assert code == 400


def test_sample_timeline_file_matches_schema():
    sample = ROOT.parents[1] / "sample_timeline.json"
    if not sample.is_file():
        pytest.skip("sample not generated in this checkout")
    doc = json.loads(sample.read_text())
    assert doc["schema"] == "simco.timeline.v1" and doc["synthetic"] is True and len(doc["days"]) == 45
    assert "score" not in set(_walk_keys(doc))


def test_recs_today_max_three_with_evidence_effort_measurement(state):
    code, out = product_api.try_handle("GET", "/api/recs/today", {"user": USER}, state)
    assert code == 200 and 1 <= len(out["recs"]) <= 3
    assert len({r["category"] for r in out["recs"]}) == len(out["recs"])
    for r in out["recs"]:
        assert r["evidence"] and all(e["kind"] in {"finding", "metric", "memory", "goal", "category"} for e in r["evidence"])
        assert r["effort"] in {"low", "medium", "high"}
        assert {"metric", "window_days", "success"} <= set(r["measurement"])
        assert r["status"] == "shown"
    assert "not causation" in out["caveat"].lower()
    code, again = product_api.try_handle("GET", "/api/recs/today", {"user": USER}, state)
    assert [r["id"] for r in again["recs"]] == [r["id"] for r in out["recs"]] and again["cached"]


def test_every_day_recs_never_exceed_three_or_lack_evidence(doc):
    d = json.loads(json.dumps(doc))
    for day in _days(d)[20:]:
        out = recs.build_today(d, day)
        assert len(out["recs"]) <= 3
        assert all(r["evidence"] for r in out["recs"])


def test_feedback_updates_weights_and_cooldown(state):
    code, out = product_api.try_handle("GET", "/api/recs/today", {"user": USER}, state)
    first = out["recs"][0]
    code, fb = product_api.try_handle("POST", "/api/recs/feedback", {"user": USER, "rec_id": first["id"], "action": "complete"}, state)
    assert code == 200 and fb["arm"]["alpha"] == 2.0 and fb["arm"]["beta"] == 1.0 and fb["rec"]["status"] == "completed"
    second = out["recs"][-1]
    code, fb = product_api.try_handle("POST", "/api/recs/feedback", {"user": USER, "rec_id": second["id"], "action": "ignore"}, state)
    assert code == 200 and fb["arm"]["beta"] == 2.0
    code, fb = product_api.try_handle("POST", "/api/recs/feedback", {"user": USER, "rec_id": second["id"], "action": "accept"}, state)
    assert fb["arm"]["alpha"] == 1.5
    stored = core_store.load(state, USER)
    assert stored["arms"][first["template_id"]]["alpha"] == 2.0 and len(stored["feedback"]) == 3
    # cooldown: the ignored + completed templates are not offered again for that day on refresh
    code, again = product_api.try_handle("GET", "/api/recs/today", {"user": USER, "refresh": "1"}, state)
    ids = {r["template_id"] for r in again["recs"]}
    assert first["template_id"] not in ids and second["template_id"] not in ids
    code, bad = product_api.try_handle("POST", "/api/recs/feedback", {"user": USER, "rec_id": first["id"], "action": "love"}, state)
    assert code == 400
    code, bad = product_api.try_handle("POST", "/api/recs/feedback", {"user": USER, "rec_id": "rec-x", "action": "accept"}, state)
    assert code == 404
    code, _ = product_api.try_handle("GET", "/api/recs/feedback", {"user": USER}, state)
    assert code == 405


def test_thompson_sampling_learns_from_ignores(doc):
    d = json.loads(json.dumps(doc))
    day = _days(d)[-1]
    base = recs.build_today(d, day, refresh=True)
    top = base["recs"][0]["template_id"]
    d["arms"][top] = {"alpha": 1.0, "beta": 40.0}  # ignored many times on earlier days
    after = recs.build_today(d, day, refresh=True)
    assert after["recs"][0]["template_id"] != top


def test_token_auth_and_bad_day(state):
    code, out = product_api.try_handle("GET", "/api/lifebook/today", {"token": "not-a-token"}, state)
    assert code == 401
    code, out = product_api.try_handle("GET", "/api/lifebook/today", {"user": USER, "day": "yesterday"}, state)
    assert code == 400


def test_empty_user_is_safe(tmp_path):
    code, out = product_api.try_handle("GET", "/api/timeline", {"user": "nobody"}, tmp_path)
    assert code == 200 and out["days"] == []
    code, out = product_api.try_handle("GET", "/api/recs/today", {"user": "nobody"}, tmp_path)
    assert code == 200 and out["recs"] == []
    assert not (tmp_path / "core" / "nobody.json").exists()


def test_demo_user_autoseeds(tmp_path):
    code, out = product_api.try_handle("GET", "/api/lifebook/today", {"user": USER}, tmp_path)
    assert code == 200 and out["synthetic"] and len(out["categories"]) == 13
    assert (tmp_path / "core" / f"{USER}.json").is_file()


def test_local_server_parses_query_string(state, monkeypatch):
    monkeypatch.setenv("PODCODER_STATE_DIR", str(state))
    spec = importlib.util.spec_from_file_location("local_server_core_test", ROOT.parent / "local" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    httpd = mod.make_server(0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/timeline?user={USER}&days=5&details=1", timeout=5) as r:
            out = json.loads(r.read())
        assert len(out["days"]) == 5 and "score" in out["days"][0]["lifebook"]["career"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/lifebook/today?user={USER}", timeout=5) as r:
            out = json.loads(r.read())
        assert "score" not in set(_walk_keys(out))
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---------- SQL file ----------

def test_sql_file_targets_podcoder_project_with_rls():
    sql = (ROOT / "sql" / "002_simco_core.sql").read_text()
    assert "wxvjajecvklfjxppawdx" in sql
    # the forbidden ref appears only in the "never apply" warning line
    assert [l for l in sql.splitlines() if "nexkymqahpkvzzlvivfi" in l] == ["-- NEVER apply to nexkymqahpkvzzlvivfi."]
    tables = re.findall(r"create table if not exists public\.(\w+)", sql)
    assert len(tables) >= 10
    for t in tables:
        assert f"'{t}'" in sql, f"{t} missing from RLS loop"
    assert "enable row level security" in sql and "(select auth.uid()) = user_id" in sql and "to authenticated" in sql
    assert "security_invoker = true" in sql and "set search_path = ''" in sql
    assert "rank between 1 and 3" in sql


def test_core_code_never_names_forbidden_project_outside_guards():
    for path in [ROOT / "core_api.py", ROOT / "core_store.py", *(ROOT / "scoring").glob("*.py"),
                 *(ROOT / "recs").glob("*.py"), *(ROOT / "analytics").glob("*.py"), *(ROOT / "seed").glob("*.py")]:
        assert "nexkymqahpkvzzlvivfi" not in path.read_text(), path
