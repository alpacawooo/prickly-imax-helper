#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path


WEEKDAYS = "월화수목금토일"
LOCKED_SAFETY = {
    "dates": "all_open",
    "prevent_duplicate_booking": True,
    "allow_cancel_existing": False,
    "allow_change_existing": False,
    "authorization": {
        "automatic_query": True,
        "automatic_seat_selection": True,
        "automatic_submission": True,
    },
}


class PolicyError(ValueError):
    pass


def load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(config: dict) -> dict:
    errors: list[str] = []
    for key in ("movie", "theater", "format", "party_size", "rows", "edge_exclusion", "time_rules", "payment"):
        if key not in config:
            errors.append(f"missing {key}")
    for key, expected in LOCKED_SAFETY.items():
        if config.get(key) != expected:
            errors.append(f"private beta requires fixed safety field: {key}")
    for key in ("movie", "theater", "format"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            errors.append(f"{key} must be a non-empty string")
    if isinstance(config.get("format"), str) and "imax" not in config["format"].casefold():
        errors.append("format must contain IMAX while registered_imax_voucher is the only payment method")
    party = config.get("party_size")
    if not isinstance(party, int) or party < 1 or party > 8:
        errors.append("party_size must be an integer from 1 to 8")
    minimum_lead = config.get("minimum_lead_minutes", 180)
    if isinstance(minimum_lead, bool) or not isinstance(minimum_lead, int) or not 180 <= minimum_lead <= 1440:
        errors.append("minimum_lead_minutes must be an integer from 180 through 1440")
    rows = config.get("rows")
    if not isinstance(rows, list) or not rows or any(not re.fullmatch(r"[A-Z]+", str(row)) for row in rows):
        errors.append("rows must be a non-empty array of uppercase row labels")
    edge = config.get("edge_exclusion")
    if not isinstance(edge, (int, float)) or not 0 <= edge < 0.5:
        errors.append("edge_exclusion must be at least 0 and below 0.5")
    if config.get("preference") not in {"closest_to_center", "row_order_then_left"}:
        errors.append("unsupported preference")
    payment = config.get("payment", {})
    if payment.get("maximum_remaining_balance") != 0:
        errors.append("public beta requires maximum_remaining_balance to be 0")
    if payment.get("voucher_count") != party:
        errors.append("voucher_count must equal party_size")
    if payment.get("method") != "registered_imax_voucher":
        errors.append("public beta supports registered_imax_voucher only")
    if config.get("allow_cancel_existing", False):
        errors.append("allow_cancel_existing must be false")
    if config.get("allow_change_existing", False):
        errors.append("allow_change_existing must be false")
    if not config.get("prevent_duplicate_booking", True):
        errors.append("prevent_duplicate_booking must be true")
    return {"ok": not errors, "errors": errors}


def eligible_start(day: date, start: str, config: dict) -> bool:
    hour, minute = map(int, start.split(":"))
    total = hour * 60 + minute
    rules = config["time_rules"]
    rule = rules["saturday"] if day.weekday() == 5 else rules["sunday"] if day.weekday() == 6 else rules["weekday"]
    if rule.get("any_time") is True:
        return True
    lower = rule.get("at_or_after")
    upper = rule.get("before")
    if lower:
        start_h, start_m = map(int, lower.split(":"))
        if total < start_h * 60 + start_m:
            return False
    if upper:
        limit_h, limit_m = map(int, upper.split(":"))
        if total >= limit_h * 60 + limit_m:
            return False
    return True


def rank_best_block(seat_map: dict, config: dict) -> dict | None:
    available = set(seat_map["available"])
    all_seats = seat_map["all"]
    party = config["party_size"]
    ranked = []
    for row_index, row in enumerate(config["rows"]):
        numbers = sorted({int(value[len(row):]) for value in all_seats if re.fullmatch(re.escape(row) + r"\d+", value)})
        if len(numbers) < party:
            continue
        cut = math.ceil(len(numbers) * config["edge_exclusion"])
        allowed = numbers[cut : len(numbers) - cut]
        positions = {number: index for index, number in enumerate(numbers)}
        center = (len(numbers) - 1) / 2
        for start_index in range(0, len(allowed) - party + 1):
            block = allowed[start_index : start_index + party]
            if any(right != left + 1 for left, right in zip(block, block[1:])):
                continue
            labels = [f"{row}{number}" for number in block]
            if not all(label in available for label in labels):
                continue
            midpoint = sum(positions[number] for number in block) / party
            distance = abs(midpoint - center) / len(numbers)
            if config.get("preference") == "row_order_then_left":
                key = (float(row_index), float(block[0]), distance)
            else:
                key = (distance, float(row_index), float(block[0]))
            ranked.append((key, distance, labels))
    if not ranked:
        return None
    _, distance, labels = min(ranked)
    return {"seats": labels, "pair": "-".join(labels), "center_distance": round(distance, 4)}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("config")
    rank_parser = sub.add_parser("rank")
    rank_parser.add_argument("seat_map")
    rank_parser.add_argument("config")
    args = parser.parse_args()

    config = load_json(args.config)
    result = validate(config)
    if not result["ok"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    if args.command == "validate":
        print(json.dumps({"ok": True}, ensure_ascii=False))
        return 0
    ranked = rank_best_block(load_json(args.seat_map), config)
    print(json.dumps({"ok": True, "selection": ranked}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
