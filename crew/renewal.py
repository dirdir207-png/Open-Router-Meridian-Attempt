"""Guided Crew credential renewal lifecycle.

Owns single-flight renewal sessions: launch a capturer, wait for the user to
authenticate interactively, capture the credential server-side, store it via
the existing path, then re-check health. Credential values never appear in
status payloads, logs, or repr() output.
"""

import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional


class CapturerUnavailable(RuntimeError):
    """Raised when the local browser-capture helper cannot run."""


class RenewalStatus(str, Enum):
    PENDING = "pending"
    WAITING_FOR_USER = "waiting_for_user"
    CAPTURED = "captured"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class _Session:
    id: str
    status: RenewalStatus
    message: str = ""
    deadline: float = 0.0
    done: bool = False
    health: Any = None


def _sanitize_health(health: Any) -> Optional[Dict[str, str]]:
    if isinstance(health, dict):
        state = health.get("state")
        message = health.get("message")
        state = getattr(state, "value", state)
    else:
        state = getattr(getattr(health, "state", None), "value", None)
        message = getattr(health, "message", None)
    if state is None and message is None:
        return None
    return {"state": state or "", "message": message or ""}


ALLOWED_STATUS_FIELDS = ("status", "message")


def sanitize_status_payload(payload: Any) -> Dict[str, Any]:
    """Whitelist a renewal status payload; credential material cannot pass."""
    if not isinstance(payload, dict):
        return {}
    sanitized: Dict[str, Any] = {key: payload[key] for key in ALLOWED_STATUS_FIELDS if key in payload}
    if "health" in payload:
        sanitized_health = _sanitize_health(payload.get("health"))
        if sanitized_health:
            sanitized["health"] = sanitized_health
    return sanitized


class GuidedRenewalService:
    def __init__(
        self,
        capturer_factory: Callable[[], Any],
        storer: Callable[[str], None],
        health_checker: Optional[Callable[[], Any]] = None,
        timeout_seconds: float = 300.0,
    ):
        self._capturer_factory = capturer_factory
        self._storer = storer
        self._health_checker = health_checker
        self._timeout_seconds = float(timeout_seconds)
        self._lock = threading.Lock()
        self._sessions: Dict[str, _Session] = {}

    def __repr__(self) -> str:
        return "GuidedRenewalService()"

    def start(self) -> Dict[str, str]:
        with self._lock:
            for session in self._sessions.values():
                if not session.done:
                    return {
                        "error": "A renewal session is already running",
                        "session_id": session.id,
                    }
            session_id = uuid.uuid4().hex
            self._sessions[session_id] = _Session(
                id=session_id,
                status=RenewalStatus.PENDING,
                message="Starting renewal browser",
                deadline=time.monotonic() + self._timeout_seconds,
            )
        threading.Thread(target=self._run, args=(session_id,), daemon=True).start()
        return {"session_id": session_id}

    def status(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if (
                session.status is RenewalStatus.WAITING_FOR_USER
                and time.monotonic() > session.deadline
            ):
                session.status = RenewalStatus.EXPIRED
                session.message = "Renewal window timed out; start again"
                session.done = True
            payload: Dict[str, Any] = {
                "status": session.status.value,
                "message": session.message,
            }
            if session.health is not None:
                sanitized = _sanitize_health(session.health)
                if sanitized:
                    payload["health"] = sanitized
            return sanitize_status_payload(payload)

    def active_session_id(self) -> Optional[str]:
        with self._lock:
            for session in self._sessions.values():
                if not session.done:
                    return session.id
            return None

    def _finish(self, session: _Session, status: RenewalStatus, message: str, health: Any = None) -> None:
        with self._lock:
            if session.done and session.status is not RenewalStatus.EXPIRED:
                return
            session.status = status
            session.message = message
            session.health = health
            session.done = True

    def _run(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.status = RenewalStatus.WAITING_FOR_USER
            session.message = "Complete login in the opened window"

        try:
            capturer = self._capturer_factory()
        except Exception as exc:
            message = str(exc) or "Local renewal helper is unavailable"
            self._finish(session, RenewalStatus.FAILED, message)
            return

        captured_value: Optional[str] = None
        try:
            with capturer as context:
                captured_value = context.capture(timeout_seconds=self._timeout_seconds)
        except Exception as exc:
            message = str(exc) or "Credential capture failed"
            self._finish(session, RenewalStatus.FAILED, message)
            return

        expired = time.monotonic() > session.deadline
        if expired:
            self._finish(session, RenewalStatus.EXPIRED, "Renewal window timed out; start again")
            return

        if not captured_value or not str(captured_value).strip():
            self._finish(session, RenewalStatus.FAILED, "No Crew credential was captured")
            return

        try:
            self._storer(str(captured_value))
        except Exception:
            self._finish(session, RenewalStatus.FAILED, "Captured credential could not be stored")
            return

        health = None
        try:
            if self._health_checker:
                health = self._health_checker()
        except Exception:
            health = None

        self._finish(
            session,
            RenewalStatus.CAPTURED,
            "Crew credential renewed",
            health=health,
        )
