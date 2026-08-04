from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prickly_imax_helper.notify import MAIL_SCRIPT, send_email


class NotificationTests(unittest.TestCase):
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
        with patch("prickly_imax_helper.notify.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stderr = ""
            run.return_value.stdout = ""
            send_email(recipient, 'subject " test', "body")
        command = run.call_args.args[0]
        self.assertEqual(command[-3:], [recipient, 'subject " test', "body"])
        self.assertNotIn(recipient, MAIL_SCRIPT)


if __name__ == "__main__":
    unittest.main()
