import json
import os

import pytest

APP_URL = os.getenv("APP_URL")
pytestmark = pytest.mark.skipif(not APP_URL, reason="APP_URL is required for browser tests")

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}
OWNER_PASSWORD = "meridian-owner-2026"


def _authed_page(browser, viewport=DESKTOP_VIEWPORT):
    from tests.browser.conftest import ensure_owner

    ensure_owner()
    context = browser.new_context(viewport=viewport)
    response = context.request.post(
        f"{APP_URL}/api/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "owner", "password": OWNER_PASSWORD}),
    )
    assert response.status == 200
    return context, context.new_page()


def _fulfill(payload, status=200):
    body = json.dumps(payload)

    def handler(route):
        route.fulfill(status=status, content_type="application/json", body=body)

    return handler


ACTIVITY_PAYLOAD = {
    "transactions": [
        {
            "id": 101,
            "account_id": 11,
            "provider": "crew",
            "amount": -3.0,
            "currency": "USD",
            "occurred_at": "2026-08-20T18:00:00Z",
            "posted_at": None,
            "description": "Coffee",
            "merchant": "Blue Bottle",
            "status": "posted",
            "source_updated_at": "2026-08-20T18:05:00Z",
            "synced_at": "2026-08-26T10:00:00Z",
        }
    ],
    "next_cursor": None,
    "data_freshness": {"status": "fresh", "last_updated_at": "2026-08-27T12:00:00Z"},
}

TRANSACTION_DETAIL_PAYLOAD = {
    "transaction": ACTIVITY_PAYLOAD["transactions"][0],
    "data_freshness": {"status": "fresh", "last_updated_at": "2026-08-27T12:00:00Z"},
}


def _install_routes(page):
    page.route("**/api/meridian/activity*", _fulfill(ACTIVITY_PAYLOAD))
    page.route("**/api/meridian/transactions/*", _fulfill(TRANSACTION_DETAIL_PAYLOAD))
    page.route(
        "**/api/meridian/accounts",
        _fulfill(
            {
                "accounts": [
                    {
                        "id": 11,
                        "provider": "crew",
                        "name": "Checking",
                        "account_type": "checking",
                        "balance": 100.0,
                        "available_balance": None,
                        "currency": "USD",
                        "is_active": True,
                        "source_updated_at": "2026-08-27T12:00:00Z",
                        "synced_at": "2026-08-27T12:00:00Z",
                    }
                ],
                "data_freshness": {
                    "status": "fresh",
                    "last_updated_at": "2026-08-27T12:00:00Z",
                },
            }
        ),
    )


def test_inspector_shows_complete_detail_context():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        _install_routes(page)
        page.goto(f"{APP_URL}/meridian?workspace=activity", wait_until="domcontentloaded")
        page.locator('[data-transaction-id="101"]').click()
        page.wait_for_timeout(200)

        panel = page.locator("[data-inspector-rail]")
        assert panel.is_visible()

        facts = {
            row.get_attribute("data-fact"): row.inner_text()
            for row in page.locator("[data-fact]").all()
        }
        assert "Blue Bottle" in facts["merchant"]
        assert "Coffee" in facts["description"]
        assert "3.00" in facts["amount"]
        assert "$" in facts["amount"]
        assert "2026" in facts["date"]
        assert "Posted" in facts["status"].title() or "posted" in facts["status"]
        assert "Checking" in facts["account"]

        assert "Unassigned" in page.locator("[data-category-state]").inner_text()
        assert (
            "No linked commitment"
            in page.locator("[data-commitment-state]").inner_text()
        )
        assert (
            "No recurrence detected"
            in page.locator("[data-recurrence-state]").inner_text()
        )
        assert (
            "No related transfers" in page.locator("[data-transfers-state]").inner_text()
        )
        assert page.locator("[data-inspector-provider]").inner_text().lower().startswith(
            "crew"
        )

        chip = panel.locator("[data-freshness]")
        assert chip.get_attribute("data-state") == "fresh"

        advisor_meta = page.locator(
            '[data-advisor-context][data-object-id="101"]'
        )
        assert advisor_meta.count() == 1
        assert advisor_meta.get_attribute("data-advisor-context") == "transaction"
        browser.close()


def test_escape_and_close_button_restore_focus_to_the_opening_row():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        _install_routes(page)
        page.goto(f"{APP_URL}/meridian?workspace=activity", wait_until="domcontentloaded")

        row = page.locator('[data-transaction-id="101"]')
        row.click()
        page.wait_for_timeout(150)
        assert page.locator("[data-inspector-close]").is_visible()

        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        assert not page.locator("[data-inspector-rail]").is_visible()

        # Reopen, then close via the button.
        row.click()
        page.wait_for_timeout(150)
        page.locator("[data-inspector-close]").click()
        page.wait_for_timeout(150)
        assert not page.locator("[data-inspector-rail]").is_visible()

        active_id = page.evaluate("document.activeElement && document.activeElement.dataset.transactionId || null")
        assert active_id == "101"
        assert "transaction=101" not in page.url
        browser.close()


def test_transaction_selection_is_url_addressable():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        _install_routes(page)
        page.goto(
            f"{APP_URL}/meridian?workspace=activity&transaction=101",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(250)

        assert page.locator("[data-inspector-rail]").is_visible()
        assert "transaction=101" in page.url
        assert "workspace=activity" in page.url

        # Activity filters survive the selection.
        assert page.locator("[data-ledger] [data-transaction-row]").count() == 1
        browser.close()


def test_mobile_inspector_is_full_screen():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser, MOBILE_VIEWPORT)
        _install_routes(page)
        page.goto(f"{APP_URL}/meridian?workspace=activity", wait_until="domcontentloaded")

        page.locator('[data-transaction-id="101"]').click()
        page.wait_for_timeout(250)

        panel = page.locator("[data-inspector-rail]")
        assert panel.is_visible()
        box = panel.bounding_box()
        viewport = page.viewport_size
        assert box["x"] <= 1 and box["y"] <= 1
        assert abs(box["width"] - viewport["width"]) <= 2
        assert abs(box["height"] - viewport["height"]) <= 2
        close_button = page.locator("[data-inspector-close]")
        assert close_button.is_visible()
        assert min(close_button.bounding_box()["width"], close_button.bounding_box()["height"]) >= 44
        browser.close()
