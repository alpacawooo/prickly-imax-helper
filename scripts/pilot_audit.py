#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PILOT_IDS = ("A", "B", "C")
REQUIRED_STEPS = (
    "github_invite_accepted",
    "checksum_verified",
    "user_scoped_install",
    "dedicated_chrome_login",
    "test_email_received",
    "dry_run_passed",
    "armed_status_seen",
    "doctor_passed",
    "diagnose_redaction_confirmed",
    "stop_passed",
    "update_preserved_config_and_profile",
    "restart_returned_armed",
    "uninstall_program_only_passed",
)
MAIL_BRIDGES = {"macos": "apple_mail", "windows": "classic_outlook"}
RECIPIENT_PROVIDERS = {"gmail", "naver", "icloud", "other"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def template(pilot_id: str) -> dict[str, Any]:
    os_family = "windows" if pilot_id == "C" else "macos"
    return {
        "pilot_id": pilot_id,
        "os_family": os_family,
        "os_version": "",
        "standard_non_admin_user": os_family == "macos",
        "mail_bridge": MAIL_BRIDGES[os_family],
        "recipient_provider": "",
        "independent_public_ip_confirmed": False,
        "no_other_helper_on_public_ip_confirmed": False,
        "developer_intervention_required": False,
        "credentials_and_payment_data_stayed_local": False,
        "release_archive_sha256": "",
        "redacted_diagnose_sha256": "",
        "completed_at": "",
        "steps": {step: False for step in REQUIRED_STEPS},
    }


def write_private_json(target: Path, value: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def validate_record(value: dict[str, Any], expected_id: str) -> list[str]:
    errors: list[str] = []
    if value.get("pilot_id") != expected_id:
        errors.append(f"pilot_id must be {expected_id}")
    os_family = str(value.get("os_family", ""))
    if os_family not in MAIL_BRIDGES:
        errors.append("os_family must be macos or windows")
    expected_family = "windows" if expected_id == "C" else "macos"
    if os_family != expected_family:
        errors.append(f"pilot {expected_id} must use {expected_family}")
    if not str(value.get("os_version", "")).strip():
        errors.append("os_version is required")
    if os_family in MAIL_BRIDGES and value.get("mail_bridge") != MAIL_BRIDGES[os_family]:
        errors.append(f"mail_bridge must be {MAIL_BRIDGES[os_family]}")
    if os_family == "windows" and value.get("standard_non_admin_user") is not True:
        errors.append("Windows evidence must use a standard non-admin user")
    if value.get("recipient_provider") not in RECIPIENT_PROVIDERS:
        errors.append("recipient_provider must be gmail, naver, icloud, or other")
    for field in (
        "independent_public_ip_confirmed",
        "no_other_helper_on_public_ip_confirmed",
        "credentials_and_payment_data_stayed_local",
    ):
        if value.get(field) is not True:
            errors.append(f"{field} must be true")
    if value.get("developer_intervention_required") is not False:
        errors.append("developer_intervention_required must be false")
    for field in ("release_archive_sha256", "redacted_diagnose_sha256"):
        if not SHA256.fullmatch(str(value.get(field, ""))):
            errors.append(f"{field} must be a lowercase SHA-256 digest")
    try:
        completed = datetime.fromisoformat(str(value.get("completed_at", "")))
        if completed.tzinfo is None:
            raise ValueError
    except ValueError:
        errors.append("completed_at must be an ISO timestamp with timezone")
    steps = value.get("steps")
    if not isinstance(steps, dict):
        errors.append("steps must be an object")
    else:
        missing = [step for step in REQUIRED_STEPS if steps.get(step) is not True]
        unknown = sorted(set(steps) - set(REQUIRED_STEPS))
        if missing:
            errors.append("incomplete steps: " + ", ".join(missing))
        if unknown:
            errors.append("unknown steps: " + ", ".join(unknown))
    serialized = json.dumps(value, ensure_ascii=False)
    if "@" in serialized:
        errors.append("evidence must not contain an email address")
    unix_home_marker = "/" + "Users/"
    windows_home_pattern = re.compile(r"[A-Z]:\\" + re.escape("Users\\"))
    if unix_home_marker in serialized or windows_home_pattern.search(serialized):
        errors.append("evidence must not contain an absolute user path")
    return errors


def verify(directory: Path) -> dict[str, Any]:
    failures: dict[str, list[str]] = {}
    records: list[dict[str, Any]] = []
    for pilot_id in PILOT_IDS:
        target = directory / f"pilot-{pilot_id}.json"
        try:
            value = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("root must be an object")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures[pilot_id] = [f"could not read {target.name}: {exc}"]
            continue
        errors = validate_record(value, pilot_id)
        if errors:
            failures[pilot_id] = errors
        records.append(value)
    families = {str(record.get("os_family", "")) for record in records}
    if not {"macos", "windows"}.issubset(families):
        failures.setdefault("cohort", []).append("cohort must include macOS and Windows")
    providers = [str(record.get("recipient_provider", "")) for record in records]
    if len(set(providers)) != len(PILOT_IDS):
        failures.setdefault("cohort", []).append("three pilots must use three different recipient providers")
    return {
        "ok": not failures and len(records) == len(PILOT_IDS),
        "pilot_count": len(records),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify privacy-safe Prickly private-pilot evidence")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--output", type=Path, required=True)
    audit = commands.add_parser("verify")
    audit.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    directory = (args.output if args.command == "init" else args.input).expanduser().resolve()
    if args.command == "init":
        for pilot_id in PILOT_IDS:
            target = directory / f"pilot-{pilot_id}.json"
            if target.exists():
                raise SystemExit(f"refusing to overwrite {target}")
            write_private_json(target, template(pilot_id))
        print(json.dumps({"ok": True, "directory": str(directory), "files": 3}, ensure_ascii=False, indent=2))
        return 0
    result = verify(directory)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
