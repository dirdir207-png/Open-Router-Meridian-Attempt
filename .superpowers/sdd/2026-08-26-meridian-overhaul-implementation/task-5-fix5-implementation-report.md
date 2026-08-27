# Task 5 Fix Round 5 — Timestamp precision grammar

## Fix commit

`11e07eb fix: reject unsupported high-precision timestamps`

## Finding resolved

`canonical_occurred_at` previously checked fractional precision only when the
input used uppercase `T` or a space separator. Python's
`datetime.fromisoformat()` also accepts arbitrary one-character separators,
so lowercase `t` and `X` values with more than six fractional digits were
accepted and silently truncated.

The shared timestamp helper now validates an explicit supported grammar before
calling `fromisoformat()`. It retains the existing safe legacy spellings:
uppercase `T` or space date/time separators, extended or basic clock fields,
dot or comma fractional seconds, and standard `Z`/numeric offsets. Unsupported
separators are rejected, and a broad pre-check still returns the explicit
six-digit precision error for excess fractional input before parsing.

## Tests added

- Repository writes reject seven fractional digits with uppercase `T`,
  lowercase `t`, and `X` separators; no transaction is persisted.
- Migration tests seed lowercase `t` and `X` seven-digit legacy values and
  verify both are quarantined (`occurred_at_valid = 0`) with the original
  `occurred_at` and `source_updated_at` provenance preserved.
- Existing offset, fixed-width ordering, migration conversion, and
  pre-upgrade cursor tests remain green.

## TDD evidence

The new parameterized cases were run before the parser change:

```text
pytest -q tests/meridian/test_repository.py -k 'more_than_microsecond_precision'
1 passed, 2 failed, 12 deselected

pytest -q tests/meridian/test_migrations.py -k 'unsupported_high_precision_separators'
2 failed, 10 deselected
```

The failures demonstrated the exact lowercase-`t`/`X` silent truncation. The
minimal grammar validation then made the focused cases pass.

## Verification

```text
pytest -q tests/meridian/test_migrations.py tests/meridian/test_repository.py
27 passed

pytest -q tests/meridian
80 passed

pytest -q
208 passed, 17 skipped

ruff check .
All checks passed!

git diff --check
exit 0
```

The pre-existing uncommitted `static/css/meridian/shell.css` UI change was not
modified or included in the fix commit.
