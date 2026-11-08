#!/usr/bin/env python3
"""Local hardware probe. Picks the Download stack. Does not rent or call Vast.

GPU, VRAM, RAM, and free disk decide a local install. CPU is recorded and does not pick the stack.
q8_0 is cloud RTX 3090 only. A laptop that is too small is told to Confirm Rent; Download never rents.

Joseph confirmed Ada means Aider (aider-chat), the coding agent. A coding
host installs a pinned Aider and points it at the chosen Granite tag through
Ollama. Video boots and computers that are too small do not install Aider.
Aider is not a second model in VRAM, so it can sit beside Granite. Wan still
cannot.

Ollama is chosen by platform and whether nvidia-smi can see a GPU. The catalog
pins one version and varies the install method. nvidia-smi missing is an empty GPU.
"""
from __future__ import annotations

import json
import platform as platform_mod
import shutil
import subprocess
import sys
from pathlib import Path

# ~8GB and ~16GB stay Q4. ~32GB (often reported as 28–31 GiB) is Q5.
CODING_MIN_RAM_GB = 7.0
CODING_Q5_RAM_GB = 24.0
CODING_MIN_DISK_GB = 12.0
VIDEO_MIN_VRAM_GB = 8.0
VIDEO_MIN_DISK_GB = 40.0
IMAGE_MIN_VRAM_GB = 6.0
IMAGE_MIN_DISK_GB = 20.0

Q4_MODEL = "granite4.2:8b"
Q5_MODEL = "granite4.2:8b-q5_0"
Q8_MODEL = "granite4.2:8b-q8_0"

CLOUD_OFFER = "RTX 3090, at least 900 Mbps, 150 GB disk"

# Catalog pin. The install method changes with the host; the version does not.
# 0.40.13 is what the official Linux install.sh delivered on 2026-10-29.
OLLAMA_VERSION = "0.40.13"

# aider-chat pin. The install method changes with the host; the version does not.
AIDER_VERSION = "0.86.2"
AIDER_PACKAGE = "aider-chat"
OLLAMA_API_BASE = "http://127.0.0.1:11434"


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _host_platform() -> str:
    name = sys.platform or ""
    if name.startswith("linux"):
        return "linux"
    if name == "darwin":
        return "darwin"
    if name.startswith("win"):
        return "windows"
    return name or "unknown"


def normalize(raw: dict | None) -> dict:
    raw = raw or {}
    gpu = str(raw.get("gpu") or "none").strip() or "none"
    platform_name = str(raw.get("platform") or "").strip().lower() or _host_platform()
    return {
        "gpu": gpu,
        "vram_gb": round(_num(raw.get("vram_gb")), 1),
        "ram_gb": round(_num(raw.get("ram_gb")), 1),
        "disk_free_gb": round(_num(raw.get("disk_free_gb")), 1),
        "cpu": str(raw.get("cpu") or "").strip(),
        "platform": platform_name,
    }


def _ram_gb() -> float:
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.is_file():
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return round(float(line.split()[1]) / (1024 * 1024), 1)
    except (OSError, IndexError, ValueError):
        pass
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0 and (proc.stdout or "").strip():
                return round(float(proc.stdout.strip()) / (1024 ** 3), 1)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return 0.0
    if sys.platform.startswith("win"):
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return round(stat.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            return 0.0
    return 0.0


def _disk_free_gb() -> float:
    try:
        target = Path.home() if Path.home().exists() else Path("/")
        return round(shutil.disk_usage(target).free / (1024 ** 3), 1)
    except OSError:
        return 0.0


def _cpu() -> str:
    try:
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.is_file():
            for line in cpuinfo.read_text(encoding="utf-8").splitlines():
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0 and (proc.stdout or "").strip():
                return proc.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        return platform_mod.processor() or platform_mod.machine() or ""
    except Exception:
        return ""


def _gpu() -> tuple[str, float]:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "none", 0.0
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return "none", 0.0
    best_name, best_vram = "none", 0.0
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        vram = _num(parts[1]) / 1024.0
        if vram >= best_vram:
            best_name, best_vram = parts[0] or "GPU", vram
    if best_vram <= 0:
        return "none", 0.0
    return best_name, round(best_vram, 1)


def detect() -> dict:
    gpu, vram = _gpu()
    return normalize({
        "gpu": gpu,
        "vram_gb": vram,
        "ram_gb": _ram_gb(),
        "disk_free_gb": _disk_free_gb(),
        "cpu": _cpu(),
    })


def _rent_message(role: str, why: str) -> str:
    return (
        f"This laptop is too small for {role}: {why}. "
        f"Rent a matching cloud computer ({CLOUD_OFFER}). "
        "Check I confirm RENT, then Confirm Rent. Download will not rent one for you."
    )


def _cloud_decision(role: str) -> dict:
    if role == "video":
        stack = "ComfyUI and Wan2.2-TI2V-5B"
        script = "install-video-comfy-wan.sh"
        model = ""
        quant = ""
        message = (
            "Cloud Video downloads ComfyUI and Wan2.2-TI2V-5B on its own computer after Confirm Rent. "
            f"The offer stays {CLOUD_OFFER}. Granite is not installed there."
        )
    elif role == "image":
        stack = "ComfyUI"
        script = "install-image-role.sh"
        model = ""
        quant = ""
        message = (
            "Cloud Image downloads ComfyUI without Wan after Confirm Rent. "
            f"The offer stays {CLOUD_OFFER}."
        )
    else:
        stack = "Ollama, granite4.2:8b-q8_0, and Aider"
        script = "install-on-pod-q8.sh"
        model = Q8_MODEL
        quant = "q8_0"
        message = (
            "Cloud Coding downloads Ollama, granite4.2:8b-q8_0, and Aider after Confirm Rent. "
            f"The offer stays {CLOUD_OFFER}. ComfyUI is not installed on that computer."
        )
    return {
        "ok": True,
        "needs_rent": False,
        "role": "coding" if role not in {"video", "image"} else role,
        "compute": "cloud",
        "script": script,
        "model": model,
        "quant": quant,
        "stack": stack,
        "where": "the rented computer",
        "message": message,
    }


def _choose_core(role: str, probe: dict, compute: str) -> dict:
    """Pick one install for this role. Local uses the probe. Cloud stays on the 3090 stack."""
    role = (role or "coding").strip().lower()
    compute = (compute or "local").strip().lower()
    facts = normalize(probe)
    if compute == "cloud":
        return _cloud_decision(role)
    if role == "combined":
        return {
            "ok": False,
            "needs_rent": True,
            "role": role,
            "compute": "local",
            "script": "",
            "model": "",
            "quant": "",
            "stack": "",
            "where": "a rented cloud computer",
            "message": (
                "Coding and video stay on separate computers. Granite and Wan do not load together. "
                f"Rent a matching cloud computer ({CLOUD_OFFER}). "
                "Check I confirm RENT, then Confirm Rent. Download will not rent one for you."
            ),
        }
    if role == "video":
        if facts["vram_gb"] >= VIDEO_MIN_VRAM_GB and facts["disk_free_gb"] >= VIDEO_MIN_DISK_GB:
            return {
                "ok": True,
                "needs_rent": False,
                "role": "video",
                "compute": "local",
                "script": "install-video-comfy-wan.sh",
                "model": "",
                "quant": "",
                "stack": "ComfyUI and Wan2.2-TI2V-5B",
                "where": "this laptop",
                "message": (
                    f"This laptop has {facts['vram_gb']:g} GB of GPU memory and {facts['disk_free_gb']:g} GB free. "
                    "Video will download ComfyUI and Wan2.2-TI2V-5B here. Granite will not load beside Wan."
                ),
            }
        return {
            "ok": False,
            "needs_rent": True,
            "role": "video",
            "compute": "local",
            "script": "",
            "model": "",
            "quant": "",
            "stack": "",
            "where": "a rented cloud computer",
            "message": _rent_message(
                "video",
                f"Wan2.2-TI2V-5B needs {VIDEO_MIN_VRAM_GB:g} GB of GPU memory and {VIDEO_MIN_DISK_GB:g} GB free disk",
            ),
        }
    if role == "image":
        if facts["vram_gb"] >= IMAGE_MIN_VRAM_GB and facts["disk_free_gb"] >= IMAGE_MIN_DISK_GB:
            return {
                "ok": True,
                "needs_rent": False,
                "role": "image",
                "compute": "local",
                "script": "install-image-role.sh",
                "model": "",
                "quant": "",
                "stack": "ComfyUI",
                "where": "this laptop",
                "message": (
                    f"This laptop has {facts['vram_gb']:g} GB of GPU memory and {facts['disk_free_gb']:g} GB free. "
                    "Image will download ComfyUI here, without Wan."
                ),
            }
        return {
            "ok": False,
            "needs_rent": True,
            "role": "image",
            "compute": "local",
            "script": "",
            "model": "",
            "quant": "",
            "stack": "",
            "where": "a rented cloud computer",
            "message": _rent_message(
                "image",
                f"ComfyUI needs {IMAGE_MIN_VRAM_GB:g} GB of GPU memory and {IMAGE_MIN_DISK_GB:g} GB free disk",
            ),
        }
    if facts["ram_gb"] < CODING_MIN_RAM_GB or facts["disk_free_gb"] < CODING_MIN_DISK_GB:
        return {
            "ok": False,
            "needs_rent": True,
            "role": "coding",
            "compute": "local",
            "script": "",
            "model": "",
            "quant": "",
            "stack": "",
            "where": "a rented cloud computer",
            "message": _rent_message(
                "coding",
                f"Granite needs about 8 GB of RAM and {CODING_MIN_DISK_GB:g} GB free disk",
            ),
        }
    if facts["ram_gb"] >= CODING_Q5_RAM_GB:
        model, quant, label = Q5_MODEL, "Q5", "granite4.2:8b-q5_0 Q5"
        profile = "local_ram32_q5"
    else:
        model, quant, label = Q4_MODEL, "Q4", "granite4.2:8b Q4"
        profile = "local_aspire_ryzen7000"
    return {
        "ok": True,
        "needs_rent": False,
        "role": "coding",
        "compute": "local",
        "script": "install-local-aspire.sh",
        "model": model,
        "quant": quant,
        "profile": profile,
        "stack": f"Ollama, {label}, and Aider",
        "where": "this laptop",
        "message": (
            f"This laptop has {facts['ram_gb']:g} GB of RAM. "
            f"Coding will download Ollama, {label}, and Aider here. "
            "The cloud q8_0 weights stay on a rented RTX 3090."
        ),
    }


def _residents(decision: dict) -> list[str]:
    stack = (decision.get("stack") or "").lower()
    model = (decision.get("model") or "").lower()
    found: list[str] = []
    if model.startswith("granite") or "granite" in stack:
        found.append("granite")
    if "wan" in stack:
        found.append("wan")
    return found


def _nvidia(facts: dict) -> bool:
    gpu = str(facts.get("gpu") or "").lower()
    if _num(facts.get("vram_gb")) <= 0:
        return False
    if gpu in {"none", "igpu", "intel"}:
        return False
    if "radeon" in gpu or "amd" in gpu:
        return False
    return True


def _ollama_choice(facts: dict, platform_name: str) -> dict:
    version = OLLAMA_VERSION
    if platform_name.startswith("darwin") or platform_name == "macos":
        return {"version": version, "method": "macos-dmg", "package": "Ollama.dmg"}
    if platform_name.startswith("win"):
        return {"version": version, "method": "windows-exe", "package": "OllamaSetup.exe"}
    if _nvidia(facts):
        return {"version": version, "method": "linux-install-sh-cuda", "package": "install.sh"}
    return {"version": version, "method": "linux-install-sh", "package": "install.sh"}


def _aider_none() -> dict:
    return {
        "name": "aider",
        "version": "",
        "method": "not-selected",
        "package": AIDER_PACKAGE,
        "model_flag": "",
        "env": {},
        "argv": [],
        "note": "Aider is not installed for video, image, or a computer that is too small.",
    }


def _aider_choice(facts: dict, platform_name: str, model: str) -> dict:
    """Pick pipx, uv, or a venv. The pin stays put."""
    disk = _num(facts.get("disk_free_gb"))
    if platform_name.startswith("win"):
        method = "pip-venv"
        note = f"python -m venv .venv && pip install {AIDER_PACKAGE}=={AIDER_VERSION}"
    elif (not platform_name.startswith("darwin")) and platform_name != "macos" and disk >= 80:
        method = "uv"
        note = f"uv tool install {AIDER_PACKAGE}=={AIDER_VERSION}"
    else:
        method = "pipx"
        note = f"pipx install {AIDER_PACKAGE}=={AIDER_VERSION}"
    flag = f"ollama_chat/{model}" if model else ""
    return _grok_aider({
        "name": "aider",
        "version": AIDER_VERSION,
        "method": method,
        "package": AIDER_PACKAGE,
        "model_flag": flag,
        "env": {"OLLAMA_API_BASE": OLLAMA_API_BASE},
        "argv": ["aider", "--model", flag] if flag else [],
        "note": note,
    }, model)


def aider_launch(model: str, message: str = "") -> dict:
    """How the host should start Aider against the selected Granite tag."""
    tag = (model or "").strip()
    flag = f"ollama_chat/{tag}" if tag else ""
    argv = ["aider", "--model", flag, "--no-detect-urls"]
    if message:
        argv.extend(["--message", message])
    return _grok_aider({
        "route": "aider",
        "version": AIDER_VERSION,
        "argv": argv,
        "env": {"OLLAMA_API_BASE": OLLAMA_API_BASE},
        "model": flag,
    }, tag)


def _grok_aider(choice: dict, model: str) -> dict:
    """When XAI_API_KEY is set, point Aider at Grok. Otherwise leave the Granite plan."""
    try:
        import llm_router
    except Exception:
        return choice
    if not llm_router.key_present():
        return choice
    picked = llm_router.aider_settings(model)
    updated = dict(choice)
    flag = picked["model_flag"]
    updated["model_flag"] = flag
    updated["env"] = dict(picked["env"])
    updated["llm_backend"] = "grok"
    if "model" in updated:
        updated["model"] = flag
    argv = list(updated.get("argv") or [])
    if "--model" in argv:
        argv[argv.index("--model") + 1] = flag
    elif flag:
        argv.extend(["--model", flag])
    updated["argv"] = argv
    if picked.get("note"):
        updated["note"] = ((updated.get("note") or "") + " " + picked["note"]).strip()
    return updated


def strip_retired_ada(value):
    """Drop the retired Ada adapter slot and any profile id that still says -ada-."""
    retired = {
        "granite-q4-ada-chat": "granite-q4-chat",
        "granite-q5-ada-chat": "granite-q5-chat",
        "granite-q8-ada-tools": "granite-q8-tools",
        "granite-q8-ada-chat": "granite-q8-tools",
    }
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key == "adapter":
                continue
            cleaned[key] = strip_retired_ada(item)
        return cleaned
    if isinstance(value, list):
        return [strip_retired_ada(item) for item in value]
    if isinstance(value, str):
        text = retired.get(value, value)
        if "ada-granite" in text or "-ada-" in text or "Ada slot" in text:
            for old, new in retired.items():
                text = text.replace(old, new)
            text = text.replace("Ada slot ada-granite-chat", "Aider")
            text = text.replace("Ada slot ada-granite-tools", "Aider")
            text = text.replace("ada-granite-chat", "")
            text = text.replace("ada-granite-tools", "")
            text = text.replace("ada-granite", "")
        return text
    return value


def _translation_profile_id(model: str) -> str:
    if not model:
        return ""
    if "q8" in model:
        return "granite-q8-tools"
    if "q5" in model:
        return "granite-q5-chat"
    return "granite-q4-chat"


def _decorate(decision: dict, facts: dict) -> dict:
    out = dict(decision)
    role = out.get("role") or "coding"
    platform_name = str(facts.get("platform") or _host_platform())
    residents = _residents(out)
    if "granite" in residents and "wan" in residents and _num(facts.get("vram_gb")) <= 24:
        out.update({
            "ok": False,
            "needs_rent": True,
            "model": "",
            "quant": "",
            "stack": "",
            "script": "",
            "message": (
                "Granite and Wan are not loaded in VRAM at the same time on a 24 GB GPU. "
                "Pick coding or video, not both."
            ),
        })
        residents = []
    target = facts
    if out.get("compute") == "cloud" and role == "coding" and out.get("ok"):
        target = dict(facts)
        target["vram_gb"] = max(_num(facts.get("vram_gb")), 24)
        target["gpu"] = "RTX 3090"
    if role in {"video", "image"} or not out.get("ok") or not out.get("model"):
        ollama = {"version": "", "method": "not-selected", "package": ""}
        aider = _aider_none()
    else:
        ollama = _ollama_choice(target, platform_name)
        aider = _aider_choice(target, platform_name, out.get("model") or "")
    out["tag"] = out.get("model") or ""
    out["ollama"] = ollama
    out["aider"] = aider
    out["vram_residents"] = residents
    out["vram_simultaneous"] = False
    out["platform"] = platform_name
    out["translation_profile"] = _translation_profile_id(out.get("model") or "")
    return out


def choose(role: str, probe: dict, compute: str, platform: str | None = None) -> dict:
    raw = dict(probe or {})
    if platform:
        raw["platform"] = platform
    decision = _choose_core(role, raw, compute)
    return _decorate(decision, normalize(raw))


def loads_both(decision: dict) -> bool:
    residents = set(decision.get("vram_residents") or [])
    return "granite" in residents and "wan" in residents


def simultaneous(coding: dict, video: dict, vram_gb: float = 24) -> dict:
    """Coding and video are different boots. A 24 GB card never holds both."""
    return {
        "coding": list(coding.get("vram_residents") or []),
        "video": list(video.get("vram_residents") or []),
        "exclusive": not (loads_both(coding) or loads_both(video)),
        "allowed_on_24gb": float(vram_gb) > 24 or not (loads_both(coding) or loads_both(video)),
        "same_boot": False,
    }


def remember(state: Path, probe: dict, decision: dict) -> None:
    state.mkdir(parents=True, exist_ok=True)
    payload = {"probe": normalize(probe), "decision": decision, "vast_calls": 0, "destroyed": False}
    (state / "hardware.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def advise(state: Path, body: dict | None) -> tuple[int, dict]:
    import compute_profiles
    import roles

    body = body or {}
    try:
        role = roles.resolve_role(str(body.get("role") or "coding"))
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc), "vast_calls": 0, "destroyed": False}
    compute = str(body.get("compute") or compute_profiles.current(state).get("compute") or "cloud").lower()
    if compute not in {"local", "cloud"}:
        compute = "cloud"
    raw = body.get("probe")
    probe = normalize(raw) if isinstance(raw, dict) else detect()
    decision = choose(role, probe, compute)
    remember(state, probe, decision)
    try:
        import llm_router

        llm = llm_router.public_status(granite_model_name=decision.get("model") or "")
    except Exception:
        llm = {"order": ["grok", "granite", "canned"], "preferred": "granite", "backend": "granite", "key_set": False}
    return 200, strip_retired_ada({
        "ok": True,
        "vast_calls": 0,
        "destroyed": False,
        "role": role,
        "compute": compute,
        "probe": probe,
        "model": decision.get("model") or "",
        "quant": decision.get("quant") or "",
        "install_script": decision.get("script") or "",
        "needs_rent": bool(decision.get("needs_rent")),
        "message": decision["message"],
        "tag": decision.get("tag") or "",
        "aider": decision.get("aider") or {},
        "ollama": decision.get("ollama") or {},
        "vram_residents": decision.get("vram_residents") or [],
        "vram_simultaneous": False,
        "translation_profile": decision.get("translation_profile") or "",
        "platform": probe.get("platform") or "",
        "llm": llm,
        "backend": llm.get("preferred") or llm.get("backend") or "granite",
    })
