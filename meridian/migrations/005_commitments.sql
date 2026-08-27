-- 005: Unified Commitments (local planning layer over Crew pockets)
CREATE TABLE IF NOT EXISTS commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('bill', 'goal', 'reserve', 'buffer', 'debt')),
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    priority INTEGER NOT NULL DEFAULT 3 CHECK (priority >= 1),
    currency TEXT NOT NULL DEFAULT 'USD',
    target_amount REAL,
    target_date TEXT,
    funded_amount REAL NOT NULL DEFAULT 0 CHECK (funded_amount >= 0),
    amount REAL,
    due_date TEXT,
    recurrence TEXT,
    cadence TEXT,
    minimum_payment REAL,
    buffer_minimum REAL,
    payoff_strategy TEXT,
    backing_account_id INTEGER REFERENCES financial_accounts(id),
    legacy_source TEXT,
    legacy_id TEXT,
    migration_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        target_amount IS NULL OR target_amount >= 0
    ),
    CHECK (
        amount IS NULL OR amount >= 0
    ),
    CHECK (
        minimum_payment IS NULL OR minimum_payment >= 0
    ),
    CHECK (
        buffer_minimum IS NULL OR buffer_minimum >= 0
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_commitments_legacy_identity
    ON commitments (legacy_source, legacy_id)
    WHERE legacy_source IS NOT NULL AND legacy_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS migration_previews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preview_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS migration_review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preview_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    legacy_source TEXT NOT NULL,
    legacy_id TEXT NOT NULL,
    suggested_type TEXT NOT NULL,
    name TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolution TEXT,
    resolved_at TEXT
);
