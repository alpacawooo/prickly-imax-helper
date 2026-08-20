from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @classmethod
    def default(cls) -> "RuntimePaths":
        configured = os.environ.get("PRICKLY_IMAX_HOME")
        if configured:
            return cls(Path(configured).expanduser())
        if platform.system() == "Windows":
            local = os.environ.get("LOCALAPPDATA")
            return cls(Path(local) / "PricklyIMAXHelper" if local else Path.home() / "AppData" / "Local" / "PricklyIMAXHelper")
        return cls(Path.home() / ".prickly-imax-helper")

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
    def maintenance_barrier(self) -> Path:
        return self.state_dir / "update-in-progress"

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
