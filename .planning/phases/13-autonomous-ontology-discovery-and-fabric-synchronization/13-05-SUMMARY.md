---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 05
subsystem: ontology-governance
tags: [ontology, shadow-mode, proposal-policy, cas, release-gates, validation]

requires:
  - phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
    plan: 04
    provides: strict proposal-only curator output and scope-filtered evidence tools
  - phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
    plan: 11
    provides: immutable content-addressed evaluation snapshots
provides:
  - exact direction-sensitive relationship vocabulary shared by policy and candidate validation
  - hard server-side shadow admission that excludes every model-derived edge after review
  - content-addressed proposals and durable authorized CAS review history
  - disabled-by-default pair-release eligibility, activation, and scoped revocation contracts
affects: [13-07, 13-08, 13-09, ontology-publication, ontology-evaluation]

actuals:
  tokens: 17138
  tasks: 2
  commits: 6

tech-stack:
  added: []
  patterns:
    - one authoritative exact-triple vocabulary consumed through a direction-sensitive helper
    - immutable content identity plus append-only review events with revision CAS
    - separate BLOCKED/PENDING pair-release records revalidated at synthetic activation time

key-files:
  created:
    - src/ontology_discovery/policy.py
    - tests/test_ontology_proposal_policy.py
  modified:
    - src/ontology_discovery/contracts.py
    - src/ontology_discovery/store.py
    - src/ontology_discovery/coordinator.py
    - src/fabric/dataset_mapper.py
    - src/ontology/ontology_validator.py
    - tests/test_ontology_validator.py

key-decisions:
  - "Keep Phase 13 globally shadowed: accepted reviews remain durable evidence but always return shadow_review_only and never enter an authoritative candidate."
  - "Derive exact directional triples only from ONTOLOGY_RELATIONSHIP_TYPES; policy and validation do not maintain copied allowlists."
  - "Persist proposals, review histories, and AdmissionRelease records separately so review acceptance cannot mutate admission policy."
  - "Expose pair activation only through an explicit synthetic-test constructor gate; live Phase 13 remains BLOCKED/PENDING and has no production activation configuration."
  - "Preserve root STATE.md Phase 03.1 ownership during this approved concurrent Phase 13 plan."

patterns-established:
  - "Shadow boundary: deterministic policy checks -> durable review -> immediate server shadow gate -> deterministic-wins candidate merge."
  - "Release boundary: immutable pair snapshot -> exact gate evaluation -> separate pending release record -> audited CAS activation/revocation."

requirements-completed: [AUTO-ONT-04, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: "Exact vocabulary, scope, lifecycle, evidence, contradiction, corroboration, duplicate, and deterministic-wins checks fail closed before candidate assembly."
    requirement: AUTO-ONT-04
    verification:
      - kind: unit
        ref: "tests/test_ontology_proposal_policy.py#test_policy_fails_closed_for_every_deterministic_defect"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_proposal_policy.py#test_full_candidate_validation_rechecks_scope_lifecycle_duplicates_and_triples"
        status: pass
      - kind: integration
        ref: "tests/test_relationship_vocabulary_consistency.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Reviewed proposals remain non-authoritative in hard shadow mode while deterministic edges continue and win collisions."
    requirement: AUTO-ONT-07
    verification:
      - kind: unit
        ref: "tests/test_ontology_proposal_policy.py#test_accepted_review_is_durable_but_shadow_never_admits_model_edge"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_proposal_policy.py#test_coordinator_persists_accepted_review_but_returns_shadow_candidate"
        status: pass
    human_judgment: false
  - id: D3
    description: "Proposal identity, authorized review CAS, exact pair-release gates, disabled activation, and pair-scoped revocation remain deterministic across restart."
    requirement: AUTO-ONT-06
    verification:
      - kind: unit
        ref: "tests/test_ontology_proposal_policy.py#test_proposal_identity_covers_scope_generation_triple_evidence_and_versions"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_proposal_policy.py#test_review_cas_is_authorized_immutable_and_restart_durable"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_proposal_policy.py#test_pair_release_eligibility_requires_every_exact_gate"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_proposal_policy.py#test_pair_release_is_disabled_by_default_and_scoped_revocation_is_immediate"
        status: pass
    human_judgment: false

duration: 13min
completed: 2026-09-06
status: complete
---

# Phase 13 Plan 05: Hard Shadow Proposal Policy and Durable Release Lifecycle Summary

**Exact ontology policy, immutable proposal/review history, and disabled pair-release machinery now enforce a non-bypassable server-side shadow boundary.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-09-06T15:00:39Z
- **Completed:** 2026-09-06T15:13:12Z
- **Tasks:** 2
- **Files modified:** 8 implementation/test files

## Accomplishments

- Added one exact, direction-sensitive triple helper over `ONTOLOGY_RELATIONSHIP_TYPES`, then made proposal policy and full candidate validation reject unsupported direction/type combinations, unknown or inactive endpoints, cross-scope rows, stale or contradictory evidence, insufficient independent corroboration, and semantic duplicates.
- Added the hard candidate-assembly shadow gate. An accepted review is persisted and reported as `shadow_review_only`, while model-derived edges remain absent and colliding deterministic edges always win.
- Added content-addressed proposal identity over scope, source generation, endpoint/triple identity, ordered-independent evidence references, schema version, and policy version.
- Added restart-durable proposal, immutable review-event, and separate `AdmissionRelease` storage with authorized reviewer CAS and supersession lineage.
- Added exact release eligibility for one predicate/type pair: 30 consecutive shadow days, 200 expert-adjudicated eligible proposals, zero Critical failures, escalation recall 1.00, recall at least 0.90, Wilson precision lower bound at least 0.98, every AI-SPEC gate, and ontology/security/Fabric approvals.
- Kept live Phase 13 release `BLOCKED/PENDING`. Activation is unavailable by default, exercised only through an explicit synthetic-test gate, revalidates the immutable snapshot at the transition, and supports immediate pair-scoped revocation.

## Task Commits

Each TDD task has a RED commit followed by its GREEN implementation:

1. **Task 1 RED: hard shadow admission policy tests** - `b1f9ba7c`
2. **Task 1 GREEN: exact policy and candidate validation** - `798cdfc4`
3. **Task 2 RED: deterministic proposal lifecycle tests** - `d2708cf4`
4. **Task 2 GREEN: durable review and release lifecycle** - `15067668`
5. **Correctness fix: PaaS containment vocabulary alignment** - `2208f77e`
6. **Security fix: activation-time release snapshot validation** - `137ff5ee`

## Files Created/Modified

- `src/ontology_discovery/policy.py` - Deterministic policy decisions, hard shadow assembly, release gates, and Wilson lower-bound calculation.
- `src/ontology_discovery/contracts.py` - Content-addressed proposal IDs and immutable pair evaluation snapshots.
- `src/ontology_discovery/store.py` - Durable proposals, review CAS/events, separately stored pending releases, synthetic activation, and scoped revocation.
- `src/ontology_discovery/coordinator.py` - Joins durable review/release state to policy without receiving publication authority.
- `src/fabric/dataset_mapper.py` - Authoritative exact-triple helper plus existing deterministic Situation/PaaS containment vocabulary.
- `src/ontology/ontology_validator.py` - Full exact-triple, explicit-scope, active-lifecycle, endpoint-type, and semantic-duplicate validation.
- `tests/test_ontology_proposal_policy.py` - Shadow, defect, identity, CAS, restart, release-threshold, activation, revocation, and coordinator coverage.
- `tests/test_ontology_validator.py` - Existing fixtures aligned to exact authoritative triples.

## Decisions Made

- Review status and admission status are deliberately separate. `accepted` records expert judgment, while `admitted` remains false under Phase 13 shadow mode.
- Exact vocabulary matching is case- and direction-sensitive. No policy synonym, prompt vocabulary, or copied allowlist can authorize a relationship.
- A release record starts `BLOCKED/PENDING` even when its synthetic evidence is eligible; an audited activation CAS is a separate transition and is disabled in production.
- Activation revalidates the persisted snapshot ID and every eligibility gate rather than trusting cached eligibility booleans.
- Revocation addresses one explicit pair and immediately removes it from coordinator lookup; unrelated pair state remains unchanged.
- Root `.planning/STATE.md`, `.planning/ROADMAP.md`, and `.planning/REQUIREMENTS.md` were intentionally not advanced because Phase 03.1 remains the active root workstream.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Aligned legacy validator fixtures to exact triples**
- **Found during:** Task 1 validator regression verification
- **Issue:** The legacy validator fixture used `VirtualMachine dependsOn Application`, which is not an exact member of the authoritative vocabulary and therefore correctly failed after exact validation was enabled.
- **Fix:** Changed the active fixture to `VirtualMachine member_of Application` and retained the retired reclassification test with the valid historical `Resource member_of Application` triple.
- **Files modified:** `tests/test_ontology_validator.py`
- **Verification:** `tests/test_ontology_validator.py` passed.
- **Committed in:** `798cdfc4`

**2. [Rule 1 - Bug] Registered deterministic triples already emitted by production mappers**
- **Found during:** Task 1 and overall ontology regression verification
- **Issue:** Existing Situation and granular PaaS mappers emitted `Situation affects VirtualMachine` and `ResourceGroup contains ContainerRegistry`, but those deterministic triples were missing from the authoritative vocabulary.
- **Fix:** Added exact generated vocabulary entries for Situation-to-supported-assets and ResourceGroup-to-PaaS containment without introducing wildcard policy matching.
- **Files modified:** `src/fabric/dataset_mapper.py`
- **Verification:** The complete 203-test relevant ontology regression suite passed.
- **Committed in:** `798cdfc4`, `2208f77e`

**3. [Rule 2 - Missing Critical] Revalidated release evidence at activation**
- **Found during:** Overall release-boundary audit
- **Issue:** A synthetic activation could have trusted the cached `eligible` flag, and durable uppercase `ENABLED` status did not match the policy's initial lowercase check.
- **Fix:** Activation now reconstructs and validates the immutable snapshot ID, reruns every release gate, checks pair identity, and policy compares durable status case-insensitively.
- **Files modified:** `src/ontology_discovery/store.py`, `src/ontology_discovery/policy.py`, `tests/test_ontology_proposal_policy.py`
- **Verification:** Proposal policy, store, and coordinator suites passed.
- **Committed in:** `137ff5ee`

---

**Total deviations:** 3 auto-fixed (1 bug, 1 missing critical security control, 1 blocking fixture issue).
**Impact on plan:** All changes enforce or unblock the planned exact policy boundary; no deployment, live release, or later-plan work was added.

## Issues Encountered

- The Phase 13 dependency preflight passed before implementation and after all implementation commits.
- Exact validation exposed two pre-existing authoritative-vocabulary omissions in deterministic producers; both were corrected and covered by the existing end-to-end ontology regressions.

## Verification

- `uv run python .planning/scripts/preflight_phase_13.py` — passed before and after implementation.
- Required proposal-policy, relationship-vocabulary, validator, coordinator, store, contract, and evaluation suites — passed.
- Relevant ontology discovery, publication, synchronization, Fabric integration, generation-consumer, network, pending-relationship, remediation-alignment, and Situation regressions — 203 passed.
- `uv run ruff check src/ontology_discovery src/fabric/dataset_mapper.py src/ontology/ontology_validator.py` — passed.
- `git diff --check` — passed.
- All six implementation commits contain the required Copilot trailer.

## Known Stubs

None.

## User Setup Required

None - no deployment, credential setup, push, or external service mutation was performed.

## Next Phase Readiness

- Plan 13-05 is complete and its shadow-only proposal/review contracts are ready for later publication and API plans.
- Live Phase 13 pair release remains explicitly `BLOCKED/PENDING`; no model-derived edge can enter an authoritative candidate.
- No Plan 13-07 or later work was started.
- Phase 03.1 remains the active root planning workstream.

## Self-Check: PASSED

- All eight implementation/test artifacts and this summary exist.
- All six RED, GREEN, and corrective commits are present in repository history.
- Root `.planning/STATE.md` SHA-256 remains `829912d96ff83b56d31c420c2f95d017d34c4446f671b0bdebaa764e59c3db17`, preserving active Phase 03.1 fields.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-06*
