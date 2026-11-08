#!/usr/bin/env python3
"""Heartbeat watchdog. Restarts are recorded. This module does not kill processes."""
from __future__ import annotations

import time
from pathlib import Path


def _dir(state: Path) -> Path:
    path = state / "health"
    path.mkdir(parents=True, exist_ok=True)
    return path


def beat(state: Path, now: float | None = None) -> dict:
    moment = time.time() if now is None else now
    _dir(state).joinpath("heartbeat").write_text(str(moment), encoding="utf-8")
    return {"ok": True, "at": moment, "vast_calls": 0, "destroyed": False}


def check(state: Path, now: float | None = None, stale_after: float = 30) -> dict:
    moment = time.time() if now is None else now
    path = state / "health" / "heartbeat"
    last = None
    if path.is_file():
        try:
            last = float(path.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            last = None
    stale = last is None or moment - last > stale_after
    restart = []
    if stale:
        restart = ["podcoder", "ollama"]
        log = _dir(state) / "restarts.log"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{moment} restart {' '.join(restart)}\n")
    return {
        "ok": True,
        "stale": stale,
        "restart": restart,
        "service": "local",
        "vast_calls": 0,
        "destroyed": False,
    }


def snapshot(state: Path) -> dict:
    path = state / "health" / "heartbeat"
    stale = not path.is_file()
    if path.is_file():
        try:
            stale = time.time() - float(path.read_text(encoding="utf-8").strip() or "0") > 30
        except Exception:
            stale = True
    return {"watchdog": "restart" if stale else "ok", "vast_calls": 0}
