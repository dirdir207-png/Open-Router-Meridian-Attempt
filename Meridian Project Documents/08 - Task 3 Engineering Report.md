# Task 3 Report: Versioned Migrations and Normalized Financial Read Model

## Status

Recovered the interrupted Task 3 work and audited every Meridian source/test
file. Committed the task-scoped normalized financial read model as `671abc9`
(`feat: add Meridian normalized financial read model`). The
unrelated `Meridian Project Documents.zip` and `tmp/` remain unmodified and
unstaged. Generated `__pycache__` files remain untracked after the environment
declined their removal; they are not staged.

## Implementation

- Added `run_migrations(db_path)` with ordered, versioned SQL discovery,
  SHA-256 checksum drift detection, and one `BEGIN IMMEDIATE` transaction per
  migration. A failed migration and its metadata insert roll back together;
  earlier committed migrations remain available for a later resume.
- Added non-destructive schema migration `001_financial_graph.sql` for
  `provider_connections`, `financial_accounts`, `financial_transactions`, and
  `transaction_relations`, including provider/external-ID uniqueness, foreign
  keys, deterministic-order indexes, freshness fields, and no credential
  columns.
- Added immutable `AccountRecord` and `TransactionRecord` DTOs with
  JSON-safe `to_dict()` output.
- Added `FinancialRepository` parameterized transactional account/transaction
  upserts, provider-neutral account reads, stable transaction reads ordered by
  `occurred_at DESC, id DESC`, account filtering, and opaque cursor pagination.
- Added the `tests/meridian/__init__.py` package marker. This is required for
  the task-specified plain `pytest tests/meridian/...` invocation to import the
  workspace-local `meridian` package under this repository's test layout.

## Files Changed

- `meridian/__init__.py`
- `meridian/db.py`
- `meridian/models.py`
- `meridian/migrations/001_financial_graph.sql`
- `meridian/repository.py`
- `tests/meridian/__init__.py`
- `tests/meridian/test_migrations.py`
- `tests/meridian/test_repository.py`

## TDD Evidence

The interrupted worker left both production and test files untracked. Historical
RED evidence is therefore not recoverable: `git show
28f4fd8f83ad9c73087a6a98a830514ca4ae048b:meridian/db.py` and the corresponding
`tests/meridian/test_migrations.py` both fail because neither path existed at
the base commit. No feature RED result is claimed or reconstructed.

The first live focused run during recovery failed at collection with
`ModuleNotFoundError: No module named 'meridian'`; the cause was the missing
test-package marker, not a production feature failure. After adding that
marker, the exact focused command passed:

```text
$ pytest tests/meridian/test_migrations.py tests/meridian/test_repository.py -q
.......                                                                  [100%]
7 passed in 0.08s
```

## Verification

```text
$ python3 [12 concurrent run_migrations callers, then 12 FinancialRepository initializers]
concurrent migration and repository startup: 12 workers, one migration row, all initializers succeeded

$ pytest tests/meridian -q
.......                                                                  [100%]
7 passed in 0.06s

$ pytest -q
133 passed, 2 skipped in 6.01s

$ ruff check app.py crew tests
All checks passed!

$ ruff check meridian tests/meridian
All checks passed!

$ git diff --check
(no output; exit 0)

$ git diff --no-index --check /dev/null [each untracked Meridian source/test file]
all untracked Meridian file diffs are whitespace-clean
```

The existing migration tests cover idempotency, legacy-row preservation,
checksum drift rejection, rollback of a failed migration, and resumption. The
repository tests cover provider/external-ID uniqueness, source/sync freshness,
immutable JSON-safe DTOs, account filtering, stable same-timestamp ordering,
and cursor pagination. An additional recovery probe verified that a foreign-key
failure leaves the previous repository write intact and malformed cursors raise
`ValueError("Invalid transaction cursor")`.

## Self-Review

- Confirmed bootstrap and every migration acquisition use `BEGIN IMMEDIATE`,
  so concurrent starters serialize migration inspection/application.
- Confirmed each migration's SQL statements and `schema_migrations` insert are
  one transaction; interruption cannot leave a partial migration table behind.
- Confirmed schema versions and checksums are immutable once applied, while
  legacy tables and rows are never dropped or rewritten.
- Confirmed repository SQL is parameterized, writes are transaction-scoped,
  ordering is deterministic, cursors use the `(occurred_at, id)` sort key, and
  account filtering is incorporated into the same query.
- Confirmed no Flask code, provider calls, credentials, or secret-like fixture
  values appear in this module or its tests.

## Concerns

- Task 3 intentionally supplies only migrations and a normalized read/write
  repository. Provider adapters, connection synchronization, and Flask/API
  integration belong to later planned tasks.
- The schema has no down migrations by design: forward-only migrations preserve
  legacy data and recover by retrying the failed pending version after repair.

---

## Fix Round 1 — Freshness, Append-Only History, and Provenance Integrity

### Findings Addressed

1. Account and transaction upserts now use source evidence as the business-data
   authority. A strictly newer `source_updated_at` replaces normalized fields;
   missing or older source evidence cannot replace a known source-backed record.
   `synced_at` is retained monotonically, so an older arrival cannot move it
   backward.
2. Migration startup now validates the complete applied history before applying
   anything: every applied version must still have the same file name and
   checksum, and any newly discovered version at or below the applied high-water
   mark is rejected as retroactive.
3. Added forward-only migration `002_financial_integrity.sql`, rather than
   rewriting applied `001`. It adds relation freshness fields, backfills relation
   sync timestamps from preserved local update timestamps, and installs insert/
   update triggers that require transaction and account providers to match.
4. Repository transaction writes perform the same provider/account check before
   the upsert, including a conflicting update that attempts account reassignment.

### Files Changed

- `meridian/db.py`
- `meridian/repository.py`
- `meridian/migrations/002_financial_integrity.sql`
- `tests/meridian/test_migrations.py`
- `tests/meridian/test_repository.py`

### Named Regression Coverage

- `test_account_upsert_preserves_newer_source_backed_data`
  - Proves `NULL` and older source evidence keep the known business and source
    fields, while a newer source timestamp replaces them and stale `synced_at`
    cannot move backward.
- `test_transaction_upsert_preserves_newer_source_backed_data`
  - Covers the same `NULL`/older/newer policy for transaction amount/status/
    description and timestamps.
- `test_transaction_upsert_rejects_mismatched_account_provider`
  - Rejects both a mismatched insert and a conflict-update reassignment while
    preserving the original transaction.
- `test_financial_graph_schema_tracks_relation_freshness_and_provider_ownership`
  - Verifies relation freshness columns and direct-SQL provider mismatch rejection
    through the database trigger.
- `test_missing_applied_migration_file_is_rejected`
  - Rejects a database whose applied migration file was removed.
- `test_retroactive_migration_insertion_is_rejected`
  - Rejects adding `001` after `002` has already been applied.

### RED Evidence

```text
$ pytest tests/meridian/test_migrations.py -k 'financial_graph_schema_tracks or missing_applied or retroactive' -q
FFF                                                                      [100%]
3 failed, 3 deselected in 0.08s

$ pytest tests/meridian/test_repository.py -k 'preserves_newer_source_backed_data or rejects_mismatched' -q
FFF                                                                      [100%]
3 failed, 4 deselected in 0.08s
```

The migration failures demonstrated missing trigger/freshness schema support,
silently accepted deletion of an applied file, and retroactive version
application. The repository failures demonstrated a `NULL` source timestamp
overwriting known account/transaction data and a mismatched transaction insert
being accepted.

### GREEN Evidence

```text
$ pytest tests/meridian/test_migrations.py -k 'financial_graph_schema_tracks or missing_applied or retroactive' -q
...                                                                      [100%]
3 passed, 3 deselected in 0.04s

$ pytest tests/meridian/test_repository.py -k 'preserves_newer_source_backed_data or rejects_mismatched' -q
...                                                                      [100%]
3 passed, 4 deselected in 0.07s
```

### Final Verification

```text
$ pytest tests/meridian -q
.............                                                            [100%]
13 passed in 0.11s

$ pytest -q
139 passed, 2 skipped in 5.85s

$ ruff check app.py crew tests
All checks passed!

$ ruff check meridian tests/meridian
All checks passed!

$ python3 [12 concurrent run_migrations callers]
concurrent migration startup: 12 workers, two migration rows, all succeeded

$ git diff --check
(no output; exit 0)

$ git diff --no-index --check /dev/null meridian/migrations/002_financial_integrity.sql
new migration diff is whitespace-clean
```

### Commit

`1cc5207 fix: harden Meridian migration integrity`

### Fix-Round Self-Review

- Confirmed source-backed account/transaction fields change only when the
  incoming source timestamp is strictly newer, while source-less records can
  still be populated before any source timestamp is known.
- Confirmed `synced_at` comparisons prevent timestamp regression independently
  of source evidence, and the test suite covers a stale sync timestamp.
- Confirmed preflight validates every persisted migration, including missing
  files, changed identity/checksum, and the append-only high-water rule before
  any pending SQL runs. Existing rollback/resume tests remain green.
- Confirmed `002` is additive and preserves relation rows while backfilling the
  new sync field; no legacy table or row is dropped.
- Confirmed both repository validation and SQLite triggers reject cross-provider
  transaction ownership, including conflict-update reassignment.
- Confirmed no provider calls, Flask code, credentials, or secret-like test
  values were introduced.

### Remaining Concerns

- Timestamp comparisons retain the existing lexical ISO-8601 contract. Strict
  cursor decoding and canonical UTC validation are intentionally deferred as
  directed; adapters should supply normalized UTC timestamps.
- `transaction_relations` has no repository writer in Task 3. Its new freshness
  columns are available and existing rows receive `synced_at` from `updated_at`;
  a later relation writer must populate both source and sync timestamps.
