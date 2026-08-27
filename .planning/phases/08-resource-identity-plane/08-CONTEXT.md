# Phase 8: Resource Identity Plane - Context

**Gathered:** 2026-08-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Move complete resource identity acquisition to the Fabric-backed inventory read port and determine whether Hermes provides enough unique graph value to remain. Hermes is not presumed to be an autonomous or self-learning discovery agent. The phase must either retain a narrowly scoped graph component with demonstrated operator value or remove Hermes as a runtime/domain and use Fabric IQ plus inventory/API directly.

</domain>

<decisions>
## Implementation Decisions

### Hermes viability gate
- **D-01:** Keeping Hermes requires demonstrated unique graph value in at least one end-to-end operator workflow, not merely a technically unique implementation.
- **D-02:** The minimum proof workflow is bounded blast-radius analysis from a changed or unhealthy resource.
- **D-03:** The proof must measure bounded relationship/topology inference, blast-radius traversal, provenance/confidence, and agent-safe context packaging against Fabric IQ plus the API.
- **D-04:** Use the same curated Fabric snapshot and representative operator scenarios for repeatable comparison, measuring correctness, evidence links, authorization, latency, and operational cost. An optional live smoke test may follow.
- **D-04a:** The comparison arm is not hypothetical — build a real Fabric-native pipeline (Spark/KQL notebook or DataPipeline) that reproduces Hermes's current relationship/topology construction (entity/edge derivation from ARG identity data, plus NSG+flow-log-derived network topology per D-11) directly against the Fabric lakehouse, and expose it through Fabric IQ ontology. Run the same blast-radius scenarios against this pipeline's output as against Hermes.
- **D-05:** Unknown, stale, conflicting, or unauthorized edges must remain explicit; unsupported certainty is a failed result.

### Hermes reduction or removal
- **D-06:** If Hermes passes only partially, retain only a small graph library/service for dependency inference and bounded traversal. Remove source acquisition, normalization ownership, inventory publication, and “discovery agent” branding.
- **D-07:** Preserve compatible semantic/query read contracts during migration while changing their backing source to Fabric/API; remove APIs that have no unique consumer after the comparison.
- **D-08:** Before deleting Hermes responsibilities, no direct ARG/LAW reads or duplicate inventory publication may remain. Contract tests and one end-to-end proof must pass first.
- **D-09:** The final retain/reduce/delete decision is an architecture gate requiring operator approval after the reproducible comparison report.
- **D-09a:** Operator direction is to treat Hermes removal as the default outcome: Fabric/Fabric IQ owns governed inventory, ontology, relationships, and traversal; Foundry owns grounded AI assessment. Hermes must demonstrate material unique value in the Phase 8 comparison to remain.

### Network topology derivation
- **D-10:** Fabric IQ's ontology generation promotes existing Power BI semantic model entities/relationships; it does not infer new entity types or relationships by analyzing raw data (e.g., NSG rules, flow logs). It hosts and traverses topology once defined, but does not derive it.
- **D-11:** Directional network topology (source/dest/port/protocol, allowed vs. observed) is computable today from NSG rule tables joined with flow log/Traffic Analytics data. This is bounded data-engineering logic, not AI/self-learning discovery, and is not exclusive to Hermes — it can run as a Fabric pipeline/notebook that writes a topology-edges table for Fabric IQ ontology to expose.
- **D-12:** The Hermes viability proof (D-01 through D-05) must treat "who derives network topology edges" as a separate, bounded engineering question from "does Hermes provide unique graph value." A Fabric-native topology pipeline is an explicit fallback/default if Hermes does not clear the viability gate.

### Agent's Discretion
- Exact comparison harness, scenario fixture shape, graph-library module boundaries, and migration sequencing are open to research and planning, provided they satisfy the locked viability and safety decisions above.

</decisions>

<canonical_refs>
## Canonical References

### Planning and requirements
- `.planning/ROADMAP.md` §Phase 8 — resource identity scope, success criteria, and Hermes viability boundary.
- `.planning/REQUIREMENTS.md` INV-07 through INV-12 — inventory ownership, lossless identity, and assessment-domain boundaries.
- `.planning/STATE.md` — paused Phase 7 Fabric pivot, blockers, and Hermes consumer decision.
- `.planning/phases/07-unified-resource-inventory/07-CONTEXT.md` — Fabric source-of-truth pivot, lossless `ResourceObservation`, and inventory/Hermes boundary.
- `.planning/phases/07-unified-resource-inventory/.continue-here.md` — blocking architecture pivot and required re-scoping before further execution.

### Existing Hermes and semantic implementation
- `src/hermes_arg_connector/queries.py` — deterministic query catalog and identity acquisition path.
- `src/hermes_arg_connector/normalize.py` — deterministic normalization into known entity and relationship rows.
- `src/hermes_arg_connector/ontology.py` — ontology metadata generated from emitted row shapes.
- `src/hermes_arg_connector/agent_queries.py` — current graph-backed query surface and direct dataset reads.
- `src/semantic/semantic_engine.py` — read-only semantic graph query/traversal engine.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/semantic/semantic_engine.py`: existing bounded read-only semantic engine, with traversal limits, validation, cache, freshness, and telemetry.
- `src/hermes_arg_connector/normalize.py`: existing deterministic normalizers that should be evaluated as graph construction logic, not treated as self-learning discovery.
- `src/hermes_arg_connector/agent_queries.py`: compatibility surface to migrate from direct datasets to inventory/API or remove if no unique consumer remains.

### Established Patterns
- Fabric/OneLake is the durable inventory source of truth; consumers use inventory-owned scope-enforced read ports.
- Raw provider properties must remain lossless in `ResourceObservation`; typed fields are projections.
- Assessment domains remain separate and join by resource ID; Hermes must not absorb patch, vulnerability, policy, advisor, metric, or health ownership.
- Evidence, provenance, freshness, uncertainty, and authorization are explicit and cannot be replaced by complete-looking inferred output.

### Integration Points
- Phase 8 must audit `queries.py`, `normalize.py`, `network_normalize.py`, identity specs, and `agent_queries.py` before changing the resource contract.
- Phase 9 depends on the resulting read-port and API compatibility decisions.

</code_context>

<specifics>
## Specific Ideas

The proof should be a reproducible comparison on a fixed curated Fabric snapshot, centered on explainable blast-radius analysis. Generic resource search and OS/software reporting do not establish unique Hermes value because Fabric/API can plausibly provide those directly.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within Phase 8 scope.

</deferred>

---

*Phase: 08-Resource-Identity-Plane*
*Context gathered: 2026-08-27*
