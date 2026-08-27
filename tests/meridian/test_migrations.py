import sqlite3

import pytest

from meridian import db as db_module
from meridian.db import run_migrations


def test_migrations_are_idempotent_and_preserve_legacy_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE history (date TEXT PRIMARY KEY, balance REAL)")
        connection.execute(
            "INSERT INTO history (date, balance) VALUES (?, ?)",
            ("2026-08-26", 1234.56),
        )

    assert run_migrations(str(db_path)) == ["001_financial_graph.sql"]
    assert run_migrations(str(db_path)) == []

    with sqlite3.connect(db_path) as connection:
        migrations = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        legacy_row = connection.execute(
            "SELECT date, balance FROM history"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert migrations == [("001", "001_financial_graph.sql")]
    assert legacy_row == ("2026-08-26", 1234.56)
    assert {
        "provider_connections",
        "financial_accounts",
        "financial_transactions",
        "transaction_relations",
    } <= tables


def test_failed_migration_rolls_back_and_can_resume(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE first_table (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    failing_path = migrations_dir / "002_recovery.sql"
    failing_path.write_text(
        "CREATE TABLE partial_table (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO table_that_does_not_exist (id) VALUES (1);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migrations_dir)
    db_path = tmp_path / "resumable.db"

    with pytest.raises(sqlite3.OperationalError):
        run_migrations(str(db_path))

    with sqlite3.connect(db_path) as connection:
        applied = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        partial_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("partial_table",),
        ).fetchone()

    assert applied == [("001",)]
    assert partial_exists is None

    failing_path.write_text(
        "CREATE TABLE recovered_table (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )

    assert run_migrations(str(db_path)) == ["002_recovery.sql"]
    with sqlite3.connect(db_path) as connection:
        applied = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        recovered_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("recovered_table",),
        ).fetchone()

    assert applied == [("001",), ("002",)]
    assert recovered_exists == (1,)


def test_applied_migration_checksum_drift_is_rejected(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    migration_path = migrations_dir / "001_example.sql"
    migration_path.write_text(
        "CREATE TABLE example (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migrations_dir)
    db_path = tmp_path / "checksum.db"

    run_migrations(str(db_path))
    migration_path.write_text(
        "CREATE TABLE example (id INTEGER PRIMARY KEY, name TEXT);\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="checksum"):
        run_migrations(str(db_path))
