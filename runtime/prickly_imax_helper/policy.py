from __future__ import annotations

import math
import re
from datetime import date
from typing import Any


def eligible_start(day: date, start: str, config: dict[str, Any]) -> bool:
    hour, minute = map(int, start.split(":"))
    total = hour * 60 + minute
    rules = config["time_rules"]
    if day.weekday() == 5:
        return bool(rules["saturday"]["any_time"])
    if day.weekday() == 6:
        limit_h, limit_m = map(int, rules["sunday"]["before"].split(":"))
        return total < limit_h * 60 + limit_m
    start_h, start_m = map(int, rules["weekday"]["at_or_after"].split(":"))
    return total >= start_h * 60 + start_m


def rank_best_block(seat_map: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    available = set(seat_map["available"])
    all_seats = seat_map["all"]
    party = config["party_size"]
    ranked: list[tuple[float, int, int, list[str]]] = []
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
            ranked.append((distance, row_index, block[0], labels))
    if not ranked:
        return None
    distance, _, _, labels = min(ranked)
    return {
        "seats": labels,
        "pair": "-".join(labels),
        "center_distance": round(distance, 4),
        "available_count": len(available),
    }

