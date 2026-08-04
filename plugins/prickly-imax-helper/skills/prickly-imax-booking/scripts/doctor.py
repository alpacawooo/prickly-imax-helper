#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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
    system = platform.system()
    if system == "Darwin":
        chrome_candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
        service = shutil.which("launchctl")
        notifier = Path("/usr/bin/osascript") if Path("/usr/bin/osascript").is_file() else None
    elif system == "Windows":
        chrome_candidates = []
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                chrome_candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
        service = shutil.which("schtasks.exe")
        notifier = shutil.which("powershell.exe") or shutil.which("powershell")
    else:
        chrome_candidates = []
        service = None
        notifier = None
    chrome = next((candidate for candidate in chrome_candidates if candidate.is_file()), None)
    checks = {
        "operating_system": {"ok": system in {"Darwin", "Windows"}, "value": platform.platform()},
        "python": {"ok": sys.version_info >= (3, 10), "value": sys.version.split()[0]},
        "chrome": {"ok": chrome is not None, "path": str(chrome) if chrome else None},
        "resident_service": {"ok": service is not None, "path": service},
        "notification_backend": {"ok": notifier is not None, "path": str(notifier) if notifier else None},
    }
    required_ok = all(item["ok"] for item in checks.values())
    print(json.dumps({"status": "ok" if required_ok else "needs_setup", "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if required_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
