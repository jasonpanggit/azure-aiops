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

## Plan 13-13

- **Pre-existing Next.js static-export failures:** `npm run build` compiles the
  Phase 13 UI and completes lint/type validation, then fails while prerendering
  `/exposure`, `/exposure/defender-posture`, and
  `/exposure/patch-priorities` because those unrelated routes call
  `useSearchParams()` outside a Suspense boundary. Plan 13-13 does not modify
  any Exposure route; the full 54-file/520-test web regression suite,
  TypeScript, and ESLint gates pass.

## Plan 13-16

- **Pre-existing ontology graph regression failures:** The full `uv run pytest
  -q` suite reaches three failures in
  `tests/test_graph_network_traversal.py` and
  `tests/test_operational_context_graph_v2_hardening.py`. They fail inside
  unchanged `src/ontology/ontology_sync.py` validation paths; Plan 13-16 does
  not modify those files. The complete 170-test Plan 13-16 gate passes.
- **Pre-existing repository-wide Ruff findings:** `uv run ruff check .` still
  reports the same 27 unrelated findings already recorded for Plan 13-07 in
  legacy utility scripts. Ruff passes for every Plan 13-16 source and test
  file.
