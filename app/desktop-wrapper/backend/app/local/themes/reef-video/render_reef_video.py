#!/usr/bin/env python3
"""Prepared Reef Video plan. This file does not render, download, or rent."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG = Path(__file__).with_name("render-config.json")


def main() -> int:
    plan = json.loads(CONFIG.read_text(encoding="utf-8"))
    confirmed = os.environ.get("SIMCO_CONFIRM") == "RENT"
    print(json.dumps({
        "ok": True,
        "rendered": False,
        "confirmed": confirmed,
        "reason": "Reef Video is prepared only. This build does not run Wan, SeedVR2, or Real-ESRGAN.",
        "plan": plan,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
