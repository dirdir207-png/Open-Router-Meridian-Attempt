import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Event

import pytest

from meridian import db as db_module
from meridian.db import run_migrations
from meridian.repository import FinancialRepository


def _create_pre_timestamp_migration_database(
    db_path: Path, migrations_dir: Path, monkeypatch
) -> None:
    legacy_migrations = migrations_dir / "legacy-migrations"
    legacy_migrations.mkdir()
    for source in sorted(db_module.MIGRATIONS_DIR.glob("00[1-3]_*.sql")):
        shutil.copy(source, legacy_migrations / source.name)
    with monkeypatch.context() as migration_patch:
        migration_patch.setattr(db_module, "MIGRATIONS_DIR", legacy_migrations)
        run_migrations(str(db_path))


def _seed_legacy_transaction(
    db_path: Path,
    *,
    occurred_at: str,
    source_updated_at: str = "2026-08-27T08:00:00Z#legacy",
) -> int:
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
                "legacy-account",
                "Legacy account",
                "checking",
                100.0,
                "USD",
                "2026-08-27T08:00:00Z",
                "2026-08-27T08:00:00Z",
                "2026-08-27T08:00:00Z",
            ),
        ).lastrowid
        return connection.execute(
            """
            INSERT INTO financial_transactions (
                account_id, provider, external_id, amount, currency,
                occurred_at, description, status, source_updated_at, synced_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                "crew",
                "legacy-transaction",
                -1.0,
                "USD",
                occurred_at,
                "Legacy",
                "posted",
                source_updated_at,
                "2026-08-27T08:00:00Z",
                "2026-08-27T08:00:00Z",
                "2026-08-27T08:00:00Z",
            ),
        ).lastrowid


def test_migrations_are_idempotent_and_preserve_legacy_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE history (date TEXT PRIMARY KEY, balance REAL)")
        connection.execute(
            "INSERT INTO history (date, balance) VALUES (?, ?)",
            ("2026-08-26", 1234.56),
        )

    assert run_migrations(str(db_path)) == [
        "001_financial_graph.sql",
        "002_financial_integrity.sql",
        "003_provider_sync_runs.sql",
        "004_canonical_transaction_timestamps.sql",
    ]
    assert run_migrations(str(db_path)) == []

    with sqlite3.connect(db_path) as connection:
        migrations = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        legacy_row = connection.execute("SELECT date, balance FROM history").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert migrations == [
        ("001", "001_financial_graph.sql"),
        ("002", "002_financial_integrity.sql"),
        ("003", "003_provider_sync_runs.sql"),
        ("004", "004_canonical_transaction_timestamps.sql"),
    ]
    assert legacy_row == ("2026-08-26", 1234.56)
    assert {
        "provider_connections",
        "financial_accounts",
        "financial_transactions",
        "transaction_relations",
        "provider_sync_runs",
    } <= tables


def test_financial_graph_schema_tracks_relation_freshness_and_provider_ownership(
    tmp_path,
):
    db_path = tmp_path / "financial.db"
    run_migrations(str(db_path))

    with sqlite3.connect(db_path) as connection:
        relation_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(transaction_relations)")
        }
        connection.execute(
            """
            INSERT INTO financial_accounts (
                provider, external_id, name, account_type, balance, currency,
                synced_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "crew",
                "account-1",
                "Everyday",
                "checking",
                1.0,
                "USD",
                "2026-08-26T10:00:00Z",
                "2026-08-26T10:00:00Z",
                "2026-08-26T10:00:00Z",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError, match="provider must match"):
            connection.execute(
                """
                INSERT INTO financial_transactions (
                    account_id, provider, external_id, amount, currency,
                    occurred_at, description, status, synced_at, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "simplefin",
                    "transaction-1",
                    -1.0,
                    "USD",
                    "2026-08-26T10:00:00Z",
                    "Lunch",
                    "posted",
                    "2026-08-26T10:00:00Z",
                    "2026-08-26T10:00:00Z",
                    "2026-08-26T10:00:00Z",
                ),
            )

    assert {"source_updated_at", "synced_at"} <= relation_columns


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


def test_missing_applied_migration_file_is_rejected(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    first_path = migrations_dir / "001_first.sql"
    first_path.write_text(
        "CREATE TABLE first_table (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    (migrations_dir / "002_second.sql").write_text(
        "CREATE TABLE second_table (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migrations_dir)
    db_path = tmp_path / "missing-file.db"

    run_migrations(str(db_path))
    first_path.unlink()

    with pytest.raises(RuntimeError, match="missing from migrations directory"):
        run_migrations(str(db_path))


def test_retroactive_migration_insertion_is_rejected(tmp_path, monkeypatch):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "002_second.sql").write_text(
        "CREATE TABLE second_table (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "MIGRATIONS_DIR", migrations_dir)
    db_path = tmp_path / "retroactive.db"

    assert run_migrations(str(db_path)) == ["002_second.sql"]
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE first_table (id INTEGER PRIMARY KEY);\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="append-only"):
        run_migrations(str(db_path))


def test_timestamp_migration_is_recorded_once_and_preserves_provenance(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "timestamp-upgrade.db"
    _create_pre_timestamp_migration_database(db_path, tmp_path, monkeypatch)
    transaction_id = _seed_legacy_transaction(
        db_path,
        occurred_at="2026-08-27T04:00:00.11-04:00",
    )

    assert run_migrations(str(db_path)) == ["004_canonical_transaction_timestamps.sql"]
    assert run_migrations(str(db_path)) == []

    with sqlite3.connect(db_path) as connection:
        migration = connection.execute(
            "SELECT version, name FROM schema_migrations WHERE version = '004'"
        ).fetchone()
        transaction = connection.execute(
            """
            SELECT occurred_at, occurred_at_valid, source_updated_at
            FROM financial_transactions WHERE id = ?
            """,
            (transaction_id,),
        ).fetchone()

    assert migration == ("004", "004_canonical_transaction_timestamps.sql")
    assert transaction == (
        "2026-08-27T08:00:00.110000Z",
        1,
        "2026-08-27T08:00:00Z#legacy",
    )


def test_timestamp_migration_failure_rolls_back_and_resumes(tmp_path, monkeypatch):
    db_path = tmp_path / "timestamp-resume.db"
    _create_pre_timestamp_migration_database(db_path, tmp_path, monkeypatch)
    transaction_id = _seed_legacy_transaction(
        db_path,
        occurred_at="2026-08-27T04:00:00.1-04:00",
    )
    migration_name = "004_canonical_transaction_timestamps.sql"
    real_hook = db_module._MIGRATION_HOOKS[migration_name]

    def fail_after_conversion(connection):
        real_hook(connection)
        raise RuntimeError("interrupted timestamp migration")

    monkeypatch.setitem(
        db_module._MIGRATION_HOOKS, migration_name, fail_after_conversion
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        run_migrations(str(db_path))

    with sqlite3.connect(db_path) as connection:
        migration = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = '004'"
        ).fetchone()
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(financial_transactions)")
        }
        occurred_at = connection.execute(
            "SELECT occurred_at FROM financial_transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()[0]

    assert migration is None
    assert "occurred_at_valid" not in columns
    assert occurred_at == "2026-08-27T04:00:00.1-04:00"

    monkeypatch.setitem(db_module._MIGRATION_HOOKS, migration_name, real_hook)
    assert run_migrations(str(db_path)) == [migration_name]


def test_timestamp_migration_locks_before_read_and_does_not_lose_concurrent_write(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "timestamp-concurrency.db"
    _create_pre_timestamp_migration_database(db_path, tmp_path, monkeypatch)
    _seed_legacy_transaction(
        db_path,
        occurred_at="2026-08-27T08:00:00Z",
        source_updated_at="2026-08-27T08:00:00Z",
    )
    repository = object.__new__(FinancialRepository)
    repository._db_path = str(db_path)
    migration_name = "004_canonical_transaction_timestamps.sql"
    real_hook = db_module._MIGRATION_HOOKS[migration_name]
    migration_read = Event()
    allow_migration = Event()
    writer_started = Event()

    def pause_after_read(connection):
        assert (
            connection.execute(
                "SELECT occurred_at FROM financial_transactions"
            ).fetchone()[0]
            == "2026-08-27T08:00:00Z"
        )
        migration_read.set()
        assert allow_migration.wait(timeout=5)
        real_hook(connection)

    monkeypatch.setitem(db_module._MIGRATION_HOOKS, migration_name, pause_after_read)

    def write_newer_value():
        writer_started.set()
        account_id = repository.list_accounts()[0].id
        return repository.upsert_transaction(
            provider="crew",
            external_id="legacy-transaction",
            account_id=account_id,
            amount=-2.0,
            occurred_at="2026-08-27T09:00:00Z",
            description="Newer",
            status="posted",
            source_updated_at="2026-08-27T09:00:00Z",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        migrating = executor.submit(run_migrations, str(db_path))
        assert migration_read.wait(timeout=5)
        writing = executor.submit(write_newer_value)
        assert writer_started.wait(timeout=5)
        with pytest.raises(TimeoutError):
            writing.result(timeout=0.1)
        allow_migration.set()
        assert migrating.result(timeout=5) == [migration_name]
        written = writing.result(timeout=5)

    assert written.occurred_at == "2026-08-27T09:00:00.000000Z"
    assert written.description == "Newer"


def test_invalid_legacy_timestamp_is_quarantined_without_blocking_reads(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "invalid-timestamp.db"
    _create_pre_timestamp_migration_database(db_path, tmp_path, monkeypatch)
    transaction_id = _seed_legacy_transaction(
        db_path,
        occurred_at="legacy-not-a-time",
    )

    repository = FinancialRepository(str(db_path))

    assert repository.list_transactions() == ([], None)
    assert repository.get_transaction(transaction_id) is None
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT occurred_at, occurred_at_valid, source_updated_at
            FROM financial_transactions WHERE id = ?
            """,
            (transaction_id,),
        ).fetchone()
        migration = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = '004'"
        ).fetchone()

    assert row == ("legacy-not-a-time", 0, "2026-08-27T08:00:00Z#legacy")
    assert migration == (1,)


@pytest.mark.parametrize(
    "legacy_timestamp",
    [
        "2026-08-27t08:00:00.1234567+00:00",
        "2026-08-27X08:00:00.1234567+00:00",
    ],
)
def test_timestamp_migration_quarantines_unsupported_high_precision_separators(
    tmp_path, monkeypatch, legacy_timestamp
):
    db_path = tmp_path / "unsupported-precision-timestamp.db"
    _create_pre_timestamp_migration_database(db_path, tmp_path, monkeypatch)
    transaction_id = _seed_legacy_transaction(
        db_path,
        occurred_at=legacy_timestamp,
        source_updated_at="2026-08-27T08:00:00Z#unsupported-precision",
    )

    assert run_migrations(str(db_path)) == ["004_canonical_transaction_timestamps.sql"]

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT occurred_at, occurred_at_valid, source_updated_at
            FROM financial_transactions WHERE id = ?
            """,
            (transaction_id,),
        ).fetchone()

    assert row == (legacy_timestamp, 0, "2026-08-27T08:00:00Z#unsupported-precision")
