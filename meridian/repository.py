"""Provider-neutral writes and stable reads for Meridian financial records."""

import base64
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from .db import run_migrations
from .models import AccountRecord, TransactionRecord


@dataclass(frozen=True)
class SyncRun:
    id: int
    connection_id: int


@dataclass(frozen=True)
class ProviderConnectionFreshness:
    """The complete-sync state and source timestamps behind a read model."""

    connection_id: int
    provider: str
    status: str
    last_successful_at: Optional[str]
    source_updated_at: tuple[Optional[str], ...]


@dataclass(frozen=True)
class ProviderFreshnessScope:
    """Credential-free provider state and linkage completeness for one read."""

    connections: tuple[ProviderConnectionFreshness, ...]
    has_unlinked_records: bool


_CANONICAL_OCCURRED_AT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)


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


def _canonical_occurred_at(value: str) -> str:
    """Store occurrence times in the UTC spelling used by keyset cursors."""
    if not isinstance(value, str):
        raise ValueError("occurred_at must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("occurred_at must be a timezone-aware timestamp")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        encoded = cursor.encode("ascii")
        payload = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(payload) != encoded:
            raise ValueError
        occurred_at, record_id = json.loads(payload.decode("utf-8"))
        if (
            not isinstance(occurred_at, str)
            or type(record_id) is not int
            or record_id < 1
            or _CANONICAL_OCCURRED_AT.fullmatch(occurred_at) is None
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError
        canonical_payload = json.dumps(
            [occurred_at, record_id], separators=(",", ":")
        ).encode("utf-8")
        if payload != canonical_payload:
            raise ValueError
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid transaction cursor") from exc
    return occurred_at, record_id


class FinancialRepository:
    def __init__(self, db_path: str):
        self._db_path = db_path
        run_migrations(db_path)
        self._backfill_occurred_at()

    def _backfill_occurred_at(self) -> None:
        """Canonicalize rows written before fixed-width cursor keys existed."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, occurred_at FROM financial_transactions"
            ).fetchall()
            updates = []
            for row in rows:
                canonical = _canonical_occurred_at(row["occurred_at"])
                if canonical != row["occurred_at"]:
                    updates.append((canonical, row["id"]))
            if updates:
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    "UPDATE financial_transactions SET occurred_at = ? WHERE id = ?",
                    updates,
                )

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
        connection_id: Optional[int] = None,
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
                    connection_id, available_balance, currency, is_active, source_updated_at,
                    synced_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, external_id) DO UPDATE SET
                    connection_id = COALESCE(excluded.connection_id, financial_accounts.connection_id),
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
                    connection_id,
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
        occurred_at = _canonical_occurred_at(occurred_at)
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

    def begin_sync_run(
        self,
        *,
        provider: str,
        connection_external_id: str,
        connection_name: str,
    ) -> SyncRun:
        """Record an attempted provider read without advancing freshness."""
        timestamp = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO provider_connections (
                    provider, external_id, display_name, status, last_attempted_at
                ) VALUES (?, ?, ?, 'syncing', ?)
                ON CONFLICT(provider, external_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    status = 'syncing',
                    last_attempted_at = excluded.last_attempted_at,
                    updated_at = excluded.last_attempted_at
                """,
                (provider, connection_external_id, connection_name, timestamp),
            )
            connection_row = connection.execute(
                "SELECT id FROM provider_connections WHERE provider = ? AND external_id = ?",
                (provider, connection_external_id),
            ).fetchone()
            assert connection_row is not None
            cursor = connection.execute(
                """
                INSERT INTO provider_sync_runs (connection_id, provider, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (connection_row["id"], provider, timestamp),
            )
        return SyncRun(id=int(cursor.lastrowid), connection_id=int(connection_row["id"]))

    def finish_sync_run(
        self,
        run_id: int,
        *,
        status: str,
        accounts_synced: int,
        transactions_synced: int,
        errors: int,
    ) -> None:
        """Finalize a run and advance connection freshness only when complete."""
        if status not in {"complete", "partial", "failed"}:
            raise ValueError("Invalid sync status")
        timestamp = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT connection_id FROM provider_sync_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError("Unknown sync run")
            connection.execute(
                """
                UPDATE provider_sync_runs
                SET status = ?, completed_at = ?, accounts_synced = ?,
                    transactions_synced = ?, errors = ?
                WHERE id = ?
                """,
                (status, timestamp, accounts_synced, transactions_synced, errors, run_id),
            )
            if status == "complete":
                connection.execute(
                    """
                    UPDATE provider_connections
                    SET status = 'healthy', last_successful_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, run["connection_id"]),
                )
            else:
                connection.execute(
                    "UPDATE provider_connections SET status = ?, updated_at = ? WHERE id = ?",
                    (status, timestamp, run["connection_id"]),
                )

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

    def get_transaction(self, transaction_id: int) -> Optional[TransactionRecord]:
        """Return one normalized transaction by its local, opaque Meridian id."""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_TRANSACTION_COLUMNS} FROM financial_transactions WHERE id = ?",
                (transaction_id,),
            ).fetchone()
        return self._transaction_from_row(row) if row is not None else None

    def get_freshness_scope(
        self,
        *,
        account_ids: Optional[Sequence[int]] = None,
        transaction_ids: Optional[Sequence[int]] = None,
        include_all_connections: bool = False,
        include_all_transaction_links: bool = False,
    ) -> ProviderFreshnessScope:
        """Return provider state and whether selected records lack a connection."""
        if account_ids is not None and transaction_ids is not None:
            raise ValueError("Specify account_ids or transaction_ids, not both")
        selected_ids = tuple(account_ids or transaction_ids or ())
        selected_records = account_ids is not None or transaction_ids is not None
        parameters: tuple[object, ...] = tuple(selected_ids)
        if account_ids is not None and selected_ids:
            placeholders = ", ".join("?" for _ in account_ids)
            selected_connections_sql = (
                "SELECT connection_id FROM financial_accounts "
                f"WHERE id IN ({placeholders})"
            )
        elif transaction_ids is not None and include_all_transaction_links:
            selected_connections_sql = (
                "SELECT account.connection_id "
                "FROM financial_transactions AS financial_transaction "
                "JOIN financial_accounts AS account "
                "ON account.id = financial_transaction.account_id"
            )
            parameters = ()
        elif transaction_ids is not None and selected_ids:
            placeholders = ", ".join("?" for _ in transaction_ids)
            selected_connections_sql = (
                "SELECT account.connection_id FROM financial_transactions AS financial_transaction "
                "JOIN financial_accounts AS account ON account.id = financial_transaction.account_id "
                f"WHERE financial_transaction.id IN ({placeholders})"
            )
        else:
            selected_connections_sql = None

        with self._connect() as connection:
            connection_ids: set[int] = set()
            has_unlinked_records = False
            if selected_connections_sql is not None:
                selected_rows = connection.execute(
                    selected_connections_sql, parameters
                ).fetchall()
                has_unlinked_records = any(
                    row["connection_id"] is None for row in selected_rows
                )
                connection_ids.update(
                    int(row["connection_id"])
                    for row in selected_rows
                    if row["connection_id"] is not None
                )
            if include_all_connections or not selected_records:
                connection_ids.update(
                    int(row["id"])
                    for row in connection.execute(
                        "SELECT id FROM provider_connections"
                    ).fetchall()
                )
            if not connection_ids:
                return ProviderFreshnessScope(
                    connections=(), has_unlinked_records=has_unlinked_records
                )
            placeholders = ", ".join("?" for _ in connection_ids)
            rows = connection.execute(
                f"""
                SELECT connection.id, connection.provider, connection.status,
                       connection.last_successful_at, account.source_updated_at
                FROM provider_connections AS connection
                LEFT JOIN financial_accounts AS account ON account.connection_id = connection.id
                WHERE connection.id IN ({placeholders})
                ORDER BY connection.id ASC, account.id ASC
                """,
                tuple(sorted(connection_ids)),
            ).fetchall()

        grouped: dict[int, dict[str, object]] = {}
        for row in rows:
            connection_id = int(row["id"])
            current = grouped.setdefault(
                connection_id,
                {
                    "provider": row["provider"],
                    "status": row["status"],
                    "last_successful_at": row["last_successful_at"],
                    "source_updated_at": [],
                },
            )
            current["source_updated_at"].append(row["source_updated_at"])
        return ProviderFreshnessScope(
            connections=tuple(
                ProviderConnectionFreshness(
                    connection_id=connection_id,
                    provider=values["provider"],
                    status=values["status"],
                    last_successful_at=values["last_successful_at"],
                    source_updated_at=tuple(values["source_updated_at"]),
                )
                for connection_id, values in grouped.items()
            ),
            has_unlinked_records=has_unlinked_records,
        )

    def list_connection_freshness(
        self,
        *,
        account_ids: Optional[Sequence[int]] = None,
        transaction_ids: Optional[Sequence[int]] = None,
    ) -> list[ProviderConnectionFreshness]:
        """Return provider freshness records for the requested record scope."""
        return list(
            self.get_freshness_scope(
                account_ids=account_ids,
                transaction_ids=transaction_ids,
            ).connections
        )

    @staticmethod
    def _account_from_row(row: sqlite3.Row) -> AccountRecord:
        values = dict(row)
        values["is_active"] = bool(values["is_active"])
        return AccountRecord(**values)

    @staticmethod
    def _transaction_from_row(row: sqlite3.Row) -> TransactionRecord:
        return TransactionRecord(**dict(row))
