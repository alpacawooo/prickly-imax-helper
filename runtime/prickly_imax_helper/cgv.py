from __future__ import annotations

import contextlib
import json
import urllib.parse
from dataclasses import dataclass
from typing import Any, Iterator

from .browser import CGV_BOOKING_URL, browser_info
from .locks import locked_file
from .paths import RuntimePaths
from .request_budget import RequestBudget


SITE_NO = "0013"
MOVIE_NO = "30001323"
COMPANY_CODE = "A420"


class CgvError(RuntimeError):
    pass


class LoginRequired(CgvError):
    pass


class RateLimited(CgvError):
    def __init__(self, message: str, *, cooldown_seconds: float) -> None:
        super().__init__(message)
        self.cooldown_seconds = cooldown_seconds


@dataclass
class CgvSession:
    paths: RuntimePaths
    minimum_interval_seconds: float = 1.0
    cooldown_seconds: float = 300.0
    company_code: str = COMPANY_CODE
    site_no: str = SITE_NO
    movie_no: str = MOVIE_NO

    def __post_init__(self) -> None:
        self.budget = RequestBudget(self.paths.root, minimum_interval_seconds=self.minimum_interval_seconds)
        self._playwright = None
        self.browser = None
        self.page = None

    @contextlib.contextmanager
    def locked(self) -> Iterator["CgvSession"]:
        self.paths.prepare()
        lock_path = self.paths.state_dir / "browser.lock"
        with locked_file(lock_path):
            try:
                self.connect()
                yield self
            finally:
                self.disconnect()

    def connect(self) -> None:
        info = browser_info(self.paths)
        if not info:
            raise CgvError("dedicated Chrome is not running")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise CgvError("Playwright is not installed") from exc
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{int(info['port'])}")
        context = self.browser.contexts[0]
        pages = [page for page in context.pages if "cgv.co.kr" in page.url]
        self.page = pages[-1] if pages else context.new_page()
        if not pages:
            self.page.goto(CGV_BOOKING_URL, wait_until="domcontentloaded")

    def disconnect(self) -> None:
        # Do not call browser.close(): this is a persistent user Chrome reached
        # over CDP, not a Playwright-owned disposable browser process.
        if self._playwright is not None:
            self._playwright.stop()
        self.browser = None
        self.page = None
        self._playwright = None

    def is_logged_in(self) -> bool:
        if self.page is None:
            raise CgvError("browser is not connected")
        return bool(
            self.page.evaluate(
                """() => document.cookie.split(';').some(c => c.trim().startsWith('accessToken=')) ||
                [...document.querySelectorAll('button')].some(b => b.innerText.trim() === '로그아웃')"""
            )
        )

    def require_login(self) -> None:
        if not self.is_logged_in():
            raise LoginRequired("CGV login is required in the dedicated Chrome profile")

    def api_get(self, path: str) -> Any:
        if self.page is None:
            raise CgvError("browser is not connected")
        self.budget.acquire()
        result = self.page.evaluate(
            """async path => {
              const response = await fetch(path, {credentials: 'include'});
              const text = await response.text();
              return {status: response.status, retryAfter: response.headers.get('Retry-After'), text};
            }""",
            path,
        )
        if int(result["status"]) == 429:
            try:
                cooldown = max(self.cooldown_seconds, float(result.get("retryAfter") or 0))
            except ValueError:
                cooldown = self.cooldown_seconds
            self.budget.defer(cooldown)
            raise RateLimited(f"CGV returned HTTP 429; cooldown {cooldown:.0f}s", cooldown_seconds=cooldown)
        if int(result["status"]) in {401, 403}:
            raise LoginRequired(f"CGV returned HTTP {result['status']}; login or session verification is required")
        try:
            payload = json.loads(result["text"])
        except json.JSONDecodeError as exc:
            raise CgvError(f"CGV returned non-JSON HTTP {result['status']}") from exc
        if int(result["status"]) != 200 or payload.get("statusCode") != 0:
            raise CgvError(f"CGV API failed with HTTP {result['status']} statusCode={payload.get('statusCode')}")
        return payload.get("data")

    def open_dates(self) -> list[str]:
        data = self.api_get(
            f"/api/v1/booking/searchSiteScnscYmdListByMov?coCd={self.company_code}&siteNo={self.site_no}&movNo={self.movie_no}"
        )
        return [str(item["scnYmd"]) for item in data]

    def schedules(self, ymd: str) -> list[dict[str, Any]]:
        return self.api_get(
            f"/api/v1/booking/searchSchByMov?coCd={self.company_code}&siteNo={self.site_no}&movNo={self.movie_no}"
            f"&scnYmd={ymd}&rtctlScopCd=01"
        )

    def seats(self, ymd: str, screen_no: str, sequence: str) -> dict[str, list[str]]:
        data = self.api_get(
            f"/api/v1/booking/searchIfSeatData?coCd={self.company_code}&siteNo={self.site_no}&scnYmd={ymd}"
            f"&scnsNo={screen_no}&scnSseq={sequence}"
        )
        seats = [seat for item in (data or {}).get("items", []) for seat in item.get("seats", [])]
        labels = [f"{seat['seatRowNm']}{seat['seatNo']}" for seat in seats]
        available = [f"{seat['seatRowNm']}{seat['seatNo']}" for seat in seats if seat.get("seatSaleYn") == "Y"]
        return {"all": labels, "available": available}

    def booking_target_from_page(self) -> dict[str, str]:
        if self.page is None:
            raise CgvError("browser is not connected")
        urls = self.page.evaluate(
            """() => performance.getEntriesByType('resource').map(entry => entry.name).reverse()"""
        )
        for raw in urls:
            parsed = urllib.parse.urlparse(str(raw))
            if not parsed.path.endswith("/api/v1/booking/searchSchByMov"):
                continue
            query = urllib.parse.parse_qs(parsed.query)
            target = {
                "company_code": query.get("coCd", [""])[0],
                "site_no": query.get("siteNo", [""])[0],
                "movie_no": query.get("movNo", [""])[0],
            }
            if all(target.values()):
                return target
        raise CgvError("could not resolve CGV target identifiers from the selected booking page")
