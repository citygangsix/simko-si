#!/usr/bin/env python3
"""Grok-first router. Fake HTTP only. No real key and no real xAI call."""
from __future__ import annotations

import io
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import agent_loop
import granite_to_everyday
import hardware_probe
import job_runner
import llm_router
import product_api
import sessions
import setup_flow
import user_settings
import xai_client

ROOT = Path(__file__).resolve().parent
KEY = "test-key-not-secret"
GRANITE_LINE = "Granite says the multiply key is ready."
GROK_LINE = "The multiply key is ready. Try 7 times 8."


class _Resp:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body

    def readline(self):
        if self._body:
            line, _, rest = self._body.partition(b"\n")
            self._body = rest
            return line + (b"\n" if line else b"")
        return b""


def _grok_body(text: str, model: str = "grok-4.3") -> bytes:
    return json.dumps({"model": model, "choices": [{"message": {"role": "assistant", "content": text}}]}).encode()


def _granite_body(text: str) -> bytes:
    return json.dumps({"message": {"role": "assistant", "content": text}}).encode()


def _http_error(status: int, url: str = "https://api.x.ai/v1/chat/completions"):
    return urllib.error.HTTPError(url, status, "nope", hdrs=None, fp=io.BytesIO(b""))


class EnvGuard:
    def __init__(self, **values):
        self.values = values
        self.saved = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *args):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _opener(routes):
    seen = []

    def open_url(request, timeout=None):
        url = request.full_url
        seen.append(url)
        for needle, action in routes:
            if needle in url:
                if isinstance(action, Exception):
                    raise action
                if callable(action):
                    return action(request, timeout)
                status, body = action
                return _Resp(status, body)
        raise urllib.error.URLError("no route")

    open_url.seen = seen
    return open_url


class RouterTests(unittest.TestCase):
    def test_grok_success_monkeypatch(self):
        opener = _opener([("api.x.ai", (200, _grok_body(GROK_LINE)))])
        with EnvGuard(XAI_API_KEY=KEY, XAI_MODEL=None, XAI_BASE_URL=None, XAI_SETTINGS_FILE=None):
            routed = llm_router.complete(text="make multiply show 7 times 8", purpose="chat", opener=opener)
        self.assertEqual(routed["backend"], "grok")
        self.assertEqual(routed["model"], "grok-4.3")
        self.assertIn("multiply", routed["text"].lower())
        self.assertEqual(opener.seen, ["https://api.x.ai/v1/chat/completions"])
        self.assertNotIn(KEY, json.dumps(routed))

    def test_grok_http_errors_fall_back_to_granite(self):
        for status, kind in ((401, "unauthorized"), (429, "rate"), (500, "server"), (503, "server")):
            opener = _opener([
                ("api.x.ai", _http_error(status)),
                ("11434", (200, _granite_body(GRANITE_LINE))),
            ])
            with EnvGuard(XAI_API_KEY=KEY, XAI_MODEL=None, XAI_BASE_URL=None, XAI_SETTINGS_FILE=None):
                routed = llm_router.complete(text="hello", purpose="chat", opener=opener)
            self.assertEqual(routed["backend"], "granite", kind)
            self.assertEqual(routed["text"], GRANITE_LINE)
            self.assertNotIn(KEY, json.dumps(routed))
            self.assertTrue(any("11434" in url for url in opener.seen))

    def test_grok_timeout_and_network_fall_back_to_granite(self):
        for action in (TimeoutError("timed out"), urllib.error.URLError("network down")):
            opener = _opener([
                ("api.x.ai", action),
                ("11434", (200, _granite_body(GRANITE_LINE))),
            ])
            with EnvGuard(XAI_API_KEY=KEY, XAI_MODEL=None, XAI_BASE_URL=None, XAI_SETTINGS_FILE=None):
                routed = llm_router.complete(text="hello", purpose="chat", opener=opener)
            self.assertEqual(routed["backend"], "granite")
            self.assertEqual(routed["text"], GRANITE_LINE)

    def test_no_key_uses_granite_and_skips_xai(self):
        opener = _opener([("11434", (200, _granite_body(GRANITE_LINE)))])
        with EnvGuard(XAI_API_KEY=None, XAI_MODEL=None, XAI_BASE_URL=None, XAI_SETTINGS_FILE=None):
            routed = llm_router.complete(text="hello", purpose="chat", opener=opener)
        self.assertEqual(routed["backend"], "granite")
        self.assertFalse(any("x.ai" in url for url in opener.seen))
        self.assertTrue(any("11434" in url for url in opener.seen))

    def test_both_down_returns_the_canned_line(self):
        opener = _opener([
            ("api.x.ai", urllib.error.URLError("down")),
            ("11434", urllib.error.URLError("down")),
        ])
        with EnvGuard(XAI_API_KEY=KEY, XAI_SETTINGS_FILE=None):
            routed = llm_router.complete(text="hello", purpose="chat", opener=opener)
        self.assertEqual(routed["backend"], "canned")
        self.assertEqual(routed["text"], granite_to_everyday._fail("the reply was empty"))
        self.assertFalse(routed["ok"])
        self.assertNotIn(KEY, json.dumps(routed))

    def test_no_key_and_granite_down_is_canned(self):
        opener = _opener([("11434", urllib.error.URLError("down"))])
        with EnvGuard(XAI_API_KEY=None, XAI_SETTINGS_FILE=None):
            routed = llm_router.complete(text="hello", purpose="session", opener=opener)
        self.assertEqual(routed["backend"], "canned")
        self.assertIn("didn't finish", routed["text"])


class FakeXAIServerTests(unittest.TestCase):
    def test_fake_server_serves_chat(self):
        seen = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                seen["auth"] = self.headers.get("Authorization") or ""
                seen["body"] = json.loads(raw.decode() or "{}")
                payload = _grok_body(GROK_LINE)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with TemporaryDirectory() as tmp:
                state = Path(tmp)
                with EnvGuard(
                    XAI_API_KEY=KEY,
                    XAI_MODEL=None,
                    XAI_BASE_URL=f"http://127.0.0.1:{port}/v1",
                    XAI_SETTINGS_FILE=None,
                ):
                    setup_flow.run(state, {"role": "coding", "probe": {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 200, "gpu": "none", "cpu": "Ryzen"}})
                    code, body = product_api.try_handle(
                        "POST",
                        "/api/simco/turn",
                        {"text": "make multiply show 7 times 8"},
                        state,
                    )
            self.assertEqual(code, 200)
            self.assertEqual(body["backend"], "grok")
            self.assertIn("multiply", body["everyday"].lower())
            self.assertNotIn("<", body["everyday"])
            self.assertEqual(seen["auth"], "Bearer " + KEY)
            self.assertEqual(seen["body"]["model"], "grok-4.3")
            self.assertNotIn(KEY, json.dumps(seen["body"]))
            self.assertNotIn(KEY, json.dumps(body))
            self.assertEqual(body["vast_calls"], 0)
        finally:
            server.shutdown()
            server.server_close()


class FeatureRouteTests(unittest.TestCase):
    def test_sessions_probe_agent_and_aider(self):
        opener = _opener([
            ("api.x.ai", (200, _grok_body("Saved that note."))),
            ("11434", (200, _granite_body("should not run"))),
        ])
        original = urllib.request.urlopen
        urllib.request.urlopen = opener
        try:
            with TemporaryDirectory() as tmp:
                state = Path(tmp)
                with EnvGuard(XAI_API_KEY=KEY, XAI_MODEL="grok-4.3", XAI_BASE_URL=None, XAI_SETTINGS_FILE=None):
                    created = sessions.create_session(state, "joseph", "one")
                    queued = sessions.enqueue(state, "joseph", created["session"]["id"], "hello")
                    self.assertEqual(queued["backend"], "grok")
                    self.assertEqual(queued["model_loads"], 1)
                    stored = sessions.get_session(state, "joseph", created["session"]["id"])
                    self.assertEqual(stored["session"]["messages"][0]["role"], "user")
                    self.assertEqual(stored["session"]["messages"][1]["backend"], "grok")
                    self.assertNotIn(KEY, json.dumps(stored))
                    code, probe = hardware_probe.advise(state, {"compute": "local", "role": "coding", "probe": {"ram_gb": 16, "vram_gb": 0, "disk_free_gb": 80, "gpu": "none"}})
                    self.assertEqual(code, 200)
                    self.assertEqual(probe["backend"], "grok")
                    self.assertEqual(probe["llm"]["order"], ["grok", "granite", "canned"])
                    self.assertTrue(probe["llm"]["key_set"])
                    self.assertEqual(probe["aider"]["model_flag"], "xai/grok-4.3")
                    self.assertNotIn("XAI_API_KEY", probe["aider"]["env"])
                    self.assertNotIn(KEY, json.dumps(probe))
                    launched = hardware_probe.aider_launch("granite4.2:8b-q5_0", "fix the button")
                    self.assertEqual(launched["model"], "xai/grok-4.3")
                    self.assertIn("--model", launched["argv"])
                    self.assertNotIn(KEY, json.dumps(launched))
                    done = agent_loop.run(state, "job-1", {"task": "say hello", "compute": "local", "max_steps": 1})
                    self.assertEqual(done["backend"], "grok")
                    self.assertEqual(done["model"], "grok-4.3")
                    self.assertNotIn(KEY, json.dumps(done))
                    argv = llm_router.aider_command("/root/run-aider-granite.sh", ["--yes-always"])
                    self.assertEqual(argv[:4], ["/root/run-aider-granite.sh", "--model", "xai/grok-4.3", "--yes-always"])
                    self.assertNotIn(KEY, json.dumps(argv))
            with EnvGuard(XAI_API_KEY=None, XAI_SETTINGS_FILE=None):
                plain = llm_router.aider_command("/root/run-aider-granite.sh", ["--yes-always"])
                self.assertEqual(plain, ["/root/run-aider-granite.sh", "--yes-always"])
        finally:
            urllib.request.urlopen = original

    def test_agent_plan_keeps_the_granite_name_without_a_key(self):
        with TemporaryDirectory() as tmp:
            state = Path(tmp)
            workspace = state / "workspace"
            workspace.mkdir()
            with EnvGuard(XAI_API_KEY=None, XAI_SETTINGS_FILE=None):
                created = job_runner.create_job(state, "ada", "agent", {
                    "compute": "local",
                    "max_steps": 1,
                    "plan": [{"tool": "shell", "args": {"cmd": "echo hello"}}],
                })
                done = job_runner.execute(state, created["id"], workspace)
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["result"]["model"], "granite4.2:8b-q5_0")
        self.assertEqual(done["result"]["backend"], "granite")

    def test_user_settings_model_and_external_key_file(self):
        with TemporaryDirectory() as tmp:
            state = Path(tmp)
            with EnvGuard(XAI_API_KEY=None, XAI_MODEL=None, XAI_SETTINGS_FILE=None):
                saved = user_settings.set_llm_model(state, "ada", "grok-4.7")
                self.assertTrue(saved["ok"])
                self.assertEqual(llm_router.model_id(state=state, user="ada"), "grok-4.7")
                rejected = user_settings.set_llm_model(state, "ada", KEY)
                self.assertFalse(rejected["ok"])
                self.assertNotIn(KEY, json.dumps(rejected))
            with EnvGuard(XAI_API_KEY=None, XAI_MODEL="grok-4.3", XAI_SETTINGS_FILE=None):
                self.assertEqual(llm_router.model_id(state=state, user="ada"), "grok-4.3")
            outside = Path(tmp) / "xai.env"
            # TemporaryDirectory may live under /tmp, which is outside the repo.
            outside.write_text("XAI_API_KEY=file-key-not-secret\nXAI_MODEL=ignored\n", encoding="utf-8")
            inside = ROOT / "xai-test.env"
            inside.write_text("XAI_API_KEY=repo-key-should-be-ignored\n", encoding="utf-8")
            try:
                with EnvGuard(XAI_API_KEY=None, XAI_SETTINGS_FILE=str(outside)):
                    self.assertEqual(xai_client.api_key(), "file-key-not-secret")
                    self.assertNotIn("file-key-not-secret", json.dumps(llm_router.public_status()))
                with EnvGuard(XAI_API_KEY=None, XAI_SETTINGS_FILE=str(inside)):
                    self.assertEqual(xai_client.api_key(), "")
            finally:
                inside.unlink(missing_ok=True)

    def test_coding_runner_prefers_grok_then_granite(self):
        import pod_autocode_runner

        calls = []

        def open_url(request, timeout=None):
            calls.append(request.full_url)
            if "api.x.ai" in request.full_url:
                raise urllib.error.URLError("grok down")
            body = json.dumps({"message": {"content": "<!DOCTYPE html><html></html>"}, "done": True}).encode()
            return _Resp(200, body)

        original = urllib.request.urlopen
        urllib.request.urlopen = open_url
        try:
            with EnvGuard(XAI_API_KEY=KEY, XAI_MODEL=None, XAI_BASE_URL=None, XAI_SETTINGS_FILE=None):
                text, meta = pod_autocode_runner.granite_chat(
                    {"model": "granite4.2:8b-q8_0", "messages": [{"role": "user", "content": "edit the page"}]},
                    abort_s=1,
                )
            self.assertIn("<!DOCTYPE html>", text)
            self.assertEqual(meta["backend"], "granite")
            self.assertTrue(any("api.x.ai" in url for url in calls))
            self.assertTrue(any("11434" in url for url in calls))
            with EnvGuard(XAI_API_KEY=KEY, XAI_SETTINGS_FILE=None):
                urllib.request.urlopen = _opener([("api.x.ai", (200, _grok_body("<!DOCTYPE html><html></html>")))])
                text, meta = pod_autocode_runner.granite_chat(
                    {"model": "granite4.2:8b-q8_0", "messages": [{"role": "user", "content": "edit the page"}]},
                    abort_s=1,
                )
            self.assertEqual(meta["backend"], "grok")
            self.assertIn("<!DOCTYPE html>", text)
            with EnvGuard(XAI_API_KEY=None, XAI_SETTINGS_FILE=None):
                defaults = llm_router.mission_defaults()
            self.assertEqual(defaults["llm_backend"], "granite")
            self.assertEqual(defaults["model"], "granite4.2:8b-q8_0")
            with EnvGuard(XAI_API_KEY=KEY, XAI_MODEL=None, XAI_SETTINGS_FILE=None):
                defaults = llm_router.mission_defaults()
            self.assertEqual(defaults["llm_backend"], "grok")
            self.assertEqual(defaults["model"], "grok-4.3")
        finally:
            urllib.request.urlopen = original


if __name__ == "__main__":
    unittest.main()
