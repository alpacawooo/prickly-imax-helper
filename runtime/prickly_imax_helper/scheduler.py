from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .policy import eligible_start, has_minimum_lead, rank_best_block


def show_key(show: dict[str, Any]) -> str:
    return f"{show['ymd']}|{show.get('scnsNo')}|{show.get('scnSseq')}"


@dataclass(frozen=True)
class ScanAction:
    lane: str
    kind: str
    ymd: str | None = None
    show: dict[str, Any] | None = None


@dataclass
class BalancedScanPlanner:
    minimum_interval_seconds: float
    open_dates: list[str] = field(default_factory=list)
    schedules: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    schedule_refreshed_at: dict[str, float] = field(default_factory=dict)
    hot_targets: list[dict[str, Any]] = field(default_factory=list)
    hot_cursor: int = 0
    hot_actions_since_discovery: int = 0

    def replace_dates(self, values: list[str]) -> None:
        dates = list(dict.fromkeys(values))
        self.open_dates = dates
        for ymd in list(self.schedules):
            if ymd not in dates:
                self.schedules.pop(ymd, None)
                self.schedule_refreshed_at.pop(ymd, None)
        self._replace_hot_targets(
            [show for ymd in dates for show in self.schedules.get(ymd, [])]
        )

    def update_schedule(self, ymd: str, shows: list[dict[str, Any]], *, now: float) -> None:
        normalized = [{**show, "ymd": ymd} for show in shows]
        self.schedules[ymd] = normalized
        self.schedule_refreshed_at[ymd] = now
        self._replace_hot_targets(
            [show for date_value in self.open_dates for show in self.schedules.get(date_value, [])]
        )

    def _replace_hot_targets(self, values: list[dict[str, Any]]) -> None:
        previous_keys = [show_key(show) for show in self.hot_targets]
        next_by_key = {show_key(show): show for show in values}
        ordered_keys = [key for key in previous_keys if key in next_by_key]
        ordered_keys.extend(key for key in next_by_key if key not in ordered_keys)
        if previous_keys:
            next_key = previous_keys[self.hot_cursor % len(previous_keys)]
        else:
            next_key = None
        self.hot_targets = [next_by_key[key] for key in ordered_keys]
        if not self.hot_targets:
            self.hot_cursor = 0
        elif next_key in ordered_keys:
            self.hot_cursor = ordered_keys.index(next_key)
        else:
            self.hot_cursor %= len(self.hot_targets)

    def remove_hot_target(self, show: dict[str, Any]) -> None:
        key = show_key(show)
        self._replace_hot_targets([candidate for candidate in self.hot_targets if show_key(candidate) != key])

    def _next_discovery(self, *, open_dates_due: bool) -> ScanAction:
        self.hot_actions_since_discovery = 0
        if open_dates_due or not self.open_dates:
            return ScanAction("discovery", "open_dates")
        unloaded = [ymd for ymd in self.open_dates if ymd not in self.schedules]
        if unloaded:
            return ScanAction("discovery", "schedule", ymd=unloaded[0])
        stalest = min(self.open_dates, key=lambda ymd: self.schedule_refreshed_at.get(ymd, float("-inf")))
        return ScanAction("discovery", "schedule", ymd=stalest)

    def next_action(self, *, now: float, open_dates_due: bool) -> ScanAction:
        del now
        if not self.hot_targets or self.hot_actions_since_discovery >= 4:
            return self._next_discovery(open_dates_due=open_dates_due)
        show = self.hot_targets[self.hot_cursor]
        self.hot_cursor = (self.hot_cursor + 1) % len(self.hot_targets)
        self.hot_actions_since_discovery += 1
        return ScanAction("hot", "seats", ymd=str(show["ymd"]), show=show)

    def metrics(self, *, now: float) -> dict[str, int | float]:
        count = len(self.hot_targets)
        ages = [max(0.0, now - refreshed_at) for refreshed_at in self.schedule_refreshed_at.values()]
        return {
            "hot_target_count": count,
            "estimated_hot_revisit_seconds": float(math.ceil(count * 5 / 4) * self.minimum_interval_seconds),
            "discovery_queue_count": sum(1 for ymd in self.open_dates if ymd not in self.schedules),
            "oldest_schedule_age_seconds": round(max(ages, default=0.0), 1),
        }


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


def eligible_shows(
    ymd: str,
    schedules: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    day = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
    minimum_lead = config.get("minimum_lead_minutes", 180)
    if type(minimum_lead) is not int or not 180 <= minimum_lead <= 1440:
        raise ValueError("minimum_lead_minutes must be an integer from 180 through 1440")
    result = []
    for show in schedules:
        if str(config["format"]).casefold() not in str(show.get("movkndDsplNm", "")).casefold():
            continue
        raw = str(show.get("scnsrtTm", ""))
        if not raw.isdigit() or len(raw) != 4:
            continue
        start = f"{raw[:2]}:{raw[2:]}"
        if eligible_start(day, start, config) and has_minimum_lead(
            ymd,
            start,
            minimum_lead,
            now=now,
        ):
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
