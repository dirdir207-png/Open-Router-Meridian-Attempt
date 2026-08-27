"""Provider-neutral writes and stable reads for Meridian financial records."""

import base64
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .db import run_migrations
from .models import AccountRecord, TransactionRecord

_ACCOUNT_COLUMNS = (
    "id, provider, external_id, name, account_type, balance, currency, "
    "available_balance, is_active, source_updated_at, synced_at, created_at, "
    "updated_at"
)
_TRANSACTION_COLUMNS = (
    "id, provider, external_id, account_id, amount, currency, occurred_at, "
    "posted_at, description, merchant, status, raw_description, "
    "source_updated_at, synced_at, created_at, updated_at"
)
_ACCOUNT_FRESHNESS_CONDITION = """
    financial_accounts.source_updated_at IS NULL
    OR (
        excluded.source_updated_at IS NOT NULL
        AND excluded.source_updated_at > financial_accounts.source_updated_at
    )
"""
_TRANSACTION_FRESHNESS_CONDITION = """
    financial_transactions.source_updated_at IS NULL
    OR (
        excluded.source_updated_at IS NOT NULL
        AND excluded.source_updated_at > financial_transactions.source_updated_at
    )
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _encode_cursor(occurred_at: str, record_id: int) -> str:
    payload = json.dumps([occurred_at, record_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        occurred_at, record_id = json.loads(payload)
        if not isinstance(occurred_at, str) or not isinstance(record_id, int):
            raise ValueError
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid transaction cursor") from exc
    return occurred_at, record_id


class FinancialRepository:
    def __init__(self, db_path: str):
        self._db_path = db_path
        run_migrations(db_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def upsert_account(
        self,
        *,
        provider: str,
        external_id: str,
        name: str,
        account_type: str,
        balance: float,
        currency: str = "USD",
        available_balance: Optional[float] = None,
        is_active: bool = True,
        source_updated_at: Optional[str] = None,
        synced_at: Optional[str] = None,
    ) -> AccountRecord:
        timestamp = synced_at or _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"""
                INSERT INTO financial_accounts (
                    provider, external_id, name, account_type, balance,
                    available_balance, currency, is_active, source_updated_at,
                    synced_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, external_id) DO UPDATE SET
                    name = CASE WHEN {_ACCOUNT_FRESHNESS_CONDITION}
                        THEN excluded.name ELSE financial_accounts.name END,
                    account_type = CASE WHEN {_ACCOUNT_FRESHNESS_CONDITION}
                        THEN excluded.account_type ELSE financial_accounts.account_type END,
                    balance = CASE WHEN {_ACCOUNT_FRESHNESS_CONDITION}
                        THEN excluded.balance ELSE financial_accounts.balance END,
                    available_balance = CASE WHEN {_ACCOUNT_FRESHNESS_CONDITION}
                        THEN excluded.available_balance
                        ELSE financial_accounts.available_balance END,
                    currency = CASE WHEN {_ACCOUNT_FRESHNESS_CONDITION}
                        THEN excluded.currency ELSE financial_accounts.currency END,
                    is_active = CASE WHEN {_ACCOUNT_FRESHNESS_CONDITION}
                        THEN excluded.is_active ELSE financial_accounts.is_active END,
                    source_updated_at = CASE
                        WHEN excluded.source_updated_at IS NOT NULL
                            AND {_ACCOUNT_FRESHNESS_CONDITION}
                        THEN excluded.source_updated_at
                        ELSE financial_accounts.source_updated_at
                    END,
                    synced_at = CASE WHEN excluded.synced_at > financial_accounts.synced_at
                        THEN excluded.synced_at ELSE financial_accounts.synced_at END,
                    updated_at = CASE
                        WHEN {_ACCOUNT_FRESHNESS_CONDITION}
                            OR excluded.synced_at > financial_accounts.synced_at
                        THEN excluded.updated_at
                        ELSE financial_accounts.updated_at
                    END
                """,
                (
                    provider,
                    external_id,
                    name,
                    account_type,
                    balance,
                    available_balance,
                    currency,
                    int(is_active),
                    source_updated_at,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM financial_accounts "
                "WHERE provider = ? AND external_id = ?",
                (provider, external_id),
            ).fetchone()
        assert row is not None
        return self._account_from_row(row)

    def upsert_transaction(
        self,
        *,
        provider: str,
        external_id: str,
        account_id: int,
        amount: float,
        occurred_at: str,
        description: str,
        status: str,
        currency: str = "USD",
        posted_at: Optional[str] = None,
        merchant: Optional[str] = None,
        raw_description: Optional[str] = None,
        source_updated_at: Optional[str] = None,
        synced_at: Optional[str] = None,
    ) -> TransactionRecord:
        timestamp = synced_at or _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            matching_account = connection.execute(
                "SELECT 1 FROM financial_accounts WHERE id = ? AND provider = ?",
                (account_id, provider),
            ).fetchone()
            if matching_account is None:
                raise ValueError("Transaction provider must match account provider")
            connection.execute(
                f"""
                INSERT INTO financial_transactions (
                    provider, external_id, account_id, amount, currency,
                    occurred_at, posted_at, description, merchant, status,
                    raw_description, source_updated_at, synced_at, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, external_id) DO UPDATE SET
                    account_id = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.account_id ELSE financial_transactions.account_id END,
                    amount = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.amount ELSE financial_transactions.amount END,
                    currency = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.currency ELSE financial_transactions.currency END,
                    occurred_at = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.occurred_at ELSE financial_transactions.occurred_at END,
                    posted_at = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.posted_at ELSE financial_transactions.posted_at END,
                    description = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.description ELSE financial_transactions.description END,
                    merchant = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.merchant ELSE financial_transactions.merchant END,
                    status = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.status ELSE financial_transactions.status END,
                    raw_description = CASE WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.raw_description
                        ELSE financial_transactions.raw_description END,
                    source_updated_at = CASE
                        WHEN excluded.source_updated_at IS NOT NULL
                            AND {_TRANSACTION_FRESHNESS_CONDITION}
                        THEN excluded.source_updated_at
                        ELSE financial_transactions.source_updated_at
                    END,
                    synced_at = CASE
                        WHEN excluded.synced_at > financial_transactions.synced_at
                        THEN excluded.synced_at ELSE financial_transactions.synced_at
                    END,
                    updated_at = CASE
                        WHEN {_TRANSACTION_FRESHNESS_CONDITION}
                            OR excluded.synced_at > financial_transactions.synced_at
                        THEN excluded.updated_at
                        ELSE financial_transactions.updated_at
                    END
                """,
                (
                    provider,
                    external_id,
                    account_id,
                    amount,
                    currency,
                    occurred_at,
                    posted_at,
                    description,
                    merchant,
                    status,
                    raw_description,
                    source_updated_at,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                f"SELECT {_TRANSACTION_COLUMNS} FROM financial_transactions "
                "WHERE provider = ? AND external_id = ?",
                (provider, external_id),
            ).fetchone()
        assert row is not None
        return self._transaction_from_row(row)

    def list_accounts(self) -> list[AccountRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM financial_accounts "
                "ORDER BY name COLLATE NOCASE ASC, id ASC"
            ).fetchall()
        return [self._account_from_row(row) for row in rows]

    def list_transactions(
        self,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
        account_id: Optional[int] = None,
    ) -> tuple[list[TransactionRecord], Optional[str]]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")

        conditions: list[str] = []
        parameters: list[object] = []
        if account_id is not None:
            conditions.append("account_id = ?")
            parameters.append(account_id)
        if cursor is not None:
            occurred_at, record_id = _decode_cursor(cursor)
            conditions.append("(occurred_at < ? OR (occurred_at = ? AND id < ?))")
            parameters.extend((occurred_at, occurred_at, record_id))

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        parameters.append(limit + 1)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_TRANSACTION_COLUMNS} FROM financial_transactions"
                f"{where} ORDER BY occurred_at DESC, id DESC LIMIT ?",
                tuple(parameters),
            ).fetchall()

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        records = [self._transaction_from_row(row) for row in page_rows]
        next_cursor = None
        if has_more and records:
            last = records[-1]
            next_cursor = _encode_cursor(last.occurred_at, last.id)
        return records, next_cursor

    @staticmethod
    def _account_from_row(row: sqlite3.Row) -> AccountRecord:
        values = dict(row)
        values["is_active"] = bool(values["is_active"])
        return AccountRecord(**values)

    @staticmethod
    def _transaction_from_row(row: sqlite3.Row) -> TransactionRecord:
        return TransactionRecord(**dict(row))
