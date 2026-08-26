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
