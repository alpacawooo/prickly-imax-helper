#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path


FORBIDDEN_RUNTIME_NAMES = {
    ".env",
    "browser.json",
    "checkout.json",
    "config.json",
    "heartbeat.json",
    "request-budget.json",
}
FORBIDDEN_RUNTIME_DIRECTORIES = {"browser-profile", "logs", "state"}
FORBIDDEN_SECRET_SUFFIXES = {".cookie", ".secret", ".token"}
REQUIRED_AUTHORIZATION_FIELDS = {
    "approved_at",
    "scope",
    "request_limit_scope",
    "max_requests_per_ip_per_second",
}
OPTIONAL_AUTHORIZATION_FIELDS = {"authorization_reference", "document_sha256"}
REQUIRED_AUTHORIZATION_SCOPES = {
    "automated_availability_query",
    "automated_seat_selection",
    "voucher_submission",
    "private_beta_distribution",
}


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_stage(stage: Path) -> None:
    """Reject local runtime state and developer-specific paths before archiving."""

    problems: list[str] = []
    for item in stage.rglob("*"):
        relative = item.relative_to(stage)
        if item.is_dir():
            if item.name in FORBIDDEN_RUNTIME_DIRECTORIES:
                problems.append(f"forbidden runtime directory: {relative}")
            continue
        if item.name in FORBIDDEN_RUNTIME_NAMES or item.suffix.lower() in FORBIDDEN_SECRET_SUFFIXES:
            problems.append(f"forbidden runtime file: {relative}")
            continue
        if item.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = item.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        mac_user_prefix = "/" + "Users" + "/"
        if mac_user_prefix in text or re.search(r"[A-Za-z]:\\Users\\[^\\\r\n]+", text):
            problems.append(f"developer-specific absolute path: {relative}")
    if problems:
        raise SystemExit("release stage privacy check failed: " + "; ".join(problems))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if args.version != project_version:
        raise SystemExit(f"release version {args.version} does not match pyproject version {project_version}")
    mac_installer = (root / "scripts" / "Install.command").read_text(encoding="utf-8")
    mac_version = re.search(r"^APP_VERSION=([^\s]+)$", mac_installer, re.MULTILINE)
    if not mac_version or mac_version.group(1) != args.version:
        raise SystemExit("Install.command APP_VERSION does not match the release version")
    windows_installer = (root / "scripts" / "Install.ps1").read_text(encoding="utf-8")
    windows_version = re.search(r'^\$AppVersion = "([^"]+)"$', windows_installer, re.MULTILINE)
    if not windows_version or windows_version.group(1) != args.version:
        raise SystemExit("Install.ps1 AppVersion does not match the release version")
    authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
    if not isinstance(authorization, dict):
        raise SystemExit("authorization metadata must be a JSON object")
    allowed_fields = REQUIRED_AUTHORIZATION_FIELDS | OPTIONAL_AUTHORIZATION_FIELDS
    unknown = sorted(set(authorization) - allowed_fields)
    if unknown:
        raise SystemExit("authorization metadata contains non-public or unknown fields: " + ", ".join(unknown))
    missing = sorted(REQUIRED_AUTHORIZATION_FIELDS - authorization.keys())
    if missing:
        raise SystemExit("authorization metadata missing: " + ", ".join(missing))
    if authorization["request_limit_scope"] != "public_ip":
        raise SystemExit("request_limit_scope must be public_ip")
    if isinstance(authorization["max_requests_per_ip_per_second"], bool):
        raise SystemExit("max_requests_per_ip_per_second must be numeric")
    try:
        request_rate = float(authorization["max_requests_per_ip_per_second"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("max_requests_per_ip_per_second must be numeric") from exc
    if not 0 < request_rate <= 1.0:
        raise SystemExit("release metadata exceeds the approved request rate")
    scopes = authorization["scope"]
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise SystemExit("authorization scope must be a JSON string list")
    scope_set = set(scopes)
    missing_scopes = sorted(REQUIRED_AUTHORIZATION_SCOPES - scope_set)
    if missing_scopes:
        raise SystemExit("authorization scope missing: " + ", ".join(missing_scopes))
    extra_scopes = sorted(scope_set - REQUIRED_AUTHORIZATION_SCOPES)
    if extra_scopes:
        raise SystemExit("authorization scope contains unsupported capabilities: " + ", ".join(extra_scopes))
    document_sha256 = authorization.get("document_sha256")
    authorization_reference = authorization.get("authorization_reference")
    if not document_sha256 and not authorization_reference:
        raise SystemExit("authorization_reference or document_sha256 is required")
    if document_sha256 and (not isinstance(document_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", document_sha256)):
        raise SystemExit("document_sha256 must be a 64-character hexadecimal SHA-256 digest")
    if authorization_reference:
        if not isinstance(authorization_reference, str):
            raise SystemExit("authorization_reference must be text")
        reference = authorization_reference.strip()
        if not 3 <= len(reference) <= 200 or any(ord(character) < 32 or ord(character) == 127 for character in reference):
            raise SystemExit("authorization_reference must be a single public-safe line of 3-200 characters")
        placeholder_tokens = ("OPTIONAL", "REPLACE", "PLACEHOLDER", "CHANGEME", "TODO")
        if any(token in reference.upper() for token in placeholder_tokens):
            raise SystemExit("authorization_reference is still a placeholder")
    approved_at = authorization["approved_at"]
    if not isinstance(approved_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", approved_at):
        raise SystemExit("approved_at must be an ISO date (YYYY-MM-DD)")
    try:
        from datetime import date

        date.fromisoformat(approved_at)
    except ValueError as exc:
        raise SystemExit("approved_at must be an ISO date (YYYY-MM-DD)") from exc

    public_authorization = {
        "approved_at": approved_at,
        "scope": sorted(REQUIRED_AUTHORIZATION_SCOPES),
        "request_limit_scope": "public_ip",
        "max_requests_per_ip_per_second": request_rate,
    }
    if document_sha256:
        public_authorization["document_sha256"] = str(document_sha256).lower()
    if authorization_reference:
        public_authorization["authorization_reference"] = reference

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"prickly-imax-helper-{args.version}.tar.gz"
    windows_archive = output / f"prickly-imax-helper-{args.version}.zip"
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary) / f"prickly-imax-helper-{args.version}"
        stage.mkdir()
        for name in ("runtime", "scripts", "pyproject.toml", "uv.lock", "README.md", "LICENSE"):
            source = root / name
            destination = stage / name
            if source.is_dir():
                shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
            else:
                shutil.copy2(source, destination)
        (stage / "AUTHORIZATION.json").write_text(
            json.dumps(public_authorization, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        validate_stage(stage)
        for command in (stage / "scripts" / "Install.command", stage / "scripts" / "Update.command", stage / "scripts" / "Uninstall.command"):
            os.chmod(command, 0o755)
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(stage, arcname=stage.name)
        with zipfile.ZipFile(windows_archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for item in stage.rglob("*"):
                if item.is_file():
                    bundle.write(item, arcname=str(Path(stage.name) / item.relative_to(stage)))
    artifacts = []
    for operating_system, artifact in (("macos", archive), ("windows", windows_archive)):
        digest = hash_file(artifact)
        checksum = artifact.with_suffix(artifact.suffix + ".sha256")
        checksum.write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
        artifacts.append(
            {
                "operating_system": operating_system,
                "archive": str(artifact),
                "sha256": digest,
                "checksum": str(checksum),
            }
        )
    mac = artifacts[0]
    print(json.dumps({**mac, "artifacts": artifacts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
