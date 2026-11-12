#!/usr/bin/env python3
"""Minimum analytics the recommendations need. Stdlib only, offline.

For each hypothesis pair (predictor -> outcome) and lag 0..3 days we compute
Spearman's rho between predictor(t - lag) and outcome(t) on detrended series,
with gates and Benjamini-Hochberg FDR across every test that ran.

Gates (brief A2; thresholds are a heuristic, not a sourced rule):
  * missing-data gate: skip a test when fewer than MIN_PAIRS paired days exist,
    or when more than MAX_MISSING_SHARE of the window is missing for either series
  * n >= 14 paired days to run at all ("insufficient data" otherwise)
  * "finding" needs n >= 21, |rho| >= 0.3, BH q < 0.10 and a CI that excludes 0
  * anything that runs but misses those is an "early signal" or "no signal"
Every result carries CAVEAT: correlation, not causation.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

CAVEAT = "Correlation, not causation: these are patterns in your own logs, not proof that one thing causes another."
LAGS = (0, 1, 2, 3)
MIN_PAIRS = 14
FINDING_PAIRS = 21
MIN_RHO = 0.3
MAX_Q = 0.10
MAX_MISSING_SHARE = 0.4

# Hypotheses worth testing (keeps the FDR family small and meaningful).
PAIRS = [
    ("sleep_hours", "mood"),
    ("sleep_hours", "focus"),
    ("exercise_min", "sleep_quality"),
    ("exercise_min", "mood"),
    ("steps", "mood"),
    ("steps", "focus"),
    ("spending", "stress"),
    ("stress", "sleep_quality"),
]

METRIC_CATEGORIES = {
    "sleep_hours": ["health_fitness"], "sleep_quality": ["health_fitness", "quality_of_life"],
    "steps": ["health_fitness"], "exercise_min": ["health_fitness"],
    "mood": ["emotional_life"], "focus": ["career", "intellectual_life"],
    "stress": ["emotional_life", "quality_of_life"], "spending": ["financial_life"],
}


# ---------- small stats helpers ----------

def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(ranks(x), ranks(y))


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > 1e-30 else 1e-30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > 1e-30 else 1e-30
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    front = math.exp(lbeta)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def p_value(rho: float, n: int) -> float:
    """Two-sided p for a correlation via the t approximation with n-2 df."""
    if n < 4:
        return 1.0
    rho = max(-0.999999, min(0.999999, rho))
    df = n - 2
    t = rho * math.sqrt(df / (1 - rho * rho))
    return max(0.0, min(1.0, betainc(df / 2, 0.5, df / (df + t * t))))


def fisher_ci(rho: float, n: int, z_crit: float = 1.959964) -> tuple[float, float]:
    """95% CI for Spearman via Fisher z with the Fieller et al. SE 1.06/sqrt(n-3)."""
    if n < 5:
        return (-1.0, 1.0)
    rho = max(-0.999999, min(0.999999, rho))
    z = math.atanh(rho)
    se = 1.06 / math.sqrt(n - 3)
    return (math.tanh(z - z_crit * se), math.tanh(z + z_crit * se))


def bh_fdr(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted q-values, same order as input."""
    m = len(pvalues)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = min(1.0, running)
    return q


# ---------- series prep ----------

def detrend(series: dict[str, float], days: list[str]) -> dict[str, float]:
    """Remove a linear trend and the day-of-week mean (light prewhitening)."""
    pts = [(i, series[d]) for i, d in enumerate(days) if d in series]
    if len(pts) < 3:
        return dict(series)
    n = len(pts)
    mx = sum(i for i, _ in pts) / n
    my = sum(v for _, v in pts) / n
    sxx = sum((i - mx) ** 2 for i, _ in pts) or 1.0
    slope = sum((i - mx) * (v - my) for i, v in pts) / sxx
    resid = {days[i]: v - (my + slope * (i - mx)) for i, v in pts}
    by_dow: dict[int, list[float]] = {}
    for d, v in resid.items():
        by_dow.setdefault(date.fromisoformat(d).weekday(), []).append(v)
    dow_mean = {k: sum(v) / len(v) for k, v in by_dow.items() if len(v) >= 3}
    return {d: v - dow_mean.get(date.fromisoformat(d).weekday(), 0.0) for d, v in resid.items()}


def _shift(day: str, lag: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=lag)).isoformat()


def lagged_pairs(xs: dict[str, float], ys: dict[str, float], lag: int, days: list[str]) -> tuple[list[float], list[float], list[str]]:
    x, y, used = [], [], []
    for d in days:
        src = _shift(d, lag)
        if d in ys and src in xs:
            x.append(xs[src])
            y.append(ys[d])
            used.append(d)
    return x, y, used


# ---------- main entry ----------

def analyze(series: dict[str, dict[str, float]], days: list[str], pairs=PAIRS, lags=LAGS, until: str | None = None) -> dict:
    """series: metric_key -> {day: value}. days: full ordered calendar. Returns tests + findings."""
    if until:
        days = [d for d in days if d <= until]
    window = len(days)
    tests, skipped = [], []
    prepared = {k: detrend({d: v for d, v in s.items() if d in set(days)}, days) for k, s in series.items()}
    for predictor, outcome in pairs:
        xs, ys = prepared.get(predictor, {}), prepared.get(outcome, {})
        miss_x = 1 - len(xs) / window if window else 1
        miss_y = 1 - len(ys) / window if window else 1
        for lag in lags:
            x, y, used = lagged_pairs(xs, ys, lag, days)
            base = {"predictor": predictor, "outcome": outcome, "lag": lag, "n": len(x)}
            if max(miss_x, miss_y) > MAX_MISSING_SHARE:
                skipped.append({**base, "reason": "missing-data gate", "missing_share": round(max(miss_x, miss_y), 2)})
                continue
            if len(x) < MIN_PAIRS:
                skipped.append({**base, "reason": f"fewer than {MIN_PAIRS} paired days"})
                continue
            rho = spearman(x, y)
            lo, hi = fisher_ci(rho, len(x))
            tests.append({**base, "rho": round(rho, 3), "p": p_value(rho, len(x)), "ci95": [round(lo, 3), round(hi, 3)],
                          "first_day": used[0], "last_day": used[-1]})
    qs = bh_fdr([t["p"] for t in tests])
    for t, q in zip(tests, qs):
        t["q"] = round(q, 4)
        t["p"] = round(t["p"], 4)
        excludes_zero = t["ci95"][0] > 0 or t["ci95"][1] < 0
        if t["n"] >= FINDING_PAIRS and abs(t["rho"]) >= MIN_RHO and q < MAX_Q and excludes_zero:
            t["strength"] = "finding"
        elif abs(t["rho"]) >= MIN_RHO and t["p"] < 0.05:
            t["strength"] = "early signal"
        else:
            t["strength"] = "no signal"
        t["id"] = f"f-{t['predictor']}-{t['outcome']}-lag{t['lag']}"
        t["statement"] = describe(t)
        t["categories"] = sorted(set(METRIC_CATEGORIES.get(t["predictor"], []) + METRIC_CATEGORIES.get(t["outcome"], [])))
    findings = [t for t in tests if t["strength"] == "finding"]
    findings = _best_lag_only(findings)
    early = _best_lag_only([t for t in tests if t["strength"] == "early signal"])
    return {
        "method": "spearman on detrended series, lags 0-3 days, BH-FDR across all tests",
        "gates": {"min_pairs": MIN_PAIRS, "finding_pairs": FINDING_PAIRS, "min_rho": MIN_RHO, "max_q": MAX_Q,
                  "max_missing_share": MAX_MISSING_SHARE},
        "window_days": window, "tests_run": len(tests), "tests": tests, "skipped": skipped,
        "findings": findings, "early_signals": early, "caveat": CAVEAT,
    }


def _best_lag_only(rows: list[dict]) -> list[dict]:
    best: dict[tuple, dict] = {}
    for row in rows:
        key = (row["predictor"], row["outcome"])
        if key not in best or row["q"] < best[key]["q"]:
            best[key] = row
    return sorted(best.values(), key=lambda r: r["q"])


LABELS = {"sleep_hours": "sleep", "sleep_quality": "sleep quality", "steps": "steps", "exercise_min": "exercise",
          "mood": "mood", "focus": "focus", "stress": "stress", "spending": "spending"}


def describe(t: dict) -> str:
    direction = "higher" if t["rho"] > 0 else "lower"
    when = {0: "the same day", 1: "the next day", 2: "two days later", 3: "three days later"}[t["lag"]]
    hedge = "tends to go with" if t.get("strength") == "finding" else "may go with"
    return (f"More {LABELS.get(t['predictor'], t['predictor'])} {hedge} {direction} "
            f"{LABELS.get(t['outcome'], t['outcome'])} {when} ({t['n']} days). {CAVEAT.split(':')[0]}.")
