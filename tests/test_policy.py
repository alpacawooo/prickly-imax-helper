from __future__ import annotations

import importlib.util
import copy
import json
import os
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/prickly-imax-helper/skills/prickly-imax-booking/scripts/policy.py"
CONFIG_PATH = ROOT / "plugins/prickly-imax-helper/assets/default-odyssey.json"
SPEC = importlib.util.spec_from_file_location("prickly_policy", SCRIPT)
policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(policy)
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


class PolicyTests(unittest.TestCase):
    def test_korea_timezone_loads_without_system_timezone_database(self):
        environment = os.environ.copy()
        environment["PYTHONTZPATH"] = ""
        completed = subprocess.run(
            [sys.executable, "-c", "from prickly_imax_helper.policy import KOREA_TIMEZONE; print(KOREA_TIMEZONE.key)"],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "Asia/Seoul")

    def test_default_config_is_valid(self):
        self.assertEqual(policy.validate(CONFIG), {"ok": True, "errors": []})

    def test_plugin_accepts_user_selected_rows_times_and_party_size(self):
        custom = copy.deepcopy(CONFIG)
        custom["movie"] = "다른 영화"
        custom["theater"] = "다른CGV"
        custom["format"] = "IMAX 2D"
        custom["rows"] = ["F", "G", "H"]
        custom["party_size"] = 3
        custom["payment"]["voucher_count"] = 3
        custom["time_rules"]["weekday"]["at_or_after"] = "18:00"
        self.assertEqual(policy.validate(custom), {"ok": True, "errors": []})

    def test_plugin_minimum_lead_boundary_and_legacy_default(self):
        for value in (180, 1440):
            with self.subTest(valid=value):
                config = copy.deepcopy(CONFIG)
                config["minimum_lead_minutes"] = value
                self.assertEqual(policy.validate(config), {"ok": True, "errors": []})

        legacy = copy.deepcopy(CONFIG)
        legacy.pop("minimum_lead_minutes", None)
        self.assertEqual(policy.validate(legacy), {"ok": True, "errors": []})

        for value in (179, True, 1441):
            with self.subTest(invalid=value):
                config = copy.deepcopy(CONFIG)
                config["minimum_lead_minutes"] = value
                result = policy.validate(config)
                self.assertFalse(result["ok"])
                self.assertTrue(any("minimum_lead_minutes" in error for error in result["errors"]))

    def test_center_adjacent_pair_wins(self):
        seats = [f"H{i}" for i in range(1, 31)]
        result = policy.rank_best_block({"all": seats, "available": ["H15", "H16", "H20", "H21"]}, CONFIG)
        self.assertEqual(result["pair"], "H15-H16")

    def test_edges_and_nonadjacent_are_rejected(self):
        seats = [f"H{i}" for i in range(1, 31)]
        self.assertIsNone(policy.rank_best_block({"all": seats, "available": ["H1", "H2", "H15", "H17"]}, CONFIG))

    def test_row_order_preference_can_override_center_priority(self):
        config = copy.deepcopy(CONFIG)
        config["preference"] = "row_order_then_left"
        config["rows"] = ["G", "H"]
        seats = [f"{row}{i}" for row in ("G", "H") for i in range(1, 31)]
        result = policy.rank_best_block({"all": seats, "available": ["G7", "G8", "H15", "H16"]}, config)
        self.assertEqual(result["pair"], "G7-G8")

    def test_time_rules(self):
        self.assertFalse(policy.eligible_start(date(2026, 8, 6), "18:59", CONFIG))
        self.assertTrue(policy.eligible_start(date(2026, 8, 6), "19:00", CONFIG))
        self.assertTrue(policy.eligible_start(date(2026, 8, 8), "06:30", CONFIG))
        self.assertTrue(policy.eligible_start(date(2026, 8, 9), "21:59", CONFIG))
        self.assertFalse(policy.eligible_start(date(2026, 8, 9), "22:00", CONFIG))


if __name__ == "__main__":
    unittest.main()
