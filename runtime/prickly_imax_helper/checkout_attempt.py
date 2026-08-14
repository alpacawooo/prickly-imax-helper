from __future__ import annotations

import copy
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .eventlog import write_event


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


@dataclass
class CheckoutAttemptRecorder:
    log_dir: Path
    match: dict[str, Any]
    attempt_id: str
    _terminal_outcome: str | None = field(default=None, init=False)

    @classmethod
    def start(cls, log_dir: str | Path, match: dict[str, Any]) -> CheckoutAttemptRecorder:
        recorder = cls(Path(log_dir), copy.deepcopy(match), secrets.token_hex(8))
        write_event(recorder.log_dir, "seat_match", attempt_id=recorder.attempt_id, match=recorder.match)
        return recorder

    def _require_stage(self, name: str) -> None:
        if name not in STAGE_ORDER:
            raise ValueError(f"unknown checkout stage: {name}")

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        self._require_stage(name)
        started = time.monotonic()
        write_event(self.log_dir, "checkout_stage", attempt_id=self.attempt_id, stage=name, outcome="started")
        try:
            yield
        except Exception as exc:
            write_event(
                self.log_dir,
                "checkout_stage",
                attempt_id=self.attempt_id,
                stage=name,
                outcome="failed",
                elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        write_event(
            self.log_dir,
            "checkout_stage",
            attempt_id=self.attempt_id,
            stage=name,
            outcome="passed",
            elapsed_ms=max(0, round((time.monotonic() - started) * 1000)),
        )

    def mark(self, name: str, outcome: str = "passed") -> None:
        self._require_stage(name)
        if outcome not in {"started", "passed", "failed"}:
            raise ValueError(f"invalid checkout stage outcome: {outcome}")
        write_event(
            self.log_dir,
            "checkout_stage",
            attempt_id=self.attempt_id,
            stage=name,
            outcome=outcome,
        )

    def terminal(self, name: str, *, error: str | None = None) -> None:
        if name not in TERMINAL_OUTCOMES:
            raise ValueError(f"unknown checkout terminal outcome: {name}")
        if self._terminal_outcome is not None:
            raise RuntimeError(f"terminal outcome already recorded: {self._terminal_outcome}")
        fields: dict[str, Any] = {"attempt_id": self.attempt_id, "match": self.match}
        if error is not None:
            fields["error"] = error
        write_event(self.log_dir, name, **fields)
        self._terminal_outcome = name
