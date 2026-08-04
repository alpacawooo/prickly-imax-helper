from __future__ import annotations

import importlib.util
import json
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
    def test_default_config_is_valid(self):
        self.assertEqual(policy.validate(CONFIG), {"ok": True, "errors": []})

    def test_center_adjacent_pair_wins(self):
        seats = [f"H{i}" for i in range(1, 31)]
        result = policy.rank_best_block({"all": seats, "available": ["H15", "H16", "H20", "H21"]}, CONFIG)
        self.assertEqual(result["pair"], "H15-H16")

    def test_edges_and_nonadjacent_are_rejected(self):
        seats = [f"H{i}" for i in range(1, 31)]
        self.assertIsNone(policy.rank_best_block({"all": seats, "available": ["H1", "H2", "H15", "H17"]}, CONFIG))

    def test_time_rules(self):
        self.assertFalse(policy.eligible_start(date(2026, 8, 6), "18:59", CONFIG))
        self.assertTrue(policy.eligible_start(date(2026, 8, 6), "19:00", CONFIG))
        self.assertTrue(policy.eligible_start(date(2026, 8, 8), "06:30", CONFIG))
        self.assertTrue(policy.eligible_start(date(2026, 8, 9), "21:59", CONFIG))
        self.assertFalse(policy.eligible_start(date(2026, 8, 9), "22:00", CONFIG))


if __name__ == "__main__":
    unittest.main()
