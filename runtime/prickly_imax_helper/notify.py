from __future__ import annotations

import subprocess


MAIL_SCRIPT = r'''
on run argv
  set recipientAddress to item 1 of argv
  set messageSubject to item 2 of argv
  set messageBody to item 3 of argv
  tell application "Mail"
    set outgoingMessage to make new outgoing message with properties {subject:messageSubject, content:messageBody & return & return, visible:false}
    tell outgoingMessage
      make new to recipient at end of to recipients with properties {address:recipientAddress}
      send
    end tell
  end tell
end run
'''


def send_email(recipient: str, subject: str, body: str, timeout: int = 20) -> None:
    process = subprocess.run(
        ["/usr/bin/osascript", "-e", MAIL_SCRIPT, recipient, subject, body],
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout).strip() or "Apple Mail notification failed")


def show_notification(title: str, message: str, timeout: int = 10) -> None:
    script = 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run'
    subprocess.run(
        ["/usr/bin/osascript", "-e", script, title, message],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
