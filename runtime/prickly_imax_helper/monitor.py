from __future__ import annotations

import time
from typing import Any

from .browser import launch_browser
from .cgv import CgvSession, LoginRequired, RateLimited
from .checkout import CheckoutError, CheckoutFlow, DuplicateBlocked, PaymentBlocked, SeatVanished, UnknownAfterSubmit
from .config import ConfigError, load_config
from .eventlog import write_event
from .locks import LockUnavailable, locked_file
from .notify import send_email, show_notification
from .paths import RuntimePaths
from .scheduler import FairScanState, changed_seat_targets, eligible_shows, match_for
from .state import TERMINAL, Status, read_state, transition


OPEN_DATE_REFRESH_SECONDS = 30.0
UNCHANGED_SEAT_PROBE_SECONDS = 60.0
MAX_RATE_LIMIT_COOLDOWN_SECONDS = 3600.0
CHECKOUT_GUARD_RETRY_SECONDS = 300.0


class AlreadyRunning(RuntimeError):
    pass


def rate_limit_backoff_seconds(streak: int, base_seconds: float) -> float:
    if streak < 1:
        raise ValueError("rate-limit streak must be positive")
    if base_seconds < 300:
        raise ValueError("rate-limit cooldown must be at least five minutes")
    return min(MAX_RATE_LIMIT_COOLDOWN_SECONDS, base_seconds * (2 ** (streak - 1)))


def _notify(paths: RuntimePaths, config: dict[str, Any], subject: str, body: str) -> None:
    try:
        show_notification(subject, body)
    except Exception as exc:
        write_event(paths.logs, "desktop_notification_failed", error=str(exc))
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
        flow.ensure_no_existing_ticket(match, separate_tab=True)
        flow.open_movie_and_theater()
        selected_target = session.booking_target_from_page()
        expected_target = config.get("target") or {
            "company_code": "A420",
            "site_no": "0013",
            "movie_no": "30001323",
        }
        if selected_target != expected_target:
            raise CheckoutError("selected movie/theater identifiers do not match the monitored target")
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
        result = flow.verify_mobile_ticket(match)
    except UnknownAfterSubmit as exc:
        _heartbeat(paths, Status.UNKNOWN_AFTER_SUBMIT, str(exc), match=match)
        _notify(paths, config, "Prickly IMAX 결과 확인 필요", "최종 제출 이후 모바일티켓 확인에 실패했습니다. 안전을 위해 재시도하지 않습니다.")
        return Status.UNKNOWN_AFTER_SUBMIT.value
    _heartbeat(paths, Status.COMPLETED, "mobile ticket verified", match=match, proof=result.proof)
    _notify(paths, config, "Prickly IMAX 예매 완료", f"{match['date']} {match['time']} {match['pair']} 예매가 완료됐습니다.")
    return Status.COMPLETED.value


def run(paths: RuntimePaths, *, max_cycles: int | None = None, allow_checkout: bool = True) -> int:
    paths.prepare()
    try:
        config = load_config(paths.config)
    except ConfigError as exc:
        current = read_state(paths.heartbeat).get("status", Status.UNCONFIGURED.value)
        if current == Status.SUBMITTING.value:
            _heartbeat(paths, Status.UNKNOWN_AFTER_SUBMIT, "configuration became invalid across submission boundary; retry forbidden")
        elif current not in {status.value for status in TERMINAL}:
            _heartbeat(paths, Status.FATAL, "configuration is invalid; resident restart disabled")
        write_event(paths.logs, "configuration_invalid", error=str(exc))
        return 0
    lock_path = paths.state_dir / "monitor.lock"
    try:
        daemon_lock = locked_file(lock_path, blocking=False)
        daemon_lock.__enter__()
    except LockUnavailable as exc:
        raise AlreadyRunning("monitor is already running") from exc
    try:

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
        rate_limit_streak = 0
        session = CgvSession(
            paths,
            minimum_interval_seconds=float(config["request_policy"]["minimum_interval_seconds"]),
            cooldown_seconds=float(config["request_policy"].get("rate_limit_cooldown_seconds", 300)),
            company_code=str(config.get("target", {}).get("company_code", "A420")),
            site_no=str(config.get("target", {}).get("site_no", "0013")),
            movie_no=str(config.get("target", {}).get("movie_no", "30001323")),
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
                        if max_cycles is not None:
                            return 0
                        time.sleep(5)
                        continue
                    shows = eligible_shows(ymd, session.schedules(ymd), config)
                    changed = changed_seat_targets(state, shows, int(config["party_size"]))
                    targets = []
                    for show in shows:
                        key = f"{show['ymd']}|{show.get('scnsNo')}|{show.get('scnSseq')}"
                        if show in changed or now - last_seat_probe.get(key, 0.0) >= UNCHANGED_SEAT_PROBE_SECONDS:
                            targets.append(show)
                    checkout_guard_unavailable = False
                    for show in targets:
                        key = f"{show['ymd']}|{show.get('scnsNo')}|{show.get('scnSseq')}"
                        last_seat_probe[key] = time.time()
                        seat_map = session.seats(show["ymd"], str(show["scnsNo"]), str(show["scnSseq"]))
                        match = match_for(show, seat_map, config)
                        if match:
                            write_event(paths.logs, "seat_match", match=match)
                            if allow_checkout:
                                result = _checkout(paths, config, session, match)
                                if result == Status.RECOVERING.value:
                                    checkout_guard_unavailable = True
                                elif result != Status.ARMED.value:
                                    return 0
                            else:
                                write_event(paths.logs, "dry_run_match_not_selected", match=match)
                            break
                    if checkout_guard_unavailable:
                        write_event(paths.logs, "checkout_guard_retry_deferred", seconds=CHECKOUT_GUARD_RETRY_SECONDS)
                        if max_cycles is not None:
                            return 1
                        time.sleep(CHECKOUT_GUARD_RETRY_SECONDS)
                        continue
                    consecutive_errors = 0
                    rate_limit_streak = 0
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
                    rate_limit_streak += 1
                    base_cooldown = float(config["request_policy"].get("rate_limit_cooldown_seconds", 300))
                    cooldown = max(exc.cooldown_seconds, rate_limit_backoff_seconds(rate_limit_streak, base_cooldown))
                    session.budget.defer(cooldown)
                    _heartbeat(paths, Status.RATE_LIMITED, str(exc), cooldown_seconds=cooldown, streak=rate_limit_streak)
                    write_event(paths.logs, "rate_limited", error=str(exc), cooldown_seconds=cooldown, streak=rate_limit_streak)
                    _notify(paths, config, "Prickly IMAX 조회 제한", "CGV 요청 제한을 감지해 모든 자동 조회를 일시 중지했습니다.")
                    if max_cycles is not None:
                        return 3
                    time.sleep(cooldown)
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
    finally:
        daemon_lock.__exit__(None, None, None)


def main() -> int:
    try:
        return run(RuntimePaths.default())
    except AlreadyRunning:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
