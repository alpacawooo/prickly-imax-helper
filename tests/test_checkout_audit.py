from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "checkout-audit-legacy-14.jsonl"
SPEC = importlib.util.spec_from_file_location("checkout_audit", ROOT / "scripts" / "checkout_audit.py")
checkout_audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(checkout_audit)


def valid_attempt() -> list[dict]:
    attempt_id = "attempt-a"
    match = {"date": "2026-08-21", "time": "24:30", "pair": "G13-G14", "seats": ["G13", "G14"]}
    events = [{"at": "2026-08-09T10:00:00+09:00", "event": "seat_match", "attempt_id": attempt_id, "match": match}]
    for index, stage in enumerate(checkout_audit.STAGE_ORDER):
        events.append(
            {
                "at": f"2026-08-09T10:00:{index + 1:02d}+09:00",
                "event": "checkout_stage",
                "attempt_id": attempt_id,
                "stage": stage,
                "outcome": "started" if stage == "submission" else "passed",
            }
        )
    events.append(
        {"at": "2026-08-09T10:01:00+09:00", "event": "completed", "attempt_id": attempt_id, "match": match}
    )
    return events


class CheckoutAuditTests(unittest.TestCase):
    def test_legacy_fourteen_match_report_is_10_2_1_1(self):
        report = checkout_audit.build_report(checkout_audit.load_events(FIXTURE))
        self.assertEqual(report["attempts_total"], 14)
        self.assertEqual(
            report["legacy_classification"],
            {"theater_picker": 10, "today_label": 2, "general_party": 1, "legacy_unknown": 1},
        )
        self.assertEqual(report["instrumented_attempts"], 0)

    def test_valid_instrumented_attempt_passes(self):
        report = checkout_audit.build_report(valid_attempt())
        self.assertEqual(checkout_audit.verify_report(report), [])

    def test_missing_terminal_fails(self):
        events = valid_attempt()[:-1]
        self.assertIn("attempt attempt-a has no terminal outcome", checkout_audit.verify_report(checkout_audit.build_report(events)))

    def test_two_terminals_fail(self):
        events = valid_attempt()
        events.append({"at": "2026-08-09T10:01:01+09:00", "event": "seat_vanished", "attempt_id": "attempt-a"})
        errors = checkout_audit.verify_report(checkout_audit.build_report(events))
        self.assertIn("attempt attempt-a has 2 terminal outcomes", errors)

    def test_backward_stage_order_fails(self):
        events = valid_attempt()
        stage_events = [event for event in events if event.get("event") == "checkout_stage"]
        stage_events[3]["stage"], stage_events[4]["stage"] = stage_events[4]["stage"], stage_events[3]["stage"]
        errors = checkout_audit.verify_report(checkout_audit.build_report(events))
        self.assertTrue(any("stage order moved backward" in error for error in errors))

    def test_duplicate_submission_start_fails(self):
        events = valid_attempt()
        duplicate = next(event for event in events if event.get("stage") == "submission")
        events.append(copy.deepcopy(duplicate))
        errors = checkout_audit.verify_report(checkout_audit.build_report(events))
        self.assertIn("attempt attempt-a has 2 submission starts", errors)

    def test_sensitive_key_fails(self):
        events = valid_attempt()
        events[0]["cookie"] = "redacted"
        errors = checkout_audit.verify_report(checkout_audit.build_report(events))
        self.assertTrue(any("prohibited key cookie" in error for error in errors))

    def test_sensitive_values_fail(self):
        events = valid_attempt()
        events[0]["error"] = "person@example.com"
        events[1]["detail"] = "customer 123456789012"
        errors = checkout_audit.verify_report(checkout_audit.build_report(events))
        self.assertTrue(any("email-like value" in error for error in errors))
        self.assertTrue(any("customer-like number" in error for error in errors))

    def test_legacy_unknown_is_disclosed_but_not_future_failure(self):
        report = checkout_audit.build_report(checkout_audit.load_events(FIXTURE))
        self.assertEqual(checkout_audit.verify_report(report), [])
        self.assertEqual(report["legacy_classification"]["legacy_unknown"], 1)


if __name__ == "__main__":
    unittest.main()
