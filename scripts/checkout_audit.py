#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE_ORDER = (
    "duplicate_guard_before",
    "theater",
    "date",
    "showtime",
    "party",
    "seats",
    "vouchers",
    "zero_balance",
    "duplicate_guard_final",
    "submission_ready",
    "submission",
    "mobile_ticket",
)

TERMINAL_OUTCOMES = frozenset(
    {
        "completed",
        "seat_vanished",
        "checkout_pre_submit_error",
        "blocked_duplicate",
        "blocked_payment",
        "unknown_after_submit",
        "checkout_attempt_interrupted",
    }
)

OPERATIONAL_EVENTS = (
    "rate_limited",
    "login_required",
    "monitor_error",
    "browser_closed",
    "transport_error",
    "http_error",
    "desktop_notification_failed",
    "email_failed",
)

PROHIBITED_KEYS = frozenset(
    {
        "cookie",
        "cookies",
        "authorization",
        "authorization_header",
        "voucher_number",
        "ticket_id",
        "customer_number",
        "account_number",
        "payment_detail",
        "payment_details",
    }
)
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
CUSTOMER_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{12,}(?!\d)")


def _parsed_at(event: dict[str, Any]) -> datetime:
    value = str(event.get("at", ""))
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min


def load_events(input_path: Path) -> list[dict[str, Any]]:
    source = Path(input_path)
    files = sorted(source.glob("*.jsonl")) if source.is_dir() else [source]
    events: list[dict[str, Any]] = []
    for file_path in files:
        with file_path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{file_path}:{line_number} is not a JSON object")
                events.append(value)
    return sorted(events, key=_parsed_at)


def _pair(match: Any) -> str | None:
    if not isinstance(match, dict):
        return None
    if isinstance(match.get("pair"), str):
        return match["pair"]
    seats = match.get("seats")
    if isinstance(seats, list) and seats:
        return "-".join(str(seat) for seat in seats)
    return None


def _match_key(match: Any) -> tuple[str, str, str] | None:
    if not isinstance(match, dict):
        return None
    pair = _pair(match)
    if not pair:
        return None
    return str(match.get("date", "")), str(match.get("time", "")), pair


def _classify_legacy(outcome: dict[str, Any] | None) -> str:
    if outcome is None:
        return "legacy_unknown"
    error = str(outcome.get("error", "")).lower()
    if "theater picker launcher not found" in error:
        return "theater_picker"
    if "target date is no longer open" in error:
        return "today_label"
    if "general admission count control" in error:
        return "general_party"
    return "legacy_unknown"


def _walk(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _privacy_errors(attempt_id: str, events: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for event in events:
        for path, value in _walk(event):
            key = path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
            if key in PROHIBITED_KEYS:
                errors.append(f"attempt {attempt_id} contains prohibited key {key}")
            if isinstance(value, str):
                if EMAIL_PATTERN.search(value):
                    errors.append(f"attempt {attempt_id} contains email-like value")
                if CUSTOMER_NUMBER_PATTERN.search(value):
                    errors.append(f"attempt {attempt_id} contains customer-like number")
    return list(dict.fromkeys(errors))


def build_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    instrumented: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        attempt_id = event.get("attempt_id")
        if isinstance(attempt_id, str) and attempt_id:
            instrumented[attempt_id].append(event)

    legacy_counts = Counter(
        {"theater_picker": 0, "today_label": 0, "general_party": 0, "legacy_unknown": 0}
    )
    legacy_attempts = 0
    for index, event in enumerate(events):
        if event.get("event") != "seat_match" or event.get("attempt_id"):
            continue
        legacy_attempts += 1
        outcome = events[index + 1] if index + 1 < len(events) else None
        if not (
            isinstance(outcome, dict)
            and outcome.get("event") in TERMINAL_OUTCOMES
            and not outcome.get("attempt_id")
            and _match_key(outcome.get("match")) == _match_key(event.get("match"))
        ):
            outcome = None
        legacy_counts[_classify_legacy(outcome)] += 1

    attempt_summaries: list[dict[str, Any]] = []
    for attempt_id, attempt_events in sorted(instrumented.items()):
        terminals = [event["event"] for event in attempt_events if event.get("event") in TERMINAL_OUTCOMES]
        stages = [
            {"stage": event.get("stage"), "outcome": event.get("outcome")}
            for event in attempt_events
            if event.get("event") == "checkout_stage"
        ]
        attempt_summaries.append(
            {
                "attempt_id": attempt_id,
                "terminal_outcomes": terminals,
                "stages": stages,
                "submission_starts": sum(
                    1
                    for stage in stages
                    if stage.get("stage") == "submission" and stage.get("outcome") == "started"
                ),
                "privacy_errors": _privacy_errors(attempt_id, attempt_events),
            }
        )

    operational = Counter(str(event.get("event")) for event in events)
    return {
        "attempts_total": legacy_attempts + len(attempt_summaries),
        "instrumented_attempts": len(attempt_summaries),
        "legacy_attempts": legacy_attempts,
        "legacy_classification": dict(legacy_counts),
        "attempts": attempt_summaries,
        "operational_event_counts": {name: operational[name] for name in OPERATIONAL_EVENTS},
    }


def verify_report(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    order = {stage: index for index, stage in enumerate(STAGE_ORDER)}
    for attempt in report.get("attempts", []):
        attempt_id = str(attempt.get("attempt_id", "unknown"))
        terminal_count = len(attempt.get("terminal_outcomes", []))
        if terminal_count == 0:
            errors.append(f"attempt {attempt_id} has no terminal outcome")
        elif terminal_count != 1:
            errors.append(f"attempt {attempt_id} has {terminal_count} terminal outcomes")
        last_index = -1
        for stage_event in attempt.get("stages", []):
            stage = stage_event.get("stage")
            if stage not in order:
                errors.append(f"attempt {attempt_id} has unknown stage {stage}")
                continue
            current_index = order[stage]
            if current_index < last_index:
                errors.append(f"attempt {attempt_id} stage order moved backward at {stage}")
                break
            last_index = current_index
        submission_starts = int(attempt.get("submission_starts", 0))
        if submission_starts > 1:
            errors.append(f"attempt {attempt_id} has {submission_starts} submission starts")
        errors.extend(str(error) for error in attempt.get("privacy_errors", []))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Prickly checkout attempt audit")
    parser.add_argument("command", choices=("report", "verify"))
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(load_events(args.input))
    if args.command == "report":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    errors = verify_report(report)
    result = {
        "ok": not errors,
        "attempts_total": report["attempts_total"],
        "instrumented_attempts": report["instrumented_attempts"],
        "legacy_unknown": report["legacy_classification"]["legacy_unknown"],
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
