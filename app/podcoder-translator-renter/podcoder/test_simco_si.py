#!/usr/bin/env python3
"""Simco SI detection, Aider install choice, translation profiles, and dry-run setup."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hardware_probe
import install_hook
import product_api
import setup_flow
import translation_profiles

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures" / "translation"

LAPTOP_8 = {"ram_gb": 8, "vram_gb": 0, "disk_free_gb": 40, "gpu": "none", "cpu": "Intel", "platform": "linux"}
ASPIRE_32 = {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 100, "gpu": "Radeon", "cpu": "Ryzen 7000", "platform": "linux"}
BOX_3090 = {"ram_gb": 32, "vram_gb": 24, "disk_free_gb": 200, "gpu": "RTX 3090", "cpu": "Xeon", "platform": "linux"}
TOO_SMALL = {"ram_gb": 4, "vram_gb": 0, "disk_free_gb": 100, "gpu": "none", "cpu": "Celeron", "platform": "linux"}
TOO_SMALL_DISK = {"ram_gb": 8, "vram_gb": 0, "disk_free_gb": 4, "gpu": "none", "cpu": "Intel", "platform": "linux"}


class TurtleCardTests(unittest.TestCase):
    def test_card_controls_call_the_server_and_skip_rent(self):
        chat = (ROOT.parent / "local" / "chat.html").read_text(encoding="utf-8")
        card = chat.split('id="turtleScreen"', 1)[1].split("</section>", 1)[0]
        self.assertIn('id="turtleRedetect"', card)
        self.assertIn("Re-detect this computer", card)
        self.assertIn('id="turtleCheck"', card)
        self.assertIn("Run setup check", card)
        self.assertIn('id="turtleQuestion"', card)
        self.assertIn('id="turtleAskSend"', card)
        self.assertIn("Ask the turtle", card)
        self.assertNotIn("/api/rent", card)
        self.assertNotIn("Confirm Rent", card)
        self.assertIn('"/api/probe"', chat)
        self.assertIn('"/api/setup"', chat)
        self.assertIn('"/api/install/status"', chat)
        self.assertIn('"/api/simco/turn"', chat)
        self.assertNotIn("dry_run: true", chat)
        self.assertNotIn('"dry_run": true', chat)


class HardwareSelectionTests(unittest.TestCase):
    def test_profiles(self):
        laptop = hardware_probe.choose("coding", LAPTOP_8, "local")
        self.assertTrue(laptop["ok"])
        self.assertEqual(laptop["model"], "granite4.2:8b")
        self.assertEqual(laptop["quant"], "Q4")
        self.assertEqual(laptop["tag"], "granite4.2:8b")
        self.assertEqual(laptop["aider"]["method"], "pipx")
        self.assertEqual(laptop["aider"]["version"], hardware_probe.AIDER_VERSION)
        self.assertEqual(laptop["aider"]["model_flag"], "ollama_chat/granite4.2:8b")
        self.assertEqual(laptop["aider"]["env"]["OLLAMA_API_BASE"], "http://127.0.0.1:11434")
        self.assertEqual(laptop["ollama"]["method"], "linux-install-sh")
        self.assertEqual(laptop["ollama"]["version"], hardware_probe.OLLAMA_VERSION)
        self.assertEqual(laptop["vram_residents"], ["granite"])
        self.assertNotIn("wan", laptop["stack"].lower())
        self.assertEqual(laptop["translation_profile"], "granite-q4-chat")
        self.assertNotIn("adapter", laptop)

        aspire = hardware_probe.choose("coding", ASPIRE_32, "local")
        self.assertEqual(aspire["model"], "granite4.2:8b-q5_0")
        self.assertEqual(aspire["quant"], "Q5")
        self.assertEqual(aspire["profile"], "local_ram32_q5")
        self.assertEqual(aspire["aider"]["method"], "uv")
        self.assertEqual(aspire["aider"]["model_flag"], "ollama_chat/granite4.2:8b-q5_0")
        self.assertEqual(aspire["ollama"]["method"], "linux-install-sh")
        self.assertNotEqual(aspire["model"], hardware_probe.Q8_MODEL)
        self.assertEqual(aspire["translation_profile"], "granite-q5-chat")

        box = hardware_probe.choose("coding", BOX_3090, "local")
        self.assertEqual(box["model"], "granite4.2:8b-q5_0")
        self.assertNotEqual(box["model"], hardware_probe.Q8_MODEL)
        self.assertEqual(box["ollama"]["method"], "linux-install-sh-cuda")
        self.assertEqual(box["vram_residents"], ["granite"])
        self.assertNotIn("wan", box["stack"].lower())

        video = hardware_probe.choose("video", BOX_3090, "local")
        self.assertTrue(video["ok"])
        self.assertEqual(video["vram_residents"], ["wan"])
        self.assertNotIn("granite", video["stack"].lower())
        self.assertEqual(video["aider"]["method"], "not-selected")
        self.assertEqual(video["aider"]["argv"], [])
        self.assertEqual(video["model"], "")
        self.assertFalse(hardware_probe.loads_both(box))
        self.assertFalse(hardware_probe.loads_both(video))
        pair = hardware_probe.simultaneous(box, video, 24)
        self.assertTrue(pair["exclusive"])
        self.assertTrue(pair["allowed_on_24gb"])
        self.assertFalse(pair["same_boot"])

        cloud = hardware_probe.choose("coding", BOX_3090, "cloud")
        self.assertEqual(cloud["model"], hardware_probe.Q8_MODEL)
        self.assertEqual(cloud["aider"]["method"], "uv")
        self.assertEqual(cloud["aider"]["model_flag"], "ollama_chat/granite4.2:8b-q8_0")
        self.assertEqual(cloud["ollama"]["method"], "linux-install-sh-cuda")
        self.assertEqual(cloud["ollama"]["version"], hardware_probe.OLLAMA_VERSION)
        self.assertEqual(cloud["translation_profile"], "granite-q8-tools")
        self.assertNotIn("wan", (cloud.get("stack") or "").lower())

        tiny = hardware_probe.choose("coding", TOO_SMALL, "local")
        self.assertFalse(tiny["ok"])
        self.assertTrue(tiny["needs_rent"])
        self.assertEqual(tiny["aider"]["method"], "not-selected")
        self.assertEqual(tiny["ollama"]["method"], "not-selected")
        self.assertEqual(tiny["tag"], "")
        starved = hardware_probe.choose("coding", TOO_SMALL_DISK, "local")
        self.assertFalse(starved["ok"])
        self.assertEqual(starved["aider"]["method"], "not-selected")

    def test_cpu_does_not_change_the_stack(self):
        ryzen = hardware_probe.choose("coding", ASPIRE_32, "local")
        other = hardware_probe.choose("coding", {**ASPIRE_32, "cpu": "other"}, "local")
        self.assertEqual(ryzen["model"], other["model"])
        self.assertEqual(ryzen["aider"]["method"], other["aider"]["method"])
        self.assertEqual(ryzen["ollama"]["method"], other["ollama"]["method"])

    def test_install_method_follows_platform(self):
        mac = hardware_probe.choose("coding", {**LAPTOP_8, "platform": "darwin"}, "local")
        self.assertEqual(mac["ollama"]["method"], "macos-dmg")
        self.assertEqual(mac["model"], "granite4.2:8b")
        self.assertEqual(mac["aider"]["method"], "pipx")
        windows = hardware_probe.choose("coding", {**ASPIRE_32, "platform": "windows"}, "local")
        self.assertEqual(windows["ollama"]["method"], "windows-exe")
        self.assertEqual(windows["model"], "granite4.2:8b-q5_0")
        self.assertEqual(windows["aider"]["method"], "pip-venv")

    def test_nvidia_smi_missing_is_safe(self):
        with mock.patch("hardware_probe.subprocess.run", side_effect=FileNotFoundError("nvidia-smi")):
            self.assertEqual(hardware_probe._gpu(), ("none", 0.0))
        with mock.patch(
            "hardware_probe.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=4),
        ):
            self.assertEqual(hardware_probe._gpu(), ("none", 0.0))


class TranslationProfileTests(unittest.TestCase):
    def test_fixtures_offline(self):
        for name in ("q4_chat.json", "q5_chat.json", "q8_tools.json"):
            fixture = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
            profile = translation_profiles.get_profile(fixture["profile"])
            self.assertIsNotNone(profile)
            inbound = translation_profiles.translate_in(fixture["text"], profile)
            self.assertTrue(inbound["ok"], inbound)
            self.assertEqual(inbound["model"], fixture["model"])
            self.assertEqual(inbound["route"], "aider")
            self.assertEqual(inbound["aider"]["model"], "ollama_chat/" + fixture["model"])
            self.assertEqual(inbound["aider"]["env"]["OLLAMA_API_BASE"], "http://127.0.0.1:11434")
            self.assertIn("--model", inbound["aider"]["argv"])
            self.assertEqual(inbound["api"], "/api/chat")
            self.assertEqual(inbound["payload"]["model"], fixture["model"])
            self.assertFalse(inbound["payload"]["stream"])
            self.assertEqual(inbound["payload"]["options"]["stop"], fixture["stop"])
            self.assertIn(fixture["marker"], inbound["rendered_prompt"])
            self.assertIn("<|start_of_role|>assistant<|end_of_role|>", inbound["rendered_prompt"])
            self.assertEqual(inbound["payload"]["messages"][0]["role"], "system")
            if fixture.get("tool_format"):
                self.assertEqual(inbound["tool_format"], fixture["tool_format"])
                self.assertIn("tools", inbound["payload"])
            outbound = translation_profiles.translate_out(
                fixture["raw"],
                profile,
                feature=inbound["feature"],
                ask=fixture["text"],
            )
            if "everyday" in fixture:
                self.assertEqual(outbound["everyday"], fixture["everyday"])
            if fixture.get("everyday_contains"):
                self.assertIn(fixture["everyday_contains"], outbound["everyday"].lower())
                self.assertNotIn("you should see 56", outbound["everyday"])
            self.assertNotIn("<", outbound["everyday"])
            self.assertEqual(outbound["profile"], fixture["profile"])

    def test_ollama_documents_select_the_profile(self):
        def fetcher(url, body=None):
            if url.endswith("/api/tags"):
                return {"models": [{"name": "granite4.2:8b-q5_0"}]}
            self.assertEqual((body or {}).get("name"), "granite4.2:8b-q5_0")
            return {"template": "<|start_of_role|>system<|end_of_role|>{{ .System }}<|end_of_text|>", "model": "granite4.2:8b-q5_0"}

        picked = translation_profiles.query_ollama("http://127.0.0.1:11434", fetcher, detected={"model": "granite4.2:8b"})
        self.assertEqual(picked["id"], "granite-q5-chat")
        self.assertEqual(picked["family"], "granite")
        chatml = translation_profiles.profile_from_ollama(
            show={"template": "<|im_start|>system\nYou are helpful.<|im_end|>"},
            detected={"model": "granite4.2:8b"},
        )
        self.assertEqual(chatml["family"], "chatml")
        rendered = translation_profiles.render_prompt(chatml, [{"role": "user", "content": "hello"}])
        self.assertIn("<|im_start|>user", rendered)
        self.assertIn("<|im_end|>", rendered)


class SetupFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_locks_profile_and_skips_weights(self):
        calls = []

        def downloader(plan):
            calls.append(plan)
            return {"executed": True, "dry_run": True, "vast_calls": 0, "destroyed": False}

        result = setup_flow.run(self.state, {"role": "coding", "probe": ASPIRE_32}, downloader=downloader)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["granite"], "granite4.2:8b-q5_0")
        self.assertEqual(calls[0]["aider"]["method"], "uv")
        self.assertEqual(calls[0]["aider"]["version"], hardware_probe.AIDER_VERSION)
        self.assertEqual(calls[0]["ollama"]["method"], "linux-install-sh")
        self.assertEqual(calls[0]["vram_residents"], ["granite"])
        self.assertFalse(calls[0]["vram_simultaneous"])
        self.assertTrue(result["chat_unlocked"])
        self.assertEqual(result["vast_calls"], 0)
        self.assertFalse(result["destroyed"])
        self.assertEqual(result["profile_id"], "granite-q5-chat")
        self.assertTrue(result["ready_check"]["ok"])
        self.assertEqual(result["ready_check"]["aider_model"], "ollama_chat/granite4.2:8b-q5_0")
        self.assertTrue(setup_flow.unlocked(self.state))
        code, body = product_api.try_handle(
            "POST",
            "/api/simco/turn",
            {
                "text": "make multiply show 7 times 8",
                "raw": "<!DOCTYPE html><html><body><button id='*'></button></body></html>",
            },
            self.state,
        )
        self.assertEqual(code, 200)
        self.assertIn("56", body["everyday"])
        self.assertEqual(body["model"], "granite4.2:8b-q5_0")
        self.assertEqual(body["route"], "aider")
        self.assertEqual(body["aider"]["model"], "ollama_chat/granite4.2:8b-q5_0")
        self.assertEqual(body["vast_calls"], 0)
        self.assertIn("stop", body["payload"]["options"])

    def test_default_run_writes_a_plan_without_a_downloader(self):
        result = setup_flow.run(self.state, {"role": "coding", "probe": LAPTOP_8})
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["downloads"]["executed"])
        plan = json.loads((self.state / "download-plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["granite"], "granite4.2:8b")
        self.assertEqual(plan["aider"]["method"], "pipx")
        self.assertEqual(plan["ollama"]["version"], hardware_probe.OLLAMA_VERSION)
        self.assertEqual(result["vast_calls"], 0)

    def test_too_small_stays_locked(self):
        result = setup_flow.run(self.state, {"role": "coding", "probe": TOO_SMALL})
        self.assertFalse(result["chat_unlocked"])
        self.assertEqual(result["phase"], "blocked")
        self.assertEqual(result["vast_calls"], 0)
        code, body = product_api.try_handle(
            "POST",
            "/api/simco/turn",
            {"text": "hello there friend"},
            self.state,
        )
        self.assertEqual(code, 409)
        self.assertFalse(body.get("coding_allowed", True))

    def test_show_document_can_override_the_locked_family(self):
        result = setup_flow.run(
            self.state,
            {
                "role": "coding",
                "probe": ASPIRE_32,
                "ollama_tags": {"models": [{"name": "granite4.2:8b-q5_0"}]},
                "ollama_show": {"model": "granite4.2:8b-q5_0", "template": "<|start_of_role|>system<|end_of_role|>"},
            },
        )
        self.assertEqual(result["profile_id"], "granite-q5-chat")

    def test_confirm_rent_stays_gated_and_does_not_rent(self):
        vague = install_hook.accept_rent({"confirm": "I confirm RENT", "dry_run": False, "role": "coding"}, self.state)
        self.assertFalse(vague.get("rented"))
        self.assertEqual(vague["vast_calls"], 0)
        self.assertNotEqual(vague.get("install"), "started")
        lower = install_hook.accept_rent({"confirm": "rent", "dry_run": False, "role": "coding"}, self.state)
        self.assertEqual(lower["http"], 400)
        self.assertFalse(lower.get("rented"))
        self.assertEqual(lower["vast_calls"], 0)
        self.assertFalse((self.state / "rent-confirm.json").exists())


class NoAdaAdapterTests(unittest.TestCase):
    def _assert_no_ada(self, payload):
        blob = json.dumps(payload)
        self.assertNotIn('"adapter"', blob)
        self.assertNotIn("ada-granite", blob)
        self.assertNotIn("-ada-", blob)
        self.assertNotIn("Ada slot", blob)

    def test_probe_setup_and_saved_status_have_no_ada(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            code, probe = hardware_probe.advise(state, {"compute": "local", "role": "coding", "probe": LAPTOP_8})
            self.assertEqual(code, 200)
            self.assertEqual(probe["translation_profile"], "granite-q4-chat")
            self.assertEqual(probe["aider"]["model_flag"], "ollama_chat/granite4.2:8b")
            self.assertNotIn("adapter", probe)
            self._assert_no_ada(probe)
            result = setup_flow.run(state, {"role": "coding", "probe": LAPTOP_8})
            self.assertEqual(result["profile_id"], "granite-q4-chat")
            self.assertIn("Aider", result["message"])
            self._assert_no_ada(result)
            self.assertEqual(translation_profiles.get_profile("granite-q4-ada-chat")["id"], "granite-q4-chat")
            lock = state / "setup-lock.json"
            lock.write_text(json.dumps({
                "phase": "ready",
                "chat_unlocked": True,
                "profile_id": "granite-q4-ada-chat",
                "adapter": {"slot": "ada", "id": "ada-granite-chat", "tag": "ada-granite-chat"},
                "message": "Ada slot ada-granite-chat. Translator profile granite-q4-ada-chat is locked.",
                "decision": {
                    "adapter": {"slot": "ada", "id": "ada-granite-chat"},
                    "translation_profile": "granite-q4-ada-chat",
                },
            }), encoding="utf-8")
            cleaned = setup_flow.status(state)
            self._assert_no_ada(cleaned)
            self.assertEqual(cleaned["profile_id"], "granite-q4-chat")
            self._assert_no_ada(json.loads(lock.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
