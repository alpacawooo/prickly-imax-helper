from __future__ import annotations

import os
import platform
import shutil
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

OUTLOOK_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$recipient = [Environment]::GetEnvironmentVariable('PRICKLY_NOTIFY_TO')
$subject = [Environment]::GetEnvironmentVariable('PRICKLY_NOTIFY_SUBJECT')
$body = [Environment]::GetEnvironmentVariable('PRICKLY_NOTIFY_BODY')
$outlook = New-Object -ComObject Outlook.Application
$mail = $outlook.CreateItem(0)
$mail.To = $recipient
$mail.Subject = $subject
$mail.Body = $body
$mail.Send()
'''

WINDOWS_TOAST_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$title = [Environment]::GetEnvironmentVariable('PRICKLY_NOTIFY_TITLE')
$message = [Environment]::GetEnvironmentVariable('PRICKLY_NOTIFY_MESSAGE')
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$safeTitle = [System.Security.SecurityElement]::Escape($title)
$safeMessage = [System.Security.SecurityElement]::Escape($message)
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$safeTitle</text><text>$safeMessage</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Prickly IMAX Helper').Show($toast)
'''


def powershell_executable() -> str | None:
    return shutil.which("powershell.exe") or shutil.which("powershell")


def notification_method() -> str:
    if platform.system() == "Darwin":
        return "apple_mail"
    if platform.system() == "Windows":
        return "outlook_desktop"
    return "unsupported"


def notification_label() -> str:
    return "Apple Mail" if platform.system() == "Darwin" else "Outlook 데스크톱"


def _run_powershell(script: str, environment: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    powershell = powershell_executable()
    if not powershell:
        raise RuntimeError("Windows PowerShell is not available")
    return subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        text=True,
        capture_output=True,
        timeout=timeout,
        env={**os.environ, **environment},
    )


def send_email(recipient: str, subject: str, body: str, timeout: int = 20) -> None:
    system = platform.system()
    if system == "Darwin":
        process = subprocess.run(
            ["/usr/bin/osascript", "-e", MAIL_SCRIPT, recipient, subject, body],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        failure = "Apple Mail notification failed"
    elif system == "Windows":
        process = _run_powershell(
            OUTLOOK_SCRIPT,
            {
                "PRICKLY_NOTIFY_TO": recipient,
                "PRICKLY_NOTIFY_SUBJECT": subject,
                "PRICKLY_NOTIFY_BODY": body,
            },
            timeout,
        )
        failure = "Outlook desktop notification failed"
    else:
        raise RuntimeError("email notification is not supported on this operating system")
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout).strip() or failure)


def show_notification(title: str, message: str, timeout: int = 10) -> None:
    if platform.system() == "Darwin":
        script = 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run'
        process = subprocess.run(
            ["/usr/bin/osascript", "-e", script, title, message],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    elif platform.system() == "Windows":
        process = _run_powershell(
            WINDOWS_TOAST_SCRIPT,
            {"PRICKLY_NOTIFY_TITLE": title, "PRICKLY_NOTIFY_MESSAGE": message},
            timeout,
        )
    else:
        return
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout).strip() or "desktop notification failed")
