---
phase: quick-260920-f9f
plan: "01"
subsystem: api
tags: [providers, readiness, startup, ordering]
requires: []
provides:
  - Stable required-first startup refresh ordering for scheduled providers
  - Deterministic regression coverage for optional blocking and required failure
affects: [provider-runtime, readiness]
actuals:
  tasks: 1
  commits: 1
tech-stack:
  added: []
  patterns:
    - Stable two-class traversal without changing provider classification
key-files:
  created: []
  modified:
    - src/api/providers.py
    - tests/test_api_providers.py
key-decisions:
  - "Partition only the scheduled refresh traversal: required first, optional second, stable within each class."
  - "Preserve serialized refresh, retry, publication, liveness, and readiness behavior."
requirements-completed: [QUICK-260920-F9F]
coverage:
  - id: D1
    description: "Required providers publish before an optional-first blocker."
    requirement: QUICK-260920-F9F
    verification:
      - kind: unit
        ref: "tests/test_api_providers.py::test_scheduled_required_providers_publish_before_optional_blocker"
        status: pass
    human_judgment: false
  - id: D2
    description: "Required provider failures remain unavailable and fail readiness closed."
    requirement: QUICK-260920-F9F
    verification:
      - kind: unit
        ref: "tests/test_api_providers.py::test_required_provider_failure_remains_fail_closed_after_priority"
        status: pass
    human_judgment: false
completed: 2026-09-20
status: complete
---

# Quick Task 260920-f9f: Required Provider Startup Ordering

**Scheduled required providers now refresh and publish before optional provider work can delay startup readiness, while preserving stable registration order inside both classes.**

## Accomplishments

- Changed only `ProviderRuntime._refresh_locked` to traverse scheduled required providers before scheduled optional providers.
- Added an event-gated regression proving required instances publish before an optional provider blocks the serialized refresh.
- Added a required-failure regression proving unavailable state, retry metadata, and degraded readiness remain fail-closed.
- Preserved deferred-provider exclusion and stable order within the required and optional groups.

## Task Commit

1. **Required-first provider startup** - `4b4e95cb`

## Pull Request

- [#238](https://github.com/jasonpanggit/azure-aiops/pull/238) - open against `main`; Unified deployment session notified.

## Files Modified

- `src/api/providers.py` - Applies the stable required-first scheduled traversal.
- `tests/test_api_providers.py` - Adds deterministic ordering and fail-closed regressions.

## Decisions Made

- Kept refresh serialized under the existing lock; no concurrency, route, readiness, provider-classification, retry, or configuration changes were introduced.
- Used the generic runtime seam rather than production-specific fixtures because the traversal applies uniformly to every provider registry.

## Deviations from Plan

- The initial generated plan proposed new runtime and HTTP test cases. The coordinating session narrowed execution to the two-file root-cause fix; unchanged runtime and HTTP suites were run in full instead.

## Verification

- `uv run --extra test pytest -q tests/test_api_providers.py::test_scheduled_required_providers_publish_before_optional_blocker tests/test_api_providers.py::test_required_provider_failure_remains_fail_closed_after_priority` - 2 passed.
- `uv run --extra test pytest -q tests/test_api_providers.py tests/test_api_runtime.py tests/test_api_http.py` - 139 passed with existing deprecation warnings.
- `uv run --extra test ruff check src/api/providers.py tests/test_api_providers.py tests/test_api_runtime.py tests/test_api_http.py` - passed.
- `git diff --check` - passed.

## Residual Risk

- Refresh remains intentionally serial, so optional providers can still delay completion of the full refresh after all required providers have published.
- Production provider ordering is covered through the registry-independent traversal and broader runtime tests, not a new production-registration-specific assertion.

## Self-Check: PASSED

The implementation commit contains exactly the provider runtime and focused test changes. No Azure, deployment, or external service operation was performed.

---
*Quick task: 260920-f9f*
*Completed: 2026-09-20*
