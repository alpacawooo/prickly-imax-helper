from __future__ import annotations

import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class Status(str, Enum):
    UNCONFIGURED = "unconfigured"
    LOGIN_REQUIRED = "login_required"
    ARMED = "armed"
    STAGING = "staging"
    SUBMITTING = "submitting"
    COMPLETED = "completed"
    RECOVERING = "recovering"
    RATE_LIMITED = "rate_limited"
    BLOCKED_DUPLICATE = "blocked_duplicate"
    BLOCKED_PAYMENT = "blocked_payment"
    UNKNOWN_AFTER_SUBMIT = "unknown_after_submit"
    FATAL = "fatal"
    STOPPED = "stopped"


TERMINAL = {
    Status.COMPLETED,
    Status.BLOCKED_DUPLICATE,
    Status.BLOCKED_PAYMENT,
    Status.UNKNOWN_AFTER_SUBMIT,
    Status.FATAL,
    Status.STOPPED,
}

ALLOWED: dict[Status, set[Status]] = {
    Status.UNCONFIGURED: {Status.LOGIN_REQUIRED, Status.STOPPED, Status.FATAL},
    Status.LOGIN_REQUIRED: {Status.ARMED, Status.STOPPED, Status.FATAL},
    Status.ARMED: {Status.LOGIN_REQUIRED, Status.STAGING, Status.RECOVERING, Status.RATE_LIMITED, Status.BLOCKED_DUPLICATE, Status.STOPPED, Status.FATAL},
    Status.STAGING: {Status.SUBMITTING, Status.ARMED, Status.BLOCKED_DUPLICATE, Status.BLOCKED_PAYMENT, Status.RECOVERING, Status.STOPPED, Status.FATAL},
    Status.SUBMITTING: {Status.COMPLETED, Status.UNKNOWN_AFTER_SUBMIT},
    Status.RECOVERING: {Status.ARMED, Status.LOGIN_REQUIRED, Status.RATE_LIMITED, Status.STOPPED, Status.FATAL},
    Status.RATE_LIMITED: {Status.ARMED, Status.LOGIN_REQUIRED, Status.STOPPED, Status.FATAL},
    # A fresh, consented setup or an explicit reviewed recovery may re-arm these
    # pre-submit blocks. Submission-boundary states remain intentionally terminal.
    Status.BLOCKED_DUPLICATE: {Status.LOGIN_REQUIRED},
    Status.BLOCKED_PAYMENT: {Status.LOGIN_REQUIRED},
    Status.STOPPED: {Status.LOGIN_REQUIRED},
    Status.FATAL: {Status.LOGIN_REQUIRED},
}


class InvalidTransition(RuntimeError):
    pass


def read_state(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def transition(path: str | Path, target: Status, *, detail: str = "", **fields: Any) -> dict[str, Any]:
    destination = Path(path)
    current_data = read_state(destination)
    current = Status(current_data.get("status", Status.UNCONFIGURED.value))
    if target != current and target not in ALLOWED.get(current, set()):
        raise InvalidTransition(f"{current.value} -> {target.value} is not allowed")
    result = {
        **current_data,
        **fields,
        "status": target.value,
        "detail": detail,
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = destination.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, destination)
    return result
