#!/usr/bin/env python3
"""Local workbench: translator UI on :8788.

/api/rent and /api/install stay on the laptop so Confirm Rent can scp
install-on-pod-q8.sh to the new instance. Other /api/* proxy to the pod.
Never rents or destroys GPUs. Chat/calc proxies stay closed until smoke passes.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
PODCODER = HERE.parent / "podcoder"
sys.path.insert(0, str(PODCODER))
import gallery
import hardware_probe
import install_hook
import product_api

PORT = int(os.environ.get("LOCAL_PORT", "8788"))
REMOTE = os.environ.get("PODCODER_REMOTE", "http://127.0.0.1:8787").rstrip("/")
CODING_PREFIXES = ("/api/chat", "/api/mission", "/api/translate", "/api/generate")
CAPACITOR_ORIGINS = {
    "capacitor://localhost",
    "ionic://localhost",
    "http://localhost",
    "https://localhost",
}
STATIC_FILES = {
    "/desktop-lab.html": "text/html; charset=utf-8",
    "/simco-client.js": "text/javascript; charset=utf-8",
    "/platform-preview.js": "text/javascript; charset=utf-8",
    "/simco-voice.js": "text/javascript; charset=utf-8",
    "/coral-reef-bg.jpg": "image/jpeg",
    "/coral-reef-bg-sm.jpg": "image/jpeg",
}
THEME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".mp4": "video/mp4",
    ".md": "text/markdown; charset=utf-8",
}


def allow_origin(origin: str) -> bool:
    """Phone-app origins, localhost, and an explicit env allowlist. Not the open web."""
    text = (origin or "").strip()
    if not text or text.lower() == "null":
        return False
    if text in CAPACITOR_ORIGINS:
        return True
    extra = {item.strip() for item in (os.environ.get("PODCODER_CORS_ORIGINS") or "").split(",") if item.strip()}
    if text in extra or "*" in extra:
        return True
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme in {"http", "https"} and host in {"localhost", "127.0.0.1"}:
        return True
    return False


def app_state_dir() -> Path:
    from platform_paths import data_dir
    return data_dir()


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[local] {self.address_string()} {fmt % args}", flush=True)

    def end_headers(self):
        if not getattr(self, "_cors_sent", False):
            self._cors_sent = True
            origin = ""
            try:
                origin = self.headers.get("Origin") or ""
            except Exception:
                origin = ""
            if allow_origin(origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.send_header("Access-Control-Max-Age", "600")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, code: int, obj, cookie: str | None = None):
        body = json.dumps(obj, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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

    def _proxy(self, body=None):
        req = urllib.request.Request(
            REMOTE + self.path,
            data=body,
            method=self.command,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                code, data = response.status, response.read()
        except urllib.error.HTTPError as exc:
            code, data = exc.code, exc.read()
        except Exception as exc:
            code, data = 502, f'{{"error":"remote unreachable: {exc}"}}'.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _product(self, method: str, body: dict | None = None) -> bool:
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path.startswith("/api/platform/"):
            import platform_api
            from http.cookies import SimpleCookie
            host = urlparse("http://" + self.headers.get("Host", "")).hostname
            if host not in {"127.0.0.1", "localhost", "::1"}:
                self._json(403, {"ok": False, "error": "loopback host required"})
                return True
            origin = self.headers.get("Origin", "")
            if method != "GET":
                # Prevent untrusted websites reaching the loopback API (CSRF).
                parsed_origin = urlparse(origin) if origin else None
                if origin and (not parsed_origin or parsed_origin.netloc != self.headers.get("Host") or parsed_origin.scheme != "http"):
                    self._json(403, {"ok": False, "error": "same-origin request required"})
                    return True
                if "application/json" not in self.headers.get("Content-Type", ""):
                    self._json(415, {"ok": False, "error": "JSON required"})
                    return True
            data = dict(body or {})
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            if "podcoder_session" in cookie:
                data["token"] = cookie["podcoder_session"].value
            hit = platform_api.handle(method, path, data, app_state_dir())
        else:
            hit = product_api.try_handle(method, path, body, app_state_dir())
        if hit is None:
            return False
        self._json(hit[0], hit[1])
        return True

    def do_DELETE(self):
        if self._product("DELETE", {}):
            return
        self._json(403, install_hook.destroy_refusal())

    def _proxy_raw(self) -> bool:
        try:
            req = urllib.request.Request(REMOTE + self.path, method="GET")
            with urllib.request.urlopen(req, timeout=8) as response:
                data = response.read()
                ctype = response.headers.get("Content-Type") or "application/octet-stream"
                self.send_response(response.status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return True
        except Exception:
            return False

    def _serve_local_media(self, name: str) -> None:
        found = gallery.resolve_media(app_state_dir(), name)
        if not found:
            self._json(404, {"ok": False, "error": "not in gallery", "vast_calls": 0, "destroyed": False})
            return
        path, ctype = found
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/gallery" or path.startswith("/api/gallery/media/"):
            if os.environ.get("PODCODER_GALLERY_LOCAL") != "1" and self._proxy_raw():
                return
            if path.startswith("/api/gallery/media/"):
                self._serve_local_media(path.split("/api/gallery/media/", 1)[-1])
                return
        if path == "/api/health":
            payload = {"ok": True, "service": "local", "destroyed": False, "vast_calls": 0}
            try:
                import watchdog
                payload.update(watchdog.snapshot(app_state_dir()))
            except Exception:
                pass
            self._json(200, payload)
            return
        if path == "/api/quotes":
            from urllib.parse import parse_qs
            qs = parse_qs(urlparse(self.path).query)
            def one(key):
                return (qs.get(key) or [""])[0]
            hit = product_api.try_handle("GET", path, {"q": one("q"), "speaker": one("speaker"), "category": one("category")}, app_state_dir())
            if hit:
                self._json(hit[0], hit[1])
                return
        if path == "/widgets" or path.startswith("/widgets/"):
            self._widget(path)
            return
        if path == "/api/install/status":
            self._json(200, install_hook.public_status(app_state_dir()))
            return
        if path == "/api/probe":
            code, result = hardware_probe.advise(app_state_dir(), {})
            self._json(code, result)
            return
        if path == "/api/voice/speak":
            import voice
            voice.serve_speech(self, urlparse(self.path).query, app_state_dir())
            return
        if self._product("GET"):
            return
        if path.startswith("/api/"):
            self._proxy()
            return
        if path in STATIC_FILES:
            data = (HERE / path.lstrip("/")).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", STATIC_FILES[path])
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/themes/") or path == "/themes":
            self._theme(path)
            return
        name = "chat.html" if path in ("/", "/chat", "/chat.html", "/turtle", "/turtle.html") else "translator.html"
        data = (HERE / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _theme(self, path: str) -> None:
        rel = path[len("/themes/"):] if path.startswith("/themes/") else ""
        if not rel or rel.startswith("/") or "\\" in rel or ".." in rel.split("/"):
            self._json(400, {"ok": False, "error": "bad path", "vast_calls": 0, "destroyed": False})
            return
        root = (HERE / "themes").resolve()
        file = (root / rel).resolve()
        if file != root and root not in file.parents:
            self._json(400, {"ok": False, "error": "bad path", "vast_calls": 0, "destroyed": False})
            return
        if not file.is_file():
            self._json(404, {"ok": False, "error": "missing theme file", "vast_calls": 0, "destroyed": False})
            return
        ctype = THEME_TYPES.get(file.suffix.lower())
        if not ctype:
            self._json(403, {"ok": False, "error": "theme file type is not served", "vast_calls": 0, "destroyed": False})
            return
        data = file.read_bytes()
        rng = self.headers.get("Range", "") if ctype.startswith("video/") else ""
        if rng.startswith("bytes=") and "," not in rng:
            # Safari and some WebViews only play video when byte ranges work.
            start_s, _sep, end_s = rng[len("bytes="):].partition("-")
            try:
                size = len(data)
                if start_s:
                    start = int(start_s)
                    end = min(int(end_s), size - 1) if end_s else size - 1
                else:
                    start = max(0, size - int(end_s))
                    end = size - 1
                if start > end or start >= size:
                    raise ValueError
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(data)}")
                self.end_headers()
                return
            part = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(part)))
            self.end_headers()
            self.wfile.write(part)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if ctype.startswith("video/"):
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _widget(self, path: str) -> None:
        rel = "demo.html" if path == "/widgets" else path.split("/widgets/", 1)[1]
        if not rel or ".." in rel.split("/"):
            self._json(400, {"ok": False, "error": "bad path", "vast_calls": 0, "destroyed": False})
            return
        root = (HERE / "widgets").resolve()
        file = (root / rel).resolve()
        if file != root and root not in file.parents:
            self._json(400, {"ok": False, "error": "bad path", "vast_calls": 0, "destroyed": False})
            return
        if not file.is_file():
            self._json(404, {"ok": False, "error": "missing widget", "vast_calls": 0, "destroyed": False})
            return
        data = file.read_bytes()
        if file.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif file.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        else:
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        body, err = self._read_body()
        if err:
            self._json(400, {"ok": False, "error": f"bad json: {err}", "destroyed": False, "vast_calls": 0})
            return
        if path == "/api/install/comfyui":
            try:
                result = install_hook.handle_comfy_install(
                    body, app_state_dir(), src_dir=PODCODER, allow_local=False
                )
            except install_hook.HookError as exc:
                self._json(exc.code, exc.payload)
                return
            self._json(int(result.pop("http", 200)), result)
            return
        if path == "/api/probe":
            code, result = hardware_probe.advise(app_state_dir(), body)
            self._json(code, result)
            return
        if path == "/api/auth":
            hit = product_api.try_handle("POST", path, body, app_state_dir())
            result = hit[1] if hit else {"ok": False, "error": "auth unavailable", "vast_calls": 0}
            code = hit[0] if hit else 400
            cookie = None
            token = str(result.get("token") or "") if isinstance(result, dict) else ""
            if token:
                cookie = f"podcoder_session={token}; Path=/; HttpOnly; SameSite=Lax"
            elif str(body.get("op") or "").lower() == "signout":
                cookie = "podcoder_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
            self._json(code, result, cookie=cookie)
            return
        if path == "/api/download":
            try:
                result = install_hook.handle_download(body, app_state_dir(), src_dir=PODCODER)
            except install_hook.HookError as exc:
                self._json(exc.code, exc.payload)
                return
            self._json(int(result.pop("http", 200)), result)
            return
        if path in ("/api/rent", "/api/install"):
            try:
                if path == "/api/rent":
                    result = install_hook.handle_rent(
                        body, app_state_dir(), src_dir=PODCODER, allow_local=False
                    )
                else:
                    result = install_hook.handle_install(
                        body, app_state_dir(), src_dir=PODCODER, allow_local=False
                    )
            except install_hook.HookError as exc:
                self._json(exc.code, exc.payload)
                return
            self._json(int(result.pop("http", 200)), result)
            return
        if self._product("POST", body):
            return
        if path.startswith(CODING_PREFIXES):
            blocked = product_api.chat_block(app_state_dir())
            if blocked:
                self._json(409, blocked)
                return
        self._proxy(json.dumps(body).encode("utf-8"))


def make_server(port: int | None = None):
    return ThreadingHTTPServer(("127.0.0.1", PORT if port is None else port), H)


def main():
    app_state_dir().mkdir(parents=True, exist_ok=True)
    import feature_defaults
    feature_defaults.apply()
    import scheduler
    stop_routines = scheduler.start_background(app_state_dir())
    httpd = make_server(PORT)
    print(f"local workbench http://127.0.0.1:{PORT}/  -> remote {REMOTE}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        stop_routines.set()
        httpd.server_close()


if __name__ == "__main__":
    main()
