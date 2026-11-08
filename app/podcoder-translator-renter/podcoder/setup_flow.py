#!/usr/bin/env python3
"""First-run setup. Detect the host, plan Granite + Ollama + Aider, lock the translator.

Downloads stay dry unless the caller passes live=True and PODCODER_SETUP_LIVE=1.
Nothing here rents, calls Vast, or pulls weights by itself.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import hardware_probe
import translation_profiles

LOCK_NAME = "setup-lock.json"


def _read(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def lock_path(state: Path) -> Path:
    return state / LOCK_NAME


def current(state: Path) -> dict | None:
    return _read(lock_path(state))


def unlocked(state: Path) -> bool:
    doc = current(state) or {}
    return bool(doc.get("chat_unlocked") and doc.get("profile_id"))


def _grok_ready() -> bool:
    try:
        import llm_router

        return llm_router.key_present()
    except Exception:
        return False


GROK_MESSAGE = "Grok powers chat and coding on this computer. Granite, Ollama and GPU rental are optional."


def status(state: Path) -> dict:
    raw = current(state) or {}
    doc = hardware_probe.strip_retired_ada(raw) if raw else {}
    if raw and doc != raw:
        _write(state, doc)
    return {
        "ok": True,
        "phase": doc.get("phase") or "idle",
        "chat_unlocked": bool(doc.get("chat_unlocked")) or _grok_ready(),
        "brain": "grok" if _grok_ready() else "granite",
        "profile_id": doc.get("profile_id") or "",
        "model": doc.get("model") or "",
        "aider": doc.get("aider") or {},
        "ollama": doc.get("ollama") or {},
        "dry_run": bool(doc.get("dry_run", True)),
        "vast_calls": 0,
        "destroyed": False,
        "message": doc.get("message") or "Simco SI has not configured this computer yet.",
    }


def _live_requested(body: dict) -> bool:
    if not body.get("live"):
        return False
    return os.environ.get("PODCODER_SETUP_LIVE") == "1"


def _write(state: Path, doc: dict) -> None:
    state.mkdir(parents=True, exist_ok=True)
    lock_path(state).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _installed_tags(after_install: bool) -> list[str]:
    """Model names from Ollama /api/tags. Only after a real (or live-test) install; 2 s limit; [] on any problem."""
    if not after_install and os.environ.get("PODCODER_SIMCO_LIVE_OLLAMA") != "1":
        return []
    import urllib.request

    root = (os.environ.get("OLLAMA_API_BASE") or "http://127.0.0.1:11434").strip().rstrip("/")
    try:
        with urllib.request.urlopen(root + "/api/tags", timeout=2) as response:
            doc = json.loads(response.read().decode("utf-8") or "{}")
    except Exception:
        return []
    return translation_profiles._names_from_tags(doc if isinstance(doc, dict) else {})


def pick_installed(planned: str, installed: list[str]) -> str:
    """The planned tag when it is installed, else the closest installed Granite 4.2 tag, else planned."""
    names = [n for n in installed or [] if n]
    if not names or planned in names:
        return planned
    granite = [n for n in names if n.startswith("granite4.2")] or [n for n in names if "granite" in n]
    if not granite:
        return planned
    base = planned.split("-")[0] if planned else "granite4.2:8b"
    # Never step up to a bigger quant than planned before trying the smaller ones.
    order = (base + "-q8_0", base + "-q5_0", base) if "q8" in planned else (base + "-q5_0", base, base + "-q8_0")
    for want in (*order, "granite4.2:8b"):
        if want in granite:
            return want
    return granite[0]


def run(state: Path, body: dict | None = None, downloader=None) -> dict:
    body = body or {}
    role = str(body.get("role") or "coding").strip().lower() or "coding"
    raw_probe = body.get("probe") if isinstance(body.get("probe"), dict) else None
    probe = hardware_probe.normalize(raw_probe) if raw_probe else hardware_probe.detect()
    if body.get("platform"):
        probe = dict(probe)
        probe["platform"] = str(body.get("platform"))
    decision = hardware_probe.choose(role, probe, "local", platform=probe.get("platform"))
    hardware_probe.remember(state, probe, decision)
    show = body.get("ollama_show") if isinstance(body.get("ollama_show"), dict) else None
    tags = body.get("ollama_tags") if isinstance(body.get("ollama_tags"), dict) else None
    profile = translation_profiles.profile_from_ollama(tags=tags, show=show, detected=decision)
    plan = {
        "granite": decision.get("tag") or decision.get("model") or "",
        "quant": decision.get("quant") or "",
        "ollama": decision.get("ollama") or {},
        "aider": decision.get("aider") or {},
        "script": decision.get("script") or "",
        "vram_residents": decision.get("vram_residents") or [],
        "vram_simultaneous": False,
    }
    if not decision.get("ok") and _grok_ready():
        # Too small for local Granite is fine: Grok answers chat and writes code.
        doc = {
            "phase": "ready",
            "chat_unlocked": True,
            "brain": "grok",
            "profile_id": profile.get("id") or "",
            "model": "",
            "aider": plan["aider"],
            "ollama": plan["ollama"],
            "ready_check": {"ok": True, "note": "Grok is set up. Local Granite is optional and skipped here."},
            "dry_run": True,
            "vast_calls": 0,
            "destroyed": False,
            "message": GROK_MESSAGE + " (Local Granite skipped: " + (decision.get("message") or "this computer is too small") + ")",
            "probe": probe,
            "downloads": {**plan, "executed": False},
        }
        try:
            import llm_router

            doc["llm"] = llm_router.public_status()
        except Exception:
            pass
        doc = hardware_probe.strip_retired_ada(doc)
        decision = hardware_probe.strip_retired_ada(decision)
        _write(state, doc)
        return {"ok": True, "http": 200, **doc, "decision": decision, "profile": profile.get("id") or ""}
    if not decision.get("ok"):
        doc = {
            "phase": "blocked",
            "chat_unlocked": False,
            "profile_id": "",
            "model": "",
            "aider": plan["aider"],
            "ollama": plan["ollama"],
            "ready_check": {"ok": False, "note": "No ready check until this computer can hold Granite."},
            "dry_run": True,
            "vast_calls": 0,
            "destroyed": False,
            "message": decision.get("message") or "This computer is too small.",
            "probe": probe,
            "downloads": {**plan, "executed": False},
        }
        doc = hardware_probe.strip_retired_ada(doc)
        decision = hardware_probe.strip_retired_ada(decision)
        _write(state, doc)
        return {"ok": True, "http": 200, **doc, "decision": decision}

    live = _live_requested(body)
    if downloader is not None:
        report = downloader(plan)
        executed = True
        dry = False
    elif live:
        import install_hook

        report = install_hook.handle_download(
            {"compute": "local", "role": role, "probe": probe, "dry_run": False},
            state,
            src_dir=Path(__file__).resolve().parent,
            sync=True,
        )
        executed = True
        dry = False
    else:
        report = {"executed": False, "dry_run": True, "planned": plan}
        executed = False
        dry = True
        (state / "download-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    # Lock the Granite tag that is really installed (Ollama /api/tags), not the one the plan hoped for.
    # The 3090 run pulled only granite4.2:8b while the lock said q5.
    installed = translation_profiles._names_from_tags(tags) if tags else _installed_tags(live or downloader is not None)
    picked = pick_installed(decision.get("model") or "", installed)
    if picked and picked != (decision.get("model") or ""):
        decision = dict(decision)
        decision["planned_model"] = decision.get("model") or ""
        decision["model"] = picked
        decision["tag"] = picked
        profile = translation_profiles.profile_from_ollama(tags={"models": [{"name": n} for n in installed]}, show=show,
                                                           detected={"model": picked})
    if decision.get("model"):
        import compute_profiles

        compute_profiles.save(state, "local", decision["model"])

    aider = decision.get("aider") or {}
    tag = decision.get("tag") or decision.get("model") or ""
    ready = {
        "ok": True,
        "dry_run": dry,
        "ollama_api_base": "http://127.0.0.1:11434",
        "granite": tag,
        "aider_model": aider.get("model_flag") or "",
        "aider_version": aider.get("version") or "",
        "aider_method": aider.get("method") or "",
        "note": _ready_note(),
    }
    message = (
        f"Detected this computer ({probe.get('cpu') or 'CPU'}, {probe.get('ram_gb')} GB RAM, "
        f"{probe.get('gpu') or 'no NVIDIA GPU'}). "
        f"Plan: Ollama {((decision.get('ollama') or {}).get('method') or 'unspecified')} "
        f"{((decision.get('ollama') or {}).get('version') or '')}, "
        f"Granite {tag}, "
        f"Aider {aider.get('method') or 'not-selected'} {aider.get('version') or ''}. "
        f"Translator profile {profile.get('id')} is locked. Ready check planned. Chat is unlocked."
    )
    if _grok_ready():
        message = GROK_MESSAGE + " " + message
    doc = {
        "phase": "ready",
        "chat_unlocked": True,
        "brain": "grok" if _grok_ready() else "granite",
        "profile_id": profile.get("id") or "",
        "model": decision.get("model") or "",
        "aider": aider,
        "ready_check": ready,
        "ollama": decision.get("ollama") or {},
        "dry_run": dry,
        "vast_calls": 0,
        "destroyed": False,
        "message": message,
        "probe": probe,
        "downloads": {**plan, "executed": executed, "report": _public_report(report)},
    }
    try:
        import llm_router

        doc["llm"] = llm_router.public_status(granite_model_name=decision.get("model") or "")
    except Exception:
        pass
    doc = hardware_probe.strip_retired_ada(doc)
    decision = hardware_probe.strip_retired_ada(decision)
    _write(state, doc)
    return {
        "ok": True,
        "http": 200,
        **doc,
        "decision": decision,
        "profile": profile.get("id") or "",
    }


def _ready_note() -> str:
    try:
        import llm_router

        if llm_router.key_present():
            return (
                "Ready check planned. Aider would start with XAI_API_BASE and --model xai/<grok model>. "
                "XAI_API_KEY stays in the environment."
            )
    except Exception:
        pass
    return "Ready check planned. Aider would start with OLLAMA_API_BASE and --model ollama_chat/<granite tag>."


def _public_report(report) -> dict:
    if not isinstance(report, dict):
        return {"ok": True}
    keep = {}
    for key in ("executed", "dry_run", "planned", "install", "status", "vast_calls", "destroyed", "model"):
        if key in report:
            keep[key] = report[key]
    keep.setdefault("vast_calls", 0)
    keep.setdefault("destroyed", False)
    return keep
