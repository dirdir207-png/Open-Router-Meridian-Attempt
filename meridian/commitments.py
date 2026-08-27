"""Unified Commitment domain: typed financial intentions over Crew pockets.

A Commitment describes why money is held and how it should be funded.
Crew pockets remain the real banking containers; commitments are local
planning records and never talk to providers.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import Optional

from .db import run_migrations


class CommitmentType(str, Enum):
    BILL = "bill"
    GOAL = "goal"
    RESERVE = "reserve"
    BUFFER = "buffer"
    DEBT = "debt"


class CommitmentStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


_MIGRATION_VERSION = "005"

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Commitment:
    id: int
    type: CommitmentType
    name: str
    status: CommitmentStatus
    priority: int
    currency: str
    target_amount: Optional[float]
    target_date: Optional[str]
    funded_amount: float
    amount: Optional[float]
    due_date: Optional[str]
    recurrence: Optional[str]
    cadence: Optional[str]
    minimum_payment: Optional[float]
    buffer_minimum: Optional[float]
    payoff_strategy: Optional[str]
    backing_account_id: Optional[int]
    legacy_source: Optional[str]
    legacy_id: Optional[str]
    migration_version: Optional[str]
    created_at: str
    updated_at: str


_COLUMNS = (
    "id, type, name, status, priority, currency, target_amount, target_date,"
    " funded_amount, amount, due_date, recurrence, cadence, minimum_payment,"
    " buffer_minimum, payoff_strategy, backing_account_id, legacy_source,"
    " legacy_id, migration_version, created_at, updated_at"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_money(value, field: str, *, required: bool = False) -> Optional[float]:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a positive amount")
    try:
        money = Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a positive amount") from exc
    if money < 0:
        raise ValueError(f"{field} must be a positive amount")
    return float(money)


def _require_positive(value, field: str) -> float:
    money = _as_money(value, field, required=True)
    assert money is not None
    if money <= 0:
        raise ValueError(f"{field} must be a positive amount")
    return money


class CommitmentRepository:
    """SQLite-backed store and validation for commitments."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        run_migrations(db_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    # ---------- validation ----------

    def _validate(self, fields: dict, *, creating: bool) -> dict:
        commitment_type = fields.get("type") or fields.get("_existing_type")
        if creating and not isinstance(commitment_type, CommitmentType):
            raise ValueError("type must be a CommitmentType")

        name = fields.get("name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("name must be a non-empty string")

        priority = fields.get("priority")
        if priority is not None:
            if isinstance(priority, bool) or not isinstance(priority, int) or priority < 1:
                raise ValueError("priority must be a positive integer")

        status = fields.get("status")
        if status is not None and not isinstance(status, CommitmentStatus):
            raise ValueError("status must be a CommitmentStatus")

        currency = fields.get("currency")
        if currency is not None and (not isinstance(currency, str) or len(currency) != 3):
            raise ValueError("currency must be a three-letter code")

        commitment_type = commitment_type or fields.get("_existing_type")
        allow_pending_target = fields.get("_allow_pending_target", False)
        validated: dict = {}

        if name is not None:
            validated["name"] = name.strip()
        if priority is not None:
            validated["priority"] = priority
        if status is not None:
            validated["status"] = status
        if currency is not None:
            validated["currency"] = currency.upper()

        if fields.get("target_amount", ...) is not ...:
            target = fields.get("target_amount")
            if commitment_type is CommitmentType.GOAL and creating:
                if target is None and not allow_pending_target:
                    raise ValueError("target_amount is required for goals")
                validated["target_amount"] = (
                    None if target is None else _require_positive(target, "target_amount")
                )
            else:
                validated["target_amount"] = _as_money(target, "target_amount")
        elif creating and commitment_type is CommitmentType.GOAL:
            if not allow_pending_target:
                raise ValueError("target_amount is required for goals")
            validated["target_amount"] = None

        if fields.get("amount", ...) is not ...:
            amount = fields.get("amount")
            if commitment_type in (CommitmentType.BILL, CommitmentType.RESERVE) and creating:
                validated["amount"] = _require_positive(amount, "amount")
            else:
                if amount is None and creating:
                    raise ValueError("amount is required")
                validated["amount"] = _as_money(amount, "amount")
        elif creating and commitment_type in (CommitmentType.BILL, CommitmentType.RESERVE):
            raise ValueError("amount is required")

        if fields.get("minimum_payment", ...) is not ...:
            minimum = fields.get("minimum_payment")
            if commitment_type is CommitmentType.DEBT and creating:
                validated["minimum_payment"] = _require_positive(minimum, "minimum_payment")
            else:
                if minimum is None and creating:
                    raise ValueError("minimum_payment is required for debts")
                validated["minimum_payment"] = _as_money(minimum, "minimum_payment")
        elif creating and commitment_type is CommitmentType.DEBT:
            raise ValueError("minimum_payment is required for debts")

        if fields.get("buffer_minimum", ...) is not ...:
            minimum = fields.get("buffer_minimum")
            if minimum is None and creating:
                raise ValueError("buffer_minimum is required for buffers")
            validated["buffer_minimum"] = _as_money(minimum, "buffer_minimum")
        elif creating and commitment_type is CommitmentType.BUFFER:
            raise ValueError("buffer_minimum is required for buffers")

        for text_field in (
            "target_date",
            "due_date",
            "recurrence",
            "cadence",
            "payoff_strategy",
        ):
            if fields.get(text_field, ...) is not ...:
                value = fields.get(text_field)
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    raise ValueError(f"{text_field} must be a non-empty string when present")
                validated[text_field] = value

        if creating and commitment_type is CommitmentType.BILL:
            if not (fields.get("due_date") or fields.get("recurrence")):
                raise ValueError("bills need a due_date or recurrence")

        if creating and commitment_type is CommitmentType.RESERVE:
            if not fields.get("cadence"):
                raise ValueError("reserves need a cadence")

        if fields.get("funded_amount", ...) is not ...:
            validated["funded_amount"] = _as_money(
                fields.get("funded_amount"), "funded_amount"
            ) or 0.0

        if fields.get("backing_account_id", ...) is not ...:
            backing = fields.get("backing_account_id")
            if backing is not None:
                if isinstance(backing, bool) or not isinstance(backing, int):
                    raise ValueError("backing_account_id must reference an account")
                with self._connect() as connection:
                    exists = connection.execute(
                        "SELECT 1 FROM financial_accounts WHERE id = ?", (backing,)
                    ).fetchone()
                if exists is None:
                    raise ValueError("backing_account_id must reference an existing account")
            validated["backing_account_id"] = backing

        if creating:
            legacy_source = fields.get("legacy_source")
            legacy_id = fields.get("legacy_id")
            if (legacy_source is None) != (legacy_id is None):
                raise ValueError("legacy_source and legacy_id must be provided together")
            validated["legacy_source"] = legacy_source
            validated["legacy_id"] = legacy_id
            validated["migration_version"] = fields.get("migration_version")

        return validated

    # ---------- persistence ----------

    def build(self, *, type: CommitmentType, name: str, **fields) -> dict:
        """Validate commitment fields and return the insert record without writing."""
        values = {
            "type": type,
            "name": name,
            "status": CommitmentStatus.ACTIVE,
            "priority": 3,
            "currency": "USD",
            "funded_amount": 0.0,
            **fields,
        }
        validated = self._validate(values, creating=True)
        return {
            "type": values["type"].value,
            "name": values["name"],
            "status": values["status"].value,
            "priority": values["priority"],
            "currency": values["currency"],
            "target_amount": validated.get("target_amount"),
            "amount": validated.get("amount"),
            "minimum_payment": validated.get("minimum_payment"),
            "buffer_minimum": validated.get("buffer_minimum"),
            "funded_amount": validated.get("funded_amount", 0.0),
            "target_date": validated.get("target_date"),
            "due_date": validated.get("due_date"),
            "recurrence": validated.get("recurrence"),
            "cadence": validated.get("cadence"),
            "payoff_strategy": validated.get("payoff_strategy"),
            "backing_account_id": validated.get("backing_account_id"),
            "legacy_source": validated.get("legacy_source"),
            "legacy_id": validated.get("legacy_id"),
            "migration_version": validated.get("migration_version"),
        }

    def insert_record(self, connection: sqlite3.Connection, record: dict) -> int:
        """Write a validated record on the caller's connection (for outer transactions)."""
        columns = [
            "type", "name", "status", "priority", "currency", "target_amount",
            "amount", "minimum_payment", "buffer_minimum", "funded_amount",
            "target_date", "due_date", "recurrence", "cadence", "payoff_strategy",
            "backing_account_id", "legacy_source", "legacy_id", "migration_version",
            "created_at", "updated_at",
        ]
        now = _now()
        values = {**record, "created_at": now, "updated_at": now}
        placeholders = ", ".join("?" for _ in columns)
        try:
            cursor = connection.execute(
                f"INSERT INTO commitments ({', '.join(columns)}) VALUES ({placeholders})",
                [values[column] for column in columns],
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                "a commitment with this legacy identity already exists"
            ) from exc
        return cursor.lastrowid

    def create(self, *, type: CommitmentType, name: str, **fields) -> Commitment:
        record = self.build(type=type, name=name, **fields)
        with self._connect() as connection:
            commitment_id = self.insert_record(connection, record)
        return self.get(commitment_id)

    def update(self, commitment_id: int, **fields) -> Commitment:
        existing = self.get(commitment_id)
        if existing is None:
            raise ValueError("commitment not found")
        fields.setdefault("_existing_type", existing.type)
        validated = self._validate(fields, creating=False)

        assignments = {key: value for key, value in validated.items() if value is not ...}
        if not assignments:
            return existing
        assignments["updated_at"] = _now()
        columns = ", ".join(f"{key} = ?" for key in assignments)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE commitments SET {columns} WHERE id = ?",
                [*assignments.values(), commitment_id],
            )
        return self.get(commitment_id)

    def get(self, commitment_id: int) -> Optional[Commitment]:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM commitments WHERE id = ?", (commitment_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_commitment_by_legacy(
        self, legacy_source: str, legacy_id: str
    ) -> Optional[Commitment]:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM commitments WHERE legacy_source = ? AND legacy_id = ?",
                (legacy_source, legacy_id),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_active(self) -> list[Commitment]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM commitments WHERE status != 'archived'"
                " ORDER BY priority, id"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def archive(self, commitment_id: int) -> Commitment:
        with self._connect() as connection:
            connection.execute(
                "UPDATE commitments SET status = 'archived', updated_at = ? WHERE id = ?",
                (_now(), commitment_id),
            )
        return self.get(commitment_id)

    def _from_row(self, row: sqlite3.Row) -> Commitment:
        return Commitment(
            id=row["id"],
            type=CommitmentType(row["type"]),
            name=row["name"],
            status=CommitmentStatus(row["status"]),
            priority=row["priority"],
            currency=row["currency"],
            target_amount=row["target_amount"],
            target_date=row["target_date"],
            funded_amount=row["funded_amount"],
            amount=row["amount"],
            due_date=row["due_date"],
            recurrence=row["recurrence"],
            cadence=row["cadence"],
            minimum_payment=row["minimum_payment"],
            buffer_minimum=row["buffer_minimum"],
            payoff_strategy=row["payoff_strategy"],
            backing_account_id=row["backing_account_id"],
            legacy_source=row["legacy_source"],
            legacy_id=row["legacy_id"],
            migration_version=row["migration_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
