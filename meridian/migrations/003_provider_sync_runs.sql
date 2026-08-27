CREATE TABLE provider_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'partial', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    accounts_synced INTEGER NOT NULL DEFAULT 0,
    transactions_synced INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (connection_id) REFERENCES provider_connections(id)
);

CREATE INDEX idx_provider_sync_runs_connection_started
    ON provider_sync_runs(connection_id, started_at DESC);
