---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 06
subsystem: ontology-consumers
tags: [ontology, generation-resolution, fabric, semantic, rollback]

requires:
  - phase: 13-01
    provides: dependency preflight, immutable-generation contract tracer, and rollback harness
  - phase: 03.1-14
    provides: current governed Exposure consumer contracts
  - phase: 11-02
    provides: merged canonical snapshot v2 evidence behavior
provides:
  - request-scoped GenerationResolver with active/prior/source generation and pointer ETag metadata
  - executable five-family ontology consumer inventory and repository drift scan
  - versioned compatibility aliases for API, Fabric, agent, export, and semantic consumers
  - old/new/old promotion and rollback contract coverage across every consumer family
affects: [13-07, 13-08, 13-12, ontology-publication, fabric-consumers]

actuals:
  tokens: 12260
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - resolve the mutable pointer once, then pass an immutable GenerationSelection through an operation
    - preserve public ontology table names through ontology-generation-alias/v1
    - scan direct ontology markers against an executable consumer manifest

key-files:
  created:
    - src/ontology_discovery/generation_resolver.py
    - tests/test_ontology_generation_consumers.py
    - docs/ontology-generation-consumer-inventory.md
  modified:
    - src/api/runtime.py
    - src/fabric/data_agent_manager.py
    - src/fabric/semantic_model_manager.py
    - src/operations/tools.py
    - src/api/routers/twin.py
    - src/semantic/semantic_registry.py

key-decisions:
  - "Keep ontology_entities and ontology_relationships as stable public names while compatibility alias metadata binds them to one immutable generation."
  - "Resolve a generation once per API mapping, Operations tool call, or twin composition; promotion and rollback affect only subsequent operations."
  - "Preserve root STATE.md Phase 03.1 ownership because Phase 13 is an explicitly approved concurrent isolated workstream."

patterns-established:
  - "Generation read boundary: mutable pointer -> GenerationResolver -> immutable GenerationSelection -> all reads in one operation."
  - "Consumer completeness: repository marker scan must be a subset of the reviewed five-family inventory."

requirements-completed: [AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: "GenerationResolver returns active, prior, source, ETag, URI, and alias-version metadata while pinning immutable dataset reads."
    requirement: AUTO-ONT-05
    verification:
      - kind: unit
        ref: "tests/test_ontology_generation_consumers.py#test_resolver_returns_one_immutable_generation_snapshot"
        status: pass
    human_judgment: false
  - id: D2
    description: "The executable inventory covers API, Fabric, agent, export, and semantic consumers and rejects unlisted direct readers."
    requirement: AUTO-ONT-06
    verification:
      - kind: unit
        ref: "tests/test_ontology_generation_consumers.py#test_repository_inventory_has_no_unlisted_direct_consumer"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_generation_consumers.py#test_inventory_scan_detects_new_direct_consumer"
        status: pass
    human_judgment: false
  - id: D3
    description: "API, Fabric, Operations, twin export, and semantic registry consumers follow old/new/old pointer transitions without contract-name changes."
    requirement: AUTO-ONT-07
    verification:
      - kind: integration
        ref: "uv run pytest -q tests/test_ontology_generation_consumers.py"
        status: pass
      - kind: integration
        ref: "153-test Plan 13-06 regression suite"
        status: pass
    human_judgment: false

duration: 11min
completed: 2026-09-06
status: complete
---

# Phase 13 Plan 06: Ontology Generation Consumer Cutover Summary

**Immutable request-scoped generation resolution, versioned Fabric aliases, and executable five-family inventory now keep ontology consumers coherent across promotion and rollback.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-09-06T14:27:45Z
- **Completed:** 2026-09-06T14:38:06Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- Added `GenerationResolver`, which validates generation containment and captures active generation, prior generation, source generation, pointer ETag, external URI, and compatibility alias version before any rows are read.
- Added a documented, executable inventory across API, Fabric, agent, export, and semantic families; repository scanning now detects any new unlisted direct ontology marker.
- Migrated API snapshot mapping, Fabric Data Agent/semantic definitions, Operations tool providers, twin composition/export, and SemanticRegistry aliases to operation-scoped generation bindings while preserving public table and response contracts.
- Proved old-generation, promoted-generation, and rolled-back-generation behavior in one shared contract suite, including fail-closed handling when a pointer cannot be resolved.

## Task Commits

Each TDD task was committed with a RED test followed by GREEN implementation:

1. **Task 1 RED: Generation resolver and inventory contracts** - `2e3bbf90`
2. **Task 1 GREEN: Immutable resolver and executable inventory** - `eacfe432`
3. **Task 2 RED: API, Fabric, and agent cutover contracts** - `515b8a65`
4. **Task 2 GREEN: API, Fabric, and agent generation binding** - `27f210cb`
5. **Task 3 RED: Twin and semantic rollback contracts** - `cf162bdd`
6. **Task 3 GREEN: Twin and semantic generation binding** - `af5ce0b0`
7. **Correctness hardening: fail-closed unavailable pointer handling** - `febc3cf4`

## Files Created/Modified

- `src/ontology_discovery/generation_resolver.py` - Immutable selection, safe reads, compatibility aliases, inventory manifest, and direct-consumer scanner.
- `tests/test_ontology_generation_consumers.py` - Resolver, inventory, alias, promotion, rollback, and unavailable-pointer contracts.
- `docs/ontology-generation-consumer-inventory.md` - Owners, read paths, dispositions, and rollback assertions for all five consumer families.
- `src/api/runtime.py` - Resolves each connection generation once before mapping snapshot tables.
- `src/fabric/data_agent_manager.py` - Validates generation-bound aliases while preserving Data Agent table names and schema.
- `src/fabric/semantic_model_manager.py` - Binds Direct Lake tables to one generation and records generation annotations.
- `src/operations/tools.py` - Pins generation-aware providers once per tool invocation and fails closed when resolution is unavailable.
- `src/api/routers/twin.py` - Pins generation-aware providers once per twin composition/export.
- `src/semantic/semantic_registry.py` - Creates generation-bound semantic definitions over stable logical source names.

## Decisions Made

- Stable logical table names remain the public compatibility contract. Physical generation paths never leak into Data Agent or semantic-model table names.
- A provider may implement `for_generation(selection)` to participate in operation-level pinning without breaking existing provider interfaces.
- Existing local test/read-port doubles that implement only `current_generation()` remain compatible, while real `DatasetStore` instances retain strict generations-root containment.
- Root `.planning/STATE.md`, `.planning/ROADMAP.md`, and `.planning/REQUIREMENTS.md` were intentionally not advanced because this plan belongs to the approved concurrent Phase 13 workstream and Phase 03.1 remains active.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restored semantic model definition assembly after helper placement**
- **Found during:** Task 2 (Fabric semantic model alias integration)
- **Issue:** The first edit placed the alias helper before the remaining definition assembly, leaving that assembly unreachable.
- **Fix:** Moved the helper below the complete definition builder before running GREEN and regression tests.
- **Files modified:** `src/fabric/semantic_model_manager.py`
- **Verification:** Semantic model manager tests and the full Plan 13-06 regression set passed.
- **Committed in:** `27f210cb`

**2. [Rule 2 - Missing Critical] Added fail-closed pointer error handling**
- **Found during:** Overall verification
- **Issue:** A configured but unavailable or malformed generation pointer could escape an Operations tool call as an exception, and legacy API snapshot loaders could fail rather than degrade.
- **Fix:** Operations returns a governed unavailable result and API snapshot loading isolates invalid pointer state.
- **Files modified:** `src/api/runtime.py`, `src/operations/tools.py`, `tests/test_ontology_generation_consumers.py`
- **Verification:** Dedicated unavailable-pointer test plus API runtime and Operations regressions passed.
- **Committed in:** `febc3cf4`

---

**Total deviations:** 2 auto-fixed (1 bug, 1 missing critical functionality)
**Impact on plan:** Both changes were required for correctness and fail-closed behavior; neither expanded feature scope.

## Issues Encountered

- The Phase 13 dependency preflight passed both before implementation and after all task commits.
- Current HEAD was verified to contain Phase 03.1-14 (`0204c027`), Phase 11 snapshot v2 (`3921aa9d`, `19914ae1`), and Phase 13 evaluation snapshot (`c0a10435`) ancestry before editing.
- Ruff identified import ordering and exception-type issues during task-level verification; both were corrected before the corresponding GREEN commits.

## Verification

- `uv run python .planning/scripts/preflight_phase_13.py` — passed.
- `uv run pytest -q tests/test_ontology_generation_consumers.py` — passed.
- Required task filters (`inventory or resolver`; `api or fabric or agent or operations or alias`; `twin or semantic or inventory or rollback`) — passed.
- Relevant API, twin, Fabric, Operations, publication, semantic, and network regressions — 153 passed.
- `uv run ruff check` over all Plan 13-06 source files and the consumer suite — passed.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 13-06 is complete; the resolver and alias contracts are ready for the later publisher and cutover checkpoint plans.
- Plan 13-08 must retain the compatibility alias until its blocking cutover decision.
- No Plan 13-04 or later plan was started as part of this execution.

## Self-Check: PASSED

- All ten implementation, test, documentation, and summary artifacts exist.
- All seven task and corrective commits are present in repository history.
- Root `.planning/STATE.md` still identifies Phase 03.1 / Plan 03.1-15 as the active workstream.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-06*
