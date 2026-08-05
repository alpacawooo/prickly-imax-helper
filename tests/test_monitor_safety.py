from __future__ import annotations

import copy
import contextlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prickly_imax_helper.config import write_config
from prickly_imax_helper.cli import main as cli_main
from prickly_imax_helper.monitor import OPEN_DATE_REFRESH_SECONDS, run
from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.state import Status, read_state, transition
from test_runtime_core import VALID_CONFIG


class MonitorRestartSafetyTests(unittest.TestCase):
    def test_new_booking_dates_are_refreshed_within_thirty_seconds(self):
        self.assertLessEqual(OPEN_DATE_REFRESH_SECONDS, 30.0)

    def test_invalid_config_fails_closed_without_launch_or_restart_error(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            paths.config.write_text("{}\n", encoding="utf-8")
            with patch("prickly_imax_helper.monitor.launch_browser") as launch:
                self.assertEqual(run(paths), 0)
            launch.assert_not_called()
            self.assertEqual(read_state(paths.heartbeat)["status"], "fatal")

    def test_invalid_config_across_submission_boundary_becomes_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            paths.config.write_text("{}\n", encoding="utf-8")
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            transition(paths.heartbeat, Status.STAGING)
            transition(paths.heartbeat, Status.SUBMITTING)
            with patch("prickly_imax_helper.monitor.launch_browser") as launch:
                self.assertEqual(run(paths), 0)
            launch.assert_not_called()
            self.assertEqual(read_state(paths.heartbeat)["status"], "unknown_after_submit")

    def test_restart_during_submission_becomes_unknown_without_browser_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            transition(paths.heartbeat, Status.STAGING)
            transition(paths.heartbeat, Status.SUBMITTING)
            with patch("prickly_imax_helper.monitor.launch_browser") as launch, patch("prickly_imax_helper.monitor._notify"):
                self.assertEqual(run(paths), 2)
            launch.assert_not_called()
            self.assertEqual(read_state(paths.heartbeat)["status"], "unknown_after_submit")

    def test_dry_run_scans_without_checkout(self):
        class FakeSession:
            page = object()

            def __init__(self, *args, **kwargs):
                pass

            @contextlib.contextmanager
            def locked(self):
                yield self

            def require_login(self):
                return None

            def open_dates(self):
                return ["20260808"]

            def schedules(self, ymd):
                return [{"movkndDsplNm": "IMAX", "scnsrtTm": "1900", "scnsNo": "018", "scnSseq": "1", "frSeatCnt": 2}]

            def seats(self, ymd, screen_no, sequence):
                all_seats = [f"H{i}" for i in range(1, 31)]
                return {"all": all_seats, "available": ["H15", "H16"]}

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            with patch("prickly_imax_helper.monitor.launch_browser"), patch("prickly_imax_helper.monitor.CgvSession", FakeSession), patch("prickly_imax_helper.monitor._checkout") as checkout:
                self.assertEqual(run(paths, max_cycles=1, allow_checkout=False), 0)
            checkout.assert_not_called()
            self.assertEqual(read_state(paths.heartbeat)["status"], "armed")

    def test_dry_run_finishes_when_login_works_but_no_dates_are_open(self):
        class FakeSession:
            page = object()

            def __init__(self, *args, **kwargs):
                pass

            @contextlib.contextmanager
            def locked(self):
                yield self

            def require_login(self):
                return None

            def open_dates(self):
                return []

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            with patch("prickly_imax_helper.monitor.launch_browser"), patch(
                "prickly_imax_helper.monitor.CgvSession", FakeSession
            ):
                self.assertEqual(run(paths, max_cycles=1, allow_checkout=False), 0)
            state = read_state(paths.heartbeat)
            self.assertEqual(state["status"], "armed")
            self.assertEqual(state["open_dates"], 0)

    def test_stop_sentinel_prevents_browser_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            self.assertEqual(cli_main(["--home", temp, "stop"]), 0)
            self.assertTrue(paths.stop_requested.exists())
            with patch("prickly_imax_helper.monitor.launch_browser") as launch:
                self.assertEqual(run(paths), 0)
            launch.assert_not_called()

    def test_fixed_config_can_restart_from_fatal_state(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.FATAL)
            completed = subprocess.CompletedProcess([], 0, "", "")
            with patch("prickly_imax_helper.cli.start_service", return_value=completed) as start:
                self.assertEqual(cli_main(["--home", temp, "start"]), 0)
            start.assert_called_once_with()
            self.assertEqual(read_state(paths.heartbeat)["status"], "login_required")


if __name__ == "__main__":
    unittest.main()
