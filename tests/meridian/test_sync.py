import pytest

from meridian.providers.base import (
    NormalizedAccount,
    NormalizedTransaction,
    ProviderSnapshot,
)
from meridian.providers.crew import CrewReadAdapter
from meridian.repository import FinancialRepository
from meridian.sync import sync_provider


class SnapshotAdapter:
    provider_name = "crew"
    connection_external_id = "crew-household"
    connection_name = "Crew"

    def __init__(self, snapshot):
        self.snapshot = snapshot

    def fetch_snapshot(self):
        return self.snapshot


@pytest.fixture
def repository(tmp_path):
    return FinancialRepository(str(tmp_path / "financial.db"))


def complete_snapshot():
    return ProviderSnapshot(
        connection_external_id="crew-household",
        connection_name="Crew",
        accounts=(
            NormalizedAccount(
                external_id="crew-checking",
                name="Checking",
                account_type="checking",
                balance=250.0,
                source_updated_at="2026-08-26T10:00:00Z",
            ),
        ),
        transactions=(
            NormalizedTransaction(
                external_id="crew-transaction-1",
                account_external_id="crew-checking",
                amount=-12.5,
                occurred_at="2026-08-26T09:00:00Z",
                description="Coffee",
                status="posted",
                source_updated_at="2026-08-26T10:00:00Z",
            ),
        ),
    )


def test_syncing_an_identical_snapshot_is_idempotent(repository):
    adapter = SnapshotAdapter(complete_snapshot())

    first = sync_provider(adapter, repository)
    second = sync_provider(adapter, repository)

    assert first.status == "complete"
    assert second.status == "complete"
    assert len(repository.list_accounts()) == 1
    transactions, _ = repository.list_transactions()
    assert len(transactions) == 1
    with repository._connect() as connection:
        runs = connection.execute("SELECT status FROM provider_sync_runs ORDER BY id").fetchall()
    assert [run["status"] for run in runs] == ["complete", "complete"]


def test_sync_links_accounts_and_runs_to_the_same_provider_connection(repository):
    sync_provider(SnapshotAdapter(complete_snapshot()), repository)

    with repository._connect() as connection:
        account = connection.execute("SELECT connection_id FROM financial_accounts").fetchone()
        run = connection.execute("SELECT connection_id FROM provider_sync_runs").fetchone()
        provider_connection = connection.execute("SELECT id FROM provider_connections").fetchone()

    assert account["connection_id"] == run["connection_id"] == provider_connection["id"]


def test_partial_sync_keeps_prior_transactions_and_last_successful_freshness(repository):
    sync_provider(SnapshotAdapter(complete_snapshot()), repository)
    with repository._connect() as connection:
        prior_success = connection.execute(
            "SELECT last_successful_at FROM provider_connections "
            "WHERE provider = ? AND external_id = ?",
            ("crew", "crew-household"),
        ).fetchone()["last_successful_at"]

    partial_snapshot = ProviderSnapshot(
        connection_external_id="crew-household",
        connection_name="Crew",
        accounts=complete_snapshot().accounts,
        transactions=(),
        is_complete=False,
        errors=("transaction page failed",),
    )
    report = sync_provider(SnapshotAdapter(partial_snapshot), repository)

    transactions, _ = repository.list_transactions()
    assert report.status == "partial"
    assert [transaction.external_id for transaction in transactions] == ["crew-transaction-1"]
    with repository._connect() as connection:
        connection_row = connection.execute(
            "SELECT last_successful_at FROM provider_connections "
            "WHERE provider = ? AND external_id = ?",
            ("crew", "crew-household"),
        ).fetchone()
    assert connection_row["last_successful_at"] == prior_success


def test_failed_transaction_write_records_a_partial_sync_and_keeps_freshness(
    repository, monkeypatch
):
    sync_provider(SnapshotAdapter(complete_snapshot()), repository)
    with repository._connect() as connection:
        prior_success = connection.execute(
            "SELECT last_successful_at FROM provider_connections "
            "WHERE provider = ? AND external_id = ?",
            ("crew", "crew-household"),
        ).fetchone()["last_successful_at"]

    def reject_transaction(**kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(repository, "upsert_transaction", reject_transaction)
    report = sync_provider(SnapshotAdapter(complete_snapshot()), repository)

    assert report.status == "partial"
    assert report.errors == 1
    transactions, _ = repository.list_transactions()
    assert [transaction.external_id for transaction in transactions] == ["crew-transaction-1"]
    with repository._connect() as connection:
        connection_row = connection.execute(
            "SELECT last_successful_at FROM provider_connections "
            "WHERE provider = ? AND external_id = ?",
            ("crew", "crew-household"),
        ).fetchone()
    assert connection_row["last_successful_at"] == prior_success


def test_fetch_failure_records_a_failed_run_without_advancing_freshness(repository):
    class FailingAdapter:
        provider_name = "crew"
        connection_external_id = "crew-household"
        connection_name = "Crew"

        @staticmethod
        def fetch_snapshot():
            raise RuntimeError("unreachable")

    report = sync_provider(FailingAdapter(), repository)

    assert report.status == "failed"
    assert report.errors == 1
    with repository._connect() as connection:
        run = connection.execute("SELECT status FROM provider_sync_runs").fetchone()
        provider_connection = connection.execute(
            "SELECT last_successful_at FROM provider_connections"
        ).fetchone()
    assert run["status"] == "failed"
    assert provider_connection["last_successful_at"] is None


def test_two_page_adapter_failure_retains_first_page_and_reports_partial(repository):
    class TwoPageClient:
        def __init__(self):
            self.calls = []

        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            self.calls.append((operation_name, variables))
            if operation_name == "CurrentUser":
                return {
                    "currentUser": {
                        "accounts": [
                            {
                                "id": "account-main",
                                "displayName": "Household",
                                "subaccounts": [
                                    {
                                        "id": "checking",
                                        "displayName": "Checking",
                                        "overallBalance": 5000,
                                        "isPrimary": True,
                                    }
                                ],
                            }
                        ]
                    }
                }
            if variables["cursor"] is None:
                return {
                    "account": {
                        "cashTransactions": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "first-page-transaction",
                                        "amount": -100,
                                        "description": "Lunch",
                                        "occurredAt": "2026-08-26T09:00:00Z",
                                        "status": "posted",
                                        "subaccount": {"id": "checking"},
                                    }
                                }
                            ],
                            "pageInfo": {"hasNextPage": True, "endCursor": "next-page"},
                        }
                    }
                }
            raise RuntimeError("page two unavailable")

    client = TwoPageClient()
    report = sync_provider(CrewReadAdapter(client, observed_at="2026-08-26T10:00:00Z"), repository)

    transactions, _ = repository.list_transactions()
    assert report.status == "partial"
    assert report.errors == 1
    assert [transaction.external_id for transaction in transactions] == ["first-page-transaction"]
    assert client.calls[-1][1]["cursor"] == "next-page"


def test_crew_status_revisions_with_same_occurrence_update_but_stale_arrivals_do_not(repository):
    class RevisionCrewClient:
        status = "pending"

        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            if operation_name == "CurrentUser":
                return {
                    "currentUser": {
                        "accounts": [
                            {
                                "id": "account-main",
                                "displayName": "Household",
                                "subaccounts": [
                                    {
                                        "id": "checking",
                                        "displayName": "Checking",
                                        "overallBalance": 5000,
                                        "isPrimary": True,
                                    }
                                ],
                            }
                        ]
                    }
                }
            return {
                "account": {
                    "cashTransactions": {
                        "edges": [
                            {
                                "node": {
                                    "id": "same-occurrence",
                                    "amount": -100,
                                    "description": "Lunch",
                                    "occurredAt": "2026-08-26T09:00:00Z",
                                    "status": self.status,
                                    "subaccount": {"id": "checking"},
                                }
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }

    client = RevisionCrewClient()
    sync_provider(SnapshotAdapter(CrewReadAdapter(client).fetch_snapshot()), repository)
    client.status = "posted"
    sync_provider(SnapshotAdapter(CrewReadAdapter(client).fetch_snapshot()), repository)
    client.status = "pending"
    sync_provider(SnapshotAdapter(CrewReadAdapter(client).fetch_snapshot()), repository)

    transactions, _ = repository.list_transactions()
    assert transactions[0].status == "posted"
    assert transactions[0].source_updated_at.endswith("#30")
