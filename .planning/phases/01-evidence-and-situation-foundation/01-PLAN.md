---
phase: 01-evidence-and-situation-foundation
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/situations/__init__.py
  - src/situations/models.py
  - src/situations/materializer.py
  - src/situations/store.py
  - src/hermes_arg_connector/normalize.py
  - src/hermes_arg_connector/storage.py
  - src/fabric/schema_registry.py
  - src/fabric/dataset_mapper.py
  - src/fabric/sync_service.py
  - src/ontology/entity_builder.py
  - src/ontology/relationship_builder.py
  - src/api/evidence.py
  - src/api/models.py
  - src/api/dependencies.py
  - src/api/runtime.py
  - src/api/routers/situations.py
  - src/api/app.py
  - web/src/lib/types.ts
  - web/src/lib/services.ts
  - web/src/lib/situations.ts
  - web/src/components/SituationTable.tsx
  - web/src/components/ui/EvidenceBar.tsx
  - web/src/app/page.tsx
  - web/src/app/connections/page.tsx
  - web/src/app/situations/page.tsx
  - web/src/app/situations/[id]/page.tsx
  - tests/test_situations_model.py
  - tests/test_situations_tracer.py
  - tests/test_situations_ingestion.py
  - tests/test_situations_ontology.py
  - tests/test_situations_api.py
  - tests/test_situations_authorization.py
  - tests/test_situations_audit.py
  - tests/fixtures/phase1_signal_payloads.json
  - web/src/lib/situations.test.ts
  - web/src/components/SituationTable.test.tsx
  - web/src/app/situations/page.test.tsx
  - web/src/app/situations/[id]/page.test.tsx
autonomous: true
requirements:
  - FOUND-01
  - FOUND-02
  - FOUND-03
  - FOUND-04
  - FOUND-05
  - DETECT-01
  - DETECT-02

estimate:
  tokens: 52000
  raw_tokens: 52000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "A normalized source observation produces a durable situation with type, lifecycle, severity, priority, scope, owner, affected resources, timestamps, and stable identity."
    - "Situation detail exposes linked operational entities and source evidence without treating the ontology projection as the system of record."
    - "ARG/Activity Log, Monitor or Service Health, Defender, Policy, and vulnerability observations share one envelope containing source identity, observation and ingestion timestamps, watermark, provenance, and ingestion status."
    - "Duplicate observations do not create duplicate situation/evidence records, while every retained source identifier remains inspectable."
    - "Freshness, availability, quality, contradiction, and incomplete-data states are explicit in API responses and the operator UI."
    - "A scoped principal can read only authorized situations, nested evidence, links, and audit events; forbidden records do not disclose existence."
    - "Audit history is append-only and attributes observation and lifecycle events to actor, action, scope snapshot, timestamp, and source references."
  artifacts:
    - path: "src/situations/models.py"
      provides: "Validated canonical situation, evidence, link, source-status, and audit record shapes"
      contains: "class Situation"
    - path: "src/fabric/schema_registry.py"
      provides: "Versioned Delta schemas for situations, evidence, links, and audit events"
      contains: "metadata_audit_events"
    - path: "src/hermes_arg_connector/normalize.py"
      provides: "Canonical multi-source evidence and situation materialization inputs"
      contains: "NormalizedGraph"
    - path: "src/api/routers/situations.py"
      provides: "Scoped situation, evidence, and audit read endpoints"
      exports: ["router"]
    - path: "web/src/app/situations/[id]/page.tsx"
      provides: "Evidence-backed situation brief with trust, contradiction, linked-entity, timeline, and audit presentation"
    - path: "tests/test_situations_tracer.py"
      provides: "End-to-end ingestion-to-Delta-to-API happy-path proof"
  key_links:
    - from: "src/hermes_arg_connector/normalize.py"
      to: "src/hermes_arg_connector/storage.py"
      via: "NormalizedGraph evidence and situation collections are published in the immutable source generation"
      pattern: "situations|evidence"
    - from: "src/hermes_arg_connector/storage.py"
      to: "src/fabric/dataset_mapper.py"
      via: "generation JSONL is mapped to curated Delta datasets"
      pattern: "situation"
    - from: "src/fabric/sync_service.py"
      to: "src/ontology/ontology_sync.py"
      via: "situation entities and resolvable links enter the existing validated ontology projection"
      pattern: "Situation"
    - from: "src/api/routers/situations.py"
      to: "src/api/dependencies.py"
      via: "ReadScope is resolved before provider data is serialized"
      pattern: "ReadScope"
    - from: "web/src/lib/services.ts"
      to: "src/api/routers/situations.py"
      via: "situationsApi sends ScopeSelection and consumes the standard Envelope contract"
      pattern: "situations"
    - from: "web/src/app/situations/[id]/page.tsx"
      to: "web/src/components/ui/EvidenceBar.tsx"
      via: "detail trust summary renders source, freshness, quality, and warnings"
      pattern: "EvidenceBar"
---

<objective>
Deliver the Phase 1 evidence-and-situation foundation as one executable vertical slice: a source observation becomes a durable, governed situation; the API returns only authorized evidence and audit context; and the workbench renders the operator-trust UI contract.

Purpose: Establish the durable, provenance-bearing read boundary that later investigation work can consume without inventing a second store, graph, or authorization path.
Output: Delta-backed situation/evidence/link/audit records, representative normalized source inputs, ontology projection links, scoped read APIs, and contract-tested UI surfaces for the command center, situation queue/detail, and source-trust view.
</objective>

<execution_context>
@~/.copilot/gsd-core/workflows/execute-plan.md
@~/.copilot/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/STATE.md
@.planning/phases/01-evidence-and-situation-foundation/01-CONTEXT.md
@.planning/phases/01-evidence-and-situation-foundation/01-UI-SPEC.md
@.planning/codebase/ARCHITECTURE.md
@.planning/codebase/STRUCTURE.md
@.planning/codebase/INTEGRATIONS.md
@.planning/codebase/CONVENTIONS.md
@.planning/codebase/STACK.md
@.planning/codebase/TESTING.md
@.planning/codebase/CONCERNS.md
@src/api/evidence.py
@src/api/auth.py
@src/api/rbac.py
@src/api/scope.py
@src/api/dependencies.py
@src/api/runtime.py
@src/api/routers/operations.py
@src/hermes_arg_connector/service.py
@src/hermes_arg_connector/queries.py
@src/hermes_arg_connector/normalize.py
@src/hermes_arg_connector/storage.py
@src/fabric/dataset_mapper.py
@src/fabric/schema_registry.py
@src/fabric/sync_service.py
@src/storage/delta_writer.py
@src/ontology/entity_builder.py
@src/ontology/relationship_builder.py
@src/ontology/ontology_sync.py
@web/src/lib/types.ts
@web/src/lib/services.ts
@web/src/lib/situations.ts
@web/src/components/SituationTable.tsx
@web/src/components/ui/EvidenceBar.tsx
@web/src/components/AppShell.tsx
@web/src/app/page.tsx
@web/src/app/connections/page.tsx
@web/src/app/situations/page.tsx
@web/src/app/situations/[id]/page.tsx

<interfaces>
Use the existing interfaces directly. `Normalizer.normalize(payload, observed_at)` returns `NormalizedGraph`; `DatasetStore.publish(graph, query_results, run_metadata)` publishes an immutable generation; `InventoryDatasetMapper.load(snapshot, ingestion_run_id, fs=None)` returns curated table rows; and `FabricSyncService.sync()` owns Delta writes, quality validation, state rows, and ontology synchronization. `DeltaWriter` supports `OVERWRITE`, `APPEND`, and `MERGE`; use `APPEND` for audit records and do not change its required base columns.

API composition is through `ApiContext` in `src/api/dependencies.py` and `build_context()` in `src/api/runtime.py`; routers must use `ReadScope`, `Page`, `envelope()`, and the existing `ApiError` contract. `Evidence`/`Envelope` in `src/api/evidence.py` and `Envelope`/`EvidenceItem` in `web/src/lib/types.ts` are compatibility-sensitive wire shapes. The frontend `apiRequest()` and `scopeToSearchParams()` already carry auth and scope; `SituationTable`, `EvidenceBar`, `StatePanel`, `PageHeader`, `ScopeSelector`, and `AppShell` are the approved UI primitives.
</interfaces>

<scope_fence>
Keep the implementation inside the evidence, situation, authorization, audit, ontology-projection, and read-only workbench boundary. Do not add a second database, a new external SDK, a new authentication mode, an executable action control, or a chat-driven situation workflow. Existing later-surface links remain explicitly read-only navigation and must not be represented as server-recorded audit activity.
</scope_fence>
</context>

<tasks>

<task type="tracer">
  <name>Task 1: Tracer — persist and open one authorized situation end to end</name>
  <files>src/situations/__init__.py, src/situations/models.py, src/situations/materializer.py, src/situations/store.py, src/hermes_arg_connector/normalize.py, src/hermes_arg_connector/storage.py, src/fabric/schema_registry.py, src/fabric/dataset_mapper.py, src/fabric/sync_service.py, src/api/runtime.py, src/api/routers/situations.py, src/api/app.py, web/src/lib/types.ts, web/src/lib/services.ts, web/src/app/situations/[id]/page.tsx, tests/test_situations_model.py, tests/test_situations_tracer.py</files>
  <action>Implement the thinnest production path for D-01 and D-02. Add a `src/situations` domain package with validated records and deterministic IDs. A normalized resource-change observation must materialize one situation with explicit type, lifecycle state, severity, priority, scope dimensions, owner, affected-resource IDs, started/last-observed timestamps, and linked evidence IDs; use `resource_id` as the Delta-compatible stable key and keep raw source payloads out of the situation response. Add `silver_situations`, `silver_situation_links`, and `silver_situation_evidence` schemas and map them through the existing immutable generation → `InventoryDatasetMapper` → `FabricSyncService` path; do not bypass `DeltaWriter` or OneLake. Add a read provider composed in `build_context()` and a thin `GET /api/v1/situations/{situation_id}` route that returns `data`, `evidence`, `scope`, warnings, and knowledge version through `envelope()`. The route must use `ReadScope`, project only in-scope nested records, and return the established not-found contract when the situation or its scope is not visible. Wire the detail page to this real endpoint through typed `situationsApi.get`; remove the current incident-only dependency for the canonical situation identity while retaining the approved shell and read-only presentation primitives. Create a deterministic fixture-backed test that runs normalization, immutable publication, local Delta synchronization, provider read, and `TestClient` request as one path; external Azure clients remain injected fakes only at the network boundary. Cite D-01 and D-02 in implementation comments/docstrings only where the rationale is non-obvious.</action>
  <verify>
    <automated>uv run pytest tests/test_situations_model.py tests/test_situations_tracer.py -q</automated>
    <automated>uv run ruff check src/situations src/hermes_arg_connector/normalize.py src/hermes_arg_connector/storage.py src/fabric/schema_registry.py src/fabric/dataset_mapper.py src/fabric/sync_service.py src/api/runtime.py src/api/routers/situations.py src/api/app.py tests/test_situations_model.py tests/test_situations_tracer.py</automated>
  </verify>
  <done>One fixture observation is normalized, persisted through the existing generation and Delta synchronization path, projected into a queryable situation record, and returned by `GET /api/v1/situations/{id}` with a scope-aware envelope; the detail page can render that response without using the incident engine as its data contract. D-01 and D-02 are covered by direct schema, persistence, API, and UI assertions.</done>
</task>

<task type="auto">
  <name>Task 2: Expand representative evidence, deduplication, trust states, audit, and ontology links</name>
  <files>src/hermes_arg_connector/queries.py, src/hermes_arg_connector/source.py, src/hermes_arg_connector/normalize.py, src/hermes_arg_connector/service.py, src/hermes_arg_connector/storage.py, src/fabric/schema_registry.py, src/fabric/dataset_mapper.py, src/fabric/sync_service.py, src/fabric/data_quality.py, src/ontology/entity_builder.py, src/ontology/relationship_builder.py, tests/fixtures/phase1_signal_payloads.json, tests/test_situations_ingestion.py, tests/test_situations_ontology.py, tests/test_situations_audit.py</files>
  <action>Extend the tracer without creating a parallel ingestion path. For D-03 and D-04, add canonical source-family adapters/specs at the existing source boundary for representative ARG/Activity Log, Monitor or Service Health, Defender, Policy, and vulnerability payloads, using the current Azure query/client and vulnerability-feed abstractions and fixture payloads rather than adding SDKs. Preserve per-family query version, requested subscription scope, run ID, provider status, and watermark in batch metadata. Normalize every family into the same evidence envelope: stable evidence ID, source family, source object ID and locator/deep-link input, target resource/entity IDs, observed_at, ingested_at, watermark, ingestion_status, provenance, freshness band, quality, availability, and confidence. Deduplicate repeated records by source identity plus canonical fingerprint and deduplicate related cross-source observations without dropping their distinct source IDs; a failed or unavailable family must remain an explicit source status and must not advance its successful watermark. Reuse `classify_freshness` and the existing lock/state/immutable-generation behavior instead of full-table freshness scans. For D-07 and D-08, derive explicit fresh/aging/stale/unknown, available/degraded/unavailable, quality, contradiction, and unknown markers from retained evidence; preserve conflicting assertions and never collapse them into a definitive conclusion. For D-09 and D-10, add `metadata_audit_events` with an append-only Delta write, stable event ID, actor, action, scope snapshot, timestamp, situation/evidence IDs, and source references; emit observation, situation-created, evidence-ingested, and lifecycle-state events. Add `Situation` to the existing ontology entity registry and typed links for resolvable incident, exposure/compliance, vulnerability, change, resource, service, and operational-twin entities; keep unresolved links in the curated link table with an explicit quality state. Validate all new tables with the existing data-quality and ontology validators and add tests for all six source families, duplicate preservation, watermark behavior, source failure, contradiction/unknown signaling, append-only mutation rejection, and linked-entity projection. Cite D-03, D-04, D-07, D-08, D-09, and D-10 in the relevant task actions and acceptance assertions.</action>
  <verify>
    <automated>uv run pytest tests/test_situations_ingestion.py tests/test_situations_ontology.py tests/test_situations_audit.py tests/test_normalize.py tests/test_service.py tests/test_incremental_sync.py -q</automated>
    <automated>uv run ruff check src/hermes_arg_connector/queries.py src/hermes_arg_connector/source.py src/hermes_arg_connector/normalize.py src/hermes_arg_connector/service.py src/hermes_arg_connector/storage.py src/fabric/schema_registry.py src/fabric/dataset_mapper.py src/fabric/sync_service.py src/fabric/data_quality.py src/ontology/entity_builder.py src/ontology/relationship_builder.py tests/test_situations_ingestion.py tests/test_situations_ontology.py tests/test_situations_audit.py</automated>
  </verify>
  <done>Every required representative family produces the same provenance-bearing evidence shape; duplicate and partial-source tests prove source identifiers, timestamps, watermarks, and statuses survive; contradiction and unknown states are visible; append-only audit writes reject mutation; and ontology projection exposes Situation links without replacing Delta/OneLake authority. D-03, D-04, D-07, D-08, D-09, and D-10 have direct automated coverage.</done>
</task>

<task type="auto">
  <name>Task 3: Complete scoped read APIs and the approved operator-trust workbench surfaces</name>
  <files>src/api/evidence.py, src/api/models.py, src/api/dependencies.py, src/api/routers/situations.py, src/api/app.py, tests/test_situations_api.py, tests/test_situations_authorization.py, web/src/lib/types.ts, web/src/lib/services.ts, web/src/lib/situations.ts, web/src/components/SituationTable.tsx, web/src/components/ui/EvidenceBar.tsx, web/src/app/page.tsx, web/src/app/connections/page.tsx, web/src/app/situations/page.tsx, web/src/app/situations/[id]/page.tsx, web/src/lib/situations.test.ts, web/src/components/SituationTable.test.tsx, web/src/app/situations/page.test.tsx, web/src/app/situations/[id]/page.test.tsx</files>
  <action>Finish D-05 and D-06 at every read boundary and implement the approved UI-SPEC without inventing a competing design system. Extend the evidence wire contract with compatibility-safe defaults for source ID/locator, observed and ingested times, watermark, ingestion status, provenance, quality, availability, and confidence; keep `envelope()` as the serializer. Add the collection, situation evidence, and situation audit reads: `GET /api/v1/situations` with scope-aware search, P1/P2/P3 filtering, and pagination; `GET /api/v1/situations/{id}/audit`; and `GET /api/v1/evidence/{id}`. Apply `ReadScope` before serialization and recursively remove unauthorized nested resources, evidence, links, and audit fields; use the same not-found behavior for an out-of-scope ID as an unknown ID. Test reader, operator, and multi-grant principals through the existing `StaticTokenAuthenticator`/`Authorizer` fixtures, including no existence disclosure. Update `/situations` to consume durable situations rather than incident-derived summaries and preserve the table as the canonical queue with title/ID, lifecycle, priority, impact, qualified cause/status, owner/team, latest observation/change, scope count, search, segmented priority filter, pagination, exact empty/error copy, and keyboard-reachable actions. Update `/situations/[id]` to present the UI-SPEC hierarchy: breadcrumb and identity metadata; compact trust summary; “What failed?”, “What is at risk?”, and “What changed?” cards; source-grouped evidence rows with a focus-returning drawer/detail region; explicit “Evidence conflicts” and “What is not known” panels; bounded linked-entity list/graph fallback; chronological timeline; and newest-first append-only audit events with no edit/delete controls. Update `/` to use durable situations for the qualified posture scorecard and ranked six-row queue, and `/connections` to keep stale, failed, unavailable, and missing-context source rows visible. Reuse Fluent UI v9, existing CSS tokens, 4px page spacing, `StatusBadge`, `StatePanel`, `EvidenceBar`, `PageHeader`, `MetricCard`, `AppShell`, and `ScopeSelector`; do not add shadcn, Tailwind, another icon set, or a second token system. Keep scope, authorization, freshness, severity, and error states visible on mobile; use text plus color/icon for status; retain exact timestamps and selectable IDs. Replace any local collaboration or future-surface wording that could be mistaken for immutable audit or an executable action with the UI-SPEC labels “Save view locally” and “View future-phase candidate”. Cite D-05 and D-06 in authorization actions and D-07/D-08 in trust-state assertions.</action>
  <verify>
    <automated>uv run pytest tests/test_situations_api.py tests/test_situations_authorization.py tests/test_api_primitives.py -q</automated>
    <automated>cd web && npm test -- --run src/lib/situations.test.ts src/components/SituationTable.test.tsx src/app/situations/page.test.tsx 'src/app/situations/[id]/page.test.tsx'</automated>
    <automated>cd web && npm run build</automated>
  </verify>
  <done>All four target API reads return typed, scope-limited envelopes; authorized users can compare and open durable situations; forbidden records and nested fields are absent without existence leakage; and the command center, queue, detail, and source-trust surfaces visibly distinguish available, stale, degraded, contradictory, incomplete, empty, and unavailable states. D-05 through D-08 are covered by direct API/UI assertions, with no executable action or approval implication introduced.</done>
</task>

</tasks>

<dependency_graph>
Task 1 is the tracer and creates the canonical records, Delta table registration, read provider, detail endpoint, and typed detail contract. Task 2 depends on Task 1's record/envelope contracts and expands all source families, audit persistence, quality states, and ontology links. Task 3 depends on Tasks 1–2 because its collection/evidence/audit APIs and UI rendering consume those durable records and trust fields. Within the plan, execute strictly in Task 1 → Task 2 → Task 3 order; the plan is one Wave 1 unit, so no parallel task may modify these shared files.
</dependency_graph>

<verification>
<automated>uv run pytest tests/test_situations_model.py tests/test_situations_tracer.py tests/test_situations_ingestion.py tests/test_situations_ontology.py tests/test_situations_api.py tests/test_situations_authorization.py tests/test_situations_audit.py -q</automated>
<automated>uv run ruff check src/situations src/hermes_arg_connector src/fabric src/ontology src/api tests/test_situations_model.py tests/test_situations_tracer.py tests/test_situations_ingestion.py tests/test_situations_ontology.py tests/test_situations_api.py tests/test_situations_authorization.py tests/test_situations_audit.py</automated>
<automated>cd web && npm test -- --run src/lib/situations.test.ts src/components/SituationTable.test.tsx src/app/situations/page.test.tsx 'src/app/situations/[id]/page.test.tsx'</automated>
<automated>cd web && npm run build</automated>
<human-check>Run the local API and web app with a fixture-backed Delta root. Change the ScopeSelector and confirm the queue/detail/source-trust data reloads with the selected scope; open one situation and verify the trust summary, source IDs, exact timestamps, contradiction/unknown panels, bounded linked-entity list, and newest-first recorded audit events. Confirm stale/unavailable/empty states use the approved copy and that no page presents a future-phase candidate as executable.</human-check>
</verification>

<success_criteria>
- FOUND-01: durable situations expose all required lifecycle, severity, priority, scope, ownership, affected-resource, and timestamp fields.
- FOUND-02: situation links are persisted and the ontology projection exposes resolvable operational relationships with unresolved links explicitly qualified.
- FOUND-03: source freshness, availability, provenance, and quality are present in the API and visible in the workbench.
- FOUND-04: observation and lifecycle events are durable, append-only, and attributable to actor, action, scope, timestamp, and source references.
- FOUND-05: server-side Entra/RBAC-derived scope filtering protects situation, evidence, linked-entity, and audit reads, including nested fields.
- DETECT-01: representative ARG/Activity Log, Monitor or Service Health, Defender, Policy, and vulnerability inputs normalize into the common evidence envelope.
- DETECT-02: deduplication preserves source IDs, timestamps, watermarks, ingestion status, and batch provenance.
- The approved UI-SPEC is reflected in the command center, durable queue, situation brief, source-trust view, trust indicators, loading/error/empty/partial states, accessibility semantics, responsive behavior, and read-only handoff labels.
</success_criteria>

<source_audit>
## Multi-Source Coverage Audit

| Source | ID | Feature or constraint | Plan coverage | Status |
|---|---|---|---|---|
| GOAL | — | Durable, authorized situations with trustworthy evidence, freshness, provenance, quality, and audit history | Tasks 1–3 and success criteria | COVERED |
| REQ | FOUND-01 | Durable situation record and required triage fields | Task 1 | COVERED |
| REQ | FOUND-02 | Links to incidents, exposure/compliance, vulnerabilities, changes, and twin entities | Task 2 | COVERED |
| REQ | FOUND-03 | Freshness, availability, provenance, and quality visibility | Tasks 2–3 | COVERED |
| REQ | FOUND-04 | Immutable audit events | Task 2 and audit API in Task 3 | COVERED |
| REQ | FOUND-05 | Entra/RBAC scope for rows and fields | Task 3 | COVERED |
| REQ | DETECT-01 | Six representative source families | Task 2 | COVERED |
| REQ | DETECT-02 | Deduplication and source/run metadata | Task 2 | COVERED |
| RESEARCH | — | Retain FastAPI, Next.js/Fluent UI, OneLake/Delta, Fabric projection, Entra, and current adapters | Tasks 1–3 scope fence and actions | COVERED |
| RESEARCH | — | Immutable evidence references, source watermarks, explicit degraded states, and projection-not-authority boundary | Tasks 1–3 | COVERED |
| RESEARCH | — | Compact, provenance-bearing records rather than a replacement source system | Task 1 canonical model and Task 2 envelope | COVERED |
| CONTEXT | D-01 | Durable situation fields | Task 1 action/done | COVERED |
| CONTEXT | D-02 | Delta-backed persistence and ontology projection | Tasks 1–2 action/done | COVERED |
| CONTEXT | D-03 | Common envelope for representative signals | Task 2 action/done | COVERED |
| CONTEXT | D-04 | Per-record provenance and batch metadata | Task 2 action/done | COVERED |
| CONTEXT | D-05 | Entra/RBAC filters at read boundaries | Task 3 action/done | COVERED |
| CONTEXT | D-06 | No out-of-scope exposure | Task 3 action/done | COVERED |
| CONTEXT | D-07 | Freshness bands and quality signals | Tasks 2–3 action/done | COVERED |
| CONTEXT | D-08 | Explicit contradictory/incomplete evidence | Tasks 2–3 action/done | COVERED |
| CONTEXT | D-09 | Append-only immutable audit events | Task 2 action/done | COVERED |
| CONTEXT | D-10 | Actor/action/scope/time/source attribution | Task 2 action/done | COVERED |
</source_audit>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|---|---|
| Azure/provider payload → ingestion normalizer | External source observations and provider status enter the canonical evidence path. |
| Immutable generation/Delta → API read provider | Persisted records cross into request-time projections and must retain scope and provenance. |
| Entra-authenticated request → situation API | Untrusted caller input and principal claims select records and fields. |
| API envelope → browser workbench | Response data, warnings, source links, and local collaboration state reach the operator UI. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|---|---|---|---|---|---|
| T-01-01 | Tampering | Source payloads and watermarks | high | mitigate | Validate the canonical envelope, bind records to run ID/source ID, deduplicate by stable identity, and advance watermarks only for successful family ingestion. |
| T-01-02 | Information disclosure | Situation/evidence/audit API | high | mitigate | Resolve `ReadScope` from the existing Entra/RBAC principal, filter nested records before envelope serialization, and use indistinguishable not-found behavior for forbidden IDs. |
| T-01-03 | Spoofing | Audit actor attribution | high | mitigate | Derive actor from the authenticated principal or explicit system-ingestion identity; never accept browser-supplied actor fields for server-recorded events. |
| T-01-04 | Tampering | Audit Delta table | high | mitigate | Register a dedicated append-only schema, write only with `DeltaWriteMode.APPEND`, deduplicate event keys, and test that update/merge attempts are rejected. |
| T-01-05 | Information disclosure | Source locators and nested link fields | medium | mitigate | Store and return source locators only with their authorized evidence row; redact or omit fields removed by scope projection and keep raw payloads outside API responses. |
| T-01-06 | Elevation of privilege | Runtime/provider composition | high | mitigate | Keep routers read-only, reuse the existing `ApiContext`/provider boundary, and do not introduce a new authentication or direct-storage access path in the browser. |
| T-01-07 | Denial of service | Unbounded source, graph, or UI payloads | medium | mitigate | Reuse existing query/page/ontology bounds, retain compact evidence summaries, paginate collections, and preserve source failures as bounded status rows. |
| T-01-08 | Repudiation | Observation and lifecycle history | medium | mitigate | Persist immutable event IDs, run IDs, actor, action, scope snapshot, timestamps, and source/evidence references for every emitted event. |
| T-01-SC | Tampering | npm/uv dependency installation | high | accept | This plan adds no package-manager dependency; existing lockfiles and CI lint/test gates remain unchanged. |
</threat_model>

<output>
Create `.planning/phases/01-evidence-and-situation-foundation/01-SUMMARY.md` when done.
</output>
