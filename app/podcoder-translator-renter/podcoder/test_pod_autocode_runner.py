#!/usr/bin/env python3
"""Master-sync checks: Granite first, max ONE Aider round per task, seed verify. No GPU, no network."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pod_autocode_runner as r  # noqa: E402

SEED = "<!DOCTYPE html><html><head><title>Chat Translator</title></head><body><div id=\"transcript\"></div><script></script></body></html>"


class RunnerMasterSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        root = self.tmp / "podcoder"
        (root / "seeds").mkdir(parents=True)
        (root / "seeds" / "translator.html").write_text(SEED, encoding="utf-8")
        tpl = HERE / "translator-everyday-typea-master-batch.json"
        if tpl.is_file():
            shutil.copy2(tpl, root / tpl.name)
        shutil.copy2(HERE / "pod_autocode_runner.py", root / "pod_autocode_runner.py")
        self.calls: list[str] = []
        aider = self.tmp / "aider.sh"
        aider.write_text(f"#!/bin/bash\necho aider >> {self.tmp}/aider.log\nexit 0\n", encoding="utf-8")
        aider.chmod(0o755)
        self.patches = [
            mock.patch.object(r, "ROOT", root),
            mock.patch.object(r, "INBOX", root / "missions" / "inbox"),
            mock.patch.object(r, "STATUS_DIR", root / "status"),
            mock.patch.object(r, "DEFAULT_TEMPLATE", root / "translator-everyday-typea-master-batch.json"),
            mock.patch.object(r, "AIDER", aider),
        ]
        for p in self.patches:
            p.start()
        self.root = root

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def aider_runs(self) -> int:
        log = self.tmp / "aider.log"
        return len(log.read_text().splitlines()) if log.is_file() else 0

    def fake_granite(self, payload, abort_s=0):
        self.calls.append("granite")
        return "no html here", {"error": None}

    def test_seed_and_objective_survive_into_type_a(self):
        payload = r.build_type_a_payload("add status line", SEED, "Add mission status line", mission_id="m1")
        self.assertIn("seed verify ok", r.verify_seed_in_payload(payload, SEED, "Add mission status line"))

    def test_seed_verify_fails_loudly_when_seed_dropped(self):
        payload = r.build_type_a_payload("x", None, "Add mission status line", mission_id="m1")
        with self.assertRaises(r.SeedVerifyError) as cm:
            r.verify_seed_in_payload(payload, SEED, "Add mission status line")
        self.assertIn("seed", str(cm.exception))

    def test_seed_verify_fails_loudly_when_objective_dropped(self):
        payload = r.build_type_a_payload("x", SEED, "something else", mission_id="m1")
        with self.assertRaises(r.SeedVerifyError) as cm:
            r.verify_seed_in_payload(payload, SEED, "Add mission status line")
        self.assertIn("objective", str(cm.exception))

    def test_one_shot_stops_before_granite_on_seed_verify_fail(self):
        bad = lambda *a, **k: {"messages": [{"role": "user", "content": "invent a calculator"}]}
        with mock.patch.object(r, "build_type_a_payload", bad), mock.patch.object(r, "granite_chat", self.fake_granite):
            st = r.run_one_shot({"id": "m-sv", "everyday": "add status", "objective": "Add status line",
                                 "seed": str(self.root / "seeds" / "translator.html"), "allowAider": True})
        self.assertEqual(st["status"], "fail")
        self.assertEqual(st["breaker"], "SEED VERIFY FAIL")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.aider_runs(), 0)

    def test_granite_first_then_at_most_one_aider_round(self):
        with mock.patch.object(r, "granite_chat", self.fake_granite):
            mission = {"id": "m-aider", "everyday": "add status", "objective": "Add status line",
                       "seed": str(self.root / "seeds" / "translator.html"), "allowAider": True,
                       "maxSurgicalRounds": 5}
            st = r.run_one_shot(mission)
        self.assertEqual(self.calls, ["granite", "granite"])  # raw Granite attempts ran first
        self.assertEqual(self.aider_runs(), 1)
        self.assertEqual(st["aider_rounds"], 1)
        self.assertFalse(r.take_aider_round(mission))  # cap cannot be raised to 5

    def test_no_aider_when_not_allowed(self):
        with mock.patch.object(r, "granite_chat", self.fake_granite):
            st = r.run_one_shot({"id": "m-noaider", "everyday": "add status", "objective": "Add status line",
                                 "seed": str(self.root / "seeds" / "translator.html"), "allowAider": False})
        self.assertEqual(self.aider_runs(), 0)
        self.assertEqual(st["aider_rounds"], 0)

    def test_take_aider_round_cap(self):
        m = {"allowAider": True}
        self.assertTrue(r.take_aider_round(m))
        self.assertFalse(r.take_aider_round(m))
        self.assertFalse(r.take_aider_round({"allowAider": True, "maxSurgicalRounds": 0}))

    def test_dry_verify_includes_seed_verify(self):
        if not (self.root / "translator-everyday-typea-master-batch.json").is_file():
            self.skipTest("no translator batch next to runner")
        st = r.run_dry_verify({"id": "m-dry", "everyday": "dry verify onpod runner",
                               "seed": str(self.root / "seeds" / "translator.html"),
                               "batchId": "batch-7-onpod-runner", "dryVerify": True})
        self.assertEqual(st["batches"][0]["id"], "seed-verify")
        self.assertEqual(st["batches"][0]["status"], "pass")
        self.assertEqual(st["status"], "pass")

    def test_policy_files_cap_aider_at_one(self):
        tr = HERE / "translator-everyday-typea-master-batch.json"
        tp = HERE / "master-batch-template.json"
        if tr.is_file():
            d = json.loads(tr.read_text())
            self.assertEqual(d["executorPolicy"]["aider"]["maxRoundsPerTask"], 1)
            self.assertTrue(d["executorPolicy"]["seedVerify"]["required"])
        if tp.is_file():
            d = json.loads(tp.read_text())
            self.assertEqual(d["aiderPolicy"]["maxAiderRoundsPerTask"], 1)
        md = HERE / "ONPOD_MASTER_LOOP.md"
        if md.is_file():
            txt = md.read_text()
            self.assertIn("at most ONE surgical Aider round per task", txt)
            self.assertIn("Seed verify", txt)


if __name__ == "__main__":
    unittest.main()
