# Phase 03.1 Deferred Items

## 2026-09-05 — Plan 03.1-05

- `uv run ruff check .` reports 27 pre-existing findings in unrelated infrastructure
  and maintenance scripts, including `infra/scripts/generate_digital_twin_builder.py`,
  `infra/scripts/push_digital_twin_builder.py`,
  `infra/scripts/push_inventory_refresh_pipeline.py`,
  `scripts/delete-lakehouse-tables.py`,
  `scripts/deploy-relationship-suggestion-agent.py`, and
  `scripts/validate-lakehouse-tables.py`. All Plan 03.1-05 changed Python files pass
  Ruff; the unrelated findings were not modified.
