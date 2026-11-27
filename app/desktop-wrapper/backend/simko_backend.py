#!/usr/bin/env python3
"""Simko SI desktop backend (the Tauri sidecar). One process: local UI server + mission server, loopback only.

Prints one line `SIMKOSI_READY {"port": N, ...}` on stdout when the UI is reachable, and writes the same to
<data>/runtime.json. Exits when stdin closes (the desktop window went away) so nothing is left running.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

VERSION = "0.2.0"
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "app"
sys.path[:0] = [str(BASE / "podcoder"), str(BASE / "local")]

if os.name == "nt":
    # Console tools (nvidia-smi, powershell, uv, ollama) must not flash a window from the desktop app.
    import subprocess as _sp
    _orig_init = _sp.Popen.__init__

    def _quiet_init(self, *a, **kw):
        if not kw.get("creationflags"):
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        _orig_init(self, *a, **kw)
    _sp.Popen.__init__ = _quiet_init

import setup_steps  # noqa: E402

setup_steps.configure_env()
DATA = setup_steps.data_dir()
os.environ.setdefault("SIMKOSI_VERSION", VERSION)
os.environ.setdefault("PODCODER_ROOT", str(DATA / "mission"))
os.environ["PODCODER_HOST"] = "127.0.0.1"
os.environ["PODCODER_GALLERY_LOCAL"] = os.environ.get("PODCODER_GALLERY_LOCAL", "1")


def _log_setup() -> None:
    import logging.handlers
    logdir = DATA / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(logdir / "simko.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")

    class Tee:
        def __init__(self, stream):
            self.stream = stream

        def write(self, s):
            if s and s.strip():
                try:
                    import xai_client
                    s_clean = xai_client.redact(s)
                except Exception:
                    s_clean = s
                handler.emit(logging.makeLogRecord({"msg": s_clean.rstrip(), "levelno": 20, "levelname": "INFO"}))
            return len(s or "")

        def flush(self):
            pass
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    sys.stderr = Tee(sys.stderr)
    global _stdout
    _stdout = sys.stdout
    sys.stdout = Tee(sys.stdout)


_stdout = sys.stdout


def _lock() -> object | None:
    """One backend per user. Returns the open lock file or None if another backend holds it."""
    f = open(DATA / "backend.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def _ping(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/simkosi/ping", timeout=2) as r:
            return json.load(r).get("id") == "simkosi-local"
    except Exception:
        return False


def _announce(info: dict) -> None:
    (DATA / "runtime.json").write_text(json.dumps(info), encoding="utf-8")
    _stdout.write("SIMKOSI_READY " + json.dumps(info) + "\n")
    _stdout.flush()


def _make(handler, preferred: int):
    from http.server import ThreadingHTTPServer

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = os.name != "nt"  # on Windows SO_REUSEADDR would let us steal a busy port

        def server_bind(self):
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()
    try:
        return Server(("127.0.0.1", preferred), handler)
    except OSError:
        return Server(("127.0.0.1", 0), handler)  # 8788 busy (another app): any free port


def _watch_parent() -> None:
    """Exit when the desktop shell closes our stdin (normal quit or crash)."""
    if os.environ.get("SIMKOSI_NO_STDIN_WATCH") == "1":
        return
    try:
        while sys.stdin and sys.stdin.read(1):
            pass
    except Exception:
        pass
    setup_steps.stop_ollama()
    os._exit(0)


def main() -> int:
    if "--version" in sys.argv:
        print(VERSION)
        return 0
    if "--selftest" in sys.argv:
        # Import every app module from the bundle; proves the frozen build collected what they need.
        import importlib
        bad = {}
        names = sorted(p.stem for p in (BASE / "podcoder").glob("*.py")) + ["server"]
        for name in names:
            try:
                importlib.import_module(name)
            except Exception as exc:
                bad[name] = repr(exc)[:200]
        print(json.dumps({"modules": len(names), "failed": bad}))
        return 1 if bad else 0
    lock = _lock()
    if lock is None:
        try:
            info = json.loads((DATA / "runtime.json").read_text(encoding="utf-8"))
            if _ping(int(info["port"])):
                _announce({**info, "reused": True})
                return 0
        except Exception:
            pass
        time.sleep(2)
        lock = _lock()
        if lock is None:
            sys.stderr.write("Simko SI backend is already running and not answering.\n")
            return 3
    _log_setup()
    import mission_server
    mission_server.INBOX.mkdir(parents=True, exist_ok=True)
    mission_server.STATUS.mkdir(parents=True, exist_ok=True)
    mission = _make(mission_server.Handler, 0)
    mport = mission.server_address[1]
    os.environ["PODCODER_REMOTE"] = f"http://127.0.0.1:{mport}"
    threading.Thread(target=mission.serve_forever, daemon=True, name="mission").start()

    import server  # local UI server; reads PODCODER_REMOTE at import
    server.app_state_dir().mkdir(parents=True, exist_ok=True)
    try:
        server._local_runtime(server.app_state_dir())
    except Exception as exc:
        print(f"local runtime skipped: {exc}")
    want = int(os.environ.get("SIMKOSI_PORT") or 8788)
    import feature_defaults
    feature_defaults.apply()
    import scheduler
    stop_routines = scheduler.start_background(server.app_state_dir())
    ui = _make(server.H, want)
    port = ui.server_address[1]
    print(f"Simko SI {VERSION} UI on 127.0.0.1:{port}, mission server 127.0.0.1:{mport}, data {DATA}")
    threading.Thread(target=_watch_parent, daemon=True, name="parent-watch").start()
    # Show the setup screen until the xAI key is saved and the coding tools are in.
    try:
        import xai_client
        first_run = not (xai_client.api_key() and setup_steps.detect("aider"))
    except Exception:
        first_run = True
    _announce({"port": port, "pid": os.getpid(), "version": VERSION, "mission_port": mport,
               "url": f"http://127.0.0.1:{port}/" + ("setup" if first_run else ""), "data_dir": str(DATA)})
    try:
        ui.serve_forever()
    finally:
        stop_routines.set()
        setup_steps.stop_ollama()
    return 0


if __name__ == "__main__":
    sys.exit(main())
