from __future__ import annotations

import datetime as dt
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

    def test_waits_for_delayed_theater_picker_render(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <script>
            setTimeout(() => document.body.insertAdjacentHTML(
              'beforeend', '<input placeholder="지역을 입력해주세요">'), 100);
            </script>"""
        )

        state = self.flow._wait_for_booking_page_state("용산아이파크몰", "IMAX", timeout_ms=2_000)

        self.assertEqual(state, {"picker": True, "target_ready": False})

    def test_selects_search_suggestion_then_actual_theater_row_and_confirms(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <input placeholder="지역을 입력해주세요">
            <button id="suggestion" type="button">용산아이파크몰</button>
            <ul id="theaters"><li><button id="actual" type="button">용산아이파크몰</button></li></ul>
            <script>
              suggestion.onclick = () => suggestion.remove();
              actual.onclick = () => document.body.insertAdjacentHTML(
                'beforeend', '<button id="confirm" type="button">극장선택</button>');
              document.addEventListener('click', event => {
                if (event.target.id !== 'confirm') return;
                document.querySelector('input').remove();
                document.body.insertAdjacentHTML('beforeend',
                  '<button>용산아이파크몰</button><button>21:00-23:45 8 / 624석</button><h3>IMAX관</h3>');
              });
            </script>"""
        )

        self.flow._select_theater_from_picker("용산아이파크몰", "IMAX")

        self.assertEqual(
            self.flow._booking_page_state("용산아이파크몰", "IMAX"),
            {"picker": False, "target_ready": True},
        )

    def test_retries_actual_theater_row_only_when_selection_did_not_register(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <input placeholder="지역을 입력해주세요">
            <ul><li><button id="actual" type="button">용산아이파크몰</button></li></ul>
            <script>
              window.actualClicks = 0;
              actual.onclick = () => {
                window.actualClicks += 1;
                if (window.actualClicks !== 2) return;
                document.body.insertAdjacentHTML('beforeend',
                  '<button id="selected">용산아이파크몰 닫기</button>' +
                  '<button id="confirm" type="button">극장선택</button>');
              };
              document.addEventListener('click', event => {
                if (event.target.id !== 'confirm') return;
                document.querySelector('input').remove();
                document.body.insertAdjacentHTML('beforeend',
                  '<button>용산아이파크몰</button><button>21:00-23:45 8 / 624석</button><h3>IMAX관</h3>');
              });
            </script>"""
        )

        self.flow._select_theater_from_picker("용산아이파크몰", "IMAX")

        self.assertEqual(self.page.evaluate("() => window.actualClicks"), 2)
        self.assertTrue(self.flow._booking_page_state("용산아이파크몰", "IMAX")["target_ready"])

    def test_current_date_accepts_cgv_today_label(self):
        today = dt.date.today()
        self.page.set_content(
            f"""<!doctype html><meta charset=utf-8>
            <button onclick="window.dateClicked=true">
              <span class="dayScroll_txt__test">오늘</span>
              <span class="dayScroll_number__test">{today.day:02d}</span>
            </button>"""
        )

        self.assertTrue(self.flow._click_match_date(today.isoformat()))
        self.assertTrue(self.page.evaluate("() => window.dateClicked"))


if __name__ == "__main__":
    unittest.main()
