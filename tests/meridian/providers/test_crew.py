from meridian.providers.crew import CrewReadAdapter


class FixtureCrewClient:
    def __init__(self):
        self.queries = []

    def execute(self, operation_name, query, variables=None, *, is_mutation=False):
        assert is_mutation is False
        self.queries.append((operation_name, query, variables))
        if operation_name == "CurrentUser":
            return {
                "currentUser": {
                    "accounts": [
                        {
                            "id": "account-main",
                            "displayName": "Household",
                            "accountNumber": "1111222233334444",
                            "subaccounts": [
                                {
                                    "id": "pocket-checking",
                                    "displayName": "Checking",
                                    "overallBalance": 12345,
                                    "isPrimary": True,
                                    "accountNumber": "4444333322221111",
                                }
                            ],
                        }
                    ]
                }
            }
        if operation_name == "RecentActivity":
            return {
                "account": {
                    "cashTransactions": {
                        "edges": [
                            {
                                "node": {
                                    "id": "transaction-coffee",
                                    "amount": -459,
                                    "description": "Coffee shop",
                                    "title": "Coffee shop",
                                    "occurredAt": "2026-08-26T09:00:00Z",
                                    "type": "debit",
                                    "status": "pending",
                                    "subaccount": {"id": "pocket-checking"},
                                    "bearerToken": "not-a-fixture-secret",
                                }
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        raise AssertionError(operation_name)


def test_adapter_normalizes_cents_and_omits_sensitive_source_fields():
    client = FixtureCrewClient()
    snapshot = CrewReadAdapter(client, observed_at="2026-08-26T10:00:00Z").fetch_snapshot()

    assert snapshot.accounts[0].balance == 123.45
    assert snapshot.transactions[0].amount == -4.59
    assert snapshot.transactions[0].status == "pending"
    assert "status" in client.queries[1][1]
    assert snapshot.accounts[0].source_updated_at == "2026-08-26T10:00:00Z"
    assert snapshot.transactions[0].source_updated_at == "2026-08-26T09:00:00Z#10"
    assert "1111222233334444" not in repr(snapshot)
    assert "4444333322221111" not in repr(snapshot)
    assert "not-a-fixture-secret" not in repr(snapshot)


def test_adapter_marks_owned_transfers_with_a_relation_hint_not_a_category():
    class TransferCrewClient(FixtureCrewClient):
        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            result = super().execute(operation_name, query, variables, is_mutation=is_mutation)
            if operation_name == "RecentActivity":
                result["account"]["cashTransactions"]["edges"][0]["node"]["transfer"] = {
                    "id": "transfer-7",
                    "type": "internal",
                    "accountFrom": {"id": "account-main", "belongsToCurrentUser": True},
                    "accountTo": {"id": "account-spouse", "belongsToCurrentUser": True},
                }
            return result

    snapshot = CrewReadAdapter(TransferCrewClient()).fetch_snapshot()
    transaction = snapshot.transactions[0]

    assert transaction.relation_hint == "crew-transfer:transfer-7"
    assert transaction.category is None


def test_adapter_does_not_hint_transfers_without_proven_owned_endpoints():
    class ExternalTransferClient(FixtureCrewClient):
        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            result = super().execute(operation_name, query, variables, is_mutation=is_mutation)
            if operation_name == "RecentActivity":
                result["account"]["cashTransactions"]["edges"][0]["node"]["transfer"] = {
                    "id": "transfer-external",
                    "accountFrom": {"id": "account-main", "belongsToCurrentUser": True},
                    "accountTo": {"id": "account-external", "belongsToCurrentUser": False},
                }
            return result

    snapshot = CrewReadAdapter(ExternalTransferClient()).fetch_snapshot()

    assert snapshot.transactions[0].relation_hint is None


def test_adapter_normalizes_parent_account_for_missing_subaccount_transactions():
    class ParentTransactionClient(FixtureCrewClient):
        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            result = super().execute(operation_name, query, variables, is_mutation=is_mutation)
            if operation_name == "RecentActivity":
                result["account"]["cashTransactions"]["edges"][0]["node"]["subaccount"] = None
            return result

    snapshot = CrewReadAdapter(ParentTransactionClient()).fetch_snapshot()

    assert {account.external_id for account in snapshot.accounts} >= {"account-main", "pocket-checking"}
    assert snapshot.transactions[0].account_external_id == "account-main"


def test_adapter_does_not_duplicate_parent_balance_without_parent_transactions():
    snapshot = CrewReadAdapter(FixtureCrewClient()).fetch_snapshot()

    assert [account.external_id for account in snapshot.accounts] == ["pocket-checking"]


def test_fallback_parent_is_a_zero_balance_anchor_not_a_duplicate_balance():
    class ParentTransactionClient(FixtureCrewClient):
        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            result = super().execute(operation_name, query, variables, is_mutation=is_mutation)
            if operation_name == "RecentActivity":
                result["account"]["cashTransactions"]["edges"][0]["node"]["subaccount"] = None
            return result

    snapshot = CrewReadAdapter(ParentTransactionClient()).fetch_snapshot()

    assert sum(account.balance for account in snapshot.accounts) == 123.45
    fallback = next(account for account in snapshot.accounts if account.external_id == "account-main")
    assert fallback.account_type == "fallback"
    assert fallback.balance == 0


def test_adapter_marks_a_malformed_transaction_page_partial():
    class NullPageClient(FixtureCrewClient):
        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            result = super().execute(operation_name, query, variables, is_mutation=is_mutation)
            if operation_name == "RecentActivity":
                result["account"] = None
            return result

    snapshot = CrewReadAdapter(NullPageClient()).fetch_snapshot()

    assert snapshot.is_complete is False
    assert snapshot.errors == ("transaction page malformed",)


def test_adapter_marks_a_null_current_user_partial():
    class NullCurrentUserClient(FixtureCrewClient):
        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            if operation_name == "CurrentUser":
                return {"currentUser": None}
            raise AssertionError("transactions should not be fetched")

    snapshot = CrewReadAdapter(NullCurrentUserClient()).fetch_snapshot()

    assert snapshot.is_complete is False
    assert snapshot.errors == ("current user malformed",)


def test_adapter_marks_a_repeated_page_cursor_partial_without_looping():
    class RepeatingCursorClient(FixtureCrewClient):
        def __init__(self):
            super().__init__()
            self.pages = 0

        def execute(self, operation_name, query, variables=None, *, is_mutation=False):
            if operation_name == "RecentActivity" and self.pages >= 2:
                raise AssertionError("adapter requested a repeated cursor again")
            result = super().execute(operation_name, query, variables, is_mutation=is_mutation)
            if operation_name == "RecentActivity":
                self.pages += 1
                result["account"]["cashTransactions"]["pageInfo"] = {
                    "hasNextPage": True,
                    "endCursor": "repeat",
                }
            return result

    client = RepeatingCursorClient()
    snapshot = CrewReadAdapter(client).fetch_snapshot()

    assert snapshot.is_complete is False
    assert snapshot.errors == ("transaction page malformed",)
    assert client.pages == 2
