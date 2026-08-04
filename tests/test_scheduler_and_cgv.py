from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prickly_imax_helper.cgv import CgvSession, LoginRequired, RateLimited
from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.presets import odyssey
from prickly_imax_helper.scheduler import FairScanState, changed_seat_targets, eligible_shows, match_for


class SchedulerTests(unittest.TestCase):
    def test_dates_rotate_fairly_and_refresh_dynamically(self):
        state = FairScanState()
        state.replace_dates(["20260805", "20260806", "20260807"])
        self.assertEqual([state.next_date() for _ in range(4)], ["20260805", "20260806", "20260807", "20260805"])
        state.replace_dates(["20260806", "20260807", "20260808"])
        self.assertIn(state.next_date(), {"20260806", "20260807", "20260808"})

    def test_only_changed_counts_trigger_seat_map(self):
        state = FairScanState()
        shows = [{"ymd": "20260808", "scnsNo": "018", "scnSseq": "1", "frSeatCnt": 2}]
        self.assertEqual(len(changed_seat_targets(state, shows)), 1)
        self.assertEqual(changed_seat_targets(state, shows), [])
        shows[0]["frSeatCnt"] = 3
        self.assertEqual(len(changed_seat_targets(state, shows)), 1)

    def test_schedule_and_pair_policy_are_preserved(self):
        config = odyssey()
        schedules = [
            {"movkndDsplNm": "IMAX 2D", "scnsrtTm": "0630", "scnsNo": "018", "scnSseq": "1", "frSeatCnt": 2},
            {"movkndDsplNm": "IMAX 2D", "scnsrtTm": "2300", "scnsNo": "018", "scnSseq": "2", "frSeatCnt": 2},
        ]
        saturday = eligible_shows("20260808", schedules, config)
        self.assertEqual([show["time"] for show in saturday], ["06:30", "23:00"])
        sunday = eligible_shows("20260809", schedules, config)
        self.assertEqual([show["time"] for show in sunday], ["06:30"])
        seats = [f"H{i}" for i in range(1, 31)]
        result = match_for(saturday[0], {"all": seats, "available": ["H15", "H16"]}, config)
        self.assertEqual(result["pair"], "H15-H16")


class FakeBudget:
    def __init__(self) -> None:
        self.acquired = 0
        self.deferred: list[float] = []

    def acquire(self) -> None:
        self.acquired += 1

    def defer(self, seconds: float) -> None:
        self.deferred.append(seconds)


class FakePage:
    def __init__(self, value: dict) -> None:
        self.value = value

    def evaluate(self, script: str, path: str) -> dict:
        return self.value


class CgvApiTests(unittest.TestCase):
    def test_429_applies_shared_cooldown(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            session.budget = FakeBudget()
            session.page = FakePage({"status": 429, "retryAfter": "900", "text": "rate limited"})
            with self.assertRaises(RateLimited):
                session.api_get("/test")
            self.assertEqual(session.budget.acquired, 1)
            self.assertEqual(session.budget.deferred, [900.0])

    def test_success_requires_cgv_status_code_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            session.budget = FakeBudget()
            session.page = FakePage({"status": 200, "retryAfter": None, "text": json.dumps({"statusCode": 0, "data": [1]})})
            self.assertEqual(session.api_get("/test"), [1])
            self.assertEqual(session.budget.acquired, 1)

    def test_403_is_reported_as_login_required(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            session.budget = FakeBudget()
            session.page = FakePage({"status": 403, "retryAfter": None, "text": "forbidden"})
            with self.assertRaises(LoginRequired):
                session.api_get("/test")


if __name__ == "__main__":
    unittest.main()
