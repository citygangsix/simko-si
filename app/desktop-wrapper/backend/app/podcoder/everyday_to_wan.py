#!/usr/bin/env python3
"""Everyday English -> Wan/Comfy A1 prompt. Heuristic. No extra model. No Granite load."""
from __future__ import annotations

import argparse
import json
import sys

WAN_MODEL = "wan2.2-5b"


def translate(text: str) -> dict:
    everyday = (text or "").strip()
    if not everyday:
        return {"ok": False, "error": "empty", "everyday": "", "a1": None, "model": WAN_MODEL}
    return {
        "ok": True,
        "error": "",
        "everyday": everyday,
        "model": WAN_MODEL,
        "vram": "24GB-safe 5B. Do not load Granite in VRAM at the same time.",
        "a1": {
            "subject": everyday,
            "motion": "natural continuous motion of the subject",
            "camera": "stable medium shot",
            "duration_s": 5,
            "checkpoint": "Wan2.2-TI2V-5B",
            "negative": "blur, watermark, flicker, extra limbs, granite model, text overlay",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Everyday English to a Wan 2.2 5B A1 prompt.")
    parser.add_argument("--text", default="")
    args = parser.parse_args(argv)
    result = translate(args.text)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
