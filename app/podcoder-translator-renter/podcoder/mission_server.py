#!/usr/bin/env python3
"""Podcoder HTTP: translator UI, /api/mission, and post-Confirm-Rent install.

Does not rent or auto-destroy. Former Utah 58092881 was shut by Joseph. Chat/calc stay locked
until install-on-pod-q8.sh records a live smoke pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gallery
import install_hook
import product_api

ROOT = Path(os.environ.get("PODCODER_ROOT", "/opt/podcoder"))
INBOX = ROOT / "missions" / "inbox"
STATUS = ROOT / "status"
TRANSLATOR = Path("/root/translator/translator.html")
PORT = int(os.environ.get("PODCODER_PORT", "8787"))
HOST = os.environ.get("PODCODER_HOST", "0.0.0.0")


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[http] {self.address_string()} {fmt % args}", flush=True)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, obj):
        body = json.dumps(obj, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, code: int, data: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _mission_status_path(self, mid: str):
        p = ROOT / "missions" / mid / "mission-status.json"
        alt = STATUS / f"{mid}-status.json"
        if p.is_file():
            return p
        if alt.is_file():
            return alt
        return None

    def _state(self):
        env = os.environ.get("PODCODER_STATE_DIR")
        return Path(env) if env else (ROOT / "status")

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception as exc:
            return None, exc
        if not isinstance(body, dict):
            return None, ValueError("json object required")
        return body, None

    def _product(self, method: str, body: dict | None = None) -> bool:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if method == "GET" and body is None:
            import core_api
            if core_api.handles(path):
                from urllib.parse import parse_qs
                body = {k: v[-1] for k, v in parse_qs(urlparse(self.path).query).items()}
        hit = product_api.try_handle(method, path, body, self._state())
        if hit is None:
            return False
        self._json(hit[0], hit[1])
        return True

    def do_DELETE(self):
        if self._product("DELETE", {}):
            return
        self._json(403, install_hook.destroy_refusal())

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path.startswith("/api/gallery/media/"):
            found = gallery.resolve_media(self._state(), path.split("/api/gallery/media/", 1)[-1])
            if not found:
                self._json(404, {"ok": False, "error": "not in gallery", "vast_calls": 0, "destroyed": False})
                return
            file_path, ctype = found
            self._bytes(200, file_path.read_bytes(), ctype)
            return
        if path == "/api/health":
            self._json(200, {"ok": True, "service": "mission_server", "destroyed": False})
            return
        if path == "/api/install/status":
            self._json(200, install_hook.public_status(self._state()))
            return
        if path == "/api/voice/speak":
            import voice
            voice.serve_speech(self, urlparse(self.path).query, self._state(),
                               extra_headers=[("Access-Control-Allow-Origin", "*")])
            return
        if self._product("GET"):
            return
        if path in ("/", "/translator", "/translator.html", "/ui"):
            if TRANSLATOR.is_file():
                self._bytes(200, TRANSLATOR.read_bytes(), "text/html; charset=utf-8")
            else:
                self._json(404, {"error": "translator.html missing"})
            return
        if path in ("/api/status", "/api/mission-status", "/status/latest"):
            latest = STATUS / "latest-status.json"
            if latest.is_file():
                self._bytes(200, latest.read_bytes(), "application/json")
            else:
                self._json(404, {"error": "no status yet"})
            return
        # Aliases:
        #   /api/mission/<id>/status
        #   /api/mission/status/<id>
        #   /status/<id>
        parts = [p for p in path.split("/") if p]
        mid = None
        if parts[:2] == ["api", "mission"] and len(parts) >= 3:
            if parts[2] == "status" and len(parts) >= 4:
                mid = parts[3]
            elif len(parts) >= 4 and parts[3] == "status":
                mid = parts[2]
            elif len(parts) == 3:
                mid = parts[2]
        elif parts[:1] == ["status"] and len(parts) >= 2:
            mid = parts[1]
        if mid:
            target = self._mission_status_path(mid)
            if target is not None:
                self._bytes(200, target.read_bytes(), "application/json")
                return
            self._json(404, {"error": f"no status for {mid}"})
            return
        if path.startswith("/files/status/"):
            name = path.split("/")[-1]
            f = STATUS / name
            if f.is_file():
                self._bytes(200, f.read_bytes(), "application/json")
                return
        self._json(404, {"error": "not found", "path": path})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        body, err = self._read_body()
        if err:
            self._json(400, {"ok": False, "error": f"bad json: {err}", "destroyed": False, "vast_calls": 0})
            return
        if path == "/api/install/comfyui":
            try:
                result = install_hook.handle_comfy_install(
                    body, self._state(), src_dir=ROOT, allow_local=True
                )
            except install_hook.HookError as exc:
                self._json(exc.code, exc.payload)
                return
            self._json(int(result.pop("http", 200)), result)
            return
        if path == "/api/download":
            try:
                result = install_hook.handle_download(body, self._state(), src_dir=ROOT)
            except install_hook.HookError as exc:
                self._json(exc.code, exc.payload)
                return
            self._json(int(result.pop("http", 200)), result)
            return
        if path in ("/api/rent", "/api/install"):
            try:
                if path == "/api/rent":
                    result = install_hook.handle_rent(
                        body, self._state(), src_dir=ROOT, allow_local=False
                    )
                else:
                    result = install_hook.handle_install(
                        body, self._state(), src_dir=ROOT, allow_local=True
                    )
            except install_hook.HookError as exc:
                self._json(exc.code, exc.payload)
                return
            self._json(int(result.pop("http", 200)), result)
            return
        if self._product("POST", body):
            return
        if path != "/api/mission":
            self._json(404, {"error": "not found", "destroyed": False})
            return
        blocked = product_api.chat_block(self._state())
        if blocked:
            self._json(409, blocked)
            return
        mission = body
        mid = mission.get("id") or f"mission-{int(time.time())}"
        mission["id"] = mid
        mission.setdefault("template", "translator-everyday-typea-master-batch.json")
        mission.setdefault("seed", str(ROOT / "seeds" / "translator.html"))
        mission.setdefault("allowRent", False)
        mission.setdefault("allowAider", True)
        try:
            import llm_router

            defaults = llm_router.mission_defaults()
        except Exception:
            defaults = {"model": "granite4.2:8b-q8_0", "llm_backend": "granite", "llm_order": ["grok", "granite", "canned"]}
        if defaults.get("llm_backend") == "grok":
            mission["model"] = defaults["model"]
        else:
            mission.setdefault("model", defaults.get("model") or "granite4.2:8b-q8_0")
        mission["llm_backend"] = defaults.get("llm_backend") or "granite"
        mission["llm_order"] = defaults.get("llm_order") or ["grok", "granite", "canned"]
        mission.setdefault("graniteFirst", True)
        mission.setdefault("minRawFailsBeforeAider", 2)
        mission.setdefault("maxSurgicalRounds", 1)
        mission.setdefault("neverLeadWithAider", True)
        mission.setdefault("workspace", str(ROOT / "missions" / mid / "workspace"))
        if mission.get("dryVerify") is not True:
            mission.setdefault("force", True)
            mission.setdefault("oneShot", True)
            mission.setdefault("batchId", "batch-adhoc")
        INBOX.mkdir(parents=True, exist_ok=True)
        inbox_path = INBOX / f"{mid}.json"
        inbox_path.write_text(json.dumps(mission, indent=2) + "\n", encoding="utf-8")
        mdir = ROOT / "missions" / mid
        mdir.mkdir(parents=True, exist_ok=True)
        running = {
            "id": mid,
            "status": "running",
            "mode": "dry-verify" if mission.get("dryVerify") else "one-shot",
            "everyday": mission.get("everyday"),
            "model": mission.get("model"),
            "llm_backend": mission.get("llm_backend"),
            "llm_order": mission.get("llm_order"),
            "batches": [],
            "vast_calls": 0,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        for p in (mdir / "mission-status.json", STATUS / "latest-status.json", STATUS / f"{mid}-status.json"):
            STATUS.mkdir(parents=True, exist_ok=True)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(running, indent=2) + "\n")

        def _run():
            cmd = [
                "python3",
                str(ROOT / "pod_autocode_runner.py"),
                "--mission",
                str(inbox_path),
            ]
            if mission.get("dryVerify"):
                cmd.append("--dry-verify")
            try:
                subprocess.run(cmd, cwd=str(ROOT), timeout=int(mission.get("maxSeconds") or 600))
            except Exception as e:
                fail = {
                    "id": mid,
                    "status": "fail",
                    "error": str(e),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "batches": [],
                    "vast_calls": 0,
                }
                (mdir / "mission-status.json").write_text(json.dumps(fail, indent=2) + "\n")
                (STATUS / "latest-status.json").write_text(json.dumps(fail, indent=2) + "\n")
                (STATUS / f"{mid}-status.json").write_text(json.dumps(fail, indent=2) + "\n")

        threading.Thread(target=_run, daemon=True).start()
        status_url = f"/api/mission/status/{mid}"
        self._json(
            202,
            {
                "ok": True,
                "id": mid,
                "inbox": str(inbox_path),
                "statusUrl": status_url,
                "status_url": status_url,
                "status_url_alt": f"/api/mission/{mid}/status",
                "latest_url": "/api/status",
            },
        )


def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    STATUS.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"mission_server listening on {HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
