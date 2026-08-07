from __future__ import annotations

import unittest

from prickly_imax_helper.checkout import CheckoutFlow
from prickly_imax_helper.presets import odyssey


class ScriptedPage:
    def __init__(self) -> None:
        self.evaluate_calls = 0

    def goto(self, *_args, **_kwargs) -> None:
        return None

    def wait_for_function(self, *_args, **_kwargs) -> None:
        return None

    def evaluate(self, *_args, **_kwargs):
        self.evaluate_calls += 1
        if self.evaluate_calls == 1:
            return True
        if self.evaluate_calls == 2:
            return {"picker": False}
        return False


class ReadyTheaterFlow(CheckoutFlow):
    def _booking_page_state(self, theater: str, format_name: str) -> dict[str, bool]:
        self.seen_target = (theater, format_name)
        return {"picker": False, "target_ready": True}

    def _open_theater_picker(self) -> bool:
        raise AssertionError("ready booking state must not reopen the theater picker")


class CheckoutNavigationTests(unittest.TestCase):
    def test_already_selected_configured_theater_skips_picker(self):
        page = ScriptedPage()
        flow = ReadyTheaterFlow(page, odyssey())

        flow.open_movie_and_theater()

        self.assertEqual(flow.seen_target, ("용산아이파크몰", "IMAX"))
        self.assertEqual(page.evaluate_calls, 1)


if __name__ == "__main__":
    unittest.main()
