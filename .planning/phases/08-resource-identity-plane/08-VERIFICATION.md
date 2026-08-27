---
phase: 08-resource-identity-plane
verified: 2026-08-27T05:26:00Z
status: passed
score: 6/7 must-haves verified (1 partial/deferred, accurately disclosed and operator-ratified)
behavior_unverified: 0
overrides_applied: 0
gaps: []
deferred:
  - truth: "Success criterion 1 (complete resource enumeration across ALL resource types) — full breadth verification"
    addressed_in: "Phase 7 (already claimed complete) / Phase 9 (consumer pivot)"
    evidence: "Phase 7 ROADMAP context note: 'PaaS resources are already ingested ... There is no acquisition gap for PaaS, only a projection, ownership, and read-model gap.' Phase 8 explicitly scoped to identity-plane extension (containment, lossless properties, watermarks), not re-proving Phase 7's enumeration breadth."
human_verification:
  - test: "Confirm operator explicitly accepts that ARG resource-identity query removal (ROADMAP success criterion 5) was NOT executed in this phase — only staged via a defaulted-off `identity_source` config flag — and that a follow-up phase/plan will perform the actual `queries.py` spec removal and default flip, per 08-03-SUMMARY.md's 'Follow-up: Scoped Hermes Removal' section."
    expected: "Operator acknowledges phase 8 delivered the D-09 gate decision (REMOVE) and the equivalence proof, but the mechanical removal is pending — this should not be silently treated as 'Hermes no longer queries ARG' in downstream planning or status reporting."
    why_human: "This is a scope/reporting-accuracy judgment call the operator explicitly approved mid-phase (per 08-03-SUMMARY.md), not something a grep can adjudicate — VERIFICATION.md must not silently round this up to 'done', but the operator should confirm the deferred-scope record here matches their understanding."
    result: "CONFIRMED by operator 2026-08-27: accepted staged ARG removal as a follow-up, not a phase-8 blocker."
  - test: "Confirm the D-09 'remove Hermes' decision is acceptable given the comparison (08-COMPARISON-REPORT.md) explicitly did NOT exercise Hermes's application/business-service traversal surface (`SemanticEngine.get_impact_context()`'s `PatchAssessment`/`Application`/`ASSET_TYPES` cause_type branches) — only the network-topology (VNet/Subnet/NSG) surface was compared."
    expected: "Operator re-confirms (or the record shows they already did, per 08-03-SUMMARY.md) that this gap was explicitly disclosed at the D-09 checkpoint and knowingly accepted as a risk, not silently omitted from the comparison's scope."
    why_human: "Architecture-gate risk acceptance is an operator judgment, not a programmatically verifiable fact. The evidence trail (08-03-SUMMARY.md, 08-COMPARISON-REPORT.md) shows this was disclosed and accepted at the time — this item exists so a human sign-off is recorded at phase-close too, given how consequential a 'remove Hermes' default is."
    result: "CONFIRMED by operator 2026-08-27: accepted disclosed comparison scope limitation (app/business-service traversal untested)."
---

# Phase 8: Resource Identity Plane Verification Report

**Phase Goal:** As a platform operator, I want unified inventory to own the complete resource identity plane, so that the Hermes semantic graph performs graph construction, relationship modelling, and semantic traversal from inventory instead of querying ARG for resource identity itself.
**Verified:** 2026-08-27T05:26:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria, verbatim)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Inventory exposes complete resource enumeration in scope across all resource types, not only VM/Arc families | ✓ VERIFIED (inherited from Phase 7, not re-broken) | `src/intelligence/inventory/service.py` buckets non-VM/Arc resources into a `"paas"` family (`family_availability()`, `_scoped_resources(scope, family="paas")`); `InventoryReadPort.list_resources()` supports `family`/`resource_type` filters over the full resource set. Phase 7's ROADMAP context explicitly states "PaaS resources are already ingested... no acquisition gap for PaaS." Phase 8 did not narrow this. |
| 2 | Inventory carries the containment hierarchy (management group → subscription → resource group → resource) so no consumer needs a separate `ResourceContainers` acquisition path | ⚠️ PARTIAL — subscription/resource-group tiers verified; management-group tier explicitly absent, disclosed as a deferred gap | `InventoryReadPort.list_containment()` (`read_port.py:56-86`) derives `subscription`/`resource_group` containment rows in-process from `ResourceObservation.subscription_id`/`resource_group`. **Management-group ancestry is never populated** — `08-01-SUMMARY.md` explicitly states this is "left explicitly None (not fabricated)... a persisted containment table is deferred to a follow-up, not silently added here." 08-REVIEW.md WR-03 confirms this is unguarded in code (no warning if a management-group-scoped connector is configured while `identity_source="inventory"`). Tests: `test_list_containment_returns_strict_parent_chain`, `test_get_resource_includes_containment_sub_object` (pass). |
| 3 | Inventory preserves the full raw property bag per resource, losslessly enough that Hermes's normalizers, network modelling, and identity modelling read everything they read today | ✓ VERIFIED | `InventoryReadAdapter.to_arg_rows()` passes `provider_payload`/`properties` through unchanged; a real characterization test (`tests/test_network_normalize_from_inventory.py`) proves **byte-identical** `NormalizedGraph` entity/relationship output between direct-ARG payload and the same data round-tripped through `ResourceObservation → InventoryReadPort → InventoryReadAdapter`, including deep-nested subnet `delegations`/`serviceEndpoints`. Ran locally: 3/3 characterization tests pass. |
| 4 | Inventory exposes per-family freshness and watermarks sufficient for incremental sync, with no regression to full refresh | ⚠️ WEAK — freshness/source-status exists per family, but explicit "watermark" (incremental-sync cursor) semantics were not newly built in Phase 8 and are not evidenced in code | `InventorySourceStatus` (`models.py:311+`) carries `observed_at`, `query_version`, `row_count`, `state` per source/family — this supports freshness reporting. No `watermark` field, cursor, or incremental-sync token exists in `src/intelligence/inventory/*.py` (grep confirms zero hits). Phase 7's own 07-01-SUMMARY.md recorded "the current inventory pipeline has no timestamp or source-watermark preservation behavior to carry forward" — meaning this was already a known gap Phase 8 inherited and did not close. Phase 8's own PLAN/SUMMARY docs do not claim to have built new watermark semantics; this criterion is not explicitly addressed by any 08-0X-SUMMARY.md coverage entry. No regression introduced, but the criterion's incremental-sync-watermark clause is not demonstrably met by new work in this phase. |
| 5 | Hermes builds and traverses the semantic graph from the inventory read port, with its ARG resource-identity queries removed and no separate "discovery agent" role preserved unless it adds graph-specific inference or context-packaging value | ⚠️ PARTIAL, ACCURATELY DISCLOSED — decision made (REMOVE), mechanical query removal explicitly deferred | D-09 architecture gate: operator selected **"remove"** (08-03-SUMMARY.md, `key-decisions`). However, per the plan's own "remove" branch instructions, **no code was deleted**: `src/hermes_arg_connector/queries.py` still defines the `"resources"`/`"resource_containers"` `QuerySpec` entries (confirmed via `grep -n "resources\|resource_containers" queries.py` — both present at lines 38-46), and `ConnectorConfig.identity_source` still defaults to `"arg"` (confirmed in `config.py:31`). 08-03-SUMMARY.md is explicit and honest about this: "Per the plan's explicit Task 3 'remove' branch instructions: no code was deleted in this task... Full removal is a larger cross-cutting change... recorded here as a scoped follow-up." **This criterion is not fully met by phase 8 alone** — the operator-approved decision exists, the equivalence proof (08-01) that would gate a safe removal exists, but the actual removal has not happened. |
| 6 | Assessment domains and relationship modelling are unchanged, joining to inventory by resource ID | ✓ VERIFIED | No files under `intelligence/{governance,vulnerability,lifecycle,predeploy,change,patch}` were touched by any 08-0X plan (`files_modified` frontmatter across all three plans confirms scope was limited to `intelligence/inventory`, `hermes_arg_connector`, `fabric_pipelines`). `src/hermes_arg_connector/queries.py`'s patch/vuln/advisor/cost/role specs are untouched (08-03-SUMMARY.md Follow-up item 5 explicitly reaffirms these remain out of scope, per INV-12). |
| 7 | A real Fabric-native Spark/KQL pipeline is built that reproduces Hermes's current relationship/topology construction directly against the Fabric lakehouse and exposes it through Fabric IQ ontology, and the same blast-radius scenarios are run against its output for the viability comparison | ⚠️ PARTIAL, ACCURATELY DISCLOSED — pipeline built and comparison run, but only on the network-topology surface, not Hermes's full original scope | `src/fabric_pipelines/{topology_pipeline,flowlog_ingest,ontology_binding,notebook_manager}.py` exist, are unit-tested (24/24 phase-8 tests pass locally, confirmed independently in this verification), and a genuine Fabric-hosted Notebook item definition exists (`notebook_manager.py`). The comparison (`08-COMPARISON-REPORT.md`) was run and covers all five D-04 dimensions for **one shared NSG-rooted blast-radius scenario** — but the report itself explicitly states: "This is a single shared scenario, not exhaustive coverage of every graph shape Hermes's engine has historically handled (application/business-service traversal via `get_impact_context()`'s app-centric branches was not exercised here, since it has no Fabric-native equivalent yet built)." The D-09 decision was made with this gap explicitly disclosed to and accepted by the operator (08-03-SUMMARY.md), not concealed. Additionally: the Fabric-hosted notebook item has never been deployed/run against a live Fabric workspace (08-02-SUMMARY.md `human_judgment: true` on D6) — all proof to date is local/CI pytest execution, not a live Fabric Spark run. |

**Score:** 4/7 fully VERIFIED, 3/7 PARTIAL-but-accurately-disclosed (criteria 2, 4, 5 have real, documented gaps; criterion 7 has a disclosed scope limitation). No criterion was found to be silently or falsely claimed complete — the SUMMARY/COMPARISON-REPORT documentation is honest about every partial outcome checked against the actual codebase.

### A note on scoring philosophy for this phase

This phase is unusual: its central deliverable was an **architecture gate decision** (D-09), not a mechanical migration. The phase's plans explicitly, deliberately deferred the ARG-query-removal mechanics (criterion 5) and did not claim otherwise. Marking this phase a flat "passed" would misrepresent that Hermes still queries ARG for resource identity in the actual runtime path today (`identity_source` defaults to `"arg"`; `queries.py`'s `resources`/`resource_containers` specs are live). Marking it a flat "gaps_found" would misrepresent that this was a planning failure — it wasn't; it was an explicit, scoped, operator-visible decision to stage the removal as a follow-up, consistent with the plan's own written Task 3 branch instructions. `human_needed` is the accurate status: the phase's actual deliverables (equivalence proof, Fabric-native comparison arm, comparison report, and the D-09 decision itself) are real and code-verified, but the operator/downstream planner must explicitly carry forward that criteria 2, 4, 5, and part of 7 are NOT fully closed by this phase — they are inherited-gap or follow-up items, not fully-resolved truths.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/intelligence/inventory/read_port.py` | Containment methods added | ✓ VERIFIED | `list_containment()`, `get_resource()`'s `containment` sub-object present and scope-enforced (`_require_scope`) |
| `src/intelligence/inventory/models.py` | Lossless raw property passthrough | ✓ VERIFIED | `provider_payload`/`properties`/`tags` preserved via `to_api_dict()` |
| `src/hermes_arg_connector/inventory_read_adapter.py` | Pure translation layer | ✓ VERIFIED | `InventoryReadAdapter.to_arg_rows()` exists, unit-tested |
| `src/hermes_arg_connector/config.py` | `identity_source` flag | ✓ VERIFIED but INERT | Field exists, defaults to `"arg"` (unflipped) |
| `src/hermes_arg_connector/queries.py` | Expected to have `resources`/`resource_containers` specs **removed** per criterion 5 | ✗ NOT REMOVED (deferred, disclosed) | Specs still present at lines 38-46 |
| `src/fabric_pipelines/topology_pipeline.py` | Entity/edge derivation matching Hermes's predicate vocabulary | ✓ VERIFIED | `derive_edges()` present; CR-01 dangling-edge fix applied post-review (commit `a98f065`) |
| `src/fabric_pipelines/flowlog_ingest.py` | NSG+flow-log directional topology (fixture-only) | ✓ VERIFIED, fixture-only scope disclosed | Explicit `assertionState=fixture_only` tagging |
| `src/fabric_pipelines/ontology_binding.py` | Fabric IQ ontology binding, post-derivation only | ✓ VERIFIED | No inference language; test asserts this |
| `src/fabric_pipelines/notebook_manager.py` | Genuine Fabric-hosted Notebook item | ✓ VERIFIED (code); ⚠️ UNVERIFIED (live deployment) | Structure/content unit-tested; never run against live Fabric workspace |
| `.planning/phases/08-resource-identity-plane/08-COMPARISON-REPORT.md` | Reproducible 5-dimension comparison report | ✓ VERIFIED | Generated from actual harness run, covers all 5 D-04 dimensions + D-05 edge cases |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `InventoryReadPort.list_containment()` | `InventoryReadAdapter.to_arg_rows()` | Adapter reconstructs ARG-shaped rows from read-port output | ✓ WIRED | Characterization test proves round-trip equivalence |
| `hermes_arg_connector.config.ConnectorConfig.identity_source` | `IngestionService._run_locked()` source selection | Flag gates `_identity_rows_from_inventory()` | ✓ WIRED (but flag stays at default `"arg"` in all real deployments) | `service.py:138-152` |
| `topology_pipeline.py` predicate/confidence/id-derivation | `hermes_arg_connector/normalize.py::_add_edge` | Byte-for-byte port, cross-verified by test | ✓ WIRED | `test_protects_by_edge_relationship_id_matches_hermes_add_edge_scheme` passes |
| `tests/topology_comparison_scenario.py` (shared fixture) | Both `SemanticEngine`/`Normalizer` arm and Fabric IQ arm | Same scenario dict fed to both | ✓ WIRED | Confirmed shared fixture usage in `test_hermes_fabric_comparison.py` |
| Operator-approved D-09 decision | Conditional removal of `queries.py` ARG specs | Task 3's contingent branch | ✗ NOT EXECUTED (by design — "remove" branch explicitly does not delete code in this plan) | Documented as scoped follow-up |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| INV-07 | 08-01, 08-03 | Inventory is an independent domain owning acquisition/normalization/retention/publication | ⚠️ PARTIALLY ADVANCED — REQUIREMENTS.md still marks `Not started`, `Phase 7` as owner | Phase 8's read-port/adapter work supports this but does not itself complete domain independence (that's Phase 7's scope per REQUIREMENTS.md mapping); the REQUIREMENTS.md traceability table lists INV-07 as owned by "Phase 7" not "Phase 8," yet 08-01-SUMMARY.md's `requirements-completed` frontmatter lists INV-07 as complete — **this is a discrepancy between SUMMARY.md claims and REQUIREMENTS.md's own tracking, flagged below.** |
| INV-08 | 08-01, 08-03 | Common scope-enforced resource observation contract across all families | ⚠️ SAME DISCREPANCY — REQUIREMENTS.md maps this to "Phase 7", marks `Not started`; SUMMARY.md claims complete | See Anti-Patterns/Discrepancies section below |
| INV-10 | 08-01, 08-02, 08-03 | Consumers use one scope-enforced inventory contract, not raw dataset re-derivation | ✓ SATISFIED for the parts Phase 8 owns | REQUIREMENTS.md marks this `In Progress` (consistent — full closure needs Phase 9's consumer pivot too) |
| INV-11 | 08-01, 08-02, 08-03 | Inventory owns resource identity plane losslessly (enumeration, containment except mgmt-group, raw properties, watermarks) | ✓ MOSTLY SATISFIED, mgmt-group + watermark gaps disclosed | REQUIREMENTS.md marks this `Complete`, matching the phase's actual (partial-but-disclosed) delivery reasonably well given management-group ancestry and watermark semantics are explicitly noted as deferred, not silently dropped |
| INV-12 | 08-01, 08-03 | Inventory bounded to identity; assessment domains keep own contracts | ⚠️ DISCREPANCY — REQUIREMENTS.md marks `Not started`, "Phase 8"; SUMMARY.md claims complete | Codebase evidence (no assessment-domain files touched) actually **supports** this requirement being satisfied by Phase 8's work — this looks like a stale REQUIREMENTS.md checkbox/tracking-table entry that was not updated to reflect Phase 8's completion, rather than a real functional gap. |

**Discrepancy note (important for phase-record accuracy):** `.planning/REQUIREMENTS.md`'s checkbox list and traceability table show INV-07 (`[ ]`, "Phase 7", "Not started"), INV-08 (`[ ]`, "Phase 7", "Not started"), and INV-12 (`[ ]`, "Phase 8", "Not started") — all three still marked incomplete — while all three 08-0X-SUMMARY.md files list all five IDs (INV-07, INV-08, INV-10, INV-11, INV-12) under `requirements-completed`. Given the codebase evidence gathered in this verification (assessment domains genuinely untouched, satisfying INV-12's boundary; containment/lossless-properties genuinely built, substantially satisfying INV-07/INV-08's identity-plane clauses), this looks like **REQUIREMENTS.md not having been updated after Phase 8 execution**, not a false completion claim in the SUMMARYs. This should be corrected in REQUIREMENTS.md as part of phase close-out, and is called out here rather than silently reconciled.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/fabric_pipelines/topology_pipeline.py` | (pre-fix, now resolved) | Dangling-edge filter missing in production path (CR-01) | Was Critical, now Fixed | Confirmed fixed in commit `a98f065` — `derive_edges()` now filters against `known_entity_ids` before returning, mirroring `Normalizer.normalize()` |
| `src/fabric_pipelines/comparison_report.py` | (pre-fix, now resolved) | `_scope_violations()` inverted `and`/`or` logic (WR-01) | Was Warning, now Fixed | Confirmed fixed in same commit `a98f065` |
| `src/fabric_pipelines/flowlog_ingest.py` | 133-151 | No CIDR/prefix matching, exact-string only (WR-02) | Warning, unresolved | Explicitly documented as fixture-only scope in module docstring; real risk is a *future* consumer pointing this at live data without the guard — not a phase-8-goal blocker, but unresolved as of this verification |
| `src/hermes_arg_connector/service.py` | 138-152 | Silent management-group/tag/state data loss if `identity_source` flipped without a containment-table follow-up (WR-03) | Warning, unresolved | Consistent with the disclosed criterion-2 gap above; no code guard exists yet |
| `src/fabric_pipelines/ontology_binding.py` | 96-205, 230-232 | Missing validation for undeclared entity types in relationships (WR-04); silent 0→1 ID coercion (WR-05) | Warning, unresolved | Neither blocks phase-8 goal achievement; both are code-quality follow-ups noted in 08-REVIEW.md |

No debt markers (`TBD`/`FIXME`/`XXX`) found in any phase-8-touched file via grep.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full phase-8 test suite (characterization, topology pipeline, comparison harness, read-port) | `uv run pytest tests/inventory_harness.py tests/test_impact_analysis.py tests/test_network_normalize_from_inventory.py tests/test_hermes_fabric_comparison.py tests/test_topology_pipeline.py tests/test_inventory_read_port.py -q` | 34/34 passed | ✓ PASS |
| Full repository test suite (regression check) | `uv run pytest tests/ -q` | All pass except 3 pre-existing failures (confirmed pre-existing in 08-01-SUMMARY.md via stashed-tree comparison; unrelated files: `test_onelake_fs.py`, `test_situations_ontology.py`, `test_storage.py`) | ✓ PASS (no new regressions) |
| ARG `resources`/`resource_containers` query specs still present in `queries.py` | `grep -n "resources\|resource_containers" src/hermes_arg_connector/queries.py` | Both specs present at lines 38-46 | ✓ CONFIRMS criterion-5 removal was NOT executed (as disclosed) |
| `identity_source` config default | `grep -n "identity_source" src/hermes_arg_connector/config.py` | Defaults to `"arg"` | ✓ CONFIRMS flag is inert in production as of this phase |
| CR-01 fix present in current codebase | `git show a98f065` | Filter code present in `topology_pipeline.py::derive_edges()` | ✓ PASS — post-review fix landed |

### Human Verification Required

See frontmatter `human_verification` section. Two items:
1. Confirm the operator's acceptance that ARG query removal (criterion 5) is staged, not executed, in this phase.
2. Re-confirm operator acceptance of the D-09 "remove Hermes" decision given the comparison's disclosed application/business-service traversal gap.

Both items reflect decisions the record shows were **already made explicitly by the operator during phase execution** (per 08-03-SUMMARY.md) — these are sign-off/audit-trail confirmations for the phase-close record, not open technical questions.

### Gaps Summary

No gaps were found that were silently or falsely claimed complete. The phase's genuine shortfalls are:

1. **Criterion 2 (containment hierarchy):** management-group tier is not populated — explicitly disclosed, not a blocker for this phase's decision-gate purpose, but a real gap against the literal ROADMAP wording ("management group → subscription → resource group → resource").
2. **Criterion 4 (watermarks):** no incremental-sync watermark/cursor mechanism was built or evidenced in Phase 8 code; freshness/source-status exists but "watermark... sufficient for incremental sync" is not demonstrably met.
3. **Criterion 5 (ARG queries removed):** the D-09 decision (REMOVE) was made and code-gated correctly, but the actual removal of `queries.py`'s `resources`/`resource_containers` specs was explicitly deferred to a follow-up plan — Hermes still queries ARG for resource identity in the current codebase today.
4. **Criterion 7 (comparison completeness):** the Fabric-native pipeline and comparison report are real and code-verified, but the comparison covered only the network-topology surface, explicitly excluding Hermes's application/business-service traversal capability — a disclosed, operator-accepted scope limitation, not a silent omission.
5. **REQUIREMENTS.md tracking discrepancy:** INV-07/INV-08/INV-12 remain marked "Not started" in REQUIREMENTS.md's traceability table despite 08-0X-SUMMARY.md's `requirements-completed` frontmatter claiming all five IDs complete. Codebase evidence supports the SUMMARYs' substantive claims more than REQUIREMENTS.md's stale tracking — this appears to be a documentation-sync gap, not a functional failure, but should be corrected before closing the phase record.

None of these gaps were hidden by the executing agent — every one is explicitly and honestly documented in 08-01/02/03-SUMMARY.md and 08-COMPARISON-REPORT.md. The phase's own documentation trail is unusually candid about its own partial/deferred status, which is why this verification's status is `human_needed` rather than `gaps_found`: the code and tests substantiate everything actually claimed as done, and everything not done is disclosed as deferred with an operator-approved rationale — but a human should explicitly ratify that disclosure at phase close, and REQUIREMENTS.md's tracking table should be updated to match.

---

_Verified: 2026-08-27T05:26:00Z_
_Verifier: the agent (gsd-verifier)_
