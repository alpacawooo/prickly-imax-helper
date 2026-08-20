#!/usr/bin/env python3
"""Repository-only checkout probe that cannot enter the submission stage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from prickly_imax_helper.browser import CGV_BOOKING_URL, launch_browser
from prickly_imax_helper.cgv import CgvSession
from prickly_imax_helper.checkout import CheckoutFlow
from prickly_imax_helper.config import load_config
from prickly_imax_helper.paths import RuntimePaths


class ProbeSafetyError(RuntimeError):
    pass


QA_SENTINEL_NAME = ".prickly-no-submit-qa"
QA_SENTINEL_VALUE = "PRICKLY_NO_SUBMIT_QA_V1\n"


class NoSubmitCheckoutFlow(CheckoutFlow):
    """Checkout flow whose submission boundary is disabled at runtime."""

    @staticmethod
    def _forbidden() -> None:
        raise ProbeSafetyError("submission and post-submission methods are forbidden in the QA probe")

    def prove_ready(self, _match: dict[str, Any]) -> None:
        self._forbidden()

    def submit_once(self) -> None:
        self._forbidden()

    def prove_and_submit_once(self, _match: dict[str, Any]) -> None:
        self._forbidden()

    def verify_mobile_ticket(self, _match: dict[str, Any]) -> None:
        self._forbidden()


def require_isolated_home(home: Path) -> Path:
    resolved = home.expanduser().resolve()
    default = RuntimePaths.default().root.expanduser().resolve()
    if resolved == default:
        raise ProbeSafetyError("a separate QA home is required; the customer runtime home is forbidden")
    sentinel = resolved / QA_SENTINEL_NAME
    try:
        sentinel_value = sentinel.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProbeSafetyError(f"QA sentinel is required at {sentinel}") from exc
    if sentinel_value != QA_SENTINEL_VALUE:
        raise ProbeSafetyError("QA sentinel content is invalid")
    service_markers = (
        resolved / "ai.prickly.imax-helper.plist",
        resolved / "state/heartbeat.json",
        resolved / "state/checkout.json",
        resolved / "app",
        resolved / "venv",
    )
    if any(marker.exists() for marker in service_markers):
        raise ProbeSafetyError("QA home contains installed runtime or resident service state")
    return resolved


def execute_no_submit_probe(flow: Any, match: dict[str, Any], *, party_size: int) -> dict[str, str]:
    """Exercise only pre-submission stages and return immediately after vouchers."""

    flow.ensure_no_existing_ticket(match, separate_tab=True)
    flow.open_movie_and_theater()
    flow._require_match_date(match)
    flow._open_match_showtime(match)
    flow._select_general_party(party_size)
    flow._select_seats(match)
    flow.open_payment_and_apply_vouchers()
    return {"status": "stopped_before_submit", "last_stage": "vouchers"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True, help="separate QA runtime home")
    parser.add_argument("--match-json", required=True, help="date/time/seats JSON for an authorized QA show")
    parser.add_argument("--acknowledge-no-submit", action="store_true", required=True)
    args = parser.parse_args()

    home = require_isolated_home(args.home)
    match = json.loads(args.match_json)
    if not isinstance(match, dict) or not {"date", "time", "seats"}.issubset(match):
        raise ProbeSafetyError("match JSON must contain date, time, and seats")
    paths = RuntimePaths(home)
    paths.prepare()
    config = load_config(paths.config)
    launch_browser(paths, CGV_BOOKING_URL)
    session = CgvSession(paths)
    with session.locked():
        session.require_login()
        result = execute_no_submit_probe(
            NoSubmitCheckoutFlow(session.page, config),
            match,
            party_size=int(config["party_size"]),
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
