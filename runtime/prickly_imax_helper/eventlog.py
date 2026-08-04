from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .redaction import redact


def write_event(log_dir: str | Path, event: str, **fields: Any) -> None:
    target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target_dir, 0o700)
    target = target_dir / f"{datetime.now().astimezone():%Y-%m-%d}.jsonl"
    record = redact({"at": datetime.now().astimezone().isoformat(), "event": event, **fields})
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.chmod(target, 0o600)
