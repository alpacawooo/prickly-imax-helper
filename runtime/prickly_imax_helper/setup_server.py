from __future__ import annotations

import html
import secrets
import threading
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .browser import BrowserError, launch_browser
from .cgv import CgvError, CgvSession
from .checkout import CheckoutError, CheckoutFlow
from .config import ConfigError, SUPPORTED_NOTIFICATION_PROVIDERS, valid_email_address, validate_config, write_config
from .notify import notification_label, notification_method, send_email
from .paths import RuntimePaths
from .presets import odyssey
from .state import Status, transition


PAGE = """<!doctype html><html lang=\"ko\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>Prickly IMAX Helper</title>
<style>body{font-family:-apple-system,sans-serif;max-width:820px;margin:48px auto;padding:0 20px;color:#171717}fieldset{border:1px solid #ddd;border-radius:12px;padding:18px;margin:18px 0}label{display:block;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.three{grid-template-columns:repeat(3,minmax(0,1fr))}input,select{padding:9px;width:100%;box-sizing:border-box}button{padding:12px 18px;border:0;border-radius:9px;background:#111;color:white;font-weight:650}.secondary{background:#eee;color:#111}.warning{background:#fff7ed;padding:14px;border-radius:9px}.hint{color:#555;font-size:14px}@media(max-width:640px){.grid,.three{grid-template-columns:1fr}}</style>
<h1>Prickly IMAX Helper 설정</h1><p>비밀번호와 관람권 번호는 입력하지 않습니다. CGV 로그인은 전용 Chrome 창에서 직접 하세요.</p>
<form method=post action=\"/action\"><input type=hidden name=token value=\"__TOKEN__\">
<fieldset><legend>1. CGV 로그인</legend><button class=secondary name=action value=login formnovalidate>전용 Chrome 열기</button><p>__MESSAGE__</p></fieldset>
<fieldset><legend>2. 감시 조건</legend><p class=hint>아래 값은 직장인용 오디세이·용산 IMAX 기본값입니다. 본인 조건에 맞게 바꿀 수 있습니다.</p>
<div class=\"grid three\"><label>영화<input required name=movie maxlength=100 value=\"__MOVIE__\"></label><label>CGV 극장<input required name=theater maxlength=100 value=\"__THEATER__\"></label><label>상영 형식<input required name=screen_format maxlength=100 value=\"__FORMAT__\"></label></div>
<p class=hint>현재 자동 결제는 등록된 IMAX 관람권만 지원하므로 상영 형식은 IMAX가 포함된 형식으로 설정합니다.</p>
<div class=\"grid three\"><label>평일 시작 하한<input name=weekday_after pattern=\"(?:[01]\\d|2\\d):[0-5]\\d\" placeholder=\"제한 없음\" value=\"__WEEKDAY_AFTER__\"></label><label>평일 시작 상한(미만)<input name=weekday_before pattern=\"(?:[01]\\d|2\\d):[0-5]\\d\" placeholder=\"제한 없음\" value=\"__WEEKDAY_BEFORE__\"></label><span></span>
<label>토요일 시작 하한<input name=saturday_after pattern=\"(?:[01]\\d|2\\d):[0-5]\\d\" placeholder=\"제한 없음\" value=\"__SATURDAY_AFTER__\"></label><label>토요일 시작 상한(미만)<input name=saturday_before pattern=\"(?:[01]\\d|2\\d):[0-5]\\d\" placeholder=\"제한 없음\" value=\"__SATURDAY_BEFORE__\"></label><span></span>
<label>일요일 시작 하한<input name=sunday_after pattern=\"(?:[01]\\d|2\\d):[0-5]\\d\" placeholder=\"제한 없음\" value=\"__SUNDAY_AFTER__\"></label><label>일요일 시작 상한(미만)<input name=sunday_before pattern=\"(?:[01]\\d|2\\d):[0-5]\\d\" placeholder=\"제한 없음\" value=\"__SUNDAY_BEFORE__\"></label><span></span></div>
<p class=hint>시간은 00:00~29:59 형식입니다. 빈칸은 해당 방향의 제한 없음입니다. 새로 열리는 예매 날짜는 계속 자동 포함됩니다.</p>
<div class=\"grid\"><label>같은 행 연속 좌석 수<input required type=number name=party_size min=1 max=8 value=\"__PARTY_SIZE__\"></label><label>허용 열(쉼표 또는 공백 구분)<input required name=rows value=\"__ROWS__\" placeholder=\"D,E,F,G,H,I,J\"></label><label>각 행 양끝 제외 비율(%)<input required type=number name=edge_percent min=0 max=49 step=1 value=\"__EDGE_PERCENT__\"></label><label>좌석 우선순위<select required name=preference><option value=\"closest_to_center\" __PREFERENCE_CENTER__>중앙에 가까운 연속 좌석 우선</option><option value=\"row_order_then_left\" __PREFERENCE_ROW__>입력한 열 순서, 왼쪽 번호 우선</option></select></label></div>
<label>알림을 받을 메일 서비스<select required name=email_provider><option value=\"\">선택하세요</option><option value=\"gmail\" __PROVIDER_GMAIL__>Gmail</option><option value=\"naver\" __PROVIDER_NAVER__>네이버 메일</option><option value=\"icloud\" __PROVIDER_ICLOUD__>iCloud Mail (Apple)</option><option value=\"other\" __PROVIDER_OTHER__>기타 메일</option></select></label>
<label>결과를 받을 이메일 주소<input required type=email name=email value=\"__EMAIL__\" autocomplete=email></label><p class=hint>받는 주소는 운영체제와 상관없이 선택할 수 있습니다. 발송은 Mac의 Apple Mail 또는 Windows의 Outlook 데스크톱을 로컬로 사용하며, 이메일 비밀번호나 앱 비밀번호는 Helper에 입력하지 않습니다.</p><p>설정 저장 시 선택한 주소로 __NOTIFIER__ 테스트 메일을 한 번 보냅니다.</p></fieldset>
<fieldset><legend>3. 자동 예매 사전동의</legend><div class=warning>설정한 인원수와 같은 수의 등록된 IMAX 관람권으로 결제 잔액이 0원일 때만 조건에 맞는 좌석을 한 번 자동 예매합니다. 기존 예매 취소·변경과 중복 제출은 하지 않습니다.</div>
<label><input style=\"width:auto\" required type=checkbox name=consent value=yes> 위 조건의 자동 좌석 선택과 1회 최종 제출에 동의합니다.</label>
<label><input style=\"width:auto\" required type=checkbox name=network value=yes> 같은 공인 IP를 사용하는 집·회사 네트워크에서 이 Helper를 한 대만 실행합니다.</label></fieldset>
<button name=action value=save>설정 저장</button></form></html>"""


def _default_form_values() -> dict[str, str]:
    config = odyssey()
    return {
        "movie": str(config["movie"]),
        "theater": str(config["theater"]),
        "screen_format": str(config["format"]),
        "weekday_after": str(config["time_rules"]["weekday"].get("at_or_after") or ""),
        "weekday_before": str(config["time_rules"]["weekday"].get("before") or ""),
        "saturday_after": "",
        "saturday_before": "",
        "sunday_after": str(config["time_rules"]["sunday"].get("at_or_after") or ""),
        "sunday_before": str(config["time_rules"]["sunday"].get("before") or ""),
        "party_size": str(config["party_size"]),
        "rows": ",".join(config["rows"]),
        "edge_percent": str(round(float(config["edge_exclusion"]) * 100)),
        "preference": str(config["preference"]),
        "email": "",
        "email_provider": "",
    }


def _render_page(token: str, message: str, values: dict[str, str]) -> str:
    replacements = {
        "__TOKEN__": token,
        "__MESSAGE__": message,
        "__NOTIFIER__": notification_label(),
        "__MOVIE__": values["movie"],
        "__THEATER__": values["theater"],
        "__FORMAT__": values["screen_format"],
        "__WEEKDAY_AFTER__": values["weekday_after"],
        "__WEEKDAY_BEFORE__": values["weekday_before"],
        "__SATURDAY_AFTER__": values["saturday_after"],
        "__SATURDAY_BEFORE__": values["saturday_before"],
        "__SUNDAY_AFTER__": values["sunday_after"],
        "__SUNDAY_BEFORE__": values["sunday_before"],
        "__PARTY_SIZE__": values["party_size"],
        "__ROWS__": values["rows"],
        "__EDGE_PERCENT__": values["edge_percent"],
        "__EMAIL__": values["email"],
    }
    page = PAGE
    for marker, value in replacements.items():
        page = page.replace(marker, html.escape(value))
    for provider in SUPPORTED_NOTIFICATION_PROVIDERS:
        page = page.replace(f"__PROVIDER_{provider.upper()}__", "selected" if provider == values["email_provider"] else "")
    page = page.replace("__PREFERENCE_CENTER__", "selected" if values["preference"] == "closest_to_center" else "")
    page = page.replace("__PREFERENCE_ROW__", "selected" if values["preference"] == "row_order_then_left" else "")
    return page


def _booking_config(values: dict[str, str]) -> dict[str, object]:
    config = odyssey()
    try:
        party_size = int(values["party_size"])
        edge_exclusion = float(values["edge_percent"]) / 100
    except ValueError as exc:
        raise ConfigError("좌석 수와 양끝 제외 비율은 숫자로 입력해 주세요.") from exc
    rows = [row.upper() for row in values["rows"].replace(",", " ").split() if row]
    config.update(
        {
            "movie": values["movie"].strip(),
            "theater": values["theater"].strip(),
            "format": values["screen_format"].strip(),
            "party_size": party_size,
            "rows": rows,
            "edge_exclusion": edge_exclusion,
            "preference": values["preference"],
            "time_rules": {
                "weekday": {"at_or_after": values["weekday_after"] or None, "before": values["weekday_before"] or None},
                "saturday": {"at_or_after": values["saturday_after"] or None, "before": values["saturday_before"] or None},
                "sunday": {"at_or_after": values["sunday_after"] or None, "before": values["sunday_before"] or None},
            },
        }
    )
    config["payment"]["voucher_count"] = party_size
    if "imax" not in str(config["format"]).casefold():
        raise ConfigError("현재 자동 결제는 IMAX 관람권만 지원하므로 상영 형식에 IMAX가 포함되어야 합니다.")
    return config


def login_verified(paths: RuntimePaths) -> bool:
    try:
        with CgvSession(paths).locked() as session:
            return session.is_logged_in()
    except CgvError:
        return False


def resolve_target(paths: RuntimePaths, config: dict[str, object]) -> dict[str, str]:
    with CgvSession(paths).locked() as session:
        session.require_login()
        CheckoutFlow(session.page, config).open_movie_and_theater()
        return session.booking_target_from_page()


def run_setup(paths: RuntimePaths, *, open_page: bool = True) -> tuple[ThreadingHTTPServer, str]:
    token = secrets.token_urlsafe(32)
    message = ""
    values = _default_form_values()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            query = urllib.parse.urlparse(self.path)
            supplied = urllib.parse.parse_qs(query.query).get("token", [""])[0]
            if query.path != "/" or not secrets.compare_digest(supplied, token):
                self._send(404, "Not found")
                return
            self._send(200, _render_page(token, message, values))

        def do_POST(self) -> None:  # noqa: N802
            nonlocal message, values
            if self.path != "/action" or self.client_address[0] not in {"127.0.0.1", "::1"}:
                self._send(404, "Not found")
                return
            length = min(int(self.headers.get("Content-Length", "0")), 16_384)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            supplied = form.get("token", [""])[0]
            if not secrets.compare_digest(supplied, token):
                self._send(403, "Forbidden")
                return
            action = form.get("action", [""])[0]
            if action == "login":
                try:
                    launch_browser(paths)
                    message = "전용 Chrome이 열렸습니다. CGV 로그인을 직접 완료한 뒤 이 화면으로 돌아오세요."
                except BrowserError as exc:
                    message = str(exc)
                self._send(200, _render_page(token, message, values))
                return
            for key in values:
                values[key] = form.get(key, [values[key]])[0].strip()
            if action != "save" or form.get("consent", [""])[0] != "yes" or form.get("network", [""])[0] != "yes":
                self._send(400, "동의가 필요합니다.")
                return
            if values["email_provider"] not in SUPPORTED_NOTIFICATION_PROVIDERS or not valid_email_address(values["email"]):
                message = "메일 서비스와 올바른 수신 이메일 주소를 선택해 주세요."
                self._send(400, _render_page(token, message, values))
                return
            if not login_verified(paths):
                message = "CGV 로그인이 확인되지 않았습니다. 전용 Chrome에서 로그인한 뒤 다시 저장해 주세요."
                self._send(400, _render_page(token, message, values))
                return
            try:
                config = _booking_config(values)
                config["notification"] = {
                    "email": values["email"],
                    "recipient_provider": values["email_provider"],
                    "method": notification_method(),
                }
                config["consent"] = {
                    "automatic_submission": True,
                    "one_active_device_per_public_ip": True,
                    "accepted_at": datetime.now().astimezone().isoformat(),
                    "scope": "matching-seat-once-voucher-only-zero-balance",
                }
                errors = validate_config(config)
                if errors:
                    raise ConfigError("; ".join(errors))
                config["target"] = resolve_target(paths, config)
            except (ConfigError, CgvError, CheckoutError) as exc:
                message = f"영화·극장·상영 형식을 확인하지 못했습니다: {exc}"
                self._send(400, _render_page(token, message, values))
                return
            try:
                label = notification_label()
                send_email(values["email"], "Prickly IMAX Helper 설정 확인", f"{label} 알림이 정상적으로 연결됐습니다.")
            except Exception as exc:
                message = f"{notification_label()} 테스트 발송에 실패했습니다: {exc}"
                self._send(400, _render_page(token, message, values))
                return
            try:
                paths.prepare()
                write_config(paths.config, config)
                transition(paths.heartbeat, Status.LOGIN_REQUIRED, detail="configuration saved; login verification required")
            except (ConfigError, OSError) as exc:
                self._send(400, html.escape(str(exc)))
                return
            self._send(200, "<meta charset=utf-8><h1>설정 저장 완료</h1><p>이 창을 닫아도 됩니다. 로그인 확인 후 감시 서비스가 시작됩니다.</p>")
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}/?token={urllib.parse.quote(token)}"
    if open_page:
        webbrowser.open(url)
    return server, url


def serve_setup(paths: RuntimePaths) -> None:
    server, url = run_setup(paths)
    print(f"설정 페이지가 열리지 않으면 이 주소를 같은 PC의 브라우저에서 여세요:\n{url}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
