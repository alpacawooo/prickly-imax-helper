from __future__ import annotations

import datetime as dt
import unittest

from prickly_imax_helper.browser import CHROME
from prickly_imax_helper.checkout import (
    CheckoutError,
    CheckoutFlow,
    PaymentBlocked,
    SeatVanished,
    UnknownAfterSubmit,
)
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


class _CappedTimeoutPage:
    """Keep fail-closed browser fixtures fast without changing production limits."""

    def __init__(self, page, timeout_ms=1_000):
        self._page = page
        self._timeout_ms = timeout_ms

    def wait_for_function(self, expression, *, arg=None, timeout=None):
        timeout = self._timeout_ms if timeout is None else min(timeout, self._timeout_ms)
        return self._page.wait_for_function(expression, arg=arg, timeout=timeout)

    def __getattr__(self, name):
        return getattr(self._page, name)


class _MutatingAfterWaitPage(_CappedTimeoutPage):
    """Mutate browser state after readiness to exercise click-time revalidation."""

    def __init__(self, page, *, after_wait, mutation, timeout_ms=1_000):
        super().__init__(page, timeout_ms)
        self._after_wait = after_wait
        self._mutation = mutation
        self._completed_waits = 0

    def wait_for_function(self, expression, *, arg=None, timeout=None):
        result = super().wait_for_function(expression, arg=arg, timeout=timeout)
        self._completed_waits += 1
        if self._completed_waits == self._after_wait:
            self._page.evaluate(self._mutation)
        return result


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

    def _cap_checkout_waits(self, timeout_ms=1_000):
        self.flow.page = _CappedTimeoutPage(self.page, timeout_ms)

    def _set_payment_content(self, body, script=""):
        self.page.set_content(
            f"""<!doctype html><meta charset=utf-8>
            <script>window.orderClicks=0;window.popupClicks=0;window.finalSubmitClicks=0;{script}</script>
            {body}
            <button id=final-submit style=display:none
              onclick="window.finalSubmitClicks += 1">0원 결제하기</button>"""
        )

    def _voucher_markup(self):
        return """<button id=voucher-section>관람권</button>
          <button>IMAX 영화관람권 A</button><button>IMAX 영화관람권 B</button><button>적용</button>"""

    def _assert_no_final_submit(self):
        self.assertEqual(self.page.evaluate("() => window.finalSubmitClicks"), 0)

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

    def test_selects_single_direct_theater_result_when_cgv_does_not_use_list_rows(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <input placeholder="지역을 입력해주세요">
            <div role="button" id="actual" tabindex="0">용산아이파크몰 10.3km</div>
            <script>
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

    def test_waits_for_transient_duplicate_actual_theater_rows(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <input placeholder="지역을 입력해주세요">
            <div class="search-result active"><ul>
              <li><button id="suggestion" type="button">용산아이파크몰</button></li>
            </ul></div>
            <script>
              window.suggestionClicks = 0;
              window.actualClicks = 0;
              suggestion.onclick = () => {
                window.suggestionClicks += 1;
                document.querySelector('.search-result').remove();
                document.body.insertAdjacentHTML('beforeend', `<ul>
                  <li><button id="actual" type="button">용산아이파크몰</button></li>
                  <li id="stale"><button type="button">용산아이파크몰</button></li>
                </ul>`);
                actual.onclick = () => {
                  window.actualClicks += 1;
                  document.body.insertAdjacentHTML(
                    'beforeend', '<button id="confirm" type="button">극장선택</button>');
                };
                setTimeout(() => stale.remove(), 700);
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

        self.assertEqual(self.page.evaluate("() => window.suggestionClicks"), 1)
        self.assertEqual(self.page.evaluate("() => window.actualClicks"), 1)
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

    def test_waits_for_delayed_general_party_control(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <script>
              setTimeout(() => document.body.insertAdjacentHTML('beforeend', `
                <div role="group"><div>일반</div>
                  <button aria-label="1 선택" aria-pressed="false">1</button>
                  <button aria-label="2 선택" aria-pressed="false"
                    onclick="this.setAttribute('aria-pressed','true')">2</button>
                </div>`), 500);
            </script>"""
        )

        self.flow._select_general_party(2, timeout_ms=2_000)

        self.assertEqual(
            self.page.locator('[role=group]').get_by_role("button", name="2 선택").get_attribute("aria-pressed"),
            "true",
        )

    def test_selects_two_only_inside_exact_general_group(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <div role=group><div>일반</div><button aria-label="2 선택" aria-pressed=false
              onclick="window.general=(window.general||0)+1;this.setAttribute('aria-pressed','true')">2</button></div>
            <div role=group><div>청소년</div><button aria-label="2 선택" aria-pressed=false
              onclick="window.youth=(window.youth||0)+1;this.setAttribute('aria-pressed','true')">2</button></div>
            <div role=group><div>우대</div><button aria-label="2 선택" aria-pressed=false
              onclick="window.priority=(window.priority||0)+1;this.setAttribute('aria-pressed','true')">2</button></div>"""
        )

        self.flow._select_general_party(2, timeout_ms=500)

        self.assertEqual(self.page.evaluate("() => window.general"), 1)
        self.assertIsNone(self.page.evaluate("() => window.youth"))
        self.assertIsNone(self.page.evaluate("() => window.priority"))

    def test_missing_general_party_control_times_out_without_click(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <div role=group><div>청소년</div><button aria-label="2 선택"
              onclick="window.youth=(window.youth||0)+1">2</button></div>
            <div role=group><div>우대</div><button aria-label="2 선택"
              onclick="window.priority=(window.priority||0)+1">2</button></div>"""
        )

        with self.assertRaises(CheckoutError):
            self.flow._select_general_party(2, timeout_ms=100)

        self.assertIsNone(self.page.evaluate("() => window.youth"))
        self.assertIsNone(self.page.evaluate("() => window.priority"))

    def test_unproven_general_selection_is_not_clicked_twice(self):
        self.page.set_content(
            """<!doctype html><meta charset=utf-8>
            <div role=group><div>일반</div><button aria-label="2 선택" aria-pressed=false
              onclick="window.general=(window.general||0)+1">2</button></div>"""
        )

        with self.assertRaises(CheckoutError):
            self.flow._select_general_party(2, timeout_ms=500)

        self.assertEqual(self.page.evaluate("() => window.general"), 1)

    def test_waits_for_all_clicked_seats_to_be_confirmed(self):
        self._cap_checkout_waits()
        self.page.set_content(
            """<!doctype html><meta charset=utf-8><script>window.orderClicks=0;window.finalSubmitClicks=0</script>
            <button data-seatlocno onclick="setTimeout(() => this.classList.add('seatSelected'), 300)">H15</button>
            <button data-seatlocno onclick="setTimeout(() => this.setAttribute('aria-pressed','true'), 300)">H16</button>
            <button onclick="window.orderClicks += 1">30,000원 결제하기</button>
            <button onclick="window.finalSubmitClicks += 1">0원 결제하기</button>"""
        )

        self.flow._select_seats(self.match)

        seats = self.page.locator("button[data-seatlocno]")
        self.assertTrue(seats.nth(0).evaluate("e => e.classList.contains('seatSelected')"))
        self.assertEqual(seats.nth(1).get_attribute("aria-pressed"), "true")
        self.assertEqual(self.page.evaluate("() => window.orderClicks"), 0)
        self._assert_no_final_submit()

    def test_unconfirmed_requested_seat_blocks_order_and_final_submit(self):
        self._cap_checkout_waits(500)
        self.page.set_content(
            """<!doctype html><meta charset=utf-8><script>window.orderClicks=0;window.finalSubmitClicks=0</script>
            <button data-seatlocno onclick="this.classList.add('seatSelected')">H15</button>
            <button data-seatlocno>H16</button>
            <button onclick="window.orderClicks += 1">30,000원 결제하기</button>
            <button onclick="window.finalSubmitClicks += 1">0원 결제하기</button>"""
        )

        with self.assertRaisesRegex(SeatVanished, "target seat selection was not confirmed"):
            self.flow._select_seats(self.match)

        self.assertEqual(self.page.evaluate("() => window.orderClicks"), 0)
        self._assert_no_final_submit()

    def test_waits_for_one_delayed_enabled_order_button_and_clicks_once(self):
        self._cap_checkout_waits()
        vouchers = self._voucher_markup().replace("`", "\\`")
        self._set_payment_content(
            """<button id=order disabled onclick="window.orderClicks += 1;
              document.body.insertAdjacentHTML('beforeend', window.vouchers)">30,000원 결제하기</button>""",
            f"window.vouchers=`{vouchers}`;setTimeout(() => order.disabled=false, 500);",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.orderClicks"), 1)
        self._assert_no_final_submit()

    def test_invalid_order_button_states_fail_closed(self):
        cases = {
            "missing": "",
            "duplicate": "<button onclick='window.orderClicks+=1'>30,000원 결제하기</button><button onclick='window.orderClicks+=1'>30,000원 결제하기</button>",
            "hidden": "<button style='display:none' onclick='window.orderClicks+=1'>30,000원 결제하기</button>",
            "css-visibility-hidden": "<button style='visibility:hidden' onclick='window.orderClicks+=1'>30,000원 결제하기</button>",
            "disabled": "<button disabled onclick='window.orderClicks+=1'>30,000원 결제하기</button>",
            "aria-disabled": "<button aria-disabled='true' onclick='window.orderClicks+=1'>30,000원 결제하기</button>",
            "aria-disabled-ancestor": "<div aria-disabled='true'><button onclick='window.orderClicks+=1'>30,000원 결제하기</button></div>",
            "wrong-text": "<button onclick='window.orderClicks+=1'>30,000원 결제</button>",
        }
        for name, body in cases.items():
            with self.subTest(name=name):
                self._cap_checkout_waits(150)
                self._set_payment_content(body)
                with self.assertRaises(CheckoutError):
                    self.flow.open_payment_and_apply_vouchers()
                self.assertEqual(self.page.evaluate("() => window.orderClicks"), 0)
                self._assert_no_final_submit()

    def test_order_button_inherited_disabledness_is_revalidated_at_click_time(self):
        vouchers = self._voucher_markup().replace("`", "\\`")
        self._set_payment_content(
            """<div id=order-guard><button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.vouchers)">
              30,000원 결제하기</button></div>""",
            f"window.vouchers=`{vouchers}`;",
        )
        self.flow.page = _MutatingAfterWaitPage(
            self.page,
            after_wait=1,
            mutation="() => document.querySelector('#order-guard').setAttribute('aria-disabled', 'true')",
        )

        with self.assertRaises(CheckoutError):
            self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.orderClicks"), 0)
        self._assert_no_final_submit()

    def test_popup_absent_existing_voucher_flow_still_succeeds(self):
        self._cap_checkout_waits()
        vouchers = self._voucher_markup().replace("`", "\\`")
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks += 1;
              document.body.insertAdjacentHTML('beforeend', window.vouchers)">30,000원 결제하기</button>""",
            f"window.vouchers=`{vouchers}`;",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.orderClicks"), 1)
        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 0)
        self._assert_no_final_submit()

    def test_delayed_exact_popup_clicks_only_its_exact_payment_button(self):
        # Windows CI can take more than one second to deliver the timer and
        # requestAnimationFrame callback even though the popup delay is 100 ms.
        self._cap_checkout_waits(3_000)
        vouchers = self._voucher_markup().replace("`", "\\`")
        self._set_payment_content(
            """<button id=order onclick="window.delayedPopup()">
              30,000원 결제하기</button>
              <button onclick="window.outsideClicks=(window.outsideClicks||0)+1">결제하기</button>""",
            f"""window.vouchers=`{vouchers}`;window.delayedPopup=()=>{{window.orderClicks+=1;setTimeout(()=>
              document.body.insertAdjacentHTML('beforeend',`<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <button onclick=\"window.popupClicks+=1;document.body.insertAdjacentHTML('beforeend',window.vouchers)\">결제하기</button></div>`),100)}};""",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 1)
        self.assertIsNone(self.page.evaluate("() => window.outsideClicks"))
        self._assert_no_final_submit()

    def test_visible_popup_takes_priority_over_coexisting_voucher_ui(self):
        self._cap_checkout_waits()
        vouchers = self._voucher_markup().replace("`", "\\`")
        popup = """<div role=dialog><h2>결제 전 확인해 주세요</h2>
          <button onclick="window.popupClicks+=1">결제하기</button></div>"""
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.transitionMarkup)">30,000원 결제하기</button>""",
            f"window.transitionMarkup=`{popup + vouchers}`;",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 1)
        self._assert_no_final_submit()

    def test_non_heading_title_inside_known_modal_container_is_supported(self):
        self._cap_checkout_waits()
        vouchers = self._voucher_markup().replace("`", "\\`")
        popup = """<section class=bottom-modal><div>결제 전 확인해 주세요</div>
          <button onclick="window.popupClicks+=1;document.body.insertAdjacentHTML('beforeend',window.vouchers)">
          결제하기</button></section>"""
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.popupMarkup)">30,000원 결제하기</button>""",
            f"window.vouchers=`{vouchers}`;window.popupMarkup=`{popup}`;",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 1)
        self._assert_no_final_submit()

    def test_nested_modal_structure_is_treated_as_one_popup(self):
        self._cap_checkout_waits()
        vouchers = self._voucher_markup().replace("`", "\\`")
        popup = """<div role=dialog><div class=modal-body><h2>결제 전 확인해 주세요</h2>
          <button onclick="window.popupClicks+=1;document.body.insertAdjacentHTML('beforeend',window.vouchers)">
          결제하기</button></div></div>"""
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.popupMarkup)">30,000원 결제하기</button>""",
            f"window.vouchers=`{vouchers}`;window.popupMarkup=`{popup}`;",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 1)
        self._assert_no_final_submit()

    def test_exact_title_in_arbitrary_page_section_is_not_treated_as_popup(self):
        self._cap_checkout_waits(250)
        section = """<section><div>결제 전 확인해 주세요</div>
          <button onclick="window.popupClicks+=1">결제하기</button></section>"""
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.sectionMarkup)">30,000원 결제하기</button>""",
            f"window.sectionMarkup=`{section}`;",
        )

        with self.assertRaises(CheckoutError):
            self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 0)
        self._assert_no_final_submit()

    def test_waits_for_delayed_popup_payment_button(self):
        self._cap_checkout_waits()
        vouchers = self._voucher_markup().replace("`", "\\`")
        popup = """<div role=dialog><h2>결제 전 확인해 주세요</h2><div id=popup-actions></div></div>"""
        self._set_payment_content(
            """<button id=order onclick="window.showPopup()">30,000원 결제하기</button>""",
            f"""window.vouchers=`{vouchers}`;window.showPopup=()=>{{window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',`{popup}`);setTimeout(() =>
              document.querySelector('#popup-actions').insertAdjacentHTML('beforeend',
              `<button onclick=\"window.popupClicks+=1;document.body.insertAdjacentHTML('beforeend',window.vouchers)\">결제하기</button>`),300)}};""",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 1)
        self._assert_no_final_submit()

    def test_duplicate_exact_popup_containers_fail_without_clicking_either(self):
        self._cap_checkout_waits(300)
        popup = """<div role=dialog><h2>결제 전 확인해 주세요</h2>
          <button onclick="window.popupClicks+=1">결제하기</button></div>"""
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.popups)">30,000원 결제하기</button>""",
            f"window.popups=`{popup + popup}`;",
        )

        with self.assertRaises(CheckoutError):
            self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 0)
        self._assert_no_final_submit()

    def test_visible_unknown_or_ambiguous_modal_blocks_coexisting_voucher_ui(self):
        cases = {
            "wrong-title": """<div role=dialog><h2>결제 전 꼭 확인해 주세요</h2>
              <button onclick="window.popupClicks+=1">결제하기</button></div>""",
            "missing-title": """<div role=alertdialog><p>계속 진행하시겠습니까?</p>
              <button onclick="window.popupClicks+=1">확인</button></div>""",
            "exact-plus-unknown": """<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <button onclick="window.popupClicks+=1">결제하기</button></div>
              <section class=payment-popup><p>추가 확인</p>
              <button onclick="window.popupClicks+=1">확인</button></section>""",
            "nested-alertdialog": """<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <button onclick="window.popupClicks+=1">결제하기</button>
              <div role=alertdialog><p>추가 확인</p>
              <button onclick="window.popupClicks+=1">확인</button></div></div>""",
            "class-host-with-two-dialogs": """<div class=modal-host>
              <div role=dialog><h2>결제 전 확인해 주세요</h2>
              <button onclick="window.popupClicks+=1">결제하기</button></div>
              <div role=dialog><p>추가 확인</p>
              <button onclick="window.popupClicks+=1">확인</button></div></div>""",
            "class-only-branches": """<div class=modal-host>
              <section class=payment-popup><h2>결제 전 확인해 주세요</h2>
              <button onclick="window.popupClicks+=1">결제하기</button></section>
              <section class=warning-popup><p>추가 확인</p>
              <button onclick="window.popupClicks+=1">확인</button></section></div>""",
            "class-only-nested-extra": """<div class=payment-modal>
              <h2>결제 전 확인해 주세요</h2>
              <button onclick="window.popupClicks+=1">결제하기</button>
              <section class=warning-popup><p>추가 확인</p>
              <button onclick="window.popupClicks+=1">확인</button></section></div>""",
        }
        for name, popup in cases.items():
            with self.subTest(name=name):
                self._cap_checkout_waits(200)
                transition_markup = (popup + self._voucher_markup()).replace("`", "\\`")
                self._set_payment_content(
                    """<button id=order onclick="window.orderClicks+=1;
                      document.body.insertAdjacentHTML('beforeend',window.transitionMarkup)">
                      30,000원 결제하기</button>""",
                    f"window.transitionMarkup=`{transition_markup}`;",
                )

                with self.assertRaises(CheckoutError):
                    self.flow.open_payment_and_apply_vouchers()

                self.assertEqual(self.page.evaluate("() => window.popupClicks"), 0)
                self._assert_no_final_submit()

    def test_non_actionable_popup_elements_block_coexisting_voucher_ui(self):
        cases = {
            "hidden-button": """<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <button style="visibility:hidden" onclick="window.popupClicks+=1">결제하기</button></div>""",
            "aria-disabled-button": """<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <button aria-disabled="true" onclick="window.popupClicks+=1">결제하기</button></div>""",
            "aria-disabled-ancestor": """<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <div aria-disabled="true"><button onclick="window.popupClicks+=1">결제하기</button></div></div>""",
            "disabled-fieldset": """<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <fieldset disabled><button onclick="window.popupClicks+=1">결제하기</button></fieldset></div>""",
        }
        for name, popup in cases.items():
            with self.subTest(name=name):
                self._cap_checkout_waits(200)
                transition_markup = (popup + self._voucher_markup()).replace("`", "\\`")
                self._set_payment_content(
                    """<button id=order onclick="window.orderClicks+=1;
                      document.body.insertAdjacentHTML('beforeend',window.transitionMarkup)">
                      30,000원 결제하기</button>""",
                    f"window.transitionMarkup=`{transition_markup}`;",
                )

                with self.assertRaises(CheckoutError):
                    self.flow.open_payment_and_apply_vouchers()

                self.assertEqual(self.page.evaluate("() => window.popupClicks"), 0)
                self._assert_no_final_submit()

    def test_popup_button_inherited_disabledness_is_revalidated_at_click_time(self):
        vouchers = self._voucher_markup().replace("`", "\\`")
        popup = """<div role=dialog><h2>결제 전 확인해 주세요</h2><div id=popup-guard>
          <button onclick="window.popupClicks+=1">결제하기</button></div></div>"""
        transition_markup = (popup + vouchers).replace("`", "\\`")
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.transitionMarkup)">
              30,000원 결제하기</button>""",
            f"window.transitionMarkup=`{transition_markup}`;",
        )
        self.flow.page = _MutatingAfterWaitPage(
            self.page,
            after_wait=2,
            mutation="() => document.querySelector('#popup-guard').setAttribute('aria-disabled', 'true')",
        )

        with self.assertRaises(CheckoutError):
            self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 0)
        self._assert_no_final_submit()

    def test_hidden_popup_container_is_ignored_for_coexisting_voucher_ui(self):
        self._cap_checkout_waits()
        popup = """<div role=dialog style="visibility:hidden">
          <h2>결제 전 확인해 주세요</h2>
          <button onclick="window.popupClicks+=1">결제하기</button></div>"""
        transition_markup = (popup + self._voucher_markup()).replace("`", "\\`")
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.transitionMarkup)">
              30,000원 결제하기</button>""",
            f"window.transitionMarkup=`{transition_markup}`;",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 0)
        self._assert_no_final_submit()

    def test_unsafe_popup_titles_and_buttons_fail_without_any_payment_click(self):
        cases = {
            "wrong-title": """<div role=dialog><h2>결제 전 꼭 확인해 주세요</h2>
              <button onclick="window.popupClicks+=1">결제하기</button></div>""",
            "duplicate-buttons": """<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <button onclick="window.popupClicks+=1">결제하기</button><button onclick="window.popupClicks+=1">결제하기</button></div>""",
            "disabled-button": """<div role=dialog><h2>결제 전 확인해 주세요</h2>
              <button disabled onclick="window.popupClicks+=1">결제하기</button></div>""",
            "outside-only": """<div role=dialog><h2>결제 전 확인해 주세요</h2></div>
              <button onclick="window.popupClicks+=1">결제하기</button>""",
        }
        for name, popup in cases.items():
            with self.subTest(name=name):
                self._cap_checkout_waits(200)
                self._set_payment_content(
                    """<button id=order onclick="window.orderClicks+=1;
                      document.body.insertAdjacentHTML('beforeend',window.popupMarkup)">30,000원 결제하기</button>""",
                    f"window.popupMarkup=`{popup}`;",
                )
                with self.assertRaises(CheckoutError):
                    self.flow.open_payment_and_apply_vouchers()
                self.assertEqual(self.page.evaluate("() => window.popupClicks"), 0)
                self._assert_no_final_submit()

    def test_waits_for_delayed_voucher_ui_after_popup_confirmation(self):
        self._cap_checkout_waits()
        vouchers = self._voucher_markup().replace("`", "\\`")
        popup = """<div role=dialog><h2>결제 전 확인해 주세요</h2>
          <button onclick="window.popupClicks+=1;setTimeout(() => document.body.insertAdjacentHTML('beforeend',window.vouchers),500)">
          결제하기</button></div>"""
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.popupMarkup)">30,000원 결제하기</button>""",
            f"window.vouchers=`{vouchers}`;window.popupMarkup=`{popup}`;",
        )

        self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 1)
        self._assert_no_final_submit()

    def test_missing_voucher_ui_after_popup_confirmation_fails_closed(self):
        self._cap_checkout_waits(200)
        popup = """<div role=dialog><h2>결제 전 확인해 주세요</h2>
          <button onclick="window.popupClicks+=1">결제하기</button></div>"""
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.popupMarkup)">30,000원 결제하기</button>""",
            f"window.popupMarkup=`{popup}`;",
        )

        with self.assertRaises(CheckoutError):
            self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 1)
        self._assert_no_final_submit()

    def test_unknown_modal_after_approved_popup_blocks_all_later_payment_clicks(self):
        self._cap_checkout_waits(200)
        post_popup = """<button id=voucher-section onclick="window.voucherSectionClicks+=1">관람권</button>
          <button onclick="window.voucherClicks+=1">IMAX 영화관람권 A</button>
          <button onclick="window.voucherClicks+=1">IMAX 영화관람권 B</button>
          <button onclick="window.applyClicks+=1">적용</button>
          <div role=alertdialog><p>추가 확인이 필요합니다</p><button>확인</button></div>"""
        popup = """<div role=dialog><h2>결제 전 확인해 주세요</h2>
          <button onclick="window.popupClicks+=1;this.closest('[role=dialog]').remove();
            document.body.insertAdjacentHTML('beforeend',window.postPopupMarkup)">결제하기</button></div>"""
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.popupMarkup)">30,000원 결제하기</button>""",
            f"""window.voucherSectionClicks=0;window.voucherClicks=0;window.applyClicks=0;
              window.postPopupMarkup=`{post_popup}`;window.popupMarkup=`{popup}`;""",
        )

        with self.assertRaises(CheckoutError):
            self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.popupClicks"), 1)
        self.assertEqual(self.page.evaluate("() => window.voucherSectionClicks"), 0)
        self.assertEqual(self.page.evaluate("() => window.voucherClicks"), 0)
        self.assertEqual(self.page.evaluate("() => window.applyClicks"), 0)
        self._assert_no_final_submit()

    def test_unknown_visible_modal_blocks_payment_proof(self):
        self.page.evaluate(
            """() => document.body.insertAdjacentHTML('beforeend',
              '<div role="alertdialog"><p>추가 확인이 필요합니다</p><button>확인</button></div>')"""
        )

        with self.assertRaises(PaymentBlocked):
            self.flow.prove_ready(self.match)

        self.assertIsNone(self.page.evaluate("() => window.clicked"))

    def test_modal_opened_by_first_voucher_blocks_second_voucher_and_apply_clicks(self):
        self._cap_checkout_waits(200)
        vouchers = """<button id=voucher-section>관람권</button>
          <button onclick="window.voucherClicks+=1;document.body.insertAdjacentHTML('beforeend',
            '<div role=alertdialog><p>추가 확인이 필요합니다</p><button>확인</button></div>')">
            IMAX 영화관람권 A</button>
          <button onclick="window.voucherClicks+=1">IMAX 영화관람권 B</button>
          <button onclick="window.applyClicks+=1">적용</button>""".replace("`", "\\`")
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.vouchers)">30,000원 결제하기</button>""",
            f"window.voucherClicks=0;window.applyClicks=0;window.vouchers=`{vouchers}`;",
        )

        with self.assertRaises(CheckoutError):
            self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.voucherClicks"), 1)
        self.assertEqual(self.page.evaluate("() => window.applyClicks"), 0)
        self._assert_no_final_submit()

    def test_modal_opened_by_last_voucher_blocks_apply_click(self):
        self._cap_checkout_waits(200)
        vouchers = """<button id=voucher-section>관람권</button>
          <button onclick="window.voucherClicks+=1">IMAX 영화관람권 A</button>
          <button onclick="window.voucherClicks+=1;document.body.insertAdjacentHTML('beforeend',
            '<div role=alertdialog><p>추가 확인이 필요합니다</p><button>확인</button></div>')">
            IMAX 영화관람권 B</button>
          <button onclick="window.applyClicks+=1">적용</button>""".replace("`", "\\`")
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend',window.vouchers)">30,000원 결제하기</button>""",
            f"window.voucherClicks=0;window.applyClicks=0;window.vouchers=`{vouchers}`;",
        )

        with self.assertRaises(CheckoutError):
            self.flow.open_payment_and_apply_vouchers()

        self.assertEqual(self.page.evaluate("() => window.voucherClicks"), 2)
        self.assertEqual(self.page.evaluate("() => window.applyClicks"), 0)
        self._assert_no_final_submit()

    def test_unknown_modal_appearing_after_proof_blocks_final_submit(self):
        self.flow.prove_ready(self.match)
        self.page.evaluate(
            """() => document.body.insertAdjacentHTML('beforeend',
              '<div role="alertdialog"><p>추가 확인이 필요합니다</p><button>확인</button></div>')"""
        )

        with self.assertRaises(UnknownAfterSubmit):
            self.flow.submit_once()

        self.assertIsNone(self.page.evaluate("() => window.clicked"))

    def test_missing_voucher_options_after_section_open_is_payment_blocked(self):
        self._cap_checkout_waits(200)
        self._set_payment_content(
            """<button id=order onclick="window.orderClicks+=1;
              document.body.insertAdjacentHTML('beforeend','<button id=voucher-section>관람권</button>')">
              30,000원 결제하기</button>"""
        )

        with self.assertRaises(PaymentBlocked):
            self.flow.open_payment_and_apply_vouchers()

        self._assert_no_final_submit()


if __name__ == "__main__":
    unittest.main()
