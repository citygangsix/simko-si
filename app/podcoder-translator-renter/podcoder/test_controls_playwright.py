#!/usr/bin/env python3
"""Click every main-screen control and require a backend call or a state change.

Confirm Rent is never given the exact confirm word, so this test cannot rent.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "local"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PODCODER_DRY_RUN", "1")
os.environ.pop("PODCODER_SETUP_LIVE", None)
os.environ.pop("PODCODER_SIMCO_LIVE_OLLAMA", None)


def _chrome():
    from playwright.sync_api import sync_playwright

    return sync_playwright


class ControlClickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.playwright_factory = _chrome()
        except Exception as exc:
            raise unittest.SkipTest(f"playwright is not installed: {exc}") from exc
        import install_hook
        import server as local_server

        cls.install_hook = install_hook
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["PODCODER_STATE_DIR"] = cls.tmp.name
        os.environ["PODCODER_DRY_RUN"] = "1"
        cls.httpd = local_server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.pw = cls.playwright_factory().start()
        cls.browser = cls.pw.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    @classmethod
    def tearDownClass(cls):
        browser = getattr(cls, "browser", None)
        if browser:
            browser.close()
        pw = getattr(cls, "pw", None)
        if pw:
            pw.stop()
        httpd = getattr(cls, "httpd", None)
        if httpd:
            httpd.shutdown()
            httpd.server_close()
        tmp = getattr(cls, "tmp", None)
        if tmp:
            tmp.cleanup()
        os.environ.pop("PODCODER_STATE_DIR", None)

    def setUp(self):
        self.install_hook._ACTIVE["on"] = False
        self.page = self.browser.new_page()
        self.hits = []
        self.page.on("request", lambda request: self.hits.append((request.method, request.url, request.post_data or "")))
        self.page.on("response", self._remember_response)
        self.responses = []

    def _remember_response(self, response):
        if "/api/" not in response.url:
            return
        try:
            text = response.text()
        except Exception:
            text = ""
        self.responses.append((response.status, response.url, text))

    def tearDown(self):
        self.page.close()

    def _clear(self):
        self.hits.clear()
        self.responses.clear()

    def _saw(self, path, method=None):
        return any(path in url and (method is None or req_method == method) for req_method, url, _body in self.hits)

    def _assert_api(self, path, method="POST"):
        self.assertTrue(self._saw(path, method), f"missing {method} {path} in {self.hits}")

    def _assert_no_live_rent(self):
        for method, url, body in self.hits:
            if "/api/rent" in url and method == "POST":
                self.assertIn("dry_run", body)
                self.assertNotIn('"dry_run": false', body.replace(" ", ""))
                self.assertNotIn('"confirm": "RENT"', body)
                self.assertNotIn('"confirm":"RENT"', body)
        for _status, url, text in self.responses:
            if "/api/" in url:
                self.assertNotIn('"vast_calls": 1', text)
                self.assertNotIn('"destroyed": true', text)

    def _open_tools(self):
        drawer = self.page.locator("#drawer")
        if drawer.is_hidden():
            self.page.locator("#toolsToggle").click()
        drawer.wait_for(state="visible")

    def test_messenger_tools_advanced_and_folds(self):
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
        self.page.locator("#turtleScreen").wait_for(state="visible")
        self.page.locator("#turtleEnter").wait_for(state="visible", timeout=20000)
        details = self.page.locator("#turtleDetails")
        if details.count():
            details.locator("summary").click()
        self.assertIn("Aider", self.page.locator("#turtleLog").inner_text())
        self.assertIn("Profile", self.page.locator("#turtleLog").inner_text())
        log = self.page.locator("#turtleLog").inner_text()
        self.assertNotIn("Ada slot", log)
        self.assertNotIn("ada-granite", log.lower())
        self.assertNotIn("-ada-", log.lower())
        api_blob = " ".join(text for _status, url, text in self.responses if "/api/probe" in url or "/api/setup" in url)
        self.assertNotIn("ada-granite", api_blob)
        self.assertNotIn('"adapter"', api_blob)
        self.assertNotIn("-ada-", api_blob)
        self._assert_api("/api/setup")
        self._clear()
        self.page.locator("#turtleEnter").click()
        self.assertTrue(self.page.locator("#turtleScreen").is_hidden())

        self.page.locator("#searchChats").click()
        self.assertFalse(self.page.locator("#chatSearch").is_hidden())
        self._clear()
        self.page.locator("#chatSearch").fill("career")
        self.page.wait_for_timeout(300)
        self._assert_api("/api/sessions")
        self.assertIn('"op":"search"', " ".join(body for _m, _u, body in self.hits))
        self.assertIn("Career plan", self.page.locator("#sessionList").inner_text())
        self.assertEqual(self.page.locator("#sessionList button").count(), 1)
        self.page.locator("#sessionList button").first.click()
        self.assertEqual(self.page.locator("#threadTitle").inner_text(), "Career plan")
        self.page.locator("#chatSearch").fill("")
        self.page.wait_for_timeout(300)

        self._clear()
        self.page.locator("#sessionList button").nth(1).click()
        self.assertEqual(self.page.locator("#threadTitle").inner_text(), "Health check")

        self.page.set_viewport_size({"width": 412, "height": 960})
        self.page.locator("#backToList").click()
        self.assertNotIn("thread-open", self.page.locator("body").get_attribute("class") or "")
        self.page.locator("#sessionList button").first.click()
        self.page.locator("#backToList").click()

        self.page.set_viewport_size({"width": 1280, "height": 800})
        self._open_tools()
        self.page.locator("#authEmail").fill("simco-controls@example.com")
        self.page.locator("#authPassword").fill("correct-horse")
        self._clear()
        self.page.locator("#signUp").click()
        self.page.wait_for_function("() => (document.getElementById('authWho').textContent || '').includes('@')")
        self._assert_api("/api/auth")
        self.assertIn("simco-controls@example.com", self.page.locator("#authWho").inner_text())
        self.page.locator("#confirmEmail").wait_for(state="visible")
        self.page.locator("#confirmEmail").click()
        self.page.wait_for_timeout(200)
        self._assert_api("/api/auth")

        self._clear()
        self.page.locator("#newChat").click()
        self.page.wait_for_timeout(300)
        self._assert_api("/api/sessions")
        self._clear()
        self.page.locator("#newChat").click()
        self.page.wait_for_timeout(300)
        self.page.locator("#everyday").fill("note for the other chat")
        self.page.locator("#sendToChat").click()
        self.page.locator("#relay-sheet").wait_for(state="visible")
        self._clear()
        self.page.locator("#relayGo").click()
        self.page.wait_for_timeout(300)
        self._assert_api("/api/sessions")
        self.assertIn("relay", " ".join(body for _m, _u, body in self.hits))

        self._clear()
        self.page.locator("#everyday").fill("make multiply show 7 times 8")
        self.page.locator("#go").click()
        self.page.wait_for_timeout(400)
        self._assert_api("/api/simco/turn")
        self.assertNotEqual(self.page.locator("#reply-bubble").inner_text().strip(), "")

        self._open_tools()
        self.page.locator("#lifebook summary").click()
        self.page.locator("#lifeTags button").first.wait_for(state="visible")
        self.page.locator("#lifeTags button").first.click()
        self.page.wait_for_timeout(200)
        self._assert_api("/api/memory")

        for button, path in (
            ("#roleVideo", "/api/probe"),
            ("#roleImage", "/api/probe"),
            ("#roleCoding", "/api/probe"),
            ("#detectHardware", "/api/probe"),
            ("#computeLocal", "/api/compute"),
            ("#computeCloud", "/api/compute"),
        ):
            self._clear()
            self.page.locator(button).click()
            self.page.wait_for_timeout(250)
            self._assert_api(path)

        self._clear()
        self.page.locator("#rentComputer").click()
        self.page.locator("#rent-sheet").wait_for(state="visible")
        self._assert_api("/api/offers", "GET")
        self._clear()
        self.page.locator("#confirmRentGo").click()
        self.page.wait_for_timeout(200)
        self.assertIn("I confirm RENT", self.page.locator("#reply-bubble").inner_text())
        self._assert_api("/api/offers", "GET")
        self.assertFalse(any("/api/rent" in url for _m, url, _b in self.hits))

        self._clear()
        self.page.locator("#downloadNow").click()
        self.page.wait_for_timeout(400)
        self._assert_api("/api/download")

        self._clear()
        self.page.locator("#openTurtle").click()
        self.assertFalse(self.page.locator("#turtleScreen").is_hidden())
        self.page.locator("#turtlePeek").click()
        self.assertTrue(self.page.locator("#turtleScreen").is_hidden())

        self._clear()
        self.page.locator("#signOut").click()
        self.page.wait_for_timeout(200)
        self._assert_api("/api/auth")
        self._clear()
        self.page.locator("#authEmail").fill("simco-controls@example.com")
        self.page.locator("#resetPassword").click()
        self.page.locator("#setPassword").wait_for(state="visible")
        self._assert_api("/api/auth")
        self.page.locator("#authPassword").fill("another-horse")
        self._clear()
        self.page.locator("#setPassword").click()
        self.page.wait_for_timeout(300)
        self._assert_api("/api/auth")
        self._clear()
        self.page.locator("#authPassword").fill("another-horse")
        self.page.locator("#signIn").click()
        self.page.wait_for_function("() => (document.getElementById('authWho').textContent || '').includes('@')")
        self._assert_api("/api/auth")

        self.page.locator("#advancedLink").click()
        self.page.wait_for_url("**/translator.html")
        self.page.locator("#go").wait_for()

        checks = [
            ("#previewRent", "/api/offers", "GET"),
            ("#confirmRent", "/api/offers", "GET"),
            ("#rentConfirmBtn", "/api/rent", "POST"),
            ("#doRentDry", "/api/rent", "POST"),
            ("#installStack", "/api/install", "POST"),
            ("#saveCompute", "/api/compute", "POST"),
            ("#newSession", "/api/sessions", "POST"),
            ("#saveMemory", "/api/memory", "POST"),
            ("#saveVault", "/api/vault", "POST"),
            ("#wanPrompt", "/api/translate/wan", "POST"),
        ]
        self.page.locator("#everyday").evaluate("node => { node.disabled = false; }")
        self.page.locator("#everyday").fill("a red kite over a lake")
        self.page.locator("#vaultPass").fill("secret-pass")
        self.page.locator("#vaultEmail").fill("ada@example.com")
        self.page.locator("#lifeNote").fill("a quiet evening")
        for selector, path, method in checks:
            self._clear()
            self.page.locator(selector).click()
            self.page.wait_for_timeout(300)
            self._assert_api(path, method)
            self._assert_no_live_rent()

        self.page.locator("#previewRent").click()
        self.page.wait_for_function("() => document.getElementById('rentConfirm').style.display === 'block'")
        self.page.locator("#cancelRent").click()
        self.assertEqual(self.page.locator("#rentConfirm").evaluate("node => node.style.display"), "none")

        self.page.locator("#showRaw").check()
        self.assertEqual(self.page.locator("body").get_attribute("data-show-raw"), "yes")
        self.page.locator("#includeWan").uncheck()
        self.assertFalse(self.page.locator("#includeWan").is_checked())
        self.page.locator("#rolePreset").select_option("image")
        self.assertIn("no Wan", self.page.locator("#installBanner").inner_text())
        self._clear()
        self.page.locator("#installComfy").click()
        self.page.wait_for_timeout(300)
        self._assert_api("/api/install/comfyui")

        self.page.locator("#targetLabel").fill("local")
        self.page.locator("#targetHost").fill("127.0.0.1")
        self.page.locator("#ollamaBase").fill("http://127.0.0.1:11434")
        self.page.locator("#saveTarget").click()
        stored = self.page.evaluate("localStorage.getItem('translator_targets')")
        self.assertIn("127.0.0.1", stored or "")

        self.page.locator("#feature").evaluate("node => { node.disabled = false; node.value = 'mul'; node.dispatchEvent(new Event('change')); }")
        self.assertEqual(self.page.evaluate("window.lastFeature"), "mul")
        self._clear()
        self.page.locator("#go").evaluate("node => { node.disabled = false; node.click(); }")
        self.page.wait_for_timeout(300)
        self._assert_api("/api/install/status", "GET")
        self._clear()
        self.page.locator("#runMission").evaluate("node => { node.disabled = false; node.click(); }")
        self.page.wait_for_timeout(300)
        self._assert_api("/api/install/status", "GET")
        self.assertIn("locked", self.page.locator("#missionOut").inner_text().lower())

        self._assert_no_live_rent()

        self.page.set_viewport_size({"width": 412, "height": 960})
        self.page.goto(f"http://127.0.0.1:{self.port}/turtle", wait_until="networkidle")
        self.page.locator("#turtleCard").wait_for(state="visible")
        box = self.page.locator("#turtleCard").bounding_box()
        self.assertIsNotNone(box)
        self.assertLessEqual(box["width"], 412)
        self.page.set_viewport_size({"width": 750, "height": 832})
        self.page.locator("#turtleCard").wait_for(state="visible")
        inner = self.page.locator("#turtleCard").bounding_box()
        self.assertLessEqual(inner["width"], 750)
        self.assertGreater(inner["height"], 40)

    def test_computer_button_sends_api_calls_to_the_saved_host(self):
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
        self.page.locator("#turtleEnter").wait_for(state="visible", timeout=20000)
        self.page.locator("#turtleEnter").click()
        self._open_tools()
        self.page.locator("#openHost").click()
        self.page.locator("#hostUrl").wait_for(state="visible")
        base = f"http://127.0.0.1:{self.port}"
        self.page.locator("#hostUrl").fill("https://example.trycloudflare.com")
        self.page.locator("#hostSave").click()
        self.assertIn("own http", self.page.locator("#hostHint").inner_text())
        self._clear()
        self.page.locator("#hostUrl").fill(base)
        self.page.locator("#hostSave").click()
        self.page.wait_for_timeout(500)
        urls = [url for _method, url, _body in self.hits]
        self.assertTrue(any(url.startswith(base + "/api/") for url in urls), urls)
        self._assert_no_live_rent()

    def test_turtle_card_controls_get_server_answers(self):
        self.page.set_viewport_size({"width": 1280, "height": 900})
        self.page.goto(f"http://127.0.0.1:{self.port}/turtle", wait_until="networkidle")
        self.page.locator("#turtleEnter").wait_for(state="visible", timeout=20000)
        details = self.page.locator("#turtleDetails")
        if details.count():
            details.locator("summary").click()
        self._clear()
        self.page.locator("#turtleRedetect").click()
        self.page.wait_for_timeout(400)
        self._assert_api("/api/probe")
        log = self.page.locator("#turtleLog").inner_text()
        self.assertTrue("CPU" in log or "Memory" in log, log)
        self.assertNotIn("ada-granite", log.lower())
        self.assertNotIn("-ada-", log.lower())
        self.assertNotIn("Ada slot", log)
        self._clear()
        self.page.locator("#turtleCheck").click()
        self.page.wait_for_timeout(500)
        self._assert_api("/api/setup")
        self._assert_api("/api/install/status", "GET")
        stage = self.page.locator("#turtleStage").inner_text().strip()
        self.assertIn(stage, {"Waiting", "Downloading", "Ready"})
        self._clear()
        self.page.locator("#turtleQuestion").fill("make multiply show 7 times 8")
        self.page.locator("#turtleAskSend").click()
        self.page.locator("#turtleReply").wait_for(state="visible")
        self.page.wait_for_function("() => (document.getElementById('turtleReply').textContent || '').trim().length > 0")
        self._assert_api("/api/simco/turn")
        self.assertTrue(self.page.locator("#turtleReply").inner_text().strip())
        self.assertFalse(any("/api/rent" in url for _method, url, _body in self.hits))
        self.page.locator("#turtleCard").screenshot(path=str(Path(tempfile.gettempdir()) / "simco-turtle-ask.png"))

    def test_theme_picker_switches_plain_and_keeps_the_choice(self):
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.goto(f"http://127.0.0.1:{self.port}/", wait_until="networkidle")
        self.page.evaluate("() => localStorage.removeItem('simcoTheme')")
        self.page.reload(wait_until="networkidle")
        self.page.locator("#turtlePeek").click()
        self._open_tools()
        self.page.locator('#themeList button[data-theme-id="plain"]').wait_for()
        self.assertEqual(self.page.evaluate("() => document.documentElement.dataset.theme"), "reef-live")
        self.page.locator("#themeStage .reef-mover").first.wait_for(state="attached")
        self.page.locator('#themeList button[data-theme-id="reef-still"]').click()
        self.assertEqual(self.page.evaluate("() => document.documentElement.dataset.theme"), "reef-still")
        self.assertEqual(self.page.locator("#themeStage").count(), 0)
        self.page.locator('#themeList button[data-theme-id="plain"]').click()
        plain = self.page.evaluate(
            """() => {
              const stage = document.getElementById('themeStage');
              const swim = document.querySelector('.turtle-swim');
              const swimCss = swim ? getComputedStyle(swim) : null;
              return {
                theme: document.documentElement.dataset.theme,
                motion: document.documentElement.dataset.motion,
                stageOff: !stage || getComputedStyle(stage).display === 'none',
                swim: swimCss ? swimCss.animationName : 'none',
                bg: getComputedStyle(document.body).backgroundImage,
                saved: localStorage.getItem('simcoTheme')
              };
            }"""
        )
        self.assertEqual(plain["theme"], "plain")
        self.assertEqual(plain["motion"], "off")
        self.assertTrue(plain["stageOff"])
        self.assertEqual(plain["swim"], "none")
        self.assertEqual(plain["bg"], "none")
        self.assertEqual(plain["saved"], "plain")
        self.page.reload(wait_until="networkidle")
        self.assertEqual(self.page.evaluate("() => document.documentElement.dataset.theme"), "plain")
        self.assertEqual(self.page.evaluate("() => localStorage.getItem('simcoTheme')"), "plain")
        self.assertEqual(
            self.page.evaluate("() => getComputedStyle(document.body).backgroundImage"),
            "none",
        )

    def test_reef_live_pauses_when_idle_hidden_or_low_battery(self):
        self.page.set_viewport_size({"width": 1100, "height": 800})
        self.page.goto(f"http://127.0.0.1:{self.port}/turtle", wait_until="domcontentloaded")
        self.page.evaluate("() => localStorage.setItem('simcoTheme', 'reef-live')")
        self.page.reload(wait_until="networkidle")
        self.page.locator("#themeStage .reef-mover").first.wait_for(state="attached", timeout=10000)
        self.page.evaluate(
            """() => {
              window.simcoMotion.battery = false;
              window.simcoMotion.hiddenOverride = false;
              window.simcoMotion.idleMs = 30;
              window.simcoMotion.bump();
            }"""
        )
        self.page.wait_for_function(
            "() => document.documentElement.dataset.motion === 'off'",
            timeout=2000,
        )
        self.assertEqual(
            self.page.evaluate(
                "() => getComputedStyle(document.querySelector('#themeStage .reef-mover')).animationPlayState"
            ),
            "paused",
        )
        self.page.evaluate(
            """() => {
              window.simcoMotion.idle = false;
              window.simcoMotion.hiddenOverride = true;
              window.simcoMotion.refresh();
            }"""
        )
        self.assertEqual(self.page.evaluate("() => document.documentElement.dataset.motion"), "off")
        self.assertTrue(
            self.page.evaluate("() => document.documentElement.classList.contains('simco-turtle-paused')")
        )
        self.page.evaluate(
            """() => {
              window.simcoMotion.hiddenOverride = false;
              window.simcoMotion.idle = false;
              window.simcoMotion.battery = true;
              window.simcoMotion.refresh();
            }"""
        )
        self.assertEqual(self.page.evaluate("() => document.documentElement.dataset.motion"), "off")
        self.assertEqual(
            self.page.evaluate(
                "() => getComputedStyle(document.querySelector('#themeStage .reef-mover')).animationPlayState"
            ),
            "paused",
        )

    def test_reef_motion_uses_display_refresh(self):
        self.page.set_viewport_size({"width": 1100, "height": 800})
        self.page.goto(f"http://127.0.0.1:{self.port}/", wait_until="domcontentloaded")
        self.page.evaluate("() => localStorage.setItem('simcoTheme', 'reef-live')")
        self.page.reload(wait_until="networkidle")
        self.page.locator("#reefCaustics").wait_for(state="attached", timeout=10000)
        self.page.wait_for_timeout(900)
        video = self.page.evaluate(
            """() => {
              const v = document.getElementById('reefVideo');
              return {
                on: document.documentElement.classList.contains('reef-video-on'),
                loop: document.documentElement.dataset.reefLoop || '',
                src: v ? v.getAttribute('src') : '',
                paused: v ? v.paused : true
              };
            }"""
        )
        if video["on"]:
            # The real reef loop replaced the vector layer: wide loop on a wide window, playing.
            self.assertEqual(video["loop"], "wide")
            self.assertTrue(video["src"].endswith("reef-wide-720p.mp4"))
            self.assertFalse(video["paused"])
            self.page.set_viewport_size({"width": 412, "height": 900})
            self.page.wait_for_timeout(600)
            self.assertEqual(self.page.evaluate("() => document.documentElement.dataset.reefLoop"), "tall")
            self.assertTrue(
                self.page.evaluate("() => document.getElementById('reefVideo').getAttribute('src')").endswith(
                    "reef-tall-720p.mp4"
                )
            )
            self.page.evaluate("() => { window.simcoMotion.idle = true; window.simcoMotion.refresh(); }")
            self.page.wait_for_timeout(200)
            self.assertTrue(self.page.evaluate("() => document.getElementById('reefVideo').paused"))
            return
        stats = self.page.evaluate(
            """() => {
              const canvas = document.getElementById('reefCaustics');
              const dpr = window.devicePixelRatio || 1;
              const width = canvas ? canvas.clientWidth : 0;
              return {
                mode: window.simcoFrameStats && window.simcoFrameStats.mode,
                capped: window.simcoFrameStats && window.simcoFrameStats.capped,
                frames: window.simcoFrameStats && window.simcoFrameStats.frames,
                fps: window.simcoFrameStats && window.simcoFrameStats.fps,
                ratio: width ? canvas.width / width : 0,
                dpr: dpr
              };
            }"""
        )
        self.assertEqual(stats["mode"], "requestAnimationFrame")
        self.assertFalse(stats["capped"])
        self.assertGreater(stats["frames"], 20)
        self.assertAlmostEqual(stats["ratio"], stats["dpr"], delta=0.05)


if __name__ == "__main__":
    unittest.main()
