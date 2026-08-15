from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .presets import ODYSSEY


class ConfigError(ValueError):
    pass


REQUIRED_AUTHORIZATION = {
    "automatic_query",
    "automatic_seat_selection",
    "automatic_submission",
}

SUPPORTED_NOTIFICATION_PROVIDERS = {"gmail", "naver", "icloud", "other"}


def valid_email_address(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is not None

SUPPORTED_SEAT_PREFERENCES = {"closest_to_center", "row_order_then_left"}


def valid_clock(value: object, *, optional: bool = False) -> bool:
    if optional and value in {None, ""}:
        return True
    if not isinstance(value, str) or re.fullmatch(r"(?:[01]\d|2\d):[0-5]\d", value) is None:
        return False
    return True


def _validate_time_rules(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["time_rules must be an object"]
    errors: list[str] = []
    for day_group in ("weekday", "saturday", "sunday"):
        rule = value.get(day_group)
        if not isinstance(rule, dict):
            errors.append(f"time_rules.{day_group} must be an object")
            continue
        if rule.get("any_time") is True:
            continue
        start = rule.get("at_or_after")
        before = rule.get("before")
        if not valid_clock(start, optional=True):
            errors.append(f"time_rules.{day_group}.at_or_after must be HH:MM or empty")
        if not valid_clock(before, optional=True):
            errors.append(f"time_rules.{day_group}.before must be HH:MM or empty")
        if start and before:
            start_minutes = int(start[:2]) * 60 + int(start[3:])
            before_minutes = int(before[:2]) * 60 + int(before[3:])
            if start_minutes >= before_minutes:
                errors.append(f"time_rules.{day_group} start must be earlier than before")
    return errors


def validate_config(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = ("movie", "theater", "format", "party_size", "rows", "edge_exclusion", "time_rules", "payment")
    for key in required:
        if key not in value:
            errors.append(f"missing {key}")
    for key in ("movie", "theater", "format"):
        field = value.get(key)
        if not isinstance(field, str) or not field.strip() or len(field) > 100:
            errors.append(f"{key} must be a non-empty string of at most 100 characters")
    if isinstance(value.get("format"), str) and "imax" not in value["format"].casefold():
        errors.append("format must contain IMAX while registered_imax_voucher is the only payment method")
    party = value.get("party_size")
    if not isinstance(party, int) or not 1 <= party <= 8:
        errors.append("party_size must be an integer from 1 to 8")
    minimum_lead = value.get("minimum_lead_minutes", 180)
    if isinstance(minimum_lead, bool) or not isinstance(minimum_lead, int) or not 180 <= minimum_lead <= 1440:
        errors.append("minimum_lead_minutes must be an integer from 180 through 1440")
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows or any(not re.fullmatch(r"[A-Z]+", str(row)) for row in rows):
        errors.append("rows must be uppercase row labels")
    edge = value.get("edge_exclusion")
    if not isinstance(edge, (int, float)) or not 0 <= edge < 0.5:
        errors.append("edge_exclusion must be at least 0 and below 0.5")
    if value.get("preference") not in SUPPORTED_SEAT_PREFERENCES:
        errors.append("preference must be closest_to_center or row_order_then_left")
    errors.extend(_validate_time_rules(value.get("time_rules")))
    if value.get("dates") != "all_open":
        errors.append("dates must remain all_open")
    target = value.get("target")
    is_legacy_odyssey = all(value.get(key) == ODYSSEY[key] for key in ("movie", "theater", "format"))
    if target is None and not is_legacy_odyssey:
        errors.append("target identifiers are required for a custom movie, theater, or format")
    elif target is not None:
        if not isinstance(target, dict):
            errors.append("target must be an object")
        else:
            for key in ("company_code", "site_no", "movie_no"):
                identifier = target.get(key)
                if not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9_-]+", identifier) is None:
                    errors.append(f"target.{key} must be a safe identifier")
    payment = value.get("payment")
    if not isinstance(payment, dict):
        errors.append("payment must be an object")
    else:
        if payment.get("maximum_remaining_balance") != 0:
            errors.append("maximum_remaining_balance must be 0")
        if payment.get("voucher_count") != party:
            errors.append("voucher_count must equal party_size")
        if payment.get("method") != "registered_imax_voucher":
            errors.append("private beta supports registered_imax_voucher only")
    if value.get("allow_cancel_existing", False):
        errors.append("allow_cancel_existing must be false")
    if value.get("allow_change_existing", False):
        errors.append("allow_change_existing must be false")
    if not isinstance(value.get("prevent_duplicate_booking", True), bool):
        errors.append("prevent_duplicate_booking must be a boolean")
    rate = value.get("request_policy", {}).get("minimum_interval_seconds")
    if not isinstance(rate, (int, float)) or rate < 1.0:
        errors.append("request_policy.minimum_interval_seconds must be at least 1.0")
    cooldown = value.get("request_policy", {}).get("rate_limit_cooldown_seconds")
    if not isinstance(cooldown, (int, float)) or cooldown < 300:
        errors.append("request_policy.rate_limit_cooldown_seconds must be at least 300")
    authorization = value.get("authorization", {})
    missing_auth = sorted(key for key in REQUIRED_AUTHORIZATION if authorization.get(key) is not True)
    if missing_auth:
        errors.append("authorization must enable: " + ", ".join(missing_auth))
    consent = value.get("consent", {})
    accepted_at = consent.get("accepted_at")
    if consent.get("automatic_submission") is not True or not accepted_at:
        errors.append("recorded automatic-submission consent is required")
    elif not isinstance(accepted_at, str):
        errors.append("consent.accepted_at must be an ISO timestamp with timezone")
    else:
        try:
            accepted = datetime.fromisoformat(accepted_at)
            if accepted.tzinfo is None:
                raise ValueError
        except ValueError:
            errors.append("consent.accepted_at must be an ISO timestamp with timezone")
    if consent.get("one_active_device_per_public_ip") is not True:
        errors.append("consent.one_active_device_per_public_ip must be true")
    if consent.get("scope") != "matching-seat-once-voucher-only-zero-balance":
        errors.append("consent.scope does not match the private-beta submission boundary")
    notification = value.get("notification", {})
    method = notification.get("method")
    if method not in {"apple_mail", "outlook_desktop"}:
        errors.append("notification.method must be apple_mail or outlook_desktop")
    email = notification.get("email", "")
    if not valid_email_address(email):
        errors.append("notification.email must be a valid email address")
    recipient_provider = notification.get("recipient_provider")
    if recipient_provider is not None and recipient_provider not in SUPPORTED_NOTIFICATION_PROVIDERS:
        errors.append("notification.recipient_provider must be gmail, naver, icloud, or other")
    return errors


def load_config(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"could not read config: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("config root must be an object")
    errors = validate_config(value)
    if errors:
        raise ConfigError("; ".join(errors))
    return value


def write_config(path: str | Path, value: dict[str, Any]) -> None:
    errors = validate_config(value)
    if errors:
        raise ConfigError("; ".join(errors))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, target)
