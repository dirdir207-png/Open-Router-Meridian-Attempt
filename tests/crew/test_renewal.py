import json
import time

from crew.renewal import CapturerUnavailable, GuidedRenewalService, RenewalStatus


class FakeCapturer:
    def __init__(self, token="Bearer fresh-captured-token", delay=0.0, error=None):
        self._token = token
        self._delay = delay
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def capture(self, timeout_seconds):
        if self._error:
            raise self._error
        time.sleep(self._delay)
        return self._token


def wait_for_status(service, session_id, target, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = service.status(session_id)
        if payload and payload["status"] == target.value:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"never reached {target}; last={payload}")


def build_service(capturer=None, storer_calls=None, health=None, timeout_seconds=5.0, factory_error=None):
    storer_calls = storer_calls if storer_calls is not None else []

    def factory():
        if factory_error:
            raise factory_error
        return capturer or FakeCapturer()

    service = GuidedRenewalService(
        factory,
        storer=lambda value: storer_calls.append(value),
        health_checker=(health or (lambda: None)),
        timeout_seconds=timeout_seconds,
    )
    return service, storer_calls


def test_happy_path_captures_stores_and_reports_health():
    calls = []

    def health():
        from crew.health import CrewHealth, CrewHealthState
        return CrewHealth(CrewHealthState.HEALTHY, "Crew connection is healthy")

    service, stored = build_service(
        capturer=FakeCapturer(token=" Bearer abc.def "),
        storer_calls=calls,
        health=health,
    )
    started = service.start()
    assert "session_id" in started
    payload = wait_for_status(service, started["session_id"], RenewalStatus.CAPTURED)
    assert stored == [" Bearer abc.def "]
    assert payload["health"]["state"] == "healthy"
    body = json.dumps(payload) + repr(service)
    assert "abc.def" not in body


def test_missing_capture_fails_without_storing():
    service, stored = build_service(capturer=FakeCapturer(token=None))
    started = service.start()
    payload = wait_for_status(service, started["session_id"], RenewalStatus.FAILED)
    assert stored == []
    assert payload["status"] == "failed"


def test_unavailable_capturer_fails_with_guidance():
    service, stored = build_service(factory_error=CapturerUnavailable("renewal helper not installed"))
    started = service.start()
    payload = wait_for_status(service, started["session_id"], RenewalStatus.FAILED)
    assert stored == []
    assert "not installed" in payload["message"]


def test_timeout_expires_and_discards_late_capture():
    service, stored = build_service(
        capturer=FakeCapturer(token="late-token", delay=1.0),
        timeout_seconds=0.15,
    )
    started = service.start()
    wait_for_status(service, started["session_id"], RenewalStatus.EXPIRED)
    assert stored == []
    assert "late-token" not in repr(service)


def test_second_start_rejected_while_session_active():
    service, _ = build_service(capturer=FakeCapturer(delay=0.5))
    first = service.start()
    second = service.start()
    assert "error" in second
    assert second["session_id"] == first["session_id"]
    wait_for_status(service, first["session_id"], RenewalStatus.CAPTURED)


def test_unknown_session_id_returns_none():
    service, _ = build_service()
    assert service.status("no-such-session") is None


def test_waiting_sessions_expire_on_status_check():
    service, stored = build_service(
        capturer=FakeCapturer(token="never-seen", delay=10.0),
        timeout_seconds=0.1,
    )
    started = service.start()
    deadline = time.monotonic() + 2.0
    payload = None
    while time.monotonic() < deadline:
        payload = service.status(started["session_id"])
        if payload["status"] == RenewalStatus.EXPIRED.value:
            break
        time.sleep(0.02)
    assert payload and payload["status"] == "expired"
    assert stored == []


def test_new_start_allowed_after_previous_finishes():
    service, _ = build_service()
    first = service.start()
    wait_for_status(service, first["session_id"], RenewalStatus.CAPTURED)
    second = service.start()
    assert "session_id" in second
    wait_for_status(service, second["session_id"], RenewalStatus.CAPTURED)
