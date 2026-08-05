from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pilot_audit", ROOT / "scripts/pilot_audit.py")
pilot_audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pilot_audit)


class PilotAuditTests(unittest.TestCase):
    def completed(self, pilot_id: str, provider: str):
        value = pilot_audit.template(pilot_id)
        value.update(
            {
                "os_version": "test-version",
                "standard_non_admin_user": True,
                "recipient_provider": provider,
                "independent_public_ip_confirmed": True,
                "no_other_helper_on_public_ip_confirmed": True,
                "credentials_and_payment_data_stayed_local": True,
                "release_archive_sha256": "a" * 64,
                "redacted_diagnose_sha256": "b" * 64,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "steps": {step: True for step in pilot_audit.REQUIRED_STEPS},
            }
        )
        return value

    def test_three_cross_platform_private_records_pass(self):
        providers = {"A": "gmail", "B": "naver", "C": "icloud"}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for pilot_id in pilot_audit.PILOT_IDS:
                pilot_audit.write_private_json(directory / f"pilot-{pilot_id}.json", self.completed(pilot_id, providers[pilot_id]))
            self.assertTrue(pilot_audit.verify(directory)["ok"])

    def test_incomplete_windows_or_sensitive_record_fails(self):
        value = self.completed("C", "gmail")
        value["standard_non_admin_user"] = False
        value["steps"]["test_email_received"] = False
        value["note"] = "pilot@example.com /Users/pilot"
        errors = pilot_audit.validate_record(value, "C")
        self.assertTrue(any("standard non-admin" in error for error in errors))
        self.assertTrue(any("incomplete steps" in error for error in errors))
        self.assertTrue(any("email address" in error for error in errors))
        self.assertTrue(any("absolute user path" in error for error in errors))
        wrong_family = self.completed("C", "gmail")
        wrong_family["os_family"] = "macos"
        self.assertTrue(any("pilot C must use windows" in error for error in pilot_audit.validate_record(wrong_family, "C")))

    def test_missing_record_and_duplicate_providers_fail_cohort(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for pilot_id in ("A", "C"):
                pilot_audit.write_private_json(directory / f"pilot-{pilot_id}.json", self.completed(pilot_id, "gmail"))
            result = pilot_audit.verify(directory)
            self.assertFalse(result["ok"])
            self.assertIn("B", result["failures"])
            self.assertIn("cohort", result["failures"])


if __name__ == "__main__":
    unittest.main()
