from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prickly_imax_helper.browser import chrome_executable
from prickly_imax_helper.notify import notification_label, notification_method
from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.service import start_service


class PlatformAdapterTests(unittest.TestCase):
    def test_windows_default_path_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"LOCALAPPDATA": temp}, clear=False), mock.patch(
            "prickly_imax_helper.paths.platform.system", return_value="Windows"
        ), mock.patch.dict(os.environ, {"PRICKLY_IMAX_HOME": ""}, clear=False):
            self.assertEqual(RuntimePaths.default().root, Path(temp) / "PricklyIMAXHelper")

    def test_windows_chrome_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            chrome = Path(temp) / "Google" / "Chrome" / "Application" / "chrome.exe"
            chrome.parent.mkdir(parents=True)
            chrome.touch()
            environment = {"PROGRAMFILES": temp, "PROGRAMFILES(X86)": "", "LOCALAPPDATA": "", "PRICKLY_CHROME": ""}
            with mock.patch.dict(os.environ, environment, clear=False), mock.patch(
                "prickly_imax_helper.browser.platform.system", return_value="Windows"
            ):
                self.assertEqual(chrome_executable(), chrome)

    def test_windows_service_uses_named_scheduled_task(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("prickly_imax_helper.service.platform.system", return_value="Windows"), mock.patch(
            "prickly_imax_helper.service.subprocess.run", return_value=completed
        ) as run:
            self.assertIs(start_service(), completed)
        run.assert_called_once_with(
            ["schtasks.exe", "/Run", "/TN", "Prickly IMAX Helper"], text=True, capture_output=True
        )

    def test_macos_service_start_preserves_an_active_monitor(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("prickly_imax_helper.service.platform.system", return_value="Darwin"), mock.patch(
            "prickly_imax_helper.service.os.getuid", return_value=501, create=True
        ), mock.patch("prickly_imax_helper.service.subprocess.run", return_value=completed) as run:
            self.assertIs(start_service(), completed)
        run.assert_called_once_with(
            ["/bin/launchctl", "kickstart", "-p", "gui/501/ai.prickly.imax-helper"], text=True, capture_output=True
        )

    def test_windows_notification_copy_names_outlook(self):
        with mock.patch("prickly_imax_helper.notify.platform.system", return_value="Windows"):
            self.assertEqual(notification_method(), "outlook_desktop")
            self.assertEqual(notification_label(), "Outlook 데스크톱")


if __name__ == "__main__":
    unittest.main()
