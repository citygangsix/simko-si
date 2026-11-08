#!/usr/bin/env python3
"""Offline product checks. No Vast rent or destroy."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import auth_accounts
import compute_profiles
import everyday_to_granite
import everyday_to_wan
import gallery
import granite_to_everyday
import hardware_probe
import install_hook
import lifebook_memory
import offers
import offline_sync
import product_api
import roles
import sessions
import vault


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        install_hook._ACTIVE["on"] = False
        for key in ("PODCODER_SSH_HOST", "PODCODER_SSH_PORT", "PODCODER_SSH_USER", "PODCODER_MODEL", "PODCODER_COMPUTE"):
            os.environ.pop(key, None)

    def tearDown(self):
        install_hook._ACTIVE["on"] = False
        self.tmp.cleanup()

    def test_bandwidth_floor_and_disk(self):
        catalog = offers.list_offers()
        self.assertEqual(catalog["baseline_inet_down_mbps"], 900)
        self.assertEqual(catalog["disk_gb_default"], 150)
        self.assertTrue(catalog["recommended"])
        self.assertTrue(all(row["inet_down"] >= 900 for row in catalog["recommended"]))
        self.assertFalse(any(row.get("instance_id") == "58092881" for row in catalog["recommended"]))
        self.assertFalse(any(row.get("instance_id") == "58109814" for row in catalog["recommended"]))
        calls = []

        def runner(*args):
            calls.append(args)
            return 0, install_hook.SMOKE_BANNER

        rejected = install_hook.handle_rent(
            {"confirm": "RENT", "dry_run": False, "inet_down": 180, "ssh_host": "10.4.4.4", "role": "coding"},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=runner,
            sync=True,
        )
        self.assertEqual(rejected["install"], "rejected_bandwidth")
        self.assertEqual(rejected["vast_calls"], 0)
        self.assertFalse(rejected["destroyed"])
        self.assertEqual(calls, [])

    def test_roles_default_separate_and_video_does_not_unlock_chat(self):
        self.assertEqual(roles.resolve_role(""), "coding")
        self.assertEqual(roles.resolve_role("video"), "video")
        video_cmd = roles.remote_command("video")
        self.assertIn("PODCODER_ROLE=video", video_cmd)
        self.assertIn("install-video-comfy-wan.sh", video_cmd)
        self.assertNotIn("install-on-pod-q8.sh &&", video_cmd.split("bash", 1)[-1])
        result = install_hook.handle_rent(
            {
                "confirm": "RENT",
                "dry_run": False,
                "role": "video",
                "inet_down": 1200,
                "inet_up": 800,
                "disk_gb": 150,
                "ssh_host": "10.8.8.8",
            },
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=lambda ssh, src, on_line: (0, "PODCODER_VIDEO_READY\n"),
            sync=True,
        )
        self.assertEqual(result["install_script"], "install-video-comfy-wan.sh")
        self.assertEqual(result["install"], "pass")
        self.assertFalse(result["coding_allowed"])
        self.assertEqual(result["vast_calls"], 0)
        self.assertFalse(result["destroyed"])

    def test_destroy_never_calls_vast_and_protects_utah(self):
        code, body = product_api.destroy_result("58092881")
        self.assertEqual(code, 403)
        self.assertFalse(body["destroyed"])
        self.assertEqual(body["vast_calls"], 0)
        code, body = product_api.destroy_result("999")
        self.assertEqual(code, 403)
        self.assertFalse(body["destroyed"])
        self.assertEqual(body["vast_calls"], 0)
        self.assertEqual(body["reference_instance_id"], "58092881")
        self.assertIn("does not auto-destroy", body["error"])
        self.assertNotIn("protected", body["error"])

    def test_reverse_and_wan_prompts(self):
        empty = granite_to_everyday.translate("")
        self.assertFalse(empty["ok"])
        self.assertIn("didn't finish", empty["everyday"])
        self.assertNotIn("<", empty["everyday"])
        html = "<!DOCTYPE html><html><body><div id='display'></div><button id='*'></button></body></html>"
        # A page with no digit buttons cannot show 56, so the line must not promise it (it used to).
        ok = granite_to_everyday.translate(html, feature="mul", ask="add multiply")
        self.assertFalse(ok["ok"])
        self.assertNotIn("you should see 56", ok["everyday"])
        self.assertIn("doesn't work yet", ok["everyday"])
        self.assertIn("fix it", ok["everyday"])
        self.assertNotIn("<", ok["everyday"])
        self.assertIsNone(ok["model"])
        timed = granite_to_everyday.translate("timeout: no useful tokens")
        self.assertFalse(timed["ok"])
        self.assertIn("Aider once", timed["everyday"])
        missing = everyday_to_wan.translate("  ")
        self.assertFalse(missing["ok"])
        prompt = everyday_to_wan.translate("a red kite over a lake")
        self.assertEqual(prompt["a1"]["checkpoint"], "Wan2.2-TI2V-5B")
        self.assertIn("24GB", prompt["vram"])

    def test_sessions_memory_vault_and_compute(self):
        first = sessions.create_session(self.state, "joseph", "one")
        second = sessions.create_session(self.state, "joseph", "two")
        self.assertEqual(first["model_loads"], 1)
        self.assertEqual(second["model_loads"], 1)
        queued = sessions.enqueue(self.state, "joseph", first["session"]["id"], "hello")
        self.assertEqual(queued["model_loads"], 1)
        self.assertEqual(queued["vast_calls"], 0)
        stored = sessions.get_session(self.state, "joseph", first["session"]["id"])
        self.assertEqual(stored["session"]["messages"][0]["text"], "hello")
        self.assertEqual(stored["session"]["messages"][0]["role"], "user")
        listed = lifebook_memory.list_memory(self.state, "joseph")
        self.assertEqual(len(listed["categories"]), 13)
        self.assertIn("sex_and_sensuality", {row["id"] for row in listed["categories"]})
        added = lifebook_memory.add_note(self.state, "joseph", "career", "ship the renter")
        self.assertTrue(added["ok"])
        self.assertNotIn("score", listed)
        stored = vault.put(self.state, "joseph", "phrase", {"ssn": "000-00-0000", "email": "a@example.com"})
        self.assertEqual(stored["stored"], ["email", "ssn"])
        blob = (self.state / "vault" / "joseph.bin").read_bytes()
        self.assertNotIn(b"000-00-0000", blob)
        self.assertNotIn(b"a@example.com", blob)
        opened = vault.reveal(self.state, "joseph", "phrase")
        self.assertEqual(opened["secrets"]["ssn"], "000-00-0000")
        profile = compute_profiles.save(self.state, "local")
        self.assertEqual(profile["model"], "granite4.2:8b")
        self.assertEqual(profile["compute"], "local")

    def test_video_script_smoke_without_download(self):
        work = Path(self.tmp.name) / "video"
        work.mkdir()
        env = os.environ.copy()
        env.update({
            "PODCODER_ROLE": "video",
            "PODCODER_SKIP_DOWNLOAD": "1",
            "PODCODER_VIDEO_DEST": str(work / "dest"),
            "PODCODER_VRAM_LOCK": str(work / "vram.json"),
        })
        proc = subprocess.run(
            ["bash", str(ROOT / "install-video-comfy-wan.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PODCODER_VIDEO_READY", proc.stdout)
        self.assertNotIn("PODCODER_INSTALL_SMOKE_PASS", proc.stdout)
        self.assertTrue((work / "dest" / "gallery" / "index.html").is_file())
        lock = json.loads((work / "vram.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["holder"], "video")
        self.assertFalse(lock["simultaneous_granite_and_wan"])

    def test_download_follows_role_and_never_rents(self):
        picked = offers.pick_for_role("coding")
        self.assertIsNotNone(picked)
        self.assertIn("3090", picked["gpu"])
        self.assertGreaterEqual(picked["inet_down"], 900)
        self.assertGreaterEqual(picked["disk_gb"], 150)
        calls = []

        def runner(ssh, src, on_line):
            calls.append(ssh)
            return 0, "PODCODER_LOCAL_SMOKE_PASS\n"

        local = install_hook.handle_download(
            {"compute": "local", "role": "coding", "probe": {"ram_gb": 16, "vram_gb": 0, "disk_free_gb": 100, "gpu": "none"}},
            self.state,
            src_dir=ROOT,
            runner=runner,
            sync=True,
        )
        self.assertEqual(local["vast_calls"], 0)
        self.assertFalse(local["destroyed"])
        self.assertEqual(local["status_word"], "Ready")
        self.assertIn("this laptop", local["message"])
        self.assertIn("granite4.2:8b", local["message"])
        blocked = install_hook.handle_download(
            {"compute": "cloud", "role": "coding"},
            self.state,
            src_dir=ROOT,
            runner=runner,
            sync=True,
        )
        self.assertEqual(blocked["install"], "needs_rent")
        self.assertIn("will not rent", blocked["message"])
        self.assertEqual(len(calls), 1)
        install_hook.accept_rent(
            {"confirm": "RENT", "dry_run": False, "role": "video", "inet_down": 1200, "ssh_host": "10.7.7.7", "ssh_port": 22},
            self.state,
        )

        def cloud_runner(ssh, src, on_line):
            calls.append(ssh)
            return 0, "PODCODER_VIDEO_READY\n"

        video = install_hook.handle_download(
            {"compute": "cloud", "role": "video"},
            self.state,
            src_dir=ROOT,
            runner=cloud_runner,
            sync=True,
        )
        self.assertEqual(video["install_script"], "install-video-comfy-wan.sh")
        self.assertIn("10.7.7.7", video["message"])
        self.assertIn("Wan", video["message"])
        self.assertEqual(video["vast_calls"], 0)
        self.assertNotIn("granite4.2:8b-q8_0", video["message"])

    def test_probe_picks_stack_and_refuses_a_weak_laptop(self):
        aspire32 = hardware_probe.choose("coding", {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 100, "gpu": "Radeon", "cpu": "Ryzen 7000"}, "local")
        self.assertEqual(aspire32["model"], "granite4.2:8b-q5_0")
        self.assertEqual(aspire32["quant"], "Q5")
        self.assertEqual(aspire32["profile"], "local_ram32_q5")
        self.assertNotEqual(aspire32["quant"], "Q4")
        q4 = hardware_probe.choose("coding", {"ram_gb": 16, "vram_gb": 0, "disk_free_gb": 80, "gpu": "none", "cpu": "Ryzen"}, "local")
        self.assertTrue(q4["ok"])
        self.assertEqual(q4["model"], "granite4.2:8b")
        self.assertEqual(q4["quant"], "Q4")
        self.assertEqual(q4["script"], "install-local-aspire.sh")
        self.assertNotIn("q8_0", q4["model"])
        q5 = hardware_probe.choose("coding", {"ram_gb": 31.2, "vram_gb": 24, "disk_free_gb": 200, "gpu": "RTX 3090"}, "local")
        self.assertEqual(q5["model"], "granite4.2:8b-q5_0")
        self.assertEqual(q5["quant"], "Q5")
        self.assertNotEqual(q5["model"], hardware_probe.Q8_MODEL)
        same = hardware_probe.choose("coding", {"ram_gb": 31.2, "vram_gb": 24, "disk_free_gb": 200, "gpu": "RTX 3090", "cpu": "other"}, "local")
        self.assertEqual(same["model"], q5["model"])
        cloud = hardware_probe.choose("coding", {"ram_gb": 4, "vram_gb": 0, "disk_free_gb": 2, "gpu": "none"}, "cloud")
        self.assertEqual(cloud["model"], "granite4.2:8b-q8_0")
        self.assertIn("900", cloud["message"])
        self.assertIn("3090", cloud["message"])
        video = hardware_probe.choose("video", {"ram_gb": 32, "vram_gb": 12, "disk_free_gb": 80, "gpu": "RTX 3080"}, "local")
        self.assertEqual(video["script"], "install-video-comfy-wan.sh")
        self.assertIn("Wan2.2-TI2V-5B", video["stack"])
        self.assertNotIn("granite", video["stack"])
        image = hardware_probe.choose("image", {"ram_gb": 16, "vram_gb": 8, "disk_free_gb": 40, "gpu": "RTX 3070"}, "local")
        self.assertEqual(image["script"], "install-image-role.sh")
        self.assertEqual(image["stack"], "ComfyUI")
        self.assertNotIn("Wan", image["stack"])
        weak = hardware_probe.choose("video", {"ram_gb": 16, "vram_gb": 2, "disk_free_gb": 100, "gpu": "iGPU"}, "local")
        self.assertFalse(weak["ok"])
        self.assertTrue(weak["needs_rent"])
        self.assertIn("will not rent", weak["message"])
        self.assertIn("900", weak["message"])

        def boom(*_args):
            raise AssertionError("weak laptop must not start install")

        blocked = install_hook.handle_download(
            {"compute": "local", "role": "video", "probe": {"ram_gb": 16, "vram_gb": 2, "disk_free_gb": 100, "gpu": "iGPU"}},
            self.state,
            src_dir=ROOT,
            runner=boom,
            sync=True,
        )
        self.assertEqual(blocked["install"], "needs_rent")
        self.assertEqual(blocked["vast_calls"], 0)
        self.assertFalse(blocked["destroyed"])
        self.assertIn("will not rent", blocked["message"])

        def video_runner(ssh, src, on_line):
            return 0, "PODCODER_VIDEO_READY\n"

        ready = install_hook.handle_download(
            {"compute": "local", "role": "video", "probe": {"ram_gb": 32, "vram_gb": 12, "disk_free_gb": 90, "gpu": "RTX 3080"}},
            self.state,
            src_dir=ROOT,
            runner=video_runner,
            sync=True,
        )
        self.assertEqual(ready["install_script"], "install-video-comfy-wan.sh")
        self.assertEqual(ready["status_word"], "Ready")
        self.assertIn("Wan2.2-TI2V-5B", ready["message"])
        self.assertNotIn("q8_0", ready["message"])
        self.assertEqual(ready["vast_calls"], 0)

        def image_runner(ssh, src, on_line):
            return 0, "PODCODER_IMAGE_READY\n"

        picture = install_hook.handle_download(
            {"compute": "local", "role": "image", "probe": {"ram_gb": 16, "vram_gb": 8, "disk_free_gb": 40, "gpu": "RTX 3070"}},
            self.state,
            src_dir=ROOT,
            runner=image_runner,
            sync=True,
        )
        self.assertEqual(picture["install_script"], "install-image-role.sh")
        self.assertIn("ComfyUI", picture["message"])
        self.assertNotIn("Wan", picture["message"])

        def q5_runner(ssh, src, on_line):
            return 0, "PODCODER_LOCAL_SMOKE_PASS\n"

        quant = install_hook.handle_download(
            {"compute": "local", "role": "coding", "probe": {"ram_gb": 32, "vram_gb": 24, "disk_free_gb": 100, "gpu": "RTX 3090"}},
            self.state,
            src_dir=ROOT,
            runner=q5_runner,
            sync=True,
        )
        self.assertEqual(quant["model"], "granite4.2:8b-q5_0")
        self.assertEqual(quant["quant"], "Q5")
        self.assertNotEqual(quant["model"], "granite4.2:8b-q8_0")
        smoke = json.loads((self.state / "local-smoke.json").read_text(encoding="utf-8"))
        self.assertEqual(smoke["model"], "granite4.2:8b-q5_0")
        code, body = product_api.try_handle(
            "POST",
            "/api/probe",
            {"role": "image", "compute": "local", "probe": {"ram_gb": 8, "vram_gb": 2, "disk_free_gb": 10, "gpu": "iGPU"}},
            self.state,
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["vast_calls"], 0)
        self.assertTrue(body["needs_rent"])
        self.assertIn("I confirm RENT", body["message"])
        tiny = hardware_probe.choose("coding", {"ram_gb": 4, "vram_gb": 0, "disk_free_gb": 100, "gpu": "none"}, "local")
        self.assertFalse(tiny["ok"])
        self.assertTrue(tiny["needs_rent"])
        no_vram = hardware_probe.choose("video", {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 200, "gpu": "none"}, "local")
        self.assertTrue(no_vram["needs_rent"])
        self.assertEqual(no_vram["script"], "")

    def test_local_profiles_model_flag_and_reverse_payload(self):
        q5 = json.loads((ROOT / "profiles" / "local_ram32_q5.json").read_text(encoding="utf-8"))
        q4 = json.loads((ROOT / "profiles" / "local_aspire_ryzen7000.json").read_text(encoding="utf-8"))
        cloud = json.loads((ROOT / "profiles" / "cloud_3090.json").read_text(encoding="utf-8"))
        self.assertEqual(q5["model"], "granite4.2:8b-q5_0")
        self.assertEqual(q5["quant"], "Q5")
        self.assertEqual(q5["install"], "install-local-aspire.sh")
        self.assertEqual(q4["model"], "granite4.2:8b")
        self.assertEqual(cloud["model"], "granite4.2:8b-q8_0")
        picked = compute_profiles.profile_for("local", ram_gb=32)
        self.assertEqual(picked["id"], "local_ram32_q5")
        self.assertEqual(picked["model"], "granite4.2:8b-q5_0")
        smaller = compute_profiles.profile_for("local", ram_gb=16)
        self.assertEqual(smaller["id"], "local_aspire_ryzen7000")
        self.assertEqual(smaller["model"], "granite4.2:8b")
        saved = compute_profiles.save(self.state, "local", "granite4.2:8b-q5_0")
        self.assertEqual(saved["model"], "granite4.2:8b-q5_0")
        self.assertEqual(saved["profile"], "local_ram32_q5")
        os.environ["PODCODER_MODEL"] = "granite4.2:8b-q5_0"
        try:
            flagged = compute_profiles.profile_for("local", ram_gb=16)
            self.assertEqual(flagged["model"], "granite4.2:8b-q5_0")
            self.assertTrue(flagged["model_override"])
        finally:
            os.environ.pop("PODCODER_MODEL", None)
        plain = everyday_to_granite.translate("make a calculator")
        self.assertEqual(plain["model"], "granite4.2:8b-q8_0")
        local_payload = everyday_to_granite.translate("make a calculator", model="granite4.2:8b-q5_0")
        self.assertEqual(local_payload["payload"]["model"], "granite4.2:8b-q5_0")
        env = os.environ.copy()
        env["PODCODER_MODEL"] = "granite4.2:8b-q5_0"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "everyday_to_granite.py"), "-t", "make a calculator"],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["model"], "granite4.2:8b-q5_0")
        flagged_cli = subprocess.run(
            [sys.executable, str(ROOT / "everyday_to_granite.py"), "--model", "granite4.2:8b-q5_0", "-t", "add multiply"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(json.loads(flagged_cli.stdout)["model"], "granite4.2:8b-q5_0")
        server = (ROOT.parent / "local" / "server.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/probe"', server)
        self.assertIn("hardware_probe.advise", server)
        chat = (ROOT.parent / "local" / "chat.html").read_text(encoding="utf-8")
        self.assertIn("await loadModel()", chat)
        self.assertIn('"/api/probe"', chat)
        self.assertNotIn('"dry_run": true', chat)
        self.assertNotIn("dry_run: true", chat)

    def test_local_download_dry_run_follows_the_script(self):
        os.environ["PODCODER_DRY_RUN_HOLD"] = "0.6"
        try:
            started = install_hook.handle_download(
                {
                    "compute": "local",
                    "role": "coding",
                    "dry_run": True,
                    "probe": {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 100, "gpu": "Radeon"},
                },
                self.state,
                src_dir=ROOT,
                sync=False,
            )
            self.assertEqual(started["status_word"], "Downloading")
            self.assertEqual(started["install"], "started")
            self.assertEqual(started["model"], "granite4.2:8b-q5_0")
            self.assertEqual(started["vast_calls"], 0)
            self.assertFalse(started["destroyed"])
            status = {}
            for _ in range(40):
                status = install_hook.public_status(self.state)
                if status.get("status") == "pass":
                    break
                time.sleep(0.1)
        finally:
            os.environ.pop("PODCODER_DRY_RUN_HOLD", None)
            for _ in range(40):
                if not install_hook._ACTIVE["on"]:
                    break
                time.sleep(0.1)
        self.assertEqual(status.get("status"), "pass")
        self.assertEqual(status.get("mode"), "dry_run")
        self.assertEqual(status.get("status_word"), "Ready")
        self.assertFalse(status.get("coding_allowed"))
        self.assertEqual(status.get("vast_calls"), 0)
        self.assertIn("script=install-local-aspire.sh", status.get("tail") or "")
        self.assertIn("model=granite4.2:8b-q5_0", status.get("tail") or "")
        self.assertIn("PODCODER_DRY_RUN_OK", status.get("tail") or "")
        self.assertFalse((self.state / "local-smoke.json").exists())

    def test_two_chats_stay_independent_and_relay(self):
        first = sessions.create_session(self.state, "joseph", "Alpha")
        second = sessions.create_session(self.state, "joseph", "Beta")
        self.assertEqual(first["vast_calls"], 0)
        alpha = first["session"]["id"]
        beta = second["session"]["id"]
        sessions.append_message(self.state, "joseph", alpha, "alpha only")
        sessions.append_message(self.state, "joseph", beta, "beta only")
        sent = sessions.relay(self.state, "joseph", alpha, beta, "note from A", "A finished the shell")
        self.assertTrue(sent["ok"])
        self.assertEqual(sent["vast_calls"], 0)
        self.assertFalse(sent["destroyed"])
        self.assertEqual(sent["inbound"]["role"], "relay")
        self.assertEqual(sent["inbound"]["from_session_id"], alpha)
        self.assertEqual(sent["outbound"]["role"], "relay_out")
        hist_a = sessions.get_session(self.state, "joseph", alpha)["session"]["messages"]
        hist_b = sessions.get_session(self.state, "joseph", beta)["session"]["messages"]
        self.assertEqual([row["text"] for row in hist_a if row["role"] == "user"], ["alpha only"])
        self.assertNotIn("beta only", [row["text"] for row in hist_a])
        self.assertEqual([row["text"] for row in hist_b if row["role"] == "user"], ["beta only"])
        self.assertNotIn("alpha only", [row["text"] for row in hist_b if row["role"] == "user"])
        inbound = [row for row in hist_b if row["role"] == "relay"]
        self.assertEqual(len(inbound), 1)
        self.assertEqual(inbound[0]["text"], "note from A")
        self.assertEqual(inbound[0]["from_session_id"], alpha)
        self.assertEqual(inbound[0]["from_title"], "Alpha")
        self.assertFalse(any(row["role"] == "user" and row["text"] == "note from A" for row in hist_a))
        self.assertFalse(any(row["role"] == "user" and row["text"] == "note from A" for row in hist_b))
        code, body = product_api.try_handle(
            "POST",
            "/api/sessions",
            {"op": "relay", "user": "joseph", "from_session_id": beta, "to_session_id": alpha, "summary": "Beta saw the note"},
            self.state,
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["vast_calls"], 0)
        again = sessions.get_session(self.state, "joseph", alpha)["session"]["messages"]
        self.assertTrue(any(row["role"] == "relay" and row["from_session_id"] == beta for row in again))
        self.assertEqual([row["text"] for row in again if row["role"] == "user"], ["alpha only"])
        chat = (ROOT.parent / "local" / "chat.html").read_text(encoding="utf-8")
        self.assertIn('id="newChat"', chat)
        self.assertIn('id="sessionList"', chat)
        self.assertIn('id="sendToChat"', chat)
        self.assertIn('op: "relay"', chat)

    def test_email_password_auth_scopes_chats(self):
        code, created = auth_accounts.signup(self.state, "Ada@Example.com", "correct-horse")
        self.assertEqual(code, 200)
        self.assertTrue(created["ok"])
        self.assertEqual(created["email"], "ada@example.com")
        self.assertTrue(created["token"])
        self.assertEqual(created["vast_calls"], 0)
        raw = (self.state / "auth" / "accounts.json").read_text(encoding="utf-8")
        self.assertNotIn("correct-horse", raw)
        self.assertIn("password_hash", raw)
        duplicate = auth_accounts.signup(self.state, "ada@example.com", "correct-horse")
        self.assertEqual(duplicate[0], 400)
        self.assertIn("already", duplicate[1]["error"])
        self.assertNotIn("token", duplicate[1])
        bad = auth_accounts.signin(self.state, "ada@example.com", "wrong-password-1")
        self.assertEqual(bad[0], 400)
        self.assertFalse(bad[1]["ok"])
        self.assertNotIn("token", bad[1])
        self.assertIn("password", bad[1]["error"])
        self.assertEqual(bad[1]["vast_calls"], 0)
        good = auth_accounts.signin(self.state, "ada@example.com", "correct-horse")
        self.assertEqual(good[0], 200)
        token_a = good[1]["token"]
        self.assertEqual(auth_accounts.email_for_token(self.state, token_a), "ada@example.com")
        other = auth_accounts.signup(self.state, "bea@example.com", "another-pass")
        token_b = other[1]["token"]
        made = product_api.try_handle(
            "POST",
            "/api/sessions",
            {"op": "create", "token": token_a, "user": "bea@example.com", "title": "Ada private"},
            self.state,
        )
        self.assertEqual(made[0], 200)
        self.assertEqual(made[1]["session"]["user"], "ada@example.com")
        ada_id = made[1]["session"]["id"]
        listed = product_api.try_handle(
            "POST",
            "/api/sessions",
            {"op": "list", "token": token_b, "user": "ada@example.com"},
            self.state,
        )
        self.assertEqual(listed[1]["sessions"], [])
        self.assertEqual(listed[1]["vast_calls"], 0)
        hidden = product_api.try_handle(
            "POST",
            "/api/sessions",
            {"op": "get", "token": token_b, "session_id": ada_id},
            self.state,
        )
        self.assertFalse(hidden[1]["ok"])
        bea = product_api.try_handle(
            "POST",
            "/api/sessions",
            {"op": "create", "token": token_b, "title": "Bea"},
            self.state,
        )
        bea_id = bea[1]["session"]["id"]
        blocked = product_api.try_handle(
            "POST",
            "/api/sessions",
            {"op": "relay", "token": token_a, "from_session_id": ada_id, "to_session_id": bea_id, "text": "cross account"},
            self.state,
        )
        self.assertFalse(blocked[1]["ok"])
        self.assertEqual(blocked[1]["vast_calls"], 0)
        second = product_api.try_handle(
            "POST",
            "/api/sessions",
            {"op": "create", "token": token_a, "title": "Ada 2"},
            self.state,
        )
        relayed = product_api.try_handle(
            "POST",
            "/api/sessions",
            {
                "op": "relay",
                "token": token_a,
                "from_session_id": ada_id,
                "to_session_id": second[1]["session"]["id"],
                "text": "same account",
            },
            self.state,
        )
        self.assertTrue(relayed[1]["ok"])
        self.assertEqual(relayed[1]["inbound"]["role"], "relay")
        stolen = product_api.try_handle(
            "POST",
            "/api/sessions",
            {"op": "list", "token": "not-a-real-token"},
            self.state,
        )
        self.assertEqual(stolen[0], 401)

    def test_lifebook_tags_and_offline_sync_have_no_grades(self):
        self.assertEqual(lifebook_memory.categorize("ship the career plan"), "career")
        self.assertEqual(lifebook_memory.categorize("hello there"), "")
        tagged = lifebook_memory.tag_turn(self.state, "joseph", "ship the career plan", "s-1")
        self.assertTrue(tagged["tagged"])
        self.assertEqual(tagged["category"], "career")
        self.assertEqual(tagged["tag"]["status"], "in play")
        self.assertNotIn("score", tagged)
        self.assertNotIn("%", json.dumps(tagged))
        self.assertEqual(tagged["vast_calls"], 0)
        well = lifebook_memory.tag_turn(self.state, "joseph", "the career plan is going well", "s-2")
        self.assertEqual(well["tag"]["status"], "doing well")
        for index in range(3, 6):
            lifebook_memory.tag_turn(self.state, "joseph", "ship the career plan", f"s-{index}")
        moved = lifebook_memory.retag_last(self.state, "joseph", "life_vision")
        self.assertEqual(moved["category"], "life_vision")
        self.assertNotIn("score", moved)
        listed = lifebook_memory.list_memory(self.state, "joseph")
        self.assertEqual(len(listed["categories"]), 13)
        self.assertEqual(listed["tags"][-1]["category"], "life_vision")
        self.assertEqual(listed["statuses"]["career"], "in play")
        self.assertEqual(listed["statuses"]["health_fitness"], "not discussed")
        self.assertEqual(listed["statuses"]["life_vision"], "in play")
        self.assertIn("Career has been the main topic", listed["dominance_note"])
        self.assertNotIn("%", listed["dominance_note"])
        self.assertTrue(all("score" not in row for row in listed["categories"]))
        for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY"):
            os.environ.pop(key, None)
        quiet = offline_sync.status(self.state)
        self.assertEqual(quiet["mode"], "offline")
        self.assertFalse(quiet["cloud"])
        self.assertEqual(quiet["vast_calls"], 0)
        os.environ["SUPABASE_URL"] = "https://nexkymqahpkvzzlvivfi.supabase.co"
        os.environ["SUPABASE_ANON_KEY"] = "anon"
        try:
            refused = offline_sync.status(self.state)
        finally:
            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_ANON_KEY", None)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["mode"], "offline")
        self.assertFalse(refused["cloud"])
        self.assertIn("nexkymqahpkvzzlvivfi", refused["refused"])
        sql = (ROOT / "sql" / "podcoder_offline_cache.sql").read_text(encoding="utf-8")
        self.assertIn("podcoder_lifebook_tags", sql)
        self.assertIn("podcoder_session_messages", sql)
        self.assertIn("podcoder_lifebook_dominance", sql)
        self.assertIn("podcoder_sync_queue", sql)
        self.assertIn("wxvjajecvklfjxppawdx", sql)
        self.assertNotIn("score ", sql.lower())
        self.assertIn("status text", sql.lower())
        self.assertIn("nexkymqahpkvzzlvivfi", sql)
        example = (ROOT.parent / "local" / ".env.example").read_text(encoding="utf-8")
        self.assertIn("SUPABASE_URL=\n", example)
        self.assertIn("SUPABASE_ANON_KEY=\n", example)
        self.assertIn("wxvjajecvklfjxppawdx", example)
        self.assertIn("https://wxvjajecvklfjxppawdx.supabase.co", example)
        self.assertNotIn("https://nexkymqahpkvzzlvivfi.supabase.co", example)
        chat = (ROOT.parent / "local" / "chat.html").read_text(encoding="utf-8")
        self.assertIn('id="lifebook"', chat)
        self.assertIn("not discussed", chat)
        self.assertNotIn("0-100", chat)
        self.assertNotIn("0–100", chat)
        self.assertNotIn("floor", chat.lower())
        os.environ["SUPABASE_URL"] = "https://wxvjajecvklfjxppawdx.supabase.co"
        os.environ["SUPABASE_ANON_KEY"] = "example-anon-key"
        try:
            aimed = offline_sync.status(self.state)
        finally:
            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_ANON_KEY", None)
        self.assertEqual(aimed["project_ref"], "wxvjajecvklfjxppawdx")
        self.assertTrue(aimed["configured"])
        self.assertTrue(aimed["anon_key_set"])
        self.assertFalse(aimed["cloud"])
        self.assertNotIn("example-anon-key", json.dumps(aimed))
        self.assertEqual(aimed["vast_calls"], 0)

    def test_password_reset_and_email_confirm(self):
        code, created = auth_accounts.signup(self.state, "ada@example.com", "correct-horse")
        self.assertEqual(code, 200)
        self.assertFalse(created["email_confirmed"])
        self.assertEqual(created["vast_calls"], 0)
        inbox = json.loads((self.state / "auth" / "dev-inbox.json").read_text(encoding="utf-8"))
        confirm = inbox[-1]
        self.assertEqual(confirm["kind"], "confirm")
        self.assertNotIn("correct-horse", json.dumps(inbox))
        bad = auth_accounts.confirm_email(self.state, "not-a-token")
        self.assertEqual(bad[0], 400)
        self.assertFalse(bad[1]["ok"])
        ok = auth_accounts.confirm_email(self.state, confirm["token"])
        self.assertTrue(ok[1]["email_confirmed"])
        self.assertEqual(ok[1]["vast_calls"], 0)
        again = auth_accounts.confirm_email(self.state, confirm["token"])
        self.assertFalse(again[1]["ok"])
        requested = auth_accounts.request_reset(self.state, "ada@example.com")
        self.assertTrue(requested[1]["ok"])
        self.assertEqual(requested[1]["delivered"], "file")
        self.assertEqual(requested[1]["inbox"], "auth/dev-inbox.json")
        self.assertNotIn("correct-horse", json.dumps(requested[1]))
        inbox = json.loads((self.state / "auth" / "dev-inbox.json").read_text(encoding="utf-8"))
        reset_token = [row for row in inbox if row["kind"] == "reset"][-1]["token"]
        missed = auth_accounts.reset_password(self.state, "not-a-token", "new-password-1")
        self.assertFalse(missed[1]["ok"])
        short = auth_accounts.reset_password(self.state, reset_token, "short")
        self.assertFalse(short[1]["ok"])
        changed = auth_accounts.reset_password(self.state, reset_token, "new-password-1")
        self.assertTrue(changed[1]["ok"])
        self.assertEqual(changed[1]["vast_calls"], 0)
        old = auth_accounts.signin(self.state, "ada@example.com", "correct-horse")
        self.assertFalse(old[1]["ok"])
        new = auth_accounts.signin(self.state, "ada@example.com", "new-password-1")
        self.assertTrue(new[1]["ok"])
        raw = (self.state / "auth" / "accounts.json").read_text(encoding="utf-8")
        self.assertNotIn("new-password-1", raw)
        self.assertNotIn("correct-horse", raw)
        unknown = auth_accounts.request_reset(self.state, "nobody@example.com")
        self.assertTrue(unknown[1]["ok"])
        self.assertEqual(unknown[1]["dev_token"], "")

    def test_local_coding_download_reaches_ready_from_the_real_script(self):
        work = Path(self.tmp.name) / "stubs"
        fake = work / "bin"
        fake.mkdir(parents=True)
        log = work / "ollama.log"
        (fake / "ollama").write_text(
            "#!/bin/bash\n"
            f"printf '%s\\n' \"$*\" >> \"{log}\"\n"
            "if [[ \"$1\" == \"show\" ]]; then sleep 0.45; exit 0; fi\n"
            "if [[ \"$1\" == \"list\" ]]; then printf '%s\\n' 'granite4.2:8b-q5_0'; exit 0; fi\n"
            "if [[ \"$1\" == \"pull\" ]]; then echo pull-refused >> \"{log}\"; exit 99; fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        (fake / "curl").write_text(
            "#!/bin/bash\n"
            "if [[ \"$*\" == *install.sh* ]]; then echo refused-install >&2; exit 97; fi\n"
            "if [[ \"$*\" == *api/generate* ]]; then printf '%s\\n' '{\"response\":\"pong\"}'; exit 0; fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        (fake / "aider").write_text("#!/bin/bash\necho 'aider 0.1.0'\nexit 0\n", encoding="utf-8")
        for path in fake.iterdir():
            path.chmod(0o755)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(fake) + os.pathsep + old_path
        os.environ.pop("PODCODER_DRY_RUN", None)
        try:
            before = install_hook.public_status(self.state)
            self.assertEqual(before["status_word"], "Waiting")
            started = install_hook.handle_download(
                {
                    "compute": "local",
                    "role": "coding",
                    "dry_run": False,
                    "probe": {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 100, "gpu": "Radeon", "cpu": "Ryzen 7000"},
                },
                self.state,
                src_dir=ROOT,
                sync=False,
            )
            self.assertEqual(started["status_word"], "Downloading")
            self.assertEqual(started["model"], "granite4.2:8b-q5_0")
            self.assertEqual(started["vast_calls"], 0)
            self.assertNotIn("dry_run", started.get("message", "").lower())
            seen = set()
            status = {}
            for _ in range(50):
                status = install_hook.public_status(self.state)
                seen.add((status.get("status_word"), status.get("phase"), status.get("status")))
                if status.get("status") == "pass":
                    break
                time.sleep(0.05)
        finally:
            os.environ["PATH"] = old_path
            for _ in range(40):
                if not install_hook._ACTIVE["on"]:
                    break
                time.sleep(0.05)
        self.assertEqual(status.get("status"), "pass", status)
        self.assertEqual(status.get("mode"), "live")
        self.assertEqual(status.get("status_word"), "Ready")
        self.assertEqual(status.get("vast_calls"), 0)
        self.assertFalse(status.get("destroyed"))
        tail = status.get("tail") or ""
        self.assertIn("PODCODER_STAGE ollama", tail)
        self.assertIn("PODCODER_STAGE pull", tail)
        self.assertIn("PODCODER_STAGE aider", tail)
        self.assertIn("PODCODER_STAGE smoke", tail)
        self.assertIn("skip pull; granite4.2:8b-q5_0 already present", tail)
        self.assertIn("PODCODER_LOCAL_SMOKE_PASS", tail)
        self.assertNotIn("PODCODER_DRY_RUN_OK", tail)
        self.assertTrue(any(word == "Downloading" for word, _phase, state in seen))
        self.assertTrue(any(state == "running" for _word, _phase, state in seen))
        smoke = json.loads((self.state / "local-smoke.json").read_text(encoding="utf-8"))
        self.assertEqual(smoke["model"], "granite4.2:8b-q5_0")
        self.assertEqual(smoke["profile"], "local_ram32_q5")
        self.assertTrue(compute_profiles.local_ready(self.state))
        ollama_log = log.read_text(encoding="utf-8")
        self.assertIn("show", ollama_log)
        self.assertIn("list", ollama_log)
        self.assertNotIn("pull", ollama_log)
        self.assertNotIn("api.vast.ai", tail)

    def test_local_video_and_image_download_run_their_scripts(self):
        os.environ["PODCODER_SKIP_DOWNLOAD"] = "1"
        try:
            strong = {"ram_gb": 32, "vram_gb": 12, "disk_free_gb": 80, "gpu": "RTX 3080"}
            video_pick = hardware_probe.choose("video", strong, "local")
            self.assertEqual(video_pick["script"], "install-video-comfy-wan.sh")
            self.assertIn("Wan2.2-TI2V-5B", video_pick["stack"])
            image_pick = hardware_probe.choose("image", {"ram_gb": 16, "vram_gb": 8, "disk_free_gb": 40, "gpu": "RTX 3070"}, "local")
            self.assertEqual(image_pick["script"], "install-image-role.sh")
            self.assertNotIn("Wan", image_pick["stack"])
            weak_video = hardware_probe.choose("video", {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 80, "gpu": "none"}, "local")
            self.assertTrue(weak_video["needs_rent"])
            video = install_hook.handle_download(
                {"compute": "local", "role": "video", "probe": strong},
                self.state,
                src_dir=ROOT,
                sync=True,
            )
            self.assertEqual(video["install_script"], "install-video-comfy-wan.sh")
            self.assertEqual(video["status_word"], "Ready")
            self.assertEqual(video["vast_calls"], 0)
            self.assertIn("PODCODER_VIDEO_READY", install_hook.public_status(self.state).get("tail") or "")
            image = install_hook.handle_download(
                {"compute": "local", "role": "image", "probe": {"ram_gb": 16, "vram_gb": 8, "disk_free_gb": 40, "gpu": "RTX 3070"}},
                self.state,
                src_dir=ROOT,
                sync=True,
            )
            self.assertEqual(image["install_script"], "install-image-role.sh")
            self.assertEqual(image["status_word"], "Ready")
            self.assertNotIn("Wan", image["message"])
            self.assertIn("PODCODER_IMAGE_READY", install_hook.public_status(self.state).get("tail") or "")
            self.assertEqual(image["vast_calls"], 0)
        finally:
            os.environ.pop("PODCODER_SKIP_DOWNLOAD", None)
            install_hook._ACTIVE["on"] = False

    def test_cloud_download_runs_scripts_offline_after_confirm(self):
        work = Path(self.tmp.name) / "cloud"
        fake = work / "bin"
        fake.mkdir(parents=True)
        (fake / "ollama").write_text(
            "#!/bin/bash\n"
            "case \"$1\" in\n"
            "  list) printf '%s\\n' 'granite4.2:8b-q8_0' ;;\n"
            "  pull) exit 99 ;;\n"
            "esac\nexit 0\n",
            encoding="utf-8",
        )
        (fake / "curl").write_text(
            "#!/bin/bash\n"
            "if [[ \"$*\" == *install.sh* ]]; then exit 97; fi\n"
            "if [[ \"$*\" == *api/generate* ]]; then printf '%s\\n' '{\"response\":\"pong\"}'; exit 0; fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        (fake / "apt-get").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        (fake / "aider").write_text("#!/bin/bash\necho 'aider test'\nexit 0\n", encoding="utf-8")
        for path in fake.iterdir():
            path.chmod(0o755)
        home = work / "home"
        home.mkdir()
        base = os.environ.copy()
        for key in list(base):
            if key.startswith("PODCODER_"):
                base.pop(key, None)
        q8_env = dict(base)
        q8_env.update({
            "PATH": str(fake) + os.pathsep + base.get("PATH", ""),
            "HOME": str(home),
            "PODCODER_DEST": str(work / "opt"),
            "PODCODER_TRANSLATOR_HOME": str(work / "translator"),
            "PODCODER_SKIP_SERVER_START": "1",
            "PODCODER_INSTALL_STATUS": str(work / "q8-status.json"),
            "PODCODER_INSTALL_LOCK": str(work / "q8.lock"),
            "PODCODER_VRAM_LOCK": str(work / "vram.json"),
            "PODCODER_ROLE": "coding",
        })
        video_env = dict(base)
        video_env.update({
            "PATH": q8_env["PATH"],
            "PODCODER_SKIP_DOWNLOAD": "1",
            "PODCODER_ROLE": "video",
            "PODCODER_VIDEO_DEST": str(work / "video"),
            "PODCODER_VRAM_LOCK": str(work / "video-vram.json"),
        })
        image_env = dict(base)
        image_env.update({
            "PATH": q8_env["PATH"],
            "PODCODER_SKIP_DOWNLOAD": "1",
            "PODCODER_ROLE": "image",
            "PODCODER_IMAGE_DEST": str(work / "image"),
        })
        recorded = []
        real_run = subprocess.run
        real_popen = subprocess.Popen

        def fake_run(args, **kwargs):
            if args and args[0] in {"ssh", "scp"}:
                recorded.append(" ".join(str(part) for part in args))
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            return real_run(args, **kwargs)

        def fake_popen(args, **kwargs):
            if args and args[0] == "ssh":
                joined = " ".join(str(part) for part in args)
                recorded.append(joined)
                if "install-video-comfy-wan.sh" in joined:
                    script, env = "install-video-comfy-wan.sh", video_env
                elif "install-image-role.sh" in joined:
                    script, env = "install-image-role.sh", image_env
                else:
                    script, env = "install-on-pod-q8.sh", q8_env
                return real_popen(
                    ["bash", str(ROOT / script)],
                    cwd=str(ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
            return real_popen(args, **kwargs)

        refused = install_hook.handle_rent(
            {"confirm": "RENT", "dry_run": True, "ssh_host": "10.9.9.9", "inet_down": 1200, "role": "coding"},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            sync=True,
        )
        self.assertEqual(refused["install"], "not_started")
        self.assertEqual(refused["vast_calls"], 0)
        accepted = install_hook.accept_rent(
            {
                "confirm": "RENT",
                "dry_run": False,
                "role": "coding",
                "inet_down": 1200,
                "disk_gb": 150,
                "gpu": "RTX 3090",
                "ssh_host": "10.9.9.9",
                "ssh_port": 22,
                "ssh_user": "root",
            },
            self.state,
        )
        self.assertTrue(accepted["rent_accepted"])
        self.assertEqual(accepted["vast_calls"], 0)
        self.assertFalse(accepted["destroyed"])
        install_hook.subprocess.run = fake_run
        install_hook.subprocess.Popen = fake_popen
        try:
            coding = install_hook.handle_download(
                {"compute": "cloud", "role": "coding"},
                self.state,
                src_dir=ROOT,
                sync=True,
            )
            self.assertEqual(coding["install_script"], "install-on-pod-q8.sh")
            self.assertEqual(coding["status_word"], "Ready")
            self.assertEqual(coding["vast_calls"], 0)
            self.assertIn("10.9.9.9", coding["message"])
            video = install_hook.handle_download(
                {"compute": "cloud", "role": "video"},
                self.state,
                src_dir=ROOT,
                sync=True,
            )
            self.assertEqual(video["install_script"], "install-video-comfy-wan.sh")
            self.assertEqual(video["status_word"], "Ready")
            self.assertIn("Wan", video["message"])
            self.assertNotIn("q8_0", video["message"])
            image = install_hook.handle_download(
                {"compute": "cloud", "role": "image"},
                self.state,
                src_dir=ROOT,
                sync=True,
            )
            self.assertEqual(image["install_script"], "install-image-role.sh")
            self.assertEqual(image["status_word"], "Ready")
            self.assertNotIn("Wan", image["message"])
        finally:
            install_hook.subprocess.run = real_run
            install_hook.subprocess.Popen = real_popen
            install_hook._ACTIVE["on"] = False
        blob = "\n".join(recorded)
        self.assertIn("install-on-pod-q8.sh", blob)
        self.assertIn("install-video-comfy-wan.sh", blob)
        self.assertIn("install-image-role.sh", blob)
        self.assertIn("10.9.9.9", blob)
        self.assertNotIn("api.vast.ai", blob)
        self.assertNotIn("vast.ai", blob)
        checklist = subprocess.run(
            ["bash", str(ROOT / "checklist-confirm-rent.sh")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(checklist.returncode, 0, checklist.stderr)
        self.assertIn("does not create a Vast instance", checklist.stdout)
        self.assertIn('"confirm":"RENT"', checklist.stdout)
        self.assertIn("/api/download", checklist.stdout)
        self.assertNotIn("api.vast.ai", checklist.stdout)
        refused_destroy = subprocess.run(
            ["bash", str(ROOT / "checklist-confirm-rent.sh"), "destroy"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(refused_destroy.returncode, 3)

    def test_gallery_media_and_comfy_install_unloads_first(self):
        video = Path(self.tmp.name) / "video"
        output = video / "ComfyUI" / "output"
        output.mkdir(parents=True)
        (output / "shot.png").write_bytes(b"\x89PNG")
        (output / "clip.mp4").write_bytes(b"\x00mp4")
        os.environ["PODCODER_VIDEO_DEST"] = str(video)
        try:
            payload = gallery.list_payload(self.state)
            kinds = {item["name"]: item["kind"] for item in payload["items"]}
            self.assertEqual(kinds["shot.png"], "image")
            self.assertEqual(kinds["clip.mp4"], "video")
            self.assertTrue(kinds["shot.png"] and payload["items"][0]["url"].startswith("/api/gallery/media/"))
            self.assertIsNone(gallery.resolve_media(self.state, "../secret"))
            self.assertIsNone(gallery.resolve_media(self.state, "..%2Fsecret"))
        finally:
            os.environ.pop("PODCODER_VIDEO_DEST", None)
        blocked = install_hook.handle_comfy_install(
            {"confirm": "INSTALL_COMFY", "role": "coding", "ssh_host": "10.6.6.6"},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            sync=True,
        )
        self.assertEqual(blocked["http"], 400)
        self.assertEqual(blocked["install"], "coding_only")
        self.assertEqual(blocked["install_script"], "install-on-pod-q8.sh")
        calls = []

        def runner(ssh, src, on_line):
            calls.append(ssh)
            return 0, "PODCODER_VIDEO_READY\nPODCODER_COMFY_READY\n"

        started = install_hook.handle_comfy_install(
            {"confirm": "INSTALL_COMFY", "unload_granite": True, "ssh_host": "10.6.6.6", "ssh_port": 22},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=runner,
            sync=True,
        )
        self.assertEqual(calls, [{"host": "10.6.6.6", "port": 22, "user": "root"}])
        self.assertEqual(started["vast_calls"], 0)
        self.assertFalse(started["destroyed"])
        self.assertFalse(started["coding_allowed"])
        self.assertEqual(started["install_script"], "install-comfyui.sh")


if __name__ == "__main__":
    unittest.main()
