"""Executor registry for approved actions.

Each whitelisted action type maps to one vetted function (wrapped as a
params-dict adapter) plus a verifier that confirms the outcome after
execution. Executors inherit the safety semantics of the functions they wrap
(e.g., move_money's no-retry / uncertain-write contract).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .actions import ActionState, ActionStore, IllegalTransitionError


@dataclass(frozen=True)
class ExecutorSpec:
    execute: Callable[[Dict[str, Any]], Dict[str, Any]]
    verifier: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None

    def __repr__(self) -> str:
        return "ExecutorSpec()"


def _failure(payload: Dict[str, Any], error: str, code: str) -> Dict[str, Any]:
    payload.setdefault("error", error)
    payload.setdefault("error_code", code)
    return payload


def execute_approved_action(
    store: ActionStore,
    request_id: str,
    executors: Dict[str, ExecutorSpec],
    execution_key: Optional[str] = None,
) -> Dict[str, Any]:
    request = store.claim_for_execution(request_id, execution_key or uuid.uuid4().hex)

    spec = executors.get(request["type"])
    if spec is None:
        return store.mark_failed(
            request_id,
            _failure({}, f"No executor registered for action type '{request['type']}'", "no_executor"),
        )

    try:
        result = spec.execute(request.get("params") or {})
    except Exception as exc:
        return store.mark_failed(
            request_id,
            _failure(
                {"verify_state": True},
                str(exc) or "Executor raised an exception",
                "executor_exception",
            ),
        )

    if not isinstance(result, dict) or not result.get("success"):
        payload = result if isinstance(result, dict) else {}
        return store.mark_failed(
            request_id,
            _failure(payload, "Action did not complete successfully", "action_failed"),
        )

    store.mark_executed(request_id, result=result)

    try:
        verification = (
            spec.verifier(request["params"] or {}, result)
            if spec.verifier
            else {"ok": True}
        )
        ok = bool(verification.get("ok"))
    except Exception as exc:
        return store.mark_failed(
            request_id,
            _failure(
                {"verification": {"ok": False}},
                f"Verification raised: {exc}" if str(exc) else "Verification raised",
                "verifier_exception",
            ),
        )

    if not ok:
        return store.mark_failed(
            request_id,
            _failure(
                {"verification": verification},
                "Post-execution verification failed",
                "verification_failed",
            ),
        )

    return store.mark_verified(request_id, verification=verification)


def expire_stale_approvals(
    store: ActionStore,
    ttl_seconds: float,
    now: Optional[datetime] = None,
) -> List[str]:
    """Expire APPROVED actions older than ttl; returns expired ids."""
    reference = now or datetime.now()
    expired_ids: List[str] = []
    for request in store.list_by_state(ActionState.APPROVED):
        decided_at = request.get("decided_at")
        if not decided_at:
            continue
        try:
            age = (reference - datetime.fromisoformat(decided_at)).total_seconds()
        except ValueError:
            continue
        if age >= ttl_seconds:
            try:
                store.expire(request["id"])
            except IllegalTransitionError:
                continue
            expired_ids.append(request["id"])
    return expired_ids
