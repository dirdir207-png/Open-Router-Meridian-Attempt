"""Pure funding-rule projections.

Given a rule, a commitment, and the household cash timeline, project the
dated contributions the rule would make. Everything here is deterministic,
Decimal-based, and free of I/O: no providers, no database, no clock reads.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Mapping, Optional, Sequence

_KINDS = frozenset(
    {
        "fixed_per_paycheck",
        "percent_of_paycheck",
        "calendar",
        "even_by_due_date",
        "priority_waterfall",
    }
)

_WEEKLY_DAYS = 7
_BIWEEKLY_DAYS = 14

_ZERO = Decimal("0")
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class FundingRule:
    id: str
    commitment_id: str
    kind: str
    amount: Optional[Decimal] = None
    percent: Optional[Decimal] = None
    cadence: Optional[str] = None
    day_of_month: Optional[int] = None
    start_date: date = date(2026, 1, 1)
    horizon_end: Optional[date] = None
    min_contribution: Optional[Decimal] = None
    max_contribution: Optional[Decimal] = None
    paused: bool = False
    skip_dates: frozenset = frozenset()
    one_time_override: Optional[Decimal] = None
    priority: int = 3

    def __post_init__(self):
        if self.kind not in _KINDS:
            raise ValueError(f"unknown funding rule kind: {self.kind}")


@dataclass(frozen=True)
class FundingEvent:
    date: date
    amount: Decimal
    source: str
    explanation: tuple = field(default_factory=tuple)
    desired_amount: Decimal = _ZERO


@dataclass(frozen=True)
class FundingProjection:
    events: tuple
    total: Decimal
    shortfall: Decimal
    funded_by: Optional[date]
    explanation: tuple


def _money(value) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid money value: {value!r}") from exc


def _monthly_dates(start: date, day_of_month: int, end: date) -> list[date]:
    dates = []
    year, month = start.year, start.month
    while True:
        last_day = calendar.monthrange(year, month)[1]
        effective_day = min(day_of_month, last_day)
        candidate = date(year, month, effective_day)
        if candidate > end:
            break
        if candidate >= start:
            dates.append(candidate)
        month += 1
        if month == 13:
            month = 1
            year += 1
    return dates


def _cadence_dates(rule: FundingRule, end: date) -> list[date]:
    cadence = (rule.cadence or "monthly").lower()
    if cadence == "monthly":
        day = rule.day_of_month or rule.start_date.day
        return _monthly_dates(rule.start_date, day, end)
    if cadence == "weekly":
        step = _WEEKLY_DAYS
    elif cadence == "biweekly":
        step = _BIWEEKLY_DAYS
    else:
        raise ValueError(f"unsupported cadence: {rule.cadence}")
    dates = []
    cursor = rule.start_date
    while cursor <= end:
        dates.append(cursor)
        cursor += timedelta(days=step)
    return dates


def _commitment_target(commitment) -> Decimal:
    """Remaining amount the rule is trying to fund."""
    commitment_type = getattr(commitment, "type", "")
    if commitment_type == "bill":
        return _money(getattr(commitment, "amount") or 0)
    target = getattr(commitment, "target_amount", None)
    if target is None:
        return _ZERO
    funded = getattr(commitment, "funded_amount", None) or _ZERO
    remaining = _money(target) - _money(funded)
    return remaining if remaining > _ZERO else _ZERO


def _commitment_deadline(commitment, rule: FundingRule, as_of: date) -> Optional[date]:
    due = getattr(commitment, "due_date", None)
    if isinstance(due, date):
        return due
    target_date = getattr(commitment, "target_date", None)
    if isinstance(target_date, date):
        return target_date
    return rule.horizon_end


def _clamp_to_caps(amount: Decimal, rule: FundingRule) -> tuple[Decimal, Optional[str]]:
    bounded = amount
    reason = None
    if rule.min_contribution is not None and bounded < _money(rule.min_contribution):
        bounded = _money(rule.min_contribution)
        reason = "min_contribution"
    if rule.max_contribution is not None and bounded > _money(rule.max_contribution):
        bounded = _money(rule.max_contribution)
        reason = "max_contribution"
    return bounded, reason


def project_funding(
    rule: FundingRule,
    commitment,
    cash_events: Sequence[tuple[date, Decimal]],
    *,
    as_of: date,
    reserved_by_date: Optional[Mapping[date, Decimal]] = None,
) -> FundingProjection:
    """Project dated contributions for one rule over the household cash timeline.

    ``cash_events`` pairs dates with signed amounts: positive entries are
    inflows such as paychecks; negative entries are known outflows. Funding
    never allocates more cash than exists on each date, and never exceeds the
    configured caps or the commitment's remaining target.
    """
    reserved_by_date = dict(reserved_by_date or {})

    if rule.paused:
        return FundingProjection(
            events=(),
            total=_ZERO,
            shortfall=_ZERO,
            funded_by=None,
            explanation=("rule is paused",),
        )

    deadline = _commitment_deadline(commitment, rule, as_of) if commitment else rule.horizon_end
    end = deadline or rule.horizon_end or (as_of + timedelta(days=90))
    if end < as_of:
        end = as_of

    target_remaining = _commitment_target(commitment) if commitment else _ZERO
    ordered_cash = sorted(cash_events, key=lambda item: item[0])
    paychecks = [
        (day, _money(amount))
        for day, amount in ordered_cash
        if amount > 0 and as_of <= day <= end
    ]

    desired: list[tuple[date, Decimal, str]] = []
    if rule.kind == "fixed_per_paycheck":
        for day, _amount in paychecks:
            desired.append((day, _money(rule.amount or _ZERO), "paycheck"))
    elif rule.kind == "percent_of_paycheck":
        for day, amount in paychecks:
            desired.append(
                (day, _money(amount * (rule.percent or _ZERO) / Decimal(100)), "paycheck")
            )
    elif rule.kind == "calendar":
        for day in _cadence_dates(rule, end):
            if day >= as_of:
                desired.append((day, _money(rule.amount or _ZERO), "calendar"))
    elif rule.kind == "even_by_due_date":
        desired.extend(_even_by_date_dates(rule, commitment, as_of, end, target_remaining))
    elif rule.kind == "priority_waterfall":
        for day, _amount in paychecks:
            desired.append((day, _money(rule.amount or _ZERO), "paycheck"))
    else:  # defensive; FundingRule validates kinds already
        raise ValueError(f"unknown funding rule kind: {rule.kind}")

    if rule.one_time_override is not None and desired:
        first_day = desired[0][0]
        desired = [(first_day, _money(rule.one_time_override), "one_time_override")]

    events: list[FundingEvent] = []
    skipped: list[str] = []
    remaining_target = target_remaining
    reserved_by_date = dict(reserved_by_date)
    balance_on = _cash_balance_lookup(ordered_cash, as_of)
    strict_cash = any(day >= as_of for day, _amount in ordered_cash)

    for day, amount, source in desired:
        if remaining_target <= _ZERO:
            break
        if day in rule.skip_dates:
            skipped.append(f"{day.isoformat()} skipped by rule")
            continue
        bounded, cap_reason = _clamp_to_caps(amount, rule)
        bounded = min(bounded, remaining_target)

        explanation = []
        if source == "one_time_override":
            explanation.append("one_time_override applied")
        if strict_cash:
            reserved = sum(
                (amount for reserved_day, amount in reserved_by_date.items() if reserved_day <= day),
                _ZERO,
            )
            available_cash = balance_on(day) - reserved
            if available_cash <= _ZERO:
                skipped.append(f"{day.isoformat()} skipped: insufficient cash")
                continue
            if available_cash < bounded:
                explanation.append("limited by available cash")
                bounded = available_cash
        elif cap_reason:
            explanation.append(f"limited by {cap_reason}")

        events.append(
            FundingEvent(
                date=day,
                amount=bounded,
                source=source,
                explanation=tuple(explanation),
                desired_amount=amount,
            )
        )
        remaining_target -= bounded
        reserved_by_date[day] = reserved_by_date.get(day, _ZERO) + bounded

    funded_events = [event for event in events if event.amount > _ZERO]
    total = sum((event.amount for event in funded_events), _ZERO)
    shortfall = max(_ZERO, target_remaining - total)
    funded_by = max((event.date for event in funded_events), default=None)
    notes = tuple(skipped)
    if rule.kind == "even_by_due_date" and not desired:
        notes = notes + ("even-by-date funding needs a due date or target date",)
    return FundingProjection(
        events=tuple(events),
        total=total,
        shortfall=shortfall,
        funded_by=funded_by,
        explanation=notes,
    )


def _cash_balance_lookup(ordered_cash, as_of: date):
    """Return a callable giving the cash balance on or before any date >= as_of."""
    inflows = sorted((day, amount) for day, amount in ordered_cash if day >= as_of)
    starting = sum((amount for day, amount in ordered_cash if day < as_of), _ZERO)

    def balance_on(day: date) -> Decimal:
        total = starting
        for event_day, amount in inflows:
            if event_day <= day:
                total += amount
            else:
                break
        return total

    return balance_on


def _even_by_date_dates(
    rule: FundingRule, commitment, as_of: date, end: date, target_remaining: Decimal
) -> list[tuple[date, Decimal, str]]:
    if commitment is None:
        return []
    due = getattr(commitment, "due_date", None) or getattr(commitment, "target_date", None)
    if not isinstance(due, date):
        return []
    weeks = max(1, ((due - as_of).days + 6) // 7)
    per_event = (target_remaining / weeks).quantize(_CENT, rounding=ROUND_HALF_UP)
    dates = []
    cursor = as_of
    allocated = _ZERO
    while cursor <= due and allocated < target_remaining:
        amount = min(per_event, target_remaining - allocated)
        dates.append((cursor, amount, "even_by_due_date"))
        allocated += amount
        cursor += timedelta(days=7)
    return dates
