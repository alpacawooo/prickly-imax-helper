from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from .browser import CGV_BOOKING_URL


MOBILE_TICKETS_URL = "https://cgv.co.kr/mcv/mobileTicketList"
KOREAN_WEEKDAYS = "월화수목금토일"


class CheckoutError(RuntimeError):
    pass


class DuplicateBlocked(CheckoutError):
    pass


class PaymentBlocked(CheckoutError):
    pass


class SeatVanished(CheckoutError):
    pass


class UnknownAfterSubmit(CheckoutError):
    pass


def _contains_seat(text: str, seat: str) -> bool:
    return re.search(rf"(?<![A-Z0-9]){re.escape(seat)}(?![0-9])", text) is not None


def duplicate_status(text: str, match: dict[str, Any], movie: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if movie not in normalized:
        return "clear"
    year, month, day = map(int, match["date"].split("-"))
    date_forms = {
        match["date"],
        f"{year}.{month:02d}.{day:02d}",
        f"{month:02d}.{day:02d}",
        f"{month}.{day}",
        f"{month}월 {day}일",
    }
    date_match = any(value in normalized for value in date_forms)
    time_match = match["time"] in normalized
    if date_match and time_match:
        return "duplicate"
    return "uncertain"


def payment_proof(text: str, *, voucher_count: int, selected_voucher_count: int, seats: list[str]) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    errors = []
    for seat in seats:
        if not _contains_seat(normalized, seat):
            errors.append(f"selected seat not proven: {seat}")
    voucher_pattern = rf"IMAX\s*영화관람권\s*(?:x|X|×)?\s*{voucher_count}(?:\b|매)"
    if selected_voucher_count != voucher_count or not re.search(voucher_pattern, normalized):
        errors.append(f"exactly {voucher_count} IMAX vouchers not proven")
    zero_patterns = (
        r"(?:최종\s*)?(?:남은\s*)?결제\s*금액\s*0\s*원",
        r"총\s*결제\s*금액\s*0\s*원",
    )
    if not any(re.search(pattern, normalized) for pattern in zero_patterns):
        errors.append("zero remaining balance not proven")
    return errors


def mobile_ticket_proof(text: str, match: dict[str, Any], config: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    normalized = re.sub(r"\s+", " ", text).strip()
    errors = []
    exact_show = duplicate_status(normalized, match, str(config["movie"])) == "duplicate"
    if not exact_show:
        errors.append("exact movie date and time not proven")
    theater = str(config["theater"])
    theater_proven = theater in normalized
    if not theater_proven:
        errors.append("theater not proven")
    format_name = str(config["format"])
    format_proven = format_name in normalized
    if not format_proven:
        errors.append("format not proven")
    seats = [str(seat) for seat in match["seats"]]
    missing_seats = [seat for seat in seats if not _contains_seat(normalized, seat)]
    if missing_seats:
        errors.append("selected seats not proven: " + ", ".join(missing_seats))
    proof = {
        "exact_show": exact_show,
        "theater": theater_proven,
        "format": format_proven,
        "seats": seats if not missing_seats else [],
    }
    return errors, proof


@dataclass
class CheckoutResult:
    status: str
    proof: dict[str, Any]


class CheckoutFlow:
    def __init__(self, page: Any, config: dict[str, Any]) -> None:
        self.page = page
        self.config = config
        self.submitted = False

    def _wait(self, expression: str, timeout_ms: int = 20_000, arg: Any = None) -> None:
        self.page.wait_for_function(expression, arg=arg, timeout=timeout_ms)

    def _ticket_text(self, page: Any) -> str:
        page.goto(MOBILE_TICKETS_URL, wait_until="domcontentloaded")
        page.wait_for_function("() => location.pathname === '/mcv/mobileTicketList'", timeout=20_000)
        result = page.evaluate(
            r"""() => {
              const text = document.body.innerText.replace(/\s+/g, ' ').trim();
              const button = [...document.querySelectorAll('button')].find(x => x.innerText.trim().startsWith('시네마 '));
              const match = button?.innerText.match(/시네마\s+(\d+)/);
              return {count: match ? Number(match[1]) : -1, text};
            }"""
        )
        count = int(result.get("count", -1))
        if count < 0:
            raise DuplicateBlocked("mobile ticket count could not be verified")
        return "" if count == 0 else str(result.get("text", ""))

    def ensure_no_existing_ticket(self, match: dict[str, Any], *, separate_tab: bool = False) -> None:
        if separate_tab:
            tab = self.page.context.new_page()
            try:
                text = self._ticket_text(tab)
            finally:
                tab.close()
        else:
            text = self._ticket_text(self.page)
        if not text:
            return
        status = duplicate_status(text, match, str(self.config["movie"]))
        if status != "clear":
            raise DuplicateBlocked(f"existing matching ticket status is {status}")

    def open_movie_and_theater(self) -> None:
        self.page.goto(CGV_BOOKING_URL, wait_until="domcontentloaded")
        self._wait("() => [...document.images].some(i => i.alt === '오디세이')", 30_000)
        clicked = self.page.evaluate(
            r"""() => { const image = [...document.images].find(i => i.alt === '오디세이');
            const button = image?.closest('button'); if (!button) return false; button.click(); return true; }"""
        )
        if not clicked:
            raise CheckoutError("Odyssey movie button not found")
        self._wait("() => location.pathname === '/cnm/movieBook/movie'")
        ready = self.page.evaluate(
            r"""() => ({
              picker: !![...document.querySelectorAll('input')].find(x => x.offsetParent && x.placeholder === '지역을 입력해주세요'),
              schedules: [...document.querySelectorAll('button')].some(b => /\d{2}:\d{2}-\d{2}:\d{2}/.test(b.textContent)),
              yongsan: [...document.querySelectorAll('button')].some(b => b.textContent.trim() === '용산아이파크몰')
            })"""
        )
        if ready["schedules"] and ready["yongsan"]:
            return
        if not ready["picker"]:
            opened = self.page.evaluate(
                r"""() => { const b = [...document.querySelectorAll('button')].find(x =>
                x.querySelector('.voice-only')?.textContent.trim() === '자주가는 CGV 목록 수정' && x.offsetParent);
                if (!b) return false; b.click(); return true; }"""
            )
            if not opened:
                raise CheckoutError("theater picker launcher not found")
        self._wait("() => !![...document.querySelectorAll('input')].find(x => x.offsetParent && x.placeholder === '지역을 입력해주세요')")
        self.page.locator('input[placeholder="지역을 입력해주세요"]:visible').fill("용산")
        self._wait("() => [...document.querySelectorAll('button')].some(b => b.offsetParent && b.textContent.trim() === '용산아이파크몰')")
        selected = self.page.evaluate(
            r"""() => { const values = [...document.querySelectorAll('button')].filter(b =>
            b.offsetParent && !b.disabled && b.textContent.trim() === '용산아이파크몰');
            if (!values.length) return false; values[values.length - 1].click(); return true; }"""
        )
        if not selected:
            raise CheckoutError("actual Yongsan theater row not found")
        self._wait("() => [...document.querySelectorAll('button')].some(b => b.offsetParent && !b.disabled && b.textContent.trim() === '극장선택')")
        self.page.get_by_role("button", name="극장선택", exact=True).click()
        self._wait("() => [...document.querySelectorAll('h3')].some(h => h.innerText.includes('IMAX관'))")

    def open_match(self, match: dict[str, Any]) -> None:
        year, month, day = map(int, match["date"].split("-"))
        import datetime as dt

        weekday = KOREAN_WEEKDAYS[dt.date(year, month, day).weekday()]
        clicked = self.page.evaluate(
            r"""target => { const buttons = [...document.querySelectorAll('button')].filter(b =>
            b.offsetParent && !b.disabled && b.querySelector('[class*=dayScroll_txt]') && b.querySelector('[class*=dayScroll_number]'));
            const button = buttons.find(x => x.querySelector('[class*=dayScroll_txt]').textContent.trim() === target.weekday &&
            x.querySelector('[class*=dayScroll_number]').textContent.trim() === target.day);
            if (!button) return false; button.click(); return true; }""",
            {"weekday": weekday, "day": f"{day:02d}"},
        )
        if not clicked:
            raise SeatVanished("target date is no longer open")
        self._wait(
            r"""target => [...document.querySelectorAll('button')].some(b => b.offsetParent && !b.disabled &&
            b.textContent.replace(/\s+/g, ' ').trim().startsWith(target + '-'))""",
            15_000,
            match["time"],
        )
        clicked = self.page.evaluate(
            r"""start => { const b = [...document.querySelectorAll('button')].find(x => x.offsetParent && !x.disabled &&
            x.textContent.replace(/\s+/g, ' ').trim().startsWith(start + '-') && /\d+\s*\/\s*\d+석/.test(x.textContent));
            if (!b) return false; b.click(); return true; }""",
            match["time"],
        )
        if not clicked:
            raise SeatVanished("target showtime disappeared")
        self._wait("() => location.pathname === '/cnm/selectVisitorCnt'")

    def select_party_and_seats(self, match: dict[str, Any]) -> None:
        party = int(self.config["party_size"])
        selected = self.page.evaluate(
            r"""party => { const groups = [...document.querySelectorAll('[role=group]')].filter(g =>
            g.offsetParent && [...g.children].some(c => c.textContent.trim() === '일반'));
            const b = groups[0]?.querySelector(`button[aria-label="${party} 선택"]`);
            if (!b) return false; if (b.getAttribute('aria-pressed') !== 'true') b.click(); return true; }""",
            party,
        )
        if not selected:
            raise CheckoutError("general admission count control not found")
        seats = match["seats"]
        result = self.page.evaluate(
            r"""wanted => { const found = []; for (const seat of wanted) {
            const b = [...document.querySelectorAll('button[data-seatlocno]')].find(x =>
            x.textContent.trim() === seat && !x.disabled && x.offsetParent); if (!b) return {ok:false, missing:seat}; found.push(b); }
            for (const b of found) if (!String(b.className).includes('seatSelected')) b.click();
            return {ok:true, count:found.length}; }""",
            seats,
        )
        if not result.get("ok") or int(result.get("count", 0)) != party:
            raise SeatVanished(f"target seat vanished: {result.get('missing')}")

    def open_payment_and_apply_vouchers(self) -> None:
        clicked = self.page.evaluate(
            r"""() => { const buttons = [...document.querySelectorAll('button')].filter(b => b.offsetParent && !b.disabled);
            const b = buttons.find(x => /원\s*결제하기$/.test(x.textContent.replace(/\s+/g, ' ').trim()));
            if (!b) return false; b.click(); return true; }"""
        )
        if not clicked:
            raise CheckoutError("seat order button not available")
        self._wait("() => [...document.querySelectorAll('button')].some(b => b.offsetParent && /관람권|기프트콘/.test(b.textContent))")
        opened = self.page.evaluate(
            r"""() => { const b = [...document.querySelectorAll('button')].find(x =>
            x.offsetParent && !x.disabled && /관람권|기프트콘/.test(x.textContent)); if (!b) return false; b.click(); return true; }"""
        )
        if not opened:
            raise PaymentBlocked("voucher section not found")
        self._wait("() => document.body.innerText.includes('IMAX 영화관람권')")
        count = int(self.config["payment"]["voucher_count"])
        selected = self.page.evaluate(
            r"""count => { const candidates = [...document.querySelectorAll('button,label')].filter(x =>
            x.offsetParent && x.textContent.includes('IMAX 영화관람권'));
            const unique = []; for (const x of candidates) if (!unique.some(y => y.contains(x) || x.contains(y))) unique.push(x);
            if (unique.length < count) return {ok:false, available:unique.length}; unique.slice(0, count).forEach(x => x.click());
            return {ok:true, selected:count}; }""",
            count,
        )
        if not selected.get("ok"):
            raise PaymentBlocked(f"only {selected.get('available', 0)} IMAX vouchers are visible")
        self.page.evaluate(
            r"""() => { const b = [...document.querySelectorAll('button')].find(x =>
            x.offsetParent && !x.disabled && x.textContent.includes('적용')); if (b) b.click(); }"""
        )
        time.sleep(0.4)

    def prove_ready(self, match: dict[str, Any]) -> None:
        snapshot = self.page.evaluate(
            r"""() => { const marked = [...document.querySelectorAll('input:checked,[aria-checked="true"],[aria-selected="true"]')]
            .filter(x => (x.closest('label,button,li,div')?.textContent || '').includes('IMAX 영화관람권'));
            return {text: document.body.innerText, selectedVoucherCount: marked.length, buttons: [...document.querySelectorAll('button')]
            .filter(b => b.offsetParent && !b.disabled && b.textContent.includes('결제하기'))
            .map(b => b.textContent.replace(/\s+/g, ' ').trim())}; }"""
        )
        errors = payment_proof(
            snapshot["text"],
            voucher_count=int(self.config["payment"]["voucher_count"]),
            selected_voucher_count=int(snapshot.get("selectedVoucherCount", 0)),
            seats=match["seats"],
        )
        if errors:
            raise PaymentBlocked("; ".join(errors))
        if len(snapshot["buttons"]) != 1:
            raise PaymentBlocked(f"expected one final purchase button, found {len(snapshot['buttons'])}")

    def submit_once(self) -> None:
        if self.submitted:
            raise UnknownAfterSubmit("submission was already attempted")
        clicked = self.page.evaluate(
            r"""() => { const buttons = [...document.querySelectorAll('button')].filter(b =>
            b.offsetParent && !b.disabled && b.textContent.includes('결제하기'));
            if (buttons.length !== 1) return false; buttons[0].click(); return true; }"""
        )
        if not clicked:
            raise UnknownAfterSubmit("submission state entered but final click could not be proven")
        self.submitted = True

    def prove_and_submit_once(self, match: dict[str, Any]) -> None:
        self.prove_ready(match)
        self.submit_once()

    def verify_mobile_ticket(self, match: dict[str, Any]) -> CheckoutResult:
        if not self.submitted:
            raise CheckoutError("submission has not occurred")
        try:
            self.page.wait_for_function(
                "() => /예매.*완료|결제.*완료|예매번호/.test(document.body.innerText)",
                timeout=30_000,
            )
            self.page.goto(MOBILE_TICKETS_URL, wait_until="domcontentloaded")
            self._wait("() => location.pathname === '/mcv/mobileTicketList'")
            proof = self.page.evaluate(
                r"""() => { const text = document.body.innerText.replace(/\s+/g, ' ').trim();
                const b = [...document.querySelectorAll('button')].find(x => x.innerText.trim().startsWith('시네마 '));
                const m = b?.innerText.match(/시네마\s+(\d+)/); return {count:m ? Number(m[1]) : -1, text}; }"""
            )
            errors, exact_proof = mobile_ticket_proof(str(proof.get("text", "")), match, self.config)
            if int(proof.get("count", -1)) < 1:
                errors.append("mobile ticket count missing")
            if errors:
                raise RuntimeError("; ".join(errors))
            return CheckoutResult("completed", {"count": int(proof["count"]), **exact_proof})
        except Exception as exc:
            raise UnknownAfterSubmit(f"final click occurred but ticket proof failed: {exc}") from exc
