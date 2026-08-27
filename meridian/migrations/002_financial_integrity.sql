ALTER TABLE transaction_relations ADD COLUMN source_updated_at TEXT;

ALTER TABLE transaction_relations ADD COLUMN synced_at TEXT;

UPDATE transaction_relations
SET synced_at = updated_at
WHERE synced_at IS NULL;

CREATE TRIGGER financial_transactions_provider_matches_account_on_insert
BEFORE INSERT ON financial_transactions
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM financial_accounts
    WHERE id = NEW.account_id AND provider = NEW.provider
)
BEGIN
    SELECT RAISE(ABORT, 'transaction provider must match account provider');
END;

CREATE TRIGGER financial_transactions_provider_matches_account_on_update
BEFORE UPDATE OF account_id, provider ON financial_transactions
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM financial_accounts
    WHERE id = NEW.account_id AND provider = NEW.provider
)
BEGIN
    SELECT RAISE(ABORT, 'transaction provider must match account provider');
END;
