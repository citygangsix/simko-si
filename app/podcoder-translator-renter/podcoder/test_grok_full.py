#!/usr/bin/env python3
"""Grok is the only required brain for Simco SI chat and coding. Offline: Grok is faked.

- with a key, the install/smoke gate never blocks chat or coding
- plain chat goes to Grok
- a coding job writes files, then compiles, tests, runs and browser-loads them
- a crash or failing test is reported as a failure, never "Done"
- "fix it" sends the error back to Grok in the same project and can succeed
- video never goes through Grok before 2026-11-03
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import coding_fix  # noqa: E402
import job_runner  # noqa: E402
import llm_router  # noqa: E402
import product_api  # noqa: E402
import setup_flow  # noqa: E402
import xai_client  # noqa: E402

CRASHING = {
    "summary": "A script that divides numbers.",
    "files": [{"path": "divide.py", "content": "def divide(a, b):\n    return a / b\n\nprint(divide(1, 0))\n"}],
    "entry": {"argv": ["python3", "divide.py"]},
}
FIXED = {
    "summary": "Division now handles zero.",
    "files": [{"path": "divide.py", "content": "def divide(a, b):\n    return None if b == 0 else a / b\n\nprint(divide(1, 0))\n"}],
    "entry": {"argv": ["python3", "divide.py"]},
}
WITH_TESTS = {
    "summary": "Adds two numbers, with a test.",
    "files": [
        {"path": "adder.py", "content": "def add(a, b):\n    return a + b\n"},
        {"path": "test_adder.py", "content": "from adder import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
    ],
    "entry": None,
}
FAILING_TESTS = {
    "summary": "Adds two numbers.",
    "files": [
        {"path": "adder.py", "content": "def add(a, b):\n    return a - b\n"},
        {"path": "test_adder.py", "content": "from adder import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
    ],
    "entry": None,
}


class FakeGrok:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[list[dict]] = []

    def __call__(self, messages, **kwargs):
        self.calls.append(messages)
        doc = self.answers.pop(0) if self.answers else {"files": []}
        return {"ok": True, "text": json.dumps(doc), "model": "grok-test"}


class GrokBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        self.workspace = Path(self.tmp.name) / "coding"
        self.patches = [
            mock.patch.dict(os.environ, {"PODCODER_CODING_WORKSPACE": str(self.workspace)}),
            mock.patch.object(xai_client, "api_key", return_value="test-key-not-real"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def turn(self, text, **extra):
        code, body = product_api.try_handle("POST", "/api/simco/turn", {"text": text, **extra}, self.state)
        self.assertEqual(code, 200, body)
        return body

    def run_job(self, job_id):
        code, body = product_api.try_handle("POST", "/api/coding/run", {"job_id": job_id, "confirm": "RUN", "wait": True}, self.state)
        return body

    def status(self, job_id):
        code, body = product_api.try_handle("GET", f"/api/coding/status/{job_id}", None, self.state)
        self.assertEqual(code, 200)
        return body


class GateTests(GrokBase):
    def test_no_smoke_gate_with_grok(self):
        self.assertIsNone(product_api.chat_block(self.state))

    def test_gate_still_applies_without_grok(self):
        with mock.patch.object(xai_client, "api_key", return_value=""):
            self.assertIsNotNone(product_api.chat_block(self.state))

    def test_setup_unlocks_small_computer_with_grok(self):
        tiny = {"ram_gb": 4, "vram_gb": 0, "disk_free_gb": 5, "gpu": "", "cpu": "phone", "platform": "android"}
        out = setup_flow.run(self.state, {"probe": tiny})
        self.assertTrue(out["chat_unlocked"])
        self.assertEqual(out["brain"], "grok")
        self.assertTrue(setup_flow.status(self.state)["chat_unlocked"])


class ChatTests(GrokBase):
    def test_plain_chat_goes_to_grok(self):
        with mock.patch.object(llm_router, "complete", return_value={"ok": True, "text": "Hi Joseph.", "backend": "grok", "model": "grok-4.3"}) as fake:
            body = self.turn("hello there, how is your day")
        self.assertEqual(body["backend"], "grok")
        self.assertEqual(body["everyday"], "Hi Joseph.")
        self.assertEqual(fake.call_args.kwargs["purpose"], "chat")

    def test_chat_says_plainly_when_grok_is_down(self):
        with mock.patch.object(llm_router, "complete", return_value={"ok": False, "text": "", "backend": "canned", "error": "network"}):
            body = self.turn("hello there")
        self.assertFalse(body["ok"])
        self.assertIn("couldn't reach Grok", body["everyday"])

    def test_video_never_through_grok_before_nov_3(self):
        status = llm_router.public_status()
        self.assertFalse(status["grok_video"]["allowed"])
        self.assertEqual(status["grok_video"]["blocked_until"], "2026-11-03")
        self.assertNotIn("grok", status["features"]["video"])


class CodingTests(GrokBase):
    def test_coding_request_is_a_grok_job(self):
        body = self.turn("write a python script that adds two numbers")
        self.assertEqual(body["intent"], "coding")
        self.assertEqual(body["engine"], "grok")
        self.assertTrue(body["needs_confirm"])
        self.assertNotIn("Aider", body["everyday"])

    def test_success_is_checked_before_done(self):
        fake = FakeGrok(WITH_TESTS)
        body = self.turn("write a python function that adds two numbers, with tests")
        with mock.patch.object(xai_client, "chat", fake):
            self.run_job(body["job_id"])
        job = self.status(body["job_id"])
        self.assertEqual(job["status"], "done", job)
        self.assertIn("Done.", job["everyday"])
        self.assertIn("tests passed", job["everyday"])
        self.assertIn("adder.py", job["result"]["files"])
        self.assertIn("def add", job["result"]["preview"])

    def test_crash_is_reported_not_done_and_fix_it_works(self):
        body = self.turn("write a python script that divides one by zero and prints it")
        with mock.patch.object(xai_client, "chat", FakeGrok(CRASHING)):
            self.run_job(body["job_id"])
        job = self.status(body["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertNotIn("Done", job["everyday"])
        self.assertIn("crashed", job["everyday"])
        self.assertIn("ZeroDivisionError", job["everyday"])
        self.assertIn("divide.py", job["everyday"])
        self.assertIn('fix it', job["everyday"])
        self.assertIsNotNone(coding_fix.last_failure(self.state, "default"))

        fake = FakeGrok(FIXED)
        with mock.patch.object(xai_client, "chat", fake):
            fixed = self.turn("ok fix that", wait=True)
        self.assertEqual(fixed["intent"], "coding")
        self.assertFalse(fixed["needs_confirm"])
        sent = fake.calls[0][-1]["content"]
        self.assertIn("ZeroDivisionError", sent)
        self.assertIn("divide.py", sent)
        self.assertIn("def divide(a, b):\n    return a / b", sent)  # it saw the broken file
        job2 = self.status(fixed["job_id"])
        self.assertEqual(job2["status"], "done", job2)
        self.assertIn("it ran without errors", job2["everyday"])
        self.assertIsNone(coding_fix.last_failure(self.state, "default"))

    def test_crash_without_named_entry_is_still_caught(self):
        # Seen live: Grok left entry null for a script that crashes. We run it anyway.
        quiet = {**CRASHING, "entry": None, "files": [{"path": "crash.py", "content": "def main():\n    print(10 / 0)\n\nif __name__ == '__main__':\n    main()\n"}]}
        body = self.turn("write a python script crash.py that divides 10 by zero")
        self.assertNotIn("undo the change", body["everyday"])
        with mock.patch.object(xai_client, "chat", FakeGrok(quiet)):
            self.run_job(body["job_id"])
        job = self.status(body["job_id"])
        self.assertEqual(job["status"], "failed", job)
        self.assertNotIn("Done", job["everyday"])
        self.assertIn("ZeroDivisionError", job["everyday"])

    def test_scripts_that_wait_for_input_are_not_run(self):
        import grok_coder
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "ask.py").write_text("name = input('name? ')\nprint(name)\n")
            self.assertIsNone(grok_coder.guess_entry(Path(tmp), ["ask.py"]))

    def test_fix_it_with_nothing_failed_says_so(self):
        body = self.turn("fix it")
        self.assertEqual(body["status"], "nothing_to_fix")
        self.assertIn("nothing for me to fix", body["everyday"])

    def test_failing_tests_are_not_done(self):
        body = self.turn("write a python function that adds two numbers, with tests")
        with mock.patch.object(xai_client, "chat", FakeGrok(FAILING_TESTS)):
            self.run_job(body["job_id"])
        job = self.status(body["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertNotIn("Done", job["everyday"])
        self.assertIn("tests failed", job["everyday"])

    def test_grok_down_is_a_plain_failure(self):
        body = self.turn("write a python script that adds two numbers")
        with mock.patch.object(xai_client, "chat", return_value={"ok": False, "error": "rate", "text": ""}):
            self.run_job(body["job_id"])
        job = self.status(body["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("Grok didn't send back usable code", job["everyday"])

    def test_unsafe_paths_are_skipped(self):
        bad = {"files": [{"path": "../escape.py", "content": "x=1\n"}, {"path": "/etc/x.py", "content": "x=1\n"}, {"path": "ok.py", "content": "x = 1\n"}], "entry": None}
        body = self.turn("write a python script that sets x")
        with mock.patch.object(xai_client, "chat", FakeGrok(bad)):
            self.run_job(body["job_id"])
        job = self.status(body["job_id"])
        self.assertEqual(job["result"]["files"], ["ok.py"])
        self.assertFalse((self.workspace / "escape.py").exists())


class FixPhraseTests(unittest.TestCase):
    def test_phrases(self):
        for text in ("fix it", "fix that", "ok fix that", "Okay, let's fix that", "FIX", "try again", "fix the crash please"):
            self.assertTrue(coding_fix.is_fix_followup(text), text)
        for text in ("fix the login page so it uses email", "hello", "write a script"):
            self.assertFalse(coding_fix.is_fix_followup(text), text)

    def test_fix_without_failure_is_not_hijacked(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(coding_fix.last_failure(Path(tmp), "default"))


if __name__ == "__main__":
    unittest.main()
