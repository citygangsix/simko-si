"""Generated pages are checked, repaired and clicked before Simko SI says they work.

Fixtures in fixtures/apps/:
- granite_3090_calc.html: the real Granite 4.2 page from the 3090 run (looks up 'c' and '⌫', which don't exist,
  and its digit handler wipes the first number, so 7 * 8 = shows 8).
- calc_unrepairable.html: no digit buttons at all; nothing can be pointed at.
- <kind>_flawed.html / <kind>_fixed.html: realistic broken first answers and their repaired versions.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app_check
import coding_intent
import granite_to_everyday
import llm_router
import product_api
import setup_flow
import xai_client

APPS = Path(__file__).resolve().parent / "fixtures" / "apps"
REQ = {
    "tip": "Can you make me a simple tip calculator where I put in the bill and the tip percent and it tells me the total?",
    "todo": "I want a to-do list where I can add things and cross them off.",
    "calc": "make multiply show 7 times 8",
    "convert": "Make me a little converter that turns miles into kilometers.",
    "timer": "I need a countdown timer with start and pause buttons.",
}
CANNED = "you should see 56"


def page(name: str) -> str:
    return (APPS / name).read_text(encoding="utf-8")


def browser_ok() -> bool:
    return app_check.run_checks(page_html="<!DOCTYPE html><html><body>x</body></html>").get("ran") is True


HAVE_BROWSER = browser_ok()
needs_browser = unittest.skipUnless(HAVE_BROWSER, "no headless browser on this computer")


class StaticRepairTests(unittest.TestCase):
    def test_real_granite_page_is_repaired(self):
        raw = page("granite_3090_calc.html")
        found = app_check.refs(raw)
        self.assertIn("c", found["missing"])
        self.assertIn("⌫", found["missing"])
        fixed = app_check.repair(raw)
        self.assertEqual(fixed["unresolved"], [])
        joined = " ".join(fixed["changes"])
        self.assertIn("'c' pointed at nothing", joined)
        self.assertIn("'clear'", joined)
        self.assertIn("'⌫'", joined)
        self.assertEqual(app_check.refs(fixed["html"])["missing"], [])

    def test_unrepairable_ids_stay_unresolved(self):
        fixed = app_check.repair(page("calc_unrepairable.html"))
        self.assertIn("multiplyKey", fixed["unresolved"])

    def test_truncated_page_is_detected_and_asks_for_shorter(self):
        cut = page("granite_3090_calc.html")[:1800]
        self.assertTrue(app_check.is_truncated(cut))
        check = app_check.verify_html(cut, REQ["calc"], "mul")
        self.assertFalse(check["verified"])
        self.assertTrue(check["truncated"])
        self.assertIn("SHORTER", app_check.repair_prompt(check, REQ["calc"]))
        self.assertIn("cut off", app_check.everyday(check))
        self.assertNotIn(CANNED, app_check.everyday(check))

    def test_kinds_are_inferred_from_plain_sentences(self):
        for kind, text in REQ.items():
            self.assertEqual(app_check.infer_kind(text, "mul" if kind == "calc" else None), kind, text)


class RoutingTests(unittest.TestCase):
    def test_plain_sentences_route_without_special_format(self):
        for kind in ("tip", "todo", "convert", "timer"):
            self.assertTrue(coding_intent.is_coding_request(REQ[kind]), REQ[kind])
        self.assertTrue(coding_intent.is_calculator_request(REQ["calc"]))
        for text in ("what is the capital of France?", "give me a list of good restaurants in Boston", "set a timer for 5 minutes"):
            self.assertFalse(coding_intent.is_coding_request(text), text)


class WebPageDefaultTests(unittest.TestCase):
    def test_plain_app_asks_default_to_a_web_page(self):
        for kind in ("tip", "todo", "convert", "timer"):
            self.assertTrue(coding_intent.wants_web_page(REQ[kind]), REQ[kind])
        self.assertFalse(coding_intent.wants_web_page("write a python command line tip calculator"))
        self.assertFalse(coding_intent.wants_web_page("write a python function that adds two numbers"))

    def test_unchecked_grok_job_is_not_done(self):
        job = {"status": "done", "result": {"engine": "grok", "files": ["main.py"], "summary": "A tip calculator.", "checks": {}, "tests_after": {"ran": False}}}
        line = product_api.coding_status_line(job)
        self.assertTrue(line.startswith("Written, not verified."), line)
        self.assertNotIn("Done", line)


class HonestLineTests(unittest.TestCase):
    def test_success_line_only_after_passing_check(self):
        passing = {"verified": True, "repairs": [], "browser": {"results": [{"name": "7 × 8 = shows 56", "passed": True}]}}
        self.assertIn("I tested it in a browser: 7 × 8 = shows 56", app_check.everyday(passing, "Multiplication is in."))
        failing = {"verified": False, "failure": {"kind": "interaction", "message": "7 × 8 = shows 56 failed"}}
        line = app_check.everyday(failing, "Multiplication is in. Click 7, *, 8, = — you should see 56.")
        self.assertNotIn(CANNED, line)
        self.assertIn('"fix it"', line)
        untested = {"verified": None, "browser": {"skipped": "Playwright is not installed on this computer"}}
        line = app_check.everyday(untested, "Multiplication is in.")
        self.assertIn("not verified", line)
        self.assertNotIn("Multiplication is in", line)

    def test_no_playwright_means_not_verified(self):
        with mock.patch.object(app_check, "run_checks", return_value={"ran": False, "passed": None, "skipped": "Playwright is not installed on this computer"}):
            out = granite_to_everyday.translate(page("calc_fixed.html"), feature="mul", ask=REQ["calc"])
        self.assertIsNone(out["verified"])
        self.assertIn("not verified", out["everyday"])
        self.assertNotIn(CANNED, out["everyday"])


@needs_browser
class BrowserTests(unittest.TestCase):
    def test_real_granite_page_no_longer_crashes_but_math_is_wrong(self):
        check = app_check.verify_html(page("granite_3090_calc.html"), REQ["calc"], "mul")
        self.assertEqual(check["browser"]["errors"], [])  # the null addEventListener crash is gone
        self.assertFalse(check["verified"])  # 7 * 8 = shows 8: Granite's own logic bug
        line = app_check.everyday(check, "Multiplication is in.")
        self.assertNotIn(CANNED, line)
        self.assertIn("doesn't work yet", line)

    def test_unrepaired_page_shows_the_original_crash(self):
        report = app_check.run_checks(page_html=page("granite_3090_calc.html"), request=REQ["calc"], feature="mul")
        self.assertTrue(any("addEventListener" in e for e in report["errors"]))

    def test_translate_on_real_granite_page_is_honest(self):
        out = granite_to_everyday.translate(page("granite_3090_calc.html"), feature="mul", ask=REQ["calc"])
        self.assertFalse(out["ok"])
        self.assertFalse(out["verified"])
        self.assertNotIn(CANNED, out["everyday"])
        self.assertIn("fix it", out["everyday"])

    def test_repair_round_with_a_fixed_page_passes(self):
        sent = []

        def call(extra):
            sent.append(extra)
            return {"text": page("calc_fixed.html"), "done_reason": "stop"}

        out = product_api.check_and_repair({"text": page("granite_3090_calc.html")}, call, REQ["calc"], "mul")
        self.assertTrue(out["check"]["verified"])
        self.assertEqual(out["check"]["repair_rounds"], 1)
        self.assertIn("the display showed '8'", sent[0][-1]["content"])  # the real failure went back to the model
        line = app_check.everyday(out["check"], "Multiplication is in.")
        self.assertIn("7 × 8 = shows 56", line)
        self.assertIn("1 repair round", line)

    def test_unrepairable_stops_after_two_rounds_honestly(self):
        calls = []

        def call(extra):
            calls.append(extra)
            return {"text": page("calc_unrepairable.html"), "done_reason": "stop"}

        out = product_api.check_and_repair({"text": page("calc_unrepairable.html")}, call, REQ["calc"], "mul")
        self.assertEqual(len(calls), 2)
        self.assertFalse(out["check"]["verified"])
        line = app_check.everyday(out["check"], "Multiplication is in. Click 7, *, 8, = — you should see 56.")
        self.assertNotIn(CANNED, line)
        self.assertIn("2 repair rounds", line)
        self.assertIn('"fix it"', line)

    def test_truncated_reply_gets_a_shorter_retry(self):
        calls = []

        def call(extra):
            calls.append(extra)
            return {"text": page("calc_fixed.html"), "done_reason": "stop"}

        cut = {"text": page("granite_3090_calc.html")[:2500], "done_reason": "length"}
        out = product_api.check_and_repair(cut, call, REQ["calc"], "mul")
        self.assertTrue(out["check"]["verified"])
        self.assertEqual([m["role"] for m in calls[0]], ["user"])  # the cut page is not echoed back
        self.assertIn("SHORTER", calls[0][0]["content"])

    def test_flawed_apps_fail_and_fixed_apps_pass(self):
        for kind in ("tip", "todo", "convert", "timer"):
            bad = app_check.verify_html(page(f"{kind}_flawed.html"), REQ[kind])
            good = app_check.verify_html(page(f"{kind}_fixed.html"), REQ[kind])
            self.assertFalse(bad["verified"], kind)
            self.assertTrue(good["verified"], (kind, good.get("failure")))


class ThinkOffTests(unittest.TestCase):
    def test_granite_calls_turn_thinking_off(self):
        seen = []

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"message": {"content": "hi"}}).encode()

            def __iter__(self):
                return iter([json.dumps({"message": {"content": "hi"}, "done": True, "done_reason": "stop"}).encode()])

        def opener(req, timeout=None):
            seen.append(json.loads(req.data.decode()))
            return Resp()

        llm_router.post_granite({"model": "granite4.2:8b", "messages": []}, opener=opener)
        self.assertIs(seen[-1]["think"], False)
        with mock.patch.object(product_api, "_open_chat", opener):
            out = product_api._ollama_chat({"model": "granite4.2:8b", "messages": [{"role": "user", "content": "hi"}]})
        self.assertIs(seen[-1]["think"], False)
        self.assertEqual(out["done_reason"], "stop")


class InstalledModelTests(unittest.TestCase):
    def test_pick_installed(self):
        self.assertEqual(setup_flow.pick_installed("granite4.2:8b-q5_0", ["granite4.2:8b"]), "granite4.2:8b")
        self.assertEqual(setup_flow.pick_installed("granite4.2:8b-q8_0", ["granite4.2:8b", "granite4.2:8b-q5_0"]), "granite4.2:8b-q5_0")
        self.assertEqual(setup_flow.pick_installed("granite4.2:8b-q5_0", ["granite4.2:8b-q5_0"]), "granite4.2:8b-q5_0")
        self.assertEqual(setup_flow.pick_installed("granite4.2:8b-q5_0", []), "granite4.2:8b-q5_0")
        self.assertEqual(setup_flow.pick_installed("granite4.2:8b-q5_0", ["llama3:8b"]), "granite4.2:8b-q5_0")

    def test_setup_locks_the_installed_tag(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(xai_client, "api_key", return_value=""), \
                mock.patch.object(setup_flow, "_installed_tags", return_value=["granite4.2:8b"]):
            probe = {"ram_gb": 64, "vram_gb": 24, "disk_free_gb": 200, "gpu": "RTX 3090", "cpu": "x", "platform": "linux"}
            out = setup_flow.run(Path(tmp), {"probe": probe}, downloader=lambda *a, **k: {"ok": True})
            lock = json.loads(setup_flow.lock_path(Path(tmp)).read_text())
        text = json.dumps(lock)
        self.assertIn('"granite4.2:8b"', text, out)
        self.assertNotIn("granite4.2:8b-q8_0\"", json.dumps({k: v for k, v in lock.items() if k != "planned_model"}))


@needs_browser
class GrokPageRepairTests(unittest.TestCase):
    """The coding-job path: Grok writes a page, the click test fails, the failure goes back, round 2 passes."""

    def setUp(self):
        from test_grok_full import FakeGrok
        self.FakeGrok = FakeGrok
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        self.patches = [
            mock.patch.dict(os.environ, {"PODCODER_CODING_WORKSPACE": str(Path(self.tmp.name) / "coding")}),
            mock.patch.object(xai_client, "api_key", return_value="test-key-not-real"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _job(self, text, *answers):
        code, body = product_api.try_handle("POST", "/api/simco/turn", {"text": text}, self.state)
        self.assertEqual(body.get("intent"), "coding", body)
        fake = self.FakeGrok(*answers)
        with mock.patch.object(xai_client, "chat", fake):
            product_api.try_handle("POST", "/api/coding/run", {"job_id": body["job_id"], "confirm": "RUN", "wait": True}, self.state)
        code, job = product_api.try_handle("GET", f"/api/coding/status/{body['job_id']}", None, self.state)
        return job, fake

    def test_tip_calculator_repaired_in_one_round(self):
        flawed = {"files": [{"path": "index.html", "content": page("tip_flawed.html")}], "entry": None, "summary": "tip calculator"}
        fixed = {"files": [{"path": "index.html", "content": page("tip_fixed.html")}], "entry": None, "summary": "tip calculator"}
        job, fake = self._job(REQ["tip"], flawed, fixed)
        self.assertIn("ONE self-contained web page", fake.calls[0][-1]["content"])
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(job["result"]["repair_rounds"], 1)
        self.assertIn("115", fake.calls[1][-1]["content"])
        self.assertIn("I tested it in a browser", job["everyday"])

    def test_todo_that_never_works_is_failed_honestly(self):
        flawed = {"files": [{"path": "index.html", "content": page("todo_flawed.html")}], "entry": None}
        job, fake = self._job(REQ["todo"], flawed, flawed, flawed)
        self.assertEqual(job["status"], "failed", job)
        self.assertEqual(len(fake.calls), 3)
        self.assertNotIn("Done", job["everyday"])
        self.assertIn("fix it", job["everyday"])


if __name__ == "__main__":
    unittest.main()


@needs_browser
class CalcTurnTests(unittest.TestCase):
    """Typed sentence #3 end to end through /api/simco/turn with Grok as the page writer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.p = mock.patch.object(xai_client, "api_key", return_value="test-key-not-real")
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def turn(self, text):
        code, body = product_api.try_handle("POST", "/api/simco/turn", {"text": text}, self.state)
        self.assertEqual(code, 200, body)
        return body

    def test_broken_then_fix_it(self):
        broken = {"ok": True, "text": page("granite_3090_calc.html"), "backend": "grok", "model": "grok-test"}
        with mock.patch.object(llm_router, "complete", return_value=broken) as fake:
            body = self.turn(REQ["calc"])
        self.assertEqual(fake.call_count, 3)  # first answer + 2 repair rounds
        self.assertFalse(body.get("verified"), body)
        self.assertNotIn(CANNED, body["everyday"])
        self.assertIn("fix it", body["everyday"])
        good = {"ok": True, "text": page("calc_fixed.html"), "backend": "grok", "model": "grok-test"}
        with mock.patch.object(llm_router, "complete", return_value=good):
            again = self.turn("fix it")
        self.assertTrue(again.get("verified"), again)
        self.assertIn("7 × 8 = shows 56", again["everyday"])
