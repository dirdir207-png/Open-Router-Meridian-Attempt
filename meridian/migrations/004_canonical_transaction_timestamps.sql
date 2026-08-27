ALTER TABLE financial_transactions
ADD COLUMN occurred_at_valid INTEGER NOT NULL DEFAULT 1
CHECK (occurred_at_valid IN (0, 1));
