from __future__ import annotations

import unittest

from prickly_imax_helper.browser import CHROME
from prickly_imax_helper.checkout import CheckoutFlow, PaymentBlocked, UnknownAfterSubmit
from prickly_imax_helper.presets import odyssey


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


HTML = """<!doctype html><meta charset=utf-8>
<p>선택 좌석 H15 H16</p><p>IMAX 영화관람권 2매</p><p>최종 결제 금액 0원</p>
<label>IMAX 영화관람권<input type=checkbox checked></label>
<label>IMAX 영화관람권<input type=checkbox checked></label>
<button id=submit onclick=\"window.clicked=(window.clicked||0)+1\">0원 결제하기</button>"""


@unittest.skipIf(sync_playwright is None or CHROME is None or not CHROME.is_file(), "Playwright and system Chrome are required")
class CheckoutBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(executable_path=str(CHROME), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.page.set_content(HTML)
        self.flow = CheckoutFlow(self.page, odyssey())
        self.match = {"seats": ["H15", "H16"]}

    def tearDown(self):
        self.page.close()

    def test_exact_proof_clicks_once_and_cannot_repeat(self):
        self.flow.prove_ready(self.match)
        self.flow.submit_once()
        self.assertEqual(self.page.evaluate("() => window.clicked"), 1)
        with self.assertRaises(UnknownAfterSubmit):
            self.flow.submit_once()
        self.assertEqual(self.page.evaluate("() => window.clicked"), 1)

    def test_two_final_buttons_block_submission(self):
        self.page.evaluate("() => document.body.append(document.querySelector('#submit').cloneNode(true))")
        with self.assertRaises(PaymentBlocked):
            self.flow.prove_ready(self.match)
        self.assertIsNone(self.page.evaluate("() => window.clicked"))

    def test_unselected_voucher_blocks_submission(self):
        self.page.evaluate("() => document.querySelector('input').checked = false")
        with self.assertRaises(PaymentBlocked):
            self.flow.prove_ready(self.match)
        self.assertIsNone(self.page.evaluate("() => window.clicked"))

    def test_configured_theater_showtime_and_format_are_ready(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <button aria-pressed=true>용산아이파크몰</button>
            <button>21:00-23:45 8 / 624석</button><h3>IMAX관</h3>"""
        )
        self.assertEqual(
            self.flow._booking_page_state("용산아이파크몰", "IMAX"),
            {"picker": False, "target_ready": True},
        )

    def test_different_theater_is_not_ready(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <button aria-pressed=true>왕십리</button>
            <button>21:00-23:45 8 / 624석</button><h3>IMAX관</h3>"""
        )
        self.assertEqual(
            self.flow._booking_page_state("용산아이파크몰", "IMAX"),
            {"picker": False, "target_ready": False},
        )

    def test_legacy_theater_picker_launcher_is_clicked(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <button onclick="window.pickerOpened=true"><span class=voice-only>자주가는 CGV 목록 수정</span></button>"""
        )
        self.assertTrue(self.flow._open_theater_picker())
        self.assertTrue(self.page.evaluate("() => window.pickerOpened"))

    def test_semantic_theater_picker_launcher_is_clicked(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <button aria-label="극장 선택" onclick="window.pickerOpened=true">극장 선택</button>"""
        )
        self.assertTrue(self.flow._open_theater_picker())
        self.assertTrue(self.page.evaluate("() => window.pickerOpened"))


if __name__ == "__main__":
    unittest.main()
