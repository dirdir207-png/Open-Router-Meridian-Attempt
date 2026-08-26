"""Local browser-based Crew credential capture for guided renewal.

Opens a real Chromium window via Playwright so the user can authenticate
interactively (credentials + OTP stay inside that window), captures the first
outgoing ``authorization`` header sent to the Crew API, and hands the raw
value to the caller. The value must only travel through server-side storage;
never log it or include it in responses.
"""

import threading
from typing import Optional
from urllib.parse import urlparse

from .renewal import CapturerUnavailable

CREW_APP_URL = "https://app.trycrew.com"
CREW_API_HOST_SUFFIX = "api.trycrew.com"

INSTALL_GUIDANCE = (
    "Local renewal helper is not installed on this Mac. Run: "
    "./venv/bin/pip install playwright && ./venv/bin/playwright install chromium"
)


def _is_crew_api_url(url: str, host_suffix: str = CREW_API_HOST_SUFFIX) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == host_suffix or host.endswith("." + host_suffix)


class PlaywrightAuthorizationCapturer:
    """Context-manager capturer compatible with GuidedRenewalService."""

    def __init__(self, app_url: str = CREW_APP_URL, headless: bool = False):
        self._app_url = app_url
        self._headless = headless
        self._captured_header: Optional[str] = None
        self._captured_event = threading.Event()
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "PlaywrightAuthorizationCapturer":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self._headless)
        self._context = self._browser.new_context()
        page = self._context.new_page()
        page.on("request", self._on_request)
        self._context.on("request", self._on_request)
        page.goto(self._app_url)
        return self

    def __exit__(self, *args) -> bool:
        for closer in (
            lambda: self._context.close(),
            lambda: self._browser.close(),
            lambda: self._playwright.stop(),
        ):
            try:
                closer()
            except Exception:
                pass
        self._context = None
        self._browser = None
        self._playwright = None
        return False

    def _on_request(self, request) -> None:
        if self._captured_event.is_set():
            return
        if not _is_crew_api_url(getattr(request, "url", "")):
            return
        header_value = None
        getter = getattr(request, "header_value", None)
        if callable(getter):
            header_value = getter("authorization")
        if not header_value:
            headers = getattr(request, "headers", None) or {}
            header_value = headers.get("authorization")
        if header_value:
            self._captured_header = header_value
            self._captured_event.set()

    def capture(self, timeout_seconds: float) -> Optional[str]:
        """Block until an authorization header is seen or timeout elapses."""
        if not self._captured_event.wait(timeout=float(max(0.0, timeout_seconds))):
            return None
        return self._captured_header


def create_mac_capturer() -> PlaywrightAuthorizationCapturer:
    """Factory for GuidedRenewalService; fails with guidance when uninstalled."""
    try:
        import playwright.sync_api  # noqa: F401
    except Exception as exc:  # pragma: no cover - exercised via absence of dep
        raise CapturerUnavailable(INSTALL_GUIDANCE) from exc
    return PlaywrightAuthorizationCapturer()
