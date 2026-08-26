import pytest

from crew.browser_capture import (
    PlaywrightAuthorizationCapturer,
    _is_crew_api_url,
    create_mac_capturer,
)
from crew.renewal import CapturerUnavailable

try:
    import playwright  # noqa: F401

    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False


def test_crew_api_urls_match_by_host_suffix():
    assert _is_crew_api_url("https://api.trycrew.com/willow/graphql")
    assert _is_crew_api_url("https://api.trycrew.com/")
    assert not _is_crew_api_url("https://app.trycrew.com/login")
    assert not _is_crew_api_url("https://evil.example/api.trycrew.com")
    assert not _is_crew_api_url("not a url")


def test_capture_returns_none_after_timeout_without_browser_events():
    capturer = PlaywrightAuthorizationCapturer()
    start = __import__("time").monotonic()
    assert capturer.capture(timeout_seconds=0.05) is None
    assert __import__("time").monotonic() - start < 2.0


def test_on_request_captures_authorization_from_crew_api_only():
    class FakeRequest:
        def __init__(self, url, headers):
            self.url = url
            self.headers = headers

        def header_value(self, name):
            return self.headers.get(name)

    capturer = PlaywrightAuthorizationCapturer()
    capturer._on_request(FakeRequest("https://app.trycrew.com/session", {"authorization": "Bearer nope"}))
    assert not capturer._captured_event.is_set()
    capturer._on_request(FakeRequest("https://api.trycrew.com/willow/graphql", {"authorization": "Bearer yes"}))
    assert capturer._captured_event.is_set()
    assert capturer.capture(timeout_seconds=0.1) == "Bearer yes"


@pytest.mark.skipif(HAS_PLAYWRIGHT, reason="playwright installed; absence path untestable here")
def test_factory_reports_unavailable_with_guidance_when_missing():
    with pytest.raises(CapturerUnavailable) as exc:
        create_mac_capturer()
    assert "playwright" in str(exc.value)
