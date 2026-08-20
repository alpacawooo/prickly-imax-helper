from __future__ import annotations

import copy
import contextlib
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from prickly_imax_helper.checkout import DuplicateBlocked, PaymentBlocked, TicketCheckUnavailable, UnknownAfterSubmit
from prickly_imax_helper.checkout_attempt import CheckoutAttemptRecorder
from prickly_imax_helper.config import write_config
from prickly_imax_helper.cli import main as cli_main
from prickly_imax_helper.locks import LockUnavailable, locked_file
from prickly_imax_helper.monitor import (
    CHECKOUT_GUARD_RETRY_SECONDS,
    _checkout,
    _kst_day,
    _refresh_discovery,
    rate_limit_backoff_seconds,
    run,
)
from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.scheduler import BalancedScanPlanner
from prickly_imax_helper.state import Status, read_state, transition
from test_runtime_core import VALID_CONFIG


class MonitorRestartSafetyTests(unittest.TestCase):
    def test_overlapping_start_processes_emit_only_one_service_request_after_monitor_owns_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            root = Path(temp)
            request_entered = root / "service-request-entered"
            request_log = root / "service-requests"
            allow_request = root / "allow-service-request"
            monitor_ready = root / "monitor-lock-ready"
            release_monitor = root / "release-monitor-lock"
            monitor_done = root / "monitor-lock-done"
            holder = textwrap.dedent(
                f"""
                import time
                from pathlib import Path
                from prickly_imax_helper.locks import locked_file

                ready = Path({str(monitor_ready)!r})
                release = Path({str(release_monitor)!r})
                with locked_file(Path({str(paths.state_dir / 'monitor.lock')!r})):
                    ready.touch()
                    deadline = time.monotonic() + 10
                    while not release.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                Path({str(monitor_done)!r}).touch()
                """
            )
            worker = textwrap.dedent(
                f"""
                import os
                import subprocess
                import sys
                import time
                from pathlib import Path
                import prickly_imax_helper.cli as cli

                entered = Path({str(request_entered)!r})
                requests = Path({str(request_log)!r})
                allow = Path({str(allow_request)!r})
                ready = Path({str(monitor_ready)!r})

                def safe_service_request():
                    with requests.open("a", encoding="utf-8") as stream:
                        stream.write(f"{{os.getpid()}}\\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    entered.touch()
                    deadline = time.monotonic() + 10
                    while not allow.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if not allow.exists():
                        raise RuntimeError("test service request was not released")
                    subprocess.Popen(
                        [sys.executable, "-c", {holder!r}],
                        env=os.environ.copy(),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                    )
                    deadline = time.monotonic() + 10
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if not ready.exists():
                        raise RuntimeError("test resident did not acquire monitor.lock")
                    return subprocess.CompletedProcess([], 0, "", "")

                cli.start_service = safe_service_request
                raise SystemExit(cli.main(["--home", {temp!r}, "start"]))
                """
            )
            environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "runtime")}
            processes: list[subprocess.Popen[str]] = []
            try:
                first = subprocess.Popen(
                    [sys.executable, "-c", worker],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                )
                processes.append(first)
                deadline = time.monotonic() + 5
                while not request_entered.exists() and first.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(request_entered.exists(), "first start did not enter the safe service adapter")

                second = subprocess.Popen(
                    [sys.executable, "-c", worker],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                )
                processes.append(second)
                time.sleep(0.15)
                self.assertIsNone(second.poll(), "second start did not overlap the locked first process")
                self.assertEqual(request_log.read_text(encoding="utf-8").splitlines(), [str(first.pid)])

                allow_request.touch()
                first_stdout, first_stderr = first.communicate(timeout=10)
                second_stdout, second_stderr = second.communicate(timeout=10)
                self.assertEqual(first.returncode, 0, first_stderr or first_stdout)
                self.assertEqual(second.returncode, 0, second_stderr or second_stdout)
                self.assertEqual(request_log.read_text(encoding="utf-8").splitlines(), [str(first.pid)])
            finally:
                allow_request.touch(exist_ok=True)
                release_monitor.touch(exist_ok=True)
                deadline = time.monotonic() + 5
                while monitor_ready.exists() and not monitor_done.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                        process.communicate(timeout=5)

    def test_start_from_login_required_requests_service_once_when_monitor_lock_is_free(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)

            with patch("prickly_imax_helper.cli.start_service", return_value=completed) as start:
                self.assertEqual(cli_main(["--home", temp, "start"]), 0)

            start.assert_called_once_with()
            self.assertEqual(read_state(paths.heartbeat)["status"], Status.LOGIN_REQUIRED.value)

    def test_start_does_not_request_service_when_monitor_lock_is_held(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)

            with locked_file(paths.state_dir / "monitor.lock"):
                with patch("prickly_imax_helper.cli.start_service", return_value=completed) as start:
                    self.assertEqual(cli_main(["--home", temp, "start"]), 0)

            start.assert_not_called()

    def test_start_holds_service_control_lock_until_service_request_finishes(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            lock_during_start = []

            def start_while_checking_control_lock():
                try:
                    with locked_file(paths.state_dir / "service-control.lock", blocking=False):
                        lock_during_start.append("unlocked")
                except LockUnavailable:
                    lock_during_start.append("held")
                return completed

            with patch("prickly_imax_helper.cli.start_service", side_effect=start_while_checking_control_lock):
                self.assertEqual(cli_main(["--home", temp, "start"]), 0)

            self.assertEqual(lock_during_start, ["held"])

    def test_start_preserves_dead_staging_for_run_recovery(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            transition(paths.heartbeat, Status.STAGING)

            with patch("prickly_imax_helper.cli.start_service", return_value=completed) as start:
                self.assertEqual(cli_main(["--home", temp, "start"]), 0)

            start.assert_called_once_with()
            self.assertEqual(read_state(paths.heartbeat)["status"], Status.STAGING.value)
            with patch("prickly_imax_helper.monitor.launch_browser", side_effect=RuntimeError("stop after recovery")):
                with self.assertRaisesRegex(RuntimeError, "stop after recovery"):
                    run(paths)
            self.assertEqual(read_state(paths.heartbeat)["status"], Status.RECOVERING.value)

    def test_start_preserves_dead_submitting_for_run_fail_closed_recovery(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            transition(paths.heartbeat, Status.STAGING)
            transition(paths.heartbeat, Status.SUBMITTING)

            with patch("prickly_imax_helper.cli.start_service", return_value=completed) as start:
                self.assertEqual(cli_main(["--home", temp, "start"]), 0)

            start.assert_called_once_with()
            self.assertEqual(read_state(paths.heartbeat)["status"], Status.SUBMITTING.value)
            with patch("prickly_imax_helper.monitor.launch_browser") as launch, patch("prickly_imax_helper.monitor._notify"):
                self.assertEqual(run(paths), 2)
            launch.assert_not_called()
            self.assertEqual(read_state(paths.heartbeat)["status"], Status.UNKNOWN_AFTER_SUBMIT.value)

    def test_start_never_requests_service_from_review_required_terminal_states(self):
        sequences = {
            Status.COMPLETED: [Status.LOGIN_REQUIRED, Status.ARMED, Status.STAGING, Status.SUBMITTING, Status.COMPLETED],
            Status.UNKNOWN_AFTER_SUBMIT: [
                Status.LOGIN_REQUIRED,
                Status.ARMED,
                Status.STAGING,
                Status.SUBMITTING,
                Status.UNKNOWN_AFTER_SUBMIT,
            ],
            Status.BLOCKED_DUPLICATE: [Status.LOGIN_REQUIRED, Status.ARMED, Status.BLOCKED_DUPLICATE],
            Status.BLOCKED_PAYMENT: [Status.LOGIN_REQUIRED, Status.ARMED, Status.STAGING, Status.BLOCKED_PAYMENT],
        }
        completed = subprocess.CompletedProcess([], 0, "", "")
        for terminal, states in sequences.items():
            with self.subTest(terminal=terminal.value), tempfile.TemporaryDirectory() as temp:
                paths = RuntimePaths(Path(temp))
                paths.prepare()
                write_config(paths.config, copy.deepcopy(VALID_CONFIG))
                for state in states:
                    transition(paths.heartbeat, state)

                with patch("prickly_imax_helper.cli.start_service", return_value=completed) as start:
                    self.assertEqual(cli_main(["--home", temp, "start"]), 2)

                start.assert_not_called()

    def test_resident_bootstraps_once_then_uses_only_hot_seat_probes_same_day(self):
        calls = []

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
                calls.append(("open_dates", None))
                return ["20991231"]

            def schedules(self, ymd):
                calls.append(("schedule", ymd))
                return [
                    {"movkndDsplNm": "IMAX", "scnsrtTm": "1900", "scnsNo": "18", "scnSseq": "1"},
                    {"movkndDsplNm": "IMAX", "scnsrtTm": "2200", "scnsNo": "18", "scnSseq": "2"},
                ]

            def seats(self, ymd, screen_no, sequence):
                calls.append(("seats", sequence))
                return {"all": ["H15", "H16"], "available": []}

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)

            with patch("prickly_imax_helper.monitor.launch_browser"), patch(
                "prickly_imax_helper.monitor.CgvSession", FakeSession
            ), patch(
                "prickly_imax_helper.monitor._kst_day", return_value=date(2026, 8, 15)
            ):
                self.assertEqual(run(paths, max_cycles=7, allow_checkout=False), 0)

            self.assertEqual(
                calls,
                [
                    ("open_dates", None),
                    ("schedule", "20991231"),
                    ("seats", "1"),
                    ("seats", "2"),
                    ("seats", "1"),
                    ("seats", "2"),
                    ("seats", "1"),
                    ("seats", "2"),
                ],
            )
            state = read_state(paths.heartbeat)
            self.assertEqual(state["last_scan_lane"], "hot")
            self.assertEqual(state["hot_target_count"], 2)
            self.assertLessEqual(state["estimated_hot_revisit_seconds"], 3.0)

    def test_kst_day_changes_at_korean_midnight(self):
        before = datetime(2026, 8, 15, 14, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 8, 15, 15, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(_kst_day(before), date(2026, 8, 15))
        self.assertEqual(_kst_day(after), date(2026, 8, 16))

    def test_discovery_refreshes_open_dates_and_schedules_serially(self):
        calls = []

        class FakeSession:
            def open_dates(self):
                calls.append(("open_dates", None))
                return ["20991230", "20991231"]

            def schedules(self, ymd):
                calls.append(("schedule", ymd))
                return [{"movkndDsplNm": "IMAX", "scnsrtTm": "1900", "scnsNo": "18", "scnSseq": ymd[-2:]}]

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            planner = BalancedScanPlanner(minimum_interval_seconds=1.0)

            count = _refresh_discovery(
                paths,
                FakeSession(),
                planner,
                copy.deepcopy(VALID_CONFIG),
                now=123.0,
            )

        self.assertEqual(
            calls,
            [("open_dates", None), ("schedule", "20991230"), ("schedule", "20991231")],
        )
        self.assertEqual(count, 2)
        self.assertEqual(len(planner.hot_targets), 2)

    def test_kst_date_change_runs_exactly_one_new_discovery_cycle(self):
        calls = []

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
                calls.append(("open_dates", None))
                return ["20991231"]

            def schedules(self, ymd):
                calls.append(("schedule", ymd))
                return [{"movkndDsplNm": "IMAX", "scnsrtTm": "1900", "scnsNo": "18", "scnSseq": "1"}]

            def seats(self, _ymd, _screen_no, sequence):
                calls.append(("seats", sequence))
                return {"all": ["H15", "H16"], "available": []}

        days = [
            date(2026, 8, 15),
            date(2026, 8, 15),
            date(2026, 8, 16),
            date(2026, 8, 16),
            date(2026, 8, 16),
        ]
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)

            with patch("prickly_imax_helper.monitor.launch_browser"), patch(
                "prickly_imax_helper.monitor.CgvSession", FakeSession
            ), patch(
                "prickly_imax_helper.monitor._kst_day", side_effect=days
            ):
                self.assertEqual(run(paths, max_cycles=5, allow_checkout=False), 0)

        self.assertEqual(calls.count(("open_dates", None)), 2)
        self.assertEqual(calls.count(("schedule", "20991231")), 2)
        self.assertEqual(calls.count(("seats", "1")), 3)

    def test_hot_target_is_pruned_when_it_no_longer_meets_time_policy(self):
        seat_calls = []
        cached_show = {
            "ymd": "20991231",
            "movkndDsplNm": "IMAX",
            "scnsrtTm": "1900",
            "scnsNo": "18",
            "scnSseq": "1",
            "time": "19:00",
        }

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
                return ["20991231"]

            def schedules(self, _ymd):
                return [cached_show]

            def seats(self, *_args):
                seat_calls.append(True)
                return {"all": [], "available": []}

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)

            with patch("prickly_imax_helper.monitor.launch_browser"), patch(
                "prickly_imax_helper.monitor.CgvSession", FakeSession
            ), patch(
                "prickly_imax_helper.monitor.eligible_shows",
                side_effect=[[cached_show], []],
            ):
                self.assertEqual(run(paths, max_cycles=3, allow_checkout=False), 0)

            self.assertEqual(seat_calls, [])
            self.assertEqual(read_state(paths.heartbeat)["hot_target_count"], 0)

    def test_empty_seat_map_prunes_target_without_daytime_rediscovery(self):
        calls = []

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
                calls.append(("open_dates", None))
                return ["20991231"]

            def schedules(self, ymd):
                calls.append(("schedule", ymd))
                return [{"movkndDsplNm": "IMAX", "scnsrtTm": "1900", "scnsNo": "18", "scnSseq": "1"}]

            def seats(self, _ymd, _screen_no, sequence):
                calls.append(("seats", sequence))
                return {"all": [], "available": []}

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)

            with patch("prickly_imax_helper.monitor.launch_browser"), patch(
                "prickly_imax_helper.monitor.CgvSession", FakeSession
            ), patch(
                "prickly_imax_helper.monitor._kst_day", return_value=date(2026, 8, 15)
            ), patch(
                "prickly_imax_helper.monitor.time.sleep"
            ):
                self.assertEqual(run(paths, max_cycles=4, allow_checkout=False), 0)

            self.assertEqual(
                calls,
                [
                    ("open_dates", None),
                    ("schedule", "20991231"),
                    ("seats", "1"),
                ],
            )
            state = read_state(paths.heartbeat)
            self.assertEqual(state["last_scan_lane"], "idle")
            self.assertEqual(state["hot_target_count"], 0)

    def test_first_matching_seat_map_stops_scanning_after_one_checkout(self):
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
                return ["20991231"]

            def schedules(self, _ymd):
                return [{"movkndDsplNm": "IMAX", "scnsrtTm": "1900", "scnsNo": "18", "scnSseq": "1"}]

            def seats(self, *_args):
                return {
                    "all": [f"H{number}" for number in range(1, 11)],
                    "available": ["H5", "H6"],
                }

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)

            with patch("prickly_imax_helper.monitor.launch_browser"), patch(
                "prickly_imax_helper.monitor.CgvSession", FakeSession
            ), patch(
                "prickly_imax_helper.monitor._checkout", return_value=Status.COMPLETED.value
            ) as checkout:
                self.assertEqual(run(paths, max_cycles=20, allow_checkout=True), 0)

            checkout.assert_called_once()

    def test_repeated_429_backoff_grows_and_is_capped(self):
        self.assertEqual([rate_limit_backoff_seconds(streak, 300) for streak in range(1, 6)], [300, 600, 1200, 2400, 3600])
        self.assertEqual(rate_limit_backoff_seconds(8, 300), 3600)

    def test_unavailable_duplicate_guard_recovers_before_any_booking_click(self):
        class GuardUnavailableFlow:
            def __init__(self, *_args, **_kwargs):
                pass

            def ensure_no_existing_ticket(self, *_args, **_kwargs):
                raise TicketCheckUnavailable("ticket list ambiguous")

            def open_movie_and_theater(self):
                raise AssertionError("booking page must not open")

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            match = {"date": "2026-08-13", "time": "20:30", "seats": ["D28", "D29"]}
            session = type("Session", (), {"page": object()})()
            with patch("prickly_imax_helper.monitor.CheckoutFlow", GuardUnavailableFlow), patch(
                "prickly_imax_helper.monitor._notify"
            ):
                recorder = CheckoutAttemptRecorder.start(paths.logs, match)
                self.assertEqual(
                    _checkout(paths, copy.deepcopy(VALID_CONFIG), session, match, recorder),
                    Status.RECOVERING.value,
                )
            self.assertEqual(read_state(paths.heartbeat)["status"], Status.RECOVERING.value)

    def test_checkout_records_ordered_stages_and_one_terminal_outcome(self):
        actions = []
        timeline = []

        class SuccessfulFlow:
            def __init__(self, *_args, **_kwargs):
                pass

            def ensure_no_existing_ticket(self, *_args, **_kwargs):
                actions.append("duplicate")

            def open_movie_and_theater(self):
                actions.append("theater")

            def _require_match_date(self, _match):
                actions.append("date")

            def _open_match_showtime(self, _match):
                actions.append("showtime")

            def _select_general_party(self, party):
                actions.append(f"party:{party}")

            def _select_seats(self, _match):
                actions.append("seats")

            def open_payment_and_apply_vouchers(self):
                actions.append("vouchers")

            def prove_ready(self, _match):
                actions.append("zero_balance")

            def submit_once(self):
                actions.append("submission")

            def verify_mobile_ticket(self, _match):
                actions.append("mobile_ticket")
                return type("CheckoutResult", (), {"proof": {"ticket_count": 1}})()

        class RecorderSpy:
            attempt_id = "attempt-a"

            def __init__(self):
                self.stages = []
                self.terminals = []

            @contextlib.contextmanager
            def stage(self, name):
                self.stages.append((name, "started"))
                yield
                self.stages.append((name, "passed"))

            def mark(self, name, outcome="passed"):
                self.stages.append((name, outcome))

            def terminal(self, name, *, error=None):
                self.terminals.append((name, error))
                timeline.append(("terminal", name))

        def notify(_paths, _config, subject, _body, *, attempt_id=None):
            timeline.append(("notify", subject, attempt_id))

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            match = {"date": "2026-08-21", "time": "24:30", "seats": ["G13", "G14"], "pair": "G13-G14"}
            session = type(
                "Session",
                (),
                {
                    "page": object(),
                    "booking_target_from_page": lambda _self: {"company_code": "A420", "site_no": "0013", "movie_no": "30001323"},
                },
            )()
            recorder = RecorderSpy()
            with patch("prickly_imax_helper.monitor.CheckoutFlow", SuccessfulFlow), patch(
                "prickly_imax_helper.monitor._notify", side_effect=notify
            ):
                result = _checkout(paths, copy.deepcopy(VALID_CONFIG), session, match, recorder)

        self.assertEqual(result, Status.COMPLETED.value)
        self.assertEqual(
            actions,
            [
                "duplicate",
                "theater",
                "date",
                "showtime",
                "party:2",
                "seats",
                "vouchers",
                "zero_balance",
                "duplicate",
                "submission",
                "mobile_ticket",
            ],
        )
        passed = [name for name, outcome in recorder.stages if outcome == "passed"]
        self.assertEqual(
            passed,
            [
                "duplicate_guard_before",
                "theater",
                "date",
                "showtime",
                "party",
                "seats",
                "vouchers",
                "zero_balance",
                "duplicate_guard_final",
                "submission_ready",
                "submission",
                "mobile_ticket",
            ],
        )
        self.assertEqual(recorder.terminals, [("completed", None)])
        self.assertEqual(
            timeline,
            [
                ("terminal", "completed"),
                ("notify", "Prickly IMAX 예매 완료", "attempt-a"),
            ],
        )

    def test_checkout_skips_duplicate_guards_only_when_explicitly_disabled(self):
        actions = []

        class SuccessfulFlow:
            def __init__(self, *_args, **_kwargs):
                pass

            def ensure_no_existing_ticket(self, *_args, **_kwargs):
                raise AssertionError("duplicate ticket lookup must be skipped")

            def open_movie_and_theater(self):
                actions.append("theater")

            def _require_match_date(self, _match):
                actions.append("date")

            def _open_match_showtime(self, _match):
                actions.append("showtime")

            def _select_general_party(self, party):
                actions.append(f"party:{party}")

            def _select_seats(self, _match):
                actions.append("seats")

            def open_payment_and_apply_vouchers(self):
                actions.append("vouchers")

            def prove_ready(self, _match):
                actions.append("zero_balance")

            def submit_once(self):
                actions.append("submission")

            def verify_mobile_ticket(self, _match):
                actions.append("mobile_ticket")
                return type("CheckoutResult", (), {"proof": {"ticket_count": 1}})()

        class RecorderSpy:
            attempt_id = "attempt-fast"

            def __init__(self):
                self.stages = []
                self.terminals = []

            @contextlib.contextmanager
            def stage(self, name):
                self.stages.append((name, "started"))
                yield
                self.stages.append((name, "passed"))

            def mark(self, name, outcome="passed"):
                self.stages.append((name, outcome))

            def terminal(self, name, *, error=None):
                self.terminals.append((name, error))

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            match = {"date": "2026-08-21", "time": "24:30", "seats": ["G13", "G14"], "pair": "G13-G14"}
            session = type(
                "Session",
                (),
                {
                    "page": object(),
                    "booking_target_from_page": lambda _self: {
                        "company_code": "A420",
                        "site_no": "0013",
                        "movie_no": "30001323",
                    },
                },
            )()
            recorder = RecorderSpy()
            config = copy.deepcopy(VALID_CONFIG)
            config["prevent_duplicate_booking"] = False
            with patch("prickly_imax_helper.monitor.CheckoutFlow", SuccessfulFlow), patch(
                "prickly_imax_helper.monitor._notify"
            ):
                result = _checkout(paths, config, session, match, recorder)

        self.assertEqual(result, Status.COMPLETED.value)
        self.assertEqual(
            actions,
            [
                "theater",
                "date",
                "showtime",
                "party:2",
                "seats",
                "vouchers",
                "zero_balance",
                "submission",
                "mobile_ticket",
            ],
        )
        passed = [name for name, outcome in recorder.stages if outcome == "passed"]
        self.assertEqual(
            passed,
            [
                "theater",
                "date",
                "showtime",
                "party",
                "seats",
                "vouchers",
                "zero_balance",
                "submission_ready",
                "submission",
                "mobile_ticket",
            ],
        )
        self.assertEqual(recorder.terminals, [("completed", None)])

    def test_terminal_block_and_unknown_notifications_follow_correlated_terminal_outcomes(self):
        cases = (
            (
                "blocked_duplicate",
                DuplicateBlocked("existing ticket"),
                Status.BLOCKED_DUPLICATE.value,
                "Prickly IMAX 예매 중단",
            ),
            (
                "blocked_payment",
                PaymentBlocked("voucher proof failed"),
                Status.BLOCKED_PAYMENT.value,
                "Prickly IMAX 결제 중단",
            ),
            (
                "unknown_after_submit",
                UnknownAfterSubmit("mobile ticket unavailable"),
                Status.UNKNOWN_AFTER_SUBMIT.value,
                "Prickly IMAX 결과 확인 필요",
            ),
        )

        for terminal, failure, expected_status, expected_subject in cases:
            with self.subTest(terminal=terminal):
                timeline = []

                class TerminalFlow:
                    def __init__(self, *_args, **_kwargs):
                        pass

                    def ensure_no_existing_ticket(self, *_args, **_kwargs):
                        if terminal == "blocked_duplicate":
                            raise failure

                    def open_movie_and_theater(self):
                        pass

                    def _require_match_date(self, _match):
                        pass

                    def _open_match_showtime(self, _match):
                        pass

                    def _select_general_party(self, _party):
                        pass

                    def _select_seats(self, _match):
                        pass

                    def open_payment_and_apply_vouchers(self):
                        if terminal == "blocked_payment":
                            raise failure

                    def prove_ready(self, _match):
                        pass

                    def submit_once(self):
                        if terminal == "unknown_after_submit":
                            raise failure

                    def verify_mobile_ticket(self, _match):
                        raise AssertionError("unknown-after-submit must stop before ticket verification")

                class RecorderSpy:
                    attempt_id = "attempt-a"

                    @contextlib.contextmanager
                    def stage(self, _name):
                        yield

                    def mark(self, _name, outcome="passed"):
                        self.outcome = outcome

                    def terminal(self, name, *, error=None):
                        timeline.append(("terminal", name, error))

                def notify(_paths, _config, subject, _body, *, attempt_id=None):
                    timeline.append(("notify", subject, attempt_id))

                with tempfile.TemporaryDirectory() as temp:
                    paths = RuntimePaths(Path(temp))
                    paths.prepare()
                    transition(paths.heartbeat, Status.LOGIN_REQUIRED)
                    transition(paths.heartbeat, Status.ARMED)
                    match = {
                        "date": "2026-08-21",
                        "time": "24:30",
                        "seats": ["G13", "G14"],
                        "pair": "G13-G14",
                    }
                    session = type(
                        "Session",
                        (),
                        {
                            "page": object(),
                            "booking_target_from_page": lambda _self: {
                                "company_code": "A420",
                                "site_no": "0013",
                                "movie_no": "30001323",
                            },
                        },
                    )()
                    with patch("prickly_imax_helper.monitor.CheckoutFlow", TerminalFlow), patch(
                        "prickly_imax_helper.monitor._notify", side_effect=notify
                    ):
                        result = _checkout(paths, copy.deepcopy(VALID_CONFIG), session, match, RecorderSpy())

                self.assertEqual(result, expected_status)
                self.assertEqual(
                    timeline,
                    [
                        ("terminal", terminal, str(failure)),
                        ("notify", expected_subject, "attempt-a"),
                    ],
                )

    def test_recorder_failure_stops_before_next_booking_action(self):
        actions = []

        class Flow:
            def __init__(self, *_args, **_kwargs):
                pass

            def ensure_no_existing_ticket(self, *_args, **_kwargs):
                actions.append("duplicate")

            def open_movie_and_theater(self):
                actions.append("theater")

        class FailingRecorder:
            attempt_id = "attempt-a"

            @contextlib.contextmanager
            def stage(self, name):
                if name == "theater":
                    raise OSError("log unavailable")
                yield

            def terminal(self, *_args, **_kwargs):
                raise AssertionError("a recorder write failure must propagate")

        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            match = {"date": "2026-08-21", "time": "24:30", "seats": ["G13", "G14"], "pair": "G13-G14"}
            session = type("Session", (), {"page": object()})()
            with patch("prickly_imax_helper.monitor.CheckoutFlow", Flow):
                with self.assertRaisesRegex(OSError, "log unavailable"):
                    _checkout(paths, copy.deepcopy(VALID_CONFIG), session, match, FailingRecorder())

        self.assertEqual(actions, ["duplicate"])

    def test_checkout_guard_retry_is_not_a_fast_loop(self):
        self.assertGreaterEqual(CHECKOUT_GUARD_RETRY_SECONDS, 300)

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

    def test_restart_before_submission_records_correlated_interruption_first(self):
        timeline = []
        match = {"date": "2026-08-21", "time": "24:30", "seats": ["G13", "G14"], "pair": "G13-G14"}
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            transition(paths.heartbeat, Status.STAGING, attempt_id="attempt-a", match=match)

            def record_event(_log_dir, event, **fields):
                timeline.append(("event", event, fields))

            def record_heartbeat(_paths, status, detail="", **fields):
                timeline.append(("heartbeat", status.value, fields))

            with patch("prickly_imax_helper.monitor.write_event", side_effect=record_event), patch(
                "prickly_imax_helper.monitor._heartbeat", side_effect=record_heartbeat
            ), patch("prickly_imax_helper.monitor.launch_browser", side_effect=RuntimeError("stop after recovery")):
                with self.assertRaisesRegex(RuntimeError, "stop after recovery"):
                    run(paths)

        self.assertEqual(
            timeline[:2],
            [
                ("event", "checkout_attempt_interrupted", {"attempt_id": "attempt-a", "match": match}),
                ("heartbeat", "recovering", {}),
            ],
        )

    def test_submission_restart_never_records_pre_submit_interruption(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = RuntimePaths(Path(temp))
            paths.prepare()
            write_config(paths.config, copy.deepcopy(VALID_CONFIG))
            transition(paths.heartbeat, Status.LOGIN_REQUIRED)
            transition(paths.heartbeat, Status.ARMED)
            transition(paths.heartbeat, Status.STAGING, attempt_id="attempt-a", match={"pair": "G13-G14"})
            transition(paths.heartbeat, Status.SUBMITTING)
            with patch("prickly_imax_helper.monitor.write_event") as write, patch(
                "prickly_imax_helper.monitor.launch_browser"
            ) as launch, patch("prickly_imax_helper.monitor._notify"):
                self.assertEqual(run(paths), 2)
            launch.assert_not_called()
            self.assertFalse(any(call.args[1] == "checkout_attempt_interrupted" for call in write.call_args_list))

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
            state = read_state(paths.heartbeat)
            self.assertEqual(state["status"], "armed")
            self.assertIsNone(state["match"])

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

    def test_successful_scan_clears_stale_consecutive_error_count(self):
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
            transition(paths.heartbeat, Status.ARMED)
            transition(paths.heartbeat, Status.RECOVERING, errors=116)

            with patch("prickly_imax_helper.monitor.launch_browser"), patch(
                "prickly_imax_helper.monitor.CgvSession", FakeSession
            ):
                self.assertEqual(run(paths, max_cycles=1, allow_checkout=False), 0)

            state = read_state(paths.heartbeat)
            self.assertEqual(state["status"], "armed")
            self.assertEqual(state["errors"], 0)

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
