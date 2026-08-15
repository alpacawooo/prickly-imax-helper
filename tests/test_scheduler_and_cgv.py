from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from prickly_imax_helper.cgv import CgvSession, LoginRequired, RateLimited
from prickly_imax_helper.paths import RuntimePaths
from prickly_imax_helper.policy import has_minimum_lead
from prickly_imax_helper.presets import odyssey
from prickly_imax_helper.scheduler import (
    BalancedScanPlanner,
    FairScanState,
    changed_seat_targets,
    eligible_shows,
    match_for,
)


KST = ZoneInfo("Asia/Seoul")


class SchedulerTests(unittest.TestCase):
    def test_planner_rotates_known_shows_without_inserting_discovery(self):
        planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
        planner.replace_discovery(
            ["20260820"],
            {"20260820": [
                {"ymd": "20260820", "scnsNo": "18", "scnSseq": "1", "time": "19:00"},
                {"ymd": "20260820", "scnsNo": "18", "scnSseq": "2", "time": "22:00"},
            ]},
            now=10.0,
        )

        actions = []
        for _ in range(6):
            action = planner.next_hot_action()
            actions.append(action)
            planner.complete(action)

        self.assertEqual(
            [action.show["scnSseq"] for action in actions],
            ["1", "2", "1", "2", "1", "2"],
        )
        self.assertEqual({action.lane for action in actions}, {"hot"})

    def test_planner_returns_none_when_no_hot_targets_exist(self):
        planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
        planner.replace_discovery(["20260820"], {"20260820": []}, now=1.0)
        self.assertIsNone(planner.next_hot_action())

    def test_atomic_discovery_replacement_preserves_next_fair_target(self):
        planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
        first = {"ymd": "20260820", "scnsNo": "18", "scnSseq": "1", "time": "19:00"}
        second = {"ymd": "20260820", "scnsNo": "18", "scnSseq": "2", "time": "22:00"}
        third = {"ymd": "20260820", "scnsNo": "18", "scnSseq": "3", "time": "24:30"}
        planner.replace_discovery(["20260820"], {"20260820": [first, second]}, now=1.0)
        action = planner.next_hot_action()
        self.assertEqual(action.show["scnSseq"], "1")
        planner.complete(action)

        planner.replace_discovery(
            ["20260820"], {"20260820": [first, second, third]}, now=3.0
        )
        action = planner.next_hot_action()
        self.assertEqual(action.show["scnSseq"], "2")
        planner.complete(action)
        planner.replace_discovery(["20260820"], {"20260820": [first, third]}, now=5.0)

        remaining = []
        for _ in range(2):
            action = planner.next_hot_action()
            remaining.append(action.show["scnSseq"])
            planner.complete(action)
        self.assertEqual(remaining, ["3", "1"])

    def test_balanced_planner_does_not_advance_until_action_completes(self):
        planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
        planner.replace_discovery(
            ["20260820"],
            {"20260820": [
                {"scnsNo": "18", "scnSseq": "1", "time": "19:00"},
                {"scnsNo": "18", "scnSseq": "2", "time": "22:00"},
            ]},
            now=1.0,
        )

        failed = planner.next_hot_action()
        retried = planner.next_hot_action()
        self.assertEqual(retried, failed)

        planner.complete(retried)
        advanced = planner.next_hot_action()
        self.assertEqual(advanced.show["scnSseq"], "2")

    def test_removed_hot_target_stays_pruned_until_daily_discovery(self):
        planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
        show = {"ymd": "20260820", "scnsNo": "18", "scnSseq": "1", "time": "19:00"}
        planner.replace_discovery(["20260820"], {"20260820": [show]}, now=1.0)

        planner.remove_hot_target(show)
        self.assertEqual(planner.hot_targets, [])
        self.assertIsNone(planner.next_hot_action())

        planner.replace_discovery(["20260820"], {"20260820": [show]}, now=3.0)
        self.assertEqual([candidate["scnSseq"] for candidate in planner.hot_targets], ["1"])

    def test_revisit_metric_uses_only_hot_target_count(self):
        planner = BalancedScanPlanner(minimum_interval_seconds=1.0)
        planner.replace_discovery(
            ["20260820"],
            {"20260820": [
                {"ymd": "20260820", "scnsNo": "18", "scnSseq": str(index), "time": "19:00"}
                for index in range(35)
            ]},
            now=10.0,
        )

        metrics = planner.metrics(now=20.0)

        self.assertEqual(metrics["hot_target_count"], 35)
        self.assertEqual(metrics["estimated_hot_revisit_seconds"], 35.0)
        self.assertEqual(metrics["discovery_queue_count"], 0)
        self.assertEqual(metrics["oldest_schedule_age_seconds"], 10.0)

    def test_dates_rotate_fairly_and_refresh_dynamically(self):
        state = FairScanState()
        state.replace_dates(["20260805", "20260806", "20260807"])
        self.assertEqual([state.next_date() for _ in range(4)], ["20260805", "20260806", "20260807", "20260805"])
        state.replace_dates(["20260806", "20260807", "20260808"])
        self.assertIn(state.next_date(), {"20260806", "20260807", "20260808"})

    def test_only_changed_counts_trigger_seat_map(self):
        state = FairScanState()
        shows = [{"ymd": "20260808", "scnsNo": "018", "scnSseq": "1", "frSeatCnt": 2}]
        self.assertEqual(len(changed_seat_targets(state, shows)), 1)
        self.assertEqual(changed_seat_targets(state, shows), [])
        shows[0]["frSeatCnt"] = 3
        self.assertEqual(len(changed_seat_targets(state, shows)), 1)

    def test_changed_count_respects_configured_party_size(self):
        state = FairScanState()
        shows = [{"ymd": "20260808", "scnsNo": "018", "scnSseq": "1", "frSeatCnt": 2}]
        self.assertEqual(changed_seat_targets(state, shows, 3), [])
        shows[0]["frSeatCnt"] = 3
        self.assertEqual(len(changed_seat_targets(state, shows, 3)), 1)

    def test_schedule_and_pair_policy_are_preserved(self):
        config = odyssey()
        schedules = [
            {"movkndDsplNm": "IMAX 2D", "scnsrtTm": "0630", "scnsNo": "018", "scnSseq": "1", "frSeatCnt": 2},
            {"movkndDsplNm": "IMAX 2D", "scnsrtTm": "2300", "scnsNo": "018", "scnSseq": "2", "frSeatCnt": 2},
        ]
        saturday = eligible_shows("20260808", schedules, config, now=datetime(2026, 8, 7, 0, 0, tzinfo=KST))
        self.assertEqual([show["time"] for show in saturday], ["06:30", "23:00"])
        sunday = eligible_shows("20260809", schedules, config, now=datetime(2026, 8, 8, 0, 0, tzinfo=KST))
        self.assertEqual([show["time"] for show in sunday], ["06:30"])
        seats = [f"H{i}" for i in range(1, 31)]
        result = match_for(saturday[0], {"all": seats, "available": ["H15", "H16"]}, config)
        self.assertEqual(result["pair"], "H15-H16")

    def test_format_filter_uses_configured_imax_label(self):
        config = odyssey()
        config["format"] = "IMAX LASER"
        schedules = [
            {"movkndDsplNm": "IMAX 2D", "scnsrtTm": "1900"},
            {"movkndDsplNm": "IMAX LASER 2D", "scnsrtTm": "1930"},
        ]
        self.assertEqual(
            [
                show["time"]
                for show in eligible_shows(
                    "20260806", schedules, config, now=datetime(2026, 8, 5, 0, 0, tzinfo=KST)
                )
            ],
            ["19:30"],
        )

    def test_minimum_lead_accepts_exactly_180_minutes_and_rejects_less(self):
        config = odyssey()
        schedules = [
            {"scnsrtTm": "2100", "movkndDsplNm": "IMAX", "scnsNo": "1", "scnSseq": "1"},
            {"scnsrtTm": "2059", "movkndDsplNm": "IMAX", "scnsNo": "1", "scnSseq": "2"},
        ]
        now = datetime(2026, 8, 10, 18, 0, tzinfo=KST)

        result = eligible_shows("20260810", schedules, config, now=now)

        self.assertEqual([show["time"] for show in result], ["21:00"])

    def test_2430_rolls_into_the_next_calendar_day(self):
        config = odyssey()
        config["time_rules"]["sunday"] = {"any_time": True}
        schedules = [{"scnsrtTm": "2430", "movkndDsplNm": "IMAX"}]

        accepted = eligible_shows(
            "20260809", schedules, config,
            now=datetime(2026, 8, 9, 21, 30, tzinfo=KST),
        )
        rejected = eligible_shows(
            "20260809", schedules, config,
            now=datetime(2026, 8, 9, 21, 31, tzinfo=KST),
        )

        self.assertEqual([show["time"] for show in accepted], ["24:30"])
        self.assertEqual(rejected, [])

    def test_later_date_remains_eligible(self):
        config = odyssey()
        schedules = [{"scnsrtTm": "1900", "movkndDsplNm": "IMAX"}]

        result = eligible_shows(
            "20260811", schedules, config,
            now=datetime(2026, 8, 10, 23, 0, tzinfo=KST),
        )

        self.assertEqual([show["time"] for show in result], ["19:00"])

    def test_aware_utc_now_is_converted_to_korea_time(self):
        config = odyssey()
        schedules = [{"scnsrtTm": "2100", "movkndDsplNm": "IMAX"}]

        result = eligible_shows(
            "20260810", schedules, config,
            now=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
        )

        self.assertEqual([show["time"] for show in result], ["21:00"])

    def test_minimum_lead_rejects_naive_now(self):
        with self.assertRaisesRegex(ValueError, "now must include timezone information"):
            has_minimum_lead(
                "20260810",
                "21:00",
                180,
                now=datetime(2026, 8, 10, 18, 0),
            )

    def test_minimum_lead_accepts_configured_boundaries(self):
        lower = odyssey()
        lower["minimum_lead_minutes"] = 180
        lower_result = eligible_shows(
            "20260810",
            [{"scnsrtTm": "2100", "movkndDsplNm": "IMAX"}],
            lower,
            now=datetime(2026, 8, 10, 18, 0, tzinfo=KST),
        )

        upper = odyssey()
        upper["minimum_lead_minutes"] = 1440
        upper_result = eligible_shows(
            "20260811",
            [{"scnsrtTm": "1900", "movkndDsplNm": "IMAX"}],
            upper,
            now=datetime(2026, 8, 10, 19, 0, tzinfo=KST),
        )

        self.assertEqual([show["time"] for show in lower_result], ["21:00"])
        self.assertEqual([show["time"] for show in upper_result], ["19:00"])

    def test_minimum_lead_rejects_invalid_config_types_and_ranges(self):
        for value in (False, True, None, "180", 180.0, 179, 1441):
            with self.subTest(value=value):
                config = odyssey()
                config["minimum_lead_minutes"] = value

                with self.assertRaisesRegex(ValueError, "minimum_lead_minutes must be an integer from 180 through 1440"):
                    eligible_shows(
                        "20260810",
                        [{"scnsrtTm": "2100", "movkndDsplNm": "IMAX"}],
                        config,
                        now=datetime(2026, 8, 10, 18, 0, tzinfo=KST),
                    )


class FakeBudget:
    def __init__(self) -> None:
        self.acquired = 0
        self.deferred: list[float] = []

    def acquire(self) -> None:
        self.acquired += 1

    def defer(self, seconds: float) -> None:
        self.deferred.append(seconds)


class FakePage:
    def __init__(self, value: dict) -> None:
        self.value = value
        self.last_path: str | None = None

    def evaluate(self, script: str, path: str | None = None) -> dict:
        self.last_path = path
        return self.value


class CgvApiTests(unittest.TestCase):
    def test_closed_tab_is_replaced_with_existing_cgv_tab(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            closed = Mock()
            closed.is_closed.return_value = True
            live = Mock()
            live.is_closed.return_value = False
            live.url = "https://cgv.co.kr/cnm/movieBook"
            context = Mock()
            context.pages = [closed, live]
            browser = Mock()
            browser.is_connected.return_value = True
            browser.contexts = [context]
            session.page = closed
            session.browser = browser

            session.ensure_page()

            self.assertIs(session.page, live)
            context.new_page.assert_not_called()

    def test_closed_tab_opens_booking_page_when_no_cgv_tab_remains(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            closed = Mock()
            closed.is_closed.return_value = True
            replacement = Mock()
            replacement.is_closed.return_value = False
            context = Mock()
            context.pages = [closed]
            context.new_page.return_value = replacement
            browser = Mock()
            browser.is_connected.return_value = True
            browser.contexts = [context]
            session.page = closed
            session.browser = browser

            session.ensure_page()

            self.assertIs(session.page, replacement)
            replacement.goto.assert_called_once_with("https://cgv.co.kr/cnm/movieBook", wait_until="domcontentloaded")

    def test_429_applies_shared_cooldown(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            session.budget = FakeBudget()
            session.page = FakePage({"status": 429, "retryAfter": "900", "text": "rate limited"})
            with self.assertRaises(RateLimited):
                session.api_get("/test")
            self.assertEqual(session.budget.acquired, 1)
            self.assertEqual(session.budget.deferred, [900.0])

    def test_429_exposes_server_cooldown_to_monitor(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            session.budget = FakeBudget()
            session.page = FakePage({"status": 429, "retryAfter": "900", "text": "rate limited"})
            with self.assertRaises(RateLimited) as raised:
                session.api_get("/test")
            self.assertEqual(raised.exception.cooldown_seconds, 900.0)

    def test_success_requires_cgv_status_code_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            session.budget = FakeBudget()
            session.page = FakePage({"status": 200, "retryAfter": None, "text": json.dumps({"statusCode": 0, "data": [1]})})
            self.assertEqual(session.api_get("/test"), [1])
            self.assertEqual(session.budget.acquired, 1)

    def test_403_is_reported_as_login_required(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            session.budget = FakeBudget()
            session.page = FakePage({"status": 403, "retryAfter": None, "text": "forbidden"})
            with self.assertRaises(LoginRequired):
                session.api_get("/test")

    def test_booking_target_is_resolved_from_selected_schedule_request(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(RuntimePaths(Path(temp)))
            session.page = FakePage(
                [
                    "https://cgv.co.kr/api/v1/booking/searchSchByMov?coCd=A420&siteNo=0099&movNo=movie123&scnYmd=20260808",
                ]
            )
            self.assertEqual(
                session.booking_target_from_page(),
                {"company_code": "A420", "site_no": "0099", "movie_no": "movie123"},
            )

    def test_custom_target_identifiers_drive_availability_request(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(
                RuntimePaths(Path(temp)),
                company_code="TEST",
                site_no="0099",
                movie_no="movie123",
            )
            session.budget = FakeBudget()
            page = FakePage(
                {
                    "status": 200,
                    "retryAfter": None,
                    "text": json.dumps({"statusCode": 0, "data": [{"scnYmd": "20260808"}]}),
                }
            )
            session.page = page
            self.assertEqual(session.open_dates(), ["20260808"])
            self.assertIn("coCd=TEST&siteNo=0099&movNo=movie123", str(page.last_path))

    def test_custom_target_identifiers_drive_seat_request(self):
        with tempfile.TemporaryDirectory() as temp:
            session = CgvSession(
                RuntimePaths(Path(temp)),
                company_code="TEST",
                site_no="0099",
                movie_no="movie123",
            )
            session.budget = FakeBudget()
            page = FakePage(
                {
                    "status": 200,
                    "retryAfter": None,
                    "text": json.dumps(
                        {
                            "statusCode": 0,
                            "data": {
                                "items": [
                                    {
                                        "seats": [
                                            {"seatRowNm": "H", "seatNo": "15", "seatSaleYn": "Y"},
                                            {"seatRowNm": "H", "seatNo": "16", "seatSaleYn": "N"},
                                        ]
                                    }
                                ]
                            },
                        }
                    ),
                }
            )
            session.page = page
            self.assertEqual(session.seats("20260808", "018", "1"), {"all": ["H15", "H16"], "available": ["H15"]})
            self.assertIn("coCd=TEST&siteNo=0099", str(page.last_path))
            self.assertNotIn("siteNo=0013", str(page.last_path))


if __name__ == "__main__":
    unittest.main()
