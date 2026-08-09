from __future__ import annotations

import copy
import contextlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prickly_imax_helper.checkout import TicketCheckUnavailable
from prickly_imax_helper.checkout_attempt import CheckoutAttemptRecorder
from prickly_imax_helper.config import write_config
from prickly_imax_helper.cli import main as cli_main
from prickly_imax_helper.monitor import CHECKOUT_GUARD_RETRY_SECONDS, OPEN_DATE_REFRESH_SECONDS, _checkout, rate_limit_backoff_seconds, run
from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.state import Status, read_state, transition
from test_runtime_core import VALID_CONFIG


class MonitorRestartSafetyTests(unittest.TestCase):
    def test_new_booking_dates_are_refreshed_within_thirty_seconds(self):
        self.assertLessEqual(OPEN_DATE_REFRESH_SECONDS, 30.0)

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
                "prickly_imax_helper.monitor._notify"
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
