/* Meridian shell controller.
   Exposes window.MeridianShell: workspace switching with URL persistence,
   focus restoration, and a sheet primitive (Escape, inert background,
   focus restore) reused by later slices. */

(() => {
  "use strict";

  const WORKSPACES = ["today", "plan", "activity", "accounts"];
  const DEFAULT_WORKSPACE = "today";

  let activeWorkspace = null;
  const sheetStack = [];

  function isValidWorkspace(name) {
    return WORKSPACES.includes(name);
  }

  function setUrl(workspace) {
    const url = new URL(window.location.href);
    url.searchParams.set("workspace", workspace);
    window.history.replaceState({ meridianWorkspace: workspace }, "", url);
  }

  function applyWorkspace(name) {
    if (!isValidWorkspace(name)) {
      name = DEFAULT_WORKSPACE;
    }
    activeWorkspace = name;

    document.querySelectorAll("[data-workspace-section]").forEach((section) => {
      section.hidden = section.dataset.workspaceSection !== name;
    });

    document.querySelectorAll(".m-nav-item[data-workspace]").forEach((link) => {
      if (link.dataset.workspace === name) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });

    document.dispatchEvent(
      new CustomEvent("meridian:workspacechange", {
        detail: { workspace: name },
      })
    );
  }

  function getWorkspace() {
    return activeWorkspace || DEFAULT_WORKSPACE;
  }

  function setWorkspace(name, options) {
    const settings = options || {};
    applyWorkspace(name);
    if (settings.updateUrl !== false) {
      setUrl(activeWorkspace);
    }
  }

  /* ---------- Sheet primitive ---------- */

  function lastFocusable(container) {
    const candidates = container.querySelectorAll(
      'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    return candidates.length ? candidates[candidates.length - 1] : null;
  }

  function openSheet(sheet) {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const page = document.querySelector("#main");
    if (page && typeof page.inert === "boolean") {
      page.inert = true;
      const nav = document.querySelector("[data-primary-nav]");
      if (nav && typeof nav.inert === "boolean") {
        nav.setAttribute("data-was-inert", "0");
        nav.inert = true;
      }
    }
    sheet.hidden = false;
    sheet.setAttribute("data-open", "");
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");

    const initial = sheet.querySelector("[data-sheet-initial-focus]") || lastFocusable(sheet) || sheet;
    initial.focus();

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.stopPropagation();
        closeSheet();
        return;
      }
      if (event.key === "Tab" && typeof sheet.inert === "boolean") {
        const first = sheet.querySelector("a[href], button, input, [tabindex]:not([tabindex='-1'])");
        if (first && event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          lastFocusable(sheet).focus();
        } else if (
          !event.shiftKey &&
          lastFocusable(sheet) &&
          document.activeElement === lastFocusable(sheet)
        ) {
          event.preventDefault();
          first.focus();
        }
      }
    }

    sheet.__meridianSheetHandler = onKeyDown;
    sheet.addEventListener("keydown", onKeyDown);
    sheetStack.push({ sheet, opener });
    return sheet;
  }

  function closeSheet() {
    const entry = sheetStack.pop();
    if (!entry) {
      return null;
    }
    const { sheet, opener } = entry;
    sheet.hidden = true;
    sheet.removeAttribute("data-open");
    if (sheet.__meridianSheetHandler) {
      sheet.removeEventListener("keydown", sheet.__meridianSheetHandler);
      delete sheet.__meridianSheetHandler;
    }
    if (opener && typeof opener.focus === "function") {
      opener.focus();
    }
    return sheet;
  }

  /* ---------- Global API ---------- */

  const MeridianShell = { setWorkspace, getWorkspace, openSheet, closeSheet };
  window.MeridianShell = MeridianShell;

  document.addEventListener("click", (event) => {
    const link = event.target.closest(".m-nav-item[data-workspace]");
    if (!link) {
      return;
    }
    const target = link.getAttribute("href") || "";
    if (!target.includes("/meridian")) {
      return;
    }
    event.preventDefault();
    setWorkspace(link.dataset.workspace);
  });

  function initFromDom() {
    const fromUrl = new URLSearchParams(window.location.search).get("workspace");
    const serverActive =
      document
        .querySelector('.m-nav-item[aria-current="page"]')
        ?.dataset.workspace || null;

    applyWorkspace(fromUrl || serverActive || DEFAULT_WORKSPACE);
    setUrl(activeWorkspace);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initFromDom);
  } else {
    initFromDom();
  }
})();
