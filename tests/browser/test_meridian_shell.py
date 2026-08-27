import os

import pytest

APP_URL = os.getenv("APP_URL")
pytestmark = pytest.mark.skipif(not APP_URL, reason="APP_URL is required for browser tests")

WORKSPACES = ["today", "plan", "activity", "accounts"]
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 390, "height": 844}
TABLET_VIEWPORT = {"width": 1024, "height": 768}
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


def _document_overflow(page):
    return page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


def _wait_for_shell(page):
    page.wait_for_function("() => Boolean(window.MeridianShell)")


def _contrast_ratio(page):
    return page.evaluate(
        """() => {
          const resolvedColor = (token) => {
            const probe = document.createElement("span");
            probe.style.color = `var(${token})`;
            document.body.append(probe);
            const color = getComputedStyle(probe).color;
            probe.remove();
            return color;
          };
          const channels = (value) => value.match(/\\d+(?:\\.\\d+)?/g).slice(0, 3).map(Number);
          const luminance = (value) => channels(value).map((channel) => {
            const normalized = channel / 255;
            return normalized <= 0.04045
              ? normalized / 12.92
              : ((normalized + 0.055) / 1.055) ** 2.4;
          }).reduce((total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index], 0);
          const foreground = luminance(resolvedColor("--m-ink-faint"));
          const background = luminance(resolvedColor("--m-surface"));
          return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
        }"""
    )


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


def test_keyboard_workspace_change_moves_focus_and_announces_the_new_workspace():
    """Fails if a user-triggered SPA transition leaves focus on the old nav link."""
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, DESKTOP_VIEWPORT)
        page.emulate_media(reduced_motion="reduce")
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")
        _wait_for_shell(page)

        plan_link = _nav_link(page, "plan")
        plan_link.focus()
        page.keyboard.press("Enter")

        _expect_active(page, "plan")
        assert page.evaluate("() => document.activeElement.id") == "workspace-heading-plan"
        assert page.locator("[data-workspace-announcement]").inner_text() == "Plan workspace"
        assert page.locator('[data-workspace-section="plan"]').evaluate(
            "node => getComputedStyle(node).animationName"
        ) == "none"
        browser.close()


def test_modal_sheet_preserves_inert_until_the_final_close_and_restores_focus():
    """Fails if closing one nested modal re-enables the page or strands opener focus."""
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, DESKTOP_VIEWPORT)
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")
        _wait_for_shell(page)

        state = page.evaluate(
            """() => {
              const addSheet = (id) => {
                const sheet = document.createElement("aside");
                sheet.id = id;
                sheet.hidden = true;
                const close = document.createElement("button");
                close.type = "button";
                close.dataset.sheetInitialFocus = "";
                close.textContent = "Close";
                sheet.append(close);
                document.body.append(sheet);
                return sheet;
              };
              const opener = document.querySelector('[data-workspace="today"]');
              opener.focus();
              const first = addSheet("test-sheet-one");
              window.MeridianShell.openSheet(first, { modal: true });
              const second = addSheet("test-sheet-two");
              window.MeridianShell.openSheet(second, { modal: true });
              window.MeridianShell.closeSheet();
              const afterInnerClose = {
                mainInert: document.querySelector("#main").inert,
                navInert: document.querySelector("[data-primary-nav]").inert,
                focus: document.activeElement.closest("#test-sheet-one")?.id || null,
              };
              window.MeridianShell.closeSheet();
              return {
                ...afterInnerClose,
                finalMainInert: document.querySelector("#main").inert,
                finalNavInert: document.querySelector("[data-primary-nav]").inert,
                finalFocus: document.activeElement.dataset.workspace || null,
              };
            }"""
        )

        assert state == {
            "mainInert": True,
            "navInert": True,
            "focus": "test-sheet-one",
            "finalMainInert": False,
            "finalNavInert": False,
            "finalFocus": "today",
        }
        browser.close()


def test_mobile_shell_reaches_every_workspace_without_horizontal_overflow():
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, MOBILE_VIEWPORT)
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")
        _wait_for_shell(page)

        overflow = _document_overflow(page)
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
            overflow = _document_overflow(page)
            assert overflow <= 0
        browser.close()


def test_mobile_inspector_uses_border_box_without_document_overflow():
    """Fails if a full-screen fixed inspector adds padding outside the viewport."""
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, MOBILE_VIEWPORT)
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")
        _wait_for_shell(page)

        state = page.evaluate(
            """() => {
              const panel = document.querySelector("[data-inspector-rail]");
              window.MeridianShell.openSheet(panel, { modal: true });
              return {
                boxSizing: getComputedStyle(panel).boxSizing,
                panelWidth: panel.getBoundingClientRect().width,
                viewportWidth: window.innerWidth,
                overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
              };
            }"""
        )

        assert state["boxSizing"] == "border-box"
        assert state["panelWidth"] <= state["viewportWidth"] + 1
        assert state["overflow"] <= 0
        browser.close()


def test_mobile_shell_uses_the_right_safe_area_inset_for_the_dock_and_inspector():
    """Fails if a right-side cutout can cover the Accounts target or inspector controls."""
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, MOBILE_VIEWPORT)
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")

        shell_css = page.evaluate(
            "() => fetch('/static/css/meridian/shell.css').then((response) => response.text())"
        )
        mobile_css = shell_css.split("@media (max-width: 900px)", 1)[1]
        dock_css = mobile_css.split(".m-nav", 1)[1].split(".m-nav .m-brand", 1)[0]
        inspector_css = mobile_css.split(".m-inspector,", 1)[1].split("/* Shared focus", 1)[0]
        assert "safe-area-inset-right" in dock_css
        assert "safe-area-inset-right" in inspector_css
        browser.close()


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_faint_ink_meets_aa_contrast_on_the_elevated_surface(color_scheme):
    """Fails if normal-size faint labels fall below 4.5:1 contrast."""
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, DESKTOP_VIEWPORT)
        page.emulate_media(color_scheme=color_scheme)
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")

        assert _contrast_ratio(page) >= 4.5
        browser.close()


def test_meridian_uses_local_or_system_fonts_without_google_requests():
    """Fails if the authenticated financial shell asks Google to load fonts."""
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, DESKTOP_VIEWPORT)
        third_party_requests = []
        page.on(
            "request",
            lambda request: third_party_requests.append(request.url)
            if "fonts.googleapis.com" in request.url or "fonts.gstatic.com" in request.url
            else None,
        )
        page.goto(f"{APP_URL}/meridian", wait_until="networkidle")

        assert not third_party_requests
        assert page.locator('link[href*="fonts.googleapis.com"], link[href*="fonts.gstatic.com"]').count() == 0
        browser.close()


def test_1024_shell_retains_the_desktop_rail_without_horizontal_overflow():
    playwright = pytest.importorskip("playwright.sync_api")
    _setup_module()

    with playwright.sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch()
        context, page = _shell_page(browser, TABLET_VIEWPORT)
        page.goto(f"{APP_URL}/meridian", wait_until="domcontentloaded")

        shell = page.locator("[data-meridian-shell]")
        columns = shell.evaluate(
            "node => getComputedStyle(node).gridTemplateColumns.split(' ')"
        )
        assert len(columns) == 3
        assert int(round(float(columns[0].removesuffix("px")))) == 72
        assert page.locator("[data-topbar]").evaluate(
            "node => getComputedStyle(node).display"
        ) == "none"
        assert _document_overflow(page) <= 0
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
