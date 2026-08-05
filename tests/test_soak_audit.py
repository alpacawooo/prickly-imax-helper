from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("soak_audit", ROOT / "scripts/soak_audit.py")
soak_audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(soak_audit)


class SoakAuditTests(unittest.TestCase):
    def healthy(self):
        return {
            "started_at": "2026-08-04T00:00:00+00:00",
            "captured_at": "2026-08-05T00:00:01+00:00",
            "status": "armed",
            "match": None,
            "heartbeat_age_seconds": 5,
            "processes": {
                "monitor": {"count": 1, "rss_kib": 40_000},
                "driver": {"count": 1, "rss_kib": 90_000},
                "browser": {"count": 5, "rss_kib": 300_000},
            },
        }

    def test_healthy_24_hour_snapshot_passes(self):
        baseline = self.healthy()
        current = self.healthy()
        self.assertEqual(soak_audit.evaluate(baseline, current, {}), [])

    def test_rate_limit_duplicate_monitor_and_stale_heartbeat_fail(self):
        baseline = self.healthy()
        current = self.healthy()
        current["status"] = "rate_limited"
        current["heartbeat_age_seconds"] = 121
        current["processes"]["monitor"]["count"] = 2
        errors = soak_audit.evaluate(baseline, current, {"rate_limited": 1})
        self.assertTrue(any("status" in error for error in errors))
        self.assertTrue(any("heartbeat" in error for error in errors))
        self.assertTrue(any("exactly one" in error for error in errors))
        self.assertTrue(any("rate_limited" in error for error in errors))

    def test_checkout_guard_login_loss_stale_match_and_conflicting_browser_fail(self):
        baseline = self.healthy()
        current = self.healthy()
        current["match"] = {"pair": "D28-D29"}
        current["processes"]["conflicting_automation"] = {"count": 1, "rss_kib": 100_000}
        errors = soak_audit.evaluate(
            baseline,
            current,
            {"checkout_guard_retry_deferred": 1, "checkout_pre_submit_error": 1, "login_required": 1},
        )
        self.assertTrue(any("stale seat match" in error for error in errors))
        self.assertTrue(any("Hermes" in error for error in errors))
        self.assertTrue(any("checkout_guard_retry_deferred" in error for error in errors))
        self.assertTrue(any("checkout_pre_submit_error" in error for error in errors))
        self.assertTrue(any("login_required" in error for error in errors))

    def test_large_memory_growth_fails_but_small_noise_passes(self):
        baseline = self.healthy()
        current = self.healthy()
        current["processes"]["browser"]["rss_kib"] = 500_000
        errors = soak_audit.evaluate(baseline, current, {})
        self.assertTrue(any("browser RSS grew" in error for error in errors))
        current["processes"]["browser"]["rss_kib"] = 340_000
        self.assertEqual(soak_audit.evaluate(baseline, current, {}), [])

    def test_short_duration_fails(self):
        baseline = self.healthy()
        current = self.healthy()
        current["captured_at"] = "2026-08-04T01:00:00+00:00"
        errors = soak_audit.evaluate(baseline, current, {})
        self.assertTrue(any("duration" in error for error in errors))

    def test_playwright_driver_is_not_counted_as_monitor(self):
        home = Path("/tmp/prickly-imax-helper")
        output = "\n".join(
            (
                f"100 40000 {home}/venv/bin/prickly-imax --home {home} run",
                f"101 90000 {home}/venv/site-packages/playwright/driver/node run-driver",
                "102 100000 /Applications/Google Chrome --user-data-dir=/Users/pilot/.hermes/browser-profiles/cgv",
            )
        )
        with patch.object(soak_audit.subprocess, "run", return_value=SimpleNamespace(stdout=output)):
            with patch.object(soak_audit.os, "getpid", return_value=999):
                processes = soak_audit.process_memory(home)
        self.assertEqual(processes["monitor"]["count"], 1)
        self.assertEqual(processes["driver"]["count"], 1)
        self.assertEqual(processes["conflicting_automation"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
