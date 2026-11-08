#!/usr/bin/env python3
"""Gate tests for post-Confirm-Rent install. No Vast calls."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import install_hook

LOCAL_SERVER = ROOT.parent / "local" / "server.py"
SCRIPT = ROOT / "install-on-pod-q8.sh"


def load_local_server():
    spec = importlib.util.spec_from_file_location("podcoder_local_server", LOCAL_SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def http_json(method: str, url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, json.loads(raw)


class InstallHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "status"
        self.state.mkdir()
        self._env = {}
        for key in ("PODCODER_SSH_HOST", "PODCODER_SSH_PORT", "PODCODER_SSH_USER", "PODCODER_SSH_KEY", "PODCODER_STATE_DIR"):
            self._env[key] = os.environ.get(key)
            os.environ.pop(key, None)
        install_hook._ACTIVE["on"] = False
        install_hook._CHILD_PID["pid"] = None

    def tearDown(self):
        install_hook._ACTIVE["on"] = False
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def test_dry_run_does_not_install(self):
        calls = []

        def runner(*args):
            calls.append(args)
            return 0, install_hook.SMOKE_BANNER + "\n"

        result = install_hook.handle_rent(
            {"confirm": "RENT", "dry_run": True, "ssh_host": "10.0.0.8"},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=runner,
            sync=True,
        )
        self.assertEqual(result["install"], "not_started")
        self.assertEqual(calls, [])
        self.assertFalse(install_hook.rent_confirmed(self.state))
        self.assertFalse(install_hook.public_status(self.state)["coding_allowed"])

    def test_confirm_without_exact_word_is_rejected(self):
        result = install_hook.accept_rent(
            {"confirm": "rent", "dry_run": False, "ssh_host": "10.0.0.8"},
            self.state,
        )
        self.assertEqual(result["http"], 400)
        self.assertEqual(result["install"], "not_started")
        self.assertFalse((self.state / "rent-confirm.json").exists())

    def test_confirm_without_ssh_requires_install_stack(self):
        result = install_hook.handle_rent(
            {"confirm": "RENT", "dry_run": False, "offer_id": "55676201", "inet_down": 1200, "disk_gb": 150},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            sync=True,
        )
        self.assertEqual(result["install"], "needs_ssh")
        self.assertTrue(result["install_required"])
        self.assertEqual(result["vast_calls"], 0)
        self.assertFalse(result["destroyed"])
        self.assertTrue(install_hook.rent_confirmed(self.state))
        blocked = install_hook.handle_install({}, self.state, src_dir=ROOT, allow_local=False, sync=True)
        self.assertEqual(blocked["install"], "needs_ssh")
        self.assertFalse(install_hook.public_status(self.state)["coding_allowed"])

    def test_install_before_confirm_is_refused(self):
        result = install_hook.handle_install(
            {"confirm": "RENT", "ssh_host": "10.0.0.8"},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            sync=True,
        )
        self.assertEqual(result["http"], 403)
        self.assertIn("after Confirm Rent", result["error"])

    def test_reference_utah_is_not_a_live_protect_and_destroy_stays_offline(self):
        calls = []

        def runner(*args):
            calls.append(args)
            return 0, install_hook.SMOKE_BANNER + "\n"

        with self.assertRaises(install_hook.HookError) as caught:
            install_hook.handle_rent(
                {"destroy": True, "confirm": "DESTROY", "instance_id": "58092881"},
                self.state,
                src_dir=ROOT,
                allow_local=False,
                runner=runner,
            )
        self.assertEqual(caught.exception.code, 403)
        self.assertFalse(caught.exception.payload["destroyed"])
        self.assertEqual(caught.exception.payload["vast_calls"], 0)

        missing_bw = install_hook.handle_rent(
            {
                "confirm": "RENT",
                "dry_run": False,
                "instance_id": "58092881",
                "ssh_host": "10.9.9.9",
                "ssh_port": 22,
            },
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=runner,
            sync=True,
        )
        self.assertEqual(missing_bw["install"], "rejected_bandwidth")
        self.assertNotEqual(missing_bw["install"], "refused_protected_instance")
        self.assertEqual(calls, [])

        allowed = install_hook.handle_rent(
            {
                "confirm": "RENT",
                "dry_run": False,
                "instance_id": "58092881",
                "inet_down": 1200,
                "ssh_host": "10.9.9.9",
                "ssh_port": 22,
            },
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=runner,
            sync=True,
        )
        self.assertEqual(allowed["install"], "pass")
        self.assertEqual(allowed["vast_calls"], 0)
        self.assertFalse(allowed["destroyed"])
        self.assertEqual(len(calls), 1)

    def test_confirm_with_ssh_starts_install_and_smoke_unlocks(self):
        calls = []

        def runner(ssh, src, on_line):
            calls.append(ssh)
            on_line("==> Smoke generate")
            return 0, "smoke ok\n" + install_hook.SMOKE_BANNER + "\n"

        result = install_hook.handle_rent(
            {"confirm": "RENT", "dry_run": "false", "ssh_host": "10.1.2.3", "ssh_port": 2222, "ssh_user": "root", "inet_down": 1200},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=runner,
            sync=True,
        )
        self.assertEqual(calls, [{"host": "10.1.2.3", "port": 2222, "user": "root"}])
        self.assertEqual(result["install"], "pass")
        self.assertEqual(result["vast_calls"], 0)
        self.assertFalse(result["destroyed"])
        status = install_hook.public_status(self.state)
        self.assertTrue(status["coding_allowed"])
        self.assertIsNone(install_hook.coding_block(self.state))

    def test_exit_zero_without_banner_stays_locked(self):
        def runner(ssh, src, on_line):
            return 0, "finished without smoke banner\n"

        install_hook.handle_rent(
            {"confirm": "RENT", "dry_run": False, "ssh_host": "10.1.2.4", "inet_down": 1200},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=runner,
            sync=True,
        )
        status = install_hook.public_status(self.state)
        self.assertEqual(status["status"], "fail")
        self.assertFalse(status["coding_allowed"])
        self.assertIsNotNone(install_hook.coding_block(self.state))

    def test_second_install_does_not_interrupt_a_live_pid(self):
        install_hook.accept_rent({"confirm": "RENT", "dry_run": False, "ssh_host": "10.1.2.5", "inet_down": 1200}, self.state)
        install_hook._write_status(self.state, status="running", phase="pull", pid=os.getpid(), mode="live", error="")
        calls = []

        def runner(*args):
            calls.append(args)
            return 0, install_hook.SMOKE_BANNER

        result = install_hook.handle_install(
            {},
            self.state,
            src_dir=ROOT,
            allow_local=False,
            runner=runner,
            sync=True,
        )
        self.assertEqual(result["install"], "already_running")
        self.assertEqual(calls, [])
        self.assertFalse(install_hook.public_status(self.state)["coding_allowed"])

    def test_ssh_argv_has_no_destroy_and_rejects_injection(self):
        argv = install_hook.ssh_argv(
            {"host": "10.0.0.4", "port": 22, "user": "root"},
            install_hook.REMOTE_INSTALL_CMD,
        )
        joined = " ".join(argv)
        self.assertNotIn("destroy", joined.lower())
        self.assertNotIn("58092881", joined)
        self.assertNotIn("rsync", joined)
        self.assertEqual(argv[0], "ssh")
        self.assertEqual(argv[-1], install_hook.REMOTE_INSTALL_CMD)
        with self.assertRaises(ValueError):
            install_hook.ssh_from({"ssh_host": "10.0.0.1;rm -rf /"})
        with self.assertRaises(ValueError):
            install_hook.ssh_from({"ssh_host": "10.0.0.1", "ssh_user": "root;reboot"})
        self.assertEqual(install_hook.ssh_from({"ssh_host": "10.2.2.2"})["host"], "10.2.2.2")


class ScriptTests(unittest.TestCase):
    def test_script_refuses_destroy_and_has_no_cuda_copy(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("rsync", text)
        self.assertNotIn("api.vast.ai", text)
        self.assertIn("58092881", text)
        self.assertIn("https://ollama.com/install.sh", text)
        proc = subprocess.run(["bash", str(SCRIPT), "destroy"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("58092881", proc.stderr)

    def test_script_is_idempotent_with_fake_tools(self):
        work = Path(tempfile.mkdtemp(prefix="podcoder-q8-"))
        try:
            fake = work / "bin"
            fake.mkdir()
            log = work / "ollama.log"
            self._write(fake / "ollama", f"""#!/bin/bash
echo "$1" >> "{log}"
case "$1" in
  list) printf 'granite4.2:8b-q8_0\\n' ;;
  pull) exit 99 ;;
  serve) sleep 30 ;;
esac
exit 0
""")
            self._write(fake / "curl", """#!/bin/bash
if [[ "$*" == *install.sh* ]]; then
  echo "called install.sh" >&2
  exit 97
fi
if [[ "$*" == *api/generate* ]]; then
  printf '%s\\n' '{"response":"pong"}'
  exit 0
fi
exit 0
""")
            self._write(fake / "apt-get", "#!/bin/bash\nexit 0\n")
            self._write(fake / "aider", """#!/bin/bash
if [[ "${1:-}" == "--version" ]]; then
  echo "aider test"
fi
exit 0
""")
            for path in fake.iterdir():
                path.chmod(0o755)
            status = work / "install-status.json"
            dest = work / "opt"
            env = os.environ.copy()
            for key in list(env):
                if key.startswith("PODCODER_"):
                    env.pop(key)
            env.update({
                "PATH": str(fake) + os.pathsep + env.get("PATH", ""),
                "HOME": str(work / "home"),
                "PODCODER_DEST": str(dest),
                "PODCODER_TRANSLATOR_HOME": str(work / "translator"),
                "PODCODER_SKIP_SERVER_START": "1",
                "PODCODER_INSTALL_STATUS": str(status),
                "PODCODER_INSTALL_LOCK": str(work / "install.lock"),
                "PODCODER_VRAM_LOCK": str(work / "vram.json"),
            })
            (work / "home").mkdir()
            for _ in range(2):
                proc = subprocess.run(
                    ["bash", str(SCRIPT)],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn(install_hook.SMOKE_BANNER, proc.stdout)
                self.assertNotIn("install.sh", proc.stderr)
            pulled = log.read_text(encoding="utf-8").splitlines()
            self.assertNotIn("pull", pulled)
            doc = json.loads(status.read_text(encoding="utf-8"))
            self.assertEqual(doc["status"], "pass")
            self.assertEqual(doc["mode"], "live")
            self.assertFalse(doc["destroyed"])
            self.assertEqual(doc["reference_instance_id"], "58092881")
            self.assertTrue(doc["smoke"]["ollama_list"])
            self.assertTrue(doc["smoke"]["generate"])
            self.assertTrue(doc["smoke"]["aider_version"])
            self.assertTrue((dest / "mission_server.py").is_file())
            self.assertIn("Install stack", (dest / "seeds" / "translator.html").read_text(encoding="utf-8"))
            lock = work / "install.lock"
            hold = subprocess.Popen(["flock", str(lock), "sleep", "8"])
            try:
                import time
                time.sleep(0.3)
                busy = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(busy.returncode, 75, busy.stdout + busy.stderr)
                self.assertIn("PODCODER_INSTALL_ALREADY_RUNNING", busy.stdout)
            finally:
                hold.kill()
                hold.wait(timeout=5)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _write(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for key in ("PODCODER_SSH_HOST", "PODCODER_SSH_PORT", "PODCODER_SSH_USER", "PODCODER_SSH_KEY"):
            os.environ.pop(key, None)
        cls.server_mod = load_local_server()
        cls.httpd = cls.server_mod.make_server(0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        os.environ["PODCODER_STATE_DIR"] = str(self.state)
        install_hook._ACTIVE["on"] = False

    def tearDown(self):
        os.environ.pop("PODCODER_STATE_DIR", None)
        self.tmp.cleanup()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def test_http_gates(self):
        code, body = http_json("DELETE", self.url("/api/rent/58092881"))
        self.assertEqual(code, 403)
        self.assertFalse(body["destroyed"])
        self.assertEqual(body["vast_calls"], 0)
        self.assertIn("58092881", body["error"])
        self.assertIn("does not auto-destroy", body["error"])

        code, body = http_json("POST", self.url("/api/mission"), {"everyday": "do not run"})
        self.assertEqual(code, 409)
        self.assertFalse(body["coding_allowed"])

        code, body = http_json("POST", self.url("/api/rent"), {"confirm": "RENT", "dry_run": True})
        self.assertEqual(code, 200)
        self.assertEqual(body["install"], "not_started")

        code, body = http_json("POST", self.url("/api/install"), {"ssh_host": "10.2.2.2"})
        self.assertEqual(code, 403)

        code, body = http_json(
            "POST",
            self.url("/api/rent"),
            {"confirm": "RENT", "dry_run": False, "instance_id": "58092881", "ssh_host": "10.2.2.2"},
        )
        self.assertEqual(code, 403)
        self.assertEqual(body["install"], "rejected_bandwidth")
        self.assertEqual(body["vast_calls"], 0)

        code, body = http_json(
            "POST",
            self.url("/api/rent"),
            {"confirm": "RENT", "dry_run": False, "offer_id": "1", "inet_down": 1200, "role": "coding"},
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["install"], "needs_ssh")
        self.assertTrue(body["rent_accepted"])

        page = urllib.request.urlopen(self.url("/translator.html"), timeout=5).read().decode("utf-8")
        self.assertIn("After Confirm Rent", page)
        self.assertIn("Send (locked)", page)
        self.assertIn('id="go" disabled', page)
        self.assertIn('id="feature" disabled', page)
        home = urllib.request.urlopen(self.url("/"), timeout=5).read().decode("utf-8")
        self.assertIn('id="reply-bubble"', home)
        self.assertIn('id="input-bubble"', home)
        self.assertIn("Type everyday English", home)
        self.assertIn("Rent", home)
        self.assertIn(">Download<", home)
        self.assertIn('id="downloadNow"', home)
        self.assertIn('id="roleCoding"', home)
        self.assertIn('id="detectHardware"', home)
        self.assertIn('url("/coral-reef-bg.jpg")', home)
        self.assertIn('url("/coral-reef-bg-sm.jpg")', home)
        self.assertIn("viewport-fit=cover", home)
        self.assertIn('id="backToList"', home)
        self.assertIn('id="threadTitle"', home)
        self.assertIn('aria-label="New chat"', home)
        self.assertIn('aria-label="Send to chat"', home)
        self.assertIn('aria-label="Tools"', home)
        self.assertIn("horizontal-viewport-segments: 2", home)
        self.assertIn("vertical-viewport-segments: 2", home)
        self.assertIn("viewport-segment-left", home)
        self.assertIn("viewport-segment-width", home)
        self.assertTrue((ROOT.parent / "local" / "coral-reef-bg.jpg").is_file())
        self.assertTrue((ROOT.parent / "local" / "coral-reef-bg-sm.jpg").is_file())
        reef = urllib.request.urlopen(self.url("/coral-reef-bg.jpg"), timeout=5)
        self.assertEqual(reef.status, 200)
        self.assertTrue(reef.read(3).startswith(b"\xff\xd8"))
        small = urllib.request.urlopen(self.url("/coral-reef-bg-sm.jpg"), timeout=5)
        self.assertEqual(small.status, 200)
        self.assertTrue(small.read(3).startswith(b"\xff\xd8"))
        fold = home.split("function applyFold", 1)[1].split("function bindFold", 1)[0]
        self.assertNotIn("everyday", fold)
        self.assertNotIn("activeSessionId", fold)
        self.assertIn('id="newChat"', home)
        self.assertIn('id="sessionList"', home)
        self.assertIn('id="sendToChat"', home)
        self.assertIn('id="authEmail"', home)
        self.assertIn('id="authPassword"', home)
        self.assertIn(">Sign up<", home)
        self.assertIn(">Sign in<", home)
        self.assertNotIn("oauth", home.lower())
        self.assertNotIn("gmail", home.lower())
        self.assertIn('data-placeholder="Reply"', home)
        self.assertIn("await loadModel()", home)

        code, body = http_json(
            "POST",
            self.url("/api/probe"),
            {"role": "coding", "compute": "local", "probe": {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 80, "gpu": "Radeon"}},
        )
        self.assertEqual(code, 200)
        self.assertEqual(body["model"], "granite4.2:8b-q5_0")
        self.assertEqual(body["quant"], "Q5")
        self.assertEqual(body["vast_calls"], 0)
        code, body = http_json(
            "POST",
            self.url("/api/probe"),
            {"role": "coding", "compute": "local", "probe": {"ram_gb": 16, "vram_gb": 0, "disk_free_gb": 80, "gpu": "none"}},
        )
        self.assertEqual(body["model"], "granite4.2:8b")
        self.assertEqual(body["quant"], "Q4")
        code, body = http_json(
            "POST",
            self.url("/api/probe"),
            {"role": "video", "compute": "local", "probe": {"ram_gb": 32, "vram_gb": 0, "disk_free_gb": 80, "gpu": "none"}},
        )
        self.assertTrue(body["needs_rent"])
        code, body = http_json(
            "POST",
            self.url("/api/probe"),
            {"role": "coding", "compute": "local", "probe": {"ram_gb": 4, "vram_gb": 0, "disk_free_gb": 40, "gpu": "none"}},
        )
        self.assertTrue(body["needs_rent"])
        self.assertIn('href="/translator.html"', home)
        self.assertNotIn("rolePreset", home)
        self.assertNotIn("vaultPass", home)
        self.assertNotIn("offerList", home)

        install_hook._write_status(
            self.state,
            status="pass",
            phase="done",
            mode="live",
            error="",
            smoke={"ollama_list": True, "generate": True, "aider_version": True},
        )
        code, body = http_json("GET", self.url("/api/install/status"))
        self.assertEqual(code, 200)
        self.assertTrue(body["coding_allowed"])
        code, body = http_json("POST", self.url("/api/chat"), {"model": "granite4.2:8b-q8_0"})
        self.assertNotEqual(code, 409)


if __name__ == "__main__":
    unittest.main()
