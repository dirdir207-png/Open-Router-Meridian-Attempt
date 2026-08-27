"""Canonical timestamp handling shared by writes, cursors, and migrations."""

import re
from datetime import datetime, timezone

_SUPPORTED_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T| )"
    r"\d{2}:?\d{2}:?\d{2}(?:[.,](?P<fraction>\d+))?"
    r"(?:Z|[+-]\d{2}(?::?\d{2}(?::?\d{2})?)?)$"
)
_FRACTIONAL_SECONDS = re.compile(
    r"^\d{4}-\d{2}-\d{2}.\d{2}:?\d{2}:?\d{2}[.,](\d+)"
)


def canonical_occurred_at(value: str) -> str:
    """Return a fixed-width UTC timestamp without discarding precision."""
    if not isinstance(value, str):
        raise ValueError("occurred_at must be a timezone-aware timestamp")
    fractional_seconds = _FRACTIONAL_SECONDS.search(value)
    if fractional_seconds is not None and len(fractional_seconds.group(1)) > 6:
        raise ValueError("occurred_at must use at most 6 fractional digits")
    timestamp = _SUPPORTED_TIMESTAMP.fullmatch(value)
    if timestamp is None:
        raise ValueError("occurred_at must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("occurred_at must be a timezone-aware timestamp")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
