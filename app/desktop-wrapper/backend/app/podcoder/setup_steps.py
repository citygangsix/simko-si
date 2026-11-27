#!/usr/bin/env python3
"""First-run setup for the Simko SI desktop app: every download happens here, driven by buttons in the UI.

No bash, curl, PowerShell, sudo or admin rights. Everything lands in the per-user app-data folder
(SIMKOSI_DATA_DIR: %LOCALAPPDATA%\\SimkoSI, ~/Library/Application Support/SimkoSI, ~/.local/share/simko-si).
The same code runs on Windows, macOS and Linux; only the pinned download per OS differs.

Steps: uv -> aider (+ pytest test venv) -> ollama -> granite -> comfyui (images). Video (Wan) stays on the
rented cloud computer (Confirm Rent in chat), never local.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

UV_VERSION = "0.13.7"
OLLAMA_VERSION = "0.40.15"
COMFYUI_VERSION = "0.44.0"
AIDER_VERSION = "0.86.2"
PYTEST_VERSION = "9.2.0"
GRANITE_MODEL = os.environ.get("SIMKOSI_GRANITE_MODEL", "granite4.2:8b")  # Q4_K_M; same default as local_model.DEFAULT

# Pinned assets with the sha256 GitHub publishes for them (checked Nov 6, 2026).
UV_ASSETS = {
    ("windows", "x86_64"): ("uv-x86_64-pc-windows-msvc.zip", "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021"),
    ("windows", "arm64"): ("uv-aarch64-pc-windows-msvc.zip", "505d9e65e7692bac3ddf98c66754aa26c5050c409c184af30a881a0a72cc85e3"),
    ("linux", "x86_64"): ("uv-x86_64-unknown-linux-gnu.tar.gz", "c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83"),
    ("mac", "arm64"): ("uv-aarch64-apple-darwin.tar.gz", "81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731"),
    ("mac", "x86_64"): ("uv-x86_64-apple-darwin.tar.gz", "20c47e4c1f630b8abaff8c291fa9b9aa300fef92c4fbff95adf198b55287cda7"),
}
OLLAMA_ASSETS = {
    "windows": ("ollama-windows-amd64.zip", "9ca74a7ab66ec86870b1eecac7df160df08dc4e3a291ab5d2d59bcf9310221c6", 1614941966),
    "linux": ("ollama-linux-amd64.tar.zst", "628c018404a4206493efd38e46251c154ede5141b8b8dc85c659b3b027c47379", 1543547172),
    "mac": ("Ollama-darwin.zip", "de3298b9897828480c361c101e3efd2d3c499d08882c8ee972df524064abc3db", 229106611),
}

STEPS = [
    {"id": "uv", "title": "Python tools manager (uv)", "size": "about 15 MB", "optional": False,
     "why": "Lets Simko SI install its coding tools without admin rights."},
    {"id": "aider", "title": "Coding tools (Aider + pytest)", "size": "about 400 MB", "optional": False,
     "why": "Writes and tests code for you. Needs uv."},
    {"id": "ollama", "title": "Local model runner (Ollama)", "size": "about 1.6 GB", "optional": True,
     "why": "Runs Granite on this computer, offline."},
    {"id": "granite", "title": "Granite model", "size": "about 5.3 GB", "optional": True,
     "why": "The local coding model. Needs Ollama."},
    {"id": "comfyui", "title": "Images (ComfyUI)", "size": "about 3 GB", "optional": True,
     "why": "Local image making. Video always runs on a rented cloud computer."},
]
DEPENDS = {"aider": ["uv"], "granite": ["ollama"], "comfyui": ["uv"]}

_lock = threading.Lock()
_running: dict[str, threading.Thread] = {}
_ollama_proc: subprocess.Popen | None = None
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ---------- paths ----------
def os_name() -> str:
    if os.name == "nt":
        return "windows"
    return "mac" if sys.platform == "darwin" else "linux"


def arch() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def data_dir() -> Path:
    raw = os.environ.get("SIMKOSI_DATA_DIR")
    if raw:
        return Path(raw)
    if os_name() == "windows":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "SimkoSI"
    if os_name() == "mac":
        return Path.home() / "Library" / "Application Support" / "SimkoSI"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "simko-si"


def tools() -> Path:
    return data_dir() / "tools"


def exe(name: str) -> str:
    return name + ".exe" if os_name() == "windows" else name


def uv_exe() -> Path:
    return tools() / "uv" / exe("uv")


def ollama_exe() -> Path:
    if os_name() == "mac":
        return tools() / "ollama" / "Ollama.app" / "Contents" / "Resources" / "ollama"
    if os_name() == "linux":
        return tools() / "ollama" / "bin" / "ollama"
    return tools() / "ollama" / "ollama.exe"


def test_venv() -> Path:
    return data_dir() / "test-venv"


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os_name() == "windows" else "bin/python")


def configure_env() -> None:
    """Point every tool at app-data so nothing touches the user PATH, registry or system folders."""
    d = data_dir()
    for sub in ("tools", "logs", "downloads", "state", "models"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    os.environ["SIMKOSI_DATA_DIR"] = str(d)
    os.environ.setdefault("PODCODER_STATE_DIR", str(d / "state"))
    os.environ["UV_TOOL_DIR"] = str(tools() / "uv-tools")
    os.environ["UV_TOOL_BIN_DIR"] = str(tools() / "bin")
    os.environ["UV_PYTHON_INSTALL_DIR"] = str(tools() / "python")
    os.environ["UV_CACHE_DIR"] = str(d / "downloads" / "uv-cache")
    os.environ["UV_NO_MODIFY_PATH"] = "1"
    os.environ["PODCODER_TEST_VENV"] = str(test_venv())
    os.environ["SIMKOSI_OLLAMA_EXE"] = str(ollama_exe())
    os.environ.setdefault("OLLAMA_MODELS", str(d / "models" / "ollama"))
    extra = [str(tools() / "bin"), str(ollama_exe().parent), str(uv_exe().parent)]
    os.environ["PATH"] = os.pathsep.join(extra + [os.environ.get("PATH", "")])


# ---------- status ----------
def _status_file() -> Path:
    return data_dir() / "setup-status.json"


def _load() -> dict:
    try:
        return json.loads(_status_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(all_status: dict) -> None:
    f = _status_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_status, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def _set(step: str, **kw) -> None:
    with _lock:
        s = _load()
        cur = s.get(step, {})
        cur.update(kw)
        cur["updated"] = time.time()
        s[step] = cur
        _save(s)


def _log(step: str, line: str) -> None:
    logf = data_dir() / "logs" / f"setup-{step}.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    with open(logf, "a", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line.rstrip() + "\n")


def detect(step: str) -> bool:
    if step == "uv":
        return uv_exe().is_file()
    if step == "aider":
        return (tools() / "bin" / exe("aider")).is_file() and venv_python(test_venv()).is_file()
    if step == "ollama":
        return ollama_exe().is_file()
    if step == "granite":
        tags = _ollama_tags()
        # The exact tag, not any Granite: "Ready" used to show while the planned tag was never pulled.
        return GRANITE_MODEL in tags or (GRANITE_MODEL + ":latest") in tags
    if step == "comfyui":
        return venv_python(tools() / "comfyui-venv").is_file() and (tools() / "ComfyUI" / "main.py").is_file()
    return False


def status() -> dict:
    saved = _load()
    out = []
    for meta in STEPS:
        sid = meta["id"]
        st = dict(saved.get(sid, {}))
        alive = sid in _running and _running[sid].is_alive()
        if detect(sid) and not alive:
            st["stage"] = "Ready"
        elif not alive and st.get("stage") in ("Downloading", "Installing", "Waiting"):
            st["stage"] = "Stopped"  # app was closed mid-download; Run again resumes
        st.setdefault("stage", "Not installed")
        out.append({**meta, **st, "running": alive, "needs": DEPENDS.get(sid, [])})
    return {"ok": True, "os": os_name(), "arch": arch(), "data_dir": str(data_dir()), "steps": out,
            "video": "Video (Wan) runs only on a rented cloud computer. Use Confirm Rent in chat."}


# ---------- download helpers ----------
def download(step: str, url: str, dest: Path, sha256: str | None = None, size: int | None = None) -> Path:
    """Resumable download with progress and sha256 check."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and sha256 and _sha(dest) == sha256:
        return dest
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "SimkoSI-setup"})
    if have:
        req.add_header("Range", f"bytes={have}-")
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0
        total = int(r.headers.get("Content-Length") or 0) + have or (size or 0)
        mode = "ab" if have else "wb"
        done = have
        last = 0.0
        with open(part, mode) as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if time.time() - last > 0.5:
                    last = time.time()
                    _set(step, stage="Downloading", done=done, total=total,
                         message=f"Downloading {dest.name}")
    _set(step, stage="Installing", done=done, total=total, message="Checking download")
    if sha256:
        got = _sha(part)
        if got != sha256:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{dest.name} failed its checksum (got {got[:12]}..., expected {sha256[:12]}...)")
    os.replace(part, dest)
    return dest


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for m in zf.infolist():
        target = (dest / m.filename).resolve()
        if root not in target.parents and target != root:
            raise RuntimeError("unsafe path in archive")
    zf.extractall(dest)


def _extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    name = archive.name
    if name.endswith(".zip"):
        if os_name() == "mac":
            # Keep symlinks and exec bits inside Ollama.app.
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(dest)], check=True)
            return
        with zipfile.ZipFile(archive) as zf:
            _safe_extract_zip(zf, dest)
    elif name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest, filter="data")
    elif name.endswith(".tar.zst"):
        import zstandard
        with open(archive, "rb") as fh, zstandard.ZstdDecompressor().stream_reader(fh) as zr:
            with tarfile.open(fileobj=zr, mode="r|") as tf:
                tf.extractall(dest, filter="data")
    else:
        raise RuntimeError(f"unknown archive {name}")


def _run(step: str, argv: list[str], timeout: int = 3600) -> None:
    _log(step, "run: " + " ".join(argv))
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW, env=os.environ.copy())
    start = time.time()
    assert proc.stdout
    for line in proc.stdout:
        _log(step, line)
        if line.strip():
            _set(step, stage="Installing", message=line.strip()[:160])
        if time.time() - start > timeout:
            proc.kill()
            raise RuntimeError("timed out")
    if proc.wait() != 0:
        raise RuntimeError(f"{Path(argv[0]).name} exited with {proc.returncode}; see logs/setup-{step}.log")


# ---------- steps ----------
def step_uv() -> None:
    key = (os_name(), arch())
    if key not in UV_ASSETS:
        raise RuntimeError(f"no uv build pinned for {key}")
    name, sha = UV_ASSETS[key]
    url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{name}"
    arc = download("uv", url, data_dir() / "downloads" / name, sha)
    tmp = tools() / "uv-extract"
    shutil.rmtree(tmp, ignore_errors=True)
    _extract(arc, tmp)
    found = next(p for p in tmp.rglob(exe("uv")) if p.is_file())
    uv_exe().parent.mkdir(parents=True, exist_ok=True)
    for sib in found.parent.iterdir():  # uv + uvx (+ uvw on Windows)
        shutil.copy2(sib, uv_exe().parent / sib.name)
    shutil.rmtree(tmp, ignore_errors=True)
    if os_name() != "windows":
        uv_exe().chmod(0o755)


def step_aider() -> None:
    uv = str(uv_exe())
    _set("aider", stage="Installing", message="Getting Python 3.12 (private copy)")
    _run("aider", [uv, "python", "install", "3.12"])
    _set("aider", stage="Installing", message=f"Installing Aider {AIDER_VERSION}")
    _run("aider", [uv, "tool", "install", "--force", "--python", "3.12", f"aider-chat=={AIDER_VERSION}"])
    _set("aider", stage="Installing", message=f"Installing pytest {PYTEST_VERSION}")
    _run("aider", [uv, "venv", "--allow-existing", "--python", "3.12", str(test_venv())])
    _run("aider", [uv, "pip", "install", "--python", str(venv_python(test_venv())), f"pytest=={PYTEST_VERSION}"])
    _run("aider", [str(tools() / "bin" / exe("aider")), "--version"], timeout=180)


def step_ollama() -> None:
    name, sha, size = OLLAMA_ASSETS[os_name()]
    if os_name() == "linux" and arch() != "x86_64":
        raise RuntimeError("only x86_64 Linux is pinned")
    url = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}/{name}"
    arc = download("ollama", url, data_dir() / "downloads" / name, sha, size)
    _set("ollama", stage="Installing", message="Unpacking Ollama")
    dest = tools() / "ollama"
    shutil.rmtree(dest, ignore_errors=True)
    _extract(arc, dest)
    if not ollama_exe().is_file():
        raise RuntimeError("Ollama unpacked but its program was not found")
    arc.unlink(missing_ok=True)  # 1.6 GB; the unpacked copy is what runs


def _ollama_base() -> str:
    return (os.environ.get("OLLAMA_API_BASE") or "http://127.0.0.1:11434").rstrip("/")


def _ollama_tags() -> list[str]:
    try:
        with urllib.request.urlopen(_ollama_base() + "/api/tags", timeout=2) as r:
            return [m.get("name", "") for m in json.load(r).get("models", [])]
    except Exception:
        return []


def ensure_ollama() -> bool:
    """Start our own `ollama serve` if nothing answers on 11434. Returns True when Ollama answers."""
    global _ollama_proc
    try:
        urllib.request.urlopen(_ollama_base() + "/api/tags", timeout=2).close()
        return True
    except Exception:
        pass
    if not ollama_exe().is_file():
        return False
    log = open(data_dir() / "logs" / "ollama.log", "ab")
    _ollama_proc = subprocess.Popen([str(ollama_exe()), "serve"], stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                    creationflags=NO_WINDOW, env=os.environ.copy())
    for _ in range(60):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(_ollama_base() + "/api/tags", timeout=2).close()
            return True
        except Exception:
            continue
    return False


def stop_ollama() -> None:
    if _ollama_proc and _ollama_proc.poll() is None:
        _ollama_proc.terminate()


def step_granite() -> None:
    if not ensure_ollama():
        raise RuntimeError("Ollama did not start; see logs/ollama.log")
    req = urllib.request.Request(_ollama_base() + "/api/pull", data=json.dumps({"model": GRANITE_MODEL}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        for raw in r:
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            if ev.get("error"):
                raise RuntimeError(ev["error"])
            if ev.get("total"):
                _set("granite", stage="Downloading", done=ev.get("completed", 0), total=ev["total"],
                     message=f"{GRANITE_MODEL}: {ev.get('status', '')}")
            else:
                _set("granite", stage="Installing", message=str(ev.get("status", ""))[:160])


def _gpu_vendor() -> str:
    try:
        import gpu_detect
        if gpu_detect.nvidia_smi().get("gpus"):
            return "nvidia"
    except Exception:
        pass
    return "other"


def step_comfyui() -> None:
    uv = str(uv_exe())
    url = f"https://github.com/Comfy-Org/ComfyUI/archive/refs/tags/v{COMFYUI_VERSION}.zip"
    arc = download("comfyui", url, data_dir() / "downloads" / f"ComfyUI-{COMFYUI_VERSION}.zip")
    _set("comfyui", stage="Installing", message="Unpacking ComfyUI")
    tmp = tools() / "comfy-extract"
    shutil.rmtree(tmp, ignore_errors=True)
    _extract(arc, tmp)
    src = next(tmp.iterdir())
    dest = tools() / "ComfyUI"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(src), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)
    venv = tools() / "comfyui-venv"
    _run("comfyui", [uv, "venv", "--allow-existing", "--python", "3.12", str(venv)])
    py = str(venv_python(venv))
    torch = [uv, "pip", "install", "--python", py, "torch", "torchvision", "torchaudio"]
    if os_name() != "mac":
        # NVIDIA gets CUDA wheels; Radeon/Intel/none get CPU wheels (no admin, no driver installs).
        torch += ["--index-url", "https://download.pytorch.org/whl/cu128" if _gpu_vendor() == "nvidia"
                  else "https://download.pytorch.org/whl/cpu"]
    _set("comfyui", stage="Installing", message="Installing PyTorch")
    _run("comfyui", torch, timeout=7200)
    _set("comfyui", stage="Installing", message="Installing ComfyUI requirements")
    _run("comfyui", [uv, "pip", "install", "--python", py, "-r", str(dest / "requirements.txt")], timeout=3600)


RUNNERS = {"uv": step_uv, "aider": step_aider, "ollama": step_ollama, "granite": step_granite, "comfyui": step_comfyui}


def _worker(step: str) -> None:
    try:
        for dep in DEPENDS.get(step, []):
            if not detect(dep):
                _set(step, stage="Waiting", message=f"Installing {dep} first")
                _set(dep, stage="Waiting", message="Starting", error="")
                RUNNERS[dep]()
                _set(dep, stage="Ready", message="Ready", error="")
        _set(step, stage="Downloading", message="Starting", error="", done=0, total=0)
        RUNNERS[step]()
        _set(step, stage="Ready", message="Ready", error="")
    except Exception as exc:  # shown in the UI; never contains the xAI key
        _log(step, f"FAILED: {exc!r}")
        _set(step, stage="Failed", error=str(exc)[:300], message="Failed")
    finally:
        _running.pop(step, None)


def start(step: str) -> dict:
    if step not in RUNNERS:
        return {"ok": False, "error": f"unknown step {step}"}
    with _lock:
        t = _running.get(step)
        if t and t.is_alive():
            return {"ok": True, "already_running": True}
        t = threading.Thread(target=_worker, args=(step,), daemon=True, name=f"setup-{step}")
        _running[step] = t
    _set(step, stage="Waiting", message="Starting", error="")
    t.start()
    return {"ok": True, "started": step}
