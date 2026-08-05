from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .paths import RuntimePaths


CGV_BOOKING_URL = "https://cgv.co.kr/cnm/movieBook"


class BrowserError(RuntimeError):
    pass


def chrome_executable() -> Path | None:
    override = os.environ.get("PRICKLY_CHROME")
    candidates: list[Path] = [Path(override).expanduser()] if override else []
    system = platform.system()
    if system == "Darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    elif system == "Windows":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    else:
        candidates.extend(Path(path) for path in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium"))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


CHROME = chrome_executable()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_url(url: str, timeout: float = 1.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _ensure_browser_tab(port: int, url: str, *, wait_seconds: float = 2.0) -> None:
    """Wait for Chrome's startup tab, then create it if Chrome dropped the URL."""
    expected_host = urllib.parse.urlparse(url).hostname or ""
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            tabs = _json_url(f"http://127.0.0.1:{port}/json/list")
        except (OSError, urllib.error.URLError):
            tabs = []
        if any(expected_host in str(tab.get("url", "")) for tab in tabs):
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe='')}",
        method="PUT",
    )
    try:
        urllib.request.urlopen(request, timeout=2).close()
    except urllib.error.URLError as exc:
        raise BrowserError(f"Could not open the dedicated Chrome tab: {exc}") from exc


def browser_info(paths: RuntimePaths) -> dict[str, Any]:
    info_path = paths.state_dir / "browser.json"
    try:
        value = json.loads(info_path.read_text(encoding="utf-8"))
        port = int(value["port"])
        pid = int(value["pid"])
        if platform.system() == "Windows":
            powershell = shutil.which("powershell.exe") or shutil.which("powershell")
            if not powershell:
                return {}
            process = subprocess.run(
                [
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine",
                ],
                text=True,
                capture_output=True,
                timeout=3,
            )
            expected_profile = f"--user-data-dir={paths.browser_profile}"
            if process.returncode != 0 or expected_profile not in process.stdout:
                return {}
        else:
            process = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "command="], text=True, capture_output=True, timeout=2)
            expected_profile = f"--user-data-dir={paths.browser_profile}"
            if process.returncode != 0 or expected_profile not in process.stdout:
                return {}
        _json_url(f"http://127.0.0.1:{port}/json/version")
        return value
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError, urllib.error.URLError):
        return {}


def launch_browser(paths: RuntimePaths, url: str = CGV_BOOKING_URL, *, headless: bool = False) -> dict[str, Any]:
    chrome = chrome_executable()
    if chrome is None:
        raise BrowserError("Google Chrome is not installed in a supported location")
    paths.prepare()
    current = browser_info(paths)
    if current:
        _ensure_browser_tab(int(current["port"]), url, wait_seconds=0)
        return current
    port = _free_port()
    arguments = [
            str(chrome),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={paths.browser_profile}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
    if headless:
        arguments.append("--headless=new")
    arguments.append(url)
    process_options: dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if platform.system() == "Windows":
        process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        process_options["start_new_session"] = True
    process = subprocess.Popen(arguments, **process_options)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            _json_url(f"http://127.0.0.1:{port}/json/version")
            break
        except (OSError, urllib.error.URLError):
            if process.poll() is not None:
                raise BrowserError(f"Chrome exited with code {process.returncode}")
            time.sleep(0.2)
    else:
        process.terminate()
        raise BrowserError("Chrome remote debugging did not become ready")
    _ensure_browser_tab(port, url)
    info = {"port": port, "pid": process.pid, "profile": str(paths.browser_profile)}
    target = paths.state_dir / "browser.json"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, target)
    return info
