from __future__ import annotations

import os
import platform
import subprocess


MAC_LABEL = "ai.prickly.imax-helper"
WINDOWS_TASK = "Prickly IMAX Helper"


def start_service() -> subprocess.CompletedProcess[str]:
    if platform.system() == "Darwin":
        command = ["/bin/launchctl", "kickstart", "-p", f"gui/{os.getuid()}/{MAC_LABEL}"]
    elif platform.system() == "Windows":
        command = ["schtasks.exe", "/Run", "/TN", WINDOWS_TASK]
    else:
        raise RuntimeError("resident service is unsupported on this operating system")
    return subprocess.run(command, text=True, capture_output=True)
