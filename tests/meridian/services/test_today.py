from datetime import datetime, timedelta, timezone

import pytest

from meridian.providers.base import (
    NormalizedAccount,
    NormalizedTransaction,
    ProviderSnapshot,
)
from meridian.repository import FinancialRepository
from meridian.services.activity import get_activity
from meridian.services.today import build_today
from meridian.sync import sync_provider


@pytest.fixture
def repository(tmp_path):
    return FinancialRepository(str(tmp_path / "financial.db"))


def test_today_reports_cash_inputs_and_stale_graph_without_a_forecast(repository):
    run = repository.begin_sync_run(
        provider="crew",
        connection_external_id="crew-household",
        connection_name="Crew",
    )
    checking = repository.upsert_account(
        provider="crew",
        external_id="checking-raw-123456789",
        name="Checking",
        account_type="checking",
        balance=100.0,
        available_balance=80.0,
        connection_id=run.connection_id,
        source_updated_at="2026-08-20T08:00:00Z",
        synced_at="2026-08-20T08:00:00Z",
    )
    repository.upsert_account(
        provider="crew",
        external_id="savings-raw-987654321",
        name="Savings",
        account_type="savings",
        balance=300.0,
        connection_id=run.connection_id,
        source_updated_at="2026-08-20T08:00:00Z",
        synced_at="2026-08-20T08:00:00Z",
    )
    repository.upsert_transaction(
        provider="crew",
        external_id="transaction-raw-111",
        account_id=checking.id,
        amount=-12.5,
        occurred_at="2026-08-20T07:00:00Z",
        description="Coffee",
        status="posted",
        synced_at="2026-08-20T08:00:00Z",
    )
    repository.finish_sync_run(
        run.id,
        status="complete",
        accounts_synced=2,
        transactions_synced=1,
        errors=0,
    )

    result = build_today(
        repository,
        now=datetime.now(timezone.utc),
    )

    assert result["total_cash"] == {
        "amount": 400.0,
        "currency": "USD",
        "by_currency": {"USD": 400.0},
    }
    assert result["safe_to_spend"] == {
        "amount": None,
        "status": "unavailable",
        "inputs": {
            "available_cash": {
                "amount": 380.0,
                "currency": "USD",
                "by_currency": {"USD": 380.0},
            },
            "known_obligations": None,
            "reason": "Commitments are not yet available in the normalized graph.",
        },
    }
    assert result["upcoming_events"] == []
    assert result["forecast"] is None
    assert result["data_freshness"] == {
        "status": "stale",
        "last_updated_at": "2026-08-20T08:00:00Z",
    }


def test_today_excludes_pockets_liabilities_and_non_cash_from_cash_inputs(repository):
    for external_id, account_type, balance, available_balance in [
        ("checking", "checking", 100.0, 80.0),
        ("savings", "savings", 50.0, None),
        ("reserved", "pocket", 200.0, 200.0),
        ("credit", "credit_card", -500.0, 500.0),
        ("brokerage", "investment", 1000.0, 1000.0),
    ]:
        repository.upsert_account(
            provider="crew",
            external_id=external_id,
            name=external_id,
            account_type=account_type,
            balance=balance,
            available_balance=available_balance,
            synced_at="2026-08-27T08:00:00Z",
        )

    result = build_today(repository)

    assert result["total_cash"] == {
        "amount": 150.0,
        "currency": "USD",
        "by_currency": {"USD": 150.0},
    }
    assert result["safe_to_spend"]["inputs"]["available_cash"] == {
        "amount": 130.0,
        "currency": "USD",
        "by_currency": {"USD": 130.0},
    }


def test_today_does_not_add_cash_balances_across_currencies(repository):
    repository.upsert_account(
        provider="crew",
        external_id="usd-checking",
        name="USD checking",
        account_type="checking",
        balance=100.0,
        available_balance=80.0,
        currency="USD",
        synced_at="2026-08-27T08:00:00Z",
    )
    repository.upsert_account(
        provider="crew",
        external_id="eur-savings",
        name="EUR savings",
        account_type="savings",
        balance=50.0,
        available_balance=45.0,
        currency="EUR",
        synced_at="2026-08-27T08:00:00Z",
    )

    result = build_today(repository)

    assert result["total_cash"] == {
        "amount": None,
        "currency": None,
        "by_currency": {"EUR": 50.0, "USD": 100.0},
    }
    assert result["safe_to_spend"]["inputs"]["available_cash"] == {
        "amount": None,
        "currency": None,
        "by_currency": {"EUR": 45.0, "USD": 80.0},
    }


def test_today_treats_a_timezone_less_source_snapshot_as_stale(repository):
    run = repository.begin_sync_run(
        provider="crew",
        connection_external_id="crew-household",
        connection_name="Crew",
    )
    repository.upsert_account(
        provider="crew",
        external_id="checking",
        name="Checking",
        account_type="checking",
        balance=100.0,
        connection_id=run.connection_id,
        source_updated_at="2026-08-27T08:00:00",
        synced_at="2026-08-27T08:00:00",
    )
    repository.finish_sync_run(
        run.id,
        status="complete",
        accounts_synced=1,
        transactions_synced=0,
        errors=0,
    )

    result = build_today(
        repository,
        now=datetime(2026, 8, 27, 9, tzinfo=timezone.utc),
    )

    assert result["data_freshness"]["status"] == "stale"


def test_today_treats_a_future_source_snapshot_as_stale(repository):
    now = datetime.now(timezone.utc)
    run = repository.begin_sync_run(
        provider="crew",
        connection_external_id="crew-household",
        connection_name="Crew",
    )
    repository.upsert_account(
        provider="crew",
        external_id="checking",
        name="Checking",
        account_type="checking",
        balance=100.0,
        connection_id=run.connection_id,
        source_updated_at=(now + timedelta(days=1)).isoformat(),
    )
    repository.finish_sync_run(
        run.id,
        status="complete",
        accounts_synced=1,
        transactions_synced=0,
        errors=0,
    )

    result = build_today(
        repository,
        now=now + timedelta(minutes=1),
    )

    assert result["data_freshness"]["status"] == "stale"


def test_today_and_activity_stay_stale_after_partial_sync_until_a_complete_sync(repository):
    class SnapshotAdapter:
        provider_name = "crew"
        connection_external_id = "crew-household"
        connection_name = "Crew"

        def __init__(self, snapshot):
            self.snapshot = snapshot

        def fetch_snapshot(self):
            return self.snapshot

    observed_at = datetime.now(timezone.utc).replace(microsecond=0)
    observed_at_text = observed_at.isoformat().replace("+00:00", "Z")
    account = NormalizedAccount(
        external_id="checking",
        name="Checking",
        account_type="checking",
        balance=100.0,
        source_updated_at=observed_at_text,
    )
    transaction = NormalizedTransaction(
        external_id="coffee",
        account_external_id="checking",
        amount=-3.0,
        occurred_at=observed_at_text,
        description="Coffee",
        status="posted",
        source_updated_at=observed_at_text,
    )
    partial = ProviderSnapshot(
        connection_external_id="crew-household",
        connection_name="Crew",
        accounts=(account,),
        transactions=(transaction,),
        is_complete=False,
        errors=("transaction page unavailable",),
    )

    sync_provider(SnapshotAdapter(partial), repository)

    assert build_today(repository, now=observed_at)["data_freshness"]["status"] == "stale"
    assert get_activity(repository, now=observed_at)["data_freshness"]["status"] == "stale"

    complete = ProviderSnapshot(
        connection_external_id="crew-household",
        connection_name="Crew",
        accounts=(account,),
        transactions=(transaction,),
    )
    sync_provider(SnapshotAdapter(complete), repository)

    read_at = datetime.now(timezone.utc)
    assert build_today(repository, now=read_at)["data_freshness"]["status"] == "fresh"
    assert get_activity(repository, now=read_at)["data_freshness"]["status"] == "fresh"
