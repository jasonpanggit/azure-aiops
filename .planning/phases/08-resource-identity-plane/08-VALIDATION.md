---
phase: 08
slug: resource-identity-plane
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-27
---

# Phase 08 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest `[VERIFIED: pyproject.toml]` — `[tool.pytest.ini_options] testpaths = ["tests"] addopts = "-q"` |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]` section) |
| **Quick run command** | `pytest tests/test_inventory_read_port.py tests/test_impact_analysis.py tests/inventory_harness.py -x -q` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~30-90 seconds (full suite; quick run <10s) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_inventory_read_port.py tests/test_impact_analysis.py tests/inventory_harness.py -x -q`
- **After every plan wave:** Run `pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | INV-11 | T-08-01 | `list_containment`/`get_resource` require server-derived scope | unit/tdd | `pytest tests/test_inventory_read_port.py -x -q` | ✅ existing file extended | ⬜ pending |
| 08-01-02 | 01 | 1 | INV-11 | T-08-02 | Adapter passes provider_payload through lossless, no corruption | characterization/tdd | `pytest tests/test_network_normalize_from_inventory.py tests/test_impact_analysis.py -x -q` | ❌ W0 | ⬜ pending |
| 08-01-03 | 01 | 1 | INV-07, INV-10 | T-08-03 | identity_source flag defaults off; no behavior change until flipped | characterization | `pytest tests/inventory_harness.py -x -q` | ✅ existing harness extended | ⬜ pending |
| 08-02-decision | 02 | 2 | INV-10 | — | N/A (architecture decision checkpoint) | manual | N/A | N/A | ⬜ pending |
| 08-02-01 | 02 | 2 | INV-10, INV-11 | T-08-04, T-08-06 | Edge IDs/confidence/source fields match Hermes exactly | integration/tracer | `pytest tests/test_topology_pipeline.py -x -q` | ❌ W0 | ⬜ pending |
| 08-02-flowlog-checkpoint | 02 | 2 | — | — | N/A (human-verify: flow-log provisioning) | manual | N/A | N/A | ⬜ pending |
| 08-02-02 | 02 | 2 | INV-10, INV-11 | T-08-04, T-08-05, T-08-06 | Full predicate vocabulary + flow-log join; ontology binding after derivation only | integration | `pytest tests/test_topology_pipeline.py -x -q` | ❌ W0 | ⬜ pending |
| 08-03-01 | 03 | 3 | INV-10, INV-11, INV-12 | T-08-07 | D-05 unknown/stale/conflicting/unauthorized edges explicit in both arms | integration/comparison/tdd | `pytest tests/test_hermes_fabric_comparison.py -x -q` | ❌ W0 | ⬜ pending |
| 08-03-02 | 03 | 3 | — | T-08-07 | Report generated from actual test run, not hand-authored | doc-generation | `test -f .planning/phases/08-resource-identity-plane/08-COMPARISON-REPORT.md && grep -q "correctness" ...` | ❌ W0 | ⬜ pending |
| 08-03-decision | 03 | 3 | — | T-08-08 | N/A (D-09 architecture gate — one-way) | manual | N/A | N/A | ⬜ pending |
| 08-03-03 | 03 | 3 | INV-07, INV-08, INV-10, INV-11, INV-12 | T-08-08 | Removal gated strictly behind equivalence proof + operator approval | regression | `pytest tests/inventory_harness.py tests/test_impact_analysis.py tests/test_network_normalize_from_inventory.py -x -q` | ✅ existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_network_normalize_from_inventory.py` — stubs for INV-11 losslessness proof (Pitfall 1), plan 08-01 Task 2
- [ ] `tests/topology_comparison_scenario.py` — shared fixture module feeding both Hermes and Fabric arms identically (Pitfall 3), plan 08-02 Task 1
- [ ] `tests/test_topology_pipeline.py` — stubs for the Fabric-native edge-derivation pipeline, plan 08-02 Tasks 1-2
- [ ] `tests/test_hermes_fabric_comparison.py` — stubs for the D-01–D-05 comparison harness, plan 08-03 Task 1
- [ ] Extend existing `tests/test_inventory_read_port.py` and `tests/inventory_harness.py` — no new framework install; pytest already configured

*Existing infrastructure (pytest, `tests/inventory_harness.py` seam, `tests/semantic_scenario.py` fixture pattern) covers the harness/fixture conventions this phase's new tests must follow.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Fabric IQ ontology item correctly binds `topology_entities`/`topology_edges` and exposes traversal | INV-10, D-04a | No automated Fabric-tenant assertion available this session; Fabric IQ binding must be confirmed live via Fabric REST API/portal per 08-02 checkpoint resolution | After 08-02 Task 2, query the Fabric REST API for the ontology item and confirm it references the two Delta tables; spot-check one traversal query against the bound ontology in the Fabric portal |
| NSG Flow Logs / Traffic Analytics provisioning decision (live vs. fixture-only) | D-11 | Billable Azure-side configuration action with retention/cost implications; requires operator judgment, not inferable from code | Operator responds to 08-02's `checkpoint:human-verify` task with "provision live" or "fixture only" |
| Hermes retain/reduce/remove architecture decision | D-09 | Explicit operator-approval gate per locked decision; not a code-verifiable behavior | Operator reviews `08-COMPARISON-REPORT.md` (08-03 Task 2) and responds to the 08-03 `checkpoint:decision` task |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
