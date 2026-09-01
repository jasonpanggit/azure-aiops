# Phase 10: Fabric Medallion Capability Expansion - Context

**Gathered:** 2026-09-01
**Status:** Ready for planning
**Mode:** Autonomous recommended defaults

<domain>
## Phase Boundary

Deliver all ten recommendations from the 2026-09-01 live Fabric medallion assessment as one end-to-end platform phase. The phase covers Fabric ingestion and publication, Bronze/Silver/Gold contracts, semantic consumption, Data Agent grounding, governance and operations, and the API/web surfaces required to make health and capability visible to operators. It does not replace unified inventory as the resource-identity authority or expand into autonomous remediation.

</domain>

<decisions>
## Implementation Decisions

### Publication integrity and rollout
- Preserve and complete the existing uncommitted ontology-sync, Defender, compliance, confidence, pending-relationship, API, and web work on `fix-ontology-sync-publish`; do not reimplement or overwrite it.
- Make vocabulary and endpoint-type validation a runtime preflight before any externally visible ontology publication boundary, backed by the existing consistency tests.
- Use bounded exponential retry only for transient Fabric failures; validation and contract failures fail immediately with durable, operator-visible diagnostics.
- Sequence live rollout as integrity gates first, then metadata/status and manifests, then individual Silver/Gold pipelines with rollback, and finally semantic consumers and Data Agent grounding.

### Dataset restoration and lifecycle
- Give every code-declared or previously expected dataset an explicit disposition: populated and verified, intentionally empty with healthy source status, or retired with versioned compatibility evidence.
- Restore topology, operational-context, and assessment Gold outputs individually; do not enable all pipelines in one uncontrolled capacity spike.
- Empty ontology projections remain physically available when required by Fabric bindings, but are marked dormant in the manifest. Automatic destructive deletion is out of scope.
- Unified inventory remains the sole resource-identity authority; Gold products and semantic models consume its contracts rather than creating a parallel identity source.

### Freshness, quality, and history
- Freshness objectives are configurable per dataset and default to a bounded multiple of the producing pipeline cadence rather than one global hard-coded threshold.
- API status distinguishes healthy-empty, stale, degraded, failed, retired, and unavailable; zero rows alone never imply success or failure.
- Enforce referential integrity as a publication blocker. Ownership and tag coverage are configurable quality thresholds that can warn or block by environment.
- Retain append-only or merge-based historical facts for cost, compliance, patch, change, incident, and lifecycle trends while current-state tables remain optimized for operational reads.

### Consumption and Data Agent
- Add curated, versioned Gold consumption contracts and Fabric-native semantic-model definition/deployment support where the current public API supports it.
- If a Fabric preview surface cannot be deployed automatically, produce a validated versioned definition and expose an explicit deployment-blocked state; do not silently report success.
- Keep physical per-type ontology tables behind manifests/views/contracts so API, web, and agent consumers use stable logical names.
- Expand the existing relationship-suggestion Data Agent only after curated Gold outputs are healthy, and add reproducible offline evaluation plus optional live evaluation.

### API and web experience
- Add a dedicated scope-enforced Fabric medallion health/capabilities API because table-level SLO, quality, lineage, and lifecycle data does not fit the connection-health contract.
- Extend the existing Data & Integrations/Connections experience with a Bronze/Silver/Gold health view rather than creating a disconnected administration product.
- Show layer summaries, freshness/SLO status, failed runs, empty-versus-unavailable state, publication-manifest lifecycle, governance gaps, and semantic/Data Agent readiness.
- Preserve existing API response-envelope, authentication, accessibility, responsive-layout, and partial-degradation patterns.

### Security, lineage, capacity, and maintenance
- Use defense in depth: existing application scope enforcement remains mandatory and Fabric-native roles/RLS are added where supported.
- Use managed identity in deployed environments, least-privilege roles, no embedded secrets, and no broad workspace mutation from end-user requests.
- Formalize internal provenance and Fabric item lineage first; integrate external Purview surfaces only through supported APIs and explicit configuration.
- Add capacity paused/throttled detection and observable maintenance status. Delta compaction/vacuum must be scheduled, bounded, retention-safe, and never run implicitly on an API request.

### the agent's Discretion
- Exact module boundaries, route names, component composition, visual density, default SLO multipliers, and plan grouping may follow established repository patterns.
- The planner may split infrastructure-heavy semantic model, RLS, lineage, capacity, and maintenance work into separate plans while keeping all MED requirements in Phase 10.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/fabric/sync_service.py`, `src/fabric/data_quality.py`, `src/fabric/telemetry.py`, and `src/fabric/schema_registry.py` provide the ingestion, quality, metrics, and contract seams.
- `src/ontology/ontology_publisher.py`, `src/ontology/pending_relationships.py`, `src/ontology/confidence.py`, and `src/fabric_pipelines/relationship_suggestion_promoter.py` provide publication and relationship-governance foundations.
- Existing topology, impact-context, predeploy, vulnerability, patch, change, lifecycle, and governance pipelines already target the missing Gold outputs.
- `src/fabric/lakehouse_manager.py` and `src/fabric/data_agent_manager.py` establish Fabric item-management patterns.
- `src/onboarding/health.py`, `src/api/routers/connections.py`, and `web/src/app/connections/page.tsx` provide health vocabulary and the existing Data & Integrations experience.

### Established Patterns
- Fabric/OneLake Delta tables use versioned PyArrow schemas, scope-safe resource identity, explicit ingestion state, quality reports, and optimistic/idempotent writes.
- API routers depend on provider/service boundaries and return typed, scope-enforced envelopes with partial availability rather than reading datasets directly.
- Web services and types are centralized under `web/src/lib`, and pages preserve accessible loading, error, empty, and degraded states.
- Live Fabric changes are deployed incrementally and verified against actual table registration and row-level evidence.

### Integration Points
- Publication preflight and retry integrate at the ontology publication boundary invoked by Fabric sync.
- Manifest, SLO, lineage, lifecycle, and maintenance state land in metadata contracts and feed a dedicated API provider/router.
- Gold restoration builds on existing pipeline modules and deployment configuration rather than introducing duplicate transformations.
- Semantic serving and Data Agent expansion use Fabric REST item definitions and existing manager patterns.
- Web capability health integrates with the existing Connections/Data & Integrations navigation and API client.

</code_context>

<specifics>
## Specific Ideas

- Baseline the phase against the live scan: 320 readable tables; Bronze 9/8 non-empty; Silver 18/14; Gold 288/140; ontology 2,091 entities and 1,669 relationships; 84 missing ownership and 52 missing tags; ingestion history 9 completed and 12 failed.
- Treat the current undefined relationship endpoint class and the stale inventory/source-status gaps as concrete acceptance cases, not hypothetical examples.
- Keep live deployment reversible and avoid destructive changes to APIM or unrelated Azure resources.

</specifics>

<deferred>
## Deferred Ideas

- Fully autonomous production remediation remains outside this phase.
- Multi-cloud medallion ingestion and replacement of enterprise systems of record remain deferred.

</deferred>
