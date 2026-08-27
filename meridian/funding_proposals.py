"""Turn due funding events into idempotent, approval-only proposals."""

from decimal import Decimal

_DEDUP_PREFIX = "funding"
_REQUESTED_BY = "meridian-funding"


def _dedup_key(rule_id: str, event_date, amount: Decimal) -> str:
    amount_minor = int((amount * 100).to_integral_value())
    return f"{_DEDUP_PREFIX}:{rule_id}:{event_date.isoformat()}:{amount_minor}"


def _rationale(event, commitment_name: str, projection) -> str:
    return (
        f"Fund {commitment_name} with ${event.amount} on {event.date.isoformat()} "
        f"(projected total ${projection.total}, shortfall ${projection.shortfall}). "
        "Approve to move this money; nothing moves without you."
    )


def propose_due_funding(
    projection,
    store,
    *,
    as_of,
    rule_id: str,
    commitment_name: str,
    source_account_id: int,
    destination_account_id: int,
) -> list[dict]:
    """Create one idempotent scheduled_move_money proposal per funded event.

    Repeated triggers for the same rule/date/amount return the original
    proposals instead of duplicating them. Nothing here executes anything:
    proposals wait in Pending Actions for an explicit owner approval.
    """
    proposals: list[dict] = []
    for event in projection.events:
        if event.amount <= 0:
            continue
        params = {
            "from_id": source_account_id,
            "to_id": destination_account_id,
            "amount": str(event.amount),
            "memo": f"Funding: {commitment_name} ({rule_id})",
            "rule_id": rule_id,
            "event_date": event.date.isoformat(),
            "calculation": {
                "source": event.source,
                "explanation": list(event.explanation),
                "projection_total": str(projection.total),
                "projection_shortfall": str(projection.shortfall),
                "as_of": as_of.isoformat(),
            },
        }
        action = store.propose(
            "scheduled_move_money",
            params,
            _rationale(event, commitment_name, projection),
            _REQUESTED_BY,
            dedup_key=_dedup_key(rule_id, event.date, event.amount),
        )
        proposals.append(action)
    return proposals
