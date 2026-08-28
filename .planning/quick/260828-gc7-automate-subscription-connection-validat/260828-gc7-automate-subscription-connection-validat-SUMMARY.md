---
phase: 08-fabric-migration
plan: quick-260828-gc7
subsystem: api-ui
tags: [subscription-connections, validation, sync, fastapi, react]
requires:
  - phase: 08-resource-identity-plane
    provides: Connection registry, validation, health, and API-triggered sync services
provides:
  - Automatic validation and conditional initial sync during connection creation
  - UI lifecycle status reporting without manual Validate or Sync controls
affects: [connection onboarding, inventory sync]
actuals:
  tokens: 5352
  tasks: 2
  commits: 2
tech-stack:
  added: []
  patterns: [service-owned create lifecycle, health polling from returned sync state]
key-files:
  created: []
  modified:
    - src/onboarding/service.py
    - src/api/routers/connections.py
    - tests/test_subscription_onboarding.py
    - tests/test_api_http.py
    - web/src/app/connections/page.tsx
    - web/src/app/connections/page.test.tsx
    - web/src/lib/services.ts
    - web/src/lib/types.ts
key-decisions:
  - "Keep standalone validate and sync API routes available while moving the default create flow into the service."
  - "Allow optional validation degradation to queue sync, but persist required validation failures without starting sync."
requirements-completed: [INV-10, INV-11]
coverage:
  - id: D1
    description: "Connection creation persists validation health and queues one initial sync only when required checks pass."
    requirement: INV-10
    verification:
      - kind: integration
        ref: "tests/test_subscription_onboarding.py"
        status: pass
      - kind: integration
        ref: "tests/test_api_http.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Connections UI reports automatic validation and sync outcomes and removes manual lifecycle buttons."
    requirement: INV-11
    verification:
      - kind: automated_ui
        ref: "web/src/app/connections/page.test.tsx"
        status: pass
    human_judgment: false
duration: 4min
completed: 2026-08-28
status: complete
---

# Phase 08 Plan quick-260828-gc7: Automatic Subscription Connection Lifecycle Summary

**Subscription creation now validates Azure access, queues a scoped initial sync when safe, and reports the full lifecycle in the Connections UI without manual Validate or Sync actions.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-28T11:47:32+08:00
- **Completed:** 2026-08-28T11:51:30+08:00
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Added service-owned create → validation → conditional initial async sync orchestration.
- Returned persisted validation and initial-sync state in the create response while retaining secret redaction and authorization.
- Updated the Connections page to poll health for automatic sync progress and terminal errors, with only Edit and Delete row actions.
- Added targeted backend and frontend coverage for healthy, degraded, failed-validation, failed-sync, response hygiene, and UI control removal.

## Task Commits

1. **Task 1: Make connection creation validate and conditionally queue initial sync** - `36e19d83` (feat)
2. **Task 2: Replace manual connection lifecycle controls with automatic post-create status** - `f1f8c510` (feat)

## Files Created/Modified

- `src/onboarding/service.py` - Owns validation persistence and conditional initial sync queueing.
- `src/api/routers/connections.py` - Uses the service lifecycle for POST creation.
- `tests/test_subscription_onboarding.py` - Covers lifecycle ordering and validation outcomes.
- `tests/test_api_http.py` - Covers response envelope, authorization, and secret hygiene.
- `web/src/app/connections/page.tsx` - Reports automatic validation/sync state and removes manual controls.
- `web/src/app/connections/page.test.tsx` - Covers automatic success/failure and action removal.
- `web/src/lib/services.ts`, `web/src/lib/types.ts` - Describe the lifecycle create response.

## Decisions Made

- Kept `/validate`, `/sync`, and `/health` API compatibility routes unchanged.
- Used the existing shared async executor and health endpoint polling path rather than adding a client-side sync request or new job system.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected frontend lifecycle test fixtures and optional validation typing**
- **Found during:** Task 2
- **Issue:** Existing tests expected the removed manual Sync control, and the new response's optional failure list was not represented safely in the TypeScript contract.
- **Fix:** Updated targeted fixtures/assertions for automatic creation and made failed validation details null-safe.
- **Files modified:** `web/src/app/connections/page.test.tsx`, `web/src/lib/types.ts`, `web/src/app/connections/page.tsx`
- **Verification:** Targeted Vitest and `npx tsc --noEmit` pass.
- **Committed in:** `f1f8c510`

---

**Total deviations:** 1 auto-fixed (Rule 1)
**Impact on plan:** Necessary test and type corrections only; no unrelated scope added.

## Issues Encountered

- The host-level `pytest` command used the wrong Python environment and failed collection due to missing `onboarding` and an incompatible installed `pydantic-core`. The prescribed backend tests passed using the repository environment via `PYTHONPATH=src uv run pytest`.
- Frontend tests emitted the existing Vite CJS API deprecation warning; tests still passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Automatic connection onboarding is ready for API/UI verification. Existing standalone operational endpoints remain available to non-UI consumers.

## Self-Check: PASSED

- Summary file exists at the requested quick-task path.
- Task commits `36e19d83` and `f1f8c510` exist in git history.
- Targeted backend tests, frontend tests, and TypeScript validation passed.

---
*Phase: 08-fabric-migration*
*Completed: 2026-08-28*
