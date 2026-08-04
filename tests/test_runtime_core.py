from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from prickly_imax_helper.config import load_config, validate_config, write_config
from prickly_imax_helper.redaction import redact
from prickly_imax_helper.state import InvalidTransition, Status, read_state, transition


VALID_CONFIG = {
    "movie": "오디세이",
    "theater": "용산아이파크몰",
    "format": "IMAX",
    "party_size": 2,
    "dates": "all_open",
    "time_rules": {
        "weekday": {"at_or_after": "19:00"},
        "saturday": {"any_time": True},
        "sunday": {"before": "22:00"},
    },
    "rows": list("DEFGHIJ"),
    "edge_exclusion": 0.2,
    "prevent_duplicate_booking": True,
    "allow_cancel_existing": False,
    "allow_change_existing": False,
    "payment": {
        "method": "registered_imax_voucher",
        "voucher_count": 2,
        "maximum_remaining_balance": 0,
    },
    "authorization": {
        "automatic_query": True,
        "automatic_seat_selection": True,
        "automatic_submission": True,
    },
    "request_policy": {"minimum_interval_seconds": 1.0},
    "notification": {"email": "tester@example.com"},
    "consent": {
        "automatic_submission": True,
        "one_active_device_per_public_ip": True,
        "accepted_at": "2026-08-05T03:00:00+09:00",
    },
}


class ConfigTests(unittest.TestCase):
    def test_valid_config_round_trip_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "private" / "config.json"
            write_config(target, VALID_CONFIG)
            self.assertEqual(load_config(target), VALID_CONFIG)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_rejects_missing_consent_and_faster_rate(self):
        value = copy.deepcopy(VALID_CONFIG)
        value["consent"] = {}
        value["request_policy"]["minimum_interval_seconds"] = 0.5
        errors = validate_config(value)
        self.assertTrue(any("at least 1.0" in item for item in errors))
        self.assertTrue(any("consent" in item for item in errors))

    def test_rejects_positive_balance_and_wrong_voucher_count(self):
        value = copy.deepcopy(VALID_CONFIG)
        value["payment"]["maximum_remaining_balance"] = 1
        value["payment"]["voucher_count"] = 1
        errors = validate_config(value)
        self.assertTrue(any("maximum_remaining_balance" in item for item in errors))
        self.assertTrue(any("voucher_count" in item for item in errors))


class StateTests(unittest.TestCase):
    def test_happy_path_and_terminal_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "checkout.json"
            transition(path, Status.LOGIN_REQUIRED)
            transition(path, Status.ARMED)
            transition(path, Status.STAGING)
            transition(path, Status.SUBMITTING)
            transition(path, Status.UNKNOWN_AFTER_SUBMIT)
            self.assertEqual(read_state(path)["status"], "unknown_after_submit")
            with self.assertRaises(InvalidTransition):
                transition(path, Status.ARMED)

    def test_cannot_skip_directly_to_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(InvalidTransition):
                transition(Path(temp) / "checkout.json", Status.COMPLETED)


class RedactionTests(unittest.TestCase):
    def test_secrets_email_and_long_numbers_are_redacted(self):
        value = redact(
            {
                "cookie": "session-secret",
                "message": "mail person@example.com customer 123456789012",
                "nested": {"accessToken": "abc"},
            }
        )
        self.assertEqual(value["cookie"], "[REDACTED]")
        self.assertNotIn("person@example.com", json.dumps(value))
        self.assertNotIn("123456789012", json.dumps(value))
        self.assertEqual(value["nested"]["accessToken"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
