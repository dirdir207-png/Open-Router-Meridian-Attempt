import json
import shutil
import sqlite3
from dataclasses import FrozenInstanceError

import pytest

from meridian import db as db_module
from meridian.db import run_migrations
from meridian.repository import FinancialRepository, _encode_cursor


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


def test_transaction_pagination_emits_canonical_utc_cursor_for_offset_input(repository):
    account = repository.upsert_account(
        provider="crew",
        external_id="cursor-account",
        name="Cursor account",
        account_type="checking",
        balance=100.0,
    )
    for external_id in ("first", "second"):
        repository.upsert_transaction(
            provider="crew",
            external_id=external_id,
            account_id=account.id,
            amount=-1.0,
            occurred_at="2026-08-27T08:00:00+00:00",
            description=external_id,
            status="posted",
        )

    first_page, cursor = repository.list_transactions(limit=1)
    second_page, _ = repository.list_transactions(limit=1, cursor=cursor)

    assert first_page[0].occurred_at == "2026-08-27T08:00:00.000000Z"
    assert cursor is not None
    assert [item.external_id for item in second_page] == ["first"]


def test_transaction_ordering_uses_fixed_width_fractional_utc_storage(repository):
    account = repository.upsert_account(
        provider="crew",
        external_id="fraction-account",
        name="Fraction account",
        account_type="checking",
        balance=100.0,
    )
    for external_id, occurred_at in (
        ("whole", "2026-08-27T08:00:00Z"),
        ("tenth", "2026-08-27T08:00:00.1Z"),
        ("eleventh", "2026-08-27T08:00:00.11Z"),
    ):
        repository.upsert_transaction(
            provider="crew",
            external_id=external_id,
            account_id=account.id,
            amount=-1.0,
            occurred_at=occurred_at,
            description=external_id,
            status="posted",
        )

    records, _ = repository.list_transactions(limit=10)

    assert [record.external_id for record in records] == [
        "eleventh",
        "tenth",
        "whole",
    ]
    assert [record.occurred_at for record in records] == [
        "2026-08-27T08:00:00.110000Z",
        "2026-08-27T08:00:00.100000Z",
        "2026-08-27T08:00:00.000000Z",
    ]


@pytest.mark.parametrize(
    "occurred_at",
    [
        "2026-08-27T08:00:00.1234567Z",
        "2026-08-27t08:00:00.1234567+00:00",
        "2026-08-27X08:00:00.1234567+00:00",
    ],
)
def test_transaction_write_rejects_more_than_microsecond_precision(
    repository, occurred_at
):
    account = repository.upsert_account(
        provider="crew",
        external_id="precision-account",
        name="Precision account",
        account_type="checking",
        balance=100.0,
    )

    with pytest.raises(ValueError, match="at most 6 fractional digits"):
        repository.upsert_transaction(
            provider="crew",
            external_id="too-precise",
            account_id=account.id,
            amount=-1.0,
            occurred_at=occurred_at,
            description="Too precise",
            status="posted",
        )

    assert repository.list_transactions() == ([], None)


@pytest.mark.parametrize(
    "legacy_timestamp",
    [
        "2026-08-27T09:00:00Z",
        "2026-08-27T09:00:00.1Z",
        "2026-08-27T09:00:00.123456Z",
    ],
)
def test_pre_upgrade_cursor_continues_after_fixed_width_migration(
    tmp_path, monkeypatch, legacy_timestamp
):
    db_path = tmp_path / "pre-upgrade-cursor.db"
    original_migrations_dir = db_module.MIGRATIONS_DIR
    legacy_migrations = tmp_path / "legacy-migrations"
    legacy_migrations.mkdir()
    for source in sorted(original_migrations_dir.glob("00[1-3]_*.sql")):
        shutil.copy(source, legacy_migrations / source.name)
    with monkeypatch.context() as migration_patch:
        migration_patch.setattr(db_module, "MIGRATIONS_DIR", legacy_migrations)
        run_migrations(str(db_path))

    with sqlite3.connect(db_path) as connection:
        account_id = connection.execute(
            """
            INSERT INTO financial_accounts (
                provider, external_id, name, account_type, balance, currency,
                synced_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "crew",
                "legacy-cursor-account",
                "Legacy cursor account",
                "checking",
                100.0,
                "USD",
                "2026-08-27T10:00:00Z",
                "2026-08-27T10:00:00Z",
                "2026-08-27T10:00:00Z",
            ),
        ).lastrowid
        for external_id, occurred_at in (
            ("newer", "2026-08-27T10:00:00Z"),
            ("cursor-row", legacy_timestamp),
            ("older", "2026-08-27T08:00:00Z"),
        ):
            cursor = connection.execute(
                """
                INSERT INTO financial_transactions (
                    account_id, provider, external_id, amount, currency,
                    occurred_at, description, status, synced_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    "crew",
                    external_id,
                    -1.0,
                    "USD",
                    occurred_at,
                    external_id,
                    "posted",
                    "2026-08-27T10:00:00Z",
                    "2026-08-27T10:00:00Z",
                    "2026-08-27T10:00:00Z",
                ),
            )
            if external_id == "cursor-row":
                cursor_row_id = cursor.lastrowid

    pre_upgrade_cursor = _encode_cursor(legacy_timestamp, cursor_row_id)
    repository = FinancialRepository(str(db_path))

    records, next_cursor = repository.list_transactions(
        limit=10, cursor=pre_upgrade_cursor
    )

    assert [record.external_id for record in records] == ["older"]
    assert next_cursor is None
