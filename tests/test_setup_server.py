from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.setup_server import run_setup


class SetupServerTests(unittest.TestCase):
    def test_token_required_and_save_records_consent(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp) / "runtime")
            server, url = run_setup(paths, open_page=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                try:
                    urllib.request.urlopen(base + "/", timeout=2)
                except urllib.error.HTTPError as denied:
                    self.assertEqual(denied.code, 404)
                    denied.close()
                else:
                    self.fail("setup page must reject requests without its token")
                with urllib.request.urlopen(url, timeout=2) as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                    self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-origin")
                    self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                    page = response.read().decode("utf-8")
                    self.assertIn("Prickly IMAX Helper", page)
                    self.assertRegex(page, r"<button[^>]+value=login[^>]+formnovalidate")
                token = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["token"][0]
                payload = urllib.parse.urlencode(
                    {
                        "token": token,
                        "action": "save",
                        "email": "pilot@example.com",
                        "consent": "yes",
                        "network": "yes",
                    }
                ).encode("utf-8")
                request = urllib.request.Request(base + "/action", data=payload, method="POST")
                with patch("prickly_imax_helper.setup_server.login_verified", return_value=True), patch("prickly_imax_helper.setup_server.send_email"):
                    with urllib.request.urlopen(request, timeout=2) as response:
                        self.assertIn("설정 저장 완료", response.read().decode("utf-8"))
                config = json.loads(paths.config.read_text(encoding="utf-8"))
                self.assertTrue(config["consent"]["automatic_submission"])
                self.assertEqual(config["request_policy"]["minimum_interval_seconds"], 1.0)
                self.assertEqual(config["notification"]["email"], "pilot@example.com")
                heartbeat = json.loads(paths.heartbeat.read_text(encoding="utf-8"))
                self.assertEqual(heartbeat["status"], "login_required")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_configuration_is_not_saved_before_login(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp) / "runtime")
            server, url = run_setup(paths, open_page=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                token = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["token"][0]
                payload = urllib.parse.urlencode(
                    {"token": token, "action": "save", "email": "pilot@example.com", "consent": "yes", "network": "yes"}
                ).encode("utf-8")
                request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/action", data=payload, method="POST")
                with patch("prickly_imax_helper.setup_server.login_verified", return_value=False):
                    try:
                        urllib.request.urlopen(request, timeout=2)
                    except urllib.error.HTTPError as denied:
                        self.assertEqual(denied.code, 400)
                        self.assertIn("로그인이 확인되지 않았습니다", denied.read().decode("utf-8"))
                        denied.close()
                    else:
                        self.fail("setup must not save before login verification")
                self.assertFalse(paths.config.exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
