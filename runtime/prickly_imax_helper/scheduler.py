from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .policy import eligible_start, rank_best_block


@dataclass
class FairScanState:
    open_dates: list[str] = field(default_factory=list)
    date_cursor: int = 0
    free_counts: dict[str, int] = field(default_factory=dict)

    def replace_dates(self, values: list[str]) -> None:
        self.open_dates = list(dict.fromkeys(values))
        if self.date_cursor >= len(self.open_dates):
            self.date_cursor = 0

    def next_date(self) -> str | None:
        if not self.open_dates:
            return None
        value = self.open_dates[self.date_cursor]
        self.date_cursor = (self.date_cursor + 1) % len(self.open_dates)
        return value


def eligible_shows(ymd: str, schedules: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    day = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
    result = []
    for show in schedules:
        if str(config["format"]).casefold() not in str(show.get("movkndDsplNm", "")).casefold():
            continue
        raw = str(show.get("scnsrtTm", ""))
        if not raw.isdigit() or len(raw) != 4:
            continue
        start = f"{raw[:2]}:{raw[2:]}"
        if eligible_start(day, start, config):
            result.append({**show, "ymd": ymd, "time": start})
    return result


def changed_seat_targets(state: FairScanState, shows: list[dict[str, Any]], party_size: int = 2) -> list[dict[str, Any]]:
    targets = []
    for show in shows:
        key = f"{show['ymd']}|{show.get('scnsNo')}|{show.get('scnSseq')}"
        count = int(show.get("frSeatCnt") or 0)
        previous = state.free_counts.get(key)
        state.free_counts[key] = count
        if count >= party_size and previous != count:
            targets.append(show)
    return targets


def match_for(show: dict[str, Any], seat_map: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    pair = rank_best_block(seat_map, config)
    if not pair:
        return None
    return {
        "date": f"{show['ymd'][:4]}-{show['ymd'][4:6]}-{show['ymd'][6:8]}",
        "ymd": show["ymd"],
        "time": show["time"],
        "scnsNo": show["scnsNo"],
        "scnSseq": show["scnSseq"],
        **pair,
    }
