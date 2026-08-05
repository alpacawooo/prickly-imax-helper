from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from prickly_imax_helper.request_budget import RequestBudget


class FakeTime:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class RequestBudgetTests(unittest.TestCase):
    def test_rejects_faster_than_approved_rate(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                RequestBudget(temp, minimum_interval_seconds=0.99)

    def test_two_instances_share_one_request_per_second(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = FakeTime()
            first = RequestBudget(temp, clock=fake.time, sleeper=fake.sleep)
            second = RequestBudget(temp, clock=fake.time, sleeper=fake.sleep)
            self.assertEqual(first.acquire(), 0.0)
            self.assertEqual(second.acquire(), 1.0)
            self.assertEqual(fake.sleeps, [1.0])

    def test_429_cooldown_blocks_all_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = FakeTime()
            first = RequestBudget(temp, clock=fake.time, sleeper=fake.sleep)
            second = RequestBudget(temp, clock=fake.time, sleeper=fake.sleep)
            first.acquire()
            first.defer(60.0)
            self.assertEqual(second.acquire(), 60.0)

    def test_state_is_private_and_persistent(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = FakeTime()
            budget = RequestBudget(temp, clock=fake.time, sleeper=fake.sleep)
            budget.acquire()
            state_path = Path(temp) / "state" / "request-budget.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["next_allowed_at"], 1_001.0)
            if os.name != "nt":
                self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(state_path.parent.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
