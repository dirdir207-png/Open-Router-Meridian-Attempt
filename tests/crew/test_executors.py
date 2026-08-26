import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from crew.actions import ActionState, ActionStore, IllegalTransitionError
from crew.executors import ExecutorSpec, execute_approved_action, expire_stale_approvals

ALLOWED_TYPES = ("move_money",)


@pytest.fixture
def store(tmp_path):
    return ActionStore(db_path=str(tmp_path / "actions.db"), allowed_types=ALLOWED_TYPES)


def make_executors(fn=None, verifier=None):
    return {
        "move_money": ExecutorSpec(
            execute=fn or (lambda params: {"success": True, "result": {"id": "tx-1"}}),
            verifier=verifier,
        )
    }


def seed_approved_action(store, params=None):
    request = store.propose("move_money", params or {"amount": 100}, "r", "ai-helper")
    store.approve(request["id"], decided_by="owner")
    return request["id"]


def test_approved_action_executes_and_verifies(store):
    verifications = []

    def verifier(params, result):
        verifications.append((params, result))
        return {"ok": True, "checked": "transfer-id-present"}

    action_id = seed_approved_action(store)
    final = execute_approved_action(
        store,
        action_id,
        make_executors(verifier=verifier),
        execution_key="execute-once-key",
    )
    assert final["state"] == ActionState.VERIFIED.value
    assert final["execution_key"] == "execute-once-key"
    assert final["result"]["result"]["id"] == "tx-1"
    assert final["verification"]["ok"] is True
    assert verifications[0][0] == {"amount": 100}


def test_error_contract_lands_in_failed_without_verification(store):
    calls = []

    def executor(params):
        return {"error": "Transfer outcome is uncertain.", "error_code": "uncertain_write", "verify_state": True}

    def verifier(params, result):
        calls.append("never")

    action_id = seed_approved_action(store)
    final = execute_approved_action(store, action_id, make_executors(fn=executor, verifier=verifier))
    assert final["state"] == ActionState.FAILED.value
    assert final["result"]["error_code"] == "uncertain_write"
    assert final["result"]["verify_state"] is True
    assert calls == []


def test_executor_exception_persists_uncertain_outcome_without_retry_or_verification(store):
    calls = {"executor": 0, "verifier": 0}

    def broken(params):
        calls["executor"] += 1
        raise RuntimeError("boom")

    def verifier(params, result):
        calls["verifier"] += 1
        return {"ok": True}

    action_id = seed_approved_action(store)
    final = execute_approved_action(store, action_id, make_executors(fn=broken, verifier=verifier))
    assert final["state"] == ActionState.FAILED.value
    assert final["result"]["error_code"] == "executor_exception"
    assert final["result"]["verify_state"] is True
    assert calls == {"executor": 1, "verifier": 0}


def test_unapproved_action_cannot_execute(store):
    request = store.propose("move_money", {}, "r", "owner")
    with pytest.raises(IllegalTransitionError):
        execute_approved_action(store, request["id"], make_executors())


def test_missing_executor_registration_fails_loudly(store):
    action_id = seed_approved_action(store)
    final = execute_approved_action(store, action_id, {})
    assert final["state"] == ActionState.FAILED.value
    assert final["result"]["error_code"] == "no_executor"


def test_failed_verification_overrides_success(store):
    action_id = seed_approved_action(store)
    final = execute_approved_action(
        store,
        action_id,
        make_executors(verifier=lambda params, result: {"ok": False, "reason": "balance unchanged"}),
    )
    assert final["state"] == ActionState.FAILED.value
    assert final["result"]["verification"]["reason"] == "balance unchanged"


def test_concurrent_execution_claims_action_once(store):
    start = threading.Barrier(2)
    executor_calls = []
    executor_calls_lock = threading.Lock()
    concurrent_executor_calls = threading.Barrier(2)

    def executor(params):
        with executor_calls_lock:
            executor_calls.append(params)
        try:
            concurrent_executor_calls.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass
        return {"success": True, "result": {"id": "tx-concurrent"}}

    action_id = seed_approved_action(store)

    def execute():
        start.wait()
        try:
            return execute_approved_action(store, action_id, make_executors(fn=executor))
        except IllegalTransitionError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(), range(2)))

    assert len(executor_calls) == 1
    conflicts = [result for result in results if isinstance(result, IllegalTransitionError)]
    terminal_results = [result for result in results if isinstance(result, dict)]
    assert len(conflicts) == 1
    assert str(conflicts[0]) == "Action is not available for execution"
    assert len(terminal_results) == 1
    assert terminal_results[0]["state"] == ActionState.VERIFIED.value


def test_stale_approvals_expire_recent_ones_survive(store, monkeypatch):
    from datetime import datetime, timedelta

    from crew import actions as actions_module

    clock = {"now": datetime(2026, 8, 25, 12, 0, 0)}
    monkeypatch.setattr(actions_module, "_now", lambda: clock["now"])

    stale_id = seed_approved_action(store)

    clock["now"] = clock["now"] + timedelta(hours=2)
    fresh_id = seed_approved_action(store)

    expired_ids = expire_stale_approvals(
        store,
        ttl_seconds=3600,
        now=clock["now"],
    )
    assert stale_id in expired_ids
    assert fresh_id not in expired_ids
    assert store.get(stale_id)["state"] == ActionState.EXPIRED.value
    assert store.get(fresh_id)["state"] == ActionState.APPROVED.value

    with pytest.raises(IllegalTransitionError):
        execute_approved_action(store, stale_id, make_executors())


def test_expiry_sweep_tolerates_claim_race_and_continues(tmp_path):
    from datetime import datetime, timedelta

    class ClaimingActionStore(ActionStore):
        claim_during_sweep = None

        def list_by_state(self, state):
            requests = super().list_by_state(state)
            if state == ActionState.APPROVED and self.claim_during_sweep:
                claimed_id = self.claim_during_sweep
                self.claim_during_sweep = None
                self.claim_for_execution(claimed_id, "sweep-race-key")
                requests.sort(key=lambda request: request["id"] != claimed_id)
            return requests

    racing_store = ClaimingActionStore(
        db_path=str(tmp_path / "actions.db"),
        allowed_types=ALLOWED_TYPES,
    )
    claimed_id = seed_approved_action(racing_store)
    expired_id = seed_approved_action(racing_store)
    racing_store.claim_during_sweep = claimed_id

    expired_ids = expire_stale_approvals(
        racing_store,
        ttl_seconds=3600,
        now=datetime.now() + timedelta(hours=2),
    )

    assert expired_ids == [expired_id]
    assert racing_store.get(claimed_id)["state"] == ActionState.EXECUTING.value
    assert racing_store.get(expired_id)["state"] == ActionState.EXPIRED.value
