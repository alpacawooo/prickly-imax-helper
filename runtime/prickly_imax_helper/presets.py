from __future__ import annotations

from copy import deepcopy
from typing import Any


ODYSSEY: dict[str, Any] = {
    "movie": "오디세이",
    "theater": "용산아이파크몰",
    "format": "IMAX",
    "target": {
        "company_code": "A420",
        "site_no": "0013",
        "movie_no": "30001323",
    },
    "party_size": 2,
    "dates": "all_open",
    "time_rules": {
        "weekday": {"at_or_after": "19:00"},
        "saturday": {"any_time": True},
        "sunday": {"before": "22:00"},
    },
    "rows": list("DEFGHIJ"),
    "edge_exclusion": 0.2,
    "preference": "closest_to_center",
    "prevent_duplicate_booking": True,
    "allow_cancel_existing": False,
    "allow_change_existing": False,
    "payment": {
        "method": "registered_imax_voucher",
        "voucher_count": 2,
        "maximum_remaining_balance": 0,
    },
    "authorization": {
        "automatic_query": True,
        "automatic_seat_selection": True,
        "automatic_submission": True,
    },
    "request_policy": {
        "minimum_interval_seconds": 1.0,
        "rate_limit_cooldown_seconds": 300,
    },
}


def odyssey() -> dict[str, Any]:
    return deepcopy(ODYSSEY)
