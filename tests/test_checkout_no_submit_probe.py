from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "scripts/cgv_checkout_no_submit_probe.py"
SPEC = importlib.util.spec_from_file_location("cgv_checkout_no_submit_probe", PROBE_PATH)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


class CheckoutNoSubmitProbeTests(unittest.TestCase):
    def test_probe_stops_after_voucher_stage_without_any_submission_call(self):
        calls = []

        class Flow:
            def ensure_no_existing_ticket(self, match, *, separate_tab=False):
                calls.append(("duplicate", match, separate_tab))

            def open_movie_and_theater(self):
                calls.append(("theater",))

            def _require_match_date(self, match):
                calls.append(("date", match))

            def _open_match_showtime(self, match):
                calls.append(("showtime", match))

            def _select_general_party(self, party):
                calls.append(("party", party))

            def _select_seats(self, match):
                calls.append(("seats", match))

            def open_payment_and_apply_vouchers(self):
                calls.append(("vouchers",))

            def submit_once(self):
                self.fail("submission must be structurally unreachable")

            def prove_and_submit_once(self, _match):
                self.fail("combined submission must be structurally unreachable")

        match = {"date": "2026-08-21", "time": "21:00", "seats": ["H15", "H16"]}
        result = probe.execute_no_submit_probe(Flow(), match, party_size=2)

        self.assertEqual([entry[0] for entry in calls], ["duplicate", "theater", "date", "showtime", "party", "seats", "vouchers"])
        self.assertEqual(result, {"status": "stopped_before_submit", "last_stage": "vouchers"})

    def test_probe_source_has_no_call_to_submission_or_post_submission_methods(self):
        tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"))
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            {"submit_once", "prove_ready", "prove_and_submit_once", "verify_mobile_ticket"}.isdisjoint(called_attributes)
        )

    def test_live_probe_rejects_default_customer_home(self):
        with self.assertRaisesRegex(probe.ProbeSafetyError, "separate QA home"):
            probe.require_isolated_home(probe.RuntimePaths.default().root)
        with tempfile.TemporaryDirectory() as temp:
            isolated = Path(temp) / "qa-home"
            isolated.mkdir()
            (isolated / probe.QA_SENTINEL_NAME).write_text(probe.QA_SENTINEL_VALUE, encoding="utf-8")
            self.assertEqual(probe.require_isolated_home(isolated), isolated.resolve())

    def test_live_probe_requires_qa_sentinel_and_rejects_service_marked_home(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "qa-home"
            home.mkdir()
            with self.assertRaisesRegex(probe.ProbeSafetyError, "QA sentinel"):
                probe.require_isolated_home(home)
            (home / probe.QA_SENTINEL_NAME).write_text(probe.QA_SENTINEL_VALUE, encoding="utf-8")
            (home / "state").mkdir()
            (home / "state/heartbeat.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(probe.ProbeSafetyError, "service state"):
                probe.require_isolated_home(home)

    def test_live_flow_guards_every_submission_and_post_submission_method(self):
        flow = object.__new__(probe.NoSubmitCheckoutFlow)
        for name, args in (
            ("prove_ready", ({},)),
            ("submit_once", ()),
            ("prove_and_submit_once", ({},)),
            ("verify_mobile_ticket", ({},)),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(probe.ProbeSafetyError, "forbidden"):
                getattr(flow, name)(*args)

    def test_customer_release_archives_exclude_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            authorization = root / "authorization.json"
            authorization.write_text(
                json.dumps(
                    {
                        "approved_at": "2026-08-05",
                        "scope": [
                            "automated_availability_query",
                            "automated_seat_selection",
                            "voucher_submission",
                            "private_beta_distribution",
                        ],
                        "request_limit_scope": "public_ip",
                        "max_requests_per_ip_per_second": 1.0,
                        "authorization_reference": "QA-PROBE-EXCLUSION-TEST",
                    }
                ),
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/build_release.py"),
                    "--version",
                    "0.2.4",
                    "--authorization",
                    str(authorization),
                    "--output",
                    str(root / "dist"),
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            result = json.loads(process.stdout)
            with tarfile.open(result["archive"]) as bundle:
                self.assertFalse(any(name.endswith("cgv_checkout_no_submit_probe.py") for name in bundle.getnames()))
            windows = next(item for item in result["artifacts"] if item["operating_system"] == "windows")
            with zipfile.ZipFile(windows["archive"]) as bundle:
                self.assertFalse(any(name.endswith("cgv_checkout_no_submit_probe.py") for name in bundle.namelist()))


if __name__ == "__main__":
    unittest.main()
