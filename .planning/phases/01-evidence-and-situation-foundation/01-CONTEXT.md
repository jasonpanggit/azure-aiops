# Phase 1: Evidence and Situation Foundation - Context

**Gathered:** 2026-08-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 1 delivers a durable and authorization-scoped situation foundation where normalized Azure evidence is persisted with freshness, provenance, quality, and immutable audit history.

</domain>

<decisions>
## Implementation Decisions

### Situation model and lifecycle
- **D-01:** Represent each situation as a durable record with lifecycle state, severity, priority, scope, ownership, and affected resources.
- **D-02:** Persist situation records in Delta-backed storage and project into ontology entities for linked operational navigation.

### Evidence normalization and ingestion
- **D-03:** Normalize representative ARG, Activity Log, Monitor/Service Health, Defender, Policy, and vulnerability signals into a common record envelope with source ID, timestamps, watermark, and ingestion status.
- **D-04:** Preserve per-record provenance and batch-level ingestion metadata to support replay and auditability.

### Authorization and data visibility
- **D-05:** Enforce authorization scope at query/read boundaries using Entra claims and RBAC-derived filters.
- **D-06:** Prevent out-of-scope data exposure for situations, evidence records, and related operational entities.

### Freshness, quality, and trust indicators
- **D-07:** Expose freshness bands and quality signals on evidence so operators can distinguish fresh, stale, degraded, or unavailable source states.
- **D-08:** Surface contradictory or incomplete evidence explicitly rather than returning unsupported definitive conclusions.

### Audit persistence
- **D-09:** Use append-only immutable audit events for observation and lifecycle activity in the phase foundation.
- **D-10:** Capture actor, action, scope, timestamp, and source references for every persisted event.

### the agent's Discretion
- Minor schema naming and indexing details may be chosen during planning as long as they preserve scope boundaries, provenance, and authorization semantics.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning and scope
- `.planning/ROADMAP.md` — Phase 1 goal, dependencies, and success criteria.
- `.planning/REQUIREMENTS.md` — FOUND-01..FOUND-05 and DETECT-01..DETECT-02 requirements.
- `.planning/PROJECT.md` — Core value and delivery constraints for the MVP.

### Existing architecture and codebase guidance
- `.planning/codebase/ARCHITECTURE.md` — Current system patterns and layering.
- `.planning/codebase/STRUCTURE.md` — Code locations and module boundaries.
- `.planning/codebase/INTEGRATIONS.md` — Current external provider contracts and integration points.

### Runtime and API implementation references
- `src/api/evidence.py` — Evidence envelope and freshness/confidence handling.
- `src/hermes_arg_connector/service.py` — Watermark-driven ingestion pattern.
- `src/ontology/` — Entity/relationship projection patterns.
- `src/fabric/sync_service.py` — Delta persistence and synchronization approach.
- `src/api/auth.py` — Entra authentication and authorization guard patterns.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/api/evidence.py`: Reuse evidence envelope conventions for normalized evidence API outputs.
- `src/hermes_arg_connector/service.py`: Reuse watermark and ingestion-status patterns for source freshness.
- `src/fabric/sync_service.py`: Reuse Delta write/sync utilities for durable evidence and situation persistence.
- `src/ontology/`: Reuse projection patterns for situation-linked entities.
- `src/api/auth.py`: Reuse Entra/RBAC boundary enforcement for scoped data visibility.

### Established Patterns
- FastAPI API layer with explicit auth boundaries.
- Delta/OneLake persistence as system-of-record substrate.
- Fabric ontology projection as read-oriented relational context.
- Source-by-source connector normalization before cross-source workflows.

### Integration Points
- Situation creation/inspection routes in API layer.
- Ingestion adapters for representative Azure signal families.
- Audit event emitters tied to lifecycle transitions.
- UI read models that expose freshness/provenance/quality alongside evidence.

</code_context>

<specifics>
## Specific Ideas

- Keep phase output visibly operator-trust oriented: every situation view should expose why data is trustworthy (or not) through explicit freshness, provenance, and quality indicators.
- Keep schema evolution compatible with upcoming Phase 2 investigation and recommendation flows.

</specifics>

<deferred>
## Deferred Ideas

- Advanced recommendation ranking and approval workflow semantics (Phase 2).
- Typed remediation action orchestration (Phase 3).
- Expanded domain workflow breadth and operational twin replay experiences (Phase 4).
- Full pilot resiliency/failure drills and rollout controls (Phase 5).

</deferred>

---

*Phase: 1-Evidence and Situation Foundation*
*Context gathered: 2026-08-24*
