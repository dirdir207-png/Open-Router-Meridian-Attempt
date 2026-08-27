"""Versioned SQLite migrations for Meridian."""

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Callable, Iterator

from .timestamps import canonical_occurred_at

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_NAME = re.compile(r"^(?P<version>\d{3})_[a-z0-9_]+\.sql$")
_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _canonicalize_transaction_timestamps(connection: sqlite3.Connection) -> None:
    """Convert valid legacy keys and quarantine invalid keys in place."""
    rows = connection.execute(
        "SELECT id, occurred_at FROM financial_transactions ORDER BY id"
    ).fetchall()
    for transaction_id, occurred_at in rows:
        try:
            canonical = canonical_occurred_at(occurred_at)
        except ValueError:
            connection.execute(
                """
                UPDATE financial_transactions
                SET occurred_at_valid = 0
                WHERE id = ?
                """,
                (transaction_id,),
            )
            continue
        connection.execute(
            """
            UPDATE financial_transactions
            SET occurred_at = ?, occurred_at_valid = 1
            WHERE id = ?
            """,
            (canonical, transaction_id),
        )


_MIGRATION_HOOKS: dict[str, Callable[[sqlite3.Connection], None]] = {
    "004_canonical_transaction_timestamps.sql": _canonicalize_transaction_timestamps,
}


def _migration_files() -> list[tuple[str, Path]]:
    migrations: list[tuple[str, Path]] = []
    seen_versions: set[str] = set()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda item: item.name):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise RuntimeError(f"Invalid migration filename: {path.name}")
        version = match.group("version")
        if version in seen_versions:
            raise RuntimeError(f"Duplicate migration version: {version}")
        seen_versions.add(version)
        migrations.append((version, path))
    return migrations


def _statements(script: str) -> Iterator[str]:
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                yield statement
            pending = ""
    if pending.strip():
        raise RuntimeError("Migration contains an incomplete SQL statement")


def _checksum(script: str) -> str:
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


def _validate_migration_history(
    connection: sqlite3.Connection, migrations: list[tuple[str, Path]]
) -> set[str]:
    migration_by_version = {version: path for version, path in migrations}
    applied_rows = connection.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied_versions = {row[0] for row in applied_rows}

    for version, name, checksum in applied_rows:
        path = migration_by_version.get(version)
        if path is None:
            raise RuntimeError(
                f"Applied migration {version} is missing from migrations directory"
            )
        if name != path.name or checksum != _checksum(path.read_text(encoding="utf-8")):
            raise RuntimeError(
                f"Applied migration {version} has a name or checksum mismatch"
            )

    if applied_versions:
        high_water_mark = max(applied_versions)
        retroactive_versions = [
            version
            for version, _ in migrations
            if version not in applied_versions and version <= high_water_mark
        ]
        if retroactive_versions:
            raise RuntimeError(
                "Migration history is append-only; pending migration versions at "
                f"or below applied high-water mark {high_water_mark}: "
                f"{', '.join(retroactive_versions)}"
            )

    return applied_versions


def run_migrations(db_path: str) -> list[str]:
    """Apply pending migrations in filename order and return applied names.

    Each migration and its metadata row commit together. A failed migration is
    fully rolled back, while earlier successful versions remain available for a
    later retry.
    """

    migrations = _migration_files()
    applied_names: list[str] = []
    connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_MIGRATION_TABLE_SQL)
        connection.commit()

        try:
            connection.execute("BEGIN IMMEDIATE")
            _validate_migration_history(connection, migrations)
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise

        for version, path in migrations:
            script = path.read_text(encoding="utf-8")
            checksum = _checksum(script)
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT name, checksum FROM schema_migrations WHERE version = ?",
                    (version,),
                ).fetchone()
                if existing is not None:
                    if existing != (path.name, checksum):
                        raise RuntimeError(
                            f"Applied migration {version} has a name or checksum mismatch"
                        )
                    connection.commit()
                    continue

                for statement in _statements(script):
                    connection.execute(statement)
                hook = _MIGRATION_HOOKS.get(path.name)
                if hook is not None:
                    hook(connection)
                connection.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) "
                    "VALUES (?, ?, ?)",
                    (version, path.name, checksum),
                )
                connection.commit()
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            applied_names.append(path.name)
    finally:
        connection.close()
    return applied_names
