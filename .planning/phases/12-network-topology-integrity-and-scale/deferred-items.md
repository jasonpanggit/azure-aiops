# Phase 12 Deferred Items

## Plan 12-06

- **Pre-existing full-repository Ruff findings:** `ruff check .` reports 27 findings in
  `infra/scripts/` and `scripts/` files untouched by Plan 12-06 (import ordering,
  performance simplifications, executable-bit checks, broad exceptions, and redundant
  f-strings/noqa directives). The scoped Ruff gate over every Python file changed by
  Plan 12-06 passes. These unrelated findings were not modified.
