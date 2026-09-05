---
phase: 12-network-topology-integrity-and-scale
plan: 06
subsystem: network-topology
tags: [private-link, microsoft-fabric, cognitive-services, cytoscape, azure-icons]
requires:
  - phase: 12-network-topology-integrity-and-scale
    plan: 01
    provides: Scoped network snapshots that fail closed at the subscription boundary
  - phase: 12-network-topology-integrity-and-scale
    plan: 03
    provides: Case-normalized resource and finding identifiers
  - phase: 12-network-topology-integrity-and-scale
    plan: 05
    provides: Confirmed Fabric tenant/workspace private-link semantics and V21 icon disposition
provides:
  - Case-insensitive, de-duplicated projection of private-link candidates into topology resources
  - Fabric capacity gap suppression with tenant/workspace scope qualification
  - Azure AI Services V21 icon and intentional icon-less Fabric rendering
  - Client recognition of named and generic private-link workload entity types
affects: [12-07, network-canvas, network-findings, topology-drawer]
actuals:
  tokens: 6189
  tasks: 3
  commits: 7
tech-stack:
  added: []
  patterns:
    - Private-link candidates reconcile through case-folded ARM resource IDs
    - Unsupported product glyphs use the existing icon-less workload tile
key-files:
  created:
    - web/public/azure-icons/ai-services.svg
    - .planning/phases/12-network-topology-integrity-and-scale/deferred-items.md
    - .planning/phases/12-network-topology-integrity-and-scale/12-06-SUMMARY.md
  modified:
    - src/network/models.py
    - src/network/topology.py
    - src/network/gaps.py
    - tests/test_network_topology.py
    - tests/test_network_analysis.py
    - web/src/lib/network-graph.ts
    - web/src/lib/network-graph.test.ts
    - web/public/azure-icons/README.md
key-decisions:
  - "Microsoft.Fabric/capacities remains visible as a Fabric workload candidate, but its false per-capacity missing_private_endpoint finding is suppressed because Fabric private-link posture is tenant/workspace scoped."
  - "Microsoft.CognitiveServices/accounts keeps its high-severity per-resource missing_private_endpoint finding and maps to the official V21 Cognitive Services icon."
  - "Fabric intentionally has no RESOURCE_ICONS entry because Azure Public Service Icons V21 contains only Service Fabric glyphs, not a Microsoft Fabric product glyph."
patterns-established:
  - "Private-link resource candidates supersede attached-workload placeholders while retaining one case-insensitive graph identity."
  - "Unknown PrivateLinkResource entities are workload nodes with the existing dashed, icon-less treatment."
requirements-completed: [TOPO-02]
coverage:
  - id: D1
    description: Private-link candidates project once, remain scope-safe, and expose truthful Fabric and Cognitive Services findings.
    requirement: TOPO-02
    verification:
      - kind: integration
        ref: tests/test_network_topology.py#TestPrivateLinkProjection
        status: pass
      - kind: integration
        ref: tests/test_network_analysis.py#scoped private-link regressions
        status: pass
      - kind: integration
        ref: tests/test_network_downstream_scope.py
        status: pass
    human_judgment: false
  - id: D2
    description: The official unmodified V21 Cognitive Services asset is installed while Fabric uses the documented icon-less fallback.
    requirement: TOPO-02
    verification:
      - kind: unit
        ref: web/src/lib/network-graph.test.ts#uses only the available V21 icon and documents Fabric's icon-less fallback
        status: pass
      - kind: other
        ref: Byte comparison against Azure_Public_Service_Icons_V21.zip/10162-icon-service-Cognitive-Services.svg
        status: pass
    human_judgment: false
  - id: D3
    description: Named and generic private-link entities build as de-duplicated workload nodes with correct icon behavior and stable badge target IDs.
    requirement: TOPO-02
    verification:
      - kind: unit
        ref: web/src/lib/network-graph.test.ts#private-link graph cases
        status: pass
      - kind: unit
        ref: web/src/components/network/TopologyGraph.test.tsx
        status: pass
    human_judgment: false
duration: 19 min
completed: 2026-09-05
status: complete
---

# Phase 12 Plan 06: Private-Link Topology Projection Summary

**Scope-safe private-link projection now renders Fabric and Azure AI Services workloads exactly once, preserves truthful finding semantics, and uses only the official V21 Cognitive Services glyph.**

## Performance

- **Duration:** 19 min
- **Started:** 2026-09-05T16:33:43Z
- **Completed:** 2026-09-05T16:52:43Z
- **Tasks:** 3
- **Files modified:** 11, including this summary and the deferred-items ledger

## Accomplishments

- Projected every scoped private-link candidate through the existing resource-node path, mapped known providers to frontend workload entity types, and reconciled duplicate ARM IDs case-insensitively.
- Implemented the confirmed Fabric decision at the authoritative server surfaces: capacity nodes carry tenant/workspace scope qualification, per-capacity `missing_private_endpoint` findings are suppressed, and Cognitive Services findings remain unchanged.
- Added the byte-identical official Azure Public Service Icons V21 Cognitive Services asset while documenting and testing the intentional icon-less Fabric fallback.
- Registered `PrivateLinkResource` as a workload entity and mapped `AIFoundryAccount` to `ai-services.svg` without adding a node kind, color, shape, Fabric icon, or package dependency.

## Plan 12-02 Fixture Impact

The projection caused **no net node-count increase** on the three Plan 12-02 full-detail fixtures because every generated private-link candidate in those fixtures was already represented by an attached-workload target. The new case-insensitive reconciliation replaced each placeholder with the richer inventory-backed node rather than appending a duplicate.

| Fixture | Plan 12-02 baseline | After Plan 12-06 | Increase | Private-link candidates |
| --- | ---: | ---: | ---: | ---: |
| Small | 1,330 | 1,330 | +0 | 20 |
| Mid | 6,930 | 6,930 | +0 | 60 |
| Enterprise | 34,600 | 34,600 | +0 | 200 |

This preserves the existing Plan 12-02 node budgets while still making previously unattached private-link candidates visible in real snapshots.

## Icon Disposition

- `web/public/azure-icons/ai-services.svg` has SHA-256 `7f1d2831085f00103df5f6fd6305bdbbbe4c4530e98831d7ce6508d236c467c2`.
- It is byte-for-byte identical to both V21 archive copies of `10162-icon-service-Cognitive-Services.svg`.
- The V21 archive's only filenames containing “Fabric” are Service Fabric Cluster assets. Those represent Azure Service Fabric, not Microsoft Fabric, and were not substituted.
- Microsoft Fabric therefore remains intentionally icon-less on the existing dashed workload tile.

## Task Commits

1. **Task 1 RED: Private-link projection and Fabric semantics tests** — `456496cc`
2. **Task 1 GREEN: Server projection, de-duplication, qualification, and gap correction** — `a67af42f`
3. **Task 2 RED: Icon disposition test** — `deb651c1`
4. **Task 2 GREEN: Official AI Services icon and Fabric fallback documentation** — `52617d99`
5. **Task 3 RED: Client graph recognition and de-duplication tests** — `8032a701`
6. **Task 3 GREEN: Client workload recognition and icon mapping** — `529c9309`

**Plan metadata:** committed with this summary.

## Files Created/Modified

- `src/network/models.py` — shared Fabric capacity type and tenant/workspace scope constants.
- `src/network/topology.py` — private-link candidate projection, provider mapping, case-insensitive reconciliation, and Fabric node qualification.
- `src/network/gaps.py` — suppression of unsupported per-capacity Fabric endpoint findings while retaining per-resource Cognitive Services analysis.
- `tests/test_network_topology.py` — mapped, generic, de-duplicated, scope-safe, and gap-to-node projection coverage.
- `tests/test_network_analysis.py` — Fabric suppression and Cognitive Services retention regressions.
- `web/public/azure-icons/ai-services.svg` — unmodified official V21 Cognitive Services asset.
- `web/public/azure-icons/README.md` — Azure AI Services entry and explicit icon-less Fabric disposition.
- `web/src/lib/network-graph.ts` — AI icon mapping, generic private-link workload recognition, and case-insensitive client de-duplication.
- `web/src/lib/network-graph.test.ts` — five client graph behavior cases plus icon asset/disposition coverage.
- `.planning/phases/12-network-topology-integrity-and-scale/deferred-items.md` — unrelated full-repository Ruff findings recorded for later cleanup.

## Decisions Made

- Applied `12-FABRIC-PRIVATE-LINK-DECISION.md` verbatim: Fabric capacity is a visible candidate but not a valid per-resource endpoint-compliance target.
- Preserved the Cognitive Services high-severity finding because its private endpoint is supported at individual-resource scope.
- Preferred an inventory-backed private-link candidate over an attached-workload placeholder when both case-fold to the same ARM resource ID.
- Kept Fabric icon-less rather than borrowing Service Fabric artwork or introducing a second icon source/package.

## Deviations from Plan

None - the plan's conditional icon fallback and the authoritative Fabric decision were followed exactly.

## Verification

- Task 1 exact verification (`test_network_topology.py`, `test_network_analysis.py`, `test_network_downstream_scope.py`) — **101 passed**.
- Plan-level backend topology/link/scope verification — **115 passed**.
- Task 2 icon disposition test — **1 passed**; README command reported **30 `svg` lines** and no `fabric.svg`.
- Official V21 archive comparison — **2/2 Cognitive Services archive copies byte-identical**; SHA-256 matched.
- Task 3 graph verification — **60 passed**.
- Plan-level web network verification — **2 files, 71 tests passed**.
- Full backend per-wave gate — **2,662 passed, 35 skipped**.
- Full web per-wave gate — **39 files passed; 256 tests passed, 15 todo**.
- TypeScript (`npx tsc --noEmit`) — **passed**.
- Ruff over all Plan 12-06 Python files — **passed**.
- Package-manifest comparison from the pre-plan base — **no changes** to `web/package.json`, `web/package-lock.json`, `package.json`, `pyproject.toml`, or `uv.lock`.
- Scope-security regressions — **passed** within the 101-test Task 1 gate and 115-test plan-level backend gate.

## Issues Encountered

- `ruff check .` reports **27 pre-existing findings** in unrelated `infra/scripts/` and `scripts/` files. Plan 12-06 did not touch those files; the scoped Ruff gate passes. The findings are recorded in `deferred-items.md`. Best-effort `WINDOWS.md` registration was rejected because the existing ledger contains unsupported legacy kind `live-source-data`.

## Known Stubs

None. The changed empty values are model defaults and graph collection initializers, not UI-facing placeholders or unwired data.

## User Setup Required

None.

## Next Phase Readiness

- Plan 12-07 can apply its level-of-detail contract without adjusting the Plan 12-02 fixture node ceilings.
- Finding consumers now receive the same server-authoritative Fabric correction and can attach all remaining private-link findings to visible nodes.

## Self-Check: PASSED

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-05*
