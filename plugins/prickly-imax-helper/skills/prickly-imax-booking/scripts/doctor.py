#!/usr/bin/env python3
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def command_version(command: str, flag: str = "--version") -> dict:
    path = shutil.which(command)
    if not path:
        return {"ok": False, "path": None, "version": None}
    try:
        proc = subprocess.run([path, flag], text=True, capture_output=True, timeout=5)
        version = (proc.stdout or proc.stderr).strip().splitlines()[0]
        return {"ok": proc.returncode == 0, "path": path, "version": version}
    except Exception as exc:
        return {"ok": False, "path": path, "version": None, "error": str(exc)}


def main() -> int:
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    checks = {
        "macos": {"ok": platform.system() == "Darwin", "value": platform.platform()},
        "python": {"ok": sys.version_info >= (3, 10), "value": sys.version.split()[0]},
        "chrome": {"ok": chrome.is_file(), "path": str(chrome)},
        "launchctl": {"ok": shutil.which("launchctl") is not None, "path": shutil.which("launchctl")},
        "osascript": {"ok": Path("/usr/bin/osascript").is_file(), "path": "/usr/bin/osascript"},
    }
    required_ok = all(item["ok"] for item in checks.values())
    print(json.dumps({"status": "ok" if required_ok else "needs_setup", "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
