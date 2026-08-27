"""Durable action-proposal pipeline: propose → approve → execute → verify.

The foundation for AI-initiated work. Proposers (human or AI) can only create
requests for whitelisted action types; only explicit approval lets an executor
run; every transition is recorded. Executors and verifiers are registered
separately (see executors.py) — this module owns state, nothing else.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class UnknownActionTypeError(ValueError):
    pass


class IllegalTransitionError(RuntimeError):
    pass


class ActionState(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


_TERMINAL_STATES = {ActionState.REJECTED, ActionState.EXPIRED, ActionState.VERIFIED, ActionState.FAILED}

# from-state -> allowed target states with the column to stamp on success
_TRANSITIONS = {
    ActionState.PROPOSED: {ActionState.APPROVED, ActionState.REJECTED},
    ActionState.APPROVED: {ActionState.EXECUTING, ActionState.EXPIRED},
    ActionState.EXECUTING: {ActionState.EXECUTED, ActionState.FAILED},
    ActionState.EXECUTED: {ActionState.VERIFIED, ActionState.FAILED},
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_requests (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    params_json TEXT NOT NULL,
    rationale TEXT,
    requested_by TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT,
    execution_key TEXT,
    execution_started_at TEXT,
    executed_at TEXT,
    result_json TEXT,
    verification_json TEXT
)
"""

_SELECT_COLUMNS = (
    "id, type, params_json, rationale, requested_by, state, created_at, "
    "decided_by, decided_at, execution_key, execution_started_at, executed_at, "
    "result_json, verification_json"
)

_EXECUTION_COLUMNS = {
    "execution_key": "TEXT",
    "execution_started_at": "TEXT",
}

# Added so repeated proposers (e.g. funding schedules) can be idempotent.
_DEDUP_COLUMN = ("dedup_key", "TEXT")


def _now() -> str:
    return datetime.now().isoformat()


class ActionStore:
    def __init__(self, db_path: str, allowed_types: Tuple[str, ...]):
        self._db_path = db_path
        self._allowed_types = frozenset(allowed_types)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(action_requests)")}
            for column, column_type in (*_EXECUTION_COLUMNS.items(), _DEDUP_COLUMN):
                if column not in columns:
                    conn.execute(f"ALTER TABLE action_requests ADD COLUMN {column} {column_type}")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_action_requests_dedup_key "
                "ON action_requests (dedup_key) WHERE dedup_key IS NOT NULL"
            )

    def __repr__(self) -> str:
        return "ActionStore()"

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def propose(
        self,
        action_type: str,
        params: Dict[str, Any],
        rationale: str,
        requested_by: str,
        dedup_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        if action_type not in self._allowed_types:
            raise UnknownActionTypeError(f"Action type is not permitted: {action_type}")
        if dedup_key is not None:
            existing = self.get_by_dedup_key(dedup_key)
            if existing is not None:
                return existing
        request_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if dedup_key is not None:
                existing_row = conn.execute(
                    "SELECT id FROM action_requests WHERE dedup_key = ?",
                    (dedup_key,),
                ).fetchone()
                if existing_row is not None:
                    return self.get(existing_row[0])
            conn.execute(
                "INSERT INTO action_requests (id, type, params_json, rationale, requested_by, state, created_at, dedup_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    action_type,
                    json.dumps(params or {}),
                    rationale or "",
                    requested_by,
                    ActionState.PROPOSED.value,
                    _now(),
                    dedup_key,
                ),
            )
        return self.get(request_id)

    def get_by_dedup_key(self, dedup_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM action_requests WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM action_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_pending(self) -> list:
        return self.list_by_state(ActionState.PROPOSED)

    def list_by_state(self, state: ActionState) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM action_requests "
                "WHERE state = ? ORDER BY created_at DESC",
                (state.value,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]


    def approve(self, request_id: str, decided_by: str) -> Dict[str, Any]:
        return self._transition(request_id, ActionState.APPROVED, decided_by=decided_by)

    def reject(self, request_id: str, decided_by: str) -> Dict[str, Any]:
        return self._transition(request_id, ActionState.REJECTED, decided_by=decided_by)

    def expire(self, request_id: str) -> Dict[str, Any]:
        return self._transition(request_id, ActionState.EXPIRED)

    def claim_for_execution(self, request_id: str, execution_key: str) -> Dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                "UPDATE action_requests SET state=?, execution_key=?, execution_started_at=? "
                "WHERE id=? AND state=?",
                ("executing", execution_key, _now(), request_id, "approved"),
            )
            if updated.rowcount != 1:
                raise IllegalTransitionError("Action is not available for execution")
            row = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM action_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        assert row is not None
        return self._row_to_dict(row)

    def mark_executed(self, request_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        return self._transition(request_id, ActionState.EXECUTED, payload_json=json.dumps(result or {}))

    def mark_verified(self, request_id: str, verification: Dict[str, Any]) -> Dict[str, Any]:
        return self._transition(request_id, ActionState.VERIFIED, verification_json=json.dumps(verification or {}))

    def mark_failed(self, request_id: str, error: Dict[str, Any]) -> Dict[str, Any]:
        return self._transition(request_id, ActionState.FAILED, payload_json=json.dumps(error or {}))

    def _transition(
        self,
        request_id: str,
        target: ActionState,
        decided_by: Optional[str] = None,
        payload_json: Optional[str] = None,
        verification_json: Optional[str] = None,
    ) -> Dict[str, Any]:
        current = self.get(request_id)
        if not current:
            raise IllegalTransitionError("Unknown action request")
        try:
            from_state = ActionState(current["state"])
        except ValueError:
            raise IllegalTransitionError("Corrupt action state")
        if target not in _TRANSITIONS.get(from_state, set()):
            raise IllegalTransitionError(f"Cannot move action from {from_state.value} to {target.value}")

        assignments = ["state = ?"]
        values: list = [target.value]
        if decided_by is not None:
            assignments += ["decided_by = ?", "decided_at = ?"]
            values += [decided_by, _now()]
        if target in (ActionState.EXECUTED, ActionState.FAILED):
            assignments.append("executed_at = ?")
            values.append(_now())
        if payload_json is not None:
            assignments.append("result_json = ?")
            values.append(payload_json)
        if verification_json is not None:
            assignments.append("verification_json = ?")
            values.append(verification_json)
        values += [request_id, from_state.value]

        with self._connect() as conn:
            updated = conn.execute(
                f"UPDATE action_requests SET {', '.join(assignments)} WHERE id = ? AND state = ?",
                tuple(values),
            )
            if updated.rowcount != 1:
                raise IllegalTransitionError("Action state changed before transition completed")
            row = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM action_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        assert row is not None
        return self._row_to_dict(row)

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "type": row[1],
            "params": json.loads(row[2] or "{}"),
            "rationale": row[3],
            "requested_by": row[4],
            "state": row[5],
            "created_at": row[6],
            "decided_by": row[7],
            "decided_at": row[8],
            "execution_key": row[9],
            "execution_started_at": row[10],
            "executed_at": row[11],
            "result": json.loads(row[12]) if row[12] else None,
            "verification": json.loads(row[13]) if row[13] else None,
        }

    def _list_by_state(self, state: ActionState) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_SELECT_COLUMNS} FROM action_requests "
                "WHERE state = ? ORDER BY created_at DESC",
                (state.value,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]
