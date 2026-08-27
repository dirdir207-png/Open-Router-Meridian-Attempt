-- 006: Funding rules that project contributions for commitments.
CREATE TABLE IF NOT EXISTS funding_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commitment_id INTEGER NOT NULL REFERENCES commitments(id),
    kind TEXT NOT NULL CHECK (kind IN (
        'fixed_per_paycheck', 'percent_of_paycheck', 'calendar',
        'even_by_due_date', 'priority_waterfall'
    )),
    amount REAL,
    percent REAL,
    cadence TEXT,
    day_of_month INTEGER,
    start_date TEXT NOT NULL,
    horizon_end TEXT,
    min_contribution REAL,
    max_contribution REAL,
    paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
    skip_dates TEXT NOT NULL DEFAULT '[]',
    one_time_override REAL,
    priority INTEGER NOT NULL DEFAULT 3 CHECK (priority >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (amount IS NULL OR amount >= 0),
    CHECK (percent IS NULL OR (percent > 0 AND percent <= 100)),
    CHECK (min_contribution IS NULL OR min_contribution >= 0),
    CHECK (max_contribution IS NULL OR max_contribution >= 0),
    CHECK (one_time_override IS NULL OR one_time_override >= 0)
);

CREATE INDEX IF NOT EXISTS idx_funding_rules_commitment
    ON funding_rules (commitment_id);
