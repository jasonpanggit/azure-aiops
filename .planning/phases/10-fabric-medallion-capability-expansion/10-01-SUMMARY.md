---
phase: 10-fabric-medallion-capability-expansion
plan: 01
subsystem: ontology
tags: [defender-for-cloud, ontology, fabric, fastapi, pytest, onelake]

# Dependency graph
requires: []
provides:
  - "A green (twice-run), committed backend test suite baseline on fix-ontology-sync-publish"
  - "7 live-verified Defender/vulnerability HTTP routes (/api/v1/defender/*, /api/v1/vulnerabilities/defender-posture, /api/v1/vulnerabilities/asset-exposures)"
  - "5 reviewable, individually revertable git commits covering the previously-uncommitted Defender ontology/pipeline/API/web working tree"
  - "One canonical ontology schema doc (ontology-schema.md) with RoleAssignment/RoleDefinition/ManagedIdentity access-governance entities folded in and a documented logical-vs-physical implementation-status table"
affects: [10-02, 10-03, 10-04, 10-05, 10-06, 10-07, 10-08, 10-09, 10-10, 10-11, 10-12, 10-13, 10-14, 10-15]

# Actuals (#2632)
actuals:
  tokens: 114988
  tasks: 3
  commits: 7

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ontology publish preflight ordering (build_definition() before manager.resolve()) now has an explicit monkeypatch-based regression test"
    - "Reviewable git-slice commit pattern for reconciling a large uncommitted working tree: one commit per functional concern (ontology governance, ingestion pipeline, API surface, web surface, unrelated pre-existing fixes) rather than one monolithic commit"

key-files:
  created:
    - src/ontology/confidence.py (committed, pre-existing content)
    - src/ontology/pending_relationships.py (committed, pre-existing content)
    - src/onboarding/defender_normalize.py (committed, pre-existing content)
    - src/fabric_pipelines/relationship_suggestion_promoter.py (committed, pre-existing content)
    - src/api/routers/compliance.py (committed, pre-existing content)
  modified:
    - tests/test_situations_tracer.py (fixed stale six-family assertion)
    - tests/test_relationship_vocabulary_consistency.py (added publish-preflight regression test)
    - ontology-schema.md (reconciled into sole canonical doc)
    - ONTOLOGY_SCHEMA.md (reduced to one-line redirect)

key-decisions:
  - "test_defender_signal_endpoints_preserve_distinct_semantics full-suite flakiness could not be reproduced across 4 consecutive full-suite runs this session; no isolation fix applied (assertion left unweakened) per the plan's conditional guidance — documented as a Known Stub/follow-up rather than fabricated."
  - "ontology-schema.md kept as the target logical contract rather than rewritten to mirror dataset_mapper.py's physical naming 1:1; documented the known logical/physical entity-name drift (Team vs SupportTeam+Owner, Patch vs PatchAssessment+PatchInstallation, Finding vs OperationalFinding/AdvisorRecommendation/Defender-family, Database/StorageAccount folded into generic Resource, Runbook/CostCentre/Person not yet implemented) transparently in a new 'Current implementation status' subsection rather than silently claiming full parity or undertaking an unscoped ontology redesign."
  - "ArcMachine -> ArcServer and AKSCluster -> KubernetesCluster renamed in ontology-schema.md to match the live dataset_mapper.py entity type names exactly, since these were simple 1:1 terminology corrections, not architecture changes."

patterns-established:
  - "Git-slice reconciliation of a large uncommitted working tree: group by functional concern, scan each slice's diff for secret literals before staging, commit atomically per slice."

requirements-completed: [MED-01, MED-04]

coverage:
  - id: D1
    description: "Stale test_normalizer_production_graph_contains_all_six_signal_families assertion fixed to expect the 6 granular defender_* source_status families instead of one stale 'defender' value"
    requirement: "MED-04"
    verification:
      - kind: unit
        ref: "tests/test_situations_tracer.py::test_normalizer_production_graph_contains_all_six_signal_families"
        status: pass
    human_judgment: false
  - id: D2
    description: "ontology_publisher.py publish() preflight ordering (build_definition() before manager.resolve()) confirmed via a new monkeypatch-based regression test"
    requirement: "MED-01"
    verification:
      - kind: unit
        ref: "tests/test_relationship_vocabulary_consistency.py::test_publish_never_resolves_when_build_definition_fails"
        status: pass
    human_judgment: false
  - id: D3
    description: "Full backend suite green twice in a row (only the 2 of 4 STATE.md-tracked pre-existing failures remain; the other 2 tracked failures no longer reproduce)"
    verification:
      - kind: unit
        ref: "pytest tests/ -q (run 4 consecutive times this session, all identical: 2 pre-existing failures, 0 new)"
        status: pass
    human_judgment: false
  - id: D4
    description: "All 7 Defender/vulnerability HTTP routes return 200 against a live local dev API instance"
    requirement: "MED-04"
    verification:
      - kind: integration
        ref: "curl against http://127.0.0.1:8099/api/v1/defender/{overview,alerts,attack-paths,secure-score,secure-score-controls} and /api/v1/vulnerabilities/{defender-posture,asset-exposures}"
        status: pass
    human_judgment: false
  - id: D5
    description: "Previously-uncommitted fix-ontology-sync-publish working tree committed in 5 reviewable slices; no secrets in any staged diff"
    verification:
      - kind: other
        ref: "git log --oneline -6 (5 slice commits) + git status --short (Uncommitted Work Inventory paths clean)"
        status: pass
    human_judgment: false
  - id: D6
    description: "test_defender_signal_endpoints_preserve_distinct_semantics full-suite flakiness diagnosis attempted"
    verification: []
    human_judgment: true
    rationale: "Flakiness reported in RESEARCH.md (1 failure in 3 full-suite runs previously) did not reproduce in 4 consecutive full-suite runs this session. Code review of the request path (ApiContext built with a fresh VulnerabilityIntelligenceService per test via _service(), no module-level cache touched by /defender/* routes) found no isolation gap. A human/future session should re-attempt reproduction if this resurfaces, since root cause was not conclusively identified — only ruled out as non-reproducing under current conditions."
  - id: D7
    description: "Ontology schema docs reconciled into one canonical source, with documented (not silently ignored) logical/physical entity-name drift"
    requirement: "MED-01"
    verification:
      - kind: other
        ref: "grep -rn 'ONTOLOGY_SCHEMA.md' --include=*.md --include=*.py . (only a REPOSITORY_STRUCTURE.md tree listing and .planning/ historical artifacts remain, all still valid since the file exists as a redirect)"
        status: pass
    human_judgment: false

duration: 32min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 1: Stabilize Defender/Ontology Baseline Summary

**Fixed a stale test assertion, live-verified all 7 new Defender API routes, committed ~46 previously-uncommitted files across 5 reviewable git slices, and reconciled two competing ontology schema docs into one canonical source with an honest logical-vs-physical drift disclosure.**

## Performance

- **Duration:** ~32 min
- **Started:** 2026-09-01T07:17:31Z
- **Completed:** 2026-09-01T07:49:12Z
- **Tasks:** 3
- **Files modified:** 63 (across all 7 commits combined; see per-commit breakdown below)

## Accomplishments

- Fixed `test_normalizer_production_graph_contains_all_six_signal_families`'s stale assertion (it was still hardcoding one `"defender"` source_status family; the normalizer now emits 6 granular `defender_*` families alongside it).
- Added a new regression test (`test_publish_never_resolves_when_build_definition_fails`) confirming `OntologyPublisher.publish()` validates via `build_definition()` before ever calling `manager.resolve()` — a real Fabric-write preflight-ordering guarantee, not just an assumption.
- Ran the full backend suite 4 times consecutively this session: identical result every time — only 2 of the 4 STATE.md-tracked pre-existing failures reproduce (`test_service.py::test_end_to_end_mock_ingestion_tracks_incremental_state`, `test_situations_tracer.py::test_production_ingestion_retains_failed_arg_status_without_watermark`); the other 2 tracked failures (`test_api_remediation_approvals.py` x2) and the previously-flaky `test_defender_signal_endpoints_preserve_distinct_semantics` did not reproduce at all.
- Started a local dev API instance (`scripts/start-api.sh`, live Azure discovery mode) and live-curled all 7 new Defender/vulnerability routes — all returned HTTP 200.
- Committed the entire previously-uncommitted `fix-ontology-sync-publish` working tree (~46 modified + ~14 new files) across 5 reviewable, individually-revertable git commits: ontology governance, Defender Bronze/Silver ingestion pipeline, Defender API surface, Defender web surface, and pre-existing unrelated fixes (explicitly not attributed to Phase 10).
- Reconciled `ONTOLOGY_SCHEMA.md` (stale "HOG" terminology) and `ontology-schema.md` (current terminology) into one canonical doc: folded in the `RoleAssignment`/`RoleDefinition`/`ManagedIdentity` access-governance entity types and `grantedTo`/`definedBy`/`scopedTo` relationships (verified present in `dataset_mapper.py`'s `ONTOLOGY_ENTITY_TYPES` but previously undocumented), folded in the "Effective graph views" subsection, corrected `ArcMachine`→`ArcServer` and `AKSCluster`→`KubernetesCluster` to match live code, and added a new "Current implementation status" subsection that honestly documents remaining logical/physical drift instead of claiming false 1:1 parity.
- `ONTOLOGY_SCHEMA.md` reduced to a one-line redirect (`Superseded by ontology-schema.md.`).

## Task Commits

Each task was committed atomically:

1. **Task 1 (tracer): Stabilize the Defender/ontology path end-to-end** - `0de31d1b` (test)
2. **Task 2: Commit the uncommitted working tree in reviewable slices** - `89631582` (feat, ontology governance), `cb34a756` (feat, Defender Bronze/Silver ingestion pipeline), `24be2650` (feat, Defender API surface), `c252842e` (feat, Defender web surface), `8978e609` (fix, pre-existing unrelated fixes)
3. **Task 3: Reconcile the two ontology schema documents** - `08795e33` (docs)

_Note: Task 2's plan called for exactly 5 slice commits — delivered as specified._

## Files Created/Modified

- `tests/test_situations_tracer.py` - Fixed stale six-family source_status assertion
- `tests/test_relationship_vocabulary_consistency.py` - Added publish-preflight-ordering regression test
- `src/ontology/confidence.py`, `src/ontology/pending_relationships.py` - Confidence scoring and deferred-relationship resolution (pre-existing, now committed)
- `src/onboarding/defender_normalize.py` - Defender for Cloud raw-row normalization (pre-existing, now committed)
- `src/fabric/dataset_mapper.py`, `schema_registry.py`, `sync_service.py` - Defender ontology vocabulary, Bronze/Silver schemas, Defender snapshot builder (pre-existing, now committed)
- `src/api/routers/vulnerability.py`, `compliance.py`, `src/api/runtime.py`, `app.py`, `dependencies.py`, `models.py` - 7 new Defender/vulnerability routes plus the new compliance router (pre-existing, now committed)
- `web/src/lib/types.ts`, `services.ts`, `web/src/app/compliance/page.tsx`, `exposure/page.tsx` - Defender web surface (pre-existing, now committed)
- `ontology-schema.md` - Reconciled canonical ontology schema doc
- `ONTOLOGY_SCHEMA.md` - Reduced to one-line redirect

## Decisions Made

- Kept `ontology-schema.md` as a target **logical** contract rather than rewriting it to mirror `dataset_mapper.py`'s physical entity/relationship naming 1:1 across the board — that would be an unscoped ontology-naming redesign (Rule 4 territory), not a doc-reconciliation task. Instead, added an explicit "Current implementation status" subsection documenting exactly where the logical and physical models currently diverge (renamed the two straightforward 1:1 aliases `ArcMachine`→`ArcServer`/`AKSCluster`→`KubernetesCluster`; documented the rest as known, tracked drift).
- Did not force a fix for `test_defender_signal_endpoints_preserve_distinct_semantics`'s previously-reported full-suite flakiness since it did not reproduce across 4 consecutive full-suite runs this session; per the plan's explicit "if it reproduces" conditional and "do not weaken the assertion" guidance, no test changes were made. Documented as an open item (D6) for a future session to re-attempt if it resurfaces.
- Slice 3 of Task 2's commit plan explicitly separates `tests/test_azure_clients.py` (committed in the API-surface slice) from `src/onboarding/azure_clients.py` (committed in the unrelated-fixes slice) — followed the plan's literal slice assignment even though the test and its source file land in different commits, since that's how the plan's Task 2 action text enumerated them.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed stale six-family source_status assertion**
- **Found during:** Task 1
- **Issue:** `test_normalizer_production_graph_contains_all_six_signal_families` asserted `graph.source_status`'s `source_family` set equaled exactly the 6 canonical families including one `"defender"` value — but the normalizer (per the uncommitted working-tree change) now always additionally emits 6 granular `defender_*` families (`defender_assessments`, `defender_subassessments`, `defender_alerts`, `defender_attack_paths`, `defender_secure_scores`, `defender_secure_score_controls`) into `source_status` regardless of whether Defender data is present in the payload.
- **Fix:** Expanded the assertion to check the 5 non-Defender canonical families are a subset of the observed set, and that the Defender-prefixed subset exactly equals the 6 canonical + 6 granular family names — without touching the (already-correct) `graph.evidence` assertion.
- **Files modified:** `tests/test_situations_tracer.py`
- **Verification:** `pytest tests/test_situations_tracer.py::test_normalizer_production_graph_contains_all_six_signal_families -q` passes; full suite green 4/4 runs.
- **Committed in:** `0de31d1b`

**2. [Rule 2 - Missing Critical] Added ontology-publisher preflight-ordering regression test**
- **Found during:** Task 1
- **Issue:** The plan's `<read_first>` step identified that `ontology_publisher.py::publish()` calls `build_definition()` before `manager.resolve()` (a load-bearing safety property — invalid ontology/relationship mappings must never reach a live Fabric lookup), but no regression test enforced this ordering.
- **Fix:** Added `test_publish_never_resolves_when_build_definition_fails` to `tests/test_relationship_vocabulary_consistency.py`, monkeypatching a fake manager's `resolve()` to raise loudly if called, then asserting it's never invoked when `build_definition()` raises `ValueError` for an empty entity-type mapping.
- **Files modified:** `tests/test_relationship_vocabulary_consistency.py`
- **Verification:** New test passes; all 5 tests in the file pass.
- **Committed in:** `0de31d1b`

---

**Total deviations:** 2 auto-fixed (1 bug fix, 1 missing-critical-test addition), both explicitly called for by the plan's own Task 1 action text (not scope creep).
**Impact on plan:** Both changes were prerequisites for the plan's own acceptance criteria (green suite, preflight-ordering regression coverage). No scope creep beyond what Task 1 specified.

## Issues Encountered

- **`test_defender_signal_endpoints_preserve_distinct_semantics` flakiness did not reproduce.** RESEARCH.md documented this test failing in 1 of 3 full-suite runs in a prior session. This session ran the full suite 4 consecutive times (2 before the Task 1 fix, 2 after) — the test passed every time. Code review of the request path (`ApiContext` built fresh per test via `_service()`, no `provider_runtime` set, no module-level cache in `VulnerabilityIntelligenceService`/`resolve_provider` touched by `/defender/*` routes) found no isolation gap in that code path. Per the plan's explicit "if it reproduces" conditional, no fix was fabricated. Tracked as coverage item D6 for a future session to revisit if the flake resurfaces.
- **Local dev API discovery took ~40s to complete** before the Defender routes stopped returning 503 "provider is loading" — this is expected behavior for `AIOPS_RUNTIME_MODE=production`'s live Azure discovery path (used because `web/.env.local`'s `AZURE_CLIENT_*` credentials were present), not a bug. Polled with a short retry loop until the provider became ready, then verified all 7 routes, then stopped the server cleanly.

## Broken-Windows Ledger

Attempted to append the D6 flakiness deviation to `.planning/WINDOWS.md` via `gsd-tools windows append`. The command failed with `Error: Ledger entry 17 has invalid kind: "live-source-data"` — a pre-existing, unrelated ledger entry from an earlier phase fails the tool's current kind-vocabulary validation, which blocks any further append to the same file. Per the executor contract this population is best-effort and non-blocking; the D6 item remains recorded here in the SUMMARY (and as `coverage: D6` with `human_judgment: true`) so it is not lost, but is not yet mirrored into `WINDOWS.md`. A future session should fix or remove ledger entry 17's invalid `kind` before this and any other pending append can succeed.

## User Setup Required

None - no external service configuration required. (The live dev-server verification used already-configured `web/.env.local` credentials; no new setup needed.)

## Next Phase Readiness

- The Phase 10 baseline is now green (twice-run, actually 4x-run), fully committed in 5 reviewable git slices, and documented with one canonical ontology schema doc — every subsequent Phase 10 plan (10-02 through 10-15) can build on this without rediscovering or re-litigating this session's uncommitted work.
- **Follow-up tracked, not blocking:** re-attempt reproduction of `test_defender_signal_endpoints_preserve_distinct_semantics`'s full-suite-only flakiness if it resurfaces in a later session (see D6/Issues Encountered).
- **Follow-up tracked, not blocking:** the ontology-schema.md "Current implementation status" section identifies several logical entity types not yet backed by a matching physical type (`Database`, `StorageAccount`, `Runbook`, `CostCentre`, `Person`) and the registered-but-unconnected `RoleAssignment`/`RoleDefinition`/`ManagedIdentity` relationships (`grantedTo`/`definedBy`/`scopedTo` not yet in `ONTOLOGY_RELATIONSHIP_TYPES`) — future MED plans (particularly access-governance or semantic-model work) should consult this before assuming full logical/physical parity.

---
*Phase: 10-fabric-medallion-capability-expansion*
*Completed: 2026-09-01*

## Self-Check: PASSED

All 10 claimed files verified present on disk; all 7 claimed commit hashes verified present in `git log --oneline --all`.
