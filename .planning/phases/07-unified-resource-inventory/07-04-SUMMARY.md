---
phase: 07-unified-resource-inventory
plan: 04
subsystem: inventory
tags: [fabric, inventory, resource-observation, registry, parquet]
requires:
  - phase: 07-unified-resource-inventory
    provides: [07-03 Fabric inventory contracts and standalone pipeline]
provides:
  - Lossless ResourceObservation contract with Fabric-safe payload serialization
  - Resource-observation Fabric table mapping and schema
  - Inventory family registry for OS, software, and generalized resources
affects: [phase-7, phase-8, phase-9, inventory, fabric, hermes]
actuals:
  tokens: 3325
  tasks: 3
  commits: 2
tech-stack:
  added: []
  patterns:
    - Canonical JSON payload columns for heterogeneous provider payloads in Fabric tables
    - Registry-owned family metadata and collision validation
key-files:
  created:
    - src/intelligence/inventory/registry.py
    - tests/test_inventory_resource_contract.py
  modified:
    - src/intelligence/inventory/models.py
    - src/intelligence/inventory/fabric_contracts.py
    - src/intelligence/inventory/fabric_publication.py
    - src/intelligence/inventory/__init__.py
    - tests/test_inventory_fabric_contract.py
key-decisions:
  - "ResourceObservation retains raw provider properties internally and serializes them to provider_payload_json for Fabric/Delta/Parquet stability."
  - "Raw provider payload remains internal-only; existing MachineObservation/API serialization stays unchanged."
patterns-established:
  - "Use ResourceObservation.to_fabric_row/from_fabric_row for payload encoding and decoding."
  - "Use default_inventory_registry as the family-to-Fabric binding catalog."
requirements-completed: [INV-08, INV-10, INV-12]
coverage:
  - id: D1
    description: "Lossless ResourceObservation JSONL and Parquet round trip"
    requirement: INV-08
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_inventory_resource_contract.py tests/test_inventory_fabric_contract.py -p no:cacheprovider"
        status: pass
    human_judgment: false
  - id: D2
    description: "MachineObservation compatibility and API payload redaction"
    requirement: INV-10
    verification:
      - kind: integration
        ref: "uv run pytest tests/test_inventory_resource_contract.py tests/test_inventory_characterization.py tests/test_inventory_provider.py tests/test_api_inventory_router.py -p no:cacheprovider"
        status: pass
    human_judgment: false
  - id: D3
    description: "Inventory family registry with Fabric table bindings and collision guards"
    requirement: INV-08
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_inventory_resource_contract.py tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py tests/test_inventory_mapping.py tests/test_inventory_eol.py -p no:cacheprovider"
        status: pass
    human_judgment: false
duration: 7min
completed: 2026-08-26
status: complete
---

# Phase 7 Plan 04: Fabric Resource Observation Contract Summary

**Lossless resource identity observations now serialize safely to Fabric while legacy OS/software APIs stay payload-free.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-08-26T06:55:00Z
- **Completed:** 2026-08-26T07:02:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Added `ResourceObservation` with immutable typed projections plus deep-copied provider payload retention.
- Added canonical JSON encoding/decoding through `provider_payload_json`, proven through JSONL and Parquet reads.
- Registered `inventory/resource_observations -> inventory_resource_observations`.
- Added `InventoryFamilyRegistry` for OS, software, and generalized resource families with duplicate logical/table rejection.
- Preserved MachineObservation row shape and API non-leakage expectations.

## Task Commits

1. **Task 1 RED: Resource contract tests** - `be26b5c` (test)
2. **Tasks 1-3 GREEN: ResourceObservation, contract, registry** - `6aa57e1` (feat)

## Decisions Made

- Resource provider payloads are retained only as internal immutable/deep-copied state and as canonical Fabric JSON columns.
- Assessment-domain fields are rejected as schema extras instead of maintained through a keyword blacklist.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved row identity-independent assertions**
- **Found during:** Task 1.
- **Issue:** DatasetStore sorts rows by semantic content, so round-trip tests could not assume input ordering.
- **Fix:** Asserted round-trip equality by resource ID.
- **Files modified:** `tests/test_inventory_resource_contract.py`
- **Verification:** 07-04 verification commands passed.
- **Committed in:** `6aa57e1`

## Issues Encountered

- Existing unrelated dirty work remained present; plan-owned files were committed path-limited.

## Verification

- `uv run pytest tests/test_inventory_resource_contract.py tests/test_inventory_fabric_contract.py -p no:cacheprovider` — passed (15 tests).
- `uv run pytest tests/test_inventory_resource_contract.py tests/test_inventory_characterization.py tests/test_inventory_provider.py tests/test_api_inventory_router.py -p no:cacheprovider` — passed (43 tests).
- `uv run pytest tests/test_inventory_resource_contract.py tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py tests/test_inventory_mapping.py tests/test_inventory_eol.py -p no:cacheprovider` — passed (31 tests).
- `grep -v '^#' src/intelligence/inventory/fabric_contracts.py | grep -ci 'vulnerab\|advisor\|patch_state\|policy_evaluation\|health_status'` — returned `0`.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

07-05 can use the resource-observation contract and family registry to add PaaS family availability.

## Self-Check: PASSED

- Summary file created at `.planning/phases/07-unified-resource-inventory/07-04-SUMMARY.md`.
- Task commits exist: `be26b5c`, `6aa57e1`.

---
*Phase: 07-unified-resource-inventory*
*Completed: 2026-08-26*
