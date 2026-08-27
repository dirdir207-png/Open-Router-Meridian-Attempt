/* Plan workspace: canonical view model rendering and the funding-rule editor
   whose only write path is an approval-gated proposal. */

import { MeridianApiError, meridianFetch, meridianPropose } from "./api.js";
import { formatCurrency } from "./format.js";

let controller = null;

function money(value, currency = "USD") {
  return value === null || value === undefined ? "—" : formatCurrency(value, currency);
}

function renderSummary(root, plan) {
  root.querySelector("[data-plan-headline]").textContent = plan.summary.headline;

  const ratio = Math.max(0, Math.min(1, plan.summary.coverage_ratio || 0));
  root.querySelector("[data-coverage-fill]").style.width = `${Math.round(ratio * 100)}%`;
  root.querySelector("[data-coverage-text]").textContent = `${Math.round(ratio * 100)}% funded`;

  root.querySelector("[data-plan-total]").textContent = money(plan.summary.total_target);
  root.querySelector("[data-plan-funded]").textContent = money(plan.summary.total_funded);
  root.querySelector("[data-plan-unfunded]").textContent = money(plan.summary.unfunded);
  root.querySelector("[data-plan-next-due]").textContent = plan.summary.next_due || "—";

  const shortfall = root.querySelector("[data-plan-shortfall]");
  const first = plan.summary.first_shortfall;
  if (first) {
    shortfall.hidden = false;
    shortfall.textContent = `First shortfall: ${first.date} — ${money(first.amount)} (${first.cause})`;
  } else {
    shortfall.hidden = true;
    shortfall.textContent = "";
  }
}

const SEGMENT_CLASSES = {
  "Committed to commitments": "is-committed",
  "Unfunded commitments": "is-unfunded",
  "Available": "is-available",
};

function renderAllocation(root, plan) {
  const bar = root.querySelector("[data-allocation-bar]");
  const legend = root.querySelector("[data-allocation-legend]");
  bar.replaceChildren();
  legend.replaceChildren();

  const cash = plan.allocation.cash_total || 0;
  for (const segment of plan.allocation.segments) {
    if (cash > 0 && segment.amount > 0) {
      const slice = document.createElement("span");
      slice.className = SEGMENT_CLASSES[segment.label] || "";
      slice.style.width = `${(segment.amount / cash) * 100}%`;
      bar.appendChild(slice);
    }
    const item = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = `swatch ${SEGMENT_CLASSES[segment.label] || ""}`;
    item.appendChild(swatch);
    item.appendChild(
      document.createTextNode(`${segment.label}: ${money(segment.amount)}`)
    );
    legend.appendChild(item);
  }
}

function renderTimeline(root, plan) {
  const list = root.querySelector("[data-timeline]");
  const empty = root.querySelector("[data-timeline-empty]");
  list.replaceChildren();
  const events = plan.timeline.events || [];
  empty.hidden = events.length > 0;
  for (const event of events.slice(0, 12)) {
    const row = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${event.date} · ${event.commitment}`;
    const amount = document.createElement("span");
    amount.className = "m-timeline-amount";
    amount.textContent = money(event.amount);
    row.append(label, amount);
    list.appendChild(row);
  }
}

/* ---------- Funding-rule editor ---------- */

function describeRule(kind, amount, percent) {
  switch (kind) {
    case "fixed_per_paycheck":
      return `Moves ${money(amount)} from available cash on each paycheck.`;
    case "percent_of_paycheck":
      return `Moves ${percent || 0}% of each paycheck.`;
    case "calendar":
      return `Moves ${money(amount)} on a repeating calendar cadence.`;
    case "even_by_due_date":
      return `Splits the remaining amount evenly between now and the due date.`;
    default:
      return "";
  }
}

function openEditor(root, commitment, template) {
  root.querySelectorAll("[data-funding-editor]").forEach((node) => node.remove());
  const editor = template.content.firstElementChild.cloneNode(true);
  editor.dataset.commitmentId = String(commitment.id);
  const preview = editor.querySelector("[data-editor-preview]");

  const kindSelect = editor.querySelector('select[name="kind"]');
  const amountInput = editor.querySelector('input[name="amount"]');
  const percentInput = editor.querySelector('input[name="percent"]');

  function syncFields() {
    const kind = kindSelect.value;
    editor.querySelector('[data-editor-field="amount"]').hidden = kind === "percent_of_paycheck";
    editor.querySelector('[data-editor-field="percent"]').hidden = kind !== "percent_of_paycheck";
    preview.textContent = describeRule(
      kind,
      amountInput.value ? Number(amountInput.value) : null,
      percentInput.value
    );
  }

  kindSelect.addEventListener("change", syncFields);
  amountInput.addEventListener("input", syncFields);
  percentInput.addEventListener("input", syncFields);
  editor.querySelector("[data-editor-cancel]").addEventListener("click", () => editor.remove());

  editor.addEventListener("submit", async (event) => {
    event.preventDefault();
    const note = editor.querySelector("[data-editor-note]");
    const rule = { kind: kindSelect.value };
    if (kindSelect.value === "percent_of_paycheck") {
      if (percentInput.value) {
        rule.percent = Number(percentInput.value);
      }
    } else if (amountInput.value) {
      rule.amount = Number(amountInput.value);
    }
    note.hidden = true;
    try {
      await meridianPropose("/api/meridian/funding-rules/propose", {
        commitment_id: commitment.id,
        rule,
      });
      note.hidden = false;
      note.textContent = "Proposal created — approve it in Pending Actions.";
      note.dataset.state = "ok";
    } catch (error) {
      note.hidden = false;
      note.dataset.state = "error";
      note.textContent =
        error instanceof MeridianApiError
          ? `${error.message} ${error.recoveryAction}`
          : "The proposal could not be created.";
    }
  });

  syncFields();
  root
    .querySelector(`[data-commitment-card="${commitment.id}"]`)
    .appendChild(editor);
  return editor;
}

function renderCommitments(root, plan) {
  const list = root.querySelector("[data-commitment-list]");
  const empty = root.querySelector("[data-commitments-empty]");
  const template = root
    .closest("main")
    .querySelector("[data-funding-editor-template]");
  list.replaceChildren();
  const commitments = plan.commitments || [];
  empty.hidden = commitments.length > 0;

  for (const commitment of commitments) {
    const card = document.createElement("li");
    card.className = "m-commitment-card";
    card.dataset.commitmentCard = String(commitment.id);

    const head = document.createElement("div");
    head.className = "m-commitment-head";
    const name = document.createElement("h3");
    name.className = "m-commitment-name";
    name.textContent = commitment.name;
    const type = document.createElement("span");
    type.className = "m-commitment-type";
    type.textContent = commitment.type;
    head.append(name, type);

    const progress = document.createElement("div");
    progress.className = "m-commitment-progress";
    const fill = document.createElement("span");
    const ratio =
      commitment.target > 0 ? Math.min(1, commitment.funded / commitment.target) : 0;
    fill.style.width = `${Math.round(ratio * 100)}%`;
    progress.appendChild(fill);

    const facts = document.createElement("div");
    facts.className = "m-commitment-facts";
    const pieces = [
      `${money(commitment.funded)} of ${money(commitment.target)}`,
    ];
    if (commitment.due_date) {
      pieces.push(`due ${commitment.due_date}`);
    }
    if (commitment.backing) {
      pieces.push(`backed by ${commitment.backing.name}`);
    }
    for (const text of pieces) {
      const span = document.createElement("span");
      span.textContent = text;
      facts.appendChild(span);
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "m-button";
    button.textContent = "Edit funding";
    button.addEventListener("click", () =>
      openEditor(root, commitment, template)
    );

    card.append(head, progress, facts, button);
    list.appendChild(card);
  }
}

async function loadPlan() {
  const root = document.querySelector("[data-plan-root]");
  if (!root) {
    return;
  }
  if (controller) {
    controller.abort();
  }
  controller = new AbortController();
  const errorBox = root.querySelector("[data-plan-error]");
  errorBox.hidden = true;
  root.setAttribute("aria-busy", "true");
  try {
    const plan = await meridianFetch("/api/meridian/plan", {
      signal: controller.signal,
    });
    renderSummary(root, plan);
    renderAllocation(root, plan);
    renderTimeline(root, plan);
    renderCommitments(root, plan);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return;
    }
    errorBox.textContent =
      error instanceof MeridianApiError
        ? `${error.message} ${error.recoveryAction}`
        : "The plan could not be loaded.";
    errorBox.hidden = false;
  } finally {
    root.removeAttribute("aria-busy");
  }
}

window.MeridianPlan = { loadPlan };

document.addEventListener("meridian:workspacechange", (event) => {
  if (event.detail.workspace === "plan") {
    loadPlan();
  }
});

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    if (window.MeridianShell && window.MeridianShell.getWorkspace() === "plan") {
      loadPlan();
    }
  });
} else if (window.MeridianShell && window.MeridianShell.getWorkspace() === "plan") {
  loadPlan();
}
