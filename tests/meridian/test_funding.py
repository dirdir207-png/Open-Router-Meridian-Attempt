from datetime import date
from decimal import Decimal

import pytest

from meridian.funding import (
    FundingRule,
    project_funding,
)


def _rule(**overrides):
    base = dict(
        id="rule-1",
        commitment_id="c-1",
        kind="fixed_per_paycheck",
        amount=Decimal("100.00"),
        start_date=date(2026, 9, 1),
        horizon_end=date(2026, 10, 15),
    )
    base.update(overrides)
    return FundingRule(**base)


def _goal(target="1000.00", funded="0", target_date=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        type="goal",
        target_amount=Decimal(target),
        funded_amount=Decimal(funded),
        amount=None,
        due_date=None,
        target_date=target_date,
    )


def _paychecks(*pairs):
    return [(day, Decimal(amount)) for day, amount in pairs]


def test_fixed_per_paycheck_funds_every_paycheck_in_the_horizon():
    projection = project_funding(
        _rule(),
        _goal(),
        _paychecks((date(2026, 9, 4), "2000"), (date(2026, 9, 18), "2000")),
        as_of=date(2026, 9, 1),
    )
    assert [event.amount for event in projection.events] == [
        Decimal("100.00"),
        Decimal("100.00"),
    ]
    assert projection.total == Decimal("200.00")
    assert projection.shortfall == Decimal("800.00")


def test_percent_of_paycheck_uses_each_paycheck_amount():
    projection = project_funding(
        _rule(kind="percent_of_paycheck", amount=None, percent=Decimal("10")),
        _goal(target="500.00"),
        _paychecks((date(2026, 9, 4), "1500.55")),
        as_of=date(2026, 9, 1),
    )
    assert projection.events[0].amount == Decimal("150.06")
    assert projection.total == Decimal("150.06")


def test_calendar_cadence_monthly_clamps_short_months():
    projection = project_funding(
        _rule(
            kind="calendar",
            amount=Decimal("50.00"),
            cadence="monthly",
            day_of_month=31,
            horizon_end=date(2026, 10, 31),
        ),
        _goal(target="200.00"),
        [],
        as_of=date(2026, 9, 1),
    )
    assert [event.date for event in projection.events] == [
        date(2026, 9, 30),
        date(2026, 10, 31),
    ]


def test_biweekly_cadence_is_stable_across_the_dst_boundary():
    rule = _rule(
        kind="calendar",
        amount=Decimal("25.00"),
        cadence="biweekly",
        start_date=date(2026, 3, 1),
        horizon_end=date(2026, 3, 31),
    )
    projection = project_funding(rule, _goal(target="100.00"), [], as_of=date(2026, 3, 1))
    days = [event.date for event in projection.events]
    assert days == [date(2026, 3, 1), date(2026, 3, 15), date(2026, 3, 29)]
    gaps = {(b - a).days for a, b in zip(days, days[1:])}
    assert gaps == {14}


def test_even_by_due_date_splits_remaining_across_weeks():
    projection = project_funding(
        _rule(kind="even_by_due_date", amount=None, cadence="weekly"),
        _goal(target="300.00", target_date=date(2026, 10, 13)),
        [],
        as_of=date(2026, 9, 1),
    )
    assert projection.events
    assert sum((event.amount for event in projection.events), Decimal("0")) == Decimal("300.00")
    amounts = {event.amount for event in projection.events}
    assert max(amounts) - min(amounts) <= Decimal("0.01")


def test_even_by_due_date_is_not_used_without_a_date():
    projection = project_funding(
        _rule(kind="even_by_due_date", amount=None, cadence="weekly"),
        None,
        [],
        as_of=date(2026, 9, 1),
    )
    assert projection.events == ()
    assert "date" in " ".join(projection.explanation).lower()


def test_min_and_max_caps_bind():
    projection = project_funding(
        _rule(
            kind="percent_of_paycheck",
            amount=None,
            percent=Decimal("50"),
            min_contribution=Decimal("100.00"),
            max_contribution=Decimal("200.00"),
        ),
        _goal(target="1000.00"),
        _paychecks((date(2026, 9, 4), "300"), (date(2026, 9, 18), "1000")),
        as_of=date(2026, 9, 1),
    )
    assert [event.amount for event in projection.events] == [
        Decimal("150.00"),
        Decimal("200.00"),
    ]


def test_paused_rules_project_nothing():
    projection = project_funding(
        _rule(paused=True),
        _goal(),
        _paychecks((date(2026, 9, 4), "2000")),
        as_of=date(2026, 9, 1),
    )
    assert projection.events == ()
    assert projection.total == Decimal("0")
    assert "paused" in " ".join(projection.explanation).lower()


def test_skip_dates_are_honored():
    projection = project_funding(
        _rule(skip_dates=frozenset({date(2026, 9, 4)})),
        _goal(),
        _paychecks((date(2026, 9, 4), "2000"), (date(2026, 9, 18), "2000")),
        as_of=date(2026, 9, 1),
    )
    assert [event.date for event in projection.events] == [date(2026, 9, 18)]


def test_one_time_override_funds_once_at_the_full_amount():
    projection = project_funding(
        _rule(one_time_override=Decimal("500.00")),
        _goal(target="1000.00"),
        _paychecks((date(2026, 9, 4), "2000"), (date(2026, 9, 18), "2000")),
        as_of=date(2026, 9, 1),
    )
    assert len(projection.events) == 1
    assert projection.events[0].amount == Decimal("500.00")
    assert any("override" in factor for factor in projection.events[0].explanation)


def test_insufficient_cash_caps_allocations_and_reports_shortfall():
    projection = project_funding(
        _rule(kind="calendar", amount=Decimal("400.00"), cadence="monthly", day_of_month=5),
        _goal(target="800.00"),
        _paychecks((date(2026, 9, 1), "250")),
        as_of=date(2026, 9, 1),
    )
    assert [event.amount for event in projection.events] == [Decimal("250.00")]
    assert projection.total == Decimal("250.00")
    assert projection.shortfall == Decimal("550.00")
    assert any("cash" in factor.lower() for factor in projection.events[0].explanation)


def test_priority_waterfall_respects_already_reserved_cash():
    projection = project_funding(
        _rule(kind="priority_waterfall", amount=Decimal("150.00"), priority=2),
        _goal(target="1000.00"),
        _paychecks((date(2026, 9, 4), "2000")),
        as_of=date(2026, 9, 1),
        reserved_by_date={date(2026, 9, 4): Decimal("1900.00")},
    )
    assert [event.amount for event in projection.events] == [Decimal("100.00")]


def test_target_shortfall_limits_the_final_event():
    projection = project_funding(
        _rule(),
        _goal(target="150.00"),
        _paychecks((date(2026, 9, 4), "2000"), (date(2026, 9, 18), "2000")),
        as_of=date(2026, 9, 1),
    )
    assert [event.amount for event in projection.events] == [
        Decimal("100.00"),
        Decimal("50.00"),
    ]
    assert projection.shortfall == Decimal("0")


def test_projection_is_deterministic():
    rule = _rule()
    goal = _goal()
    cash = _paychecks((date(2026, 9, 4), "2000"), (date(2026, 9, 18), "1500"))
    first = project_funding(rule, goal, cash, as_of=date(2026, 9, 1))
    second = project_funding(rule, goal, cash, as_of=date(2026, 9, 1))
    assert first == second


def test_bill_projection_funds_the_amount_by_its_due_date():
    rule = _rule(kind="even_by_due_date", amount=None, cadence="weekly")
    bill = _goal(target="0")
    bill.type = "bill"
    bill.amount = Decimal("120.00")
    bill.due_date = date(2026, 9, 22)
    projection = project_funding(rule, bill, [], as_of=date(2026, 9, 1))
    assert projection.total == Decimal("120.00")
    assert all(event.date <= bill.due_date for event in projection.events)


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        project_funding(_rule(kind="magic"), _goal(), [], as_of=date(2026, 9, 1))


def _property_scenarios():
    scenarios = []
    kinds = ["fixed_per_paycheck", "percent_of_paycheck", "calendar", "even_by_due_date", "priority_waterfall"]
    paydates = [
        date(2026, 9, 4), date(2026, 9, 18), date(2026, 10, 2), date(2026, 10, 16),
    ]
    for index, kind in enumerate(kinds):
        rule = _rule(
            id=f"prop-{index}",
            kind=kind,
            amount=Decimal("120.00"),
            percent=Decimal("15"),
            cadence="biweekly",
            day_of_month=10,
            start_date=date(2026, 9, 1),
            horizon_end=date(2026, 10, 31),
            max_contribution=Decimal("200.00"),
            min_contribution=Decimal("10.00") if index % 2 else None,
        )
        goal = _goal(target="900.00", target_date=date(2026, 11, 30))
        cash = [(day, Decimal("1400")) for day in paydates[: index + 1]]
        cash.append((date(2026, 9, 10), Decimal("-300")))
        scenarios.append((rule, goal, cash))
    return scenarios


def test_allocations_conserve_cash_and_respect_caps():
    for rule, goal, cash in _property_scenarios():
        projection = project_funding(rule, goal, cash, as_of=date(2026, 9, 1))

        inflow = sum((Decimal(amount) for day, amount in cash if amount > 0), Decimal("0"))
        outflow = sum((Decimal(amount) for day, amount in cash if amount < 0), Decimal("0"))
        available = inflow + outflow

        assert projection.total >= Decimal("0")
        assert projection.total <= available
        for event in projection.events:
            assert event.amount >= Decimal("0")
            if rule.max_contribution is not None:
                assert event.amount <= rule.max_contribution
        assert sum((event.amount for event in projection.events), Decimal("0")) == projection.total


def test_identical_inputs_always_produce_identical_projections():
    for rule, goal, cash in _property_scenarios():
        assert project_funding(rule, goal, cash, as_of=date(2026, 9, 1)) == project_funding(
            rule, goal, cash, as_of=date(2026, 9, 1)
        )
