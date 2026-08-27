from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from meridian.commitments import CommitmentRepository, CommitmentType
from meridian.funding_repo import FundingRuleRepository
from meridian.repository import FinancialRepository
from meridian.services.plan import build_plan


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "plan.db")
    graph = FinancialRepository(db)
    commitments = CommitmentRepository(db)
    rules = FundingRuleRepository(db)
    return graph, commitments, rules


def _synced_checking(graph, balance=2000.0):
    run = graph.begin_sync_run(
        provider="crew",
        connection_external_id="crew-household",
        connection_name="Crew",
    )
    account = graph.upsert_account(
        provider="crew",
        external_id="checking-1",
        name="Checking",
        account_type="checking",
        balance=balance,
        connection_id=run.connection_id,
        source_updated_at=datetime.now(timezone.utc).isoformat(),
    )
    graph.finish_sync_run(run.id, status="complete", accounts_synced=1, transactions_synced=0, errors=0)
    return account


def _pocket(graph, external_id, name, balance):
    return graph.upsert_account(
        provider="crew",
        external_id=external_id,
        name=name,
        account_type="pocket",
        balance=balance,
        source_updated_at=datetime.now(timezone.utc).isoformat(),
    )


def test_plan_summarizes_commitments_and_coverage(env):
    graph, commitments, rules = env
    _synced_checking(graph, balance=1500.0)
    pocket = _pocket(graph, "vac-1", "Vacation", 250.0)
    commitments.create(
        type=CommitmentType.GOAL,
        name="Vacation",
        target_amount=1000.0,
        funded_amount=250.0,
        backing_account_id=pocket.id,
    )
    commitments.create(
        type=CommitmentType.BILL,
        name="Internet",
        amount=80.0,
        due_date="2026-10-01",
    )

    plan = build_plan(
        graph,
        commitments,
        rules,
        as_of=date(2026, 9, 1),
    )

    assert plan["summary"]["commitment_count"] == 2
    assert Decimal(str(plan["summary"]["total_target"])) == Decimal("1080.00")
    assert Decimal(str(plan["summary"]["total_funded"])) == Decimal("250.00")
    assert Decimal(str(plan["summary"]["unfunded"])) == Decimal("830.00")
    assert 0 < plan["summary"]["coverage_ratio"] < 1
    assert plan["summary"]["next_due"] == "2026-10-01"


def test_plan_includes_backing_account_names_and_states(env):
    graph, commitments, rules = env
    _synced_checking(graph)
    pocket = _pocket(graph, "car-1", "Car repairs", 40.0)
    commitments.create(
        type=CommitmentType.GOAL,
        name="Car repairs",
        target_amount=400.0,
        funded_amount=40.0,
        backing_account_id=pocket.id,
    )
    commitments.create(
        type=CommitmentType.BUFFER,
        name="Checking floor",
        buffer_minimum=200.0,
    )

    plan = build_plan(graph, commitments, rules, as_of=date(2026, 9, 1))
    by_name = {c["name"]: c for c in plan["commitments"]}
    assert by_name["Car repairs"]["backing"] == {
        "account_id": pocket.id,
        "name": "Car repairs",
    }
    assert by_name["Checking floor"]["backing"] is None


def test_plan_timeline_lists_upcoming_funding_events(env):
    graph, commitments, rules = env
    _synced_checking(graph)
    pocket = _pocket(graph, "vac-1", "Vacation", 0.0)
    commitment = commitments.create(
        type=CommitmentType.GOAL,
        name="Vacation",
        target_amount=200.0,
        backing_account_id=pocket.id,
    )
    rules.create(
        commitment_id=commitment.id,
        kind="fixed_per_paycheck",
        amount=50.0,
        start_date=date(2026, 9, 1),
        horizon_end=date(2026, 12, 31),
    )

    plan = build_plan(
        graph,
        commitments,
        rules,
        as_of=date(2026, 9, 1),
        cash_events=[(date(2026, 9, 4), Decimal("2000"))],
    )

    timeline = plan["timeline"]["events"]
    assert timeline, "expected at least one projected funding event"
    first = timeline[0]
    assert first["date"] == "2026-09-04"
    assert Decimal(str(first["amount"])) == Decimal("50.00")
    assert first["commitment"] == "Vacation"
    assert "explanation" in first


def test_plan_reports_first_projected_shortfall(env):
    graph, commitments, rules = env
    _synced_checking(graph, balance=100.0)
    commitment = commitments.create(
        type=CommitmentType.GOAL,
        name="Vacation",
        target_amount=400.0,
    )
    rules.create(
        commitment_id=commitment.id,
        kind="calendar",
        amount=150.0,
        cadence="monthly",
        day_of_month=5,
        start_date=date(2026, 9, 1),
        horizon_end=date(2026, 12, 31),
    )

    plan = build_plan(
        graph,
        commitments,
        rules,
        as_of=date(2026, 9, 1),
        cash_events=[(date(2026, 9, 1), Decimal("100"))],
    )

    shortfall = plan["summary"]["first_shortfall"]
    assert shortfall is not None
    assert shortfall["date"] == "2026-09-05"
    assert Decimal(str(shortfall["amount"])) == Decimal("50.00")
    assert "Vacation" in shortfall["cause"]


def test_plan_allocation_segments_reconcile(env):
    graph, commitments, rules = env
    _synced_checking(graph, balance=1500.0)
    pocket = _pocket(graph, "vac-1", "Vacation", 250.0)
    commitments.create(
        type=CommitmentType.GOAL,
        name="Vacation",
        target_amount=1000.0,
        funded_amount=250.0,
        backing_account_id=pocket.id,
    )

    plan = build_plan(graph, commitments, rules, as_of=date(2026, 9, 1))
    segments = plan["allocation"]["segments"]
    total = sum(Decimal(str(segment["amount"])) for segment in segments)
    assert total == Decimal("1500.00")
    by_label = {segment["label"]: Decimal(str(segment["amount"])) for segment in segments}
    assert by_label["Committed to commitments"] == Decimal("250.00")
    assert by_label["Unfunded commitments"] == Decimal("750.00")
    assert by_label["Available"] == Decimal("500.00")


def test_plan_labels_stale_freshness(env):
    graph, commitments, rules = env
    _pocket(graph, "loose-1", "Unlinked", 10.0)
    plan = build_plan(graph, commitments, rules, as_of=date(2026, 9, 1))
    assert plan["data_freshness"]["status"] in {"stale", "unavailable"}


def test_empty_plan_is_an_honest_empty_state(env):
    graph, commitments, rules = env
    _synced_checking(graph, balance=500.0)
    plan = build_plan(graph, commitments, rules, as_of=date(2026, 9, 1))
    assert plan["summary"]["commitment_count"] == 0
    assert plan["commitments"] == []
    assert plan["timeline"]["events"] == []
    assert plan["summary"]["first_shortfall"] is None
    assert "no commitments" in plan["summary"]["headline"].lower()
