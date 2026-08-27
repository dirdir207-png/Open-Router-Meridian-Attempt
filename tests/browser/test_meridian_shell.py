import os

import pytest

APP_URL = os.getenv("APP_URL")
pytestmark = pytest.mark.skipif(not APP_URL, reason="APP_URL is required for browser tests")

WORKSPACES = ["today", "plan", "activity", "accounts"]
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}
OWNER_PASSWORD = "meridian-owner-2026"


def _setup_module():
    from tests.browser.conftest import ensure_owner

    ensure_owner()


def _shell_page(browser, viewport):
    """Authenticate through the API so tests do not depend on legacy login DOM."""
    import json

    context = browser.new_context(viewport=viewport)
    response = context.request.post(
        f"{APP_URL}/api/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"username": "owner", "password": OWNER_PASSWORD}),
    )
    assert response.status == 200, f"Login failed: {response.status}"
    return context, context.new_page()


def _nav_link(scope, workspace):
    return scope.locator(f'nav[aria-label="Primary"] .m-nav-item[data-workspace="{workspace}"]')


def _workspace_links(scope):
    return scope.locator('nav[aria-label="Primary"] .m-nav-item[data-workspace]')


def _expect_active(page, workspace):
    current = page.locator('[aria-current="page"]')
    assert current.count() == 1
    assert current.first.get_attribute("data-workspace") == workspace
    section = page.locator(f'[data-workspace-section="{workspace}"]')
    assert section.is_visible()


def test_unauthenticated_meridian_request_redirects_to_login():
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        page = browser.new_context(viewport=DESKTOP_VIEWPORT).new_page()
        response = page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")

        assert response is not None
        assert "/login" in page.url
        browser.close()


def test_desktop_shell_renders_rail_canvas_and_inspector():
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, DESKTOP_VIEWPORT)
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")

        assert page.title() != ""
        main = page.locator("main#main")
        assert main.is_visible()

        shell = page.locator("[data-meridian-shell]")
        assert shell.is_visible()
        columns = shell.evaluate(
            "node => getComputedStyle(node).gridTemplateColumns.split(' ')"
        )
        assert len(columns) == 3
        assert int(round(float(columns[0].removesuffix("px")))) == 72
        assert float(columns[1].removesuffix("px")) > 600

        skip_link = page.locator('a[href="#main"].skip-link')
        assert skip_link.count() == 1

        links = _workspace_links(shell)
        assert links.count() == 4
        assert {
            link.get_attribute("data-workspace")
            for link in [links.nth(i) for i in range(links.count())]
        } == set(WORKSPACES)

        _expect_active(page, "today")

        inspector = shell.locator("[data-inspector-rail]")
        assert inspector.count() == 1
        browser.close()


def test_desktop_workspace_navigation_updates_url_and_current_marker():
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, DESKTOP_VIEWPORT)

        for workspace in WORKSPACES:
            page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")
            _nav_link(page, workspace).click()
            page.wait_for_timeout(150)

            assert f"workspace={workspace}" in page.url
            _expect_active(page, workspace)
        browser.close()


def test_mobile_shell_reaches_every_workspace_without_horizontal_overflow():
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, MOBILE_VIEWPORT)
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")

        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0

        nav = page.locator('nav[aria-label="Primary"][data-primary-nav]')
        assert nav.is_visible()
        nav_box = nav.bounding_box()
        viewport_height = page.evaluate("() => window.innerHeight")
        assert nav_box["y"] + nav_box["height"] >= viewport_height - 2

        links = nav.locator(".m-nav-item[data-workspace]")
        assert links.count() == 4
        for index in range(links.count()):
            box = links.nth(index).bounding_box()
            assert box["height"] >= 44, "Workspace dock targets must be at least 44px tall"
            assert box["width"] >= 44, "Workspace dock targets must be at least 44px wide"

        for workspace in WORKSPACES:
            nav.locator(f'.m-nav-item[data-workspace="{workspace}"]').click()
            page.wait_for_timeout(150)
            assert f"workspace={workspace}" in page.url
            _expect_active(page, workspace)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            assert overflow <= 0
        browser.close()


def test_reload_preserves_the_active_workspace_from_the_url():
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, DESKTOP_VIEWPORT)
        page.goto(f"{APP_URL}/meridian?workspace=plan", wait_until="domcontentloaded")

        _expect_active(page, "plan")
        assert not page.locator('[data-workspace-section="today"]').is_visible()
        browser.close()
