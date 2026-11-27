#!/usr/bin/env python3
"""What is really installed, and where Granite really runs (S6, A2, B9, S8, S10).

Detect and Setup check used to show the plan ("Ollama linux-install-sh-cuda 0.40.13") instead of what the
computer has (run 2 actually had 0.40.14). This reads the truth, each step with a short time limit:
- Ollama: GET /api/version, /api/tags, /api/ps (size_vram > 0 means GPU; size_vram == size means all on GPU).
- The ollama binary on PATH / user-mode / Windows %LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe (also from WSL).
- Port 11434 answering but not Ollama (something else owns it).
- aider --version; pytest --version in the interpreter that runs the tests; ComfyUI folder and its venv.
No network beyond 127.0.0.1 / OLLAMA_API_BASE. Never installs anything.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path


def _base() -> str:
    return (os.environ.get("OLLAMA_API_BASE") or "http://127.0.0.1:11434").strip().rstrip("/")


def _get(path: str, opener=None, timeout: float = 2.0):
    """(status, json-or-None, error)."""
    try:
        with (opener or urllib.request.urlopen)(_base() + path, timeout=timeout) as resp:
            body = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
    except Exception as exc:
        return 0, None, type(exc).__name__
    try:
        return status, json.loads(body.decode("utf-8") or "null"), ""
    except ValueError:
        return status, None, "not json"


def where_model_runs(ps_doc: dict | None, gpu_available: bool | None = None) -> list[dict]:
    """From /api/ps: each loaded model and GPU / CPU / split (A2).

    gpu_available=False (Detect found no GPU Ollama can use) means CPU even when size_vram > 0: Ollama 0.40.14 on this
    CPU-only box reported size_vram 5.2 GB of 8.4 GB while its log said "inference compute ... library=cpu".
    """
    out = []
    for row in (ps_doc or {}).get("models") or []:
        size = float(row.get("size") or 0)
        vram = float(row.get("size_vram") or 0)
        if gpu_available is False:
            vram = 0.0
        if vram <= 0:
            where, pct = "CPU", 0
        elif size and vram >= size * 0.99:
            where, pct = "GPU", 100
        else:
            pct = int(round(100 * vram / size)) if size else 0
            where = "split"
        line = {"GPU": "on the GPU", "CPU": "on the CPU", "split": f"split, {pct}% on the GPU"}[where]
        out.append({"model": row.get("name") or row.get("model") or "", "where": where, "gpu_percent": pct,
                    "everyday": f"Granite ({row.get('name') or row.get('model')}) is running {line}."})
    return out


def _ollama_binaries() -> list[str]:
    found = []
    own_ollama = os.environ.get("SIMKOSI_OLLAMA_EXE") or ""
    for cand in (own_ollama, shutil.which("ollama"), str(Path.home() / ".local/share/simko/ollama/bin/ollama"), "/usr/local/bin/ollama", "/usr/bin/ollama"):
        if cand and os.path.isfile(cand) and cand not in found:
            found.append(cand)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        exe = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if exe.is_file():
            found.append(str(exe))
    users = Path("/mnt/c/Users")
    if users.is_dir():  # WSL: a Windows Ollama install (B9)
        try:
            for user in users.iterdir():
                exe = user / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
                if exe.is_file():
                    found.append(str(exe))
        except OSError:
            pass
    return found


def _version_of(argv: list[str], runner=subprocess.run, timeout: float = 15) -> str:
    try:
        proc = runner(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"(\d+\.\d+\.\d+)", (proc.stdout or "") + (proc.stderr or ""))
    return m.group(1) if proc.returncode == 0 and m else ""


def aider_version(runner=subprocess.run) -> str:
    tool_bin = os.environ.get("UV_TOOL_BIN_DIR") or ""
    own = os.path.join(tool_bin, "aider.exe" if os.name == "nt" else "aider") if tool_bin else ""
    for exe in (own, shutil.which("aider"), str(Path.home() / ".local/bin/aider")):
        if exe and os.path.isfile(exe):
            v = _version_of([exe, "--version"], runner)
            if v:
                return v
    return ""


def pytest_version(runner=subprocess.run) -> str:
    """pytest in the interpreter aider_job runs the tests with (the Simko SI test venv, else the system Python)."""
    import coding_intent

    return _version_of([coding_intent.test_python(), "-m", "pytest", "--version"], runner)


def comfyui(state: Path | None = None) -> dict:
    for root in ([state / "video" / "ComfyUI", state / "image" / "ComfyUI"] if state else []) + [Path.home() / "ComfyUI"]:
        if (root / "main.py").is_file():
            venv = any((root / d / "bin" / "python").exists() or (root / d / "Scripts" / "python.exe").exists() for d in ("venv", ".venv"))
            return {"present": True, "path": str(root), "complete": venv,
                    "everyday": "ComfyUI is installed." if venv else "ComfyUI is half-installed (no Python venv); Download can repair it."}
    return {"present": False, "path": "", "complete": False, "everyday": ""}


def _gpu_available(state: Path | None, probe: dict | None) -> bool | None:
    if probe is None and state is not None:
        try:
            probe = (json.loads((Path(state) / "hardware.json").read_text(encoding="utf-8")) or {}).get("probe")
        except (OSError, ValueError):
            probe = None
    if not isinstance(probe, dict):
        return None
    if probe.get("ollama_gpu") is not None:
        return bool(probe.get("ollama_gpu"))
    return float(probe.get("vram_gb") or 0) > 0


def read(state: Path | None = None, opener=None, runner=subprocess.run, pinned: str = "", probe: dict | None = None) -> dict:
    status, ver, err = _get("/api/version", opener)
    api_up = status == 200 and isinstance(ver, dict) and bool(ver.get("version"))
    _, tags, _ = _get("/api/tags", opener) if api_up else (0, None, "")
    _, ps, _ = _get("/api/ps", opener) if api_up else (0, None, "")
    models = [str(m.get("name") or m.get("model") or "") for m in ((tags or {}).get("models") or [])]
    running = where_model_runs(ps if isinstance(ps, dict) else None, _gpu_available(state, probe))
    binaries = _ollama_binaries()
    version = (ver or {}).get("version", "") if api_up else ""
    lines = []
    if api_up:
        lines.append(f"Installed: Ollama {version}" + (f" (plan pinned {pinned})" if pinned and pinned != version else "") + ".")
        lines.append("Models: " + (", ".join(models) if models else "none pulled yet") + ".")
    elif status and not api_up:
        lines.append("Port 11434 answers, but it is not Ollama; something else is using it.")
    elif binaries:
        lines.append("Ollama is installed (" + binaries[0] + ") but not running.")
    else:
        lines.append("Ollama is not installed yet.")
    if any(b.endswith("ollama.exe") for b in binaries) and not api_up:
        lines.append("A Windows copy of Ollama is installed; start it, or turn on WSL mirrored networking so Simko SI can reach it.")
    av = aider_version(runner)
    lines.append(f"Installed: Aider {av}." if av else "Aider is not installed yet.")
    pv = pytest_version(runner)
    lines.append(f"Installed: pytest {pv}." if pv else "pytest is not installed yet.")
    for r in running:
        lines.append(r["everyday"])
    comfy = comfyui(state)
    if comfy["everyday"]:
        lines.append(comfy["everyday"])
    return {"ollama": {"running": api_up, "version": version, "models": models, "binaries": binaries,
                       "port_owner_other": bool(status) and not api_up, "loaded": running},
            "aider": {"version": av, "installed": bool(av)},
            "pytest": {"version": pv, "installed": bool(pv)}, "comfyui": comfy, "lines": lines}
