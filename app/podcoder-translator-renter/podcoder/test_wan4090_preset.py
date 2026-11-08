#!/usr/bin/env python3
"""Wan 2.2 video - RTX 4090 machine preset. No Vast calls, no rent, no video generation."""
from __future__ import annotations

import importlib.util
import itertools
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import install_hook  # noqa: E402
import machine_presets  # noqa: E402
import product_api  # noqa: E402

PRESET_DIR = ROOT / "presets" / "wan22_video_rtx4090"
NAME = "Wan 2.2 video - RTX 4090"

spec = importlib.util.spec_from_file_location("wan4090_controller", PRESET_DIR / "controller.py")
ctl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctl)

GOOD_OFFER = {"id": 55948366, "machine_id": 154106, "gpu_name": "RTX 4090", "num_gpus": 1, "verified": True,
              "geolocation": "Texas, US", "dph_total": 0.4222, "inet_down": 4319.2, "reliability2": 0.9901}


class FakeVast:
    """Records every call. credit() replays a list; create/destroy are fake."""

    def __init__(self, credits, offers=None, running=True):
        self.credits = list(credits)
        self.offers = [GOOD_OFFER] if offers is None else offers
        self.calls: list[tuple] = []
        self.alive: set[int] = set()
        self.running = running

    def credit(self):
        self.calls.append(("credit",))
        return self.credits.pop(0) if len(self.credits) > 1 else self.credits[0]

    def search(self, q):
        self.calls.append(("search", q))
        return list(self.offers)

    def list_instances(self):
        self.calls.append(("list",))
        return [{"id": i, "actual_status": "running" if self.running else "exited", "ssh_host": "ssh5.vast.ai", "ssh_port": 12345}
                for i in self.alive]

    def create(self, offer_id, label, image, disk):
        self.calls.append(("create", offer_id, label, image, disk))
        self.alive.add(777)
        return 777

    def destroy(self, iid):
        self.calls.append(("destroy", iid))
        self.alive.discard(int(iid))
        return True

    def billable(self):
        return [c for c in self.calls if c[0] == "create"]


class FakeRunner:
    def __init__(self, host, port):
        self.commands: list[str] = []
        FakeRunner.last = self

    def put(self, files):
        for f in files:
            assert Path(f).is_file(), f
        return 0

    def run(self, command):
        self.commands.append(command)
        return 0

    def get(self, name, local):
        return 0

    def abort(self):
        pass


def confirm(state: Path, preset="wan22_video_rtx4090", used=False):
    rec = {"confirm": "RENT", "preset": preset, "preset_used": used}
    (state / "rent-confirm.json").write_text(json.dumps(rec), encoding="utf-8")


class PresetLoads(unittest.TestCase):
    def test_preset_loads_with_exact_name(self):
        p = machine_presets.get("wan22_video_rtx4090")
        self.assertEqual(p["name"], NAME)
        self.assertEqual(p["role"], "video")
        self.assertIn(NAME, [x["name"] for x in machine_presets.describe()["presets"]])
        self.assertFalse(machine_presets.describe()["picking_rents"])

    def test_fields_match_source_run(self):
        p = ctl.load_preset()
        f = p["offer_filter"]
        self.assertEqual(f["gpu_names"], ["RTX 4090"])
        self.assertTrue(f["verified"])
        self.assertEqual(f["country"], "US")
        self.assertLessEqual(f["max_dph_usd"], 0.5)
        self.assertGreaterEqual(f["max_dph_usd"], 0.4222)
        self.assertEqual(f["min_inet_down_mbps"], 1000)
        self.assertEqual(f["min_reliability"], 0.99)
        self.assertEqual(p["image"], "pytorch/pytorch:2.14.1-cuda12.6-cudnn9-runtime")
        self.assertEqual(p["disk_gb"], 80)
        r = p["render"]
        self.assertEqual((r["width"], r["height"], r["frames"], r["fps"]), (704, 1280, 121, 24))
        self.assertEqual(p["model"]["checkpoint"], "wan2.2_ti2v_5B_fp16.safetensors")
        self.assertEqual(p["budget"]["source"], "live_credit_drop")
        self.assertTrue(p["destroy_after_last_job"])
        self.assertEqual(p["requires_confirm"], "RENT")
        self.assertIn("lipsync", p["separate_from"])
        for name in p["scripts"].values():
            self.assertTrue((PRESET_DIR / name).is_file(), name)
        for name in p["pack_scripts"]:
            self.assertTrue((ROOT / name).is_file(), name)
        gen = (PRESET_DIR / "gen_one.py").read_text(encoding="utf-8")
        self.assertIn('"width":704,"height":1280,"length":121', gen)
        self.assertIn('"fps":24', gen)

    def test_query_and_client_side_filters(self):
        p = ctl.load_preset()
        q = ctl.vast_query(p)
        self.assertEqual(q["gpu_name"], {"in": ["RTX 4090"]})
        self.assertEqual(q["verified"], {"eq": True})
        self.assertEqual(q["geolocation"], {"in": ["US"]})
        self.assertEqual(q["inet_down"], {"gte": 1000.0})
        self.assertEqual(q["dph_total"], {"lte": 0.5})
        self.assertTrue(ctl.offer_ok(p, GOOD_OFFER)[0])
        for change in ({"gpu_name": "RTX 3090"}, {"geolocation": "New Brunswick, CA"}, {"verified": False},
                       {"dph_total": 0.61}, {"inet_down": 500}, {"reliability2": 0.95}):
            self.assertFalse(ctl.offer_ok(p, {**GOOD_OFFER, **change})[0], change)

    def test_granite_and_wan_never_together(self):
        p = ctl.load_preset()
        self.assertFalse(p["vram"]["granite_with_wan"])
        self.assertNotEqual(p["role"], "combined")
        launch = (PRESET_DIR / "launch.sh").read_text(encoding="utf-8")
        self.assertIn("refuse: Granite is loaded", launch)
        install = (PRESET_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn("PODCODER_UNLOAD_GRANITE=1", install)
        self.assertNotIn("ollama pull", install)


class PickingDoesNotRent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, **kw):
        return {"preset": "wan22_video_rtx4090", "role": "video", "gpu": "RTX 4090", "inet_down": 4319,
                "price_hr": 0.4222, "region": "Texas, US", "disk_gb": 80, **kw}

    def test_pick_without_confirm_is_dry_run(self):
        out = install_hook.accept_rent(self.body(dry_run=True), self.state)
        self.assertFalse(out["rented"])
        self.assertTrue(out["dry_run"])
        self.assertFalse((self.state / "rent-confirm.json").exists())
        out = install_hook.accept_rent(self.body(dry_run=False, confirm="rent"), self.state)
        self.assertEqual(out["http"], 400)
        self.assertFalse((self.state / "rent-confirm.json").exists())

    def test_confirm_rent_records_preset_but_does_not_rent(self):
        out = install_hook.accept_rent(self.body(dry_run=False, confirm="RENT"), self.state)
        self.assertEqual(out["http"], 200)
        self.assertFalse(out["rented"])
        self.assertEqual(out["vast_calls"], 0)
        self.assertEqual(out["preset_name"], NAME)
        self.assertEqual(out["install"], "needs_controller")
        rec = json.loads((self.state / "rent-confirm.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["preset"], "wan22_video_rtx4090")
        self.assertFalse(rec["preset_used"])
        self.assertEqual(rec["role"], "video")

    def test_preset_rejects_wrong_offer_and_role(self):
        out = install_hook.accept_rent(self.body(dry_run=False, confirm="RENT", gpu="RTX 3090"), self.state)
        self.assertEqual(out["http"], 403)
        out = install_hook.accept_rent(self.body(dry_run=False, confirm="RENT", inet_down=950), self.state)
        self.assertEqual(out["http"], 403)
        out = install_hook.accept_rent(self.body(dry_run=False, confirm="RENT", role="coding"), self.state)
        self.assertEqual(out["http"], 400)
        self.assertFalse((self.state / "rent-confirm.json").exists())

    def test_api_presets_lists_it(self):
        code, body = product_api.try_handle("GET", "/api/presets", {}, self.state)
        self.assertEqual(code, 200)
        self.assertEqual(body["vast_calls"], 0)
        self.assertIn(NAME, [p["name"] for p in body["presets"]])

    def test_controller_refuses_without_live_or_confirm(self):
        api = FakeVast([5.0])
        c = ctl.Controller(api, ctl.load_preset(), self.state, runner_factory=FakeRunner, live=False, sleep=lambda s: None)
        with self.assertRaises(ctl.GateClosed):
            c.run()
        c = ctl.Controller(api, ctl.load_preset(), self.state, runner_factory=FakeRunner, live=True, sleep=lambda s: None)
        with self.assertRaises(ctl.GateClosed):
            c.run()
        confirm(self.state, preset="")
        with self.assertRaises(ctl.GateClosed):
            c.run()
        confirm(self.state, used=True)
        with self.assertRaises(ctl.GateClosed):
            c.run()
        self.assertEqual(api.calls, [])

    def test_controller_runs_jobs_then_destroys_and_consumes_confirm(self):
        confirm(self.state)
        api = FakeVast([5.0, 4.98, 4.95, 4.90, 4.85, 4.80])
        jobs = [{"name": "p0a", "env": {"SHOT": "p0a"}, "fetch": "p0a.mp4"},
                {"name": "p0b", "env": {"SHOT": "p0b"}, "fetch": "p0b.mp4"}]
        c = ctl.Controller(api, ctl.load_preset(), self.state, jobs=jobs, runner_factory=FakeRunner,
                           live=True, sleep=lambda s: None, watch_s=3600)
        res = c.run()
        self.assertEqual(res["status"], "jobs_done")
        self.assertEqual(res["jobs_ok"], ["p0a", "p0b"])
        self.assertTrue(res["destroyed"])
        self.assertEqual(len(api.billable()), 1)
        self.assertIn(("destroy", 777), api.calls)
        self.assertEqual(api.alive, set())
        cmds = FakeRunner.last.commands
        self.assertEqual(cmds[:2], ["cd /root/job && bash install.sh", "cd /root/job && bash launch.sh"])
        self.assertIn("SHOT=p0a", cmds[2])
        rec = json.loads((self.state / "rent-confirm.json").read_text(encoding="utf-8"))
        self.assertTrue(rec["preset_used"])
        with self.assertRaises(ctl.GateClosed):  # one Confirm Rent = one rent
            ctl.Controller(api, ctl.load_preset(), self.state, live=True).run()

    def test_budget_uses_live_credit_drop_not_time_times_rate(self):
        confirm(self.state)
        # credit falls $1.45 after the first job: cap 1.50 - margin 0.10 -> stop before job 2, destroy
        api = FakeVast([5.0, 5.0, 5.0, 5.0, 3.55])
        jobs = [{"name": f"j{i}", "env": {"SHOT": f"j{i}"}} for i in range(3)]
        c = ctl.Controller(api, ctl.load_preset(), self.state, jobs=jobs, runner_factory=FakeRunner,
                           live=True, sleep=lambda s: None, watch_s=3600)
        res = c.run()
        self.assertEqual(res["status"], "budget_stop")
        self.assertEqual(res["jobs_ok"], ["j0"])
        self.assertTrue(res["destroyed"])
        self.assertIn(("destroy", 777), api.calls)
        # a clock 100 hours later with flat credit never trips the budget: time x rate is not used
        confirm(self.state)
        api = FakeVast([5.0])
        hours = itertools.count(0, 100 * 3600)
        c = ctl.Controller(api, ctl.load_preset(), self.state, jobs=jobs, runner_factory=FakeRunner, live=True,
                           sleep=lambda s: None, clock=lambda: next(hours), boot_max_s=10**12, watch_s=3600)
        self.assertEqual(c.run()["jobs_ok"], ["j0", "j1", "j2"])

    def test_unreadable_credit_fails_closed(self):
        confirm(self.state)
        api = FakeVast([5.0])
        jobs = [{"name": "j0", "env": {"SHOT": "j0"}}]
        c = ctl.Controller(api, ctl.load_preset(), self.state, jobs=jobs, runner_factory=FakeRunner,
                           live=True, sleep=lambda s: None, watch_s=3600)
        c.credit_before = 5.0
        api.credit = lambda: (_ for _ in ()).throw(RuntimeError("down"))
        c.spent(); c.spent()
        with self.assertRaises(ctl.BudgetStop):
            c.spent()


class UiAndSecrets(unittest.TestCase):
    def test_advanced_rent_ui_offers_preset_through_confirm_rent(self):
        for path in (ROOT.parent / "local" / "translator.html", ROOT / "seeds" / "translator.html"):
            html = path.read_text(encoding="utf-8")
            self.assertIn(f'<option value="video" data-preset="wan22_video_rtx4090">{NAME}</option>', html)
            self.assertIn("preset: pickedPreset()", html)
            self.assertIn('id="confirmRent"', html)
            self.assertIn('id="rentWords"', html)

    def test_no_secrets_in_preset_files(self):
        files = [p for p in PRESET_DIR.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        files += [ROOT / "machine_presets.py"]
        bad = [
            re.compile(r"Bearer\s+[A-Za-z0-9]{20,}"),
            re.compile(r"(api[_-]?key|token|secret|password)\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]", re.I),
            re.compile(r"\b[a-f0-9]{48,}\b"),
            re.compile(r"trycloudflare\.com/[A-Za-z0-9]"),
            re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            for rx in bad:
                self.assertIsNone(rx.search(text), f"{path.name}: {rx.pattern}")
        doc = json.loads((PRESET_DIR / "preset.json").read_text(encoding="utf-8"))
        self.assertFalse(doc["secrets"]["stored_in_files"])
        self.assertNotIn("token", json.dumps(doc["source_run"]).lower())
        self.assertIn("key=<hidden>", repr(ctl.VastREST(key="x" * 40)))

    def test_run_state_has_no_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            confirm(state)
            api = FakeVast([5.0, 4.9])
            ctl.Controller(api, ctl.load_preset(), state, jobs=[], runner_factory=FakeRunner, live=True,
                           sleep=lambda s: None, watch_s=3600).run()
            text = (state / "wan4090-run.json").read_text(encoding="utf-8")
            self.assertNotIn("token", text.lower())
            self.assertNotIn("Bearer", text)


if __name__ == "__main__":
    unittest.main()
