"""Calculations for Meridian's read-only Today workspace."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from meridian.models import AccountRecord
from meridian.repository import FinancialRepository

_STALE_AFTER = timedelta(hours=24)


def _parse_timestamp(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def data_freshness(
    accounts: Sequence[AccountRecord], *, now: Optional[datetime] = None
) -> dict[str, Optional[str]]:
    """Describe the oldest account snapshot needed for a trustworthy summary."""
    if not accounts:
        return {"status": "unavailable", "last_updated_at": None}

    timestamps = [(_parse_timestamp(account.synced_at), account.synced_at) for account in accounts]
    valid_timestamps = [item for item in timestamps if item[0] is not None]
    if len(valid_timestamps) != len(accounts):
        return {"status": "stale", "last_updated_at": None}

    oldest, oldest_value = min(valid_timestamps, key=lambda item: item[0])
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    status = "stale" if current_time - oldest > _STALE_AFTER else "fresh"
    return {"status": status, "last_updated_at": oldest_value}


def build_today(
    repository: FinancialRepository, *, now: Optional[datetime] = None
) -> dict[str, object]:
    """Build a conservative Today summary from normalized repository records."""
    accounts = repository.list_accounts()
    active_accounts = [account for account in accounts if account.is_active]
    total_cash = sum(account.balance for account in active_accounts)
    available_cash = sum(
        account.available_balance
        if account.available_balance is not None
        else account.balance
        for account in active_accounts
    )

    return {
        "total_cash": total_cash,
        "safe_to_spend": {
            "amount": available_cash,
            "inputs": {
                "available_cash": available_cash,
                "known_obligations": None,
                "reason": "Commitments are not yet available in the normalized graph.",
            },
        },
        "upcoming_events": [],
        "forecast": None,
        "data_freshness": data_freshness(accounts, now=now),
    }
