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


PLAN_PAYLOAD = {
    "summary": {
        "headline": "2 commitments, 25% funded",
        "commitment_count": 2,
        "total_target": 1080.0,
        "total_funded": 250.0,
        "unfunded": 830.0,
        "coverage_ratio": 0.23,
        "next_due": "2026-10-01",
        "first_shortfall": {
            "date": "2026-09-05",
            "amount": 50.0,
            "cause": "Vacation wanted $150.00 but only $100.00 of cash was available",
        },
    },
    "commitments": [
        {
            "id": 1,
            "type": "goal",
            "name": "Vacation",
            "status": "active",
            "priority": 3,
            "target": 1000.0,
            "funded": 250.0,
            "unfunded": 750.0,
            "due_date": None,
            "target_date": None,
            "backing": {"account_id": 3, "name": "Vacation pocket"},
            "rule_ids": ["1"],
            "projected_30d": 50.0,
            "explanation": ["$250.00 already set aside"],
        },
        {
            "id": 2,
            "type": "bill",
            "name": "Internet",
            "status": "active",
            "priority": 3,
            "target": 80.0,
            "funded": 0.0,
            "unfunded": 80.0,
            "due_date": "2026-10-01",
            "target_date": None,
            "backing": None,
            "rule_ids": [],
            "projected_30d": 0.0,
            "explanation": ["No funding activity yet"],
        },
    ],
    "timeline": {
        "start": "2026-09-01",
        "end": "2026-10-01",
        "events": [
            {
                "date": "2026-09-04",
                "amount": 50.0,
                "commitment": "Vacation",
                "commitment_id": 1,
                "rule_id": "1",
                "source": "paycheck",
                "explanation": [],
            }
        ],
    },
    "allocation": {
        "cash_total": 1500.0,
        "segments": [
            {"label": "Committed to commitments", "amount": 250.0},
            {"label": "Unfunded commitments", "amount": 750.0},
            {"label": "Available", "amount": 500.0},
        ],
    },
    "data_freshness": {"status": "fresh", "last_updated_at": "2026-08-27T12:00:00Z"},
}


def _install_routes(page, plan_payload=PLAN_PAYLOAD):
    page.route("**/api/meridian/plan*", _fulfill(plan_payload))


def test_plan_renders_command_timeline_and_allocation():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        _install_routes(page)
        page.goto(f"{APP_URL}/meridian?workspace=plan", wait_until="domcontentloaded")
        page.wait_for_timeout(250)

        root = page.locator("[data-plan-root]")
        assert root.is_visible()
        assert "2 commitments" in page.locator("[data-plan-headline]").inner_text()
        assert "%" in page.locator("[data-coverage-text]").inner_text()
        assert page.locator("[data-plan-total]").inner_text() != "—"
        assert page.locator("[data-plan-shortfall]").is_visible()

        timeline_rows = page.locator("[data-timeline] li")
        assert timeline_rows.count() == 1
        assert "Vacation" in timeline_rows.nth(0).inner_text()

        legend_items = page.locator("[data-allocation-legend] li")
        assert legend_items.count() == 3

        cards = page.locator("[data-commitment-card]")
        assert cards.count() == 2
        assert "backed by Vacation pocket" in cards.nth(0).inner_text()
        browser.close()


def test_funding_editor_saves_changes_as_a_proposal():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser)
        _install_routes(page)

        proposals = []

        def capture(route):
            proposals.append(json.loads(route.request.post_data))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"proposal": {"id": "abc123"}}),
            )

        page.route("**/api/meridian/funding-rules/propose", capture)
        page.goto(f"{APP_URL}/meridian?workspace=plan", wait_until="domcontentloaded")
        page.wait_for_timeout(250)

        card = page.locator('[data-commitment-card="1"]')
        card.get_by_role("button", name="Edit funding").click()

        editor = card.locator("[data-funding-editor]")
        assert editor.is_visible()
        assert "Fixed per paycheck" in editor.inner_text()

        editor.locator('input[name="amount"]').fill("75")
        assert "75" in editor.locator("[data-editor-preview]").inner_text()

        editor.get_by_role("button", name="Save as proposal").click()
        page.wait_for_timeout(200)

        assert len(proposals) == 1
        assert proposals[0]["commitment_id"] == 1
        assert proposals[0]["rule"]["kind"] == "fixed_per_paycheck"
        assert proposals[0]["rule"]["amount"] == 75
        assert "Pending Actions" in editor.locator("[data-editor-note]").inner_text()
        browser.close()


def test_plan_is_reachable_and_readable_on_mobile():
    playwright_api = pytest.importorskip("playwright.sync_api")
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = _authed_page(browser, MOBILE_VIEWPORT)
        _install_routes(page)
        page.goto(f"{APP_URL}/meridian?workspace=plan", wait_until="domcontentloaded")
        page.wait_for_timeout(250)

        assert page.locator("[data-plan-root]").is_visible()
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0
        assert page.locator("[data-plan-shortfall]").is_visible()
        browser.close()
