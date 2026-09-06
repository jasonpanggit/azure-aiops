# Phase 13 Deferred Items

## Plan 13-04

- **Pre-existing FastAPI/Starlette deprecations:** Relevant MCP and Operations
  regressions pass, but importing the existing test client emits Starlette's
  `httpx` integration deprecation, and `src/mcp_server/app.py:148` still uses
  FastAPI's deprecated `on_event` startup hook. Neither warning is caused by
  Plan 13-04, so the curator/tool implementation did not modify those surfaces.
