from datetime import datetime, timezone

import pytest

from meridian.repository import FinancialRepository
from meridian.services.today import build_today


@pytest.fixture
def repository(tmp_path):
    return FinancialRepository(str(tmp_path / "financial.db"))


def test_today_reports_cash_inputs_and_stale_graph_without_a_forecast(repository):
    checking = repository.upsert_account(
        provider="crew",
        external_id="checking-raw-123456789",
        name="Checking",
        account_type="checking",
        balance=100.0,
        available_balance=80.0,
        synced_at="2026-08-20T08:00:00Z",
    )
    repository.upsert_account(
        provider="crew",
        external_id="savings-raw-987654321",
        name="Savings",
        account_type="savings",
        balance=300.0,
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

    result = build_today(
        repository,
        now=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )

    assert result["total_cash"] == 400.0
    assert result["safe_to_spend"] == {
        "amount": 380.0,
        "inputs": {
            "available_cash": 380.0,
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


def test_today_treats_a_timezone_less_snapshot_as_stale_instead_of_crashing(repository):
    repository.upsert_account(
        provider="crew",
        external_id="checking",
        name="Checking",
        account_type="checking",
        balance=100.0,
        synced_at="2026-08-27T08:00:00",
    )

    result = build_today(
        repository,
        now=datetime(2026, 8, 27, 9, tzinfo=timezone.utc),
    )

    assert result["data_freshness"] == {
        "status": "stale",
        "last_updated_at": None,
    }
