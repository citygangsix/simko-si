#!/usr/bin/env python3
"""Independence pack. Offline only. No Vast calls."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import wave
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import agent_loop
import approvals
import auth_accounts
import backups
import charts
import connectors
import emotion
import humor
import job_runner
import memories
import notify
import offline_sync
import product_api
import scheduler
import scrape_job
import transcripts
import vault
import watchdog


class IndependenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.env = {}
        for key in (
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
            "CURSOR_API_KEY",
            "VAPID_PUBLIC_KEY",
            "VAPID_PRIVATE_KEY",
            "SMTP_HOST",
            "HF_TOKEN",
            "PODCODER_PROFILE",
            "PODCODER_COMPUTE",
            "PODCODER_PUSH_LIVE",
            "PODCODER_YTDLP_LIVE",
            "PODCODER_WHISPER_LIVE",
        ):
            self.env[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_jobs_persist_cancel_and_retry(self):
        created = job_runner.create_job(self.state, "ada@example.com", "task", {"note": "keep"})
        self.assertTrue(created["ok"])
        self.assertEqual(created["status"], "queued")
        self.assertEqual(created["vast_calls"], 0)
        again = job_runner.list_jobs(self.state, "ada@example.com")
        self.assertEqual(again["jobs"][0]["id"], created["id"])
        cancelled = job_runner.cancel_job(self.state, created["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        retried = job_runner.retry_job(self.state, created["id"])
        self.assertEqual(retried["status"], "queued")
        self.assertGreaterEqual(retried["attempts"], 1)
        logs = job_runner.get_job(self.state, created["id"])["logs"]
        self.assertTrue(any(row["line"] == "queued" for row in logs))

    def test_agent_sandbox_budget_and_approval(self):
        workspace = self.state / "workspace"
        workspace.mkdir()
        (workspace / "note.txt").write_text("hi\n", encoding="utf-8")
        created = job_runner.create_job(self.state, "ada", "agent", {
            "compute": "local",
            "max_steps": 2,
            "plan": [
                {"tool": "shell", "args": {"cmd": "echo hello"}},
                {"tool": "read", "args": {"path": "note.txt"}},
                {"tool": "write", "args": {"path": "out.txt", "text": "yo"}},
            ],
        })
        done = job_runner.execute(self.state, created["id"], workspace)
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["result"]["model"], "granite4.2:8b-q5_0")
        self.assertEqual(done["result"]["steps"], 2)
        self.assertFalse((workspace / "out.txt").exists())
        blocked = agent_loop.run_shell(workspace, "rm -rf /")
        self.assertFalse(blocked["ok"])
        outside = agent_loop.run_shell(workspace, "cat /etc/passwd")
        self.assertFalse(outside["ok"])
        agent_loop.run_write(workspace, "out.txt", "yo")
        edited = agent_loop.run_edit(workspace, "out.txt", "yo", "ok")
        self.assertTrue(edited["ok"])
        self.assertEqual((workspace / "out.txt").read_text(encoding="utf-8"), "ok")
        cloud = agent_loop.model_for("cloud")
        self.assertEqual(cloud, "granite4.2:8b-q8_0")
        gated = job_runner.create_job(self.state, "ada", "agent", {
            "plan": [{"tool": "send", "args": {"text": "hello there"}}],
        })
        paused = job_runner.execute(self.state, gated["id"], workspace)
        self.assertEqual(paused["status"], "needs_approval")
        wrong = approvals.confirm(self.state, gated["id"], "send", "RENT")
        self.assertFalse(wrong["approved"])
        right = approvals.confirm(self.state, gated["id"], "send", "SEND")
        self.assertTrue(right["approved"])
        self.assertFalse(right["performed"])

    def test_cursor_stub_hides_the_key(self):
        os.environ["CURSOR_API_KEY"] = "cursor-test-key"
        handed = agent_loop.cursor_hand("fix the button")
        self.assertTrue(handed["stub"])
        self.assertTrue(handed["cursor"])
        self.assertNotIn("cursor-test-key", json.dumps(handed))
        self.assertEqual(handed["vast_calls"], 0)
        os.environ.pop("CURSOR_API_KEY")
        local = agent_loop.cursor_hand("fix the button")
        self.assertEqual(local["engine"], "granite")

    def test_scrape_fixture_robots_and_csv(self):
        html = "<html><title>Reef Note</title><body>Title: Coral</body></html>"
        created = job_runner.create_job(self.state, "ada", "scrape", {
            "html": html,
            "fields": ["Title"],
            "min_interval": 0,
            "robots": "User-agent: *\nDisallow:\n",
            "path": "/notes",
        })
        done = job_runner.execute(self.state, created["id"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["result"]["title"], "Reef Note")
        self.assertEqual(done["result"]["fields"]["Title"], "Coral")
        self.assertTrue((self.state / done["result"]["csv"]).is_file())
        self.assertFalse(robots_allows_private())
        (self.state / "scrape-rate.json").unlink(missing_ok=True)
        limited = scrape_job.run(self.state, "rate", {"html": html, "min_interval": 60})
        again = scrape_job.run(self.state, "rate2", {"html": html, "min_interval": 60})
        self.assertTrue(limited["ok"])
        self.assertIn("rate", again["error"])
        viewed = scrape_job.browser(html, [
            {"op": "click", "selector": "a"},
            {"op": "scroll"},
            {"op": "fill", "use_vault": True},
            {"op": "screenshot"},
        ], secret="hidden-secret")
        self.assertEqual(viewed["engine"], "stub")
        self.assertNotIn("hidden-secret", json.dumps(viewed))
        self.assertIn("screenshot", viewed["actions"])

    def test_routines_cron_and_when(self):
        self.assertTrue(scheduler.cron_match("0 */4 * * *", datetime(2026, 10, 29, 4, 0)))
        self.assertFalse(scheduler.cron_match("0 */4 * * *", datetime(2026, 10, 29, 1, 0)))
        made = scheduler.create_routine(self.state, "ada", "four", "cron", {"expr": "0 */4 * * *", "job_kind": "task", "payload": {"note": "tick"}})
        self.assertTrue(made["ok"])
        ticked = scheduler.tick(self.state, datetime(2026, 10, 29, 4, 0))
        self.assertEqual(len(ticked["enqueued"]), 1)
        again = scheduler.tick(self.state, datetime(2026, 10, 29, 4, 0))
        self.assertEqual(again["enqueued"], [])
        flag = self.state / "flags"
        flag.mkdir()
        (flag / "ready").write_text("1", encoding="utf-8")
        scheduler.create_routine(self.state, "ada", "ping", "when", {"flag": "ready", "job_kind": "task", "payload": {}})
        fired = scheduler.tick(self.state, datetime(2026, 10, 29, 5, 0))
        self.assertEqual(len(fired["enqueued"]), 1)

    def test_notify_stub_when_unset(self):
        sent = notify.send(self.state, "job_done", "Done", "the job finished")
        self.assertEqual(sent["delivered"], "stub")
        self.assertEqual(sent["vast_calls"], 0)
        raw = (self.state / "notifications.json").read_text(encoding="utf-8")
        self.assertNotIn("VAPID", raw)

    def test_vault_names_and_connector_stubs(self):
        vault.put(self.state, "ada", "phrase", {"email": "a@example.com"})
        stored = vault.put_named(self.state, "ada", "phrase", "dropbox", "secret-value")
        self.assertTrue(stored["ok"])
        self.assertFalse(stored["revealed"])
        listed = vault.names(self.state, "ada", "phrase")
        self.assertEqual(listed["names"], ["dropbox"])
        self.assertNotIn("secret-value", json.dumps(listed))
        opened = vault.reveal(self.state, "ada", "phrase")
        self.assertNotIn("secret-value", json.dumps(opened))
        token = vault.put_oauth(self.state, "ada", "phrase", "github", {"access_token": "gh-secret", "client_secret": "nope"})
        self.assertTrue(token["ok"])
        blob = (self.state / "vault" / "ada.bin").read_bytes()
        self.assertNotIn(b"secret-value", blob)
        self.assertNotIn(b"gh-secret", blob)
        described = connectors.describe("gmail")
        self.assertTrue(described["stub"])
        self.assertFalse(described["configured"])
        self.assertNotIn("CLIENT_SECRET", json.dumps(connectors.listing()))

    def test_memories_recall_prefers_the_chat_category(self):
        memories.add_memory(self.state, "ada", "ship the career plan", "goal", "s-1")
        memories.add_memory(self.state, "ada", "I want a quiet home", "preference", "s-2")
        recalled = memories.recall(self.state, "ada", "career")
        self.assertEqual(recalled["memories"][0]["categories"], ["career"])
        self.assertNotIn("score", json.dumps(recalled))
        sql = (ROOT / "sql" / "podcoder_independence.sql").read_text(encoding="utf-8")
        self.assertIn("podcoder_memories", sql)
        self.assertNotIn("score", sql.lower())
        self.assertIn("wxvjajecvklfjxppawdx", sql)
        self.assertIn("nexkymqahpkvzzlvivfi", sql)

    def test_backup_restore_and_schedule(self):
        os.environ["PODCODER_PROFILE"] = "aspire"
        folder = self.state / "keep"
        folder.mkdir()
        (folder / "a.txt").write_text("one", encoding="utf-8")
        first = backups.backup(self.state, "manual")
        (folder / "a.txt").write_text("two", encoding="utf-8")
        second = backups.backup(self.state, "manual")
        self.assertIn("keep/a.txt", second["changed"])
        dest = self.state / "restored"
        restored = backups.restore(self.state, first["id"], dest)
        self.assertTrue(restored["ok"])
        self.assertEqual((dest / "keep" / "a.txt").read_text(encoding="utf-8"), "one")
        early = backups.maybe_due(self.state, now=10)
        self.assertTrue(early["due"])
        later = backups.maybe_due(self.state, now=10 + 60)
        self.assertFalse(later["due"])
        os.environ["PODCODER_PROFILE"] = "cloud"
        noted = backups.after_write(self.state, "job")
        self.assertTrue(noted["mirror"]["mirrored"])
        self.assertFalse(offline_sync.status(self.state)["cloud"])

    def test_watchdog_and_aspire_script(self):
        stale = watchdog.check(self.state, now=100, stale_after=30)
        self.assertEqual(stale["restart"], ["podcoder", "ollama"])
        watchdog.beat(self.state, now=100)
        fresh = watchdog.check(self.state, now=110, stale_after=30)
        self.assertEqual(fresh["restart"], [])
        script = (ROOT.parent / "scripts" / "aspire-always-on.sh").read_text(encoding="utf-8")
        self.assertIn("powercfg /change standby-timeout-ac 0", script)
        self.assertIn("powercfg /change hibernate-timeout-ac 0", script)
        self.assertIn("systemd=true", script)
        self.assertTrue((ROOT.parent / "scripts" / "systemd" / "podcoder.service").is_file())
        self.assertTrue((ROOT.parent / "scripts" / "systemd" / "ollama.service").is_file())

    def test_totp_is_optional(self):
        code, created = auth_accounts.signup(self.state, "ada@example.com", "correct-horse")
        self.assertEqual(code, 200)
        plain = auth_accounts.signin(self.state, "ada@example.com", "correct-horse")
        self.assertTrue(plain[1]["token"])
        enrolled = auth_accounts.enroll_totp(self.state, plain[1]["token"])
        self.assertTrue(enrolled[1]["totp_enabled"])
        missing = auth_accounts.signin(self.state, "ada@example.com", "correct-horse")
        self.assertTrue(missing[1]["needs_totp"])
        self.assertNotIn("token", missing[1])
        wrong = auth_accounts.signin(self.state, "ada@example.com", "correct-horse", "000000")
        self.assertFalse(wrong[1]["ok"])
        good = auth_accounts.signin(self.state, "ada@example.com", "correct-horse", auth_accounts.totp_now(enrolled[1]["secret"]))
        self.assertTrue(good[1]["token"])
        self.assertNotIn(enrolled[1]["secret"], good[1].get("token", ""))

    def test_charts_cover_percent_level_and_tag(self):
        circ = 2 * math.pi * charts.RING_R
        for value in range(101):
            svg = charts.render_svg("ringMetrics", {
                "format": "percent",
                "ring": {"value": value, "word": "mark"},
                "rows": [{"label": "Row", "value": value}],
            })
            length = circ * (value / 100.0)
            self.assertIn(f'data-pct="{value}"', svg)
            self.assertIn(f"{length:.2f}", svg)
            progress = charts.render_svg("progressStats", {"format": "percent", "value": value})
            self.assertIn(f'data-pct="{value}"', progress)
        for word, steps in (("Low", 1), ("Medium", 2), ("High", 3)):
            svg = charts.render_svg("ringMetrics", {"format": "level", "ring": {"value": word}, "rows": [{"label": "A", "value": word}]})
            self.assertIn(f'data-steps="{steps}"', svg)
            self.assertIn(f'data-word="{word}"', svg)
        for word, steps in (("Quiet", 1), ("Emerging", 2), ("Dominant", 3)):
            svg = charts.render_svg("goalRing", {"format": "tag", "progress": word, "headline": word, "goal": word})
            self.assertIn(f'data-steps="{steps}"', svg)
        lifebook = charts.from_lifebook(self.state, "ada")
        self.assertEqual(lifebook["format"], "tag")
        self.assertNotEqual(lifebook["format"], "percent")
        refused = charts.validate("ringMetrics", {"source": "lifebook", "format": "percent", "ring": {"value": 10}})
        self.assertFalse(refused["ok"])
        quote = charts.render_svg("quoteCard", {"quote": "Love grows where attention flows."})
        self.assertIn("Love grows", quote)

    def test_widgets_route_is_hidden_from_chat(self):
        chat = (ROOT.parent / "local" / "chat.html").read_text(encoding="utf-8")
        self.assertNotIn("/widgets", chat)
        self.assertNotIn("ReefWidgets", chat)
        self.assertTrue((ROOT.parent / "local" / "widgets" / "widgets.js").is_file())
        os.environ["PODCODER_STATE_DIR"] = str(self.state)
        sys.path.insert(0, str(ROOT.parent / "local"))
        import server
        httpd = server.make_server(8766)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            page = urllib.request.urlopen("http://127.0.0.1:8766/widgets", timeout=5).read().decode("utf-8")
            self.assertIn("ReefWidgets", page)
            home = urllib.request.urlopen("http://127.0.0.1:8766/", timeout=5).read().decode("utf-8")
            self.assertNotIn("/widgets", home)
            health = json.load(urllib.request.urlopen("http://127.0.0.1:8766/api/health", timeout=5))
            self.assertTrue(health["ok"])
            self.assertEqual(health["service"], "local")
            self.assertFalse(health["destroyed"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            os.environ.pop("PODCODER_STATE_DIR", None)

    def test_transcript_fixtures_and_quotes(self):
        vtt = "\n".join([
            "WEBVTT",
            "",
            "00:00:01.000 --> 00:00:04.000",
            "<v Ada>Ship the career plan",
            "",
            "00:00:04.500 --> 00:00:06.000",
            "<v Bea>The reef is calm",
        ])
        created = job_runner.create_job(self.state, "ada", "transcript", {
            "captions": vtt,
            "title": "Career talk",
            "creator": "Ada",
            "url": "https://example.test/watch?v=1",
        })
        done = job_runner.execute(self.state, created["id"])
        self.assertEqual(done["status"], "done")
        self.assertIn("career", done["result"]["categories"])
        found = transcripts.search(self.state, "career plan", "Ada", "career")
        self.assertEqual(found["quotes"][0]["quote"], "Ship the career plan")
        self.assertEqual(found["quotes"][0]["speaker"], "Ada")
        self.assertEqual(found["quotes"][0]["video"], "Career talk")
        self.assertIn("t=1", found["quotes"][0]["link"])
        audio = self.state / "clip.wav"
        with wave.open(str(audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\x00\x00" * 8000)
        Path(str(audio) + ".txt").write_text("0 1 fixture career line\n", encoding="utf-8")
        lines = transcripts.transcribe_audio(audio)
        self.assertIn("career", lines[0]["text"])
        os.environ["HF_TOKEN"] = "hf-test-token"
        labeled = transcripts.diarize(lines)
        self.assertEqual(labeled["engine"], "stub")
        self.assertNotIn("hf-test-token", json.dumps(labeled))
        quoted = product_api.try_handle("GET", "/api/quotes", {"q": "career plan"}, self.state)
        self.assertEqual(quoted[0], 200)
        self.assertEqual(quoted[1]["quotes"][0]["speaker"], "Ada")

    def test_emotion_and_humor_boundaries(self):
        shaped = emotion.shape(self.state, "Peace and kindness can wait with patience.", "career")
        self.assertIn("peace", shaped["fruits"])
        self.assertIn("kindness", shaped["fruits"])
        self.assertIn("patience", shaped["fruits"])
        self.assertNotIn("score", shaped)
        self.assertIn("fruits of the Spirit", shaped["system"])
        emotion.set_enabled(self.state, False)
        off = emotion.shape(self.state, "Peace", "career")
        self.assertEqual(off["system"], "")
        self.assertEqual(off["fruits"], [])
        listed = humor.list_bits(self.state)
        self.assertTrue(all(bit["sample"] for bit in listed["bits"]))
        self.assertTrue(all(bit["text"].startswith("Sample bit:") for bit in listed["bits"]))
        career = humor.pick(self.state, "career")
        self.assertEqual(career["bit"]["category"], "career")
        quiet = humor.pick(self.state, context="spend")
        self.assertIsNone(quiet["bit"])
        vault_bit = humor.pick(self.state, context="vault")
        self.assertIsNone(vault_bit["bit"])
        added = humor.add_bit(self.state, "A fresh clean line", ["fresh"], "career", "warm", True)
        self.assertFalse(added["sample"])

    def test_forbidden_project_is_not_mirrored(self):
        os.environ["SUPABASE_URL"] = "https://nexkymqahpkvzzlvivfi.supabase.co"
        os.environ["SUPABASE_ANON_KEY"] = "anon"
        created = job_runner.create_job(self.state, "ada", "task", {"note": "local"})
        self.assertEqual(created["mirror"]["refused"], "nexkymqahpkvzzlvivfi")
        self.assertFalse(created["mirror"]["cloud"])
        self.assertTrue(job_runner.get_job(self.state, created["id"])["ok"])


def robots_allows_private() -> bool:
    return scrape_job.robots_allows("User-agent: *\nDisallow: /private\n", "/private")
