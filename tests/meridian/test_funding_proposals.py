from datetime import date
from decimal import Decimal

import pytest

from crew.actions import ActionStore
from meridian.funding import (
    FundingEvent,
    FundingProjection,
    FundingRule,
    project_funding,
)
from meridian.funding_proposals import propose_due_funding


def _store(tmp_path):
    return ActionStore(str(tmp_path / "actions.db"), allowed_types=("move_money", "scheduled_move_money"))


def _projection(events):
    return FundingProjection(
        events=tuple(events),
        total=sum((event.amount for event in events), Decimal("0")),
        shortfall=Decimal("0"),
        funded_by=events[-1].date if events else None,
        explanation=(),
    )


def _event(day, amount):
    from decimal import Decimal

    return FundingEvent(date=day, amount=Decimal(amount), source="paycheck", explanation=())


def test_each_due_event_becomes_one_proposal_with_calculation(tmp_path):
    store = _store(tmp_path)
    projection = _projection(
        [
            _event(date(2026, 9, 4), "100.00"),
            _event(date(2026, 9, 18), "100.00"),
        ]
    )

    proposals = propose_due_funding(
        projection,
        store,
        as_of=date(2026, 9, 1),
        rule_id="rule-7",
        commitment_name="Vacation",
        source_account_id=11,
        destination_account_id=22,
    )

    assert len(proposals) == 2
    pending = store.list_pending()
    assert len(pending) == 2
    assert all(action["type"] == "scheduled_move_money" for action in pending)

    first = pending[0]
    params = first["params"]
    assert params["from_id"] == 11
    assert params["to_id"] == 22
    assert params["amount"] == "100.00"
    assert params["rule_id"] == "rule-7"
    assert "event_date" in params
    assert "calculation" in params
    assert "Vacation" in first["rationale"]
    assert first["requested_by"] == "meridian-funding"


def test_repeated_triggers_create_no_duplicates(tmp_path):
    store = _store(tmp_path)
    projection = _projection([_event(date(2026, 9, 4), "100.00")])
    kwargs = dict(
        as_of=date(2026, 9, 1),
        rule_id="rule-7",
        commitment_name="Vacation",
        source_account_id=11,
        destination_account_id=22,
    )

    first = propose_due_funding(projection, store, **kwargs)
    second = propose_due_funding(projection, store, **kwargs)

    assert len(first) == 1
    assert second == first
    assert len(store.list_pending()) == 1


def test_different_amounts_on_the_same_day_are_separate_proposals(tmp_path):
    store = _store(tmp_path)
    projection = _projection(
        [
            _event(date(2026, 9, 4), "100.00"),
            _event(date(2026, 9, 4), "250.00"),
        ]
    )
    proposals = propose_due_funding(
        projection,
        store,
        as_of=date(2026, 9, 1),
        rule_id="rule-7",
        commitment_name="Vacation",
        source_account_id=11,
        destination_account_id=22,
    )
    assert len(proposals) == 2
    assert {proposal["params"]["amount"] for proposal in proposals} == {"100.00", "250.00"}


def test_zero_amount_events_never_propose(tmp_path):
    store = _store(tmp_path)
    projection = _projection([_event(date(2026, 9, 4), "0.00")])
    proposals = propose_due_funding(
        projection,
        store,
        as_of=date(2026, 9, 1),
        rule_id="rule-7",
        commitment_name="Vacation",
        source_account_id=11,
        destination_account_id=22,
    )
    assert proposals == []
    assert store.list_pending() == []


def test_unknown_action_types_still_rejected(tmp_path):
    store = ActionStore(str(tmp_path / "other.db"), allowed_types=("move_money",))
    with pytest.raises(Exception):
        propose_due_funding(
            _projection([_event(date(2026, 9, 4), "10.00")]),
            store,
            as_of=date(2026, 9, 1),
            rule_id="rule-1",
            commitment_name="X",
            source_account_id=1,
            destination_account_id=2,
        )


def test_projection_from_funding_engine_feeds_proposals(tmp_path):
    from types import SimpleNamespace

    rule = FundingRule(
        id="rule-9",
        commitment_id="c-1",
        kind="fixed_per_paycheck",
        amount=Decimal("75.00"),
        start_date=date(2026, 9, 1),
        horizon_end=date(2026, 9, 30),
    )
    goal = SimpleNamespace(
        type="goal", target_amount=Decimal("150.00"), funded_amount=Decimal("0"),
        amount=None, due_date=None, target_date=None,
    )
    projection = project_funding(
        rule,
        goal,
        [(date(2026, 9, 4), Decimal("2000"))],
        as_of=date(2026, 9, 1),
    )
    store = _store(tmp_path)
    proposals = propose_due_funding(
        projection,
        store,
        as_of=date(2026, 9, 1),
        rule_id=rule.id,
        commitment_name="Bike fund",
        source_account_id=5,
        destination_account_id=6,
    )
    assert len(proposals) == 1
    assert proposals[0]["params"]["amount"] == "75.00"
    assert store.list_pending()[0]["state"] == "proposed"
