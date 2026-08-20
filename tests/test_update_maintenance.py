from __future__ import annotations

import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import prickly_imax_helper.maintenance as maintenance
from prickly_imax_helper.cli import main as cli_main
from prickly_imax_helper.config import write_config
from prickly_imax_helper.locks import locked_file
from prickly_imax_helper.maintenance import (
    MaintenanceError,
    arm_update,
    begin_update,
    end_update,
    parse_old_cli_json,
    replace_runtime,
    verify_monitor_stopped,
)
from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.state import Status, transition
from test_runtime_core import VALID_CONFIG


ROOT = Path(__file__).resolve().parents[1]


class FakeWindowsProcessApi:
    ERROR_ACCESS_DENIED = 5
    ERROR_INVALID_PARAMETER = 87
    STILL_ACTIVE = 259

    def __init__(self, *, handle: int = 42, exit_code: int | None = STILL_ACTIVE, last_error: int = 0):
        self.handle = handle
        self.exit_code = exit_code
        self.last_error = last_error
        self.opened_pids: list[int] = []
        self.closed_handles: list[int] = []

    def open_process(self, pid: int) -> int:
        self.opened_pids.append(pid)
        return self.handle

    def get_last_error(self) -> int:
        return self.last_error

    def get_exit_code(self, handle: int) -> int | None:
        if handle != self.handle:
            raise AssertionError("queried the wrong process handle")
        return self.exit_code

    def close_handle(self, handle: int) -> None:
        self.closed_handles.append(handle)


class UpdateMaintenanceTests(unittest.TestCase):
    def configured_paths(self, root: Path) -> RuntimePaths:
        paths = RuntimePaths(root)
        paths.prepare()
        write_config(paths.config, copy.deepcopy(VALID_CONFIG))
        transition(paths.heartbeat, Status.LOGIN_REQUIRED)
        return paths

    def test_begin_is_atomic_under_the_service_control_lock_and_crash_state_blocks_start(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.configured_paths(Path(temp))
            environment = {**os.environ, "PYTHONPATH": str(ROOT / "runtime")}
            ready = Path(temp) / "begin-ready"
            script = (
                "import os; "
                "from pathlib import Path; "
                "from prickly_imax_helper.maintenance import begin_update; "
                "from prickly_imax_helper.paths import RuntimePaths; "
                f"Path({str(ready)!r}).touch(); "
                f"print(begin_update(RuntimePaths(Path({temp!r})), owner_pid=os.getppid()))"
            )
            command = [
                sys.executable,
                "-c",
                script,
            ]
            with locked_file(paths.state_dir / "service-control.lock"):
                process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
                deadline = time.monotonic() + 5
                while process.poll() is None and not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "maintenance helper did not reach begin_update")
                time.sleep(0.1)
                self.assertIsNone(process.poll(), "maintenance begin bypassed service-control.lock")
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertTrue(paths.maintenance_barrier.is_file())

            completed = subprocess.CompletedProcess([], 0, "", "")
            with patch("prickly_imax_helper.cli.start_service", return_value=completed) as start:
                self.assertEqual(cli_main(["--home", temp, "start"]), 2)
            start.assert_not_called()

            token = stdout.strip()
            end_update(paths, token)
            self.assertFalse(paths.maintenance_barrier.exists())

    def test_barrier_owner_is_exclusive_and_only_matching_owner_can_clear_it(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            token = begin_update(paths)
            with self.assertRaises(MaintenanceError):
                begin_update(paths)
            with self.assertRaises(MaintenanceError):
                end_update(paths, "not-the-owner")
            self.assertTrue(paths.maintenance_barrier.exists())
            end_update(paths, token)

    def test_windows_process_query_reports_live_dead_and_access_denied_without_os_kill(self):
        cases = (
            ("live", FakeWindowsProcessApi(exit_code=259), True, [42]),
            ("dead", FakeWindowsProcessApi(exit_code=0), False, [42]),
            ("access denied", FakeWindowsProcessApi(handle=0, last_error=5), True, []),
        )
        for name, api, expected, closed in cases:
            with self.subTest(name=name), patch.object(
                maintenance, "_is_windows", return_value=True, create=True
            ), patch.object(
                maintenance, "_WindowsProcessApi", return_value=api, create=True
            ), patch.object(maintenance.os, "kill", side_effect=AssertionError("Windows liveness called os.kill")):
                self.assertEqual(maintenance._process_is_running(1234), expected)
            self.assertEqual(api.opened_pids, [1234])
            self.assertEqual(api.closed_handles, closed)

    def test_posix_process_query_retains_non_destructive_signal_zero_semantics(self):
        cases = ((None, True), (ProcessLookupError(), False), (PermissionError(), True))
        for side_effect, expected in cases:
            with self.subTest(side_effect=type(side_effect).__name__), patch.object(
                maintenance, "_is_windows", return_value=False
            ), patch.object(maintenance.os, "kill", side_effect=side_effect) as kill:
                self.assertEqual(maintenance._process_is_running(1234), expected)
            kill.assert_called_once_with(1234, 0)

    def test_windows_second_updater_rejects_live_owner_without_signaling_it_and_dead_owner_is_adopted(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            first_token = begin_update(paths)
            live_api = FakeWindowsProcessApi(exit_code=259)
            with patch.object(maintenance, "_is_windows", return_value=True, create=True), patch.object(
                maintenance, "_WindowsProcessApi", return_value=live_api, create=True
            ), patch.object(maintenance.os, "kill", side_effect=AssertionError("Windows updater signaled owner")):
                with self.assertRaisesRegex(MaintenanceError, "another installer"):
                    begin_update(paths)
            self.assertIn(first_token, paths.maintenance_barrier.read_text(encoding="utf-8"))
            self.assertEqual(live_api.closed_handles, [42])

            dead_api = FakeWindowsProcessApi(exit_code=0)
            with patch.object(maintenance, "_is_windows", return_value=True, create=True), patch.object(
                maintenance, "_WindowsProcessApi", return_value=dead_api, create=True
            ), patch.object(maintenance.os, "kill", side_effect=AssertionError("Windows updater signaled owner")):
                adopted_token = begin_update(paths)
            self.assertNotEqual(adopted_token, first_token)
            self.assertEqual(dead_api.closed_handles, [42])
            end_update(paths, adopted_token)

    def test_active_installer_barrier_prevents_a_second_updater_from_repointing_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = RuntimePaths(root / "home")
            launcher = root / "launcher.py"
            launcher.write_text("original launcher\n", encoding="utf-8")
            runtime = root / "release-runtime"
            runtime.mkdir()
            token = begin_update(paths)
            with self.assertRaises(MaintenanceError):
                arm_update(paths, launcher, runtime)
            self.assertEqual(launcher.read_text(encoding="utf-8"), "original launcher\n")
            end_update(paths, token)

    def test_arm_creates_crash_barrier_before_attempting_launcher_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = RuntimePaths(root / "home")
            launcher = root / "launcher.py"
            launcher.write_text("original launcher\n", encoding="utf-8")
            runtime = root / "release-runtime"
            runtime.mkdir()

            def fail_after_observing_barrier(*args, **kwargs):
                self.assertTrue(paths.maintenance_barrier.is_file())
                raise OSError("simulated launcher handoff crash")

            with patch("prickly_imax_helper.maintenance.install_launcher", side_effect=fail_after_observing_barrier):
                with self.assertRaisesRegex(OSError, "handoff crash"):
                    arm_update(paths, launcher, runtime)

            self.assertTrue(paths.maintenance_barrier.is_file())
            self.assertEqual(launcher.read_text(encoding="utf-8"), "original launcher\n")

    def test_crashed_installer_barrier_can_be_adopted_without_unblocking_start(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            environment = {**os.environ, "PYTHONPATH": str(ROOT / "runtime")}
            script = (
                "import os; "
                "from pathlib import Path; "
                "from prickly_imax_helper.maintenance import begin_update; "
                "from prickly_imax_helper.paths import RuntimePaths; "
                f"print(begin_update(RuntimePaths(Path({temp!r})), owner_pid=os.getpid()))"
            )
            crashed = subprocess.run(
                [sys.executable, "-c", script], text=True, capture_output=True, env=environment, check=True
            )
            first_token = crashed.stdout.strip()
            self.assertTrue(paths.maintenance_barrier.is_file())

            adopted_token = begin_update(paths)
            self.assertNotEqual(adopted_token, first_token)
            self.assertTrue(paths.maintenance_barrier.is_file())
            end_update(paths, adopted_token)

    def test_direct_service_run_is_a_safe_noop_while_update_barrier_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            token = begin_update(paths)
            with patch("prickly_imax_helper.monitor.run") as run:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli_main(["--home", temp, "run"]), 0)
            run.assert_not_called()
            rendered = output.getvalue().strip()
            self.assertTrue(rendered.isascii())
            self.assertEqual(json.loads(rendered), {"ok": False, "error": "update in progress; run is blocked"})
            end_update(paths, token)

    def test_monitor_lock_is_reprobed_immediately_before_runtime_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            token = begin_update(paths)
            with locked_file(paths.state_dir / "monitor.lock"):
                with self.assertRaises(MaintenanceError):
                    verify_monitor_stopped(paths, token)
            verify_monitor_stopped(paths, token)
            end_update(paths, token)

    def test_isolated_update_replaces_runtime_and_preserves_config_profile_while_blocking_each_race_phase(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = self.configured_paths(root / "home")
            profile_marker = paths.browser_profile / "profile-marker"
            profile_marker.write_text("keep-profile", encoding="utf-8")
            config_before = paths.config.read_bytes()
            old_runtime = paths.root / "app" / "0.2.1" / "runtime"
            old_runtime.mkdir(parents=True)
            (old_runtime / "version.txt").write_text("0.2.1", encoding="utf-8")
            old_launcher = paths.root / "venv" / "bin" / "prickly-imax"
            old_launcher.parent.mkdir(parents=True)
            old_launcher.write_text("old 0.2.1 launcher\n", encoding="utf-8")
            target = paths.root / "app" / "0.2.4" / "runtime"
            target.mkdir(parents=True)
            (target / "version.txt").write_text("old-candidate", encoding="utf-8")
            source = ROOT / "runtime"
            token = arm_update(paths, old_launcher, source)
            completed = subprocess.CompletedProcess([], 0, "", "")

            def assert_start_blocked(phase: str) -> None:
                with self.subTest(phase=phase), patch(
                    "prickly_imax_helper.cli.start_service", return_value=completed
                ) as start:
                    self.assertEqual(cli_main(["--home", str(paths.root), "start"]), 2)
                    start.assert_not_called()

            assert_start_blocked("before old status and stop")
            status = subprocess.run(
                [sys.executable, str(old_launcher), "--home", str(paths.root), "status"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(parse_old_cli_json(status.stdout), Status.LOGIN_REQUIRED.value)
            stop = subprocess.run(
                [sys.executable, str(old_launcher), "--home", str(paths.root), "stop"],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(stop.returncode, 0, stop.stderr)
            self.assertEqual(parse_old_cli_json(stop.stdout, stop_payload=True), Status.STOPPED.value)
            assert_start_blocked("before service-exit poll")
            verify_monitor_stopped(paths, token)
            assert_start_blocked("between poll and teardown")

            real_copytree = shutil.copytree

            def copytree_during_update(*args, **kwargs):
                assert_start_blocked("during runtime replacement")
                return real_copytree(*args, **kwargs)

            with patch("prickly_imax_helper.maintenance.shutil.copytree", side_effect=copytree_during_update):
                replace_runtime(paths, token, source, target)

            self.assertIn('__version__ = "0.2.4"', (target / "prickly_imax_helper" / "__init__.py").read_text())
            self.assertEqual((old_runtime / "version.txt").read_text(encoding="utf-8"), "0.2.1")
            self.assertEqual(paths.config.read_bytes(), config_before)
            self.assertEqual(profile_marker.read_text(encoding="utf-8"), "keep-profile")
            self.assertTrue(paths.maintenance_barrier.is_file())
            end_update(paths, token)

    def test_partial_install_runtime_without_launcher_is_atomically_replaced_without_stale_or_nested_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = RuntimePaths(root / "home")
            target = paths.root / "app" / "0.2.4" / "runtime"
            target.mkdir(parents=True)
            (target / "stale-sentinel.txt").write_text("must disappear", encoding="utf-8")

            token = begin_update(paths)
            replace_runtime(paths, token, ROOT / "runtime", target)

            self.assertFalse((target / "stale-sentinel.txt").exists())
            self.assertFalse((target / "runtime").exists(), "release runtime was nested inside the target")
            self.assertIn('__version__ = "0.2.4"', (target / "prickly_imax_helper" / "__init__.py").read_text())
            debris = list(target.parent.glob(".runtime.update-*")) + list(target.parent.glob(".runtime.backup-*"))
            self.assertEqual(debris, [])
            end_update(paths, token)


if __name__ == "__main__":
    unittest.main()
