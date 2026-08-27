/* Activity workspace: a stable, date-grouped ledger with cursor pagination. */

import { MeridianApiError, meridianFetch } from "./api.js";
import { dayKey, dayLabel, formatCurrency } from "./format.js";

const state = { cursor: null, accountId: null, controller: null, accountsLoaded: false };

function buildRow(transaction) {
  const row = document.createElement("div");
  row.className = "m-transaction-row";
  row.dataset.transactionRow = "";
  row.dataset.transactionId = String(transaction.id);
  row.dataset.kind = transaction.amount < 0 ? "spend" : "income";
  row.setAttribute("role", "button");
  row.setAttribute("tabindex", "0");
  row.setAttribute(
    "aria-label",
    `${transaction.merchant || transaction.description}, ${formatCurrency(
      transaction.amount,
      transaction.currency
    )}. Open details.`
  );

  const left = document.createElement("span");
  left.className = "m-row-text";
  const title = document.createElement("span");
  title.className = "m-row-title";
  title.setAttribute("data-row-description", "");
  title.textContent =
    transaction.merchant || transaction.description || `Transaction ${transaction.id}`;
  const sub = document.createElement("span");
  sub.className = "m-row-sub";
  sub.textContent =
    transaction.merchant && transaction.description
      ? transaction.description
      : (transaction.provider || "");
  left.append(title, sub);

  const amount = document.createElement("span");
  amount.className = `m-row-amount ${
    transaction.amount < 0 ? "is-spend" : "is-income"
  }`;
  amount.textContent = formatCurrency(transaction.amount, transaction.currency);

  row.append(left, amount);
  return row;
}

function groupFor(ledger, isoTimestamp) {
  const key = dayKey(isoTimestamp);
  let group = ledger.querySelector(`[data-day-group][data-day-key="${key}"]`);
  if (!group) {
    group = document.createElement("section");
    group.className = "m-day-group";
    group.dataset.dayGroup = "";
    group.dataset.dayKey = key;
    const heading = document.createElement("h2");
    heading.className = "m-day-heading";
    heading.textContent = dayLabel(isoTimestamp);
    const list = document.createElement("div");
    list.className = "m-day-rows";
    group.append(heading, list);

    // Insert newest day first.
    const existing = [...ledger.querySelectorAll("[data-day-group]")];
    const anchor = existing.find((candidate) => candidate.dataset.dayKey < key);
    if (anchor) {
      ledger.insertBefore(group, anchor);
    } else {
      ledger.appendChild(group);
    }
  }
  return group.querySelector(".m-day-rows");
}

function setChip(root, freshness) {
  const chip = root.querySelector("[data-freshness]");
  chip.dataset.state = freshness ? (freshness.status || "unavailable") : "unavailable";
  const labels = { fresh: "Fresh", stale: "Stale", unavailable: "Not connected" };
  chip.textContent = labels[chip.dataset.state] || chip.dataset.state;
}

function renderPage(root, payload, { append }) {
  const ledger = root.querySelector("[data-ledger]");
  const empty = root.querySelector("[data-activity-empty]");
  const loadMore = root.querySelector("[data-load-more]");
  const errorBox = root.querySelector("[data-activity-error]");

  errorBox.hidden = true;
  if (!append) {
    ledger.replaceChildren();
  }

  const transactions = payload.transactions || [];
  for (const transaction of transactions) {
    groupFor(ledger, transaction.occurred_at).appendChild(buildRow(transaction));
  }

  empty.hidden = ledger.querySelector("[data-transaction-row]") !== null;
  state.cursor = payload.next_cursor || null;
  loadMore.hidden = !state.cursor;
  setChip(root, payload.data_freshness);
}

async function populateAccounts(select) {
  if (state.accountsLoaded) {
    return;
  }
  state.accountsLoaded = true;
  try {
    const payload = await meridianFetch("/api/meridian/accounts");
    for (const account of payload.accounts || []) {
      const option = document.createElement("option");
      option.value = String(account.id);
      option.textContent = account.name;
      select.appendChild(option);
    }
  } catch {
    /* The All-accounts view remains usable without the filter options. */
  }
}

async function loadActivity(options = {}) {
  const root = document.querySelector("[data-activity-root]");
  if (!root) {
    return;
  }
  const append = Boolean(options.cursor) && options.cursor === state.cursor;

  if (state.controller) {
    state.controller.abort();
  }
  state.controller = new AbortController();

  const params = new URLSearchParams();
  const limit = options.limit || 50;
  params.set("limit", String(limit));
  const cursor = options.cursor !== undefined ? options.cursor : null;
  if (cursor && append) {
    params.set("cursor", cursor);
  }
  const accountId =
    options.accountId !== undefined ? options.accountId : state.accountId;
  if (accountId) {
    params.set("account_id", String(accountId));
  }

  root.setAttribute("aria-busy", "true");
  try {
    const payload = await meridianFetch(`/api/meridian/activity?${params}`, {
      signal: state.controller.signal,
    });
    renderPage(root, payload, { append: append && cursor !== null });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return;
    }
    const ledgerEmpty =
      root.querySelector("[data-ledger] [data-transaction-row]") === null;
    if (ledgerEmpty || !(error instanceof MeridianApiError)) {
      const detail =
        error instanceof MeridianApiError
          ? `${error.message} ${error.recoveryAction}`
          : "Something went wrong while loading Activity.";
      const errorBox = root.querySelector("[data-activity-error]");
      errorBox.textContent = detail;
      errorBox.hidden = false;
    }
  } finally {
    root.removeAttribute("aria-busy");
  }
}

window.MeridianActivity = { loadActivity };

document.addEventListener("click", (event) => {
  if (!event.target.closest("[data-load-more]")) {
    return;
  }
  event.preventDefault();
  if (state.cursor) {
    loadActivity({ cursor: state.cursor });
  }
});

document.addEventListener("change", (event) => {
  const select = event.target.closest("[data-account-filter]");
  if (!select) {
    return;
  }
  const value = select.value ? Number(select.value) : null;
  state.accountId = value;
  loadActivity({ accountId: value, cursor: null });
});

document.addEventListener("meridian:workspacechange", (event) => {
  if (event.detail.workspace === "activity") {
    loadActivity();
    const select = document.querySelector("[data-account-filter]");
    if (select) {
      populateAccounts(select);
    }
  }
});

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    if (window.MeridianShell && window.MeridianShell.getWorkspace() === "activity") {
      loadActivity();
      const select = document.querySelector("[data-account-filter]");
      if (select) {
        populateAccounts(select);
      }
    }
  });
} else if (
  window.MeridianShell &&
  window.MeridianShell.getWorkspace() === "activity"
) {
  loadActivity();
  const select = document.querySelector("[data-account-filter]");
  if (select) {
    populateAccounts(select);
  }
}
