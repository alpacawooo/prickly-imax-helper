from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prickly_imax_helper.cli import main
from prickly_imax_helper.locks import LockUnavailable
from prickly_imax_helper.monitor import AlreadyRunning
from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.state import Status, transition


class CliPrivacyTests(unittest.TestCase):
    def test_setup_fails_fast_when_monitor_is_running(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "prickly_imax_helper.cli.locked_file", side_effect=LockUnavailable("busy")
        ), patch("prickly_imax_helper.cli.serve_setup") as setup:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--home", temp, "setup"]), 2)
            setup.assert_not_called()
            self.assertIn("먼저", output.getvalue())

    def test_run_exits_cleanly_when_monitor_is_already_running(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "prickly_imax_helper.monitor.run", side_effect=AlreadyRunning()
        ):
            self.assertEqual(main(["--home", temp, "run"]), 0)

    def test_dry_run_reports_existing_monitor_without_creating_another(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "prickly_imax_helper.monitor.run", side_effect=AlreadyRunning()
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--home", temp, "dry-run"]), 2)
            self.assertIn("중복 프로세스", output.getvalue())

    def test_stop_is_idempotent_for_every_terminal_state(self):
        for terminal in (
            Status.COMPLETED,
            Status.UNKNOWN_AFTER_SUBMIT,
            Status.BLOCKED_DUPLICATE,
            Status.BLOCKED_PAYMENT,
            Status.FATAL,
            Status.STOPPED,
        ):
            with self.subTest(terminal=terminal.value), tempfile.TemporaryDirectory() as temp:
                paths = RuntimePaths(Path(temp))
                paths.prepare()
                paths.heartbeat.write_text(
                    json.dumps({"status": terminal.value}),
                    encoding="utf-8",
                )
                with patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(main(["--home", temp, "stop"]), 0)
                self.assertEqual(json.loads(output.getvalue())["status"], terminal.value)

    def test_stop_during_submission_becomes_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            transition(paths.heartbeat, Status.STAGING)
            transition(paths.heartbeat, Status.SUBMITTING)
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(main(["--home", temp, "stop"]), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], Status.UNKNOWN_AFTER_SUBMIT.value)

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
