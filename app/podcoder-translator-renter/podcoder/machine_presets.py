#!/usr/bin/env python3
"""Named machine presets (one rentable box setup each). Picking one never rents.

Each preset lives in presets/<id>/preset.json beside its install, launch, job, and
auto-destroy controller scripts. A preset maps onto an existing rent role (for
example "video"), so Confirm Rent, the role split, and the 24GB Granite/Wan rule
all still apply. No Vast calls happen here.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRESETS = ROOT / "presets"


def _load(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["dir"] = str(path.parent.relative_to(ROOT))
    return doc


def all_presets() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if PRESETS.is_dir():
        for path in sorted(PRESETS.glob("*/preset.json")):
            doc = _load(path)
            out[doc["id"]] = doc
    return out


def get(preset_id: str | None) -> dict | None:
    key = (preset_id or "").strip()
    if not key:
        return None
    found = all_presets().get(key)
    if found is None:
        raise ValueError(f"unknown machine preset {key}")
    return found


def offer_check(preset: dict, body: dict) -> tuple[bool, str]:
    """Check a rent body (gpu, inet_down, price_hr, region) against the preset filters."""
    f = preset.get("offer_filter") or {}
    gpu = str(body.get("gpu") or body.get("gpu_name") or "")
    if f.get("gpu_names") and gpu not in f["gpu_names"]:
        return False, f"{preset['name']} needs {', '.join(f['gpu_names'])}, not {gpu or 'an unknown GPU'}"
    try:
        down = float(body.get("inet_down") or 0)
    except (TypeError, ValueError):
        down = 0.0
    if down < float(f.get("min_inet_down_mbps") or 0):
        return False, f"{preset['name']} needs inet_down of at least {f['min_inet_down_mbps']} Mbps"
    try:
        price = float(body.get("price_hr") or body.get("dph_total") or 0)
    except (TypeError, ValueError):
        price = 0.0
    if price and f.get("max_dph_usd") and price > float(f["max_dph_usd"]):
        return False, f"{preset['name']} caps price at ${float(f['max_dph_usd']):.2f}/hr"
    region = str(body.get("region") or body.get("geolocation") or "")
    country = f.get("country")
    if region and country and not (region == country or region.endswith(", " + country)):
        return False, f"{preset['name']} needs a {country} host"
    return True, ""


def public(preset: dict) -> dict:
    keep = ("id", "name", "role", "provider", "offer_filter", "image", "disk_gb", "model", "render",
            "timing_estimates", "budget", "scripts", "destroy_after_last_job", "requires_confirm", "vram",
            "separate_from", "dir")
    return {k: preset[k] for k in keep if k in preset}


def describe() -> dict:
    return {
        "ok": True,
        "presets": [public(p) for p in all_presets().values()],
        "picking_rents": False,
        "needs": "Confirm Rent",
        "vast_calls": 0,
    }
