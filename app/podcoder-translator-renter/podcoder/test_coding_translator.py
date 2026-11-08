#!/usr/bin/env python3
"""Coding translator fixes from the 3090 test (instance 58440710). Offline, mock model only.

- general coding asks route to Aider with the user's own words, never a calculator payload
- the chat timeout no longer empties the reply
- the chat UI starts the Aider job behind the RUN confirm, and shows its status
- harness: output cap, Aider timeout, no URL scraping, auto-test, auto-revert, one file per call
"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import aider_job  # noqa: E402
import coding_intent  # noqa: E402
import job_runner  # noqa: E402
import product_api  # noqa: E402
import setup_flow  # noqa: E402
import translation_profiles  # noqa: E402

ASPIRE_32 = {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 100, "gpu": "Radeon", "cpu": "Ryzen 7000", "platform": "linux"}

# The six prompts from the 3090 run, word for word, plus the brief's example.
REPORT_PROMPTS = [
    "yo build me a little python thing that reads jobs and prices from a csv file and tells me the total and the biggest one, and make it look nice in the terminal",
    "ok now add tests for it, then run the tests and show me what happens",
    "split that job thing into a little package, one file for loading, one for the math, one for the CLI, and keep the tests passing",
    "what happens if the csv has blank prices, dollar signs, or a negative number? handle it and test it",
    "add a command that groups jobs by customer and shows each one's total, sorted biggest first",
    "there's a bug somewhere, totals are off by a few cents sometimes, find it and fix it",
]
CSV_ASK = "build me a csv total thing"

CSV_TOTAL = (
    "import csv, sys\n\n"
    "def total(path):\n"
    "    with open(path, newline='') as fh:\n"
    "        return round(sum(float(r['price']) for r in csv.DictReader(fh)), 2)\n\n"
    "if __name__ == '__main__':\n"
    "    print(total(sys.argv[1]))\n"
)
CSV_TEST = (
    "import csv_total\n\n"
    "def test_total(tmp_path):\n"
    "    p = tmp_path / 'j.csv'\n"
    "    p.write_text('job,price\\na,1.10\\nb,2.20\\n')\n"
    "    assert csv_total.total(p) == 3.3\n"
)


class FakeAider:
    """Stands in for the aider binary. Everything else (git, pytest) runs for real."""

    def __init__(self, files=None, timeout=False, rc=0):
        self.files = files or {}
        self.timeout = timeout
        self.rc = rc
        self.calls = []

    def __call__(self, argv, **kw):
        if argv and argv[0] == "aider":
            self.calls.append({"argv": list(argv), "cwd": kw.get("cwd"), "timeout": kw.get("timeout"), "env": kw.get("env") or {}})
            settings = argv[argv.index("--model-settings-file") + 1]
            self.calls[-1]["settings"] = Path(settings).read_text(encoding="utf-8")
            if self.timeout:
                raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 1, output=b"partial")
            for rel, body in self.files.items():
                path = Path(kw["cwd"]) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
            return subprocess.CompletedProcess(argv, self.rc, "Applied edit\nTokens: 1.2k sent, 0.4k received.\n", "")
        return subprocess.run(argv, **kw)


def _unlock(state: Path) -> None:
    setup_flow.run(
        state,
        {"role": "coding", "probe": ASPIRE_32},
        downloader=lambda plan: {"executed": True, "dry_run": True, "vast_calls": 0, "destroyed": False},
    )
    assert setup_flow.unlocked(state)


class _StateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.workspace = self.state / "project"
        self.env = mock.patch.dict(os.environ, {"PODCODER_CODING_WORKSPACE": str(self.workspace)})
        self.env.start()
        os.environ.pop("PODCODER_SIMCO_LIVE_OLLAMA", None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class RoutingTests(_StateCase):
    def test_csv_total_routes_to_coding_with_the_original_words(self):
        _unlock(self.state)
        code, body = product_api.try_handle("POST", "/api/simco/turn", {"text": CSV_ASK}, self.state)
        self.assertEqual(code, 200, body)
        self.assertEqual(body["intent"], "coding")
        self.assertEqual(body["route"], "aider")
        self.assertIsNone(body["feature"])
        self.assertIsNone(body["payload"])
        message = body["aider"]["message"]
        self.assertTrue(message.startswith("User request (verbatim):\n" + CSV_ASK + "\n"))
        self.assertIn("Restatement:", message)
        argv = body["aider"]["argv"]
        self.assertEqual(argv[argv.index("--message") + 1], message)
        dumped = json.dumps(body).lower()
        for banned in ("calculator", "<!doctype", "html5", "fe_shell"):
            self.assertNotIn(banned, dumped)
        self.assertTrue(body["everyday"].strip())
        self.assertIn("RUN", body["everyday"])
        self.assertTrue(body["needs_confirm"])
        self.assertEqual(body["status"], "needs_approval")
        job = job_runner.get_job(self.state, body["job_id"])
        self.assertEqual(job["kind"], "aider")
        self.assertEqual(job["status"], "needs_approval")

    def test_stale_client_feature_cannot_force_a_calculator(self):
        for forced in ("fe_shell", "add", "mul"):
            inbound = translation_profiles.translate_in(CSV_ASK, None, feature=forced)
            self.assertEqual(inbound["intent"], "coding", forced)
            self.assertIsNone(inbound["feature"])
            self.assertNotIn("calculator", json.dumps(inbound).lower())

    def test_all_six_report_prompts_route_to_coding(self):
        for text in REPORT_PROMPTS:
            inbound = translation_profiles.translate_in(text)
            self.assertTrue(inbound["ok"], text)
            self.assertEqual(inbound["intent"], "coding", text)
            self.assertIn(text, inbound["aider"]["message"])
            self.assertNotIn("calculator", inbound["aider"]["message"].lower())

    def test_calculator_asks_keep_the_calculator_gates(self):
        inbound = translation_profiles.translate_in("make multiply show 7 times 8")
        self.assertEqual(inbound["feature"], "mul")
        self.assertNotEqual(inbound.get("intent"), "coding")
        self.assertFalse(coding_intent.is_coding_request("make a calculator"))
        self.assertFalse(coding_intent.is_coding_request("hello there friend"))

    def test_restatement_and_harness_flags(self):
        plan = coding_intent.plan("granite4.2:8b", "there's a bug in totals.py, totals are off by a few cents")
        argv = plan["argv"]
        for flag in ("--no-detect-urls", "--auto-test", "--edit-format", "--map-tokens", "--yes-always"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--test-cmd") + 1], coding_intent.TEST_CMD)
        self.assertEqual(argv[-1], "totals.py")  # one file per call
        self.assertEqual(plan["restatement"]["kind"], "fix a bug")
        self.assertTrue(plan["restatement"]["tests"])
        self.assertIn("max_tokens: 3072", plan["model_settings"])
        self.assertIn("num_predict: 3072", plan["model_settings"])
        self.assertIn("Edit one file per reply", plan["message"])
        self.assertEqual(plan["timeout_s"], coding_intent.AIDER_TIMEOUT_S)
        with mock.patch.dict(os.environ, {"PODCODER_AIDER_TIMEOUT": "120"}):
            self.assertEqual(coding_intent.plan("granite4.2:8b", CSV_ASK)["timeout_s"], 120)

    def test_unmapped_text_gets_words_not_an_empty_reply(self):
        _unlock(self.state)
        code, body = product_api.try_handle("POST", "/api/simco/turn", {"text": "hello there friend"}, self.state)
        self.assertEqual(code, 200)
        self.assertTrue(body["everyday"].strip())
        self.assertNotIn("calculator", body["everyday"].lower())


class WholeWordIntentTests(unittest.TestCase):
    """Coding keywords match whole words only ("capital" is not "api")."""

    NOT_CODING = [
        "What is the capital of France?",
        "What is the capital of France? Answer in one short sentence.",
        "what's the latest news",
        "update my profile",
        "nearest clinic",
        "first class flight",
        "click here",
        "Hi, what's 7 times 8?",
        "Hi, what's 7 times 8? Answer in one short sentence.",
        "hello there friend",
    ]
    CODING = [
        "write a python script",
        "build an API",
        "fix the CLI",
        "add a class",
        "write tests",
        "write a python function that adds two numbers, with tests",
        "Write A PYTHON Script",
        "my app crashes on start",
        "refactor the parser",
        "make me a website",
        "the import fails",
        CSV_ASK,
    ] + REPORT_PROMPTS

    def test_everyday_words_are_not_coding(self):
        for text in self.NOT_CODING:
            self.assertFalse(coding_intent.is_coding_request(text), text)

    def test_everyday_words_go_to_chat_not_a_coding_job(self):
        for text in self.NOT_CODING[:7]:
            inbound = translation_profiles.translate_in(text)
            self.assertNotEqual(inbound.get("intent"), "coding", text)

    def test_real_coding_asks_still_route_to_coding(self):
        for text in self.CODING:
            self.assertTrue(coding_intent.is_coding_request(text), text)
            self.assertEqual(translation_profiles.translate_in(text)["intent"], "coding", text)

    def test_restatement_flags_use_whole_words(self):
        self.assertFalse(coding_intent.restate("show the latest totals")["tests"])
        self.assertTrue(coding_intent.restate("write tests for totals")["tests"])
        self.assertEqual(coding_intent.restate("fix the prefix bug")["kind"], "fix a bug")
        self.assertEqual(coding_intent.restate("build a prefixer script")["kind"], "build something new")

    def test_chat_page_calculator_keywords_use_whole_words(self):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        page = (ROOT.parent / "local" / "chat.html").read_text(encoding="utf-8")
        start = page.index("function detectIntent(text) {")
        end = page.index("\n}\n", start) + 3
        cases = {
            "what is my address": "",
            "sometimes I wonder": "",
            "summer plans": "",
            "make multiply show 7 times 8": "mul",
            "now do division": "div",
            "add plus": "add",
            "subtraction please": "sub",
            "multi-digit": "mul_multi",
            "make a calculator": "fe_shell",
        }
        script = page[start:end] + "\nconst cases = " + json.dumps(cases) + ";\n" + (
            "const out = {}; for (const k of Object.keys(cases)) out[k] = detectIntent(k);"
            " process.stdout.write(JSON.stringify(out));"
        )
        got = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(got, cases)


class _Stream:
    """A fake streamed Ollama response: yields chunks, then optionally a socket timeout."""

    def __init__(self, chunks, fail=None):
        self.lines = [json.dumps({"message": {"content": c}, "done": False}).encode() + b"\n" for c in chunks]
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        yield from self.lines
        if self.fail:
            raise self.fail
        yield json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n"


class TimeoutTests(_StateCase):
    def test_limits_are_no_longer_eight_seconds(self):
        limits = product_api.chat_limits()
        self.assertGreaterEqual(limits["total_s"], 120)
        self.assertGreaterEqual(limits["idle_s"], 30)

    def test_stream_collects_text_and_caps_output(self):
        seen = {}

        def opener(req, timeout):
            seen["body"] = json.loads(req.data.decode())
            seen["timeout"] = timeout
            return _Stream(["Hel", "lo"])

        with mock.patch.object(product_api, "_open_chat", side_effect=opener):
            reply = product_api._ollama_chat({"model": "granite4.2:8b", "options": {"num_predict": 8192}, "messages": []})
        self.assertEqual(reply["status"], "done")
        self.assertEqual(reply["text"], "Hello")
        self.assertTrue(seen["body"]["stream"])
        self.assertEqual(seen["body"]["options"]["num_predict"], product_api.CHAT_NUM_PREDICT)
        self.assertGreater(seen["timeout"], 8)

    def test_timeout_keeps_partial_text(self):
        with mock.patch.object(product_api, "_open_chat", return_value=_Stream(["<!DOCTYPE html><html>", "<body>"], fail=socket.timeout("timed out"))):
            reply = product_api._ollama_chat({"messages": []})
        self.assertEqual(reply["status"], "timeout")
        self.assertEqual(reply["text"], "<!DOCTYPE html><html><body>")

    def test_total_deadline_stops_a_runaway_stream(self):
        ticks = iter([0.0] + [float(i * 100) for i in range(1, 50)])
        with mock.patch.dict(os.environ, {"PODCODER_CHAT_TIMEOUT": "150"}):
            with mock.patch.object(product_api, "_open_chat", return_value=_Stream(["a", "b", "c", "d", "e"])):
                reply = product_api._ollama_chat({"messages": []}, clock=lambda: next(ticks))
        self.assertEqual(reply["status"], "timeout")
        self.assertTrue(reply["text"])

    def test_timed_out_turn_reply_is_not_empty(self):
        _unlock(self.state)
        with mock.patch.dict(os.environ, {"PODCODER_SIMCO_LIVE_OLLAMA": "1"}):
            with mock.patch.object(product_api, "_open_chat", side_effect=socket.timeout("timed out")):
                code, body = product_api.try_handle("POST", "/api/simco/turn", {"text": "make multiply show 7 times 8"}, self.state)
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "timeout")
        self.assertTrue(body["everyday"].strip())
        self.assertNotIn("reply was empty", body["everyday"])

    def test_coding_turn_never_waits_on_granite_chat(self):
        _unlock(self.state)
        with mock.patch.dict(os.environ, {"PODCODER_SIMCO_LIVE_OLLAMA": "1"}):
            with mock.patch.object(product_api, "_open_chat", side_effect=AssertionError("no chat call for coding")):
                code, body = product_api.try_handle("POST", "/api/simco/turn", {"text": CSV_ASK}, self.state)
        self.assertEqual(code, 200)
        self.assertTrue(body["everyday"].strip())


class JobStartTests(_StateCase):
    def _queue(self, text=CSV_ASK):
        _unlock(self.state)
        code, body = product_api.try_handle("POST", "/api/simco/turn", {"text": text}, self.state)
        self.assertEqual(code, 200)
        return body["job_id"]

    def test_wrong_word_does_not_start(self):
        job_id = self._queue()
        fake = FakeAider()
        with mock.patch.object(product_api, "AIDER_RUNNER", fake):
            for word in ("", "run", "yes", "RENT"):
                code, body = product_api.try_handle("POST", "/api/coding/run", {"job_id": job_id, "confirm": word, "wait": True}, self.state)
                self.assertEqual(code, 400, word)
        self.assertEqual(fake.calls, [])
        self.assertEqual(job_runner.get_job(self.state, job_id)["status"], "needs_approval")

    def test_run_confirm_starts_aider_with_the_users_words(self):
        job_id = self._queue()
        fake = FakeAider({"csv_total.py": CSV_TOTAL, "test_csv_total.py": CSV_TEST})
        with mock.patch.object(product_api, "AIDER_RUNNER", fake):
            code, body = product_api.try_handle("POST", "/api/coding/run", {"job_id": job_id, "confirm": "RUN", "wait": True}, self.state)
        self.assertEqual(code, 200, body)
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        argv = call["argv"]
        self.assertIn(CSV_ASK, argv[argv.index("--message") + 1])
        self.assertIn("--no-detect-urls", argv)
        self.assertIn("--auto-test", argv)
        self.assertIn("max_tokens: 3072", call["settings"])
        self.assertEqual(call["timeout"], coding_intent.AIDER_TIMEOUT_S)
        self.assertEqual(call["env"].get("OLLAMA_API_BASE"), "http://127.0.0.1:11434")
        self.assertEqual(Path(call["cwd"]).resolve(), self.workspace.resolve())
        code, status = product_api.try_handle("GET", f"/api/coding/status/{job_id}", {}, self.state)
        self.assertEqual(code, 200)
        self.assertEqual(status["status"], "done", status)
        self.assertTrue(status["result"]["tests_after"]["passed"])
        self.assertIn("Done", status["everyday"])
        self.assertTrue((self.workspace / "csv_total.py").is_file())
        lines = [row["line"] for row in status["logs"]]
        self.assertTrue(any(line.startswith("aider started") for line in lines))

    def test_background_start_reports_running_then_done(self):
        job_id = self._queue()
        fake = FakeAider({"csv_total.py": CSV_TOTAL})
        with mock.patch.object(product_api, "AIDER_RUNNER", fake):
            code, body = product_api.try_handle("POST", "/api/coding/run", {"job_id": job_id, "confirm": "RUN"}, self.state)
            self.assertEqual(code, 200)
            self.assertEqual(body["status"], "running")
            aider_job._THREADS[job_id].join(60)
        self.assertEqual(job_runner.get_job(self.state, job_id)["status"], "done")

    def test_breaking_tests_auto_reverts(self):
        self.workspace.mkdir(parents=True)
        (self.workspace / "csv_total.py").write_text(CSV_TOTAL, encoding="utf-8")
        (self.workspace / "test_csv_total.py").write_text(CSV_TEST, encoding="utf-8")
        job_id = self._queue("ok now add tests for it, then run the tests and show me what happens")
        # Prompt 2 of the 3090 run: Granite overwrote the source file with test code.
        fake = FakeAider({"csv_total.py": "import csv_total\n", "path/to/test_x.py": "x = 1\n", "Output would look like": "junk\n"})
        with mock.patch.object(product_api, "AIDER_RUNNER", fake):
            product_api.try_handle("POST", "/api/coding/run", {"job_id": job_id, "confirm": "RUN", "wait": True}, self.state)
        job = job_runner.get_job(self.state, job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("reverted", job["error"])
        self.assertEqual((self.workspace / "csv_total.py").read_text(encoding="utf-8"), CSV_TOTAL)
        self.assertFalse((self.workspace / "Output would look like").exists())
        self.assertFalse((self.workspace / "path").exists() and any((self.workspace / "path").rglob("*.py")))
        code, status = product_api.try_handle("POST", "/api/coding/status", {"job_id": job_id}, self.state)
        self.assertIn("Nothing was kept", status["everyday"])

    def test_aider_timeout_reverts_and_fails_once(self):
        job_id = self._queue()
        fake = FakeAider(timeout=True)
        with mock.patch.object(product_api, "AIDER_RUNNER", fake):
            product_api.try_handle("POST", "/api/coding/run", {"job_id": job_id, "confirm": "RUN", "wait": True}, self.state)
        job = job_runner.get_job(self.state, job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("timed out", job["error"])
        self.assertEqual(len(fake.calls), 1)  # max_attempts=1, no silent retry loop


class ChatPageWiringTests(unittest.TestCase):
    def test_chat_page_runs_the_job_behind_the_run_word(self):
        chat = (ROOT.parent / "local" / "chat.html").read_text(encoding="utf-8")
        self.assertIn('"/api/coding/run"', chat)
        self.assertIn('"/api/coding/status/"', chat)
        self.assertIn('text === "RUN"', chat)
        intent = chat.split("function detectIntent", 1)[1].split("\n}\n", 1)[0]
        self.assertTrue(intent.rstrip().endswith('return "";'), intent[-120:])


class ChatPageBrowserTests(unittest.TestCase):
    """Type a coding ask, type RUN, and watch the mocked job finish in the real page."""

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise unittest.SkipTest(f"playwright is not installed: {exc}") from exc
        sys.path.insert(0, str(ROOT.parent / "local"))
        import server as local_server

        cls.tmp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.tmp.name)
        cls.old_env = {k: os.environ.get(k) for k in ("PODCODER_STATE_DIR", "PODCODER_DRY_RUN", "PODCODER_CODING_WORKSPACE")}
        os.environ["PODCODER_STATE_DIR"] = cls.tmp.name
        os.environ["PODCODER_DRY_RUN"] = "1"
        os.environ["PODCODER_CODING_WORKSPACE"] = str(cls.state / "project")
        os.environ.pop("PODCODER_SIMCO_LIVE_OLLAMA", None)
        _unlock(local_server.app_state_dir())
        cls.httpd = local_server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        try:
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        except Exception as exc:
            cls.tearDownClass()
            raise unittest.SkipTest(f"chrome is not available: {exc}") from exc

    @classmethod
    def tearDownClass(cls):
        for name in ("browser", "pw"):
            obj = getattr(cls, name, None)
            if obj:
                (obj.close if name == "browser" else obj.stop)()
                setattr(cls, name, None)
        if getattr(cls, "httpd", None):
            cls.httpd.shutdown()
            cls.httpd.server_close()
            cls.httpd = None
        for key, value in getattr(cls, "old_env", {}).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if getattr(cls, "tmp", None):
            cls.tmp.cleanup()
            cls.tmp = None

    def test_ui_triggered_job_starts_and_shows_status(self):
        fake = FakeAider({"csv_total.py": CSV_TOTAL, "test_csv_total.py": CSV_TEST})
        page = self.browser.new_page()
        hits = []
        page.on("request", lambda r: hits.append((r.method, r.url, r.post_data or "")))
        try:
            with mock.patch.object(product_api, "AIDER_RUNNER", fake):
                page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
                page.evaluate("() => { const t = document.getElementById('turtleScreen'); if (t) t.hidden = true; }")
                page.locator("#everyday").fill(CSV_ASK)
                page.locator("#go").click()
                page.wait_for_function("() => (document.getElementById('reply-bubble').textContent || '').includes('RUN')", timeout=15000)
                turn = [b for m, u, b in hits if u.endswith("/api/simco/turn")]
                self.assertTrue(turn)
                self.assertNotIn('"feature"', turn[-1])
                self.assertEqual(fake.calls, [])
                page.locator("#everyday").fill("RUN")
                page.locator("#go").click()
                page.wait_for_function("() => (document.getElementById('reply-bubble').textContent || '').startsWith('Done')", timeout=60000)
            self.assertEqual(len(fake.calls), 1)
            self.assertIn(CSV_ASK, fake.calls[0]["argv"][fake.calls[0]["argv"].index("--message") + 1])
            self.assertTrue(any(u.endswith("/api/coding/run") and '"RUN"' in b for m, u, b in hits))
            self.assertTrue(any("/api/coding/status/" in u for m, u, b in hits))
            self.assertFalse(any("/api/rent" in u and m == "POST" for m, u, b in hits))
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
