import sqlite3
from datetime import datetime, timezone

import pytest

from meridian.commitments import CommitmentRepository
from meridian.migrate_legacy import (
    apply_legacy_migration,
    preview_legacy_migration,
)
from meridian.repository import FinancialRepository


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "legacy.db"
    FinancialRepository(str(path))  # ensures graph schema exists
    return str(path)


def _seed_pocket(
    repository,
    external_id,
    *,
    name="Vacation",
    account_type="pocket",
    balance=25.0,
    with_connection=True,
):
    connection_id = None
    if with_connection:
        run = repository.begin_sync_run(
            provider="crew",
            connection_external_id="crew-household",
            connection_name="Crew",
        )
        connection_id = run.connection_id
    return repository.upsert_account(
        provider="crew",
        external_id=external_id,
        name=name,
        account_type=account_type,
        balance=balance,
        connection_id=connection_id,
        source_updated_at=datetime.now(timezone.utc).isoformat(),
    )


def _link_credit_card_pocket(db_path, pocket_external_id):
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS credit_card_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT UNIQUE NOT NULL,
                account_name TEXT,
                pocket_id TEXT,
                provider TEXT DEFAULT 'lunchflow',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            "INSERT INTO credit_card_config (account_id, account_name, pocket_id) VALUES (?, ?, ?)",
            ("card-external-1", "Everyday card", pocket_external_id),
        )


def test_preview_maps_pockets_debt_links_and_flags_unknowns(db_path):
    repository = FinancialRepository(db_path)
    _seed_pocket(repository, "crew-goal-1", name="Vacation")
    _seed_pocket(repository, "crew-debt-1", name="Card payments")
    _link_credit_card_pocket(db_path, "crew-debt-1")
    _seed_pocket(repository, "crew-loose-1", name="Mystery", with_connection=False)
    _seed_pocket(repository, "crew-checking", name="Checking", account_type="checking")

    preview = preview_legacy_migration(db_path)

    decisions = {item["legacy_id"]: item for item in preview.decisions}
    assert decisions["crew-goal-1"]["suggested_type"] == "goal"
    assert decisions["crew-goal-1"]["decision"] == "auto"

    assert decisions["crew-debt-1"]["suggested_type"] == "debt"
    assert decisions["crew-debt-1"]["decision"] == "review"

    assert decisions["crew-loose-1"]["decision"] == "review"

    assert "crew-checking" not in decisions
    assert preview.preview_id


def test_preview_is_a_stable_snapshot(db_path):
    repository = FinancialRepository(db_path)
    _seed_pocket(repository, "crew-goal-1")

    preview = preview_legacy_migration(db_path)
    _seed_pocket(repository, "crew-goal-later")

    report = apply_legacy_migration(preview.preview_id, db_path=db_path)
    applied = {item["legacy_id"] for item in report.applied}
    assert "crew-goal-1" in applied
    assert "crew-goal-later" not in applied


def test_apply_creates_commitments_with_provenance_and_review_rows(db_path):
    repository = FinancialRepository(db_path)
    goal = _seed_pocket(repository, "crew-goal-1", name="Vacation", balance=250.0)
    _seed_pocket(repository, "crew-debt-1", name="Card payments")
    _link_credit_card_pocket(db_path, "crew-debt-1")
    _seed_pocket(repository, "crew-loose-1", name="Mystery", with_connection=False)

    commitments_repository = CommitmentRepository(db_path)
    preview = preview_legacy_migration(db_path)
    report = apply_legacy_migration(preview.preview_id, db_path=db_path)

    assert len(report.applied) == 1
    assert report.applied[0]["legacy_id"] == "crew-goal-1"
    assert len(report.review) == 2

    commitment = commitments_repository.get_commitment_by_legacy("financial_accounts", "crew-goal-1")
    assert commitment is not None
    assert commitment.type == "goal"
    assert commitment.name == "Vacation"
    assert commitment.backing_account_id == goal.id
    assert commitment.target_amount is None
    assert commitment.migration_version

    with sqlite3.connect(db_path) as connection:
        queued = connection.execute(
            "SELECT legacy_id, suggested_type, reason FROM migration_review_queue ORDER BY legacy_id"
        ).fetchall()
    assert {row[0] for row in queued} == {"crew-debt-1", "crew-loose-1"}
    assert all(row[2] for row in queued)


def test_apply_is_idempotent_and_leaves_sources_untouched(db_path):
    repository = FinancialRepository(db_path)
    _seed_pocket(repository, "crew-goal-1", balance=111.11)

    commitments_repository = CommitmentRepository(db_path)
    before = repository.list_accounts()
    preview = preview_legacy_migration(db_path)
    apply_legacy_migration(preview.preview_id, db_path=db_path)
    first = apply_legacy_migration(preview.preview_id, db_path=db_path)

    assert first.applied == []  # already applied; no duplicates
    assert commitments_repository.get_commitment_by_legacy("financial_accounts", "crew-goal-1") is not None

    after = repository.list_accounts()
    assert [(a.id, a.external_id, a.balance) for a in after] == [
        (a.id, a.external_id, a.balance) for a in before
    ]
    assert after[0].balance == 111.11

    second_preview = preview_legacy_migration(db_path)
    decisions = {item["legacy_id"]: item for item in second_preview.decisions}
    assert decisions["crew-goal-1"]["decision"] == "already_migrated"


def test_review_queue_items_can_be_resolved_into_commitments(db_path):
    repository = FinancialRepository(db_path)
    debt = _seed_pocket(repository, "crew-debt-1", name="Card payments")
    _link_credit_card_pocket(db_path, "crew-debt-1")

    preview = preview_legacy_migration(db_path)
    report = apply_legacy_migration(preview.preview_id, db_path=db_path)
    review_entry = report.review[0]

    from meridian.migrate_legacy import resolve_review

    commitments_repository = CommitmentRepository(db_path)
    commitment = resolve_review(
        db_path,
        review_entry["queue_id"],
        type="debt",
        minimum_payment=35.0,
    )

    assert commitment.minimum_payment == 35.0
    assert commitment.legacy_id == "crew-debt-1"
    assert commitment.backing_account_id == debt.id

    with sqlite3.connect(db_path) as connection:
        resolved = connection.execute(
            "SELECT resolution, resolved_at FROM migration_review_queue WHERE id = ?",
            (review_entry["queue_id"],),
        ).fetchone()
    assert resolved[0] == "accepted"
    assert resolved[1]
    assert commitments_repository.get_commitment_by_legacy("financial_accounts", "crew-debt-1") is not None


def test_migration_never_invokes_crew(db_path):
    import sys

    repository = FinancialRepository(db_path)
    _seed_pocket(repository, "crew-goal-1")

    saved_crew = {name: module for name, module in sys.modules.items() if "crew" in name}
    try:
        for name in list(sys.modules):
            if name.startswith("crew"):
                del sys.modules[name]

        preview = preview_legacy_migration(db_path)
        apply_legacy_migration(preview.preview_id, db_path=db_path)
    finally:
        sys.modules.update(saved_crew)
