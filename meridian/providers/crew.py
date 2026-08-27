"""Read-only Crew adapter that emits credential-free normalized records."""

from typing import Any, Dict, Iterable, Optional

from .base import NormalizedAccount, NormalizedTransaction, ProviderSnapshot

_CURRENT_USER_QUERY = """
query CurrentUser {
  currentUser {
    accounts {
      id
      displayName
      subaccounts {
        id
        displayName
        name
        overallBalance
        isPrimary
      }
    }
  }
}
"""

_RECENT_ACTIVITY_QUERY = """
query RecentActivity($accountId: ID!, $cursor: String, $pageSize: Int = 100) {
  account: node(id: $accountId) {
    ... on Account {
      cashTransactions(first: $pageSize, after: $cursor) {
        edges {
          node {
            id
            amount
            description
            title
            occurredAt
            type
            memo
            externalMemo
            matchingName
            subaccount { id }
            transfer { id type }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


class CrewReadAdapter:
    """Translate Crew reads without exposing source payloads or credentials."""

    provider_name = "crew"

    def __init__(self, client):
        self._client = client

    def fetch_snapshot(self) -> ProviderSnapshot:
        user_data = self._client.execute("CurrentUser", _CURRENT_USER_QUERY)
        accounts_data = (user_data.get("currentUser") or {}).get("accounts") or []
        accounts = []
        owned_subaccount_ids = set()
        source_accounts = []

        for source_account in accounts_data:
            account_id = source_account.get("id")
            if not isinstance(account_id, str) or not account_id:
                continue
            source_accounts.append(source_account)
            for subaccount in source_account.get("subaccounts") or []:
                normalized = self._normalize_account(subaccount)
                if normalized is not None:
                    accounts.append(normalized)
                    owned_subaccount_ids.add(normalized.external_id)

        transactions, errors = self._fetch_transactions(source_accounts, owned_subaccount_ids)
        return ProviderSnapshot(
            connection_external_id="current-user",
            connection_name="Crew",
            accounts=tuple(accounts),
            transactions=tuple(transactions),
            is_complete=not errors,
            errors=tuple(errors),
        )

    @staticmethod
    def _normalize_account(source: Dict[str, Any]) -> Optional[NormalizedAccount]:
        external_id = source.get("id")
        if not isinstance(external_id, str) or not external_id:
            return None
        name = source.get("displayName") or source.get("name") or "Crew account"
        is_primary = bool(source.get("isPrimary"))
        return NormalizedAccount(
            external_id=external_id,
            name=str(name),
            account_type="checking" if is_primary or str(name).lower() == "checking" else "pocket",
            balance=float(source.get("overallBalance") or 0) / 100,
            is_active=True,
        )

    def _fetch_transactions(
        self,
        source_accounts: Iterable[Dict[str, Any]],
        owned_subaccount_ids: set[str],
    ) -> tuple[list[NormalizedTransaction], list[str]]:
        transactions = []
        errors = []
        for source_account in source_accounts:
            account_id = source_account["id"]
            cursor = None
            while True:
                try:
                    data = self._client.execute(
                        "RecentActivity",
                        _RECENT_ACTIVITY_QUERY,
                        {"accountId": account_id, "cursor": cursor, "pageSize": 100},
                    )
                except Exception:
                    errors.append("transaction page unavailable")
                    break
                cash_transactions = ((data.get("account") or {}).get("cashTransactions") or {})
                for edge in cash_transactions.get("edges") or []:
                    transaction = self._normalize_transaction(
                        edge.get("node") or {},
                        account_id,
                        owned_subaccount_ids,
                    )
                    if transaction is not None:
                        transactions.append(transaction)
                page_info = cash_transactions.get("pageInfo") or {}
                if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
                    break
                cursor = page_info["endCursor"]
        return transactions, errors

    @staticmethod
    def _normalize_transaction(
        source: Dict[str, Any],
        source_account_id: str,
        owned_subaccount_ids: set[str],
    ) -> Optional[NormalizedTransaction]:
        external_id = source.get("id")
        occurred_at = source.get("occurredAt")
        if not isinstance(external_id, str) or not external_id or not isinstance(occurred_at, str):
            return None
        subaccount_id = (source.get("subaccount") or {}).get("id")
        account_external_id = subaccount_id if subaccount_id in owned_subaccount_ids else source_account_id
        transfer = source.get("transfer") or {}
        transfer_id = transfer.get("id")
        relation_hint = None
        if isinstance(transfer_id, str) and transfer_id:
            relation_hint = f"crew-transfer:{transfer_id}"
        return NormalizedTransaction(
            external_id=external_id,
            account_external_id=account_external_id,
            amount=float(source.get("amount") or 0) / 100,
            occurred_at=occurred_at,
            description=str(source.get("description") or source.get("title") or "Crew transaction"),
            status=str(source.get("status") or source.get("type") or "unknown"),
            merchant=source.get("matchingName"),
            raw_description=source.get("memo") or source.get("externalMemo"),
            relation_hint=relation_hint,
        )
