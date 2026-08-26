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
    final = execute_approved_action(store, action_id, make_executors(verifier=verifier))
    assert final["state"] == ActionState.VERIFIED.value
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
    assert calls == []


def test_executor_exception_becomes_normalized_failure(store):
    def broken(params):
        raise RuntimeError("boom")

    action_id = seed_approved_action(store)
    final = execute_approved_action(store, action_id, make_executors(fn=broken))
    assert final["state"] == ActionState.FAILED.value
    assert final["result"]["error_code"] == "executor_exception"


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
