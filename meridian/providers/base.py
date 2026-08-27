"""Provider-neutral, credential-free snapshots used by Meridian syncs."""

from dataclasses import dataclass
from typing import Optional, Protocol, Tuple


@dataclass(frozen=True)
class NormalizedAccount:
    external_id: str
    name: str
    account_type: str
    balance: float
    currency: str = "USD"
    available_balance: Optional[float] = None
    is_active: bool = True
    source_updated_at: Optional[str] = None


@dataclass(frozen=True)
class NormalizedTransaction:
    external_id: str
    account_external_id: str
    amount: float
    occurred_at: str
    description: str
    status: str
    currency: str = "USD"
    posted_at: Optional[str] = None
    merchant: Optional[str] = None
    raw_description: Optional[str] = None
    source_updated_at: Optional[str] = None
    category: Optional[str] = None
    relation_hint: Optional[str] = None


@dataclass(frozen=True)
class ProviderSnapshot:
    connection_external_id: str
    connection_name: str
    accounts: Tuple[NormalizedAccount, ...]
    transactions: Tuple[NormalizedTransaction, ...]
    is_complete: bool = True
    errors: Tuple[str, ...] = ()


class ProviderAdapter(Protocol):
    provider_name: str
    connection_external_id: str
    connection_name: str

    def fetch_snapshot(self) -> ProviderSnapshot:
        """Return a credential-free read-only source snapshot."""
