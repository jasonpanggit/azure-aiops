# Coding Conventions

**Analysis Date:** 2026-08-23

## Naming Patterns

**Files:**
- Python modules use lowercase `snake_case`, for example `src/hermes_arg_connector/network_normalize.py` and `src/api/dependencies.py`.
- Tests use `test_<area>.py`; scenario/support modules use descriptive lowercase names such as `tests/change_scenario.py`.

**Functions:**
- Functions and methods use `snake_case`; private helpers are prefixed with `_`, as in `_load_json` in `src/hermes_arg_connector/azure.py`.
- Test functions use `test_<behavior>` and favor behavioral descriptions, for example `test_unknown_subject_is_404_not_500` in `tests/test_api_semantic.py`.

**Variables:**
- Local variables and parameters use `snake_case`; constants use uppercase names such as `TOKEN` and `HEADERS` in `tests/test_api_semantic.py`.
- Boolean names are descriptive (`raise_server_exceptions`, `retain_raw_queries`, `fail`).

**Types:**
- Classes use `PascalCase` (`ConnectorConfig`, `AzureCliArgClient`, `ApiError`).
- Type aliases and protocols follow class-style naming; generic collections use built-in typing syntax such as `list[dict]` and `Mapping[str, str]`.

## Code Style

**Formatting:**
- Python code targets Python 3.11+ and consistently uses `from __future__ import annotations`; see `src/hermes_arg_connector/config.py` and `tests/test_api_semantic.py`.
- No standalone formatter configuration is detected. Keep lines readable, use four-space indentation, trailing commas in multiline calls, and explicit return annotations where practical.
- Dataclasses are preferred for structured immutable/configuration values, e.g. `ConnectorConfig` in `src/hermes_arg_connector/config.py` and `ApiError` in `src/api/errors.py`.

**Linting:**
- Ruff is the project lint tool and is an optional test dependency, declared in `pyproject.toml`.
- `__init__.py` has explicit Ruff per-file ignores for `N999` and `E402` in `pyproject.toml`; do not broaden ignores without a specific reason.
- The web app exposes `npm run lint` through `web/package.json`, using Next.js linting.

## Import Organization

**Order:**
1. `from __future__ import annotations` when the module uses postponed annotations.
2. Python standard library imports, grouped alphabetically or by purpose.
3. Third-party imports such as `pytest`, `httpx`, `fastapi`, and Azure SDK modules.
4. Project imports, with package imports before relative imports where both are present.

Examples are `src/hermes_arg_connector/azure.py` and `tests/test_api_semantic.py`.

**Path Aliases:**
- No Python path alias scheme is detected. Use package imports such as `from api.app import create_app` or relative imports within `hermes_arg_connector`.
- Frontend aliases are not detected in the inspected configuration; follow the existing import style in `web/`.

## Error Handling

**Patterns:**
- Validate configuration and external payloads at boundaries and raise specific built-in exceptions (`ValueError`, `TypeError`, `RuntimeError`), as in `src/hermes_arg_connector/config.py` and `src/hermes_arg_connector/azure.py`.
- Chain translated exceptions with `raise ... from exc` when preserving the cause, as in `src/hermes_arg_connector/azure.py` and `src/hermes_arg_connector/onelake_fs.py`.
- Normalize domain failures at the API boundary through `translate()` and stable `ApiError` codes in `src/api/errors.py`; clients should rely on `code`, not message text.
- Never expose secrets or raw upstream/internal error text across the API boundary. `src/api/errors.py` scrubs messages and redacts secret references.
- CLI commands catch expected operational/configuration exceptions and return a user-facing failure result in `src/hermes_arg_connector/cli.py`.

## Logging

**Framework:** Python `logging` where needed; `src/hermes_arg_connector/locking.py` defines a module logger. There is no detected project-wide logging wrapper.

**Patterns:**
- Keep operational diagnostics at the boundary that can add context, while returning safe errors to callers.
- Use telemetry abstractions for API/agent metrics (`src/api/telemetry.py`) rather than putting instrumentation into tests.
- Do not log credentials, tokens, connection strings, or raw secret-bearing payloads.

## Comments

**When to Comment:**
- Comment non-obvious security, compatibility, boundary, or data-contract decisions; examples include `src/hermes_arg_connector/config.py` URI handling and `src/api/errors.py` secret scrubbing.
- Tests use docstrings/comments to state the regression or contract being protected, as in `tests/test_api_copilot.py` and `tests/test_enrichment_cache.py`.
- Avoid comments that merely restate a line of code.

**JSDoc/TSDoc:**
- Python public classes/functions commonly have concise docstrings, but not every private helper does. Preserve docstrings for public contracts and security-sensitive behavior.
- Frontend documentation conventions are not detected.

## Function Design

**Size:** Keep orchestration in service/route methods and extract deterministic transformations into private helpers; `src/hermes_arg_connector/service.py` and `src/hermes_arg_connector/normalize.py` demonstrate this split.

**Parameters:** Prefer keyword-only options for configuration or behavior switches, typed dataclass/config objects for grouped values, and `Protocol` interfaces for injectable external runners (`src/hermes_arg_connector/azure.py`).

**Return Values:** Return explicit typed values and domain objects/collections. Use `None` only for an intentional absence; distinguish cache misses from cached empty values in `src/intelligence/vulnerability/enrichment_cache.py`.

## Module Design

**Exports:** Keep implementation modules focused by domain (`src/intelligence/`, `src/ontology/`, `src/storage/`, and `src/api/`). Use package `__init__.py` files sparingly.

**Barrel Files:** No broad barrel-file convention is detected. Import concrete modules directly; `src/hermes_arg_connector/__init__.py` uses lazy attribute access to keep optional imports lightweight.

---

*Convention analysis: 2026-08-23*
