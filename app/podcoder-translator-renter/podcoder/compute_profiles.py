#!/usr/bin/env python3
"""PODCODER_COMPUTE=local|cloud. One translator, two quants."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILES = ROOT / "profiles"
LOCAL_ID = "local_aspire_ryzen7000"
CLOUD_ID = "cloud_3090"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def profile_for(compute: str, ram_gb: float | None = None) -> dict:
    name = (compute or "").strip().lower()
    if name not in {"local", "cloud"}:
        raise ValueError("PODCODER_COMPUTE must be local or cloud")
    if name == "local":
        if ram_gb is None:
            import hardware_probe
            ram_gb = hardware_probe.detect()["ram_gb"]
        import hardware_probe
        profile_id = "local_ram32_q5" if float(ram_gb) >= hardware_probe.CODING_Q5_RAM_GB else LOCAL_ID
        path = PROFILES / f"{profile_id}.json"
    else:
        path = PROFILES / f"{CLOUD_ID}.json"
    doc = _read(path)
    override = (os.environ.get("PODCODER_MODEL") or "").strip()
    if override:
        doc = dict(doc)
        doc["model"] = override
        doc["model_override"] = True
    return doc


def active_compute() -> str:
    raw = (os.environ.get("PODCODER_COMPUTE") or "cloud").strip().lower()
    return raw if raw in {"local", "cloud"} else "cloud"


def load_saved(state: Path) -> dict | None:
    path = state / "compute.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def current(state: Path) -> dict:
    saved = load_saved(state) or {}
    compute = (saved.get("compute") or active_compute())
    if compute not in {"local", "cloud"}:
        compute = "cloud"
    doc = profile_for(compute)
    stale_q4 = (
        compute == "local"
        and saved.get("model") == "granite4.2:8b"
        and doc.get("model") == "granite4.2:8b-q5_0"
    )
    if saved.get("model") and not stale_q4:
        doc = dict(doc)
        doc["model"] = saved["model"]
        if saved.get("profile"):
            doc["id"] = saved["profile"]
    doc["compute"] = compute
    doc["profile"] = saved.get("profile") or doc.get("id")
    doc["vast_calls"] = 0
    return doc


def save(state: Path, compute: str, model: str | None = None) -> dict:
    ram = None
    if (compute or "").strip().lower() == "local" and not model:
        import hardware_probe
        ram = hardware_probe.detect()["ram_gb"]
    doc = profile_for(compute, ram_gb=ram)
    if model:
        doc = dict(doc)
        doc["model"] = model.strip()
        if doc.get("compute") == "local":
            doc["id"] = "local_ram32_q5" if "q5" in doc["model"] else LOCAL_ID
            doc["quant"] = "Q5" if "q5" in doc["model"] else "Q4"
    state.mkdir(parents=True, exist_ok=True)
    payload = {"compute": doc["compute"], "model": doc["model"], "profile": doc["id"]}
    (state / "compute.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return current(state)


def local_smoke_path(state: Path) -> Path:
    return state / "local-smoke.json"


def local_ready(state: Path) -> bool:
    path = local_smoke_path(state)
    if not path.is_file():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return doc.get("status") == "pass" and doc.get("model") == current(state).get("model")
