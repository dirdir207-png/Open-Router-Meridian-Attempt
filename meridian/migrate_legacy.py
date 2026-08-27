"""Non-destructive migration of legacy pocket records into Commitments.

Legacy Crew pockets live in the normalized graph as financial_accounts
rows. Bills live provider-side and arrive through adapters later; this
module migrates exactly what is stored locally, marks everything that
cannot be decided safely for review, never contacts Crew, and never
mutates the source rows.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .commitments import CommitmentRepository, CommitmentType
from .db import run_migrations

_MIGRATION_VERSION = "005"
_LEGACY_SOURCE = "financial_accounts"


@dataclass(frozen=True)
class MigrationPreview:
    preview_id: str
    created_at: str
    decisions: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class MigrationReport:
    preview_id: str
    applied: list[dict] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _debt_linked_pocket_ids(connection: sqlite3.Connection) -> set[str]:
    """Credit-card payment pockets linked through legacy configuration."""
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'credit_card_config'"
    ).fetchone()
    if table is None:
        return set()
    rows = connection.execute(
        "SELECT pocket_id FROM credit_card_config WHERE pocket_id IS NOT NULL"
    ).fetchall()
    return {row[0] for row in rows}


def _decide_account(account, debt_links: set[str], migrated: set[str]) -> Optional[dict]:
    if account["account_type"] != "pocket":
        return None
    if account["external_id"] in migrated:
        return {
            "source_type": "account",
            "legacy_source": _LEGACY_SOURCE,
            "legacy_id": account["external_id"],
            "decision": "already_migrated",
            "suggested_type": None,
            "name": account["name"],
            "reason": None,
        }

    if account["external_id"] in debt_links:
        return {
            "source_type": "account",
            "legacy_source": _LEGACY_SOURCE,
            "legacy_id": account["external_id"],
            "decision": "review",
            "suggested_type": "debt",
            "name": account["name"],
            "reason": "Confirm the minimum payment and payoff details before creating the debt commitment.",
        }

    if account["connection_id"] is None:
        return {
            "source_type": "account",
            "legacy_source": _LEGACY_SOURCE,
            "legacy_id": account["external_id"],
            "decision": "review",
            "suggested_type": "goal",
            "name": account["name"],
            "reason": "This pocket has no provider provenance yet, so it needs review before migrating.",
        }

    return {
        "source_type": "account",
        "legacy_source": _LEGACY_SOURCE,
        "legacy_id": account["external_id"],
        "decision": "auto",
        "suggested_type": "goal",
        "name": account["name"],
        "reason": None,
        "fields_pending": ["target_amount"],
    }


def preview_legacy_migration(db_path: str) -> MigrationPreview:
    """Snapshot the current legacy rows and the decisions that follow from them."""
    run_migrations(db_path)
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        debt_links = _debt_linked_pocket_ids(connection)
        migrated = {
            row[0]
            for row in connection.execute(
                "SELECT legacy_id FROM commitments WHERE legacy_source = ?",
                (_LEGACY_SOURCE,),
            ).fetchall()
        }
        accounts = connection.execute(
            "SELECT id, external_id, name, account_type, balance, connection_id"
            " FROM financial_accounts ORDER BY id"
        ).fetchall()
    finally:
        connection.close()

    decisions = []
    for account in accounts:
        decision = _decide_account(account, debt_links, migrated)
        if decision is None:
            continue
        decision["payload"] = {
            "account_id": account["id"],
            "external_id": account["external_id"],
            "name": account["name"],
            "balance": account["balance"],
        }
        decisions.append(decision)

    preview = MigrationPreview(
        preview_id=str(uuid.uuid4()),
        created_at=_now(),
        decisions=decisions,
    )
    _persist_preview(db_path, preview)
    return preview


def _persist_preview(db_path: str, preview: MigrationPreview) -> None:
    with sqlite3.connect(db_path, timeout=30) as connection:
        connection.execute(
            "INSERT INTO migration_previews (preview_id, created_at, payload) VALUES (?, ?, ?)",
            (
                preview.preview_id,
                preview.created_at,
                json.dumps(preview.decisions, separators=(",", ":")),
            ),
        )


def _load_preview(db_path: str, preview_id: str) -> list[dict]:
    with sqlite3.connect(db_path, timeout=30) as connection:
        row = connection.execute(
            "SELECT payload FROM migration_previews WHERE preview_id = ?", (preview_id,)
        ).fetchone()
    if row is None:
        raise ValueError("migration preview not found")
    return json.loads(row[0])


def apply_legacy_migration(preview_id: str, *, db_path: str) -> MigrationReport:
    """Apply an explicit preview: auto rows become commitments, the rest queue for review."""
    run_migrations(db_path)
    decisions = _load_preview(db_path, preview_id)
    repository = CommitmentRepository(db_path)
    applied: list[dict] = []
    review: list[dict] = []

    with sqlite3.connect(db_path, timeout=30) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for decision in decisions:
                if decision.get("decision") != "auto":
                    continue
                legacy_id = decision["legacy_id"]
                if repository.get_commitment_by_legacy(_LEGACY_SOURCE, legacy_id) is not None:
                    continue
                payload = decision.get("payload") or {}
                pending_fields = decision.get("fields_pending") or []
                record = repository.build(
                    type=CommitmentType(decision["suggested_type"]),
                    name=decision["name"],
                    funded_amount=payload.get("balance") or 0.0,
                    backing_account_id=payload.get("account_id"),
                    legacy_source=_LEGACY_SOURCE,
                    legacy_id=legacy_id,
                    migration_version=_MIGRATION_VERSION,
                    _allow_pending_target="target_amount" in pending_fields,
                )
                commitment_id = repository.insert_record(connection, record)
                applied.append({"legacy_id": legacy_id, "commitment_id": commitment_id})

            for decision in decisions:
                if decision.get("decision") != "review":
                    continue
                legacy_id = decision["legacy_id"]
                pending = connection.execute(
                    "SELECT 1 FROM migration_review_queue"
                    " WHERE legacy_id = ? AND resolution IS NULL",
                    (legacy_id,),
                ).fetchone()
                if pending is not None:
                    continue
                payload = decision.get("payload") or {}
                cursor = connection.execute(
                    "INSERT INTO migration_review_queue"
                    " (preview_id, source_type, legacy_source, legacy_id, suggested_type,"
                    "  name, reason, payload, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        preview_id,
                        decision["source_type"],
                        decision["legacy_source"],
                        legacy_id,
                        decision["suggested_type"],
                        decision["name"],
                        decision["reason"],
                        json.dumps(payload, separators=(",", ":")),
                        _now(),
                    ),
                )
                review.append(
                    {
                        "queue_id": cursor.lastrowid,
                        "legacy_id": legacy_id,
                        "suggested_type": decision["suggested_type"],
                        "reason": decision["reason"],
                    }
                )
        except Exception:
            connection.execute("ROLLBACK")
            raise

    return MigrationReport(preview_id=preview_id, applied=applied, review=review)


def resolve_review(db_path: str, queue_id: int, *, type: str, **fields):
    """Turn one reviewed queue entry into a commitment with full provenance."""
    run_migrations(db_path)
    with sqlite3.connect(db_path, timeout=30) as connection:
        connection.row_factory = sqlite3.Row
        entry = connection.execute(
            "SELECT * FROM migration_review_queue WHERE id = ? AND resolution IS NULL",
            (queue_id,),
        ).fetchone()
    if entry is None:
        raise ValueError("review entry not found or already resolved")

    payload = json.loads(entry["payload"])
    repository = CommitmentRepository(db_path)
    commitment = repository.create(
        type=CommitmentType(type),
        name=entry["name"],
        funded_amount=payload.get("balance") or 0.0,
        backing_account_id=payload.get("account_id"),
        legacy_source=_LEGACY_SOURCE,
        legacy_id=entry["legacy_id"],
        migration_version=_MIGRATION_VERSION,
        **fields,
    )
    with sqlite3.connect(db_path, timeout=30) as connection:
        connection.execute(
            "UPDATE migration_review_queue SET resolution = 'accepted', resolved_at = ? WHERE id = ?",
            (_now(), queue_id),
        )
    return commitment
