from __future__ import annotations

import copy
import json
import os
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
    "minimum_lead_minutes": 180,
    "party_size": 2,
    "dates": "all_open",
    "time_rules": {
        "weekday": {"at_or_after": "19:00"},
        "saturday": {"any_time": True},
        "sunday": {"before": "22:00"},
    },
    "rows": list("DEFGHIJ"),
    "edge_exclusion": 0.2,
    "preference": "closest_to_center",
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
    "request_policy": {"minimum_interval_seconds": 1.0, "rate_limit_cooldown_seconds": 300},
    "notification": {"email": "tester@example.com", "recipient_provider": "gmail", "method": "apple_mail"},
    "consent": {
        "automatic_submission": True,
        "one_active_device_per_public_ip": True,
        "accepted_at": "2026-08-05T03:00:00+09:00",
        "scope": "matching-seat-once-voucher-only-zero-balance",
    },
}


class ConfigTests(unittest.TestCase):
    def test_legacy_config_without_minimum_lead_remains_valid(self):
        legacy = copy.deepcopy(VALID_CONFIG)
        legacy.pop("minimum_lead_minutes", None)
        self.assertEqual(validate_config(legacy), [])

    def test_minimum_lead_accepts_180_to_1440_only(self):
        for value in (180, 181, 1440):
            with self.subTest(valid=value):
                config = copy.deepcopy(VALID_CONFIG)
                config["minimum_lead_minutes"] = value
                self.assertEqual(validate_config(config), [])
        for value in (179, 1441, True, 180.5, "180"):
            with self.subTest(invalid=value):
                config = copy.deepcopy(VALID_CONFIG)
                config["minimum_lead_minutes"] = value
                self.assertTrue(any("minimum_lead_minutes" in error for error in validate_config(config)))

    def test_valid_config_round_trip_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "private" / "config.json"
            write_config(target, VALID_CONFIG)
            self.assertEqual(load_config(target), VALID_CONFIG)
            if os.name != "nt":
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

    def test_custom_booking_policy_is_valid_with_resolved_target(self):
        value = copy.deepcopy(VALID_CONFIG)
        value["movie"] = "다른 영화"
        value["theater"] = "다른CGV"
        value["format"] = "IMAX 2D"
        value["target"] = {"company_code": "A420", "site_no": "0099", "movie_no": "movie123"}
        value["party_size"] = 3
        value["payment"]["voucher_count"] = 3
        value["rows"] = ["F", "G", "H"]
        value["edge_exclusion"] = 0.1
        value["preference"] = "row_order_then_left"
        value["time_rules"]["weekday"]["at_or_after"] = "18:00"
        self.assertEqual(validate_config(value), [])

    def test_custom_target_and_time_bounds_are_validated(self):
        value = copy.deepcopy(VALID_CONFIG)
        value["movie"] = "다른 영화"
        self.assertTrue(any("target identifiers" in item for item in validate_config(value)))
        value["target"] = {"company_code": "A420", "site_no": "bad space", "movie_no": "123"}
        self.assertTrue(any("target.site_no" in item for item in validate_config(value)))
        value["target"]["site_no"] = "0099"
        value["time_rules"]["weekday"] = {"at_or_after": "23:00", "before": "19:00"}
        self.assertTrue(any("start must be earlier" in item for item in validate_config(value)))

    def test_rejects_short_cooldown_or_unscoped_consent(self):
        value = copy.deepcopy(VALID_CONFIG)
        value["request_policy"]["rate_limit_cooldown_seconds"] = 30
        value["consent"]["scope"] = "anything"
        value["consent"]["accepted_at"] = "not-a-date"
        errors = validate_config(value)
        self.assertTrue(any("at least 300" in item for item in errors))
        self.assertTrue(any("consent.scope" in item for item in errors))
        self.assertTrue(any("ISO timestamp" in item for item in errors))

    def test_recipient_provider_is_user_selectable_and_legacy_config_remains_valid(self):
        for provider in ("gmail", "naver", "icloud", "other"):
            value = copy.deepcopy(VALID_CONFIG)
            value["notification"]["recipient_provider"] = provider
            self.assertEqual(validate_config(value), [])
        legacy = copy.deepcopy(VALID_CONFIG)
        legacy["notification"].pop("recipient_provider")
        self.assertEqual(validate_config(legacy), [])
        invalid = copy.deepcopy(VALID_CONFIG)
        invalid["notification"]["recipient_provider"] = "unsupported"
        self.assertTrue(any("recipient_provider" in item for item in validate_config(invalid)))


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

    def test_fatal_configuration_state_can_return_to_login_required(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "heartbeat.json"
            transition(path, Status.FATAL)
            transition(path, Status.LOGIN_REQUIRED)
            self.assertEqual(read_state(path)["status"], "login_required")

    def test_pre_submit_blocks_can_return_to_login_required_after_review(self):
        for blocked in (Status.BLOCKED_DUPLICATE, Status.BLOCKED_PAYMENT):
            with self.subTest(blocked=blocked.value), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "heartbeat.json"
                transition(path, Status.LOGIN_REQUIRED)
                transition(path, Status.ARMED)
                transition(path, Status.STAGING)
                transition(path, blocked)
                transition(path, Status.LOGIN_REQUIRED)
                self.assertEqual(read_state(path)["status"], Status.LOGIN_REQUIRED.value)


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
