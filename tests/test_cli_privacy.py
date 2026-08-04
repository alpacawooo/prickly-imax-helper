from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from prickly_imax_helper.cli import main


class CliPrivacyTests(unittest.TestCase):
    def test_status_redacts_even_manually_modified_state(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            state = home / "state" / "heartbeat.json"
            state.parent.mkdir()
            state.write_text(
                json.dumps({"status": "armed", "cookie": "session-secret", "detail": "mail person@example.com"}),
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["--home", str(home), "status"])
            self.assertEqual(result, 0)
            payload = output.getvalue()
            self.assertNotIn("session-secret", payload)
            self.assertNotIn("person@example.com", payload)
            self.assertIn("[REDACTED]", payload)

    def test_diagnose_redacts_legacy_untrusted_log_content(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            logs = home / "logs"
            logs.mkdir()
            (logs / "legacy.jsonl").write_text(
                json.dumps({"event": "legacy", "authorization": "Bearer secret", "message": "person@example.com 123456789012"}) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["--home", str(home), "diagnose"])
            self.assertEqual(result, 0)
            payload = output.getvalue()
            self.assertNotIn("Bearer secret", payload)
            self.assertNotIn("person@example.com", payload)
            self.assertNotIn("123456789012", payload)
            self.assertIn("[REDACTED]", payload)


if __name__ == "__main__":
    unittest.main()
