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

LOCKED_ODYSSEY_FIELDS = (
    "movie",
    "theater",
    "format",
    "party_size",
    "dates",
    "time_rules",
    "rows",
    "edge_exclusion",
    "preference",
    "prevent_duplicate_booking",
    "allow_cancel_existing",
    "allow_change_existing",
    "payment",
    "authorization",
)


def validate_config(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = ("movie", "theater", "format", "party_size", "rows", "edge_exclusion", "time_rules", "payment")
    for key in required:
        if key not in value:
            errors.append(f"missing {key}")
    for key in LOCKED_ODYSSEY_FIELDS:
        if value.get(key) != ODYSSEY[key]:
            errors.append(f"private beta requires exact Odyssey preset field: {key}")
    party = value.get("party_size")
    if not isinstance(party, int) or not 1 <= party <= 8:
        errors.append("party_size must be an integer from 1 to 8")
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows or any(not re.fullmatch(r"[A-Z]+", str(row)) for row in rows):
        errors.append("rows must be uppercase row labels")
    edge = value.get("edge_exclusion")
    if not isinstance(edge, (int, float)) or not 0 <= edge < 0.5:
        errors.append("edge_exclusion must be at least 0 and below 0.5")
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
    if not value.get("prevent_duplicate_booking", True):
        errors.append("prevent_duplicate_booking must be true")
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
    if not isinstance(email, str) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append("notification.email must be a valid email address")
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
