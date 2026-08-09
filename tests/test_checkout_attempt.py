from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prickly_imax_helper.checkout_attempt import CheckoutAttemptRecorder


MATCH = {"date": "2026-08-21", "time": "24:30", "pair": "G13-G14", "seats": ["G13", "G14"]}


def read_events(log_dir: Path) -> list[dict]:
    events = []
    for source in sorted(log_dir.glob("*.jsonl")):
        events.extend(json.loads(line) for line in source.read_text(encoding="utf-8").splitlines())
    return events


class CheckoutAttemptRecorderTests(unittest.TestCase):
    def test_records_correlated_started_passed_and_terminal_events(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "prickly_imax_helper.checkout_attempt.secrets.token_hex", return_value="attempt-a"
        ):
            log_dir = Path(temp)
            recorder = CheckoutAttemptRecorder.start(log_dir, MATCH)
            with recorder.stage("theater"):
                pass
            recorder.terminal("checkout_pre_submit_error", error="safe bounded error")

            events = read_events(log_dir)

        self.assertEqual(recorder.attempt_id, "attempt-a")
        self.assertEqual([event["event"] for event in events], ["seat_match", "checkout_stage", "checkout_stage", "checkout_pre_submit_error"])
        self.assertEqual(events[0]["attempt_id"], "attempt-a")
        self.assertEqual(events[0]["match"], MATCH)
        self.assertEqual(events[1]["stage"], "theater")
        self.assertEqual(events[1]["outcome"], "started")
        self.assertEqual(events[2]["stage"], "theater")
        self.assertEqual(events[2]["outcome"], "passed")
        self.assertIsInstance(events[2]["elapsed_ms"], int)
        self.assertGreaterEqual(events[2]["elapsed_ms"], 0)
        self.assertEqual(events[3]["error"], "safe bounded error")

    def test_failed_stage_is_recorded_and_exception_is_reraised(self):
        with tempfile.TemporaryDirectory() as temp:
            log_dir = Path(temp)
            recorder = CheckoutAttemptRecorder.start(log_dir, MATCH)
            with self.assertRaisesRegex(ValueError, "boom"):
                with recorder.stage("party"):
                    raise ValueError("boom")
            events = read_events(log_dir)

        self.assertEqual(events[-1]["event"], "checkout_stage")
        self.assertEqual(events[-1]["stage"], "party")
        self.assertEqual(events[-1]["outcome"], "failed")
        self.assertEqual(events[-1]["error_type"], "ValueError")
        self.assertEqual(events[-1]["error"], "boom")

    def test_unknown_stage_is_rejected_before_event_write(self):
        with tempfile.TemporaryDirectory() as temp:
            log_dir = Path(temp)
            recorder = CheckoutAttemptRecorder.start(log_dir, MATCH)
            before = read_events(log_dir)
            with self.assertRaisesRegex(ValueError, "unknown checkout stage"):
                recorder.mark("made_up")
            after = read_events(log_dir)

        self.assertEqual(after, before)

    def test_second_terminal_outcome_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            log_dir = Path(temp)
            recorder = CheckoutAttemptRecorder.start(log_dir, MATCH)
            recorder.terminal("seat_vanished", error="gone")
            with self.assertRaisesRegex(RuntimeError, "terminal outcome already recorded"):
                recorder.terminal("checkout_pre_submit_error", error="again")
            events = read_events(log_dir)

        terminals = [event for event in events if event["event"] in {"seat_vanished", "checkout_pre_submit_error"}]
        self.assertEqual(len(terminals), 1)


if __name__ == "__main__":
    unittest.main()
