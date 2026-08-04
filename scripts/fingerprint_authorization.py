#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


SCOPES = [
    "automated_availability_query",
    "automated_seat_selection",
    "voucher_submission",
    "private_beta_distribution",
]


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create public-safe authorization release metadata without copying the source document")
    parser.add_argument("document", type=Path)
    parser.add_argument("--approved-at", required=True)
    parser.add_argument(
        "--reference",
        help="Optional public-safe approval, contract, or ticket reference. Never pass credentials or private document text.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.document.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"authorization source not found: {source}")
    payload = {
        "approved_at": args.approved_at,
        "scope": SCOPES,
        "request_limit_scope": "public_ip",
        "max_requests_per_ip_per_second": 1.0,
        "document_sha256": fingerprint(source),
    }
    if args.reference:
        payload["authorization_reference"] = args.reference.strip()
    target = args.output.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, target)
    print(json.dumps({"metadata": str(target), "source_copied": False, "document_sha256": payload["document_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
