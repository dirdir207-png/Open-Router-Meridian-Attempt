# Meridian Project Memory

**Recorded:** August 26, 2026  
**Repository:** `dirdir207-png/SimpleCrew`  
**Product name:** Meridian  
**Implementation branch:** `feat/meridian-implementation`

## Product thesis

Meridian is a high-trust financial operating system for individuals and households. It replaces fragmented budgeting pages with a coherent view of what happened, what is coming, why the system believes it, and what requires attention. The product must feel editorial, calm, graphical, modular, and premium while retaining full mobile capability.

## Approved experience

- Four primary workspaces: Today, Plan, Activity, and Accounts.
- A context-aware advisor that remains accessible throughout the product.
- A unified Commitment model replacing overlapping bills, expenses, and pockets.
- Proper funding schedules and granular transaction details.
- Provider-neutral outside accounts folded into one financial picture.
- Automatic AI transaction assignment with confidence, review, and correction-derived rules.
- User rules and corrections always outrank AI classifications.
- AI may change local classifications and forecasts; creating Commitments, changing funding rules, modifying Crew state, or moving money requires an explained proposal and owner approval.
- Mobile exposes the same core capabilities through responsive composition and progressive disclosure.
- Splitwise, Crew, SimpleFin, LunchFlow, and future providers must not fragment the visual language.

## Visual direction

The approved direction is the Command Center shell, led by Editorial Wealth and supported by Quiet Precision. Aurora effects are rare emphasis, not decoration. The interface must meet WCAG 2.2 AA, keyboard and screen-reader requirements, reduced-motion preferences, safe-area behavior, and 44 CSS-pixel touch targets.

## Intelligence architecture

Meridian's long-term differentiator is a Financial Evidence Graph connecting:

- Accounts, balances, and transactions
- Commitments and funding schedules
- Bills, statements, receipts, and payment confirmations
- Email evidence with explicit read-only authorization
- Shared obligations and reimbursements
- Payroll, calendar, and travel signals
- Contracts, warranties, renewals, and maintenance
- Direct biller monitoring, approved payment-method switching, and partner-mediated bill payment as the final roadmap priority
- Provider provenance, freshness, external identifiers, and confidence
- User corrections and deterministic rules

The graph should reconcile documents, charges, reimbursements, obligations, and payments into economic events rather than presenting unrelated provider records.

## Delivery program

The approved implementation plan contains 26 tasks across seven slices:

1. Trustworthy foundation and shell
2. Commitments and funding
3. Unified providers and transaction intelligence
4. Advanced intelligence and consolidation
5. Document Intelligence
6. Life Context
7. Asset and Contract Memory

An approved eighth and final-priority slice, Connected Billers, will be appended to the implementation plan after written-spec review. It progresses from read-only monitoring to approved payment-method switching, then regulated partner-mediated payment. A partner-backed Meridian bill account remains optional and contingent on validated demand.

The implementation uses versioned, non-destructive SQLite migrations, stable `/api/meridian/*` read models, compatibility adapters, vanilla ES2020 modules, Flask, pytest, Playwright, Docker, and GitHub Actions. New business logic must not be added to the existing monolithic `app.py`.

## Model and cost strategy

- Terra leads routine multi-file implementation and integration work.
- Sol governs architecture, security, concurrency, migrations, release gates, and final review.
- Luna handles bounded mechanical work with complete specifications.
- Expected full-roadmap consumption: approximately 26-46 million input tokens and 4.0-7.4 million output/reasoning tokens.
- Estimated API-equivalent cost: approximately $105-$190, with a prudent ceiling of $300.
- These are forecasts for the complete roadmap, not usage already consumed.

## Commercial thesis

Launch Meridian as a premium subscription for financially complex households, not as a generic budgeting application. The initial promise is automatic reconciliation of accounts, documents, obligations, charges, reimbursements, and payments into one trustworthy picture.

Suggested initial tiers:

- Individual: approximately $15-$20 per month.
- Household: approximately $30-$45 per month.

Begin with 10 deeply engaged design partners and expand to 25-50 founding households through white-glove onboarding and referrals. Measure weekly retention, correction rate, classification accuracy, time saved, detected savings, avoided fees, and willingness to pay. Expand only after consumer validation into advisor tooling, employer financial wellness, and white-label intelligence infrastructure.

Meridian must never depend on advertising, selling customer financial data, or paid placement disguised as advice.

## Intellectual-property posture

Copyright can protect human-authored code, visual expression, written specifications, and creative assets, but not the general idea, workflow, method, algorithm, or system. Trademark may protect Meridian and its identifiers subject to clearance. Trade-secret controls may protect unpublished reconciliation logic, scoring, prompts, evaluation methods, and proprietary datasets.

The strongest patent candidate is not the broad concept of AI reading bills. It is a potentially novel, provenance-preserving evidence architecture that resolves heterogeneous documents and financial records into confidence-scored events, forecasts, explanations, and reversible proposals while separating informational automation from approval-required financial actions. Patent counsel and prior-art review should occur before further public technical disclosure if international rights matter.

Because AI assisted development, preserve evidence of human direction, selection, arrangement, revision, testing, and product judgment.

## Current engineering state

- Product design, implementation plan, model strategy, and evidence-graph expansion are committed.
- An isolated implementation worktree exists at `.worktrees/meridian`.
- Baseline Docker build succeeded and the original suite passed 116 tests.
- Task 1 initially produced commit `c385855`, with 118 tests passing and an isolated production browser smoke test passing.
- Independent review rejected Task 1 pending a genuinely passing dependency audit, full lint gate, bounded smoke-test startup, promotion of the tested image, and stronger configuration tests.
- A subsequent correction attempt hit the account usage limit and left an uncommitted mechanical lint cleanup. Those changes are not accepted as complete and require verification before they are committed.
- No merge, push, deployment, or production financial mutation has been performed.

## Binding safety rules

- Credentials and provider secrets remain server-side and never enter browser payloads, AI prompts, logs, or fixtures.
- Financial mutations are never retried automatically; uncertain outcomes require state verification.
- Existing migrations remain non-destructive, versioned, idempotent, and resumable.
- Every normalized record retains provenance, freshness, and external identifiers.
- Every task requires implementation, tests, independent review, and explicit completion evidence.
