# Phase 13 Deferred Items

## Plan 13-04

- **Pre-existing FastAPI/Starlette deprecations:** Relevant MCP and Operations
  regressions pass, but importing the existing test client emits Starlette's
  `httpx` integration deprecation, and `src/mcp_server/app.py:148` still uses
  FastAPI's deprecated `on_event` startup hook. Neither warning is caused by
  Plan 13-04, so the curator/tool implementation did not modify those surfaces.

## Plan 13-07

- **Pre-existing repository-wide Ruff findings:** `uv run ruff check .` still
  reports 27 findings in unrelated legacy utility scripts, including
  `infra/scripts/generate_digital_twin_builder.py`,
  `infra/scripts/push_digital_twin_builder.py`, and pre-existing
  `scripts/delete-lakehouse-tables.py`, `scripts/deploy-relationship-suggestion-agent.py`,
  and `scripts/validate-lakehouse-tables.py`. Plan 13-07's complete changed-file
  Ruff target passes; these unrelated findings were not modified.
