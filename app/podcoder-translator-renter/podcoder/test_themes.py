#!/usr/bin/env python3
"""Theme library: manifest, per-user settings, and safe static serving."""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "local"))
sys.path.insert(0, str(ROOT))

import auth_accounts
import product_api
import user_settings


class ThemeLibraryTests(unittest.TestCase):
    def test_manifest_ships_reef_live_still_and_plain(self):
        doc = user_settings.manifest()
        ids = [item["id"] for item in doc["themes"]]
        self.assertEqual(doc["default"], "reef-live")
        self.assertEqual(ids[:3], ["reef-live", "reef-still", "plain"])
        self.assertIn("reef-video", ids)
        video = next(item for item in doc["themes"] if item["id"] == "reef-video")
        self.assertTrue(video.get("disabled"))
        names = {item["id"]: item["name"] for item in doc["themes"]}
        self.assertEqual(names["plain"], "No theme / Plain")
        self.assertTrue(doc["themes"][0]["animation"])
        self.assertFalse(doc["themes"][1]["animation"])
        self.assertFalse(doc["themes"][2]["animation"])
        root = ROOT.parent / "local" / "themes"
        self.assertTrue((root / "THEMES.md").is_file())
        guide = (root / "THEMES.md").read_text(encoding="utf-8")
        self.assertIn("manifest.json", guide)
        self.assertIn("folder", guide.lower())
        plain = (root / "plain" / "theme.css").read_text(encoding="utf-8")
        self.assertIn("background-image: none", plain)
        self.assertIn("animation: none", plain)

    def test_signed_in_theme_is_saved_per_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            signed = auth_accounts.signup(state, "theme-owner@example.com", "correct-horse")
            token = signed[1]["token"]
            other = auth_accounts.signup(state, "other-owner@example.com", "correct-horse")
            other_token = other[1]["token"]
            missing = product_api.try_handle("POST", "/api/settings", {"op": "set", "theme": "plain"}, state)
            self.assertEqual(missing[0], 401)
            unknown = product_api.try_handle(
                "POST", "/api/settings", {"op": "set", "token": token, "theme": "../secret"}, state
            )
            self.assertEqual(unknown[0], 400)
            self.assertFalse(unknown[1]["ok"])
            saved = product_api.try_handle(
                "POST", "/api/settings", {"op": "set", "token": token, "theme": "plain"}, state
            )
            self.assertEqual(saved[0], 200)
            self.assertEqual(saved[1]["theme"], "plain")
            self.assertEqual(saved[1]["vast_calls"], 0)
            loaded = product_api.try_handle("POST", "/api/settings", {"op": "get", "token": token}, state)
            self.assertEqual(loaded[1]["theme"], "plain")
            untouched = product_api.try_handle(
                "POST", "/api/settings", {"op": "get", "token": other_token}, state
            )
            self.assertIsNone(untouched[1]["theme"])
            self.assertEqual(untouched[1]["default"], "reef-live")


class ThemeStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PODCODER_STATE_DIR"] = tempfile.mkdtemp(prefix="simco-themes-")
        import server

        cls.server = server
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, resp.getheader("Content-Type") or "", body

    def test_theme_files_are_served_and_escape_is_refused(self):
        status, ctype, body = self._get("/themes/manifest.json")
        self.assertEqual(status, 200)
        self.assertIn("json", ctype)
        doc = json.loads(body.decode("utf-8"))
        self.assertEqual(doc["default"], "reef-live")
        status, ctype, body = self._get("/themes/reef-live/theme.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", ctype)
        self.assertIn("themeStage", body.decode("utf-8"))
        status, _ctype, body = self._get("/themes/plain/theme.css")
        self.assertEqual(status, 200)
        self.assertIn(b"animation: none", body)
        status, _ctype, _body = self._get("/themes/../server.py")
        self.assertEqual(status, 400)
        status, _ctype, _body = self._get("/themes/reef-live/missing.css")
        self.assertEqual(status, 404)


    def test_reef_loops_are_served_with_byte_ranges(self):
        status, ctype, body = self._get("/themes/reef-live/video/reef-wide-720p.mp4")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "video/mp4")
        self.assertGreater(len(body), 100000)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/themes/reef-live/video/reef-tall-720p.mp4", headers={"Range": "bytes=0-99"})
        resp = conn.getresponse()
        part = resp.read()
        conn.close()
        self.assertEqual(resp.status, 206)
        self.assertEqual(len(part), 100)
        self.assertTrue(resp.getheader("Content-Range", "").startswith("bytes 0-99/"))


class ReefLoopAssetTests(unittest.TestCase):
    THEME = ROOT.parent / "local" / "themes" / "reef-live"

    def test_wide_and_tall_loops_ship_small(self):
        for name in ("reef-wide-720p.mp4", "reef-tall-720p.mp4"):
            path = self.THEME / "video" / name
            self.assertTrue(path.is_file(), name)
            self.assertLess(path.stat().st_size, 3 * 1024 * 1024, name)

    def test_layout_picks_wide_or_tall_and_pauses_with_motion(self):
        js = (self.THEME / "theme.js").read_text(encoding="utf-8")
        self.assertIn("reef-wide-720p.mp4", js)
        self.assertIn("reef-tall-720p.mp4", js)
        self.assertIn("(max-width: 640px)", js)
        self.assertIn("video.pause()", js)
        self.assertIn('"data-motion"', js)
        self.assertIn("playsinline", js)
        self.assertIn("muted", js)
        css = (self.THEME / "theme.css").read_text(encoding="utf-8")
        self.assertIn("#reefVideo", css)
        self.assertIn("reef-video-on", css)


if __name__ == "__main__":
    unittest.main()
