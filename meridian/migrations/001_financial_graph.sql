CREATE TABLE provider_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    last_attempted_at TEXT,
    last_successful_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, external_id)
);

CREATE TABLE financial_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    balance REAL NOT NULL,
    available_balance REAL,
    currency TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    source_updated_at TEXT,
    synced_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (connection_id) REFERENCES provider_connections(id),
    UNIQUE (provider, external_id)
);

CREATE INDEX idx_financial_accounts_connection
    ON financial_accounts(connection_id);

CREATE TABLE financial_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    posted_at TEXT,
    description TEXT NOT NULL,
    merchant TEXT,
    status TEXT NOT NULL,
    raw_description TEXT,
    source_updated_at TEXT,
    synced_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES financial_accounts(id),
    UNIQUE (provider, external_id)
);

CREATE INDEX idx_financial_transactions_account_order
    ON financial_transactions(account_id, occurred_at DESC, id DESC);

CREATE INDEX idx_financial_transactions_order
    ON financial_transactions(occurred_at DESC, id DESC);

CREATE TABLE transaction_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_transaction_id INTEGER NOT NULL,
    related_transaction_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_transaction_id) REFERENCES financial_transactions(id),
    FOREIGN KEY (related_transaction_id) REFERENCES financial_transactions(id),
    CHECK (source_transaction_id <> related_transaction_id),
    UNIQUE (provider, external_id)
);

CREATE INDEX idx_transaction_relations_source
    ON transaction_relations(source_transaction_id);

CREATE INDEX idx_transaction_relations_related
    ON transaction_relations(related_transaction_id);
