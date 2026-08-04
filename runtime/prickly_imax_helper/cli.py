from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from .config import ConfigError, load_config
from .paths import RuntimePaths
from .setup_server import serve_setup
from .state import Status, read_state, transition


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prickly-imax")
    parser.add_argument("--home", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("setup")
    commands.add_parser("run")
    commands.add_parser("status")
    commands.add_parser("validate")
    commands.add_parser("stop")
    commands.add_parser("start")
    commands.add_parser("diagnose")
    commands.add_parser("dry-run")
    args = parser.parse_args(argv)
    paths = RuntimePaths(args.home.expanduser() if args.home else RuntimePaths.default().root)

    if args.command == "doctor":
        checks = {
            "configured": {"ok": paths.config.is_file(), "required": False},
            "state_directory": {"ok": paths.state_dir.is_dir(), "required": False},
            "browser_profile": {"ok": paths.browser_profile.is_dir(), "required": False},
            "chrome": {"ok": Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").is_file(), "required": True},
            "osascript": {"ok": Path("/usr/bin/osascript").is_file(), "required": True},
        }
        required_ok = all(value["ok"] for value in checks.values() if value["required"])
        print(json.dumps({"ok": required_ok, "checks": checks}, ensure_ascii=False, indent=2))
        return 0 if required_ok else 1
    if args.command == "setup":
        serve_setup(paths)
        return 0
    if args.command == "run":
        from .monitor import run

        return run(paths)
    if args.command == "dry-run":
        from .monitor import run

        return run(paths, max_cycles=1, allow_checkout=False)
    if args.command == "status":
        print(json.dumps(read_state(paths.heartbeat), ensure_ascii=False, indent=2))
        return 0
    if args.command == "diagnose":
        events = []
        for log in sorted(paths.logs.glob("*.jsonl"), reverse=True):
            try:
                lines = log.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(events) >= 20:
                    break
            if len(events) >= 20:
                break
        output = {
            "version": __import__("prickly_imax_helper").__version__,
            "status": read_state(paths.heartbeat),
            "browser_state_present": (paths.state_dir / "browser.json").is_file(),
            "recent_events": events,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        try:
            load_config(paths.config)
        except ConfigError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0
    if args.command == "stop":
        paths.prepare()
        paths.stop_requested.touch(mode=0o600, exist_ok=True)
        os.chmod(paths.stop_requested, 0o600)
        current = read_state(paths.heartbeat).get("status", Status.UNCONFIGURED.value)
        if current in {status.value for status in (Status.COMPLETED, Status.UNKNOWN_AFTER_SUBMIT, Status.STOPPED)}:
            print(json.dumps({"ok": True, "status": current}, ensure_ascii=False))
            return 0
        result = transition(paths.heartbeat, Status.STOPPED, detail="stopped by user")
        print(json.dumps({"ok": True, "status": result["status"]}, ensure_ascii=False))
        return 0
    if args.command == "start":
        try:
            load_config(paths.config)
        except ConfigError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        paths.stop_requested.unlink(missing_ok=True)
        current = read_state(paths.heartbeat).get("status", Status.UNCONFIGURED.value)
        if current in {Status.COMPLETED.value, Status.UNKNOWN_AFTER_SUBMIT.value, Status.BLOCKED_DUPLICATE.value, Status.BLOCKED_PAYMENT.value}:
            print(json.dumps({"ok": False, "error": f"terminal state {current} requires review before a new configuration"}, ensure_ascii=False))
            return 2
        if current not in {Status.UNCONFIGURED.value, Status.STOPPED.value}:
            print(json.dumps({"ok": True, "status": current, "detail": "monitor is already active or starting"}, ensure_ascii=False))
            return 0
        if current != Status.LOGIN_REQUIRED.value:
            transition(paths.heartbeat, Status.LOGIN_REQUIRED, detail="start requested by user")
        process = subprocess.run(
            ["/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/ai.prickly.imax-helper"],
            text=True,
            capture_output=True,
        )
        print(json.dumps({"ok": process.returncode == 0, "status": "starting", "detail": (process.stderr or "").strip()}, ensure_ascii=False))
        return process.returncode
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
