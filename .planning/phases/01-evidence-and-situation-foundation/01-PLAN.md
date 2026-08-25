# Phase 1 Plan: Evidence and Situation Foundation

## 1. Objective
Deliver a durable, authorization-scoped situation foundation where normalized Azure evidence is persisted with freshness, provenance, quality signals, and immutable audit history.

This plan implements Phase 1 only:
- FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05
- DETECT-01, DETECT-02

## 2. Planning Inputs and Constraints

### Required Sources Used
- `.planning/phases/01-evidence-and-situation-foundation/01-CONTEXT.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/INTEGRATIONS.md`
- `.planning/codebase/CONVENTIONS.md`
- `.planning/codebase/STACK.md`
- `.planning/codebase/TESTING.md`
- `.planning/codebase/CONCERNS.md`

### Locked Decisions to Implement
- D-01..D-10 are mandatory and explicitly mapped in Section 10.

### Scope Guardrails
In scope:
- Durable situation record model and lifecycle metadata.
- Evidence normalization envelope for representative signals.
- Delta persistence + ontology projection links.
- Read-time authorization scoping.
- Freshness/quality/trust indicators and contradiction signaling.
- Append-only audit events for situation/evidence lifecycle activity.

Out of scope (deferred to later phases):
- Recommendation ranking and approval workflow semantics.
- Typed remediation execution and rollback orchestration.
- Broader domain workflow expansion and pilot failure drills.

## 3. Existing Patterns and Integration Points to Reuse

### API Layer Patterns
- Use envelope and evidence conventions from `src/api/evidence.py`.
- Reuse auth and scoped-read guardrails from `src/api/auth.py`, `src/api/rbac.py`, and existing `_filter_scoped` route patterns in `src/api/routers/`.
- Keep router handlers thin and delegate business logic through runtime providers as in `src/api/routers/operations.py`.

### Ingestion and Watermark Patterns
- Follow lock + watermark + immutable run metadata orchestration in `src/hermes_arg_connector/service.py`.
- Extend query normalization flow rather than creating a second ingestion path.

### Persistence and Projection Patterns
- Add curated tables through dataset mapping in `src/fabric/dataset_mapper.py`.
- Reuse sync orchestration, quality validation, and state transitions in `src/fabric/sync_service.py`.
- Keep Azure/Fabric systems as systems of record and ontology as projection.

### Testing and Verification Patterns
- Add focused pytest suites under `tests/test_*.py` with behavior-first assertions.
- Add API contract tests using FastAPI `TestClient` patterns seen in existing `tests/test_api_*.py` suites.

## 4. Execution Order and Dependencies

### Wave 1 (Foundation Data Plane)
1. Task 1: Situation and evidence canonical schema + Delta table registration.
2. Task 2: Ingestion normalization for representative signals into common evidence envelope.
3. Task 3: Append-only audit event model and persistence path.

### Wave 2 (Projection + API Surface)
4. Task 4: Ontology projection and links from situation to operational entities.
5. Task 5: Authorized read APIs for situations/evidence/audit with scoped filters.
6. Task 6: Freshness/quality/contradiction indicators in API contracts.

### Wave 3 (Verification Hardening)
7. Task 7: Requirement-aligned tests (unit + integration + API).
8. Task 8: Operational checks, migration notes, and phase acceptance validation.

Dependency graph:
- Task 2 depends on Task 1.
- Task 3 depends on Task 1.
- Task 4 depends on Tasks 1 and 2.
- Task 5 depends on Tasks 1, 3, and 4.
- Task 6 depends on Tasks 2 and 5.
- Task 7 depends on Tasks 2 through 6.
- Task 8 depends on Task 7.

## 5. Detailed Task Plan

### Task 1: Define canonical situation/evidence storage model (D-01, D-02)
Goal:
- Introduce durable records for situation identity, lifecycle, severity, priority, scope, ownership, and affected resources.

Primary files to modify:
- `src/fabric/dataset_mapper.py`
- `src/fabric/schema_registry.py`
- `src/storage/delta_writer.py` (only if schema or write mode support is required)

Implementation steps:
1. Define normalized datasets/tables for:
   - `silver_situations`
   - `silver_situation_resources`
   - `silver_situation_evidence`
2. Add schema definitions with explicit required fields:
   - Situation ID, state, severity, priority, scope dimensions, owner, timestamps.
   - Resource linkage rows for affected entities.
   - Evidence linkage rows with source references.
3. Ensure these tables are mapped in the existing dataset load/write pipeline.
4. Keep records immutable where required and updateable only for lifecycle-state transitions with explicit event tracking.

Verification:
- `uv run pytest tests/test_dataset_mapper.py -k situation`
- `uv run pytest tests/test_delta_tables.py -k situation`

Done when:
- Situation and evidence tables exist in mapper/schema outputs.
- Validation fails on missing required lifecycle/ownership/scope fields.

---

### Task 2: Normalize representative source signals into common evidence envelope (D-03, D-04)
Goal:
- Ingest representative ARG, Activity Log, Monitor/Service Health, Defender, Policy, and vulnerability signals into one canonical evidence record shape.

Primary files to modify:
- `src/hermes_arg_connector/queries.py`
- `src/hermes_arg_connector/source.py`
- `src/hermes_arg_connector/normalize.py`
- `src/hermes_arg_connector/service.py`
- `src/fabric/dataset_mapper.py`

Implementation steps:
1. Extend query catalog/specs to include representative signal families required by Phase 1.
2. Normalize all evidence records to one envelope containing:
   - canonical evidence ID
   - source family/type
   - source object ID/deep link inputs
   - observed timestamp + ingested timestamp
   - watermark/version
   - ingestion status
3. Preserve batch-level metadata (`runId`, query version, subscriptions/scope) and per-record provenance.
4. Ensure deduplication across same-source and cross-source duplicates while retaining source identifiers.
5. Persist normalized evidence rows into `silver_situation_evidence` inputs.

Verification:
- `uv run pytest tests/test_normalize.py -k evidence`
- `uv run pytest tests/test_service.py -k watermark`
- `uv run pytest tests/test_incremental_sync.py -k evidence`

Done when:
- Each representative signal family can be observed in canonical evidence rows.
- Watermarks and ingestion status are preserved for replay/audit.

---

### Task 3: Implement immutable append-only audit events (D-09, D-10)
Goal:
- Persist append-only event logs for situation observation and lifecycle activity.

Primary files to modify:
- `src/fabric/dataset_mapper.py`
- `src/fabric/schema_registry.py`
- `src/fabric/sync_service.py`
- `src/api/routers/` (for event emission hooks where state transitions are exposed)

Implementation steps:
1. Add `silver_audit_events` dataset/schema with immutable event rows.
2. Capture required fields:
   - event ID
   - actor
   - action
   - authorized scope snapshot
   - timestamp
   - related source references and situation/evidence IDs
3. Enforce append-only writes for audit table.
4. Emit events for:
   - situation creation
   - lifecycle transition
   - evidence attach/refresh observation

Verification:
- `uv run pytest tests/test_delta_tables.py -k audit`
- `uv run pytest tests/test_fabric_client.py -k audit`

Done when:
- Events are immutable and queryable with actor/action/scope/source references.

---

### Task 4: Project situations and links into ontology graph (D-02)
Goal:
- Project situation records and links to incidents/findings/vulnerabilities/changes/twin entities.

Primary files to modify:
- `src/fabric/dataset_mapper.py`
- `src/ontology/entity_builder.py`
- `src/ontology/relationship_builder.py`
- `src/ontology/ontology_sync.py`

Implementation steps:
1. Add ontology entity type(s) for situations if not already present.
2. Define relation mappings from situation to linked operational entities.
3. Preserve versioning/timestamps and existing ontology lifecycle semantics.
4. Ensure links remain navigable without breaking existing domain relationship contracts.

Verification:
- `uv run pytest tests/test_ontology_sync.py -k situation`
- `uv run pytest tests/test_semantic_queries.py -k situation`

Done when:
- Situation entities and relationships appear in ontology outputs and are semantically queryable.

---

### Task 5: Add authorization-scoped situation/evidence/audit read APIs (D-05, D-06)
Goal:
- Expose read APIs that enforce scope and never leak out-of-scope fields or records.

Primary files to modify:
- `src/api/runtime.py`
- `src/api/dependencies.py`
- `src/api/routers/` (new `situations.py` router plus app registration)
- `src/api/app.py`
- `src/api/scope.py`

Implementation steps:
1. Add runtime provider(s) for situation/evidence/audit views from synchronized datasets.
2. Implement routes:
   - list situations
   - get situation detail
   - list evidence for a situation
   - list audit events for a situation
3. Apply existing `ReadScope` and recursive scoped filtering patterns before response.
4. Return existing envelope shape (`data`, `evidence`, `scope`, optional warnings/pagination).
5. Block out-of-scope resources and avoid existence disclosure for forbidden items.

Verification:
- `uv run pytest tests/test_api_http.py -k situation`
- `uv run pytest tests/test_api_primitives.py -k scope`
- `uv run pytest tests/test_api_semantic.py -k scope`

Done when:
- Authorized callers see only permitted subscriptions/resources/fields.
- Out-of-scope requests are filtered or return not-found/forbidden per existing API behavior.

---

### Task 6: Expose freshness, quality, provenance, and contradiction states (D-07, D-08)
Goal:
- Make trust indicators explicit in API responses so operators can distinguish fresh/stale/degraded/contradictory evidence.

Primary files to modify:
- `src/api/evidence.py`
- `src/api/models.py`
- `src/api/routers/situations.py` (from Task 5)
- `src/fabric/data_quality.py`

Implementation steps:
1. Reuse freshness banding in `src/api/evidence.py` and extend as needed for source availability/degradation.
2. Add explicit quality/status fields at response level for situation evidence summaries.
3. Represent contradiction/incompleteness as explicit warnings/flags, never hidden fallback behavior.
4. Ensure provenance references are included for each material evidence claim.

Verification:
- `uv run pytest tests/test_api_models.py -k evidence`
- `uv run pytest tests/test_api_http.py -k freshness`

Done when:
- Situation responses carry freshness, quality, provenance, and contradiction markers.
- No endpoint returns unsupported definitive conclusions when evidence is stale/missing/conflicting.

---

### Task 7: Requirement coverage test suite
Goal:
- Lock Phase 1 behavior with deterministic tests tied to FOUND/DETECT requirements.

Primary files to add/modify:
- `tests/test_situations_model.py`
- `tests/test_situations_ingestion.py`
- `tests/test_situations_api.py`
- `tests/test_situations_authorization.py`
- `tests/test_situations_audit.py`

Implementation steps:
1. Add unit tests for normalization, dedupe, watermark, and contradiction handling.
2. Add integration tests for Delta/ontology synchronization paths.
3. Add API contract tests for envelope, scope filtering, and trust indicators.
4. Add regression cases for out-of-scope data exposure and stale/degraded source signaling.

Verification:
- `uv run pytest tests/test_situations_model.py tests/test_situations_ingestion.py tests/test_situations_api.py tests/test_situations_authorization.py tests/test_situations_audit.py`

Done when:
- All new tests pass and each Phase 1 requirement has at least one direct assertion.

---

### Task 8: Final acceptance checks and operational validation
Goal:
- Validate Phase 1 against roadmap success criteria and operational reliability concerns.

Primary files to modify:
- `docs/` runbook/config docs relevant to situation/evidence foundation
- `IMPLEMENTATION_SUMMARY.md` (if maintained for milestone tracking)

Implementation steps:
1. Execute targeted end-to-end verification flow:
   - run ingestion
   - run fabric sync
   - query situation APIs with scoped identities
2. Confirm immutable audit trail visibility and scoped access behavior.
3. Record operational notes for source outages, stale data, and replay behavior.

Verification:
- `uv run pytest tests/test_api_http.py -k situation`
- `uv run pytest tests/test_incremental_sync.py`
- `uv run pytest`

Done when:
- Roadmap Phase 1 success criteria are demonstrably satisfied by test and API evidence.

## 6. Verification Strategy

### Automated
- Unit: normalization, schema validation, freshness/quality classifiers.
- Integration: ingestion to Delta to ontology sync.
- API: scoped envelope contracts and trust indicators.
- Regression: no out-of-scope leakage, no mutable audit history.

### Manual/Operational
- Validate representative signals appear with source IDs, timestamps, watermarks, and ingestion status.
- Validate one scoped principal cannot inspect another scope's situation/evidence/audit rows.
- Validate stale or contradictory evidence is surfaced as such.

## 7. Risks and Mitigations

1. Risk: Source contract variance across signal families causes normalization drift.
   - Mitigation: enforce strict canonical envelope schema and per-source adapters with validation.

2. Risk: Scope filtering regressions leak nested out-of-scope fields.
   - Mitigation: reuse established recursive scope filtering pattern and add nested-structure regression tests.

3. Risk: Immutable audit table accidentally receives update/merge writes.
   - Mitigation: enforce append-only semantics at mapper/sync write mode and test for mutation rejection.

4. Risk: Freshness fallbacks become expensive with large tables.
   - Mitigation: preserve watermarks and source status at write time; avoid repeated full-table scans.

## 8. Definition of Done for Phase 1
- Durable situation records exist with lifecycle, severity, priority, scope, ownership, and affected resources.
- Representative source families ingest into canonical evidence records with provenance/watermark/status.
- APIs expose freshness, quality, provenance, contradiction/incompleteness, and scope-limited responses.
- Audit events are immutable, append-only, and actor/action/scope/source attributable.
- Authorization boundaries are enforced for situations, evidence, and audit data.

## 9. Requirement-to-Task Acceptance Mapping

| Requirement | Covered By Tasks | Acceptance Evidence |
|---|---|---|
| FOUND-01 | 1, 5, 7 | Situation schema + API contract tests |
| FOUND-02 | 4, 5, 7 | Ontology relationship tests + detail API checks |
| FOUND-03 | 2, 6, 7 | Evidence freshness/quality/provenance assertions |
| FOUND-04 | 3, 5, 7 | Append-only audit events + API visibility tests |
| FOUND-05 | 5, 7 | RBAC/scope tests showing no out-of-scope exposure |
| DETECT-01 | 2, 7 | Representative source normalization tests |
| DETECT-02 | 2, 7 | Dedupe + source ID/timestamp/watermark/status checks |

## 10. Decision Coverage Matrix (D-01..D-10)

| Decision | Implemented In |
|---|---|
| D-01 | Tasks 1, 5 |
| D-02 | Tasks 1, 4 |
| D-03 | Task 2 |
| D-04 | Tasks 2, 3 |
| D-05 | Task 5 |
| D-06 | Task 5 |
| D-07 | Task 6 |
| D-08 | Task 6 |
| D-09 | Task 3 |
| D-10 | Task 3 |

## 11. Execution Notes
- Implement tasks in wave order; do not begin a wave until dependencies are complete.
- Keep all changes inside backend and planning scope for Phase 1.
- Do not implement recommendation, approval orchestration, or remediation execution behavior in this phase.
