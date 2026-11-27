#!/usr/bin/env python3
"""Template charts. Data plus a template. No prompting loop and no image model."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import lifebook_memory

TEMPLATES = {"ringMetrics", "lineChart", "barChart", "goalRing", "scorePlaque", "progressStats", "quoteCard"}
FORMATS = {"percent", "currency", "count", "number", "level", "tag"}
LEVELS = ["Low", "Medium", "High"]
TAGS = ["Quiet", "Emerging", "Dominant"]
RING_R = 46


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _qual_steps(fmt: str, word: str) -> int:
    scale = LEVELS if fmt == "level" else TAGS
    if word not in scale:
        raise ValueError(f"{fmt} must be one of {', '.join(scale)}")
    return scale.index(word) + 1


def _percent(value) -> float:
    number = float(value)
    if number < 0 or number > 100:
        raise ValueError("percent values stay between 0 and 100")
    return number


def _check_value(fmt: str, value) -> None:
    if fmt == "percent":
        _percent(value)
    elif fmt in {"level", "tag"}:
        _qual_steps(fmt, str(value))
    elif fmt in {"currency", "count", "number"}:
        float(value)
    else:
        raise ValueError("unknown format")


def _walk_values(fmt: str, data: dict) -> list:
    values = []
    for key in ("value", "score", "progress", "headline", "goal"):
        if key in data and not isinstance(data[key], (dict, list)):
            if fmt in {"level", "tag"} or isinstance(data[key], (int, float)) or key in {"headline", "goal", "score", "progress", "value"}:
                if fmt in {"level", "tag"} and isinstance(data[key], str):
                    values.append(data[key])
                elif fmt == "percent" and isinstance(data[key], (int, float)):
                    values.append(data[key])
    ring = data.get("ring") or {}
    if "value" in ring:
        values.append(ring["value"])
    for row in data.get("rows") or []:
        if "value" in row:
            values.append(row["value"])
    for item in data.get("series") or []:
        values.append(item)
    for item in data.get("side") or []:
        if "value" in item:
            values.append(item["value"])
    for item in data.get("tiles") or []:
        if "value" in item:
            values.append(item["value"])
    for item in data.get("stats") or []:
        if "value" in item:
            values.append(item["value"])
    return values


def validate(template: str, data: dict) -> dict:
    if template not in TEMPLATES:
        return {"ok": False, "error": "unknown template", "vast_calls": 0, "destroyed": False}
    body = dict(data or {})
    source = str(body.get("source") or "")
    if template == "quoteCard":
        if not str(body.get("quote") or "").strip():
            return {"ok": False, "error": "quote required", "vast_calls": 0, "destroyed": False}
        config = {"template": template, "quote": str(body["quote"]), "tag": str(body.get("tag") or ""), "source": source}
        return {"ok": True, "config": config, "vast_calls": 0, "destroyed": False}
    fmt = str(body.get("format") or "")
    if fmt not in FORMATS:
        return {"ok": False, "error": "format must be percent, currency, count, number, level, or tag", "vast_calls": 0, "destroyed": False}
    if source == "lifebook" and fmt == "percent":
        return {"ok": False, "error": "lifebook charts use level or tag, never percents", "vast_calls": 0, "destroyed": False}
    try:
        for value in _walk_values(fmt, body):
            item_fmt = fmt
            if isinstance(value, str) and fmt not in {"level", "tag"}:
                continue
            _check_value(item_fmt, value)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "vast_calls": 0, "destroyed": False}
    config = dict(body)
    config["template"] = template
    config["format"] = fmt
    return {"ok": True, "config": config, "vast_calls": 0, "destroyed": False}


def _ring(fmt: str, value) -> str:
    circ = 2 * math.pi * RING_R
    if fmt in {"level", "tag"}:
        steps = _qual_steps(fmt, str(value))
        return f'<g data-format="{fmt}" data-steps="{steps}" data-word="{_esc(value)}"/>'
    pct = _percent(value)
    length = circ * (pct / 100.0)
    return f'<circle data-format="percent" data-pct="{int(pct)}" stroke-dasharray="{length:.2f} {circ:.2f}"/>'


def render_svg(template: str, data: dict) -> str:
    checked = validate(template, data)
    if not checked.get("ok"):
        raise ValueError(checked.get("error") or "invalid chart")
    config = checked["config"]
    if template == "quoteCard":
        return f'<svg xmlns="http://www.w3.org/2000/svg" data-template="quoteCard"><text>{_esc(config["quote"])}</text></svg>'
    fmt = config["format"]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" data-template="{template}" data-format="{fmt}">']
    if template == "ringMetrics":
        parts.append(_ring(fmt, (config.get("ring") or {}).get("value", 0)))
        for row in config.get("rows") or []:
            if fmt == "percent":
                parts.append(f'<rect data-pct="{int(_percent(row["value"]))}" data-width="{_percent(row["value"]):.2f}"/>')
            elif fmt in {"level", "tag"}:
                parts.append(f'<g data-steps="{_qual_steps(fmt, str(row["value"]))}" data-word="{_esc(row["value"])}"/>')
    elif template in {"goalRing", "progressStats", "scorePlaque"}:
        key = "score" if template == "scorePlaque" else "progress" if template == "goalRing" else "value"
        parts.append(_ring(fmt, config.get(key, 0)))
    elif template in {"lineChart", "barChart"}:
        for item in config.get("series") or []:
            if fmt == "percent":
                parts.append(f'<rect data-pct="{int(_percent(item))}" data-width="{_percent(item):.2f}"/>')
            elif fmt in {"level", "tag"}:
                parts.append(f'<g data-steps="{_qual_steps(fmt, str(item))}" data-word="{_esc(item)}"/>')
            else:
                parts.append(f'<rect data-value="{_esc(item)}"/>')
    parts.append("</svg>")
    return "".join(parts)


def from_lifebook(state: Path, user: str) -> dict:
    listed = lifebook_memory.list_memory(state, user)
    rows = []
    for row in listed.get("categories") or []:
        word = (listed.get("statuses") or {}).get(row["id"]) or "not discussed"
        tag = {"not discussed": "Quiet", "in play": "Emerging", "doing well": "Dominant", "strained": "Quiet"}.get(word, "Quiet")
        rows.append({"label": row["label"], "value": tag})
    return {"source": "lifebook", "format": "tag", "ring": {"value": rows[0]["value"] if rows else "Quiet", "word": "status"}, "rows": rows}


def from_crm() -> dict:
    import connectors
    rows = connectors.crm_rows()
    return {"source": "crm", "format": "count", "series": [row["value"] for row in rows], "labels": [row["label"] for row in rows]}


def build(template: str, data: dict) -> dict:
    checked = validate(template, data)
    if not checked.get("ok"):
        return checked
    svg = render_svg(template, checked["config"])
    checked["svg"] = svg
    return checked


def run(state: Path, job_id: str, payload: dict) -> dict:
    source = str(payload.get("source") or "")
    template = str(payload.get("template") or "barChart")
    if source == "lifebook":
        data = from_lifebook(state, str(payload.get("user") or "default"))
        data["template"] = template if template != "barChart" else "ringMetrics"
        template = data.pop("template")
    elif source == "crm":
        data = from_crm()
    else:
        data = dict(payload.get("data") or {})
    drawn = build(template, data)
    if not drawn.get("ok"):
        return drawn
    folder = state / "charts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{job_id}.svg"
    path.write_text(drawn["svg"], encoding="utf-8")
    return {"ok": True, "config": drawn["config"], "svg_path": str(path.relative_to(state)), "vast_calls": 0, "destroyed": False}
