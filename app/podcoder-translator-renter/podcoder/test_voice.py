#!/usr/bin/env python3
"""Simko SI voice mode. Offline: xAI speech-to-text, Grok and text-to-speech are faked.

- all 28 xAI built-in voices, each under a Simko SI sea-life name
- xAI default speed 1.0 and lowest-latency streaming are what we send
- the host streams MP3 to the app; the key never reaches the app
- a spoken request goes through the same turn handler as typing:
  coding plan, RUN, crash reported as failure, "fix it"
- mic permissions on Android and iOS, and the phone bundle carries simco-voice.js
"""
from __future__ import annotations

import base64
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "local"))

import product_api  # noqa: E402
import voice  # noqa: E402
import xai_client  # noqa: E402
from test_grok_full import CRASHING, FIXED, FakeGrok, GrokBase  # noqa: E402

REPO = ROOT.parent.parent
FAKE_KEY = "xai-test-key-not-real-123"
# GET https://api.x.ai/v1/tts/voices, 2026-10-30
XAI_VOICES = {
    "altair", "ara", "atlas", "aurora", "carina", "castor", "celeste", "cosmo", "eve", "helios",
    "helix", "iris", "kepler", "leo", "liora", "lumen", "luna", "lux", "naksh", "orion",
    "perseus", "rex", "rigel", "sal", "sirius", "ursa", "zagan", "zenith",
}


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200, ctype: str = "audio/mpeg"):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeXai:
    """Stands in for urllib.request.urlopen against api.x.ai."""

    def __init__(self, stt_text="write a python script that adds two numbers", fail_status=None):
        self.requests = []
        self.stt_text = stt_text
        self.fail_status = fail_status

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.fail_status:
            raise urllib.error.HTTPError(request.full_url, self.fail_status, "x", {}, io.BytesIO(FAKE_KEY.encode()))
        if request.full_url.endswith("/tts"):
            return FakeResponse(b"ID3" + b"\x00" * 9000)
        if request.full_url.endswith("/stt"):
            return FakeResponse(json.dumps({"text": self.stt_text}).encode(), ctype="application/json")
        raise AssertionError("unexpected url " + request.full_url)


def audio_body(**extra):
    return {"audio": base64.b64encode(b"\x1aE\xdf\xa3fake-webm").decode(), "mime": "audio/webm", **extra}


class VoiceListTests(unittest.TestCase):
    def test_all_xai_voices_have_one_new_name(self):
        self.assertEqual({v["provider_voice"] for v in voice.VOICES}, XAI_VOICES)
        self.assertEqual(len(voice.VOICES), 28)
        ids = [v["id"] for v in voice.VOICES]
        names = [v["name"] for v in voice.VOICES]
        self.assertEqual(len(set(ids)), 28)
        self.assertEqual(len(set(names)), 28)
        for v in voice.VOICES:
            self.assertNotIn(v["id"], XAI_VOICES)
            self.assertNotIn(v["name"].lower(), XAI_VOICES)

    def test_app_never_sees_provider_voice_names(self):
        code, body = product_api.try_handle("GET", "/api/voice/voices", None, Path(tempfile.mkdtemp()))
        self.assertEqual(code, 200)
        text = json.dumps(body).lower()
        for name in XAI_VOICES:
            self.assertNotIn('"' + name + '"', text)
        self.assertEqual(body["default_voice"], "coral")
        self.assertEqual(body["default_speed"], 1.0)
        self.assertEqual((body["min_speed"], body["max_speed"]), (0.7, 1.5))

    def test_default_matches_xai_default(self):
        self.assertEqual(voice.resolve(None)["provider_voice"], "eve")
        self.assertEqual(voice.resolve("nope")["id"], "coral")


class TtsTests(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(xai_client, "api_key", return_value=FAKE_KEY)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def body(self, req):
        return json.loads(req.data.decode())

    def test_request_uses_default_speed_and_lowest_latency(self):
        req = voice.tts_request("Hello.", "kraken")
        sent = self.body(req)
        self.assertTrue(req.full_url.endswith("/v1/tts"))
        self.assertEqual(sent["voice_id"], "zagan")
        self.assertEqual(sent["speed"], 1.0)
        self.assertEqual(sent["optimize_streaming_latency"], 2)
        self.assertEqual(sent["language"], "en")

    def test_speed_is_clamped_to_xai_range(self):
        self.assertEqual(self.body(voice.tts_request("a", "coral", 3))["speed"], 1.5)
        self.assertEqual(self.body(voice.tts_request("a", "coral", 0.1))["speed"], 0.7)
        self.assertEqual(self.body(voice.tts_request("a", "coral", "x"))["speed"], 1.0)

    def test_long_replies_and_code_are_trimmed_for_speech(self):
        said = voice.speakable("Here it is. ```python\nprint(1)\n``` " + "Word. " * 400)
        self.assertNotIn("print(1)", said)
        self.assertLessEqual(len(said), voice.MAX_SPEAK_CHARS + 40)

    def test_errors_are_short_codes_not_bodies(self):
        resp, err = voice.open_tts("hi", "coral", opener=FakeXai(fail_status=401))
        self.assertIsNone(resp)
        self.assertEqual(err, "unauthorized")


class FakeHandler:
    def __init__(self):
        self.wfile = io.BytesIO()
        self.status = None
        self.headers = {}

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        self.headers[k] = v

    def end_headers(self):
        pass


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(xai_client, "api_key", return_value=FAKE_KEY)
        self.p.start()
        self.state = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.p.stop()

    def test_speech_streams_without_length(self):
        fake, h = FakeXai(), FakeHandler()
        voice.serve_speech(h, "voice=orca&speed=1.0&text=Hello%20Joseph", self.state, opener=fake)
        self.assertEqual(h.status, 200)
        self.assertEqual(h.headers["Content-Type"], "audio/mpeg")
        self.assertNotIn("Content-Length", h.headers)
        self.assertTrue(h.wfile.getvalue().startswith(b"ID3"))
        self.assertEqual(json.loads(fake.requests[0].data)["voice_id"], "atlas")
        self.assertNotIn(FAKE_KEY.encode(), h.wfile.getvalue())

    def test_preview_is_cached_on_the_host(self):
        fake = FakeXai()
        for _ in range(2):
            voice.serve_speech(FakeHandler(), "voice=seahorse&preview=1", self.state, opener=fake)
        self.assertEqual(len(fake.requests), 1)
        self.assertIn("Seahorse", json.loads(fake.requests[0].data)["text"])

    def test_missing_key_is_503(self):
        h = FakeHandler()
        with mock.patch.object(xai_client, "api_key", return_value=""):
            voice.serve_speech(h, "voice=coral&text=hi", self.state, opener=FakeXai())
        self.assertEqual(h.status, 503)


class SttTests(unittest.TestCase):
    def test_multipart_has_model_and_file_last(self):
        fake = FakeXai(stt_text="hello")
        with mock.patch.object(xai_client, "api_key", return_value=FAKE_KEY):
            out = voice.transcribe(b"abc", "audio/mp4", opener=fake)
        self.assertEqual(out, {"ok": True, "text": "hello"})
        data = fake.requests[0].data
        self.assertIn(b'name="model"\r\n\r\ngrok-voice-transcribe-2.0', data)
        self.assertGreater(data.index(b'name="file"'), data.index(b'name="keyterm"'))
        self.assertIn(b'filename="speech.m4a"', data)

    def test_spoken_run_becomes_the_confirm_word(self):
        self.assertEqual(voice.normalize_command("Run."), "RUN")
        self.assertEqual(voice.normalize_command("run the tests"), "run the tests")


class VoiceTurnTests(GrokBase):
    def voice_turn(self, said, path="/api/voice/turn", **extra):
        fake = FakeXai(stt_text=said)
        with mock.patch("urllib.request.urlopen", fake):
            return product_api.try_handle("POST", path, audio_body(**extra), self.state)

    def test_transcribe_returns_words(self):
        code, body = self.voice_turn("Run.", path="/api/voice/transcribe")
        self.assertEqual((code, body), (200, {"ok": True, "text": "RUN"}))

    def test_spoken_coding_request_is_the_same_grok_job(self):
        code, body = self.voice_turn("write a python script that adds two numbers")
        self.assertEqual(code, 200, body)
        self.assertEqual(body["transcript"], "write a python script that adds two numbers")
        self.assertEqual(body["intent"], "coding")
        self.assertEqual(body["engine"], "grok")
        self.assertTrue(body["needs_confirm"])

    def test_spoken_crash_is_failure_and_spoken_fix_it_works(self):
        code, body = self.voice_turn("write a python script that divides one by zero and prints it")
        with mock.patch.object(xai_client, "chat", FakeGrok(CRASHING)):
            self.run_job(body["job_id"])
        job = self.status(body["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertNotIn("Done", job["everyday"])
        with mock.patch.object(xai_client, "chat", FakeGrok(FIXED)):
            code, fixed = self.voice_turn("Fix it.", wait=True)
        self.assertEqual(code, 200, fixed)
        self.assertEqual(fixed["intent"], "coding")
        self.assertEqual(self.status(fixed["job_id"])["status"], "done")

    def test_no_speech_is_a_plain_retry(self):
        fake = FakeXai(stt_text="")
        with mock.patch("urllib.request.urlopen", fake):
            code, body = product_api.try_handle("POST", "/api/voice/turn", audio_body(), self.state)
        self.assertEqual(code, 422)
        self.assertIn("didn't catch", body["everyday"])

    def test_voice_needs_grok(self):
        with mock.patch.object(xai_client, "api_key", return_value=""):
            code, body = product_api.try_handle("POST", "/api/voice/transcribe", audio_body(), self.state)
        self.assertEqual(code, 503)

    def test_oversize_audio_is_refused(self):
        big = {"audio": "A" * (voice.MAX_AUDIO_BYTES * 2), "mime": "audio/webm"}
        code, body = product_api.try_handle("POST", "/api/voice/transcribe", big, self.state)
        self.assertEqual((code, body["error"]), (400, "audio_too_long"))


class LocalServerTests(unittest.TestCase):
    """The host web UI server: voice routes, streaming, and the voice script."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = mock.patch.dict(os.environ, {"PODCODER_STATE_DIR": cls.tmp.name})
        cls.env.start()
        import server as local_server
        cls.httpd = local_server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.env.stop()
        cls.tmp.cleanup()

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        return resp, resp.read()

    def test_voice_script_and_list_are_served(self):
        resp, data = self.get("/simco-voice.js")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"/api/voice/speak", data)
        resp, data = self.get("/api/voice/voices")
        self.assertEqual(len(json.loads(data)["voices"]), 28)

    def test_speak_streams_and_allows_the_phone_origin(self):
        fake = FakeXai()
        with mock.patch.object(xai_client, "api_key", return_value=FAKE_KEY), \
                mock.patch.object(voice.urllib.request, "urlopen", fake):
            resp, data = self.get("/api/voice/speak?voice=dolphin&text=Hi", {"Origin": "capacitor://localhost"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "audio/mpeg")
        self.assertEqual(resp.getheader("Access-Control-Allow-Origin"), "capacitor://localhost")
        self.assertTrue(data.startswith(b"ID3"))
        self.assertEqual(json.loads(fake.requests[0].data)["voice_id"], "castor")


class SurfaceTests(unittest.TestCase):
    """Every surface gets voice: host web UI, Android app, iPhone app."""

    def read(self, rel):
        return (REPO / rel).read_text(encoding="utf-8")

    def test_web_ui_has_picker_mic_and_hooks(self):
        html = self.read("podcoder-translator-renter/local/chat.html")
        for needle in ('id="voicePicker"', 'id="voiceList"', 'id="voiceSpeed"', 'id="micButton"',
                       'src="simco-voice.js"', "simcoVoice.consumeTurn", "voiceReply(everydayLine)"):
            self.assertIn(needle, html)

    def test_phone_bundle_matches_host_ui(self):
        for name in ("chat.html", "simco-voice.js"):
            self.assertEqual(self.read("podcoder-translator-renter/local/" + name),
                             self.read("simco-mobile/www/" + name), name)
        self.assertIn("simco-voice.js", self.read("simco-mobile/sync-www.sh"))

    def test_mic_permission_on_both_platforms(self):
        self.assertIn("android.permission.RECORD_AUDIO",
                      self.read("simco-mobile/android/app/src/main/AndroidManifest.xml"))
        self.assertIn("NSMicrophoneUsageDescription", self.read("simco-mobile/ios/App/App/Info.plist"))

    def test_no_key_in_shipped_files(self):
        for path in (REPO / "simco-mobile" / "www").rglob("*"):
            if path.suffix in {".js", ".html", ".json"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                self.assertNotRegex(text, r"xai-[A-Za-z0-9]{20,}", str(path))
                self.assertNotIn("api.x.ai", text, str(path))


if __name__ == "__main__":
    unittest.main()
