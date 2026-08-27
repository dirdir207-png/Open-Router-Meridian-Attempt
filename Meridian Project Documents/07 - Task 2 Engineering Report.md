# Task 2 Report: Atomic and Idempotent Action Execution

## Status

Implemented and verified atomic, exactly-once local action claiming before any external executor call. The proposal → approval → execute → verify boundary remains intact. Financial mutations are not retried, and uncertain writes remain failed outcomes that explicitly require state verification.

## Implementation

- Added `ActionState.EXECUTING` between `APPROVED` and `EXECUTED`/`FAILED`.
- Added `execution_key` and `execution_started_at` to new `action_requests` tables.
- Added an idempotent, non-destructive startup migration that adds either missing execution column to existing `action_requests` tables while preserving existing rows.
- Added `ActionStore.claim_for_execution(request_id, execution_key)` using `BEGIN IMMEDIATE` and one conditional `UPDATE ... WHERE id=? AND state='approved'`.
- A claim that does not update exactly one row raises `IllegalTransitionError("Action is not available for execution")`.
- Updated `execute_approved_action` to accept an optional execution key, generate a UUID key when absent, atomically claim first, and invoke the registered executor only after the claim succeeds.
- Preserved the existing no-retry `uncertain_write` contract: the action becomes `FAILED`, retains `verify_state=True`, and does not run its verifier.
- The HTTP execute endpoint keeps its existing interface. Its first successful request returns the persisted execution metadata; a repeated request returns HTTP 409 without a second executor call.

## Files Changed

- `crew/actions.py`
- `crew/executors.py`
- `tests/crew/test_actions.py`
- `tests/crew/test_executors.py`
- `tests/test_app_crew_integration.py`

The unrelated untracked `tmp/` directory and Connected Billers documentation were not touched.

## TDD Evidence

### Baseline

After installing declared dependencies (using compatible `cbor2==5.6.5` because `6.1.4` required an unavailable Rust compiler on this x86_64 Python environment):

```text
$ pytest tests/crew/test_actions.py tests/crew/test_executors.py tests/test_app_crew_integration.py -q
...................................                                      [100%]
35 passed in 5.28s
```

### RED: concurrent regression

```text
$ pytest tests/crew/test_executors.py -k concurrent -q
F                                                                        [100%]
E       AssertionError: assert 2 == 1
E        +  where 2 = len([{'amount': 100}, {'amount': 100}])
1 failed, 7 deselected in 0.15s
```

This was the intended failure: two threads released by a barrier both passed the non-atomic approval read and entered the external executor.

### RED: claim, migration, and HTTP metadata

```text
$ pytest tests/crew/test_actions.py -k 'full_lifecycle or illegal_transitions or migrates_execution' -q
FFF                                                                      [100%]
AttributeError: 'ActionStore' object has no attribute 'claim_for_execution'
3 failed, 5 deselected in 0.16s

$ pytest tests/test_app_crew_integration.py -k action_pipeline_full_lifecycle -q
F                                                                        [100%]
KeyError: 'execution_key'
1 failed, 20 deselected in 1.14s
```

### GREEN: focused checkpoints

```text
$ pytest tests/crew/test_executors.py -k concurrent -q
.                                                                        [100%]
1 passed, 7 deselected in 0.64s

$ pytest tests/crew/test_actions.py -k 'full_lifecycle or illegal_transitions or migrates_execution' -q
...                                                                      [100%]
3 passed, 5 deselected in 0.10s

$ pytest tests/test_app_crew_integration.py -k action_pipeline_full_lifecycle -q
.                                                                        [100%]
1 passed, 20 deselected in 1.11s
```

## Concurrency Evidence

The regression uses two worker threads and a start barrier against one approved request. Before the fix, both external executor calls were observed. After the atomic claim, exactly one worker returns the verified terminal record and exactly one receives the expected claim conflict.

The focused concurrency regression was then run 10 consecutive times:

```text
$ for iteration in {1..10}; do pytest tests/crew/test_executors.py -k concurrent -q || exit 1; done
10/10 runs passed; every run reported 1 passed, 7 deselected.
```

## Final Verification

```text
$ ruff check crew/actions.py crew/executors.py tests/crew/test_actions.py tests/crew/test_executors.py tests/test_app_crew_integration.py
All checks passed!

$ git diff --check
(no output; exit 0)

$ pytest tests/crew/test_actions.py tests/crew/test_executors.py tests/test_app_crew_integration.py -q
.....................................                                    [100%]
37 passed in 1.84s

$ pytest -q
s...................................................s................... [ 58%]
....................................................                     [100%]
122 passed, 2 skipped in 2.92s
```

## Self-Review

- Confirmed the exact conditional claim SQL and required error message match the task brief.
- Confirmed `BEGIN IMMEDIATE` encloses the claim update and record read in one transaction.
- Confirmed the executor lookup, executor call, success recording, and verification all happen after a successful claim.
- Confirmed old action rows survive migration and receive null execution metadata.
- Confirmed a caller-supplied key is persisted and HTTP execution generates a non-empty key.
- Confirmed a repeated HTTP execute request returns 409 and leaves the external call count at one.
- Confirmed `uncertain_write` remains `FAILED`, retains `verify_state=True`, receives no automatic retry, and bypasses the verifier.
- Confirmed no credentials or provider secrets were added to action records, browser payload inputs, logs, or fixtures.
- Confirmed only task-scoped source/tests were staged for the requested commit; unrelated untracked content remains untouched.

## Concerns / Residual Safety Behavior

- If a process stops after claiming but before recording the external outcome, the action intentionally remains `executing`. It cannot be executed again automatically; an operator must verify external state before any reconciliation. This favors duplicate-transfer prevention over automatic recovery.
- The execution key currently provides local idempotency and auditability. The existing Crew executor contract accepts only action parameters and exposes no provider idempotency-key field, so this task does not claim provider-side idempotency.

---

## Fix Round 1 — Atomic Transitions, Uncertain Exceptions, Concurrent Migration

### Findings Addressed

1. Generic action transitions now use a conditional `UPDATE` constrained by both request ID and the state observed during transition validation. A zero-row update raises `IllegalTransitionError("Action state changed before transition completed")`, so a stale expiry cannot overwrite an execution claim or terminal result.
2. Exceptions raised by the external executor now persist `verify_state=True` alongside `error_code="executor_exception"`. The executor is called once, no automatic retry occurs, and the verifier is not called because the provider outcome is uncertain.
3. `ActionStore` initialization now acquires a SQLite schema write lock with `BEGIN IMMEDIATE` before creating/inspecting/migrating `action_requests`. Concurrent initializers therefore serialize their column checks and cannot both attempt the same `ALTER TABLE`.

### Files Changed in Fix Round

- `crew/actions.py`
- `crew/executors.py`
- `tests/crew/test_actions.py`
- `tests/crew/test_executors.py`

The untracked `tmp/`, `Meridian Project Documents.zip`, and consolidated documentation were not touched.

### Named Regression Coverage

- `test_stale_expiry_cannot_overwrite_execution_claim`
  - Uses two `ActionStore` instances and distinct SQLite connections.
  - Deterministically pauses expiry after its `approved` read, commits the execution claim, resumes expiry, and requires the stale transition to conflict.
  - Confirms the protected action remains `executing` and can continue to `executed` and `verified`.
- `test_executor_exception_persists_uncertain_outcome_without_retry_or_verification`
  - Confirms one executor call, zero verifier calls, persisted `FAILED` state, `error_code="executor_exception"`, and `verify_state=True`.
- `test_concurrent_store_initialization_migrates_legacy_schema_once`
  - Starts two initializers together against one legacy database and forces the old implementation's duplicate-`ALTER TABLE` window.
  - Confirms both initializers succeed, both execution columns exist, and the legacy row is preserved.

### RED Evidence

```text
$ pytest tests/crew/test_actions.py -k stale_expiry -q
F                                                                        [100%]
E           Failed: DID NOT RAISE <class 'crew.actions.IllegalTransitionError'>
1 failed, 9 deselected in 0.19s

$ pytest tests/crew/test_executors.py -k executor_exception -q
F                                                                        [100%]
E       KeyError: 'verify_state'
1 failed, 7 deselected in 0.13s

$ pytest tests/crew/test_actions.py -k concurrent_store_initialization -q
F                                                                        [100%]
E       sqlite3.OperationalError: duplicate column name: execution_key
1 failed, 9 deselected in 0.67s
```

Each failure matched the reviewed defect: stale transition overwrite, missing uncertainty signal, and duplicate-column startup race.

### GREEN Evidence

```text
$ pytest tests/crew/test_actions.py -k 'stale_expiry or concurrent_store_initialization' -q
..                                                                       [100%]
2 passed, 8 deselected in 0.70s

$ pytest tests/crew/test_executors.py -k executor_exception -q
.                                                                        [100%]
1 passed, 7 deselected in 0.09s
```

### Fix-Round Verification

```text
$ git diff --check
(no output; exit 0)

$ ruff check crew/actions.py crew/executors.py tests/crew/test_actions.py tests/crew/test_executors.py tests/test_app_crew_integration.py
All checks passed!

$ pytest tests/crew/test_actions.py tests/crew/test_executors.py tests/test_app_crew_integration.py -q
.......................................                                  [100%]
39 passed in 2.44s

$ pytest -q
s.....................................................s................. [ 57%]
......................................................                   [100%]
124 passed, 2 skipped in 3.49s
```

### Fix-Round Self-Review

- Confirmed every generic transition's write compares against the exact state previously validated; stale approval, rejection, expiry, execution, verification, and failure writes cannot overwrite a competing transition.
- Confirmed transition row-count validation occurs in the same transaction as the conditional update and the returned row is read before commit.
- Confirmed schema inspection and all execution-column additions occur under one `BEGIN IMMEDIATE` transaction.
- Confirmed migration remains non-destructive and sequentially idempotent while becoming safe for concurrent initialization.
- Confirmed executor exceptions remain non-retryable and do not claim provider success; the persisted payload explicitly directs state verification.
- Confirmed the execution key remains accurately described as local audit/idempotency metadata only; no provider-side idempotency claim was added.

### Remaining Concern

- The previously documented recovery posture is unchanged: a process interruption after claim leaves the action `executing` until external state is manually verified. This is deliberate duplicate-transfer protection, not an automatically retryable state.

---

## Fix Round 2 — Expiry Sweep Claim Conflict

### Finding Addressed

`expire_stale_approvals` now handles `IllegalTransitionError` around each individual `store.expire` call. When an approved snapshot is claimed before expiry, the sweep skips that now-ineligible request and continues processing later stale approvals. The pending endpoint therefore does not return 500 for this expected concurrency race.

### Files Changed in Fix Round

- `crew/executors.py`
- `tests/crew/test_executors.py`
- `tests/test_app_crew_integration.py`

The untracked `tmp/`, `Meridian Project Documents.zip`, and documentation were not touched.

### Named Regression Coverage

- `test_expiry_sweep_tolerates_claim_race_and_continues`
  - Selects two stale approved candidates, deterministically claims the first after selection, and confirms the sweep skips that conflict.
  - Confirms the claimed request stays `executing`, the second candidate becomes `expired`, and only the successfully expired ID is returned.
- `test_pending_endpoint_tolerates_claim_during_expiry_sweep`
  - Reproduces the same deterministic race through authenticated `GET /api/actions/pending`.
  - Confirms HTTP 200, no pending proposals, the claimed action remains `executing`, and the other stale action is expired.

### RED Evidence

```text
$ pytest tests/crew/test_executors.py -k expiry_sweep_tolerates -q
F                                                                        [100%]
E   crew.actions.IllegalTransitionError: Cannot move action from executing to expired
1 failed, 8 deselected in 0.16s

$ pytest tests/test_app_crew_integration.py -k pending_endpoint_tolerates -q
F                                                                        [100%]
E       assert 500 == 200
1 failed, 21 deselected in 1.20s
```

### GREEN Evidence

```text
$ pytest tests/crew/test_executors.py -k expiry_sweep_tolerates -q
.                                                                        [100%]
1 passed, 8 deselected in 0.12s

$ pytest tests/test_app_crew_integration.py -k pending_endpoint_tolerates -q
.                                                                        [100%]
1 passed, 21 deselected in 1.12s
```

### Fix-Round Verification

```text
$ git diff --check
(no output; exit 0)

$ ruff check crew/executors.py tests/crew/test_executors.py tests/test_app_crew_integration.py
All checks passed!

$ pytest tests/crew/test_actions.py tests/crew/test_executors.py tests/test_app_crew_integration.py -q
.........................................                                [100%]
41 passed in 2.43s

$ pytest -q
s.....................................................s................. [ 56%]
........................................................                 [100%]
126 passed, 2 skipped in 3.64s
```

### Fix-Round Self-Review

- Confirmed conflict handling is scoped to each expiry candidate, so one race cannot abort the sweep.
- Confirmed IDs are appended only after successful expiry; skipped claims are not falsely reported as expired.
- Confirmed no retry occurs and an `executing` action remains unchanged.
- Confirmed the HTTP route requires no special error handling because the sweep absorbs this expected transition race at its ownership boundary.
- Confirmed the execution key remains local audit/idempotency metadata only; no provider-side idempotency claim was added.

### Remaining Concern

- None introduced by this fix. The intentional manual-verification posture for interrupted `executing` actions remains unchanged.
