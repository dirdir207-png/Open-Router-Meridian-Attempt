"""Read-only Activity access backed exclusively by FinancialRepository."""

from datetime import datetime
from typing import Optional

from meridian.models import TransactionRecord
from meridian.repository import FinancialRepository
from meridian.services.today import data_freshness


def get_activity(
    repository: FinancialRepository,
    *,
    limit: int = 50,
    cursor: Optional[str] = None,
    account_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict[str, object]:
    """Return one stable repository page plus the graph's freshness state."""
    transactions, next_cursor = repository.list_transactions(
        limit=limit,
        cursor=cursor,
        account_id=account_id,
    )
    freshness_kwargs = (
        {"account_ids": [account_id]}
        if account_id is not None
        else {
            "transaction_ids": [transaction.id for transaction in transactions],
            "include_all_connections": True,
        }
    )
    return {
        "transactions": transactions,
        "next_cursor": next_cursor,
        "data_freshness": data_freshness(repository, **freshness_kwargs, now=now),
    }


def get_transaction(
    repository: FinancialRepository, transaction_id: int
) -> Optional[TransactionRecord]:
    """Return one normalized transaction without reaching any provider."""
    return repository.get_transaction(transaction_id)
