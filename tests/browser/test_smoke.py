import os

import pytest

APP_URL = os.getenv("APP_URL")
pytestmark = pytest.mark.skipif(not APP_URL, reason="APP_URL is required for browser smoke tests")


def test_login_page_loads_without_werkzeug_debugger():
    playwright = pytest.importorskip("playwright.sync_api")

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        page = browser.new_page()
        response = page.goto(f"{APP_URL}/login", wait_until="networkidle")

        assert response is not None
        assert response.status == 200
        assert "Werkzeug Debugger" not in page.locator("body").inner_text()

        browser.close()
