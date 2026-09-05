---
phase: 12-network-topology-integrity-and-scale
plan: 02
subsystem: testing
tags: [network-topology, scale, pytest, vitest, cytoscape, compatibility]
requires:
  - phase: 12-network-topology-integrity-and-scale
    provides: Phase base commit d57f6137d747c344c56028d7e6211811927d0b43
provides:
  - Deterministic small, mid, enterprise, and frozen G-4 network estates
  - Concrete G-1, G-2, and G-3 scale gates with measured full-detail baselines
  - Detached pre-phase default-path compatibility artifact with fail-closed provenance
  - Empirical Cytoscape canvas ceiling and shared web network fixture builders
affects: [12-07, 12-09, 12-11, topology-contract, network-ui-tests]
actuals:
  tokens: 51695
  tasks: 4
  commits: 8
tech-stack:
  added: []
  patterns:
    - Real-model deterministic scale fixtures
    - Detached-worktree compatibility capture
    - Serialized-byte topology budgets
key-files:
  created:
    - tests/network_scale_fixtures.py
    - tests/test_network_scale.py
    - tests/network_baseline.py
    - tests/test_network_prephase_baseline.py
    - .planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json
    - web/src/test/network-fixtures.ts
  modified:
    - web/src/components/ui/StatusBadge.test.tsx
key-decisions:
  - "The phase base is d57f6137d747c344c56028d7e6211811927d0b43, and baseline recording fails unless HEAD is detached at that exact commit."
  - "The measured interactive canvas ceiling is 1,500 nodes under a 250 ms single-pass threshold; evidence did not require lowering the UI contract maximum."
  - "Enterprise filler volume uses real NetworkInterface models rather than oversized firewall collections so the 34,600-node fixture remains below the one-second build gate."
patterns-established:
  - "Compatibility artifacts retain serialized bodies, byte lengths, top-level keys, representative item keys, and commit provenance."
  - "Scale tests assert both graph element counts and serialized payload bytes."
requirements-completed: [TOPO-03, TOPO-05]
coverage:
  - id: D1
    description: Deterministic real-model estate builders reproduce 1,330, 6,930, and 34,600 topology nodes.
    requirement: TOPO-03
    verification:
      - kind: unit
        ref: tests/test_network_scale.py#test_fixtures_build_expected_shapes
        status: pass
      - kind: unit
        ref: tests/test_network_scale.py#test_full_detail_payload_baselines
        status: pass
    human_judgment: false
  - id: D2
    description: G-1 and G-2 constants are fixed and enterprise topology construction remains below the G-3 one-second budget.
    requirement: TOPO-03
    verification:
      - kind: unit
        ref: tests/test_network_scale.py#test_g2_budgets_are_declared
        status: pass
      - kind: unit
        ref: tests/test_network_scale.py#test_enterprise_build_latency_budget
        status: pass
    human_judgment: false
  - id: D3
    description: A private-link-free detached baseline records default topology, gaps, and rule-findings responses plus empirical canvas measurements.
    requirement: TOPO-05
    verification:
      - kind: integration
        ref: tests/test_network_prephase_baseline.py#test_baseline_is_recorded_and_self_consistent
        status: pass
      - kind: automated_ui
        ref: Vitest jsdom/headless Cytoscape measurement recorded in 12-PRE-PHASE-BASELINE.json
        status: pass
    human_judgment: false
  - id: D4
    description: Shared web fixtures build network envelopes at arbitrary totals and the seven-tone status palette is pinned.
    requirement: TOPO-03
    verification:
      - kind: unit
        ref: web/src/components/ui/StatusBadge.test.tsx
        status: pass
      - kind: other
        ref: cd web && npx --no-install tsc --noEmit
        status: pass
    human_judgment: false
duration: 13 min
completed: 2026-09-05
status: complete
---

# Phase 12 Plan 02: Network Scale and Pre-Phase Baseline Summary

**Deterministic enterprise network estates, fail-closed detached compatibility evidence, and an empirically measured 1,500-node canvas ceiling now anchor Phase 12 scale work without changing production code.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-09-05T01:41:42Z
- **Completed:** 2026-09-05T01:54:25Z
- **Tasks:** 4
- **Files modified:** 8, including this summary

## Accomplishments

- Added real `NetworkSnapshot` builders for the exact 20/60/200-VNet estate sizes, configurable subscriptions, optional mixed-case ARM IDs, every required topology collection, and a frozen private-link-free G-4 fixture.
- Recorded concrete payload and latency baselines plus `G1_NODE_CAP = 200`, `G1_BYTE_CEILING = 250_000`, `G2_NODE_CAP = 1_500`, and `G2_BYTE_CEILING = 2_000_000`.
- Captured default topology, gaps, and rule-findings bodies at the detached phase base commit, with fail-closed SHA/provenance checks and exact pre-phase suite counts.
- Added reusable topology/gap/finding web envelopes, coverage/pagination builders, service mocks, and a compile/runtime guard for the seven-member status-tone palette.

## Measured Values

### Full-detail scale fixtures

| Estate | Nodes | Edges | Serialized bytes | Fixture construction | Topology build |
|---|---:|---:|---:|---:|---:|
| Small | 1,330 | 1,414 | 3,995,858 | 0.011008 s | 0.013983 s |
| Mid | 6,930 | 7,512 | 20,027,851 | 0.031651 s | 0.068966 s |
| Enterprise | 34,600 | 37,240 | 100,520,147 | 0.184934 s | 0.882940 s |

The enterprise fixture itself remains well below the 646 ms construction allowance, and the measured topology build remains below the G-3 one-second ceiling.

### Pre-phase compatibility artifact

- **Artifact:** `.planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json`
- **Phase base commit:** `d57f6137d747c344c56028d7e6211811927d0b43`
- **Recording mode:** detached git worktree at the exact phase base commit
- **Frozen topology:** 40 nodes, 48 edges, 0 private-link resources
- **Serialized endpoint bytes:** topology 112,127; gaps 7,415; rule findings 14,717
- **Pre-phase suite counts:** backend 123 passed; web 73 passed
- **Allowed additions at recording:** `allowed_additive_nodes = []`; `allowed_additive_keys = []`

### Empirical canvas ceiling

- **Measured ceiling:** 1,500 nodes
- **Threshold:** 250 ms for one headless fCoSE layout plus selection, neighborhood-highlight, clear, and deselection pass
- **Method:** Vitest with jsdom and the existing Cytoscape/fCoSE stack over nodes drawn from the 34,600-node enterprise fixture
- **Machine:** Mac, Darwin 25.6.0
- **Samples:** 100/164.679 ms, 250/195.533 ms, 500/138.569 ms, 750/177.704 ms, 1,000/186.956 ms, 1,250/232.995 ms, 1,500/224.298 ms
- The measured value is capped at the UI contract maximum, so plan 12-09 must consume **1,500**.

## Task Commits

1. **Task 1: Synthetic estate builders** — `72dc8236`
2. **Task 2: Backend scale module** — `b1003d5e`
3. **Task 3 RED: Pre-phase baseline contract** — `17e36d22`
4. **Task 3 GREEN: Detached baseline and canvas measurement** — `1906c29a`
5. **Task 4: Shared web fixtures and status palette** — `0466435c`
6. **Task 3 hardening: Detached provenance attestation** — `172f84c3`
7. **Task 1 hardening: Enterprise fixture latency correction** — `30adc9e7`

## Files Created/Modified

- `tests/network_scale_fixtures.py` — deterministic real-model estate builders and frozen G-4 fixture.
- `tests/test_network_scale.py` — payload baselines and G-1/G-2/G-3 gates.
- `tests/network_baseline.py` — detached recorder, response serializer, loader, and provenance validation.
- `tests/test_network_prephase_baseline.py` — replay, fail-closed, and canvas-measurement assertions.
- `.planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json` — canonical pre-phase evidence.
- `web/src/test/network-fixtures.ts` — shared network envelopes, coverage, pagination, and service mocks.
- `web/src/components/ui/StatusBadge.test.tsx` — exact seven-tone and keyword-map guard.

## Decisions Made

- Captured the baseline from a nested temporary detached worktree rooted inside the assigned executor worktree; the recorder now rejects an attached branch or a mismatched HEAD.
- Used compact deterministic JSON serialization for byte identity while retaining separately sorted key sets for actionable diagnostics.
- Kept the canvas guard at 1,500 because every measured sample through that contract maximum completed below the declared 250 ms threshold.
- Used real flat NIC resources for supporting enterprise volume after repeated builds showed oversized firewall-rule collections could breach G-3.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Bounded the canvas measurement input after a full 118 MB JSON import exhausted Node's heap**
- **Found during:** Task 3
- **Issue:** Importing the complete serialized enterprise topology into Vitest exhausted the default 4 GB Node heap before a measurement could run.
- **Fix:** Generated a deterministic 1,500-node slice from the real 34,600-node enterprise topology, retained the source estate's total node/edge counts, and measured every increasing sample through the contract maximum.
- **Files modified:** Baseline artifact only; the temporary benchmark/worktree was removed.
- **Verification:** Vitest measurement passed and recorded all seven samples.
- **Committed in:** `30adc9e7`

**2. [Rule 1 - Bug] Rebalanced supporting nodes to keep repeated enterprise builds under G-3**
- **Found during:** Overall verification
- **Issue:** Filling the target node count with thousands of deeply nested firewall rules produced repeated topology builds above one second.
- **Fix:** Retained two real firewall rules per collection and filled the remaining estate volume with real `NetworkInterface` models, preserving every required collection and the exact 34,600-node target.
- **Files modified:** `tests/network_scale_fixtures.py`, baseline artifact.
- **Verification:** Final enterprise fixture construction was 0.184934 s and topology build was 0.882940 s.
- **Committed in:** `30adc9e7`

**3. [Rule 2 - Missing Critical] Added machine-checkable detached-worktree provenance**
- **Found during:** Task 3 self-review
- **Issue:** The artifact carried the phase SHA but did not independently state or enforce detached recording mode.
- **Fix:** The recorder now rejects attached HEADs and SHA mismatches, and persists `git_mode`, `head_commit`, and platform.
- **Files modified:** `tests/network_baseline.py`, `tests/test_network_prephase_baseline.py`, baseline artifact.
- **Verification:** Four baseline tests pass, including exact provenance assertions.
- **Committed in:** `172f84c3`

**Total deviations:** 3 auto-fixed (1 blocking, 1 bug, 1 missing critical).
**Impact on plan:** All fixes were limited to test/measurement assets and strengthened the stated performance and provenance guarantees. No production source changed.

## Verification

- `.venv/bin/python -m pytest tests/test_network_scale.py tests/test_network_prephase_baseline.py -q` — **13 passed, 2 skipped**.
- `cd web && npx --no-install vitest run src/components/ui` — **6 files passed, 28 tests passed**.
- `cd web && npx --no-install tsc --noEmit` — **passed**.
- Baseline artifact non-empty check — **passed**.
- Fail-closed own-commit no-production-code gate — **passed**, 7 plan commits inspected and 0 production files found.
- Required commit trailer check — **passed** for all 7 task/fix commits.

## Known Stubs

- `tests/test_network_scale.py:127` — intentional skipped G-1 summary payload gate; plan 12-07 adds `detail=summary`.
- `tests/test_network_scale.py:134` — intentional skipped G-2 enterprise truncation gate; plan 12-07 adds summary truncation.

Both skips are explicit future gates required by this plan and do not prevent the measurement/scaffolding objective. Automatic `WINDOWS.md` registration was attempted but the existing ledger contains unsupported legacy kind `live-source-data`, so the SDK rejected the append without modifying the ledger.

## Issues Encountered

- The isolated worktree initially had neither `.venv` nor `web/node_modules`. A worktree-local system-site-packages virtual environment and the existing lockfile were used; no dependency manifests changed and no new package was added.
- `npm ci` reported vulnerabilities in the pre-existing locked dependency graph. They are outside this no-production-code plan and were not auto-modified.

## No-Production-Code Attestation

The gate loaded the full 40-character `phase_base_commit` from the artifact, verified it resolves, required a non-empty `(12-02)` commit set, and inspected only those commits from base to HEAD. It found **0** files under production `src/` or the production web app/component/library/hook paths after excluding test assets.

## User Setup Required

None.

## Next Phase Readiness

- Plan 12-07 can activate G-1 and G-2 using the four named constants.
- Plan 12-09 can consume the measured 1,500-node interactive ceiling.
- Plan 12-11 can compare default responses against the detached artifact and use its phase-base SHA for hygiene gates.

## Self-Check: PASSED

- All seven planned artifacts exist.
- All seven task/fix commits exist and carry the required co-author trailer.
- The detached baseline SHA resolves and equals its recorded detached HEAD.
- Required backend, web, type, artifact, latency, and no-production-code checks pass.

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-05*
