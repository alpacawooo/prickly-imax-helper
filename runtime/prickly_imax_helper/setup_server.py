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
from .config import ConfigError, SUPPORTED_NOTIFICATION_PROVIDERS, valid_email_address, write_config
from .notify import notification_label, notification_method, send_email
from .paths import RuntimePaths
from .presets import odyssey
from .state import Status, transition


PAGE = """<!doctype html><html lang=\"ko\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>Prickly IMAX Helper</title>
<style>body{font-family:-apple-system,sans-serif;max-width:720px;margin:48px auto;padding:0 20px;color:#171717}fieldset{border:1px solid #ddd;border-radius:12px;padding:18px;margin:18px 0}label{display:block;margin:12px 0}input,select{padding:9px;width:100%;box-sizing:border-box}button{padding:12px 18px;border:0;border-radius:9px;background:#111;color:white;font-weight:650}.secondary{background:#eee;color:#111}.warning{background:#fff7ed;padding:14px;border-radius:9px}.hint{color:#555;font-size:14px}</style>
<h1>Prickly IMAX Helper 설정</h1><p>비밀번호와 관람권 번호는 입력하지 않습니다. CGV 로그인은 전용 Chrome 창에서 직접 하세요.</p>
<form method=post action=\"/action\"><input type=hidden name=token value=\"__TOKEN__\">
<fieldset><legend>1. CGV 로그인</legend><button class=secondary name=action value=login formnovalidate>전용 Chrome 열기</button><p>__MESSAGE__</p></fieldset>
<fieldset><legend>2. 오디세이 기본 조건</legend><p>용산아이파크몰 IMAX · 2명 연속 · D~J열 · 양끝 20% 제외 · 중앙 우선</p><p>평일 19:00 이후 · 토요일 전체 · 일요일 22:00 이전 · 새로 열리는 날짜 자동 포함</p>
<label>알림을 받을 메일 서비스<select required name=email_provider><option value=\"\">선택하세요</option><option value=\"gmail\" __PROVIDER_GMAIL__>Gmail</option><option value=\"naver\" __PROVIDER_NAVER__>네이버 메일</option><option value=\"icloud\" __PROVIDER_ICLOUD__>iCloud Mail (Apple)</option><option value=\"other\" __PROVIDER_OTHER__>기타 메일</option></select></label>
<label>결과를 받을 이메일 주소<input required type=email name=email value=\"__EMAIL__\" autocomplete=email></label><p class=hint>받는 주소는 운영체제와 상관없이 선택할 수 있습니다. 발송은 Mac의 Apple Mail 또는 Windows의 Outlook 데스크톱을 로컬로 사용하며, 이메일 비밀번호나 앱 비밀번호는 Helper에 입력하지 않습니다.</p><p>설정 저장 시 선택한 주소로 __NOTIFIER__ 테스트 메일을 한 번 보냅니다.</p></fieldset>
<fieldset><legend>3. 자동 예매 사전동의</legend><div class=warning>등록된 IMAX 관람권 정확히 2매로 결제 잔액이 0원일 때만 조건에 맞는 좌석을 한 번 자동 예매합니다. 기존 예매 취소·변경과 중복 제출은 하지 않습니다.</div>
<label><input style=\"width:auto\" required type=checkbox name=consent value=yes> 위 조건의 자동 좌석 선택과 1회 최종 제출에 동의합니다.</label>
<label><input style=\"width:auto\" required type=checkbox name=network value=yes> 같은 공인 IP를 사용하는 집·회사 네트워크에서 이 Helper를 한 대만 실행합니다.</label></fieldset>
<button name=action value=save>설정 저장</button></form></html>"""


def _render_page(token: str, message: str, email: str, email_provider: str = "") -> str:
    page = (
        PAGE.replace("__TOKEN__", html.escape(token))
        .replace("__MESSAGE__", html.escape(message))
        .replace("__EMAIL__", html.escape(email))
        .replace("__NOTIFIER__", html.escape(notification_label()))
    )
    for provider in SUPPORTED_NOTIFICATION_PROVIDERS:
        page = page.replace(f"__PROVIDER_{provider.upper()}__", "selected" if provider == email_provider else "")
    return page


def login_verified(paths: RuntimePaths) -> bool:
    try:
        with CgvSession(paths).locked() as session:
            return session.is_logged_in()
    except CgvError:
        return False


def run_setup(paths: RuntimePaths, *, open_page: bool = True) -> tuple[ThreadingHTTPServer, str]:
    token = secrets.token_urlsafe(32)
    message = ""
    email = ""
    email_provider = ""

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
            self._send(200, _render_page(token, message, email, email_provider))

        def do_POST(self) -> None:  # noqa: N802
            nonlocal message, email, email_provider
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
                self._send(200, _render_page(token, message, email, email_provider))
                return
            email = form.get("email", [""])[0].strip()
            email_provider = form.get("email_provider", [""])[0].strip()
            if action != "save" or form.get("consent", [""])[0] != "yes" or form.get("network", [""])[0] != "yes":
                self._send(400, "동의가 필요합니다.")
                return
            if email_provider not in SUPPORTED_NOTIFICATION_PROVIDERS or not valid_email_address(email):
                message = "메일 서비스와 올바른 수신 이메일 주소를 선택해 주세요."
                self._send(400, _render_page(token, message, email, email_provider))
                return
            if not login_verified(paths):
                message = "CGV 로그인이 확인되지 않았습니다. 전용 Chrome에서 로그인한 뒤 다시 저장해 주세요."
                self._send(400, _render_page(token, message, email, email_provider))
                return
            try:
                label = notification_label()
                send_email(email, "Prickly IMAX Helper 설정 확인", f"{label} 알림이 정상적으로 연결됐습니다.")
            except Exception as exc:
                message = f"{notification_label()} 테스트 발송에 실패했습니다: {exc}"
                self._send(400, _render_page(token, message, email, email_provider))
                return
            config = odyssey()
            config["notification"] = {
                "email": email,
                "recipient_provider": email_provider,
                "method": notification_method(),
            }
            config["consent"] = {
                "automatic_submission": True,
                "one_active_device_per_public_ip": True,
                "accepted_at": datetime.now().astimezone().isoformat(),
                "scope": "matching-seat-once-voucher-only-zero-balance",
            }
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
