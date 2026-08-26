# Meridian Product Overhaul

**Date:** 2026-08-26

**Status:** Approved design, awaiting implementation-plan approval

**Scope:** Information architecture, planning model, transaction intelligence, external-account normalization, responsive UI, motion, haptics, accessibility, migration, and verification

## Product intent

Meridian should feel like a premium financial instrument rather than a collection of banking utilities. It must provide a unified, data-rich picture of the owner's money without sacrificing the full feature set on mobile. The redesign replaces overlapping Bills, Expenses, Pockets, Beacon, Splitwise, and provider-specific surfaces with a coherent product model and a consistent visual language.

The product should be calm at first glance and exceptionally deep on inspection. AI is embedded in classification, forecasting, explanation, and scenario analysis. It must be evidence-based, correctable, and explicit about confidence. AI may update local classifications and forecasts automatically; anything that creates a Commitment, changes a funding rule, modifies a Crew account, or moves money requires an explained proposal and owner approval.

## Guiding principles

1. **One financial truth.** All supported providers feed one normalized graph. Provider modules do not become separate products.
2. **One planning language.** Bills, savings goals, flexible reserves, buffers, and debts are typed Commitments with shared behavior.
3. **Progressive disclosure, not feature removal.** Mobile reorganizes advanced controls but does not omit them.
4. **Data before decoration.** Every visual answers a financial question. Color and motion communicate state.
5. **Explainable intelligence.** AI conclusions expose evidence, confidence, and correction paths.
6. **Safe automation.** Local metadata can change automatically. Financial rules and mutations require approval.
7. **Trustworthy freshness.** Stale or incomplete provider data is labeled and never silently treated as current.

## Information architecture

The primary navigation contains four workspaces.

### Today

The daily command center answers:

- What can I safely spend now?
- What money events happen next?
- Is the plan still viable?
- What changed since my last visit?
- What requires attention?

The page contains a dominant safe-to-spend figure, a compact explanation of its inputs, upcoming money moments, Beacon coverage and runway, anomalies, and a limited action queue. It is not a dumping ground for every metric.

### Plan

Plan is the home of Commitments. It supports three coordinated views:

- **Command view:** coverage, unfunded amount, next paycheck allocations, and exceptions.
- **Timeline view:** paychecks, planned contributions, due dates, expected transactions, and projected balances on one time axis.
- **Allocation view:** a graphical money map showing available, committed, goal-bound, reserve, and at-risk funds.

Editing a plan should update all three views from the same underlying data.

### Activity

Activity is the unified transaction ledger. It has three modes:

- **Timeline:** chronological transactions grouped by date, account, and meaningful event.
- **Review:** low-confidence classifications, anomalies, suspected duplicates, and unresolved recurrence.
- **Patterns:** recurring charges, merchant and category changes, cash-flow shifts, and detected trends.

### Accounts

Accounts contains financial structure and configuration: Crew accounts and pockets, external accounts, cards, family members, people/reimbursements, provider connections, credentials, and settings. It does not compete with the daily or planning experience.

The AI advisor is globally available. On desktop it can become an optional inspector rail; on mobile it opens as a full-height sheet. Launching it from a transaction, Commitment, forecast, or account supplies that object's safe context.

## Unified Commitment model

A Commitment is any financial intention that reserves, accumulates, or protects money. Types are:

- `bill`: an amount due on a date or recurrence;
- `goal`: a target amount by an optional target date;
- `reserve`: a replenished spending envelope;
- `buffer`: minimum-balance protection;
- `debt`: required payment plus an optional payoff strategy.

Each Commitment includes:

- identity, display name, type, status, and priority;
- backing account or Crew pocket;
- target amount and current funded amount;
- due date, recurrence, or target date;
- funding source;
- funding-rule configuration;
- variable-amount and buffer policy;
- connected transactions and recurrence series;
- forecast, confidence, and contributing factors;
- change history and provenance.

Crew pockets remain real banking containers. Commitments are the local planning layer that describes why money is held and how it should be funded. A Commitment may initially be unbacked, but the UI must label that state clearly.

## Funding rules

Funding rules support:

- fixed amount per detected paycheck;
- percentage of paycheck;
- fixed calendar cadence;
- even funding by due date;
- priority waterfall after essential Commitments;
- minimum and maximum contribution limits;
- one-time override, pause, and skip;
- a variable-bill buffer derived from observed payment history.

A funding rule produces projections and proposed contributions. When a triggering paycheck arrives, the system may automatically create a transfer proposal containing the calculation, source, destination, amount, affected forecast, and confidence. No transfer executes without explicit approval.

The rule editor uses a shared schema on desktop and mobile. Desktop presents form controls beside a live timeline preview. Mobile presents the same controls as ordered steps and bottom sheets, with a persistent preview summary.

## Beacon forecasting

Beacon becomes the shared forecasting engine rather than a separate feature card. It calculates:

- safe-to-spend after known obligations;
- funding coverage by horizon;
- balance runway and projected low point;
- first projected shortfall, date, amount, and cause;
- Commitment completion probability and confidence;
- data-freshness impact on the forecast;
- effects of proposed rule changes.

Forecast explanations must identify the underlying transactions, schedules, balances, and assumptions. Users can run counterfactual scenarios without changing saved data. Saving an AI-suggested schedule change creates an approval proposal.

## Unified financial graph

Provider adapters normalize Crew, SimpleFin, LunchFlow, Splitwise, and future sources into:

- provider connections and freshness;
- accounts and balances;
- transactions and transfer relationships;
- liabilities;
- people and reimbursements;
- Commitments and funding links.

Every normalized object retains provider provenance and external identifiers. Repeated syncs must be idempotent. Transfers between owned accounts must not be counted as spending. Credit-card purchases and payments must be reconciled without double-counting. Splitwise amounts owed to the owner become expected inflows; amounts the owner owes become short-term Commitments; shared expenses link to relevant transactions.

Provider branding is subordinate. Small source marks may appear in account and transaction details, but provider-specific layouts, colors, or navigation must not fragment the product.

## Transaction intelligence

Every synchronized transaction receives:

- normalized merchant;
- category;
- linked Commitment, when applicable;
- recurring-series detection;
- transaction kind, including income, spend, transfer, refund, fee, and reimbursement;
- anomaly and duplicate signals;
- confidence score;
- concise explanation and evidence references;
- assignment provenance: user rule, deterministic system rule, or AI.

Classification order is:

1. explicit user correction or rule;
2. deterministic transfer/provider reconciliation;
3. known merchant and recurrence rule;
4. AI classification using safe transaction and plan context;
5. fallback category.

AI always assigns a best guess. Low-confidence assignments enter Review and receive a visible confidence treatment. A user correction can optionally create a durable local rule, which outranks future AI results. Reclassification must preserve history.

Transaction details open as a full inspector surface. They show merchant, raw description, amount, status, account, card, category, Commitment, AI explanation, confidence, recurrence, related transfers/refunds/splits, notes, tags, correction history, provider freshness, and impact on safe-to-spend and forecasts.

## Embedded AI

AI capabilities include:

- explaining changes in safe-to-spend;
- forecasting dated shortfalls with causal evidence;
- detecting new recurring charges and offering Commitments;
- identifying bill increases and pattern shifts;
- recommending funding-rule changes from historical volatility;
- connecting payments to Commitments;
- reconciling outside-account activity into the unified picture;
- generating evidence-backed what-if scenarios;
- answering advisor questions from the exact data visible in the product.

AI must not use generic encouragement as a substitute for analysis. Each recommendation should state the observed facts, calculation or pattern, confidence, and likely effect. The system stores model/provider metadata for audit without exposing credentials.

## Financial evidence graph

Meridian connects financial facts across transactions, documents, schedules, messages, and real-world events. Evidence is stored separately from conclusions so every link can be inspected, corrected, expired, or removed without rewriting the source record.

Each evidence item includes source type, source identifier, captured timestamp, effective date, extracted facts, linked financial objects, confidence, provenance, retention policy, and user corrections. Each connection is individually opt-in and read-only. Meridian never sends email, deletes messages, modifies calendars, or acts on external systems through an evidence connection.

### Document Intelligence

Authorized Gmail access and a dedicated forwarding address ingest financial email and supported attachments. Meridian detects bills, statements, receipts, renewal notices, pay stubs, contracts, and payment confirmations. PDF and image extraction captures merchant, amount, due date, billing period, masked account reference, line items, renewal terms, and source evidence.

Documents link to Commitments and transactions. Meridian reconciles bill-to-charge-to-payment chains, detects duplicates, price increases, late fees, missing expected bills, and mismatched totals, and attaches the original document to the relevant detail surface. Unsupported, encrypted, oversized, suspicious, or low-confidence files enter Review. Attachments are type-checked, size-limited, malware-scanned, hashed for deduplication, encrypted at rest, and governed by explicit retention controls. Deterministic extraction runs before AI interpretation.

### Life Context

Read-only calendar, payroll-document, travel-itinerary, and shared-money evidence may enrich forecasts. Meridian can anticipate dated spending pressure, verify deposits against pay stubs, create temporary trip scenarios, and reconcile reimbursements. It describes correlations without claiming causation and never treats a calendar event as a known expense without financial evidence or user confirmation.

### Asset and Contract Memory

Receipts, warranties, leases, insurance policies, financing agreements, memberships, and maintenance records may form an asset and obligation ledger. Meridian tracks return windows, warranty expirations, renewal dates, escalation clauses, deductibles, cancellation windows, maintenance intervals, and replacement reserves. Medical financial documents may be reconciled as bills and payments, but Meridian must not make medical, legal, coverage, or tax determinations.

### Connected Billers

Connected Billers is the final roadmap priority and builds on the completed Commitment, document, transaction, and evidence layers. It is a capability inside a Commitment, not a separate primary workspace or provider-branded module.

A biller connection exposes an explicit capability ladder:

1. **Monitor:** retrieve the current amount due, due date, statement, autopay state, payment history, plan changes, provenance, freshness, and connection health.
2. **Switch:** after owner approval, update the biller's stored payment method to a user-selected linked account or card through a vetted switching partner.
3. **Pay:** after owner approval, schedule or initiate a one-time or recurring payment through a regulated bill-payment partner.
4. **Meridian bill account:** consider an optional partner-backed household bill-pay account only after the first three capabilities demonstrate demand, reliability, and an acceptable regulatory and support posture.

Monitoring may synchronize automatically after source-specific authorization. Switching, scheduling, paying, or reversing a switch is a financial mutation and must use the existing explain-propose-approve-execute-verify pipeline. Mutations receive idempotency keys, execute once, and remain pending when their outcome is uncertain; they are never retried automatically. Meridian must verify the resulting biller state and warn about transition-period duplicate charges.

Authentication occurs in OAuth or partner-hosted interfaces. Meridian never stores raw biller passwords or exposes partner tokens to the browser, AI prompts, logs, or fixtures. Merchant coverage and capability vary, so every Commitment displays supported actions and provides a guided manual fallback without pretending the connection succeeded.

The interface remains provider-neutral. Today surfaces exceptions, Plan reflects verified amounts and funding pressure, Activity records proposals and confirmed changes, and the Commitment inspector holds statements, connection state, payment method, and audit history.

## Visual language

The emotional foundation is **Editorial Wealth**, supported by **Quiet Precision**.

- Warm neutral surfaces create a composed, human atmosphere.
- Serif display typography is reserved for major financial figures and editorial headings.
- Precise sans-serif typography handles labels, controls, tables, and dense data.
- State colors are restrained and consistent: healthy, caution, risk, information, and neutral.
- Gradients or aurora glow appear only for meaningful milestones, successful recovery, or a major positive change.
- Charts use direct labels, accessible contrast, and truthful scales.
- Cards are used for meaningful grouping, not for every piece of text.
- Spacing, alignment, and typographic hierarchy carry more visual weight than shadows or glass effects.

Motion uses short spring transitions for navigation and sheet movement, continuity animations between summary and detail, tactile press states, and subtle chart transitions. Supported mobile devices receive haptics for confirmed selections, completed reviews, successful proposal creation, and important warnings. Haptics are never used for ordinary scrolling or decoration. Reduced-motion preferences disable nonessential movement.

Dark and light themes are designed independently rather than produced through mechanical inversion.

## Responsive behavior

Desktop uses a compact navigation rail, broad central canvas, and optional right inspector/advisor rail. Detail selection should preserve the user's place in lists and timelines.

Mobile retains every core capability through:

- full-screen drill-downs;
- bottom sheets for contextual actions and editors;
- compact, horizontally scrollable timelines where appropriate;
- gesture shortcuts with visible alternatives;
- sticky summaries and a persistent action dock;
- touch targets of at least 44 CSS pixels;
- safe-area support and resilient keyboard behavior.

No advanced feature may be omitted solely because the viewport is small.

## Migration and compatibility

Migration must be non-destructive and resumable.

- Existing bill/expense records become `bill` Commitments.
- Existing ordinary goal pockets become `goal` Commitments.
- Credit-card payment pockets become debt-payment Commitments when the linkage is known.
- Uncertain mappings remain visible in a migration review queue.
- Existing Crew pockets and external provider identifiers are preserved.
- Legacy endpoints may remain temporarily behind adapters while the UI moves to the new model.

The migration records source identifiers and version so it can be audited and rerun safely. No Crew mutation occurs during migration.

## Error handling and trust

Errors appear in the affected context and include the impacted provider or calculation, last trustworthy update, consequence, and one primary recovery action. The application preserves last-known-good data and labels it stale. Partial provider failures do not erase unrelated account data.

AI failure falls back to deterministic classifications and existing saved forecasts. A failed AI call cannot block transaction synchronization. Financial mutations preserve the no-automatic-retry rule for uncertain writes.

## Implementation boundaries

The current monolithic backend and overlapping front-end modules are changed incrementally:

- introduce normalized domain modules and database tables behind explicit interfaces;
- keep provider adapters separate from domain logic;
- add new API resources for Today, Plan, Activity, Accounts, and advisor context;
- build reusable UI primitives and workspace components rather than adding another global CSS override layer;
- migrate one vertical slice at a time while compatibility adapters keep existing data usable.

The first production slice should establish the shell, tokens, responsive navigation, normalized read model, and transaction detail inspector. The second should add Commitments and schedules. The third should add unified provider ingestion and transaction intelligence. The fourth should complete Beacon scenarios, contextual AI, migration cleanup, and removal of obsolete surfaces. The fifth should add Document Intelligence and reconciliation. The sixth should add opt-in Life Context. The seventh should add Asset and Contract Memory. The eighth and final-priority slice should add Connected Billers in monitor, switch, pay, and optional partner-backed-account stages.

## Verification and acceptance criteria

The redesign is accepted when:

1. Today, Plan, Activity, and Accounts replace the overlapping primary navigation.
2. A bill, goal, reserve, buffer, or debt can be represented and inspected as a Commitment.
3. Funding rules support paycheck, percentage, calendar, even-by-date, priority, and override behaviors.
4. Funding triggers create proposals and never execute transfers automatically.
5. Transactions from supported providers appear in one ledger without transfer/payment double-counting.
6. Every transaction has an assignment, confidence, explanation, and correction path.
7. Corrected assignments become deterministic local rules when requested.
8. Transaction details expose complete financial and provenance context.
9. Beacon explains forecast outcomes and supports non-destructive scenarios.
10. Mobile exposes the same core capabilities as desktop.
11. Keyboard, screen-reader, reduced-motion, contrast, safe-area, and touch-target checks pass.
12. Unit, integration, migration, API, browser, and responsive smoke tests run in CI.
13. Existing Crew credential and mutation-safety boundaries remain intact.
14. Legacy duplicated views are removed only after migrated workflows pass parity checks.
15. Email and document connections are read-only, individually revocable, and governed by retention controls.
16. Bill, charge, payment, receipt, and contract evidence can be linked without double-counting financial activity.
17. Calendar and life-context evidence influences scenarios only with visible assumptions and confidence.
18. Asset and contract facts remain traceable to source documents and never become medical, legal, coverage, or tax advice.
19. Connected billers remain part of Commitments and do not add a fifth primary navigation item.
20. Monitoring exposes source, freshness, authorization, capability, and connection-health state.
21. Switching and payment actions require explanation, explicit owner approval, single-attempt execution, and post-action verification.
22. Biller credentials and partner tokens never enter browser payloads, AI prompts, logs, or fixtures.
23. Unsupported billers and uncertain outcomes provide honest manual or verification paths rather than false success.
