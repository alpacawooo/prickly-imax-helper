from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .browser import launch_browser
from .cgv import CgvSession, LoginRequired, RateLimited
from .checkout import CheckoutError, CheckoutFlow, DuplicateBlocked, PaymentBlocked, SeatVanished, UnknownAfterSubmit
from .checkout_attempt import CheckoutAttemptRecorder
from .config import ConfigError, load_config
from .eventlog import write_event
from .locks import LockUnavailable, locked_file
from .notify import send_email, show_notification
from .paths import RuntimePaths
from .scheduler import BalancedScanPlanner, eligible_shows, match_for, show_key
from .state import TERMINAL, Status, read_state, transition


KST = ZoneInfo("Asia/Seoul")
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


def _notify(
    paths: RuntimePaths,
    config: dict[str, Any],
    subject: str,
    body: str,
    *,
    attempt_id: str | None = None,
) -> None:
    try:
        show_notification(subject, body)
    except Exception as exc:
        write_event(paths.logs, "desktop_notification_failed", error=str(exc))
        if attempt_id is not None:
            write_event(
                paths.logs,
                "notification_result",
                attempt_id=attempt_id,
                channel="desktop",
                outcome="failed",
            )
    else:
        if attempt_id is not None:
            write_event(
                paths.logs,
                "notification_result",
                attempt_id=attempt_id,
                channel="desktop",
                outcome="passed",
            )
    try:
        send_email(config["notification"]["email"], subject, body)
    except Exception as exc:
        write_event(paths.logs, "email_failed", error=str(exc))
        if attempt_id is not None:
            write_event(
                paths.logs,
                "notification_result",
                attempt_id=attempt_id,
                channel="email",
                outcome="failed",
            )
    else:
        if attempt_id is not None:
            write_event(
                paths.logs,
                "notification_result",
                attempt_id=attempt_id,
                channel="email",
                outcome="passed",
            )


def _heartbeat(paths: RuntimePaths, status: Status, detail: str = "", **fields: Any) -> None:
    transition(paths.heartbeat, status, detail=detail, **fields)


def _kst_day(now: datetime | None = None) -> date:
    value = now or datetime.now(tz=KST)
    if value.tzinfo is None:
        raise ValueError("Korean calendar checks require a timezone-aware datetime")
    return value.astimezone(KST).date()


def _refresh_discovery(
    paths: RuntimePaths,
    session: CgvSession,
    planner: BalancedScanPlanner,
    config: dict[str, Any],
    *,
    now: float,
) -> int:
    previous_dates = set(planner.open_dates)
    previous_keys = {show_key(show) for show in planner.hot_targets}
    dates = session.open_dates()
    schedules = {
        ymd: eligible_shows(ymd, session.schedules(ymd), config)
        for ymd in dates
    }
    planner.replace_discovery(dates, schedules, now=now)
    next_dates = set(planner.open_dates)
    next_keys = {show_key(show) for show in planner.hot_targets}
    if next_dates != previous_dates:
        write_event(paths.logs, "open_dates_refreshed", count=len(next_dates))
    for discovered in sorted(next_dates - previous_dates):
        write_event(paths.logs, "booking_date_discovered", ymd=discovered)
    if next_keys != previous_keys:
        write_event(paths.logs, "hot_queue_changed", count=len(next_keys))
    return len(planner.hot_targets)


def _checkout(
    paths: RuntimePaths,
    config: dict[str, Any],
    session: CgvSession,
    match: dict[str, Any],
    recorder: CheckoutAttemptRecorder,
) -> str:
    _heartbeat(paths, Status.STAGING, match=match, attempt_id=recorder.attempt_id)
    flow = CheckoutFlow(session.page, config)
    try:
        with recorder.stage("duplicate_guard_before"):
            flow.ensure_no_existing_ticket(match, separate_tab=True)
        with recorder.stage("theater"):
            flow.open_movie_and_theater()
            selected_target = session.booking_target_from_page()
            expected_target = config.get("target") or {
                "company_code": "A420",
                "site_no": "0013",
                "movie_no": "30001323",
            }
            if selected_target != expected_target:
                raise CheckoutError("selected movie/theater identifiers do not match the monitored target")
        with recorder.stage("date"):
            flow._require_match_date(match)
        with recorder.stage("showtime"):
            flow._open_match_showtime(match)
        with recorder.stage("party"):
            flow._select_general_party(int(config["party_size"]))
        with recorder.stage("seats"):
            flow._select_seats(match)
        with recorder.stage("vouchers"):
            flow.open_payment_and_apply_vouchers()
        with recorder.stage("zero_balance"):
            flow.prove_ready(match)
        with recorder.stage("duplicate_guard_final"):
            flow.ensure_no_existing_ticket(match, separate_tab=True)
        recorder.mark("submission_ready")
    except DuplicateBlocked as exc:
        recorder.terminal("blocked_duplicate", error=str(exc))
        _heartbeat(paths, Status.BLOCKED_DUPLICATE, str(exc), match=match, attempt_id=recorder.attempt_id)
        _notify(
            paths,
            config,
            "Prickly IMAX 예매 중단",
            "기존 예매가 확인되어 자동 예매를 중단했습니다.",
            attempt_id=recorder.attempt_id,
        )
        return Status.BLOCKED_DUPLICATE.value
    except PaymentBlocked as exc:
        recorder.terminal("blocked_payment", error=str(exc))
        _heartbeat(paths, Status.BLOCKED_PAYMENT, str(exc), match=match, attempt_id=recorder.attempt_id)
        _notify(
            paths,
            config,
            "Prickly IMAX 결제 중단",
            "관람권 수량 또는 0원 잔액을 증명하지 못해 결제를 실행하지 않았습니다.",
            attempt_id=recorder.attempt_id,
        )
        return Status.BLOCKED_PAYMENT.value
    except SeatVanished as exc:
        recorder.terminal("seat_vanished", error=str(exc))
        _heartbeat(paths, Status.ARMED, str(exc), match=None)
        return Status.ARMED.value
    except CheckoutError as exc:
        recorder.terminal("checkout_pre_submit_error", error=str(exc))
        _heartbeat(paths, Status.RECOVERING, str(exc), match=match, attempt_id=recorder.attempt_id)
        return Status.RECOVERING.value

    _heartbeat(
        paths,
        Status.SUBMITTING,
        "all final checks passed; one submission attempt",
        match=match,
        attempt_id=recorder.attempt_id,
    )
    try:
        with recorder.stage("submission"):
            flow.submit_once()
        with recorder.stage("mobile_ticket"):
            result = flow.verify_mobile_ticket(match)
    except UnknownAfterSubmit as exc:
        recorder.terminal("unknown_after_submit", error=str(exc))
        _heartbeat(paths, Status.UNKNOWN_AFTER_SUBMIT, str(exc), match=match, attempt_id=recorder.attempt_id)
        _notify(
            paths,
            config,
            "Prickly IMAX 결과 확인 필요",
            "최종 제출 이후 모바일티켓 확인에 실패했습니다. 안전을 위해 재시도하지 않습니다.",
            attempt_id=recorder.attempt_id,
        )
        return Status.UNKNOWN_AFTER_SUBMIT.value
    recorder.terminal("completed")
    _heartbeat(
        paths,
        Status.COMPLETED,
        "mobile ticket verified",
        match=match,
        proof=result.proof,
        attempt_id=recorder.attempt_id,
    )
    _notify(
        paths,
        config,
        "Prickly IMAX 예매 완료",
        f"{match['date']} {match['time']} {match['pair']} 예매가 완료됐습니다.",
        attempt_id=recorder.attempt_id,
    )
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

        startup_state = read_state(paths.heartbeat)
        current = startup_state.get("status")
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
            attempt_id = startup_state.get("attempt_id")
            match = startup_state.get("match")
            if isinstance(attempt_id, str) and attempt_id and isinstance(match, dict):
                write_event(
                    paths.logs,
                    "checkout_attempt_interrupted",
                    attempt_id=attempt_id,
                    match=match,
                )
            _heartbeat(paths, Status.RECOVERING, "interrupted before submission; rebuilding browser state")
        if current in {None, Status.UNCONFIGURED.value, Status.STOPPED.value}:
            _heartbeat(paths, Status.LOGIN_REQUIRED, "monitor starting; login verification pending")
        launch_browser(paths)
        planner = BalancedScanPlanner(
            minimum_interval_seconds=float(config["request_policy"]["minimum_interval_seconds"]),
        )
        last_discovery_day: date | None = None
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
                        _heartbeat(paths, Status.ARMED, "CGV login verified", match=None, errors=0)
                    checkout_guard_unavailable = False
                    today = _kst_day()
                    if last_discovery_day != today:
                        eligible_count = _refresh_discovery(
                            paths,
                            session,
                            planner,
                            config,
                            now=time.monotonic(),
                        )
                        last_discovery_day = today
                        scanned_date = None
                        last_scan_lane = "discovery"
                    else:
                        action = planner.next_hot_action()
                        if action is None:
                            consecutive_errors = 0
                            rate_limit_streak = 0
                            metrics = planner.metrics(now=time.monotonic())
                            _heartbeat(
                                paths,
                                Status.ARMED,
                                "no eligible showtimes; waiting for Korean midnight discovery",
                                open_dates=len(planner.open_dates),
                                scanned_date=None,
                                eligible_shows=0,
                                match=None,
                                errors=0,
                                last_scan_lane="idle",
                                **metrics,
                            )
                            completed_cycles += 1
                            if max_cycles is not None and completed_cycles >= max_cycles:
                                return 0
                            time.sleep(float(config["request_policy"]["minimum_interval_seconds"]))
                            continue
                        eligible_count = len(planner.hot_targets)
                        show = action.show
                        assert show is not None
                        if not eligible_shows(show["ymd"], [show], config):
                            planner.remove_hot_target(show)
                            write_event(paths.logs, "hot_target_pruned", reason="schedule_policy")
                        else:
                            seat_map = session.seats(show["ymd"], str(show["scnsNo"]), str(show["scnSseq"]))
                            if not seat_map.get("all"):
                                planner.remove_hot_target(show)
                                write_event(paths.logs, "hot_target_pruned", reason="seat_map_empty")
                                match = None
                            else:
                                match = match_for(show, seat_map, config)
                            if match:
                                if allow_checkout:
                                    recorder = CheckoutAttemptRecorder.start(paths.logs, match)
                                    result = _checkout(paths, config, session, match, recorder)
                                    if result == Status.RECOVERING.value:
                                        checkout_guard_unavailable = True
                                    elif result != Status.ARMED.value:
                                        return 0
                                else:
                                    write_event(paths.logs, "seat_match", match=match)
                                    write_event(paths.logs, "dry_run_match_not_selected", match=match)
                        planner.complete(action)
                        scanned_date = action.ymd
                        last_scan_lane = action.lane
                    if checkout_guard_unavailable:
                        write_event(paths.logs, "checkout_guard_retry_deferred", seconds=CHECKOUT_GUARD_RETRY_SECONDS)
                        if max_cycles is not None:
                            return 1
                        time.sleep(CHECKOUT_GUARD_RETRY_SECONDS)
                        continue
                    consecutive_errors = 0
                    rate_limit_streak = 0
                    metrics = planner.metrics(now=time.monotonic())
                    _heartbeat(
                        paths,
                        Status.ARMED,
                        "scan completed",
                        open_dates=len(planner.open_dates),
                        scanned_date=scanned_date,
                        eligible_shows=eligible_count,
                        match=None,
                        errors=0,
                        last_scan_lane=last_scan_lane,
                        **metrics,
                    )
                    completed_cycles += 1
                    if max_cycles is not None and completed_cycles >= max_cycles:
                        return 0
                except LoginRequired as exc:
                    _heartbeat(paths, Status.LOGIN_REQUIRED, str(exc))
                    write_event(paths.logs, "login_required", error=str(exc))
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
