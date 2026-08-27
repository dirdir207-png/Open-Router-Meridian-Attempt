from meridian.providers.crew import CrewReadAdapter


class FixtureCrewClient:
    def execute(self, operation_name, query, variables=None, *, is_mutation=False):
        assert is_mutation is False
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
                                    "type": "pending",
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
    snapshot = CrewReadAdapter(FixtureCrewClient()).fetch_snapshot()

    assert snapshot.accounts[0].balance == 123.45
    assert snapshot.transactions[0].amount == -4.59
    assert snapshot.transactions[0].status == "pending"
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
                }
            return result

    snapshot = CrewReadAdapter(TransferCrewClient()).fetch_snapshot()
    transaction = snapshot.transactions[0]

    assert transaction.relation_hint == "crew-transfer:transfer-7"
    assert transaction.category is None
