import json
import os

import pytest

APP_URL = os.getenv("APP_URL")
pytestmark = pytest.mark.skipif(not APP_URL, reason="APP_URL is required for browser tests")

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
OWNER_PASSWORD = "meridian-owner-2026"


def _authed_page(browser):
    context = browser.new_context(viewport=DESKTOP_VIEWPORT)
    response = context.request.post(
        f"{APP_URL}/api/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "owner", "password": OWNER_PASSWORD}),
    )
    assert response.status == 200
    return context, context.new_page()



def _chip(scope):
    return scope.locator('[data-workspace-section]:not([hidden]) [data-freshness]')


def _open_workspace(page, name):
    page.goto(f"{APP_URL}/meridian?workspace={name}", wait_until="domcontentloaded")


def _fulfill(payload, status=200):
    body = json.dumps(payload)

    def handler(route):
        route.fulfill(status=status, content_type="application/json", body=body)

    return handler


FRESH = {"status": "fresh", "last_updated_at": "2026-08-27T12:00:00Z"}
STALE = {"status": "stale", "last_updated_at": "2026-08-25T12:00:00Z"}


def _today_payload(freshness=FRESH):
    return {
        "total_cash": {"amount": 1500.0, "currency": "USD", "by_currency": {"USD": 1500.0}},
        "safe_to_spend": {
            "amount": None,
            "status": "unavailable",
            "inputs": {
                "available_cash": {
                    "amount": 1234.56,
                    "currency": "USD",
                    "by_currency": {"USD": 1234.56},
                },
                "known_obligations": None,
                "reason": "Commitments are not yet available in the normalized graph.",
            },
        },
        "upcoming_events": [],
        "forecast": None,
        "data_freshness": freshness,
    }


def _activity_payload(transactions, next_cursor=None, freshness=STALE):
    return {
        "transactions": [
            {
                "id": row[0],
                "account_id": 11,
                "provider": "crew",
                "amount": row[1],
                "currency": "USD",
                "occurred_at": row[2],
                "posted_at": None,
                "description": row[3],
                "merchant": row[4],
                "status": "posted",
                "source_updated_at": row[2],
                "synced_at": "2026-08-26T10:00:00Z",
            }
            for row in transactions
        ],
        "next_cursor": next_cursor,
        "data_freshness": freshness,
    }


def test_today_renders_dominant_explanation_and_freshness():
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        page.route("**/api/meridian/today", _fulfill(_today_payload()))
        _open_workspace(page, "today")

        root = page.locator("[data-today-root]")
        assert root.is_visible()

        figure = page.locator("[data-sts-figure]")
        assert figure.inner_text() != ""
        note = page.locator("[data-sts-note]")
        assert note.is_visible()
        assert "unavailable" in note.inner_text().lower()

        inputs = page.locator("[data-today-inputs] [data-input]")
        assert inputs.count() >= 1
        assert "1,234.56" in inputs.nth(0).inner_text()

        reasons = page.locator("[data-today-reason]")
        assert reasons.count() == 1
        assert "Commitments" in reasons.inner_text()

        chip = _chip(page)
        assert "fresh" in chip.get_attribute("data-state")
        assert chip.inner_text() != ""

        upcoming_empty = page.locator("[data-upcoming-empty]")
        assert upcoming_empty.is_visible()
        browser.close()


def test_today_marks_stale_data():
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        page.route(
            "**/api/meridian/today", _fulfill(_today_payload(freshness=STALE))
        )
        _open_workspace(page, "today")

        chip = _chip(page)
        assert chip.get_attribute("data-state") == "stale"
        assert "tale" in chip.inner_text()  # Stale/stale without pinning a locale
        browser.close()


def test_activity_groups_by_local_date_with_signed_amounts():
    pytest.importorskip("playwright.sync_api")
    transactions = [
        (101, -3.0, "2026-08-20T18:00:00Z", "Coffee", "Blue Bottle"),
        (102, 2500.0, "2026-08-20T18:00:00Z", "Paycheck deposit", "Employer"),
        (99, -42.5, "2026-08-17T09:30:00Z", "Groceries", "Market"),
    ]
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        page.route(
            "**/api/meridian/activity*",
            _fulfill(_activity_payload(transactions, freshness=FRESH)),
        )
        _open_workspace(page, "activity")

        root = page.locator("[data-activity-root]")
        assert root.is_visible()

        groups = page.locator("[data-day-group]")
        assert groups.count() == 2

        first_group_rows = groups.nth(0).locator("[data-transaction-row]")
        assert first_group_rows.count() == 2

        spend_row = page.locator('[data-transaction-row][data-kind="spend"]')
        income_row = page.locator('[data-transaction-row][data-kind="income"]')
        assert spend_row.count() == 2
        assert income_row.count() == 1
        assert "3.00" in spend_row.first.inner_text()
        assert "2,500.00" in income_row.first.inner_text()

        descriptions = page.locator("[data-row-description]")
        assert "Blue Bottle" in descriptions.nth(0).inner_text()

        chip = _chip(page)
        assert chip.get_attribute("data-state") == "fresh"

        load_more = page.locator("[data-load-more]")
        assert load_more.is_hidden()
        assert page.locator("[data-activity-empty]").is_hidden()
        browser.close()


def test_activity_load_more_appends_without_disturbing_existing_rows():
    pytest.importorskip("playwright.sync_api")
    page_one = _activity_payload(
        [(201, -8.0, "2026-08-21T15:00:00Z", "Lunch", "Deli"), ],
        next_cursor="CURSOR-1",
        freshness=STALE,
    )
    page_two = _activity_payload(
        [(105, -60.0, "2026-08-01T20:00:00Z", "Utilities", "Power Co.")],
        next_cursor=None,
        freshness=STALE,
    )
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)

        calls = {"count": 0}

        def route_handler(route):
            url = route.request.url
            if "cursor=CURSOR-1" in url:
                route.fulfill(
                    status=200, content_type="application/json", body=json.dumps(page_two)
                )
            else:
                calls["count"] += 1
                route.fulfill(
                    status=200, content_type="application/json", body=json.dumps(page_one)
                )

        page.route("**/api/meridian/activity*", route_handler)
        _open_workspace(page, "activity")

        existing = page.locator("[data-ledger] [data-transaction-row]")
        assert existing.count() == 1
        first_row_id = existing.first.get_attribute("data-transaction-id")

        load_more = page.locator("[data-load-more]")
        assert load_more.is_visible()
        load_more.click()
        page.wait_for_timeout(200)

        rows_after = page.locator("[data-ledger] [data-transaction-row]")
        assert rows_after.count() == 2
        assert rows_after.first.get_attribute("data-transaction-id") == first_row_id
        assert load_more.is_hidden()
        assert calls["count"] == 1
        browser.close()


def test_activity_shows_empty_state_and_preserves_layout():
    pytest.importorskip("playwright.sync_api")
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        page.route(
            "**/api/meridian/activity*",
            _fulfill(_activity_payload([], freshness=STALE)),
        )
        _open_workspace(page, "activity")

        assert page.locator("[data-activity-empty]").is_visible()
        assert page.locator("[data-ledger]").is_visible()
        assert page.locator("[data-load-more]").is_hidden()
        main = page.locator("main#main")
        assert main.is_visible()
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0
        browser.close()


def test_activity_error_state_is_explicit_and_layout_survives():
    pytest.importorskip("playwright.sync_api")
    error_payload = {
        "error": {
            "code": "financial_data_unavailable",
            "message": "Financial data is temporarily unavailable.",
            "recovery_action": "Try again after your provider reconnects.",
        }
    }
    with pytest.importorskip("playwright.sync_api").sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        page.route(
            "**/api/meridian/activity*", _fulfill(error_payload, status=503)
        )
        _open_workspace(page, "activity")

        alert = page.locator("[data-activity-error]")
        assert alert.is_visible()
        combined = alert.inner_text()
        assert "temporarily unavailable" in combined
        assert "provider reconnects" in combined
        assert page.locator("main#main").is_visible()
        browser.close()
