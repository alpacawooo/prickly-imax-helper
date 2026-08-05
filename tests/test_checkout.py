from __future__ import annotations

import unittest

from prickly_imax_helper.checkout import (
    CheckoutFlow,
    TicketCheckUnavailable,
    duplicate_status,
    mobile_ticket_proof,
    payment_proof,
)
from prickly_imax_helper.presets import odyssey


class PaymentProofTests(unittest.TestCase):
    def test_exact_vouchers_zero_balance_and_seats_pass(self):
        text = "선택 좌석 H15 H16 IMAX 영화관람권 2매 최종 결제 금액 0원"
        self.assertEqual(
            payment_proof(text, voucher_count=2, selected_voucher_count=2, seats=["H15", "H16"]),
            [],
        )

    def test_visible_but_unselected_vouchers_do_not_pass(self):
        text = "H15 H16 IMAX 영화관람권 IMAX 영화관람권 최종 결제 금액 0원"
        errors = payment_proof(text, voucher_count=2, selected_voucher_count=0, seats=["H15", "H16"])
        self.assertTrue(any("vouchers" in error for error in errors))

    def test_positive_or_missing_balance_does_not_pass(self):
        text = "H15 H16 IMAX 영화관람권 2매 최종 결제 금액 1000원"
        errors = payment_proof(text, voucher_count=2, selected_voucher_count=2, seats=["H15", "H16"])
        self.assertTrue(any("zero" in error for error in errors))

    def test_every_requested_seat_must_be_proven(self):
        text = "H15 IMAX 영화관람권 2매 결제 금액 0원"
        errors = payment_proof(text, voucher_count=2, selected_voucher_count=2, seats=["H15", "H16"])
        self.assertTrue(any("H16" in error for error in errors))

    def test_short_seat_number_does_not_match_longer_seat_number(self):
        text = "H10 H2 IMAX 영화관람권 2매 결제 금액 0원"
        errors = payment_proof(text, voucher_count=2, selected_voucher_count=2, seats=["H1", "H2"])
        self.assertTrue(any("H1" in error for error in errors))


class DuplicateTests(unittest.TestCase):
    MATCH = {"date": "2026-08-13", "time": "24:00"}

    def test_exact_movie_date_and_time_is_duplicate(self):
        self.assertEqual(duplicate_status("오디세이 08.13 24:00", self.MATCH, "오디세이"), "duplicate")

    def test_different_movie_is_clear(self):
        self.assertEqual(duplicate_status("다른 영화 08.13 24:00", self.MATCH, "오디세이"), "clear")

    def test_same_movie_without_provable_show_is_uncertain(self):
        self.assertEqual(duplicate_status("오디세이 예매 내역", self.MATCH, "오디세이"), "uncertain")


class MobileTicketListTests(unittest.TestCase):
    class Page:
        def __init__(self, result):
            self.result = result

        def goto(self, *_args, **_kwargs):
            return None

        def wait_for_function(self, *_args, **_kwargs):
            return None

        def evaluate(self, *_args, **_kwargs):
            return self.result

    def setUp(self):
        self.flow = CheckoutFlow(object(), odyssey())

    def test_current_cgv_empty_state_is_authoritative(self):
        page = self.Page({"count": -1, "empty": True, "text": "예매하신 모바일 티켓이 없습니다."})
        self.assertEqual(self.flow._ticket_text(page), "")

    def test_legacy_zero_count_is_still_authoritative(self):
        page = self.Page({"count": 0, "empty": False, "text": "시네마 0"})
        self.assertEqual(self.flow._ticket_text(page), "")

    def test_positive_count_returns_ticket_text_for_duplicate_analysis(self):
        page = self.Page({"count": 1, "empty": False, "text": "시네마 1 오디세이 08.13 20:30"})
        self.assertIn("오디세이", self.flow._ticket_text(page))

    def test_ambiguous_page_fails_closed_without_claiming_a_duplicate(self):
        page = self.Page({"count": -1, "empty": False, "text": "모바일 티켓"})
        with self.assertRaises(TicketCheckUnavailable):
            self.flow._ticket_text(page)

    def test_conflicting_positive_and_empty_state_fails_closed(self):
        page = self.Page({"count": 1, "empty": True, "text": "시네마 1 예매하신 모바일 티켓이 없습니다."})
        with self.assertRaises(TicketCheckUnavailable):
            self.flow._ticket_text(page)


class MobileTicketProofTests(unittest.TestCase):
    def setUp(self):
        self.config = odyssey()
        self.match = {"date": "2026-08-07", "time": "19:30", "seats": ["G12", "G13"]}

    def test_exact_show_theater_format_and_seats_are_required(self):
        errors, proof = mobile_ticket_proof(
            "오디세이 2026.08.07 19:30 용산아이파크몰 IMAX G12 G13",
            self.match,
            self.config,
        )
        self.assertEqual(errors, [])
        self.assertTrue(proof["exact_show"])
        self.assertEqual(proof["seats"], ["G12", "G13"])

    def test_different_odyssey_ticket_cannot_prove_completion(self):
        errors, proof = mobile_ticket_proof(
            "오디세이 2026.08.08 10:00 용산아이파크몰 IMAX G12 G13",
            self.match,
            self.config,
        )
        self.assertIn("exact movie date and time not proven", errors)
        self.assertFalse(proof["exact_show"])

    def test_missing_one_selected_seat_blocks_completion(self):
        errors, proof = mobile_ticket_proof(
            "오디세이 2026.08.07 19:30 용산아이파크몰 IMAX G12",
            self.match,
            self.config,
        )
        self.assertTrue(any("G13" in error for error in errors))
        self.assertEqual(proof["seats"], [])


if __name__ == "__main__":
    unittest.main()
