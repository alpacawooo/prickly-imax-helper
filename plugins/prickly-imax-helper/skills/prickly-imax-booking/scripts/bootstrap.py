#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from policy import load_json, validate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--home", default=str(Path.home() / ".prickly-imax-helper"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config = load_json(args.config)
    checked = validate(config)
    if not checked["ok"]:
        print(json.dumps(checked, ensure_ascii=False, indent=2))
        return 1

    root = Path(args.home).expanduser().resolve()
    target = root / "config.json"
    if target.exists() and not args.force:
        print(json.dumps({"status": "blocked", "reason": "config exists; pass --force to replace", "path": str(target)}, ensure_ascii=False))
        return 2
    for relative in ("browser-profile", "state", "logs", "runtime"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    temp = root / "config.json.tmp"
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, target)
    print(json.dumps({"status": "configured", "root": str(root), "config": str(target)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
