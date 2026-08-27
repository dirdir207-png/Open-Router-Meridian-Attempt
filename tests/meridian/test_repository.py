import json
from dataclasses import FrozenInstanceError

import pytest

from meridian.repository import FinancialRepository


@pytest.fixture
def repository(tmp_path):
    return FinancialRepository(str(tmp_path / "financial.db"))


def test_account_upsert_uses_provider_external_id_and_tracks_freshness(repository):
    original = repository.upsert_account(
        provider="crew",
        external_id="account-1",
        name="Everyday",
        account_type="checking",
        balance=125.25,
        currency="USD",
        source_updated_at="2026-08-26T08:00:00Z",
        synced_at="2026-08-26T08:01:00Z",
    )
    updated = repository.upsert_account(
        provider="crew",
        external_id="account-1",
        name="Everyday spending",
        account_type="checking",
        balance=130.75,
        currency="USD",
        source_updated_at="2026-08-26T09:00:00Z",
        synced_at="2026-08-26T09:01:00Z",
    )
    other_provider = repository.upsert_account(
        provider="simplefin",
        external_id="account-1",
        name="External checking",
        account_type="checking",
        balance=50.0,
        currency="USD",
        source_updated_at="2026-08-26T08:30:00Z",
        synced_at="2026-08-26T08:31:00Z",
    )

    assert updated.id == original.id
    assert updated.name == "Everyday spending"
    assert updated.balance == 130.75
    assert updated.source_updated_at == "2026-08-26T09:00:00Z"
    assert updated.synced_at == "2026-08-26T09:01:00Z"
    assert other_provider.id != original.id
    assert len(repository.list_accounts()) == 2


def test_account_upsert_preserves_newer_source_backed_data(repository):
    original = repository.upsert_account(
        provider="crew",
        external_id="account-freshness",
        name="Current account",
        account_type="checking",
        balance=100.0,
        source_updated_at="2026-08-26T10:00:00Z",
        synced_at="2026-08-26T10:01:00Z",
    )

    missing_source = repository.upsert_account(
        provider="crew",
        external_id="account-freshness",
        name="Partial account",
        account_type="checking",
        balance=1.0,
        source_updated_at=None,
        synced_at="2026-08-26T10:02:00Z",
    )
    assert missing_source.name == original.name
    assert missing_source.balance == original.balance
    assert missing_source.source_updated_at == original.source_updated_at

    older_source = repository.upsert_account(
        provider="crew",
        external_id="account-freshness",
        name="Older account",
        account_type="checking",
        balance=2.0,
        source_updated_at="2026-08-26T09:00:00Z",
        synced_at="2026-08-26T09:01:00Z",
    )
    assert older_source.name == original.name
    assert older_source.balance == original.balance
    assert older_source.source_updated_at == original.source_updated_at
    assert older_source.synced_at == missing_source.synced_at

    newer_source = repository.upsert_account(
        provider="crew",
        external_id="account-freshness",
        name="Newer account",
        account_type="checking",
        balance=125.0,
        source_updated_at="2026-08-26T11:00:00Z",
        synced_at="2026-08-26T11:01:00Z",
    )
    assert newer_source.name == "Newer account"
    assert newer_source.balance == 125.0
    assert newer_source.source_updated_at == "2026-08-26T11:00:00Z"


def test_account_dto_is_immutable_and_json_safe(repository):
    account = repository.upsert_account(
        provider="crew",
        external_id="account-json",
        name="Household",
        account_type="checking",
        balance=10.5,
        currency="USD",
        source_updated_at=None,
        synced_at="2026-08-26T10:00:00Z",
    )

    payload = account.to_dict()

    assert json.loads(json.dumps(payload)) == payload
    assert payload["provider"] == "crew"
    assert payload["external_id"] == "account-json"
    with pytest.raises(FrozenInstanceError):
        account.name = "Changed"


def test_transaction_upsert_is_unique_and_json_safe(repository):
    account = repository.upsert_account(
        provider="crew",
        external_id="account-1",
        name="Everyday",
        account_type="checking",
        balance=100.0,
        synced_at="2026-08-26T10:00:00Z",
    )
    original = repository.upsert_transaction(
        provider="crew",
        external_id="transaction-1",
        account_id=account.id,
        amount=-12.34,
        currency="USD",
        occurred_at="2026-08-25T12:00:00Z",
        description="Coffee",
        status="pending",
        source_updated_at="2026-08-25T12:01:00Z",
        synced_at="2026-08-25T12:02:00Z",
    )
    updated = repository.upsert_transaction(
        provider="crew",
        external_id="transaction-1",
        account_id=account.id,
        amount=-12.34,
        currency="USD",
        occurred_at="2026-08-25T12:00:00Z",
        description="Coffee shop",
        status="posted",
        source_updated_at="2026-08-26T12:01:00Z",
        synced_at="2026-08-26T12:02:00Z",
    )
    other_provider_account = repository.upsert_account(
        provider="simplefin",
        external_id="account-1",
        name="External checking",
        account_type="checking",
        balance=50.0,
        synced_at="2026-08-26T12:03:00Z",
    )
    other_provider = repository.upsert_transaction(
        provider="simplefin",
        external_id="transaction-1",
        account_id=other_provider_account.id,
        amount=-4.5,
        currency="USD",
        occurred_at="2026-08-24T12:00:00Z",
        description="Lunch",
        status="posted",
        synced_at="2026-08-26T12:03:00Z",
    )

    assert updated.id == original.id
    assert updated.status == "posted"
    assert updated.description == "Coffee shop"
    assert updated.source_updated_at == "2026-08-26T12:01:00Z"
    assert other_provider.id != original.id
    assert json.loads(json.dumps(updated.to_dict())) == updated.to_dict()


def test_transaction_upsert_preserves_newer_source_backed_data(repository):
    account = repository.upsert_account(
        provider="crew",
        external_id="account-freshness",
        name="Everyday",
        account_type="checking",
        balance=100.0,
        synced_at="2026-08-26T10:00:00Z",
    )
    original = repository.upsert_transaction(
        provider="crew",
        external_id="transaction-freshness",
        account_id=account.id,
        amount=-10.0,
        occurred_at="2026-08-26T09:00:00Z",
        description="Posted coffee",
        status="posted",
        source_updated_at="2026-08-26T10:00:00Z",
        synced_at="2026-08-26T10:01:00Z",
    )

    missing_source = repository.upsert_transaction(
        provider="crew",
        external_id="transaction-freshness",
        account_id=account.id,
        amount=-1.0,
        occurred_at="2026-08-26T09:00:00Z",
        description="Partial coffee",
        status="pending",
        source_updated_at=None,
        synced_at="2026-08-26T10:02:00Z",
    )
    assert missing_source.description == original.description
    assert missing_source.status == original.status
    assert missing_source.source_updated_at == original.source_updated_at

    older_source = repository.upsert_transaction(
        provider="crew",
        external_id="transaction-freshness",
        account_id=account.id,
        amount=-2.0,
        occurred_at="2026-08-26T09:00:00Z",
        description="Older coffee",
        status="pending",
        source_updated_at="2026-08-26T09:00:00Z",
        synced_at="2026-08-26T09:01:00Z",
    )
    assert older_source.description == original.description
    assert older_source.status == original.status
    assert older_source.source_updated_at == original.source_updated_at
    assert older_source.synced_at == missing_source.synced_at

    newer_source = repository.upsert_transaction(
        provider="crew",
        external_id="transaction-freshness",
        account_id=account.id,
        amount=-12.0,
        occurred_at="2026-08-26T09:00:00Z",
        description="Corrected coffee",
        status="reversed",
        source_updated_at="2026-08-26T11:00:00Z",
        synced_at="2026-08-26T11:01:00Z",
    )
    assert newer_source.description == "Corrected coffee"
    assert newer_source.status == "reversed"
    assert newer_source.source_updated_at == "2026-08-26T11:00:00Z"


def test_transaction_upsert_rejects_mismatched_account_provider(repository):
    crew_account = repository.upsert_account(
        provider="crew",
        external_id="crew-account",
        name="Crew checking",
        account_type="checking",
        balance=100.0,
        synced_at="2026-08-26T10:00:00Z",
    )
    simplefin_account = repository.upsert_account(
        provider="simplefin",
        external_id="simplefin-account",
        name="SimpleFin checking",
        account_type="checking",
        balance=100.0,
        synced_at="2026-08-26T10:00:00Z",
    )
    original = repository.upsert_transaction(
        provider="crew",
        external_id="crew-transaction",
        account_id=crew_account.id,
        amount=-1.0,
        occurred_at="2026-08-26T10:00:00Z",
        description="Original",
        status="posted",
        synced_at="2026-08-26T10:00:00Z",
    )

    with pytest.raises(ValueError, match="provider must match"):
        repository.upsert_transaction(
            provider="simplefin",
            external_id="invalid-insert",
            account_id=crew_account.id,
            amount=-1.0,
            occurred_at="2026-08-26T10:00:00Z",
            description="Invalid",
            status="posted",
            synced_at="2026-08-26T10:00:00Z",
        )

    with pytest.raises(ValueError, match="provider must match"):
        repository.upsert_transaction(
            provider="crew",
            external_id="crew-transaction",
            account_id=simplefin_account.id,
            amount=-2.0,
            occurred_at="2026-08-26T10:00:00Z",
            description="Invalid reassignment",
            status="reversed",
            synced_at="2026-08-26T10:01:00Z",
        )

    records, _ = repository.list_transactions(account_id=crew_account.id)
    assert records == [original]


def test_transaction_pagination_and_account_filter_use_stable_order(repository):
    first_account = repository.upsert_account(
        provider="crew",
        external_id="account-1",
        name="Everyday",
        account_type="checking",
        balance=100.0,
        synced_at="2026-08-26T10:00:00Z",
    )
    second_account = repository.upsert_account(
        provider="crew",
        external_id="account-2",
        name="Savings",
        account_type="savings",
        balance=200.0,
        synced_at="2026-08-26T10:00:00Z",
    )

    transaction_specs = [
        ("old", first_account.id, "2026-08-24T09:00:00Z"),
        ("same-time-first", first_account.id, "2026-08-26T09:00:00Z"),
        ("same-time-second", first_account.id, "2026-08-26T09:00:00Z"),
        ("other-account", second_account.id, "2026-08-27T09:00:00Z"),
    ]
    for external_id, account_id, occurred_at in transaction_specs:
        repository.upsert_transaction(
            provider="crew",
            external_id=external_id,
            account_id=account_id,
            amount=-1.0,
            currency="USD",
            occurred_at=occurred_at,
            description=external_id,
            status="posted",
            synced_at="2026-08-27T10:00:00Z",
        )

    first_page, cursor = repository.list_transactions(limit=2)
    second_page, final_cursor = repository.list_transactions(limit=2, cursor=cursor)
    filtered, filtered_cursor = repository.list_transactions(
        account_id=first_account.id,
        limit=10,
    )

    assert [item.external_id for item in first_page] == [
        "other-account",
        "same-time-second",
    ]
    assert [item.external_id for item in second_page] == [
        "same-time-first",
        "old",
    ]
    assert final_cursor is None
    assert [item.external_id for item in filtered] == [
        "same-time-second",
        "same-time-first",
        "old",
    ]
    assert filtered_cursor is None
