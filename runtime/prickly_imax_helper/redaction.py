from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEY = re.compile(r"cookie|token|password|passwd|authorization|card|voucher[_-]?(?:id|number|code)|customer", re.I)
EMAIL = re.compile(r"(?<![\w.+-])([\w.+-])[\w.+-]*@([\w.-]+\.[A-Za-z]{2,})")
LONG_DIGITS = re.compile(r"\b\d{8,}\b")


def redact(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = EMAIL.sub(r"\1***@\2", value)
        return LONG_DIGITS.sub("[REDACTED_NUMBER]", value)
    return value

