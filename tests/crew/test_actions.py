import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from crew.actions import (
    ActionState,
    ActionStore,
    IllegalTransitionError,
    UnknownActionTypeError,
)

ALLOWED_TYPES = ("move_money", "create_pocket")


@pytest.fixture
def store(tmp_path):
    return ActionStore(db_path=str(tmp_path / "actions.db"), allowed_types=ALLOWED_TYPES)


def create_legacy_action_db(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE action_requests (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                params_json TEXT NOT NULL,
                rationale TEXT,
                requested_by TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_by TEXT,
                decided_at TEXT,
                executed_at TEXT,
                result_json TEXT,
                verification_json TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO action_requests "
            "(id, type, params_json, rationale, requested_by, state, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("existing-id", "move_money", '{"amount": 10}', "existing", "owner", "proposed", "2026-08-25"),
        )


def test_propose_creates_pending_request_with_snapshot(store):
    request = store.propose(
        action_type="move_money",
        params={"from": "a-1", "to": "p-2", "amount": 12.34},
        rationale="Top up Rent pocket",
        requested_by="owner",
    )
    assert request["state"] == ActionState.PROPOSED.value
    assert request["type"] == "move_money"
    assert request["params"] == {"from": "a-1", "to": "p-2", "amount": 12.34}
    assert request["rationale"] == "Top up Rent pocket"
    assert request["requested_by"] == "owner"
    assert request["id"]
    assert request["created_at"]


def test_propose_rejects_unknown_action_type(store):
    with pytest.raises(UnknownActionTypeError):
        store.propose(
            action_type="delete_everything",
            params={},
            rationale="nope",
            requested_by="owner",
        )


def test_full_lifecycle_records_actors_and_timestamps(store):
    request = store.propose("move_money", {"amount": 100}, "r", "ai-helper")
    action_id = request["id"]

    approved = store.approve(action_id, decided_by="owner")
    assert approved["state"] == ActionState.APPROVED.value
    assert approved["decided_by"] == "owner"
    assert approved["decided_at"]

    claimed = store.claim_for_execution(action_id, execution_key="execute-once-key")
    assert claimed["state"] == ActionState.EXECUTING.value
    assert claimed["execution_key"] == "execute-once-key"
    assert claimed["execution_started_at"]

    executed = store.mark_executed(action_id, result={"success": True, "result": {"id": "tx-1"}})
    assert executed["state"] == ActionState.EXECUTED.value
    assert executed["result"]["result"]["id"] == "tx-1"

    verified = store.mark_verified(action_id, verification={"checked": "balance", "ok": True})
    assert verified["state"] == ActionState.VERIFIED.value
    assert verified["verification"]["ok"] is True


def test_illegal_transitions_raise(store):
    request = store.propose("move_money", {}, "r", "owner")
    action_id = request["id"]

    with pytest.raises(IllegalTransitionError):
        store.mark_executed(action_id, result={})

    store.approve(action_id, decided_by="owner")
    with pytest.raises(IllegalTransitionError):
        store.approve(action_id, decided_by="owner")
    with pytest.raises(IllegalTransitionError):
        store.reject(action_id, decided_by="owner")

    store.claim_for_execution(action_id, execution_key="execute-once-key")
    with pytest.raises(IllegalTransitionError):
        store.claim_for_execution(action_id, execution_key="different-key")

    store.mark_executed(action_id, result={"success": True})
    with pytest.raises(IllegalTransitionError):
        store.mark_executed(action_id, result={"success": True})


def test_reject_is_terminal(store):
    request = store.propose("move_money", {}, "r", "ai-helper")
    rejected = store.reject(request["id"], decided_by="owner")
    assert rejected["state"] == ActionState.REJECTED.value
    with pytest.raises(IllegalTransitionError):
        store.approve(rejected["id"], decided_by="owner")


def test_expiry_only_from_approved(store):
    request = store.propose("move_money", {}, "r", "owner")
    store.approve(request["id"], decided_by="owner")
    expired = store.expire(request["id"])
    assert expired["state"] == ActionState.EXPIRED.value
    with pytest.raises(IllegalTransitionError):
        store.mark_executed(expired["id"], result={})


def test_stale_expiry_cannot_overwrite_execution_claim(tmp_path):
    db_path = str(tmp_path / "actions.db")
    claim_store = ActionStore(db_path=db_path, allowed_types=ALLOWED_TYPES)
    request = claim_store.propose("move_money", {"amount": 100}, "r", "owner")
    claim_store.approve(request["id"], decided_by="owner")

    approved_read = threading.Event()
    allow_expiry_update = threading.Event()

    class PausingExpiryStore(ActionStore):
        def __init__(self):
            super().__init__(db_path=db_path, allowed_types=ALLOWED_TYPES)
            self._pause_next_get = True

        def get(self, request_id):
            current = super().get(request_id)
            if self._pause_next_get:
                self._pause_next_get = False
                assert current["state"] == ActionState.APPROVED.value
                approved_read.set()
                assert allow_expiry_update.wait(timeout=2)
            return current

    expiry_store = PausingExpiryStore()
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale_expiry = pool.submit(expiry_store.expire, request["id"])
        assert approved_read.wait(timeout=2)
        try:
            claimed = claim_store.claim_for_execution(request["id"], "race-key")
            assert claimed["state"] == ActionState.EXECUTING.value
        finally:
            allow_expiry_update.set()

        with pytest.raises(IllegalTransitionError):
            stale_expiry.result(timeout=2)

    assert claim_store.get(request["id"])["state"] == ActionState.EXECUTING.value
    executed = claim_store.mark_executed(request["id"], {"success": True, "result": {"id": "tx-race"}})
    assert executed["state"] == ActionState.EXECUTED.value
    verified = claim_store.mark_verified(request["id"], {"ok": True})
    assert verified["state"] == ActionState.VERIFIED.value


def test_params_and_result_survive_json_round_trip(store):
    params = {"memo": "Rent & utilities — “October”", "amount_cents": 123456}
    request = store.propose("move_money", params, "r", "owner")
    fetched = store.get(request["id"])
    assert fetched["params"] == params
    assert json.dumps(fetched)  # serializable


def test_existing_store_migrates_execution_claim_columns(tmp_path):
    db_path = tmp_path / "legacy-actions.db"
    create_legacy_action_db(db_path)

    migrated = ActionStore(db_path=str(db_path), allowed_types=ALLOWED_TYPES)
    existing = migrated.get("existing-id")
    assert existing["params"] == {"amount": 10}
    assert existing["execution_key"] is None
    assert existing["execution_started_at"] is None

    request = migrated.propose("move_money", {"amount": 25}, "r", "owner")
    migrated.approve(request["id"], decided_by="owner")
    claimed = migrated.claim_for_execution(request["id"], execution_key="legacy-key")

    assert claimed["state"] == ActionState.EXECUTING.value
    assert claimed["execution_key"] == "legacy-key"
    assert claimed["execution_started_at"]


def test_concurrent_store_initialization_migrates_legacy_schema_once(tmp_path, monkeypatch):
    from crew import actions as actions_module

    db_path = tmp_path / "legacy-actions.db"
    create_legacy_action_db(db_path)
    real_connect = sqlite3.connect
    concurrent_alters = threading.Barrier(2)

    class CoordinatedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if sql.startswith("ALTER TABLE action_requests ADD COLUMN"):
                try:
                    concurrent_alters.wait(timeout=0.5)
                except threading.BrokenBarrierError:
                    pass
            return super().execute(sql, parameters)

    def coordinated_connect(*args, **kwargs):
        return real_connect(*args, factory=CoordinatedConnection, **kwargs)

    monkeypatch.setattr(actions_module.sqlite3, "connect", coordinated_connect)
    start = threading.Barrier(2)

    def initialize_store():
        start.wait()
        return ActionStore(db_path=str(db_path), allowed_types=ALLOWED_TYPES)

    with ThreadPoolExecutor(max_workers=2) as pool:
        stores = list(pool.map(lambda _: initialize_store(), range(2)))

    assert len(stores) == 2
    with real_connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(action_requests)")}
        existing = conn.execute(
            "SELECT params_json, state FROM action_requests WHERE id = ?",
            ("existing-id",),
        ).fetchone()
    assert {"execution_key", "execution_started_at"} <= columns
    assert existing == ('{"amount": 10}', "proposed")
