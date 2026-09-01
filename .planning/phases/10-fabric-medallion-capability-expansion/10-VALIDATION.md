---
phase: 10
slug: fabric-medallion-capability-expansion
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-01
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Backend framework** | pytest 9.1.1 (`pyproject.toml`'s `[tool.pytest.ini_options]`, `testpaths = ["tests"]`, `addopts = "-q"`) |
| **Frontend framework** | Vitest 2.1.9 (`web/package.json`) |
| **Config file** | `pyproject.toml` (backend); `web/vitest.config.*` (frontend) |
| **Quick run command (backend)** | `pytest tests/test_relationship_vocabulary_consistency.py tests/test_relationship_builder.py tests/test_confidence.py tests/test_pending_relationships.py tests/test_relationship_suggestion_promoter.py -q` |
| **Quick run command (frontend)** | `cd web && npx vitest run <changed test file>` |
| **Full suite command (backend)** | `pytest tests/ -q` |
| **Full suite command (frontend)** | `cd web && npm test` |
| **Estimated runtime** | Quick backend subset <1s; full backend suite ~60-90s; frontend suite per `npm test` |

---

## Sampling Rate

- **After every task commit:** Run the relevant quick-run subset for the touched requirement (e.g., `pytest tests/test_relationship_vocabulary_consistency.py tests/test_ontology_validator.py -q` for MED-01/06 changes).
- **After every plan wave:** Run `pytest tests/ -q` (full backend suite) — run it **twice** for any change touching the Defender/vulnerability router surface (known flaky test, see Wave 0 Gaps).
- **Before `/gsd-verify-work`:** Full suite must be green (accounting for pre-existing unrelated failures already tracked in STATE.md); live `scripts/validate-lakehouse-tables.py` run against the dev Fabric workspace before declaring MED-02 satisfied.
- **Max feedback latency:** ~90 seconds (full backend suite).

---

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MED-01 | Preflight rejects undefined endpoint types before any Fabric call | unit | `pytest tests/test_relationship_vocabulary_consistency.py -x` | ✅ passes 4/4 |
| MED-01 | Retry/durable terminal state on transient publish failure | unit + integration | `pytest tests/test_ontology_publish_durability.py -x` | ❌ Wave 0 — new |
| MED-02 | Gold outputs match code-declared schema registry | deployment/live | `python3 scripts/validate-lakehouse-tables.py --config fabric.config.yaml --json-out /tmp/gold-audit.json` | ✅ script exists; requires live authenticated Fabric workspace |
| MED-03 | Dataset status distinguishes healthy-empty/stale/degraded/failed/unavailable | unit | `pytest tests/test_medallion_health.py -x` | ❌ Wave 0 — new |
| MED-04 | Defender-domain endpoints return distinct alert/attack-path/secure-score semantics | contract | `pytest tests/test_api_vulnerability_router.py::test_defender_signal_endpoints_preserve_distinct_semantics -x` | ✅ exists; flaky in full-suite context |
| MED-04 | Change/configuration-drift ontology rows reach publication | unit | `pytest tests/test_change_pipeline_ontology_forwarding.py -x` | ❌ Wave 0 — new |
| MED-05 | Semantic model deployment succeeds or reports deployment-blocked | integration + live Fabric | `pytest tests/test_semantic_model_manager.py -x` | ❌ Wave 0 — new |
| MED-06 | Referential integrity blocks publish on dangling/self/duplicate relationships | unit | `pytest tests/test_ontology_validator.py -x` | ⚠ verify existence |
| MED-06 | Ownership/tag coverage warns or blocks by environment | unit | `pytest tests/test_data_quality.py -x` | ✅ exists (extended by Plan 10-02) |
| MED-07 | History-preserving write mode applied to designated tables | unit | `pytest tests/ -k "sync_service and history"` | ⚠ verify existence |
| MED-08 | Gold-grounding evaluation (23-case reference set) | offline-eval | `python3 scripts/evaluate_agents.py --baseline .planning/eval/gold-grounding-baseline.json --out .planning/eval/gold-grounding-latest.json` | ✅ harness exists; cases to be added |
| MED-09 | Publication manifest lifecycle states are queryable | unit + contract | `pytest tests/test_publication_manifest.py -x` | ❌ Wave 0 — new |
| MED-10 | Capacity state check returns Active/Paused correctly | unit (mocked) + manual-live | `pytest tests/test_capacity_health.py -x` | ❌ Wave 0 — new |
| MED-10 | OneLake data access role CRUD round-trips | integration + live Fabric | `pytest tests/test_data_access_roles.py -x` | ❌ Wave 0 — new |
| MED-10 | Delta table maintenance status observable | unit + live | `pytest tests/test_table_maintenance_status.py -x` | ❌ Wave 0 — new |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky — planner assigns per-task rows against this map.*

---

## Wave 0 Requirements

- [ ] Fix `tests/test_situations_tracer.py::test_normalizer_production_graph_contains_all_six_signal_families` — stale assertion; generalize expected `source_family` set (blocking, currently failing).
- [ ] Diagnose `tests/test_api_vulnerability_router.py::test_defender_signal_endpoints_preserve_distinct_semantics` full-suite flakiness (passes in isolation).
- [ ] `tests/test_ontology_publish_durability.py` — new, MED-01 durable-terminal-state.
- [ ] `tests/test_medallion_health.py` — new, MED-03 generalized dataset-status provider.
- [ ] `tests/test_change_pipeline_ontology_forwarding.py` — new, MED-04 `knowledge_projection()`-forwarding fix.
- [ ] `tests/test_semantic_model_manager.py` — new, MED-05.
- [ ] `tests/test_data_quality.py` — extended (not new), MED-06 ownership/tag rule (Plan 10-02).
- [ ] `tests/test_publication_manifest.py` — new, MED-09.
- [ ] `tests/test_capacity_health.py`, `tests/test_data_access_roles.py`, `tests/test_table_maintenance_status.py` — new, MED-10 (mockable against verified REST/ARM shapes; live-Fabric variants gated behind an env flag, mirroring `AIOPS_ENABLE_LIVE_GOLD_EVAL`).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Gold/Silver/Bronze table population against real Fabric workspace | MED-02, MED-03 | Requires authenticated live Fabric/OneLake access not available in CI | Run `scripts/validate-lakehouse-tables.py --config fabric.config.yaml` against the dev workspace after deployment; inspect JSON output for expected tables. |
| Direct Lake semantic model / deployment-blocked disposition | MED-05 | Requires live Fabric capacity and workspace-level deployment | Deploy via Fabric REST create-semantic-model call; confirm either success or an explicit, versioned `deployment-blocked` state is recorded — never silent success. |
| OneLake Data Access Role read/write round-trip | MED-10 | Requires live Fabric workspace and role-admin permissions | Exercise list/read via new API; confirm role mutation remains an operator/deploy-time action, not an end-user-callable endpoint. |
| Fabric Capacity Metrics / paused-capacity degraded reporting | MED-10 | Requires live capacity admin access | Pause/resume capacity in a non-prod workspace; confirm API reports `unavailable`/`degraded`, never `healthy-empty`. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
