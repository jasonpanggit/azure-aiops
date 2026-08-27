---
phase: 08-resource-identity-plane
plan: 01
subsystem: inventory-hermes-bridge
tags: [inventory-read-port, containment, hermes, normalizer, characterization-test, identity-source-flag]

requires:
  - phase: 07-unified-resource-inventory
    provides: "ResourceObservation lossless model with provider_payload, InventoryReadPort scope-enforced read port"
provides:
  - "InventoryReadPort.list_containment() deriving management-group/subscription/resource-group rows in-process from existing observation data"
  - "get_resource() containment sub-object (management_group_id/subscription_id/resource_group_id)"
  - "InventoryReadAdapter.to_arg_rows() pure translation layer proving lossless equivalence"
  - "Characterization test proving byte-identical NormalizedGraph output between direct-ARG and inventory-read-port-adapter paths"
  - "ConnectorConfig.identity_source flag (defaulted off) wired into IngestionService"
affects: [08-02-topology-pipeline, 08-03-comparison-and-removal-gate]

actuals:
  tokens: 10100
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Pure in-process containment derivation from existing observation rows instead of a new ARG acquisition path"
    - "Additive translation-layer adapter (InventoryReadAdapter) that never re-derives nested properties, only passes them through"

key-files:
  created:
    - src/hermes_arg_connector/inventory_read_adapter.py
    - tests/test_network_normalize_from_inventory.py
  modified:
    - src/intelligence/inventory/read_port.py
    - src/intelligence/inventory/models.py
    - src/hermes_arg_connector/config.py
    - src/hermes_arg_connector/service.py
    - tests/test_inventory_read_port.py
    - tests/inventory_harness.py

key-decisions:
  - "Containment derived purely in-process from existing ResourceObservation rows (subscription_id/resource_group) — no new Fabric table, no separate ResourceContainers acquisition path, per ROADMAP success criterion 2"
  - "Management-group ancestry left explicitly None (not fabricated) since ResourceObservation does not yet carry it — a persisted containment table is deferred to a follow-up, not silently added here"
  - "identity_source flag defaults to 'arg'; IngestionService only requires an inventory_read_port when identity_source == 'inventory', preserving zero behavior change for existing deployments"

patterns-established:
  - "Characterization tests compare JSON-serialized (sort_keys) rows rather than hashing dicts with nested lists, to get byte-identical proof without unhashable-type errors"

requirements-completed: [INV-07, INV-08, INV-10, INV-11, INV-12]

coverage:
  - id: D1
    description: "InventoryReadPort exposes containment hierarchy (list_containment + get_resource containment sub-object)"
    requirement: "INV-11"
    verification:
      - kind: unit
        ref: "tests/test_inventory_read_port.py::test_list_containment_returns_strict_parent_chain"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_read_port.py::test_get_resource_includes_containment_sub_object"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_read_port.py::test_get_resource_without_resource_group_resolves_subscription_only_containment"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_read_port.py::test_list_containment_requires_scope"
        status: pass
    human_judgment: false
  - id: D2
    description: "Hermes's real normalizers produce byte-identical output fed via InventoryReadAdapter vs. direct ARG payload (Pitfall 1 losslessness proof)"
    requirement: "INV-11"
    verification:
      - kind: unit
        ref: "tests/test_network_normalize_from_inventory.py::test_read_port_adapter_produces_byte_identical_entities_and_relationships"
        status: pass
      - kind: unit
        ref: "tests/test_network_normalize_from_inventory.py::test_subnet_nested_delegations_and_service_endpoints_round_trip_exactly"
        status: pass
      - kind: unit
        ref: "tests/test_network_normalize_from_inventory.py::test_resource_with_empty_properties_bag_is_empty_safe_on_both_paths"
        status: pass
      - kind: integration
        ref: "pytest tests/test_impact_analysis.py -x -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "Explicit, currently-inert identity_source flag exists for Hermes ingestion, defaulted off, ARG queries untouched"
    requirement: "INV-07, INV-08, INV-10, INV-12"
    verification:
      - kind: unit
        ref: "tests/inventory_harness.py::test_identity_source_inventory_matches_identity_source_arg"
        status: pass
      - kind: unit
        ref: "tests/inventory_harness.py::test_identity_source_defaults_to_arg_with_no_behavior_change"
        status: pass
      - kind: other
        ref: "git diff --stat src/hermes_arg_connector/queries.py (empty — no ARG spec changes)"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-08-27
status: complete
---

# Phase 08 Plan 01: Resource Identity Plane — Read-Port Extension Summary

**Extended the inventory read port with a derived containment hierarchy and a lossless-property translation adapter, then proved via characterization test that Hermes's existing normalizers produce byte-identical output when fed from the inventory read port instead of direct ARG queries — the load-bearing risk proof for the whole Phase 8 pivot.**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-08-27T02:50:00Z
- **Completed:** 2026-08-27T03:38:01Z
- **Tasks:** 3/3 completed
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments

- `InventoryReadPort.list_containment()` derives subscription/resource-group rows in-process from existing `ResourceObservation` data — no new Fabric table, no separate `ResourceContainers` acquisition path (ROADMAP success criterion 2).
- `InventoryReadAdapter.to_arg_rows()` is a pure translation layer that reconstructs the exact `resources`/`resource_containers` row shape `Normalizer.normalize()` already consumes, passing `provider_payload` through unchanged.
- Characterization test proves byte-identical `NormalizedGraph` entity/relationship output between a direct-ARG payload and the same data round-tripped through `ResourceObservation` → `InventoryReadPort` → `InventoryReadAdapter`, for a VM+VNet+Subnet+NSG+NIC fixture covering the deepest nested property-access pattern (subnet `delegations`/`serviceEndpoints`) plus an empty-properties edge case.
- `ConnectorConfig.identity_source` flag (`"arg"` | `"inventory"`, default `"arg"`) wired into `IngestionService._run_locked()`; when flipped, only the `resources`/`resource_containers` specs are sourced via the inventory read port — everything else (network_*, patch, advisor, cost, role, changes) is untouched.
- No ARG identity queries removed — `queries.py` is byte-for-byte unchanged (`git diff --stat` empty), correctly deferring removal to 08-03 per D-08.

## Task Commits

Each task was committed atomically:

1. **Task 1: Read port exposes containment hierarchy end-to-end for one resource** - `dfafd98` (feat)
2. **Task 2: Prove read-port losslessness against Hermes's real normalizers (Pitfall 1)** - `69f0bd2` (feat)
3. **Task 3: Wire an explicit, defaulted-off identity-source flag for Hermes ingestion** - `a837d72` (feat)

**Plan metadata:** (this commit, see below)

## Files Created/Modified

- `src/intelligence/inventory/read_port.py` - Added `list_containment()` and a `containment` sub-object on `get_resource()`; scope enforcement (`_require_scope`) applied to the new method (T-08-01)
- `src/intelligence/inventory/models.py` - Extended `ResourceObservation.to_api_dict()` to include `tags` and `properties` (lossless raw payload) so read-port consumers can reconstruct nested ARG shapes
- `src/hermes_arg_connector/inventory_read_adapter.py` - New pure translation layer: `InventoryReadAdapter.to_arg_rows()` maps read-port containment/resource rows back into ARG row shape, unchanged `properties` passthrough
- `tests/test_inventory_read_port.py` - Added containment tests (strict parent chain, scope guard, resource-group-less edge case)
- `tests/test_network_normalize_from_inventory.py` - New characterization test module proving byte-identical entities/relationships across direct-ARG vs. adapter paths
- `src/hermes_arg_connector/config.py` - Added `identity_source: str = "arg"` field + validation + YAML load support
- `src/hermes_arg_connector/service.py` - `IngestionService` accepts optional `inventory_read_port`; `_identity_rows_from_inventory()` swaps `resources`/`resource_containers` sourcing when `identity_source == "inventory"`
- `tests/inventory_harness.py` - Added `run_hermes_ingestion()` seam and parametrized `identity_source=arg/inventory` equivalence tests against the same golden fixture

## Decisions Made

- Derive containment purely from existing `ResourceObservation.subscription_id`/`resource_group` fields rather than introducing a persisted containment table — satisfies the "no separate acquisition path" success criterion with data inventory already owns; a richer containment table (with tenant/tags/state) is explicitly deferred, not silently added.
- Management-group ancestry is left `None` in the containment sub-object rather than fabricated, since `ResourceObservation` does not yet carry management-group identity (that's a Phase 8-02/future-source concern).
- The identity-source comparison test in `inventory_harness.py` compares only the entity families and `belongsTo` relationships that the flag actually swaps (`Resource`/`VirtualMachine`/`ArcServer`), not containment `Subscription`/`ResourceGroup` entities — those necessarily differ in fidelity (tags/tenantId/state) between a full ARG `ResourceContainers` query and the derived containment rows, which is the correctly scoped, non-fabricated behavior from Task 1.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Set comparison over dict entities failed with unhashable nested lists**
- **Found during:** Task 2 (characterization test authoring)
- **Issue:** Normalized entities/relationships contain nested `list` values (e.g., `delegations`, `serviceEndpoints`), which cannot be placed in a `frozenset` for set-based equality comparison.
- **Fix:** Compared JSON-serialized (`sort_keys=True`) row strings instead of hashing dict items directly — preserves exact byte-identical proof without an unhashable-type error.
- **Files modified:** tests/test_network_normalize_from_inventory.py
- **Verification:** All 3 characterization tests pass.
- **Committed in:** `69f0bd2` (part of Task 2 commit)

**2. [Rule 3 - Blocking issue] `inventory_harness.py` has no `test_`-prefixed collection until Task 3 needed it as a pytest target**
- **Found during:** Task 3
- **Issue:** The plan's verify command runs `pytest tests/inventory_harness.py -x -q`, but the file only contained helper functions (no test functions), so pytest collected 0 tests — a silent false-positive pass.
- **Fix:** Added `test_identity_source_inventory_matches_identity_source_arg` and `test_identity_source_defaults_to_arg_with_no_behavior_change` directly in `inventory_harness.py`, alongside the new `run_hermes_ingestion()` seam, per the plan's explicit instruction to "extend tests/inventory_harness.py's existing seam."
- **Files modified:** tests/inventory_harness.py
- **Verification:** `pytest tests/inventory_harness.py -x -q` now collects and passes 2 tests.
- **Committed in:** `a837d72` (part of Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking issues in test infrastructure)
**Impact on plan:** No scope creep; both fixes were necessary to make the plan's own `<verify>` commands actually exercise the intended behavior.

## Issues Encountered

- Three pre-existing test failures unrelated to this plan's file scope were observed in the full-suite run (`tests/test_onelake_fs.py::test_resolve_fs_selects_the_dfs_native_backend`, `tests/test_situations_ontology.py::test_situations_are_registered_as_ontology_entities_with_typed_links`, `tests/test_storage.py::test_partial_publish_preserves_hash_baseline_for_next_full_publish`). Confirmed pre-existing by running the same three tests against a stashed (pre-plan) working tree — same 3 failures. Out of scope per the executor's scope-boundary rule (none of the touched files are in this plan's `files_modified` list); not fixed. Logged here for visibility, not silently ignored.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The read-port containment + lossless-properties path is proven equivalent for Hermes's existing identity+network normalizers. Plan 08-02 (Fabric-native topology pipeline) and 08-03 (comparison report + operator-gated removal decision) can proceed on this foundation.
- `identity_source` flag exists but stays at `"arg"` in all real deployments until 08-03's explicit, operator-approved cutover — no runtime behavior has changed for existing consumers.
- Follow-up not addressed here (correctly deferred): a persisted containment table carrying management-group ancestry and full ResourceContainers fidelity (tags/tenantId/state) if a future consumer needs it beyond the ID-chain proof built in this plan.

---
*Phase: 08-resource-identity-plane*
*Completed: 2026-08-27*

## Self-Check: PASSED

All 3 commit hashes (dfafd98, 69f0bd2, a837d72) verified present in git log. All created/modified files verified present on disk.

