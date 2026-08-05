#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASELINE_NAME = "soak-baseline.json"
FAILURE_EVENTS = {"rate_limited", "monitor_error", "configuration_invalid"}
HEALTHY_STATUS = "armed"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def event_offsets(log_dir: Path) -> dict[str, int]:
    offsets: dict[str, int] = {}
    if not log_dir.is_dir():
        return offsets
    for target in sorted(log_dir.glob("*.jsonl")):
        try:
            with target.open(encoding="utf-8") as stream:
                offsets[target.name] = sum(1 for _ in stream)
        except OSError:
            continue
    return offsets


def events_since(log_dir: Path, offsets: dict[str, int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not log_dir.is_dir():
        return counts
    for target in sorted(log_dir.glob("*.jsonl")):
        start = max(int(offsets.get(target.name, 0)), 0)
        try:
            with target.open(encoding="utf-8") as stream:
                for index, line in enumerate(stream):
                    if index < start:
                        continue
                    try:
                        event = str(json.loads(line).get("event", ""))
                    except (json.JSONDecodeError, AttributeError):
                        event = "invalid_log_record"
                    if event:
                        counts[event] = counts.get(event, 0) + 1
        except OSError:
            counts["log_read_error"] = counts.get("log_read_error", 0) + 1
    return counts


def process_memory(home: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,rss=,command="],
        text=True,
        capture_output=True,
        check=True,
    )
    roles: dict[str, dict[str, int]] = {}
    home_text = str(home)
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3:
            continue
        pid_text, rss_text, command = fields
        if home_text not in command or int(pid_text) == os.getpid():
            continue
        if "playwright" in command and "run-driver" in command:
            role = "driver"
        elif "prickly-imax" in command and command.rstrip().endswith(" run"):
            role = "monitor"
        elif "Google Chrome" in command and "browser-profile" in command:
            role = "browser"
        else:
            continue
        entry = roles.setdefault(role, {"count": 0, "rss_kib": 0})
        entry["count"] += 1
        entry["rss_kib"] += int(rss_text)
    return roles


def capture(home: Path, *, started_at: datetime | None = None) -> dict[str, Any]:
    heartbeat_path = home / "state" / "heartbeat.json"
    heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    captured_at = now_utc()
    heartbeat_at = parse_time(str(heartbeat.get("updated_at", "1970-01-01T00:00:00+00:00")))
    return {
        "started_at": (started_at or captured_at).isoformat(),
        "captured_at": captured_at.isoformat(),
        "status": str(heartbeat.get("status", "missing")),
        "heartbeat_age_seconds": max((captured_at - heartbeat_at).total_seconds(), 0.0),
        "processes": process_memory(home),
        "event_offsets": event_offsets(home / "logs"),
    }


def evaluate(
    baseline: dict[str, Any],
    current: dict[str, Any],
    new_events: dict[str, int],
    *,
    minimum_seconds: float = 86_400.0,
) -> list[str]:
    errors: list[str] = []
    elapsed = (parse_time(current["captured_at"]) - parse_time(baseline["started_at"])).total_seconds()
    if elapsed < minimum_seconds:
        errors.append(f"soak duration is only {elapsed:.0f}s; need {minimum_seconds:.0f}s")
    if current.get("status") != HEALTHY_STATUS:
        errors.append(f"runtime status is {current.get('status')}, not {HEALTHY_STATUS}")
    if float(current.get("heartbeat_age_seconds", 10**9)) > 120.0:
        errors.append("heartbeat is older than 120s")
    monitor_count = int(current.get("processes", {}).get("monitor", {}).get("count", 0))
    if monitor_count != 1:
        errors.append(f"expected exactly one monitor process, found {monitor_count}")
    for event in sorted(FAILURE_EVENTS):
        if int(new_events.get(event, 0)):
            errors.append(f"observed {new_events[event]} {event} event(s)")
    for role in ("monitor", "driver", "browser"):
        before = int(baseline.get("processes", {}).get(role, {}).get("rss_kib", 0))
        after = int(current.get("processes", {}).get(role, {}).get("rss_kib", 0))
        if before and after > before * 1.5 and after - before > 65_536:
            errors.append(f"{role} RSS grew from {before}KiB to {after}KiB")
    return errors


def write_private_json(target: Path, value: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record or verify a redacted Prickly 24-hour soak snapshot")
    parser.add_argument("mode", choices=("start", "verify"))
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--minimum-seconds", type=float, default=86_400.0)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    baseline_path = home / "state" / BASELINE_NAME
    if args.mode == "start":
        baseline = capture(home)
        if baseline["status"] != HEALTHY_STATUS:
            raise SystemExit(f"cannot start soak while status is {baseline['status']}")
        if baseline.get("processes", {}).get("monitor", {}).get("count") != 1:
            raise SystemExit("cannot start soak without exactly one monitor process")
        write_private_json(baseline_path, baseline)
        print(json.dumps({"ok": True, "mode": "start", "baseline": str(baseline_path)}, indent=2))
        return 0
    if not baseline_path.is_file():
        raise SystemExit("soak baseline is missing; run start first")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = capture(home, started_at=parse_time(baseline["started_at"]))
    new_events = events_since(home / "logs", baseline.get("event_offsets", {}))
    errors = evaluate(baseline, current, new_events, minimum_seconds=args.minimum_seconds)
    print(
        json.dumps(
            {
                "ok": not errors,
                "mode": "verify",
                "status": current["status"],
                "heartbeat_age_seconds": round(float(current["heartbeat_age_seconds"]), 1),
                "processes": current["processes"],
                "new_failure_events": {key: new_events.get(key, 0) for key in sorted(FAILURE_EVENTS)},
                "errors": errors,
            },
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
