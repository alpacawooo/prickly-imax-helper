from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @classmethod
    def default(cls) -> "RuntimePaths":
        configured = os.environ.get("PRICKLY_IMAX_HOME")
        return cls(Path(configured).expanduser() if configured else Path.home() / ".prickly-imax-helper")

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def heartbeat(self) -> Path:
        return self.state_dir / "heartbeat.json"

    @property
    def checkout(self) -> Path:
        return self.state_dir / "checkout.json"

    @property
    def stop_requested(self) -> Path:
        return self.state_dir / "stop-requested"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def browser_profile(self) -> Path:
        return self.root / "browser-profile"

    def prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        for path in (self.state_dir, self.logs, self.browser_profile):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)
