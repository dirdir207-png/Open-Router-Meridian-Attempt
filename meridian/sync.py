"""Idempotent synchronization of provider snapshots into Meridian."""

from dataclasses import dataclass

from .providers.base import ProviderAdapter


@dataclass(frozen=True)
class SyncReport:
    provider: str
    status: str
    accounts_synced: int
    transactions_synced: int
    errors: int


def sync_provider(adapter: ProviderAdapter, repository) -> SyncReport:
    """Persist one read-only provider snapshot without deleting prior facts."""
    snapshot = adapter.fetch_snapshot()
    run_id = repository.begin_sync_run(
        provider=adapter.provider_name,
        connection_external_id=snapshot.connection_external_id,
        connection_name=snapshot.connection_name,
    )
    accounts_by_external_id = {}
    errors = len(snapshot.errors)
    for account in snapshot.accounts:
        try:
            accounts_by_external_id[account.external_id] = repository.upsert_account(
                provider=adapter.provider_name,
                external_id=account.external_id,
                name=account.name,
                account_type=account.account_type,
                balance=account.balance,
                currency=account.currency,
                available_balance=account.available_balance,
                is_active=account.is_active,
                source_updated_at=account.source_updated_at,
            )
        except Exception:
            errors += 1

    transactions_synced = 0
    for transaction in snapshot.transactions:
        account = accounts_by_external_id.get(transaction.account_external_id)
        if account is None:
            errors += 1
            continue
        try:
            repository.upsert_transaction(
                provider=adapter.provider_name,
                external_id=transaction.external_id,
                account_id=account.id,
                amount=transaction.amount,
                currency=transaction.currency,
                occurred_at=transaction.occurred_at,
                posted_at=transaction.posted_at,
                description=transaction.description,
                merchant=transaction.merchant,
                status=transaction.status,
                raw_description=transaction.raw_description,
                source_updated_at=transaction.source_updated_at,
            )
        except Exception:
            errors += 1
            continue
        transactions_synced += 1

    status = "complete" if snapshot.is_complete and errors == 0 else "partial"
    repository.finish_sync_run(
        run_id,
        status=status,
        accounts_synced=len(accounts_by_external_id),
        transactions_synced=transactions_synced,
        errors=errors,
    )
    return SyncReport(
        provider=adapter.provider_name,
        status=status,
        accounts_synced=len(accounts_by_external_id),
        transactions_synced=transactions_synced,
        errors=errors,
    )
