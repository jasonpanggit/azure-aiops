---
phase: quick-260910-f2h
plan: "01"
subsystem: activation-recovery
tags: [python, fabric, onelake, replay, activation, tdd]
requires:
  - phase: quick-260909-032
    provides: Activation progress schema and established Fabric/Gold pointer-order transaction
provides:
  - Durable combined activation generations in the production OneLake lakehouse
  - Exact activate replay without Azure connection validation or discovery
  - URI-safe Fabric source-root configuration for local paths and OneLake
  - Fail-closed generation and manifest validation before Fabric publication
  - Historical replay coverage through tables, ontology, Gold, completion, shortcuts, and pointer activation
affects: [activation-cli, fabric-publication, exposure-gold, production-recovery]
actuals:
  tokens: 6233
  tasks: 2
  commits: 5
tech-stack:
  added: []
  patterns:
    - Exact immutable generation replay through DatasetStore.generation_path
    - URI-preserving source-root configuration with local Path compatibility
    - Activation-owned Exposure pointer-store forwarding
key-files:
  created: []
  modified:
    - src/fabric/config.py
    - src/onboarding/activation.py
    - src/onboarding/cli.py
    - fabric.config.deploy.yaml
    - tests/test_fabric_commands.py
    - tests/test_fabric_sync_service.py
    - tests/test_onboarding_activation.py
    - tests/test_subscription_cli.py
key-decisions:
  - "Exact activation replay resolves only generations/<requested-id>; it never consults the current generation pointer."
  - "Replay enters FabricSyncService directly with the activation-owned OneLakeDocumentStore so the established Gold completion and pointer transaction remains authoritative."
  - "Fabric source roots remain resolved Path objects locally and normalized strings for valid OneLake URIs."
patterns-established:
  - "Replay provenance: terminal connections come from the persisted combined manifest while skipped validation and discovery results remain empty mappings."
  - "Fail-closed replay: unsafe, absent, unreadable, or malformed generation input is rejected before runtime construction or Fabric publication."
requirements-completed: [QUICK-260910-F2H]
coverage:
  - id: D1
    description: Normal activation persists combined generations to a URI-safe configured source root and production uses the exact OneLake inventory-source path
    requirement: QUICK-260910-F2H
    verification:
      - kind: integration
        ref: "tests/test_fabric_commands.py and tests/test_onboarding_activation.py"
        status: pass
    human_judgment: false
  - id: D2
    description: Activate exact replay skips upstream discovery and preserves result, progress, publication, Gold, completion, shortcut, and pointer contracts
    requirement: QUICK-260910-F2H
    verification:
      - kind: integration
        ref: "tests/test_onboarding_activation.py, tests/test_subscription_cli.py, and tests/test_fabric_sync_service.py"
        status: pass
    human_judgment: false
  - id: D3
    description: Unsafe, missing, unreadable, and malformed exact generations fail before Fabric publication without latest fallback
    requirement: QUICK-260910-F2H
    verification:
      - kind: integration
        ref: "tests/test_onboarding_activation.py and tests/test_fabric_sync_service.py"
        status: pass
    human_judgment: false
duration: 7min
completed: 2026-09-10
status: complete
---

# Quick Task 260910-f2h: Durable Combined Activation Snapshots and Exact Replay Summary

**Durable OneLake activation generations with exact-ID replay through the established Fabric, Gold, completion, shortcut, and atomic pointer transaction**

## Performance

- **Duration:** 7 min
- **Started:** 2026-09-10T03:00:39Z
- **Completed:** 2026-09-10T03:07:10Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Made `FabricRuntimeConfig.source_data_root` URI-safe: config-relative local roots remain resolved `Path` values, while valid OneLake roots remain normalized strings.
- Added `activate --replay-source-run-id <exact-id>` and an activation replay branch that reads only the requested immutable manifest, skips all connection enumeration/validation/discovery and combined publication, and preserves the established terminal result shape.
- Bound production combined snapshots to the exact existing workspace/lakehouse OneLake root under `Files/aiops/inventory-source`.
- Proved a historical generation is used even when a different generation is current, including normal table and ontology publication, Gold staging/writes, shortcut finalization, completed-version state, and final pointer activation.
- Added fail-closed coverage for traversal-shaped IDs and absent, unreadable, malformed, or provenance-invalid manifests before Fabric runtime construction.

## Task Commits

TDD RED and GREEN gates were committed separately:

1. **Task 1 RED: Define exact activation replay contract** — `9174fe567`
2. **Task 1 GREEN: Replay exact activation generations** — `a59bfa3c5`
3. **Task 2 RED: Cover durable replay finalization** — `48a730dbe`
4. **Task 2 GREEN: Persist activation snapshots in OneLake** — `d1bc7e6db`
5. **Task 2 verification closure: Complete replay input safety cases** — `29fe08814`

## Files Created/Modified

- `src/fabric/config.py` — Preserves OneLake source URIs while retaining config-relative local path resolution.
- `src/onboarding/activation.py` — Adds exact replay resolution, manifest provenance validation, truthful progress, and direct Fabric transaction invocation.
- `src/onboarding/cli.py` — Parses and conditionally forwards `--replay-source-run-id`.
- `fabric.config.deploy.yaml` — Uses the production OneLake combined-snapshot root.
- `tests/test_fabric_commands.py` — Covers local/OneLake runtime config types and the production URI.
- `tests/test_fabric_sync_service.py` — Proves historical selection and the full Fabric/Gold/finalization/pointer transaction.
- `tests/test_onboarding_activation.py` — Covers no-upstream replay, pointer-store forwarding, result/progress compatibility, and fail-closed inputs.
- `tests/test_subscription_cli.py` — Covers exact replay argument forwarding and terminal output compatibility.

## Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q tests/test_fabric_commands.py tests/test_fabric_sync_service.py tests/test_onboarding_activation.py tests/test_subscription_cli.py` — **99 passed**.
- `uv run ruff check src/fabric/config.py src/onboarding/activation.py src/onboarding/cli.py tests/test_fabric_commands.py tests/test_fabric_sync_service.py tests/test_onboarding_activation.py tests/test_subscription_cli.py` — passed.
- `git diff --check` — passed.
- No Azure CLI, Fabric/Azure API, Terraform, deployment, networked test, Container Apps Job/profile/schedule, or D4 operation was invoked.

## Decisions Made

- Reused `DatasetStore.generation_path()` as the single safe exact-ID resolver and deliberately excluded `current_generation()` from replay.
- Loaded and validated the persisted combined manifest before runtime construction so malformed or unreadable replay input cannot begin Fabric publication.
- Kept the normal activation branch's validation, discovery, combined publication, progress order, result fields, and pointer-store behavior unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Disabled unrelated third-party pytest plugin auto-loading**
- **Found during:** Task 1 RED verification
- **Issue:** An installed Phoenix pytest entry point crashes during pytest startup on Python 3.11 because of an incompatible mutable dataclass default, before repository tests are collected.
- **Fix:** Ran the scoped local pytest commands with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; no project dependency or test behavior was changed.
- **Files modified:** None.
- **Verification:** All 99 planned tests pass with repository tests collected normally.
- **Committed in:** Not applicable (environment-only invocation).

**Total deviations:** 1 auto-fixed Rule 3 blocking issue.
**Impact on plan:** Verification remained fully local and scoped; production code and test semantics were unaffected.

## Issues Encountered

- The environment's auto-loaded Phoenix pytest plugin is incompatible with the active Python runtime. Disabling external plugin auto-loading allowed the repository's own tests to run without bypassing any project test.

## Known Stubs

None.

## Security and Threat Review

- Replay IDs pass through the existing safe single-segment generation validator.
- Exact replay never falls back to `current`, and malformed persisted provenance fails before runtime construction.
- The production configuration contains only a non-secret OneLake URI.
- Exposure pointer authority remains in the existing transaction and activates only after publication, Gold staging, shortcut finalization, and completed state.
- No security-relevant surface outside the plan threat model was introduced.

## User Setup Required

None — no dependency, credential, or external service change is required.

## Next Phase Readiness

- Operators can recover or intentionally repeat Fabric publication from one exact durable activation generation without repeating Azure connection work.
- Active Phase 03.1 ownership, status, blocker, and resume state remain unchanged.
- All unrelated dirty Fabric Data Agent, Gold-grounding, Terraform, `.azure`, documentation, and test paths remain untouched and unstaged.

## Self-Check: PASSED

- The required summary exists at the quick-task path.
- All eight planned source/config/test files exist.
- All five recorded task commits exist in Git history.
- No tracked file was deleted by a task commit.
- No unrelated dirty or untracked path was staged or committed.

---
*Quick task: 260910-f2h*
*Completed: 2026-09-10*
