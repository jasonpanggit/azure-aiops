---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 19
subsystem: ontology-deployment
tags: [terraform, container-apps-jobs, fabric, managed-identity, rbac, immutable-images]

requires:
  - phase: 13-16
    provides: Production coordinator, fair restart-safe registry selection, and publisher dispatch
  - phase: 13-17
    provides: Dedicated publisher worker, guarded drill control, and fenced publication
  - phase: 13-18
    provides: Four-root API composition and immutable command topology
provides:
  - Exact deployed API/coordinator/publisher capability topology across isolated Fabric roots
  - Fixed validation prepare and cleanup Jobs under the existing coordinator UAI
  - Immutable digest-pinned API, web, coordinator, publisher, validator, and fixture workloads
  - Exact saved-plan allowlist and closed sanitized live deployment evidence
affects: [13-20, 13-21, ontology-deployment, fabric-rbac, validation-drills]

actuals:
  tokens: 26506
  tasks: 3
  commits: 13

tech-stack:
  added: []
  patterns:
    - Exact Terraform address allowlists with zero-destroy and zero-replace gates
    - Fixed manual Container Apps Job templates with server-owned fixture identity
    - Hash-only deployment evidence with explicit supersession and applied-state gates
    - Current-main source reconciliation before immutable image publication

key-files:
  created:
    - scripts/validate_ontology_deployment_plan.py
    - scripts/collect_ontology_deployment_evidence.py
    - tests/test_ontology_deployment_plan.py
    - .planning/eval/ontology-gap-deployment.json
  modified:
    - infra/terraform/container_apps.tf
    - infra/terraform/ontology_discovery_identity.tf
    - infra/terraform/ontology_discovery_job.tf
    - infra/terraform/variables.tf
    - src/ontology_discovery/runtime.py
    - src/ontology_discovery/store.py
    - tests/test_ontology_discovery_job_infra.py
    - tests/test_ontology_discovery_runtime.py
    - tests/test_ontology_publisher_identity.py

key-decisions:
  - "Validation changes only the coordinator environment and ConnectionRegistry root; registry construction, eligible selection, reauthorization, retries, and restart behavior remain the production path."
  - "Fixture Jobs use the existing coordinator UAI and fixed templates; no fixture identity, runtime launcher grant, disposable resource group, or caller override surface exists."
  - "API receives four pairwise-distinct roots and the apps UAI but no dispatch root, publisher credential, fixture root, drill root, or Job-start authority."
  - "Deployment evidence is closed and hash-only, and a superseded snapshot fails the require-applied gate until fresh live proof replaces it."

patterns-established:
  - "Deployment gate: validate exact changed addresses, complete Job templates, image digests, roots, tags, and RBAC before apply."
  - "Fixture lifecycle: prepare leaves exactly three owned/fenced records plus one epoch; cleanup resolves server-side and deletes only that owned set."
  - "Live closeout: compare template hashes before and after harmless reads and retain no cloud IDs, URLs, commands, prompts, tokens, or raw errors."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-03, AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: Two fixed validation fixture Jobs use the coordinator UAI and the production ConnectionRegistry protocol.
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: tests/test_ontology_discovery_runtime.py#test_fixture_prepare_cleanup_and_sweep_are_bounded_and_fenced
        status: pass
      - kind: unit
        ref: tests/test_ontology_discovery_job_infra.py#test_validation_fixture_jobs_are_fixed_manual_templates
        status: pass
    human_judgment: false
  - id: D2
    description: Exact API, coordinator, publisher, command, dispatch, state, and publication boundaries are deployed without runtime Job-start grants.
    requirement: AUTO-ONT-05
    verification:
      - kind: unit
        ref: tests/test_ontology_publisher_identity.py#test_authoritative_capability_matrix_and_job_start_denials_are_exact
        status: pass
      - kind: integration
        ref: scripts/validate_ontology_publisher_rbac.py --assert-authoritative-capability-matrix
        status: pass
    human_judgment: false
  - id: D3
    description: Production and validation saved plans use exact allowlists, immutable digests, and zero destroy or replace.
    requirement: AUTO-ONT-07
    verification:
      - kind: unit
        ref: tests/test_ontology_deployment_plan.py
        status: pass
      - kind: integration
        ref: scripts/validate_ontology_deployment_plan.py --require-applied
        status: pass
    human_judgment: false
  - id: D4
    description: Final live API/web/worker images, fixture templates, roots, coordinator tag, and effective RBAC are bound to sanitized evidence.
    requirement: AUTO-ONT-06
    verification:
      - kind: e2e
        ref: .planning/eval/ontology-gap-deployment.json
        status: pass
    human_judgment: false

duration: 2h10m
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 19: Immutable Ontology Validation Deployment Summary

**Digest-pinned API, web, coordinator, publisher, RBAC validator, and fixed fixture Jobs now run across exact isolated Fabric roots with hash-only zero-destroy deployment proof and no runtime Job-start authority.**

## Performance

- **Duration:** 2h 10m
- **Started:** 2026-09-07T13:44:11Z
- **Completed:** 2026-09-07T15:53:56Z
- **Tasks:** 3
- **Files modified:** 14 implementation, test, Terraform, and evidence files

## Accomplishments

- Deployed the production API/coordinator/publisher root-capability matrix, including isolated command, dispatch, state, publication, and validation registry boundaries.
- Added exactly two fixed manual fixture Jobs under the coordinator UAI, backed by a server-generated three-record prepared epoch and fenced cleanup/sweep lifecycle.
- Preserved the existing coordinator/publisher identities and Plan 07 resources while adding no fixture principal, runtime Job-start role, wildcard target acceptance, replacement, or destroy.
- Built and deployed the integrated source tag `phase13-plan19-8c503e983`; API and all five Phase 13 Jobs use the reviewed API digest, and web uses its reviewed digest.
- Applied the final validation plan with 0 additions, 1 in-place web update, and 0 destroys, then regenerated applied evidence whose complete template hashes remained stable across live reads.

## Task Commits

1. **Task 1: Fixed-template fixture lifecycle**
   - `cecb11008` — RED fixture lifecycle contracts
   - `2804d6cbf` — validation fixture lifecycle and fixed Jobs
2. **Task 2: Exact immutable deployment set**
   - `062d4a703` — RED deployment-plan contracts
   - `4592c3170` — exact roots, roles, publisher Job, digest inputs, and plan validator
   - `9fcf0f9ed` — secret-backed non-ontology environment handling
   - `99a34569d` — computed Fabric root handling
3. **Task 3: Live matrix, template, and fixture-isolation proof**
   - `3213b64ca` — sanitized live evidence collector and RBAC assertion surface
   - `43de51def` — initial sanitized deployment snapshot
   - `1842b6dc7` — concurrent deployment blocker
   - `4f23fbe9e` — fail-closed superseded evidence
   - `2e065a772` — local-complete cloud checkpoint
   - `8015f6caf` — refreshed final applied evidence

Additional Plan 19 checkpoint commit: `d1b57ce75`.

## Files Created/Modified

- `infra/terraform/container_apps.tf` — digest-pinned images and exact four-root API environment.
- `infra/terraform/ontology_discovery_identity.tf` — isolated command, dispatch, and publication roots and process role assignments.
- `infra/terraform/ontology_discovery_job.tf` — coordinator, publisher, RBAC validator, prepare, and cleanup Job templates.
- `infra/terraform/variables.tf` — immutable image digests and exact ontology environment classification.
- `src/ontology_discovery/runtime.py` — shared production/validation registry composition and fixture lifecycle commands.
- `src/ontology_discovery/store.py` — exact prepared-epoch removal under member checks.
- `scripts/validate_ontology_deployment_plan.py` — exact saved-plan and applied-evidence validator.
- `scripts/collect_ontology_deployment_evidence.py` — closed live template/image/root/tag/RBAC evidence collector.
- `scripts/validate_ontology_publisher_rbac.py` — explicit capability-boundary assertion flags.
- `tests/test_ontology_deployment_plan.py` — exact address, template, image, root, tag, and evidence contracts.
- `tests/test_ontology_discovery_job_infra.py` — fixed Job and coordinator tag assertions.
- `tests/test_ontology_discovery_runtime.py` — three-record prepare, cleanup, sweep, and shared registry path coverage.
- `tests/test_ontology_publisher_identity.py` — authoritative matrix and Job-start denial coverage.
- `.planning/eval/ontology-gap-deployment.json` — final sanitized applied deployment evidence.

## Decisions Made

- Kept validation as a data/root selection, not a separate process or identity, so the regular coordinator exercises the same registry, fairness, authorization, retry, and restart code.
- Used the existing coordinator UAI for fixture preparation and cleanup because additional fixture principals or runtime Job-control rights would widen the threat surface.
- Made digest references authoritative for every deployed image consumer; mutable tags remain build labels only.
- Kept deployment evidence intentionally lossy: resource classes, statuses, times, digests, and hashes are retained, while cloud IDs and raw operational payloads are excluded.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Protected Terraform source/state parity**
- **Found during:** Task 2 deployment
- **Issue:** Shared main temporarily lacked the deployed Phase 13 Terraform definitions and proposed deleting 17 live resources.
- **Fix:** Paused deployment until canonical definitions were merged to main at `d34bbe3d6`, then regenerated plans from protected source parity.
- **Files modified:** Terraform source integration and planning metadata
- **Verification:** Final validation plan contained 0 additions, 1 update, and 0 destroys.

**2. [Rule 1 - Bug] Reconciled concurrent shared image deployments**
- **Found during:** Task 2 post-apply verification
- **Issue:** Concurrent Exposure deployments changed API/web revisions after an otherwise successful Plan 19 apply.
- **Fix:** Froze deployment, reconciled against clean main `8c503e983`, rebuilt the integrated immutable images, and applied only the final reviewed web update.
- **Files modified:** Deployment evidence only; no runtime source workaround
- **Verification:** Final live evidence binds API and all Phase 13 Jobs to one API digest and web to its reviewed digest.

**3. [Rule 2 - Missing Critical] Added superseded-evidence fail-closed semantics**
- **Found during:** Task 3 live closeout
- **Issue:** A historically valid evidence snapshot could be mistaken for current proof after a concurrent deployment.
- **Fix:** Added explicit `superseded` validation semantics; `--require-applied` rejects stale evidence until a fresh collector run replaces it.
- **Files modified:** `scripts/validate_ontology_deployment_plan.py`, `tests/test_ontology_deployment_plan.py`
- **Verification:** Superseded fixture rejects `--require-applied`; final refreshed evidence passes.

---

**Total deviations:** 3 auto-fixed (1 blocking, 1 bug, 1 missing critical)
**Impact on plan:** All changes strengthened source parity, immutable-image correctness, and evidence freshness without widening deployment scope.

## Issues Encountered

- The deployment lane changed twice during execution. Both times the executor stopped rather than overwrite concurrent work, preserving the shared API and all live Phase 13 resources.
- The first web ACR build used the wrong relative build context and failed before publication; it was retried with the reviewed `web/` context.

## Verification

- Plan 19 targeted Python suite — **48 passed**
- Terraform `fmt -check` — **passed**
- Terraform `validate` — **passed**
- Changed-file Ruff — **passed**
- Phase 13 dependency preflight — **passed**
- Exact saved-plan allowlists — **passed**
- Final validation apply — **0 add / 1 update / 0 destroy**
- Applied evidence `--require-applied` gate — **passed**
- Live template pre/post read hashes — **identical**
- Runtime Job-start grant audit — **no grants**
- Fixture Jobs — **not started**

## Known Stubs

None. Empty collections and strings in the changed code are bounded accumulators, optional digest/tag defaults, or test fixtures; no production data path is unwired.

## User Setup Required

None. Existing protected deployment credentials, canonical Terraform state, Fabric capacity, and ACR were used without retaining secrets.

## Next Phase Readiness

- Plan 13-20 may execute the ordered live prepare/drain/injection/cleanup sequence using the fixed deployed Jobs.
- Plan 13-21 may perform final deployed-only fairness, matrix, credential, drill, and empty-registry closeout.
- Phase 03.1 remains the active planning workstream and its active fields were not changed.

## Self-Check: PASSED

All declared implementation, Terraform, test, evidence, and summary files exist. All 13 Plan 19 task/checkpoint/evidence commits were found, final applied evidence passes the closed validator, and Phase 03.1 active position fields remain unchanged.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
