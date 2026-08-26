# Enhanced SimpleCrew — Current Status

Last consolidated: 2026-08-26 (Ox Alpha Meridian implementation)

## Canonical sources

- Repository: `dirdir207-png/SimpleCrew`
- Default branch: `main` (protected; do not work directly on it)
- Approved design: bundle artifact `Enhanced_SimpleCrew_Design_Spec` / `2026-08-24-hybrid-gateway-foundation-design.md`
- Milestone 2 design: `docs/designs/2026-08-25-guided-credential-renewal.md`
- Meridian design: `docs/superpowers/specs/2026-08-26-meridian-product-overhaul-design.md`
- Meridian implementation plan: `docs/superpowers/plans/2026-08-26-meridian-overhaul-implementation.md`
- Ox Alpha implementation branch: `ox-alpha/meridian-overhaul`
- Approved specifications override informal chat history when they conflict.

## Architecture and safety decisions

- Enhanced SimpleCrew runs on the always-on Mac.
- Crew GraphQL is the primary banking-data path.
- Crew credentials and bearer/session tokens remain server-side/local and must never be exposed to browser or Base44 frontend code.
- Tailscale is the intended private remote-access path (`docs/REMOTE_ACCESS.md`).
- Existing SimpleCrew authentication/passkey protection remains in place.
- Financial mutations must never be retried automatically; uncertain transfer outcomes surface as `uncertain_write` / verify-state.

## Milestone status

### Meridian Slice 1 — quality and production foundation: IN PROGRESS (Ox Alpha branch)

- Separate branch/workspace created: `ox-alpha/meridian-overhaul`.
- Production launch is being separated from development: secure cookie defaults, `FLASK_DEBUG=1` opt-in, and Gunicorn Docker entrypoint.
- Developer tooling is isolated in `requirements-dev.txt`; CI workflow added for lint, tests, dependency audit, and Docker build.
- Next task: add the Meridian normalized read model and the independent Today/Plan/Activity/Accounts shell. No legacy route or deployment is being replaced yet.

### Milestone 1 — Hybrid Gateway Foundation: COMPLETE (merged PR #2, hardening PR #3)

- All eight approved TDD tasks executed: credential-provider boundary, `CrewClient`, health classification, Flask/UI wiring, transfer migration, first safe-read migration, Tailscale docs, verification gate.
- Live verification server-side against real Crew: valid token → `healthy`, junk token → `unauthorized`, blackhole endpoint → `unreachable`.
- Deployment: local Docker build (`build: .`, image `simplecrew-local`) running against a copy of production data; original untouched at `~/Documents/SimpleCrew`.
- Stored tokens with literal `Bearer ` prefix are normalized before header injection.

### Milestone 2 — Guided credential renewal: IMPLEMENTED (branch `feat/guided-credential-renewal`, pending owner verification)

- Design: `docs/designs/2026-08-25-guided-credential-renewal.md`.
- `crew/renewal.py` `GuidedRenewalService`: single-flight sessions, uuid ids, deadline expiry, late-capture discard, sanitized status payloads (whitelisted fields; health reduced to state/message).
- `crew/browser_capture.py`: Playwright Chromium capturer listening for the first `authorization` header sent to `api.trycrew.com`; lazy import with actionable install guidance when absent.
- Flask: `POST /api/account/crew/reconnect/start`, `GET /api/account/crew/reconnect/status/<id>` (login required, 404 on unknown id, route-level whitelist sanitization); renewed credentials stored via the same path as manual saves.
- UI: **Reconnect Crew** button appears when health is `unauthorized`; polls status and re-checks health after capture.
- Test suite on branch: 41 passing (renewal lifecycle 8, capturer 4, endpoints/UI regressions included). No test opens a browser or contacts Crew.
- Pending manual gate: end-to-end renewal with real Crew login (requires Playwright install + invalid-token simulation).

### Milestone 3 — Action pipeline foundation: IMPLEMENTED (branch `feat/action-pipeline`)

- Design: `docs/designs/2026-08-25-action-pipeline.md`.
- `crew/actions.py`: durable SQLite store; enforced one-way lifecycle `PROPOSED → APPROVED → EXECUTED → VERIFIED` (+ rejected/expired/failed); unknown types rejected at propose.
- `crew/executors.py`: registry binding action type → vetted function adapter + verifier; failures normalized (`no_executor`, `executor_exception`, `action_failed`, `verification_failed`); `expire_stale_approvals` gives approvals a 1-hour execution window.
- Flask: `/api/actions/pending|propose|<id>/approve|reject|execute`, login required, conflicts → 409.
- UI: Pending Actions card (approve/reject). Execution is deliberately API-only for now: an approval opens a one-hour window during which an authorized runner may execute; nothing auto-executes.
- Test suite on branch: 58 passing + 1 skip. No Crew contact.

### Milestone 3b — Action proposer interface: IMPLEMENTED (branch `feat/action-proposer`)

- Design: `docs/designs/2026-08-25-action-proposer.md`.
- `crew/proposals.py`: name→id resolution + validated transfer proposals with human-readable summaries.
- `POST /api/actions/propose/local`: loopback-only (403 otherwise); a Mac-local assistant can create inert proposals ("move $50 from Checking to Rent") that surface in the owner's Pending Actions card.
- Real resolver adapter over existing lookups (`get_primary_account_id` + subaccount list); failures are explicit, never guessed ids.

### Milestone 5 — AI advisor: IMPLEMENTED (branch `feat/ai-advisor`)

- Design: `docs/designs/2026-08-25-ai-advisor.md`.
- Provider-agnostic OpenAI-compatible client via env (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`); graceful not-configured state.
- `AdvisorService`: display-safe financial context -> LLM -> reply; proposal JSON blocks validated through the same whitelist/resolver as all proposers; only `move_money`; stored as pending actions (`requested_by=ai-advisor`).
- API: `/api/advisor/status`, `/api/advisor/chat` (login required; AdvisorUnavailable -> 503).
- UI: AI Advisor chat card in Account view; drafted proposals surface in Pending Actions.
- Suite: 96 passing + 1 skip. No real network calls in tests.

### Milestones 6+7 — Beacon budget & UI polish: IMPLEMENTED (branch `feat/beacon-and-polish`, stacked on M5)

- `crew/beacon.py`: explainable 30-day forecast from balance history (avg daily burn over 14-day lookback, runway, low point); unavailable state until enough history.
- `/api/beacon/forecast` + 📡 Beacon card at top of Pockets dashboard view.
- UI polish: global interaction transitions/depth/focus rings (`polish.css`), Move-Money amount slider synced both ways, haptics on slider ticks / transfer success / advisor proposals.

### Review blockers from prior work — REPRODUCED AND REMEDIATED (merged PR #3)

1. Truthy non-string transfer ID mistaken for confirmed success → reproduced by regression test; `move_money` now requires a non-empty string `result.id`.
2. Missing `.dockerignore` → confirmed missing (prior image build could include databases/`.env`/caches); added covering secrets, data, venv, git metadata, caches, docs/tests.

## Prior-work recovery note

The previously reported 103-test result belonged to unrecoverable local commit `32fe0b8`. Recovery is moot for Milestone 1 scope: the milestone was re-implemented from the authoritative bundle and merged. The two review blockers it flagged were reproduced against the new implementation and fixed here.

## Roadmap

1. ~~Milestone 2 — automatic Crew credential renewal~~ (merged PR #4; owner E2E click-through still to be observed at a natural expiry)
2. ~~Milestone 3a — action pipeline foundation~~ (implemented on `feat/action-pipeline`)
3. **Milestone 3b — AI proposer**: natural-language/command layer that may only *propose* actions through the app API; approval stays human. Base44/AI consumers never receive Crew credentials.

## Current blockers

- AI providers: owner's OpenAI key has no credits (429); OpenRouter free-tier quota tight. Code now surfaces truthful per-provider errors; add OpenAI billing or await OpenRouter window.
- Verification workflow upgraded: Playwright screenshot harness against isolated instance now gates all UI changes.

## Next action

Merge `feat/action-pipeline` after review; design the proposer interface (local command + later Base44) against the pipeline's propose-only boundary.
