"""One canonical Plan view model: summary, timeline, allocation, commitments."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Sequence

from meridian.funding import project_funding
from meridian.funding_repo import FundingRuleRepository

_HORIZON_DAYS = 30
_ZERO = Decimal("0")


def _money(value) -> Decimal:
    return Decimal(str(value)) if value is not None else _ZERO


def _project_commitment(commitment, rules, cash_events, as_of: date):
    projections = []
    for rule in rules:
        if rule.paused:
            continue
        deadline = None
        for candidate in (
            getattr(commitment, "due_date", None),
            getattr(commitment, "target_date", None),
        ):
            if isinstance(candidate, str) and candidate:
                try:
                    deadline = date.fromisoformat(candidate)
                except ValueError:
                    deadline = None
            elif isinstance(candidate, date):
                deadline = candidate
        horizon_end = rule.horizon_end or (as_of + timedelta(days=_HORIZON_DAYS))
        if deadline and deadline < horizon_end:
            horizon_end = deadline
        projection = project_funding(
            rule,
            commitment,
            cash_events,
            as_of=as_of,
        )
        projections.append((rule, projection))
    return projections


def build_plan(
    graph_repository,
    commitment_repository,
    rule_repository: FundingRuleRepository,
    *,
    as_of: date,
    cash_events: Optional[Sequence[tuple[date, Decimal]]] = None,
) -> dict:
    """Compose the canonical Plan view model from local planning data.

    Cash events default to the graph's current cash balances treated as a
    single event today; callers with richer timelines may pass them.
    """
    if cash_events is None:
        cash_events = _cash_events_from_graph(graph_repository, as_of)

    accounts = {account.id: account for account in graph_repository.list_accounts()}
    commitments = commitment_repository.list_active()
    horizon_end = as_of + timedelta(days=_HORIZON_DAYS)

    commitment_views = []
    timeline_events = []
    shortfalls = []
    total_target = _ZERO
    total_funded = _ZERO
    next_due = None

    for commitment in commitments:
        commitment_type = commitment.type.value
        target = _commitment_target(commitment)
        funded = _money(commitment.funded_amount)
        total_target += target if commitment_type != "buffer" else _ZERO
        total_funded += min(funded, target) if commitment_type != "buffer" else _ZERO

        rules = rule_repository.list_for_commitment(commitment.id)
        projections = _project_commitment(commitment, rules, cash_events, as_of)
        projected_total = sum(
            (projection.total for _rule, projection in projections), _ZERO
        )

        due_date = _date_of(getattr(commitment, "due_date", None))
        target_date = _date_of(getattr(commitment, "target_date", None))
        if due_date and (next_due is None or due_date < next_due):
            next_due = due_date

        for rule, projection in projections:
            for event in projection.events:
                if event.amount <= _ZERO or not (as_of <= event.date <= horizon_end):
                    continue
                timeline_events.append(
                    {
                        "date": event.date.isoformat(),
                        "amount": float(event.amount),
                        "commitment": commitment.name,
                        "commitment_id": commitment.id,
                        "rule_id": rule.id,
                        "source": event.source,
                        "explanation": list(event.explanation),
                    }
                )
            for event in projection.events:
                deficit = event.desired_amount - event.amount
                if deficit > _ZERO:
                    shortfalls.append(
                        {
                            "date": event.date.isoformat(),
                            "amount": float(deficit),
                            "cause": (
                                f"{commitment.name} wanted ${event.desired_amount} but only "
                                f"${event.amount} of cash was available"
                            ),
                            "commitment_id": commitment.id,
                        }
                    )

        backing = None
        backing_id = getattr(commitment, "backing_account_id", None)
        if backing_id is not None and backing_id in accounts:
            backing = {
                "account_id": backing_id,
                "name": accounts[backing_id].name,
            }

        commitment_views.append(
            {
                "id": commitment.id,
                "type": commitment_type,
                "name": commitment.name,
                "status": commitment.status.value,
                "priority": commitment.priority,
                "target": float(target),
                "funded": float(min(funded, target)) if commitment_type != "buffer" else float(funded),
                "unfunded": float(max(_ZERO, target - funded)),
                "due_date": due_date.isoformat() if due_date else None,
                "target_date": target_date.isoformat() if target_date else None,
                "backing": backing,
                "rule_ids": [str(rule.id) for rule in rules],
                "projected_30d": float(projected_total),
                "explanation": _coverage_explanation(target, funded, projected_total),
            }
        )

    timeline_events.sort(key=lambda item: (item["date"], item["commitment"]))
    shortfalls.sort(key=lambda item: (item["date"], -item["amount"]))
    first_shortfall = shortfalls[0] if shortfalls else None

    cash_total = sum(
        (
            _money(account.balance)
            for account in accounts.values()
            if account.is_active and account.account_type in ("cash", "checking", "savings")
        ),
        _ZERO,
    )
    committed = sum(
        (
            min(_money(view["funded"]), _money(view["target"]))
            for view in commitment_views
            if view["type"] != "buffer"
        ),
        _ZERO,
    )
    unfunded = max(_ZERO, total_target - total_funded)
    available = max(_ZERO, cash_total - committed - unfunded)

    coverage_ratio = float(min(_money("1"), total_funded / total_target)) if total_target > _ZERO else 0.0
    if commitments:
        headline = (
            f"{len(commitments)} commitments, "
            f"{int(coverage_ratio * 100)}% funded"
        )
    else:
        headline = "No commitments yet — add one to start planning"

    return {
        "summary": {
            "headline": headline,
            "commitment_count": len(commitments),
            "total_target": float(total_target),
            "total_funded": float(total_funded),
            "unfunded": float(unfunded),
            "coverage_ratio": coverage_ratio,
            "next_due": next_due.isoformat() if next_due else None,
            "first_shortfall": first_shortfall,
        },
        "commitments": commitment_views,
        "timeline": {
            "start": as_of.isoformat(),
            "end": horizon_end.isoformat(),
            "events": timeline_events,
        },
        "allocation": {
            "cash_total": float(cash_total),
            "segments": [
                {"label": "Committed to commitments", "amount": float(committed)},
                {"label": "Unfunded commitments", "amount": float(unfunded)},
                {"label": "Available", "amount": float(available)},
            ],
        },
        "data_freshness": _graph_freshness(graph_repository),
    }


def _coverage_explanation(target: Decimal, funded: Decimal, projected: Decimal) -> list[str]:
    factors = []
    if funded > _ZERO:
        factors.append(f"${funded} already set aside")
    if projected > _ZERO:
        factors.append(f"${projected} projected from funding rules in the next 30 days")
    remaining = max(_ZERO, target - funded - projected)
    if target > _ZERO and remaining > _ZERO:
        factors.append(f"${remaining} still needs a plan")
    if not factors:
        factors.append("No funding activity yet")
    return factors


def _commitment_target(commitment) -> Decimal:
    commitment_type = commitment.type.value
    if commitment_type == "bill":
        return _money(commitment.amount)
    if commitment_type == "buffer":
        return _money(commitment.buffer_minimum)
    return _money(commitment.target_amount)


def _date_of(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _cash_events_from_graph(graph_repository, as_of: date) -> list[tuple[date, Decimal]]:
    total = sum(
        (
            _money(account.balance)
            for account in graph_repository.list_accounts()
            if account.is_active and account.account_type in ("cash", "checking", "savings")
        ),
        _ZERO,
    )
    return [(as_of, total)] if total > _ZERO else []


def _graph_freshness(graph_repository) -> dict:
    from meridian.services.today import data_freshness

    return data_freshness(graph_repository, include_all_connections=True)
