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
from pathlib import Path


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    installer = (root / "scripts" / "Install.command").read_text(encoding="utf-8")
    installer_version = re.search(r"^APP_VERSION=([^\s]+)$", installer, re.MULTILINE)
    if not installer_version or installer_version.group(1) != args.version:
        raise SystemExit("Install.command APP_VERSION does not match the release version")
    authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
    required = {"approved_at", "scope", "request_limit_scope", "max_requests_per_ip_per_second"}
    missing = sorted(required - authorization.keys())
    if missing:
        raise SystemExit("authorization metadata missing: " + ", ".join(missing))
    if authorization["request_limit_scope"] != "public_ip":
        raise SystemExit("request_limit_scope must be public_ip")
    try:
        request_rate = float(authorization["max_requests_per_ip_per_second"])
    except (TypeError, ValueError) as exc:
        raise SystemExit("max_requests_per_ip_per_second must be numeric") from exc
    if not 0 < request_rate <= 1.0:
        raise SystemExit("release metadata exceeds the approved request rate")
    required_scopes = {
        "automated_availability_query",
        "automated_seat_selection",
        "voucher_submission",
        "private_beta_distribution",
    }
    missing_scopes = sorted(required_scopes - set(authorization["scope"]))
    if missing_scopes:
        raise SystemExit("authorization scope missing: " + ", ".join(missing_scopes))
    document_sha256 = authorization.get("document_sha256")
    authorization_reference = authorization.get("authorization_reference")
    if not document_sha256 and not authorization_reference:
        raise SystemExit("authorization_reference or document_sha256 is required")
    if document_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", str(document_sha256)):
        raise SystemExit("document_sha256 must be a 64-character hexadecimal SHA-256 digest")
    if authorization_reference:
        reference = str(authorization_reference).strip()
        if not 3 <= len(reference) <= 200 or any(character in reference for character in "\r\n"):
            raise SystemExit("authorization_reference must be a single public-safe line of 3-200 characters")
    try:
        from datetime import date

        date.fromisoformat(str(authorization["approved_at"]))
    except ValueError as exc:
        raise SystemExit("approved_at must be an ISO date (YYYY-MM-DD)") from exc

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"prickly-imax-helper-{args.version}.tar.gz"
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
        (stage / "AUTHORIZATION.json").write_text(json.dumps(authorization, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for command in (stage / "scripts" / "Install.command", stage / "scripts" / "Update.command", stage / "scripts" / "Uninstall.command"):
            os.chmod(command, 0o755)
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(stage, arcname=stage.name)
    digest = hash_file(archive)
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(json.dumps({"archive": str(archive), "sha256": digest, "checksum": str(checksum)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
