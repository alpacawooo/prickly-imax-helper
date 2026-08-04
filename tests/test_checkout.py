from __future__ import annotations

import unittest

from prickly_imax_helper.checkout import duplicate_status, payment_proof


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


class DuplicateTests(unittest.TestCase):
    MATCH = {"date": "2026-08-13", "time": "24:00"}

    def test_exact_movie_date_and_time_is_duplicate(self):
        self.assertEqual(duplicate_status("오디세이 08.13 24:00", self.MATCH, "오디세이"), "duplicate")

    def test_different_movie_is_clear(self):
        self.assertEqual(duplicate_status("다른 영화 08.13 24:00", self.MATCH, "오디세이"), "clear")

    def test_same_movie_without_provable_show_is_uncertain(self):
        self.assertEqual(duplicate_status("오디세이 예매 내역", self.MATCH, "오디세이"), "uncertain")


if __name__ == "__main__":
    unittest.main()
