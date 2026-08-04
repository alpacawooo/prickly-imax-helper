"""Cross-process request pacing for CGV traffic.

Every CGV request must acquire this budget immediately before it starts.  The
state file and advisory lock are shared by the monitor, browser staging, status
probes, and checkout so separate processes cannot exceed the approved IP-wide
rate accidentally.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from .locks import locked_file


class RequestBudget:
    def __init__(
        self,
        root: str | Path,
        *,
        minimum_interval_seconds: float = 1.0,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if minimum_interval_seconds < 1.0:
            raise ValueError("CGV request interval must be at least one second")
        self.root = Path(root).expanduser().resolve()
        self.minimum_interval_seconds = minimum_interval_seconds
        self.clock = clock
        self.sleeper = sleeper
        self.state_path = self.root / "state" / "request-budget.json"
        self.lock_path = self.root / "state" / "request-budget.lock"

    def _prepare(self) -> None:
        state_dir = self.state_path.parent
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(state_dir, 0o700)

    def _read(self) -> dict[str, float]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"next_allowed_at": 0.0, "cooldown_until": 0.0}
        return {
            "next_allowed_at": float(raw.get("next_allowed_at", 0.0)),
            "cooldown_until": float(raw.get("cooldown_until", 0.0)),
        }

    def _write(self, state: dict[str, float]) -> None:
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, self.state_path)

    def acquire(self) -> float:
        """Wait for the shared budget and reserve one request start time.

        Returns the number of seconds waited.  The lock remains held while
        waiting so another local process cannot reserve the same time slot.
        """

        self._prepare()
        with locked_file(self.lock_path):
            state = self._read()
            now = self.clock()
            target = max(state["next_allowed_at"], state["cooldown_until"])
            waited = max(0.0, target - now)
            if waited:
                self.sleeper(waited)
            reserved_at = max(self.clock(), target)
            state["next_allowed_at"] = reserved_at + self.minimum_interval_seconds
            self._write(state)
            return waited

    def defer(self, seconds: float) -> float:
        """Apply a shared cooldown, for example after HTTP 429.

        Returns the absolute UNIX timestamp at which traffic may resume.
        """

        if seconds <= 0:
            raise ValueError("cooldown must be positive")
        self._prepare()
        with locked_file(self.lock_path):
            state = self._read()
            cooldown_until = self.clock() + seconds
            state["cooldown_until"] = max(state["cooldown_until"], cooldown_until)
            state["next_allowed_at"] = max(state["next_allowed_at"], state["cooldown_until"])
            self._write(state)
            return state["cooldown_until"]
