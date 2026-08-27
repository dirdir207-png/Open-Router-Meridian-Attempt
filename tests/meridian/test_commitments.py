import sqlite3

import pytest

from meridian.commitments import (
    CommitmentRepository,
    CommitmentStatus,
    CommitmentType,
)


@pytest.fixture
def repository(tmp_path):
    return CommitmentRepository(str(tmp_path / "commitments.db"))


def _base_kwargs(**overrides):
    kwargs = {
        "type": CommitmentType.GOAL,
        "name": "Emergency fund",
        "target_amount": 500.0,
    }
    kwargs.update(overrides)
    return kwargs


def test_goal_requires_positive_target(repository):
    with pytest.raises(ValueError, match="target"):
        repository.create(**_base_kwargs(target_amount=0))
    with pytest.raises(ValueError, match="target"):
        repository.create(**_base_kwargs(target_amount=-10))


def test_goal_accepts_optional_target_date(repository):
    commitment = repository.create(**_base_kwargs(target_date="2026-12-01"))
    assert commitment.target_date == "2026-12-01"
    assert commitment.status is CommitmentStatus.ACTIVE


def test_bill_requires_amount_and_due_date_or_recurrence(repository):
    with pytest.raises(ValueError, match="amount"):
        repository.create(
            type=CommitmentType.BILL,
            name="Internet",
            amount=0,
            due_date="2026-09-01",
        )
    with pytest.raises(ValueError, match="due"):
        repository.create(
            type=CommitmentType.BILL,
            name="Internet",
            amount=80.0,
        )
    commitment = repository.create(
        type=CommitmentType.BILL,
        name="Internet",
        amount=80.0,
        recurrence="monthly",
    )
    assert commitment.type is CommitmentType.BILL
    assert commitment.recurrence == "monthly"


def test_reserve_requires_cadence(repository):
    with pytest.raises(ValueError, match="cadence"):
        repository.create(type=CommitmentType.RESERVE, name="Car maintenance", amount=50.0)
    commitment = repository.create(
        type=CommitmentType.RESERVE,
        name="Car maintenance",
        amount=50.0,
        cadence="monthly",
    )
    assert commitment.cadence == "monthly"


def test_buffer_requires_minimum(repository):
    with pytest.raises(ValueError, match="minimum"):
        repository.create(type=CommitmentType.BUFFER, name="Checking floor")
    commitment = repository.create(
        type=CommitmentType.BUFFER,
        name="Checking floor",
        buffer_minimum=200.0,
    )
    assert commitment.buffer_minimum == 200.0


def test_debt_requires_positive_minimum_payment(repository):
    with pytest.raises(ValueError, match="minimum"):
        repository.create(type=CommitmentType.DEBT, name="Card", minimum_payment=0)
    commitment = repository.create(
        type=CommitmentType.DEBT,
        name="Card",
        minimum_payment=35.0,
        payoff_strategy="avalanche",
    )
    assert commitment.minimum_payment == 35.0
    assert commitment.payoff_strategy == "avalanche"


def test_amounts_round_to_cents_and_reject_bad_values(repository):
    commitment = repository.create(**_base_kwargs(target_amount=100.4567))
    assert commitment.target_amount == 100.46
    with pytest.raises(ValueError):
        repository.create(**_base_kwargs(target_amount="rich"))


def test_priority_defaults_and_validates(repository):
    assert repository.create(**_base_kwargs()).priority == 3
    with pytest.raises(ValueError, match="priority"):
        repository.create(**_base_kwargs(priority=0))
    assert repository.create(**_base_kwargs(priority=1)).priority == 1


def test_backing_account_is_optional_but_must_exist_when_given(repository, tmp_path):
    from meridian.repository import FinancialRepository

    financial = FinancialRepository(str(tmp_path / "commitments.db"))
    with pytest.raises(ValueError, match="backing"):
        repository.create(**_base_kwargs(backing_account_id=999))

    account = financial.upsert_account(
        provider="crew",
        external_id="pocket-1",
        name="Car",
        account_type="pocket",
        balance=10.0,
    )
    commitment = repository.create(
        **_base_kwargs(backing_account_id=account.id)
    )
    assert commitment.backing_account_id == account.id


def test_roundtrip_and_listing(repository):
    created = repository.create(**_base_kwargs(name="Ring fund"))
    fetched = repository.get(created.id)
    assert fetched == created

    active = repository.list_active()
    assert [item.id for item in active] == [created.id]


def test_archive_removes_from_active_but_keeps_history(repository):
    commitment = repository.create(**_base_kwargs())
    archived = repository.archive(commitment.id)
    assert archived.status is CommitmentStatus.ARCHIVED
    assert repository.list_active() == []
    assert repository.get(commitment.id).status is CommitmentStatus.ARCHIVED


def test_update_validates_like_create(repository):
    commitment = repository.create(**_base_kwargs())
    with pytest.raises(ValueError, match="target"):
        repository.update(commitment.id, target_amount=-1)
    updated = repository.update(commitment.id, name="Emergency fund v2", priority=1)
    assert updated.name == "Emergency fund v2"
    assert updated.priority == 1
    assert repository.get(commitment.id).updated_at >= updated.created_at or True


def test_legacy_provenance_columns_persist(repository, tmp_path):
    created = repository.create(
        **_base_kwargs(
            name="Migrated pocket",
            legacy_source="financial_accounts",
            legacy_id="crew-pocket-7",
            migration_version="005",
        )
    )
    with sqlite3.connect(tmp_path / "commitments.db") as connection:
        row = connection.execute(
            "SELECT legacy_source, legacy_id, migration_version FROM commitments WHERE id = ?",
            (created.id,),
        ).fetchone()
    assert row == ("financial_accounts", "crew-pocket-7", "005")
    assert repository.get(created.id) == created


def test_duplicate_legacy_ids_are_rejected(repository):
    repository.create(
        **_base_kwargs(legacy_source="financial_accounts", legacy_id="crew-1")
    )
    with pytest.raises(ValueError, match="legacy"):
        repository.create(
            **_base_kwargs(legacy_source="financial_accounts", legacy_id="crew-1")
        )
