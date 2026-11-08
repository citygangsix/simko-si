#!/usr/bin/env python3
"""Scrape jobs. Simple mode uses httpx and BeautifulSoup when installed. Browser mode stays stubbed offline."""
from __future__ import annotations

import csv
import time
from pathlib import Path

import offline_sync

AGENT = "podcoder"


def parse_html(html: str) -> dict:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html or "", "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        text = soup.get_text(" ", strip=True)
        return {"title": title, "text": text, "parser": "bs4"}
    except Exception:
        title = ""
        if "<title>" in (html or "").lower():
            start = html.lower().find("<title>") + 7
            end = html.lower().find("</title>", start)
            title = html[start:end].strip()
        return {"title": title, "text": html or "", "parser": "html.parser"}


def robots_allows(robots_txt: str, path: str, agent: str = AGENT) -> bool:
    lines = [line.strip() for line in (robots_txt or "").splitlines()]
    groups: list[tuple[list[str], list[str]]] = []
    agents: list[str] = []
    rules: list[str] = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key == "disallow":
            rules.append(value)
    if agents or rules:
        groups.append((agents, rules))
    chosen: list[str] = []
    for names, rules in groups:
        if agent.lower() in names or "*" in names:
            chosen = rules
            if agent.lower() in names:
                break
    target = path or "/"
    for rule in chosen:
        if rule and target.startswith(rule):
            return False
    return True


def _rate_ok(state: Path, interval: float) -> bool:
    path = state / "scrape-rate.json"
    now = time.time()
    last = 0.0
    if path.is_file():
        try:
            last = float(path.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            last = 0.0
    if interval and now - last < interval:
        return False
    path.write_text(str(now), encoding="utf-8")
    return True


def _fetch(url: str, fetch_fn=None) -> str:
    if fetch_fn:
        return fetch_fn(url)
    if url.startswith("file:"):
        return Path(url[7:]).read_text(encoding="utf-8")
    try:
        import httpx
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def extract_fields(text: str, fields: list[str]) -> dict:
    found = {}
    hay = text or ""
    lower = hay.lower()
    for field in fields:
        label = str(field)
        marker = label.lower() + ":"
        value = ""
        index = lower.find(marker)
        if index >= 0:
            value = hay[index + len(marker):].strip().split()
            value = value[0].split("<", 1)[0] if value else ""
        found[label] = value
    return {"ok": True, "fields": found, "qualitative": True, "vast_calls": 0, "destroyed": False}


def _write_csv(state: Path, job_id: str, rows: list[dict]) -> str:
    folder = state / "scrapes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{job_id}.csv"
    keys = sorted({key for row in rows for key in row}) or ["text"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    if not offline_sync.refused_project():
        offline_sync.note(state, "podcoder_scrape_rows", {"job_id": job_id, "rows": len(rows)})
    return str(path.relative_to(state))


def browser(html: str, actions: list[dict], secret: str = "") -> dict:
    applied = []
    for action in actions or []:
        op = (action.get("op") or "").strip().lower()
        if op not in {"click", "scroll", "fill", "screenshot"}:
            continue
        applied.append(op)
        if op == "fill" and action.get("use_vault"):
            applied.append("vault-fill" if secret else "vault-missing")
    shot = ""
    if "screenshot" in applied:
        shot = "scrapes/browser-shot.bin"
    return {
        "ok": True,
        "mode": "browser",
        "engine": "stub",
        "actions": applied,
        "screenshot": shot,
        "network": False,
        "vast_calls": 0,
        "destroyed": False,
    }


def run(state: Path, job_id: str, payload: dict, fetch_fn=None) -> dict:
    interval = float(payload.get("min_interval") if payload.get("min_interval") is not None else 1)
    if not _rate_ok(state, interval):
        return {"ok": False, "error": "rate limited"}
    robots = payload.get("robots")
    path = str(payload.get("path") or "/")
    if payload.get("robots_aware", True) and robots is not None and not robots_allows(str(robots), path):
        return {"ok": False, "error": "robots disallow", "fetched": False}
    mode = (payload.get("mode") or "simple").strip().lower()
    html = str(payload.get("html") or "")
    if not html and payload.get("url"):
        tries = int(payload.get("retries") or 1)
        last = ""
        for _ in range(max(1, tries)):
            try:
                html = _fetch(str(payload["url"]), fetch_fn)
                break
            except Exception as exc:
                last = str(exc)
                html = ""
        if not html:
            return {"ok": False, "error": last or "fetch failed"}
    parsed = parse_html(html)
    if mode == "browser":
        secret = ""
        if payload.get("login"):
            import vault
            opened = vault.reveal_named(state, str(payload.get("user") or ""), str(payload.get("passphrase") or ""), str(payload.get("login")))
            secret = str((opened.get("value") or "")) if opened.get("ok") else ""
        viewed = browser(html, payload.get("actions") or [], secret)
        viewed["title"] = parsed["title"]
        viewed["csv"] = _write_csv(state, job_id, [{"title": parsed["title"], "text": parsed["text"][:500]}])
        if "value" in viewed:
            viewed.pop("value")
        if secret and secret in str(viewed):
            viewed = {key: value for key, value in viewed.items() if secret not in str(value)}
        return viewed
    fields = extract_fields(parsed["text"], list(payload.get("fields") or []))
    csv_path = _write_csv(state, job_id, [{"title": parsed["title"], "text": parsed["text"][:500], **fields["fields"]}])
    return {
        "ok": True,
        "mode": "simple",
        "parser": parsed["parser"],
        "title": parsed["title"],
        "text": parsed["text"][:2000],
        "fields": fields["fields"],
        "csv": csv_path,
        "vast_calls": 0,
        "destroyed": False,
    }
