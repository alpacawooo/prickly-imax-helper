from __future__ import annotations

import fcntl
import os
import time
from typing import Any

from .browser import launch_browser
from .cgv import CgvSession, LoginRequired, RateLimited
from .checkout import CheckoutError, CheckoutFlow, DuplicateBlocked, PaymentBlocked, SeatVanished, UnknownAfterSubmit
from .config import load_config
from .eventlog import write_event
from .notify import send_email, show_notification
from .paths import RuntimePaths
from .scheduler import FairScanState, changed_seat_targets, eligible_shows, match_for
from .state import Status, read_state, transition


OPEN_DATE_REFRESH_SECONDS = 300.0
UNCHANGED_SEAT_PROBE_SECONDS = 60.0


class AlreadyRunning(RuntimeError):
    pass


def _notify(paths: RuntimePaths, config: dict[str, Any], subject: str, body: str) -> None:
    show_notification(subject, body)
    try:
        send_email(config["notification"]["email"], subject, body)
    except Exception as exc:
        write_event(paths.logs, "email_failed", error=str(exc))


def _heartbeat(paths: RuntimePaths, status: Status, detail: str = "", **fields: Any) -> None:
    transition(paths.heartbeat, status, detail=detail, **fields)


def _checkout(paths: RuntimePaths, config: dict[str, Any], session: CgvSession, match: dict[str, Any]) -> str:
    _heartbeat(paths, Status.STAGING, match=match)
    flow = CheckoutFlow(session.page, config)
    try:
        flow.ensure_no_existing_ticket(match)
        flow.open_movie_and_theater()
        flow.open_match(match)
        flow.select_party_and_seats(match)
        flow.open_payment_and_apply_vouchers()
        flow.ensure_no_existing_ticket(match, separate_tab=True)
        # Revalidate policy-sensitive order state before crossing the one-way boundary.
        flow.prove_ready(match)
    except DuplicateBlocked as exc:
        _heartbeat(paths, Status.BLOCKED_DUPLICATE, str(exc), match=match)
        _notify(paths, config, "Prickly IMAX 예매 중단", "기존 예매가 확인되어 자동 예매를 중단했습니다.")
        return Status.BLOCKED_DUPLICATE.value
    except PaymentBlocked as exc:
        _heartbeat(paths, Status.BLOCKED_PAYMENT, str(exc), match=match)
        _notify(paths, config, "Prickly IMAX 결제 중단", "관람권 수량 또는 0원 잔액을 증명하지 못해 결제를 실행하지 않았습니다.")
        return Status.BLOCKED_PAYMENT.value
    except SeatVanished as exc:
        _heartbeat(paths, Status.ARMED, str(exc))
        write_event(paths.logs, "seat_vanished", match=match, error=str(exc))
        return Status.ARMED.value
    except CheckoutError as exc:
        _heartbeat(paths, Status.RECOVERING, str(exc), match=match)
        write_event(paths.logs, "checkout_pre_submit_error", match=match, error=str(exc))
        return Status.RECOVERING.value

    _heartbeat(paths, Status.SUBMITTING, "all final checks passed; one submission attempt", match=match)
    try:
        flow.submit_once()
        result = flow.verify_mobile_ticket()
    except UnknownAfterSubmit as exc:
        _heartbeat(paths, Status.UNKNOWN_AFTER_SUBMIT, str(exc), match=match)
        _notify(paths, config, "Prickly IMAX 결과 확인 필요", "최종 제출 이후 모바일티켓 확인에 실패했습니다. 안전을 위해 재시도하지 않습니다.")
        return Status.UNKNOWN_AFTER_SUBMIT.value
    _heartbeat(paths, Status.COMPLETED, "mobile ticket verified", match=match, proof=result.proof)
    _notify(paths, config, "Prickly IMAX 예매 완료", f"{match['date']} {match['time']} {match['pair']} 예매가 완료됐습니다.")
    return Status.COMPLETED.value


def run(paths: RuntimePaths, *, max_cycles: int | None = None, allow_checkout: bool = True) -> int:
    paths.prepare()
    config = load_config(paths.config)
    lock_path = paths.state_dir / "monitor.lock"
    with lock_path.open("a+", encoding="utf-8") as daemon_lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(daemon_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning("monitor is already running") from exc

        current = read_state(paths.heartbeat).get("status")
        if paths.stop_requested.exists():
            if current != Status.STOPPED.value:
                _heartbeat(paths, Status.STOPPED, "stop request is present")
            return 0
        if current in {Status.COMPLETED.value, Status.UNKNOWN_AFTER_SUBMIT.value, Status.BLOCKED_DUPLICATE.value, Status.BLOCKED_PAYMENT.value}:
            return 0
        if current == Status.SUBMITTING.value:
            _heartbeat(paths, Status.UNKNOWN_AFTER_SUBMIT, "process restarted across submission boundary; automatic retry forbidden")
            _notify(paths, config, "Prickly IMAX 결과 확인 필요", "최종 제출 중 프로세스가 종료된 기록이 있어 자동 재시도를 중단했습니다.")
            return 2
        if current == Status.STAGING.value:
            _heartbeat(paths, Status.RECOVERING, "interrupted before submission; rebuilding browser state")
        if current in {None, Status.UNCONFIGURED.value, Status.STOPPED.value}:
            _heartbeat(paths, Status.LOGIN_REQUIRED, "monitor starting; login verification pending")
        launch_browser(paths)
        state = FairScanState()
        last_open_date_refresh = 0.0
        last_seat_probe: dict[str, float] = {}
        consecutive_errors = 0
        session = CgvSession(
            paths,
            minimum_interval_seconds=float(config["request_policy"]["minimum_interval_seconds"]),
            cooldown_seconds=float(config["request_policy"].get("rate_limit_cooldown_seconds", 300)),
        )
        with session.locked():
            completed_cycles = 0
            while True:
                if paths.stop_requested.exists() or read_state(paths.heartbeat).get("status") == Status.STOPPED.value:
                    return 0
                try:
                    session.require_login()
                    current = read_state(paths.heartbeat).get("status")
                    if current != Status.ARMED.value:
                        _heartbeat(paths, Status.ARMED, "CGV login verified")
                    now = time.time()
                    if not state.open_dates or now - last_open_date_refresh >= OPEN_DATE_REFRESH_SECONDS:
                        state.replace_dates(session.open_dates())
                        last_open_date_refresh = now
                        write_event(paths.logs, "open_dates_refreshed", count=len(state.open_dates))
                    ymd = state.next_date()
                    if ymd is None:
                        _heartbeat(paths, Status.ARMED, "no open dates", open_dates=0)
                        time.sleep(5)
                        continue
                    shows = eligible_shows(ymd, session.schedules(ymd), config)
                    changed = changed_seat_targets(state, shows)
                    targets = []
                    for show in shows:
                        key = f"{show['ymd']}|{show.get('scnsNo')}|{show.get('scnSseq')}"
                        if show in changed or now - last_seat_probe.get(key, 0.0) >= UNCHANGED_SEAT_PROBE_SECONDS:
                            targets.append(show)
                    for show in targets:
                        key = f"{show['ymd']}|{show.get('scnsNo')}|{show.get('scnSseq')}"
                        last_seat_probe[key] = time.time()
                        seat_map = session.seats(show["ymd"], str(show["scnsNo"]), str(show["scnSseq"]))
                        match = match_for(show, seat_map, config)
                        if match:
                            write_event(paths.logs, "seat_match", match=match)
                            if allow_checkout:
                                result = _checkout(paths, config, session, match)
                                if result != Status.ARMED.value and result != Status.RECOVERING.value:
                                    return 0
                            else:
                                write_event(paths.logs, "dry_run_match_not_selected", match=match)
                            break
                    consecutive_errors = 0
                    _heartbeat(
                        paths,
                        Status.ARMED,
                        "scan completed",
                        open_dates=len(state.open_dates),
                        scanned_date=ymd,
                        eligible_shows=len(shows),
                    )
                    completed_cycles += 1
                    if max_cycles is not None and completed_cycles >= max_cycles:
                        return 0
                except LoginRequired as exc:
                    _heartbeat(paths, Status.LOGIN_REQUIRED, str(exc))
                    if max_cycles is not None:
                        return 1
                    time.sleep(30)
                except RateLimited as exc:
                    _heartbeat(paths, Status.RATE_LIMITED, str(exc))
                    write_event(paths.logs, "rate_limited", error=str(exc))
                    _notify(paths, config, "Prickly IMAX 조회 제한", "CGV 요청 제한을 감지해 모든 자동 조회를 일시 중지했습니다.")
                    if max_cycles is not None:
                        return 3
                    time.sleep(float(config["request_policy"].get("rate_limit_cooldown_seconds", 300)))
                except Exception as exc:
                    consecutive_errors += 1
                    current = read_state(paths.heartbeat).get("status")
                    if current == Status.SUBMITTING.value:
                        _heartbeat(paths, Status.UNKNOWN_AFTER_SUBMIT, str(exc))
                        _notify(paths, config, "Prickly IMAX 결과 확인 필요", "제출 경계에서 오류가 발생해 재시도를 중단했습니다.")
                        return 2
                    _heartbeat(paths, Status.RECOVERING, str(exc), errors=consecutive_errors)
                    write_event(paths.logs, "monitor_error", error=str(exc), errors=consecutive_errors)
                    if max_cycles is not None:
                        return 1
                    time.sleep(min(60.0, 2.0**min(consecutive_errors, 5)))


def main() -> int:
    try:
        return run(RuntimePaths.default())
    except AlreadyRunning:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
