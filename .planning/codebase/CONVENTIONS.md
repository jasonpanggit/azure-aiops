# Coding Conventions

**Analysis Date:** 2026-08-24

## Naming Patterns

**Files:**
- Python modules use lowercase `snake_case`, for example `src/hermes_arg_connector/config.py`, `src/api/errors.py`, and `src/intelligence/vulnerability/enrichment_cache.py`.
- Python tests use `test_<feature>.py` naming under `tests/`, for example `tests/test_api_semantic.py` and `tests/test_subscription_cli.py`.
- Frontend components and pages use `PascalCase` for component files and route-oriented lowercase segments for app routes, for example `web/src/components/ErrorBoundary.tsx` and `web/src/app/agents/page.tsx`.

**Functions:**
- Python functions/methods use `snake_case`, with private helpers prefixed `_` such as `_register_openapi` and `_error_body` in `src/api/app.py`.
- TypeScript functions use `camelCase`, for example `listAllConnections` in `web/src/lib/services.ts` and `mockFetch` in `web/src/lib/api-client.test.ts`.
- Test names are behavior-driven: `test_unknown_subject_is_404_not_500` in `tests/test_api_semantic.py` and `it("throws a typed ApiError for an error contract response")` in `web/src/lib/api-client.test.ts`.

**Variables:**
- Python locals/params are `snake_case`; constants use uppercase (for example `TOKEN`, `HEADERS` in `tests/test_api_semantic.py`).
- TypeScript variables are `camelCase` and often typed explicitly for API envelopes and domain payloads, as in `web/src/app/agents/page.test.tsx`.

**Types:**
- Python classes use `PascalCase` (`ApiError` in `src/api/errors.py`, `ConnectorConfig` in `src/hermes_arg_connector/config.py`).
- TypeScript interfaces/types use `PascalCase` (`CopilotReply`, `CopilotToolCall` in `web/src/lib/services.ts`).

## Code Style

**Formatting:**
- Python style is 4-space indentation with pervasive type hints and `from __future__ import annotations`, visible in `src/api/app.py`, `src/api/errors.py`, and `tests/test_subscription_cli.py`.
- TypeScript/React style uses semicolons, double quotes, and trailing commas in multiline constructs, as seen in `web/src/lib/services.ts` and `web/src/components/ErrorBoundary.tsx`.
- Structured immutable configuration is implemented via frozen dataclasses (`@dataclass(frozen=True)` in `src/hermes_arg_connector/config.py`).

**Linting:**
- Python linting is Ruff-driven via `pyproject.toml` (`[tool.ruff.lint.per-file-ignores]`).
- CI enforces Ruff and Pytest in `.github/workflows/ci.yml` using `python -m ruff check src tests` and `python -m pytest`.
- Frontend lint entrypoint is `next lint` in `web/package.json` (`npm run lint`).

## Import Organization

**Order:**
1. Future import first in Python modules (`from __future__ import annotations`), for example `src/api/app.py`.
2. Standard library imports.
3. Third-party imports.
4. Project-local imports (relative or aliased), for example `from .routers import ...` in `src/api/app.py` and `@/lib/services` in `web/src/app/agents/page.test.tsx`.

**Path Aliases:**
- Frontend alias `@/* -> ./src/*` is configured in `web/tsconfig.json` and mirrored in `web/vitest.config.ts`.
- Python code uses package imports rooted at `src/` packages (for example `from api.app import create_app` in `tests/test_api_semantic.py`).

## Error Handling

**Patterns:**
- API boundary translates exceptions to stable machine-readable error codes through `translate()` and `ApiError` in `src/api/errors.py`.
- Sensitive content is scrubbed before leaving the boundary (`scrub()` and redaction logic in `src/api/errors.py`).
- Request-level exception handling is centralized in FastAPI exception handlers in `src/api/app.py`.
- Domain/config validation prefers explicit `ValueError`/`TypeError` checks in constructors and loaders (for example `ConnectorConfig.__post_init__` in `src/hermes_arg_connector/config.py`).
- Frontend request handling expects typed API failures (`ApiError`) and asserts contract fields in `web/src/lib/api-client.test.ts`.

## Logging

**Framework:**
- Python `logging` is used in API and service modules (`logger` in `src/api/app.py`, `_LOGGER` in `src/intelligence/vulnerability/enrichment_cache.py`).

**Patterns:**
- Request logging includes correlation IDs and status (`src/api/app.py`).
- Background refresh/cache failures are logged with contextual fields and stack traces (`src/api/app.py`, `src/intelligence/vulnerability/enrichment_cache.py`).
- Secret-bearing details are avoided in public-facing error payloads (`src/api/errors.py`).

## Comments

**When to Comment:**
- Modules and complex flows use explanatory docstrings for contract, security, and architecture intent (`src/api/errors.py`, `src/intelligence/vulnerability/enrichment_cache.py`).
- Inline comments are used sparingly for non-obvious operational rationale (for example background refresh strategy in `src/api/app.py`).

**JSDoc/TSDoc:**
- TypeScript uses targeted JSDoc for public API wrappers and behavior guarantees (`SUPPORTED_SEARCH_PHRASES`, `copilotApi.ask`, and `copilotApi.investigate` in `web/src/lib/services.ts`).

## Function Design

**Size:**
- Route wiring and orchestration are centralized, with helper extraction for reusable behavior (`_route_label`, `_correlation_id`, `_register_openapi` in `src/api/app.py`).

**Parameters:**
- Python favors typed parameters and keyword-only options for configurable behavior (`EnrichmentCache.__init__` and `get` in `src/intelligence/vulnerability/enrichment_cache.py`).
- Frontend service methods pass structured request objects instead of ad hoc strings where payloads are non-trivial (`web/src/lib/services.ts`).

**Return Values:**
- Python returns explicit typed tuples/objects for stateful semantics, such as `(hit, value)` and `(found, value, age)` in `src/intelligence/vulnerability/enrichment_cache.py`.
- Frontend service calls consistently return `Envelope<T>` via `apiRequest<T>` in `web/src/lib/services.ts`.

## Module Design

**Exports:**
- Python modules expose focused domain units; selective `__all__` is used for explicit export in `src/intelligence/vulnerability/enrichment_cache.py`.
- Frontend uses named exports for grouped API clients (`connectionsApi`, `contextApi`, `operationsApi`, `networkApi`) in `web/src/lib/services.ts`.

**Barrel Files:**
- No global barrel-file pattern is enforced; modules are imported directly by feature path across Python and frontend code.

---

*Convention analysis: 2026-08-24*
