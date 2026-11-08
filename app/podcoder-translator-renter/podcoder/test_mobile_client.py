#!/usr/bin/env python3
"""Phone-client CORS. Capacitor origins are allowed. The open web is not."""
from __future__ import annotations

import http.client
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "local"))
os.environ["PODCODER_STATE_DIR"] = tempfile.mkdtemp(prefix="simco-cors-")
import server


class CorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_allowlist(self):
        self.assertTrue(server.allow_origin("https://localhost"))
        self.assertTrue(server.allow_origin("capacitor://localhost"))
        self.assertTrue(server.allow_origin("ionic://localhost"))
        self.assertTrue(server.allow_origin("http://127.0.0.1:8788"))
        self.assertFalse(server.allow_origin("https://evil.example"))
        self.assertFalse(server.allow_origin("https://demo.trycloudflare.com"))
        self.assertFalse(server.allow_origin(""))

    def _headers(self, method, path, origin):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        resp = conn.getresponse()
        headers = {key.lower(): value for key, value in resp.getheaders()}
        resp.read()
        conn.close()
        return resp.status, headers

    def test_preflight_for_the_phone_app(self):
        status, headers = self._headers("OPTIONS", "/api/setup", "https://localhost")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("access-control-allow-origin"), "https://localhost")
        self.assertIn("POST", headers.get("access-control-allow-methods", ""))
        self.assertIn("Content-Type", headers.get("access-control-allow-headers", ""))

    def test_public_sites_do_not_get_cors(self):
        status, headers = self._headers("GET", "/api/health", "https://evil.example")
        self.assertEqual(status, 200)
        self.assertNotIn("access-control-allow-origin", headers)

    def test_client_script_is_served_and_has_no_tunnel(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/simco-client.js")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn("simcoBackendUrl", body)
        self.assertNotIn("trycloudflare.com/", body)
        self.assertIn("com.simkosi.simcosi", body)


if __name__ == "__main__":
    unittest.main()
