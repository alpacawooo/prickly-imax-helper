from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prickly_imax_helper.monitor import _notify
from prickly_imax_helper.notify import MAIL_SCRIPT, OUTLOOK_SCRIPT, send_email
from prickly_imax_helper.paths import RuntimePaths


class NotificationTests(unittest.TestCase):
    def test_attempt_linked_notification_records_each_successful_channel(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            config = {"notification": {"email": "private@example.com"}}
            with patch("prickly_imax_helper.monitor.show_notification"), patch(
                "prickly_imax_helper.monitor.send_email"
            ), patch("prickly_imax_helper.monitor.write_event") as write:
                _notify(paths, config, "subject", "body", attempt_id="attempt-a")

        self.assertEqual(
            [(call.args[1], call.kwargs) for call in write.call_args_list],
            [
                ("notification_result", {"attempt_id": "attempt-a", "channel": "desktop", "outcome": "passed"}),
                ("notification_result", {"attempt_id": "attempt-a", "channel": "email", "outcome": "passed"}),
            ],
        )

    def test_attempt_linked_notification_records_failures_without_recipient(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            config = {"notification": {"email": "private@example.com"}}
            with patch(
                "prickly_imax_helper.monitor.show_notification", side_effect=RuntimeError("desktop unavailable")
            ), patch("prickly_imax_helper.monitor.send_email", side_effect=RuntimeError("mail unavailable")), patch(
                "prickly_imax_helper.monitor.write_event"
            ) as write:
                _notify(paths, config, "subject", "body", attempt_id="attempt-a")

        events = [(call.args[1], call.kwargs) for call in write.call_args_list]
        self.assertEqual(
            events,
            [
                ("desktop_notification_failed", {"error": "desktop unavailable"}),
                ("notification_result", {"attempt_id": "attempt-a", "channel": "desktop", "outcome": "failed"}),
                ("email_failed", {"error": "mail unavailable"}),
                ("notification_result", {"attempt_id": "attempt-a", "channel": "email", "outcome": "failed"}),
            ],
        )
        self.assertNotIn("private@example.com", repr(events))

    @unittest.skipUnless(platform.system() == "Darwin", "AppleScript compiler is macOS-only")
    def test_mail_applescript_compiles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "mail.applescript"
            output = root / "mail.scpt"
            source.write_text(MAIL_SCRIPT, encoding="utf-8")
            process = subprocess.run(["/usr/bin/osacompile", "-o", str(output), str(source)], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)

    def test_user_values_are_arguments_not_script_source(self):
        recipient = 'person+"quote"@example.com'
        with patch("prickly_imax_helper.notify.platform.system", return_value="Darwin"), patch(
            "prickly_imax_helper.notify.subprocess.run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            send_email(recipient, 'subject " test', "body")
        command = run.call_args.args[0]
        self.assertEqual(command[-3:], [recipient, 'subject " test', "body"])
        self.assertNotIn(recipient, MAIL_SCRIPT)

    def test_windows_outlook_values_use_child_environment_not_script_source(self):
        recipient = 'person+"quote"@example.com'
        with patch("prickly_imax_helper.notify.platform.system", return_value="Windows"), patch(
            "prickly_imax_helper.notify.powershell_executable", return_value="powershell.exe"
        ), patch("prickly_imax_helper.notify.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            send_email(recipient, 'subject " test', "body")
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertNotIn(recipient, " ".join(command))
        self.assertNotIn(recipient, OUTLOOK_SCRIPT)
        self.assertEqual(environment["PRICKLY_NOTIFY_TO"], recipient)
        self.assertEqual(environment["PRICKLY_NOTIFY_SUBJECT"], 'subject " test')
        self.assertEqual(environment["PRICKLY_NOTIFY_BODY"], "body")
        self.assertEqual(environment.get("PATH"), os.environ.get("PATH"))


if __name__ == "__main__":
    unittest.main()
