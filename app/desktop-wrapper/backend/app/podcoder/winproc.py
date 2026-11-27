#!/usr/bin/env python3
"""Hardened subprocess runner for the desktop app (Windows field test, Nov 17 2026).

On Windows, the frozen backend's child processes inherited its stdin pipe and console state.
`git init -q` (the Git for Windows cmd shim) hung forever that way, and subprocess.run's timeout
never fired because the pipes stayed open. Every child the coding loop starts now goes through run():
- stdin=DEVNULL unless the caller passes input/stdin
- no console window (CREATE_NO_WINDOW) in its own process group
- GIT_TERMINAL_PROMPT=0 / GCM_INTERACTIVE=never so git never waits on a prompt
- PyInstaller's _MEI paths are stripped from PATH so children don't load the bundled DLLs
- the app's own tools (tools/bin, private git) are on PATH, and argv[0] resolves to an absolute path
- a real wall-clock timeout that kills the whole process tree, then raises TimeoutExpired
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


import ctypes
import threading
from contextlib import contextmanager

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

_awake_lock = threading.Lock()
_awake_count = 0
_awake_stop = threading.Event()
_awake_thread: threading.Thread | None = None


def _set_execution_state(flags: int) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
    except Exception:
        pass


def _awake_pulse() -> None:
    while not _awake_stop.wait(20):
        _set_execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def acquire_awake() -> None:
    """Keep the machine from sleeping for the life of a Simko SI job (Modern Standby too)."""
    global _awake_count, _awake_thread
    with _awake_lock:
        _awake_count += 1
        _set_execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        if _awake_thread is None or not _awake_thread.is_alive():
            _awake_stop.clear()
            _awake_thread = threading.Thread(target=_awake_pulse, name="simko-stay-awake", daemon=True)
            _awake_thread.start()


def release_awake() -> None:
    global _awake_count, _awake_thread
    with _awake_lock:
        _awake_count = max(0, _awake_count - 1)
        if _awake_count == 0:
            _awake_stop.set()
            _awake_thread = None
            _set_execution_state(ES_CONTINUOUS)


@contextmanager
def stay_awake():
    acquire_awake()
    try:
        yield
    finally:
        release_awake()


def physical_cores() -> int:
    """Physical CPU cores (not SMT threads). Falls back to os.cpu_count()."""
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "NumberOfCores", "/value"],
                stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
            cores = [int(line.split("=", 1)[1].strip()) for line in out.splitlines()
                     if line.startswith("NumberOfCores=") and line.split("=", 1)[1].strip().isdigit()]
            if cores:
                return max(1, sum(cores))
        except Exception:
            pass
    return max(1, int(os.cpu_count() or 4))


def kill_ollama_runners() -> None:
    """Abort in-flight Granite decode: taskkill /T /F the runner children, not `ollama serve`."""
    if os.name != "nt":
        return
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", "name='ollama.exe'", "get", "ProcessId,CommandLine", "/format:csv"],
            stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        out = ""
    pids: list[int] = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("node,") or "ollama" not in line.lower():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        cmd = ",".join(parts[1:-1]).lower()
        if "serve" in cmd and "runner" not in cmd:
            continue
        if "runner" in cmd or "serve" not in cmd:
            pids.append(pid)
    # Also llama-server style helpers if present
    try:
        extra = subprocess.check_output(
            ["wmic", "process", "where",
             "name='ollama_llama_server.exe' or name='llama-server.exe'",
             "get", "ProcessId", "/format:csv"],
            stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
        for raw in extra.splitlines():
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if parts and parts[-1].isdigit():
                pids.append(int(parts[-1]))
    except Exception:
        pass
    for pid in dict.fromkeys(pids):
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW, timeout=15,
            )
        except Exception:
            pass



def _data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "SimkoSI"
    return Path.home() / ".local" / "share" / "simko-si"


def tool_dirs() -> list[str]:
    tools = _data_dir() / "tools"
    dirs = [tools / "bin", tools / "git" / "cmd", tools / "git" / "mingw64" / "bin", tools / "ollama"]
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        dirs += [Path(pf) / "Git" / "cmd", Path(os.environ.get("LOCALAPPDATA") or "") / "Programs" / "Git" / "cmd"]
    return [str(d) for d in dirs if d.is_dir()]


def child_env(base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    mei = getattr(sys, "_MEIPASS", "") or ""
    raw = env.get("PATH") or env.get("Path") or ""
    parts = [p for p in raw.split(os.pathsep) if p and not (mei and p.startswith(mei)) and "_MEI" not in p]
    for d in reversed(tool_dirs()):
        if d not in parts:
            parts.insert(0, d)
    env.pop("Path", None)
    env["PATH"] = os.pathsep.join(parts)
    for k in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL", "TCL_LIBRARY", "TK_LIBRARY"):
        env.pop(k, None)
    if mei and str(env.get("SSL_CERT_FILE", "")).startswith(mei):
        env.pop("SSL_CERT_FILE", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env.setdefault("GIT_AUTHOR_NAME", "Simko SI")
    env.setdefault("GIT_AUTHOR_EMAIL", "simko-si@localhost")
    env.setdefault("GIT_COMMITTER_NAME", "Simko SI")
    env.setdefault("GIT_COMMITTER_EMAIL", "simko-si@localhost")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def resolve(cmd: str, env: dict) -> str:
    if os.path.isabs(cmd) or os.sep in cmd or (os.altsep and os.altsep in cmd):
        return cmd
    return shutil.which(cmd, path=env.get("PATH")) or cmd


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, timeout=15)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run(argv, *, cwd=None, capture_output=False, text=False, timeout=None, check=False, env=None,
        stdin=None, input=None, stdout=None, stderr=None, encoding=None, errors=None, shell=False, **_ignored):
    """Drop-in for subprocess.run with the rules above."""
    env = child_env(env)
    if isinstance(argv, (list, tuple)) and argv and not shell:
        argv = [resolve(str(argv[0]), env), *[str(a) for a in argv[1:]]]
    if capture_output:
        stdout = stderr = subprocess.PIPE
    if input is not None:
        stdin = subprocess.PIPE
    elif stdin is None:
        stdin = subprocess.DEVNULL
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    if text and encoding is None:
        encoding, errors = "utf-8", errors or "replace"
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr, shell=shell,
                            text=text, encoding=encoding, errors=errors, **kw)
    try:
        out, err = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = None, None
        raise subprocess.TimeoutExpired(argv, timeout, output=out, stderr=err)
    except BaseException:
        kill_tree(proc)
        raise
    done = subprocess.CompletedProcess(argv, proc.returncode, out, err)
    if check:
        done.check_returncode()
    return done
