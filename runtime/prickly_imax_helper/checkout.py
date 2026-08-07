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


class TicketCheckUnavailable(CheckoutError):
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
        try:
            page.wait_for_function(
                r"""() => {
                  const compact = value => (value || '').replace(/\s+/g, ' ').trim();
                  const visible = element => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
                  const hasCount = [...document.querySelectorAll('button')]
                    .filter(visible)
                    .some(element => /^시네마\s+\d+/.test(compact(element.innerText)));
                  const hasEmpty = [...document.querySelectorAll('p,li,div')]
                    .filter(element => visible(element) && !element.children.length)
                    .some(element => compact(element.textContent) === '예매하신 모바일 티켓이 없습니다.');
                  return hasCount || hasEmpty;
                }""",
                timeout=10_000,
            )
        except Exception:
            # The snapshot below remains fail-closed if CGV never renders either
            # authoritative state within the bounded wait.
            pass
        result = page.evaluate(
            r"""() => {
              const compact = value => (value || '').replace(/\s+/g, ' ').trim();
              const visible = element => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
              const text = compact(document.body.innerText);
              const button = [...document.querySelectorAll('button')]
                .filter(visible)
                .find(element => compact(element.innerText).startsWith('시네마 '));
              const match = button?.innerText.match(/시네마\s+(\d+)/);
              const count = match ? Number(match[1]) : -1;
              const emptyMessages = new Set([
                '예매하신 모바일 티켓이 없습니다.',
                '예매하신 모바일 티켓이 없습니다',
              ]);
              const empty = [...document.querySelectorAll('p,li,div')]
                .filter(element => visible(element) && !element.children.length)
                .some(element => emptyMessages.has(compact(element.textContent)));
              return {count, empty, text};
            }"""
        )
        count = int(result.get("count", -1))
        empty = result.get("empty") is True
        if count > 0 and empty:
            raise TicketCheckUnavailable("mobile ticket page presented conflicting ticket state")
        if count == 0 or empty:
            return ""
        if count > 0:
            return str(result.get("text", ""))
        raise TicketCheckUnavailable("mobile ticket list structure could not be verified")

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

    def _booking_page_state(self, theater: str, format_name: str) -> dict[str, bool]:
        return self.page.evaluate(
            r"""target => {
              const compact = value => (value || '').replace(/\s+/g, ' ').trim();
              const visible = element => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
              const picker = [...document.querySelectorAll('input')]
                .some(element => visible(element) && element.placeholder === '지역을 입력해주세요');
              const theaterVisible = [...document.querySelectorAll('button,[role="button"]')]
                .some(element => visible(element) && compact(element.textContent) === target.theater);
              const schedules = [...document.querySelectorAll('button')]
                .some(element => visible(element) && /\d{2}:\d{2}-\d{2}:\d{2}/.test(compact(element.textContent)));
              const formatVisible = compact(document.body.innerText)
                .toLocaleLowerCase()
                .includes(target.formatName.toLocaleLowerCase());
              return {picker, target_ready: !picker && theaterVisible && schedules && formatVisible};
            }""",
            {"theater": theater, "formatName": format_name},
        )

    def _wait_for_booking_page_state(
        self, theater: str, format_name: str, *, timeout_ms: int = 10_000
    ) -> dict[str, bool]:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            state = self._booking_page_state(theater, format_name)
            if state["picker"] or state["target_ready"]:
                return state
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                return state
            self.page.wait_for_timeout(min(100, remaining_ms))

    def _open_theater_picker(self) -> bool:
        return bool(
            self.page.evaluate(
                r"""() => {
                  const compact = value => (value || '').replace(/\s+/g, ' ').trim();
                  const visible = element => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
                  const buttons = [...document.querySelectorAll('button')]
                    .filter(element => visible(element) && !element.disabled);
                  const legacy = buttons.find(element =>
                    compact(element.querySelector('.voice-only')?.textContent) === '자주가는 CGV 목록 수정');
                  const exact = buttons.find(element => compact(element.innerText) === '극장 선택');
                  const semantic = buttons.find(element => {
                    const label = compact(element.getAttribute('aria-label') || element.getAttribute('title'));
                    return label.includes('극장') && (label.includes('선택') || label.includes('수정'));
                  });
                  const launcher = legacy || exact || semantic;
                  if (!launcher) return false;
                  launcher.click();
                  return true;
                }"""
            )
        )

    def _select_theater_from_picker(self, theater: str, format_name: str) -> None:
        search = self.page.locator('input[placeholder="지역을 입력해주세요"]:visible')
        search.fill(theater)
        exact = self.page.get_by_role("button", name=theater, exact=True)
        self._wait(
            "theater => [...document.querySelectorAll('button')].some(b => "
            "b.offsetParent && !b.disabled && b.textContent.trim() === theater)",
            20_000,
            theater,
        )
        if exact.count() > 1:
            exact.nth(exact.count() - 1).click()
            self._wait(
                "theater => [...document.querySelectorAll('button')].filter(b => "
                "b.offsetParent && !b.disabled && b.textContent.trim() === theater).length === 1",
                10_000,
                theater,
            )
        if exact.count() != 1:
            raise CheckoutError(f"actual theater row not found: {theater}")
        exact.first.click()
        self._wait(
            "() => [...document.querySelectorAll('button')].some(b => "
            "b.offsetParent && !b.disabled && b.textContent.trim() === '극장선택')"
        )
        self.page.get_by_role("button", name="극장선택", exact=True).click()
        ready = self._wait_for_booking_page_state(theater, format_name, timeout_ms=20_000)
        if not ready["target_ready"]:
            raise CheckoutError(f"configured theater did not become ready: {theater}")

    def open_movie_and_theater(self) -> None:
        movie = str(self.config["movie"])
        theater = str(self.config["theater"])
        format_name = str(self.config["format"])
        self.page.goto(CGV_BOOKING_URL, wait_until="domcontentloaded")
        self._wait("movie => [...document.images].some(i => i.alt.trim() === movie)", 30_000, movie)
        clicked = self.page.evaluate(
            r"""movie => { const image = [...document.images].find(i => i.alt.trim() === movie);
            const button = image?.closest('button'); if (!button) return false; button.click(); return true; }""",
            movie,
        )
        if not clicked:
            raise CheckoutError(f"movie button not found: {movie}")
        self._wait("() => location.pathname === '/cnm/movieBook/movie'")
        ready = self._wait_for_booking_page_state(theater, format_name)
        if ready["target_ready"]:
            return
        if not ready["picker"]:
            if not self._open_theater_picker():
                raise CheckoutError("theater picker launcher not found")
        self._wait("() => !![...document.querySelectorAll('input')].find(x => x.offsetParent && x.placeholder === '지역을 입력해주세요')")
        self._select_theater_from_picker(theater, format_name)

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
