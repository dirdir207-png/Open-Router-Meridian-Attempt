"""Persistence for funding rules (local planning metadata; never Crew state)."""

import sqlite3
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from .db import run_migrations
from .funding import FundingRule

_KINDS = (
    "fixed_per_paycheck",
    "percent_of_paycheck",
    "calendar",
    "even_by_due_date",
    "priority_waterfall",
)

_CENT = Decimal("0.01")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(value, field: str) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid amount") from exc


class FundingRuleRepository:
    def __init__(self, db_path: str):
        self._db_path = db_path
        run_migrations(db_path)

    def _connect(self):
        connection = sqlite3.connect(self._db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def create(
        self,
        *,
        commitment_id: int,
        kind: str,
        amount=None,
        percent=None,
        cadence=None,
        day_of_month=None,
        start_date=None,
        horizon_end=None,
        min_contribution=None,
        max_contribution=None,
        paused=False,
        one_time_override=None,
        priority=3,
    ) -> FundingRule:
        if kind not in _KINDS:
            raise ValueError(f"unknown funding rule kind: {kind}")
        start = start_date or date.today()
        row_id = None
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM commitments WHERE id = ?", (commitment_id,)
            ).fetchone()
            if exists is None:
                raise ValueError("commitment_id must reference an existing commitment")
            cursor = connection.execute(
                "INSERT INTO funding_rules (commitment_id, kind, amount, percent, cadence,"
                " day_of_month, start_date, horizon_end, min_contribution, max_contribution,"
                " paused, skip_dates, one_time_override, priority, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?)",
                (
                    commitment_id,
                    kind,
                    _money(amount, "amount"),
                    _money(percent, "percent"),
                    cadence,
                    day_of_month,
                    start.isoformat(),
                    horizon_end.isoformat() if isinstance(horizon_end, date) else horizon_end,
                    _money(min_contribution, "min_contribution"),
                    _money(max_contribution, "max_contribution"),
                    1 if paused else 0,
                    _money(one_time_override, "one_time_override"),
                    priority,
                    _now(),
                    _now(),
                ),
            )
            row_id = cursor.lastrowid
        return self.get(row_id)

    def update(self, rule_id: int, **fields) -> FundingRule:
        allowed = {
            "amount", "percent", "cadence", "day_of_month", "horizon_end",
            "min_contribution", "max_contribution", "paused", "one_time_override",
            "priority", "start_date",
        }
        assignments = {}
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in ("amount", "percent", "min_contribution", "max_contribution", "one_time_override"):
                assignments[key] = _money(value, key)
            elif key in ("start_date", "horizon_end"):
                assignments[key] = value.isoformat() if isinstance(value, date) else value
            elif key == "paused":
                assignments[key] = 1 if value else 0
            else:
                assignments[key] = value
        if not assignments:
            return self.get(rule_id)
        assignments["updated_at"] = _now()
        columns = ", ".join(f"{key} = ?" for key in assignments)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE funding_rules SET {columns} WHERE id = ?",
                [*assignments.values(), rule_id],
            )
        return self.get(rule_id)

    def get(self, rule_id: int) -> Optional[FundingRule]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM funding_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_commitment(self, commitment_id: int) -> list[FundingRule]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM funding_rules WHERE commitment_id = ? ORDER BY id",
                (commitment_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_all(self) -> list[FundingRule]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM funding_rules ORDER BY id").fetchall()
        return [self._from_row(row) for row in rows]

    def _from_row(self, row) -> FundingRule:
        horizon_end = row["horizon_end"]
        return FundingRule(
            id=str(row["id"]),
            commitment_id=str(row["commitment_id"]),
            kind=row["kind"],
            amount=Decimal(str(row["amount"])) if row["amount"] is not None else None,
            percent=Decimal(str(row["percent"])) if row["percent"] is not None else None,
            cadence=row["cadence"],
            day_of_month=row["day_of_month"],
            start_date=date.fromisoformat(row["start_date"]),
            horizon_end=date.fromisoformat(horizon_end) if horizon_end else None,
            min_contribution=(
                Decimal(str(row["min_contribution"])) if row["min_contribution"] is not None else None
            ),
            max_contribution=(
                Decimal(str(row["max_contribution"])) if row["max_contribution"] is not None else None
            ),
            paused=bool(row["paused"]),
            skip_dates=frozenset(),
            one_time_override=(
                Decimal(str(row["one_time_override"])) if row["one_time_override"] is not None else None
            ),
            priority=row["priority"],
        )
