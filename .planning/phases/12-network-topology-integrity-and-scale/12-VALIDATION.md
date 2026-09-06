---
phase: 12
slug: network-topology-integrity-and-scale
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-03
executed: 2026-09-06
verified_source_head: 811883f3
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + Vitest/jsdom |
| **Config files** | `pyproject.toml`, `web/vitest.config.ts`, `web/src/test/setup.ts` |
| **Backend quick run** | `.venv/bin/python -m pytest tests/test_network_analysis.py -q` |
| **Web quick run** | `cd web && npx vitest run src/lib/network-graph.test.ts` |
| **Full suite** | `.venv/bin/python -m pytest -q && (cd web && npx vitest run)` |
| **Estimated runtime** | Targeted: <30 seconds; full: <180 seconds |

## Sampling Rate

- **After every task commit:** Run the task's targeted `<automated>` command.
- **After Wave 1:** Run only the affected backend and web modules to avoid concurrent baseline-capture races.
- **After Waves 2–9:** Run `.venv/bin/python -m pytest -q` and `cd web && npx vitest run`.
- **Before `/gsd-verify-work`:** Both full suites and gates G-1 through G-6 must be green.
- **Max feedback latency:** 180 seconds.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | TOPO-01 | T-12-01, T-12-02, T-12-05 | No cross-scope gaps/resources | regression | `pytest test_network_analysis.py -k ScopeIsolation` | ✅ extended | ✅ green |
| 12-01-02 | 01 | 1 | TOPO-01 | T-12-03, T-12-04 | Preview and topology use one scope seam | integration | `pytest test_api_network.py test_network_analysis.py` | ✅ extended | ✅ green |
| 12-01-03 | 01 | 1 | TOPO-01 | T-12-06 | Agent/MCP/twin preserve scope | integration | `pytest test_network_downstream_scope.py ...` | ✅ created | ✅ green |
| 12-02-01 | 02 | 1 | TOPO-03 | T-12-07, T-12-09 | Deterministic bounded fixtures | unit | `python -c "...small_estate..."` | ✅ created | ✅ green |
| 12-02-02 | 02 | 1 | TOPO-03 | T-12-08 | Scale budgets are measured | performance | `pytest tests/test_network_scale.py` | ✅ created | ✅ green |
| 12-02-03 | 02 | 1 | TOPO-03 | T-12-10, T-12-11, T-12-12 | Baseline and browser ceiling fail closed | contract/performance | `pytest test_network_prephase_baseline.py` | ✅ created | ✅ green |
| 12-02-04 | 02 | 1 | TOPO-05 | — | Web fixtures preserve status vocabulary | unit | `vitest StatusBadge.test.tsx` | ✅ extended | ✅ green |
| 12-03-01 | 03 | 2 | TOPO-01, TOPO-05 | T-12-64, T-12-15 | ARM IDs are case-stable; drops counted | regression | `pytest test_network_topology_links_regression.py test_network_topology.py` | ✅ extended | ✅ green |
| 12-03-02 | 03 | 2 | TOPO-05 | T-12-66, T-12-13, T-12-14 | Freshness/DNS/flow provenance are truthful | integration | `pytest test_network_topology_links_regression.py test_network_ontology.py test_network_flow.py test_api_network.py` | ✅ extended | ✅ green |
| 12-03-03 | 03 | 2 | TOPO-01, TOPO-05 | T-12-65 | Missing-peer reason is server-derived | unit | `pytest test_network_topology.py -k peer` | ✅ extended | ✅ green |
| 12-04-01 | 04 | 3 | TOPO-04 | T-12-16, T-12-18, T-12-19 | Policy write invalidates analysis | integration | `pytest test_api_network.py -k Policy` | ✅ extended | ✅ green |
| 12-04-02 | 04 | 3 | TOPO-04 | T-12-17, T-12-20 | Rule contract is additive and validated | integration | `pytest test_api_network.py -k "Policy or declarative"` | ✅ extended | ✅ green |
| 12-04-03 | 04 | 3 | TOPO-04 | T-12-18 | Shared refetch is bounded | web unit | `vitest run` | ✅ extended | ✅ green |
| 12-05-01 | 05 | 3 | TOPO-02 | T-12-21, T-12-22, T-12-23 | Fabric gap semantics are verified | manual checkpoint | See manual table | N/A | ✅ verified |
| 12-05-02 | 05 | 3 | TOPO-02 | T-12-21, T-12-22 | Disposition is durable and explicit | artifact | `test -s 12-FABRIC-PRIVATE-LINK-DECISION.md` | ✅ created | ✅ green |
| 12-06-01 | 06 | 4 | TOPO-02 | T-12-24, T-12-26, T-12-27, T-12-28 | Private-link nodes are scoped/deduped | unit | `pytest test_network_topology.py test_network_analysis.py test_network_downstream_scope.py` | ✅ extended | ✅ green |
| 12-06-02 | 06 | 4 | TOPO-02 | T-12-25, T-12-SC | Icons are official and unmodified | asset check | `ls web/public/azure-icons` | ✅ extended | ✅ green |
| 12-06-03 | 06 | 4 | TOPO-02 | T-12-25 | Client recognizes mapped types | web unit | `vitest network-graph.test.ts` | ✅ extended | ✅ green |
| 12-07-01 | 07 | 5 | TOPO-03 | T-12-29, T-12-30, T-12-33 | LOD is lean, bounded, and additive | performance/contract | `pytest test_network_scale.py test_api_network.py test_network_topology.py` | ✅ created/extended | ✅ green |
| 12-07-02 | 07 | 5 | TOPO-03 | T-12-31, T-12-32 | Pagination/truncation are explicit | integration | `pytest test_api_network.py -k "gap or finding or coverage or truncat"` | ✅ extended | ✅ green |
| 12-07-03 | 07 | 5 | TOPO-03 | T-12-31, T-12-34 | Affected resources and agent bounds disclosed | integration | `pytest test_network_topology.py test_api_network.py test_operations_tools.py test_network_downstream_scope.py` | ✅ created/extended | ✅ green |
| 12-08-01 | 08 | 6 | TOPO-03 | T-12-35, T-12-36 | UI totals/recovery reflect coverage | web integration | `vitest page.test.tsx` | ✅ created | ✅ green |
| 12-08-02 | 08 | 6 | TOPO-04 | T-12-37, T-12-38 | Declarative policy round-trips visibly | web integration | `vitest page.test.tsx` | ✅ created | ✅ green |
| 12-08-03 | 08 | 6 | TOPO-05 | T-12-39, T-12-40 | Freshness/provenance and keyboard path are honest | web integration | `vitest run` plus `format.ts` guard | ✅ extended/created | ✅ green |
| 12-09-01 | 09 | 7 | TOPO-03 | T-12-43 | UI guard uses measured ceiling | web unit/performance | `vitest TopologyWorkspace.test.tsx` | ✅ created | ✅ green |
| 12-09-02 | 09 | 7 | TOPO-01, TOPO-03 | T-12-41, T-12-42 | Badges fan out with coverage disclosure | web unit | `vitest TopologyWorkspace.test.tsx` | ✅ created | ✅ green |
| 12-09-03 | 09 | 7 | TOPO-02, TOPO-05 | T-12-44, T-12-45, T-12-46, T-12-47 | Badge toggle, fold index, footnote stay truthful | web unit | `vitest components/network network-graph.test.ts` | ✅ extended | ✅ green |
| 12-10-01 | 10 | 8 | TOPO-03 | T-12-48, T-12-49, T-12-50 | Drawer never labels incomplete data clean | web unit | `vitest TopologyDetailDrawer.test.tsx` | ✅ created | ✅ green |
| 12-10-02 | 10 | 8 | TOPO-02, TOPO-03 | T-12-49, T-12-51 | Drill-down states and facts are explicit | web unit | `vitest TopologyDetailDrawer.test.tsx` | ✅ created | ✅ green |
| 12-10-03 | 10 | 8 | TOPO-05 | T-12-52, T-12-53, T-12-54 | Export provenance and selection are consistent | web unit | `vitest components/network` | ✅ extended | ✅ green |
| 12-11-01 | 11 | 9 | TOPO-01..05 | T-12-55, T-12-60 | Default downstream contract stays compatible | contract | `pytest test_network_downstream_contracts.py` | ✅ created | ✅ green |
| 12-11-02 | 11 | 9 | TOPO-01..05 | T-12-56, T-12-57, T-12-61 | G-1..G-6 use correct fixtures and bounds | performance/contract | `pytest test_network_scale.py test_operations_tools.py test_network_downstream_contracts.py test_network_downstream_scope.py` | ✅ created/extended | ✅ green |
| 12-11-03 | 11 | 9 | TOPO-01..05 | T-12-58, T-12-59, T-12-62, T-12-63 | Full suites and phase-diff hygiene fail closed | full suite | `pytest tests -q && vitest run && pytest ...hygiene...` | ✅ created/extended | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

## Wave 0 Requirements

- [x] `tests/test_network_downstream_scope.py` — scope seam across agents/MCP/twin (TOPO-01).
- [x] `tests/network_scale_fixtures.py` — deterministic small/mid/enterprise/G-4 estates (TOPO-03).
- [x] `tests/test_network_scale.py` — G-1, G-2, G-3 performance and coverage gates (TOPO-03).
- [x] `tests/test_network_prephase_baseline.py` and `12-PRE-PHASE-BASELINE.json` — frozen pre-phase contracts (TOPO-03).
- [x] `tests/network_baseline.py` — fail-closed baseline loader shared by compatibility and hygiene gates (TOPO-03).
- [x] `tests/test_operations_tools.py` — agent-bound disclosure (TOPO-03).
- [x] `tests/test_network_downstream_contracts.py` — compatibility and phase-diff hygiene (TOPO-01..05).
- [x] `web/src/test/network-fixtures.ts` — shared topology response fixtures.
- [x] `web/src/app/network/page.test.tsx` — totals, policy round-trip, provenance, keyboard path (TOPO-03..05).
- [x] `web/src/components/network/TopologyWorkspace.test.tsx` — LOD, badge coverage, guard behavior (TOPO-01..03, TOPO-05).
- [x] `web/src/components/network/TopologyDetailDrawer.test.tsx` — five findings states, drill-down, export/selection behavior (TOPO-02, TOPO-03, TOPO-05).

No framework installation is required.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Confirm whether `Microsoft.Fabric/capacities` supports per-resource private endpoints and whether `microsoft.cognitiveservices/accounts` mapping matches deployed Foundry semantics | TOPO-02 | In-repo evidence is insufficient; wrong assumption creates prominent false positives | Execute Plan 12-05 using current Microsoft documentation and deployed Azure resource evidence; record the disposition and citations in `12-FABRIC-PRIVATE-LINK-DECISION.md` before Plan 12-06 |
| 360px viewport has no horizontal page scroll across topology, findings, policy, and drawer states (UI-SPEC A39) | TOPO-03 | jsdom has no real layout boxes | At phase close, exercise the enterprise fixture at 360px and record passed, failed, or not exercised in the closure record; do not substitute the jsdom backstop |

## Validation Sign-Off

- [x] All tasks have `<automated>` verification or an explicit manual checkpoint.
- [x] Sampling continuity: no three consecutive tasks lack automated verification.
- [x] Wave 0 covers every currently missing test/fixture reference.
- [x] No watch-mode flags.
- [x] Planned feedback latency is under 180 seconds for targeted checks.
- [x] Wave 0 artifacts created and green.
- [x] Full backend and web suites green.
- [x] G-1 through G-6 green against their specified fixtures.
- [x] `nyquist_compliant: true` set after implementation validation.

## Execution Evidence

- All eleven `12-01` through `12-11` summary artifacts report `status: complete`.
- Latest full backend gate (after review remediation): **2,736 passed, 33 skipped** (**2,769 collected**).
- Latest full web gate (after review remediation): **43 files passed; 347 tests passed; 15 pre-existing todo**.
- Python Ruff, TypeScript (`tsc --noEmit`), and Next.js ESLint gates are clean.
- The Phase 12 G-1 through G-6/downstream closure suites passed in the Plan 12-11 closeout and again during review remediation.
- The Fabric private-link checkpoint is recorded as complete in `12-FABRIC-PRIVATE-LINK-DECISION.md`.
- The held-out 360px Chromium check passed; evidence is `12-11-A39-360px.png`.

**Approval:** complete — implementation, automated gates, and both manual checkpoints have execution evidence.
