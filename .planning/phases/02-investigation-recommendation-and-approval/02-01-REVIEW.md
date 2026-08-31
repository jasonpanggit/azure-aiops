---
phase: 02-investigation-recommendation-and-approval
reviewed: 2026-08-31T23:55:47Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - src/api/models.py
  - src/api/routers/operations.py
  - src/intelligence/remediation/approval_decisions.py
  - src/intelligence/remediation/plan_repository.py
  - src/intelligence/remediation/remediation_generator.py
  - src/fabric/dataset_mapper.py
  - web/src/app/remediation/page.tsx
  - web/src/app/remediation/page.test.tsx
  - web/src/lib/services.ts
  - web/src/lib/types.ts
  - tests/test_api_remediation_approvals.py
  - tests/test_remediation_ontology_alignment.py
  - tests/test_remediation_repository_and_reports.py
  - docs/ontology-model.md
  - ontology-schema.md
findings:
  critical: 1
  warning: 2
  info: 0
  total: 3
status: issues_found
---

# Phase 02-01: Code Review Report

**Reviewed:** 2026-08-31T23:55:47Z  
**Depth:** standard  
**Files Reviewed:** 15  
**Status:** issues_found

## Summary

Reviewed the remediation decision workspace implementation across the API contract, server-side decision recording, remediation planning repository/projection, Fabric ontology mapping declarations, React remediation page, and scoped tests. The UI and API preserve the Phase 2 execution boundary: reviewed code does not execute Azure actions, create jobs, invoke rollback, or record realized outcomes.

The main defect is that approval decisions are still stored only in an in-process tuple owned by a planner/repository instance. That fails the phase objective for durable approval audit records and creates data-loss risk across process restarts, provider rebuilds, and concurrent requests. Ontology documentation is aligned at the model/schema level, but decision records need durable storage/publication wiring before the graph can reliably contain ApprovalDecision facts.

## Critical Issues

### CR-01: Approval decisions are non-durable in-process audit records

**File:** `src/intelligence/remediation/approval_decisions.py:12-21`, `src/intelligence/remediation/approval_decisions.py:63-65`, `src/api/routers/operations.py:202-204`  
**Impact:** Approval/rejection/expiry decisions can be lost on API restart, container reschedule, provider recreation, or concurrent request races. This violates the Phase 2 requirement that approval decisions be durable audit records. Because `record_remediation_decision()` resolves a planner from the request provider and appends into `planner.repository.decisions`, deployments that rebuild providers per request/snapshot do not have a durable decision ledger.  
**Evidence:** `RemediationDecisionStore` stores decisions in `self._decisions: tuple[...] = ()` and appends via an in-memory tuple replacement. The API route records decisions through `planner.repository.decisions.append(...)`; there is no injected durable store, persistence call, transaction, or lock. The only tests assert the immediate POST response, not that a later read/recreated provider retains the record.  
**Recommended fix:** Replace the in-process store with an injected durable append-only decision repository backed by the project's persistence layer/Fabric/OneLake or another approved audit store. Make `append()` transactional/locked, enforce uniqueness at the store boundary, and add tests that record a decision, rebuild the remediation provider, and verify the decision is still listed/projected.

## Warnings

### WR-01: Approved decision expiry is not parsed or checked for future validity

**File:** `src/api/routers/operations.py:231-236`, `src/api/models.py:229-235`  
**Impact:** An operator can record an `approved` decision with `expires_at="not-a-date"` or a date already in the past. The response still reports revalidation `"status": "passed"`, which weakens the bounded approval contract and can mislead downstream audit/ontology consumers.  
**Evidence:** The request model bounds `expires_at` only by string length. The route only checks `request.expires_at.strip()` for approved decisions and does not parse ISO-8601, compare to server time, or include an expiry validation check in the revalidation result.  
**Recommended fix:** Parse `expires_at` server-side for approved decisions, reject invalid or non-future timestamps, normalize to ISO-8601 UTC/date format, and add a revalidation check such as `approval_not_expired`.

### WR-02: ApprovalDecision ontology projection is not wired into the Fabric graph publication path

**File:** `src/intelligence/remediation/plan_repository.py:91-105`, `src/fabric/dataset_mapper.py:416-433`  
**Impact:** The docs and repository can describe `ApprovalDecision` entities and `hasApprovalDecision` relationships, but production Fabric datasets are built from `graph.entities`/`graph.relationships` in `InventoryDatasetMapper`. The remediation repository projection is not fed into that path, so approval decisions recorded by the API will not reliably appear in published ontology tables even after the entity/relationship types are registered.  
**Evidence:** `PlanRepository.ontology_projection()` creates decision entities and relationships, but code search shows it is only exercised by tests. `dataset_mapper.py` creates typed ontology tables from `graph.entities` and `graph.relationships`; it adds empty relationship tables for known types but does not ingest or merge remediation repository decision projections.  
**Recommended fix:** Once CR-01 introduces a durable decision repository, add a publication/export path that maps durable `ApprovalDecision` records into canonical ontology entity/relationship rows and includes them in the Fabric dataset mapper or ontology sync pipeline. Add an integration test that records a decision and verifies `ontology_approvaldecision_entities` and the `RemediationPlan_hasApprovalDecision_ApprovalDecision` relationship table contain that decision.

## Enhancement Recommendations

1. **Add a decision read/audit endpoint (Phase 2 in scope):** expose `GET /remediation-plans/{plan_id}/decisions` and/or a scoped decisions feed so the UI can show prior approvals/rejections/expiries without implying execution.
2. **Show source degradation per backlog row (Phase 2 in scope):** keep the existing global warnings, but annotate rows that came from degraded/unavailable sources so CAB reviewers can distinguish incomplete evidence from low-risk recommendations.
3. **Add optimistic decision concurrency metadata (Phase 2 in scope):** include a server-issued plan generation/freshness identifier alongside `action_version` so approvals can be rejected when the evidence snapshot changed even if the catalog action did not.
4. **Publish durable ApprovalDecision ontology facts (Phase 2 in scope after CR-01):** no schema change is needed; wire durable decision records into the existing `ApprovalDecision` / `hasApprovalDecision` model.
5. **Execution submission, rollback invocation, job creation, and realized-outcome capture are Phase 3/out of scope:** do not add controls or backend handlers for these in this decision workspace.

## Ontology Alignment Check

The documentation in `ontology-schema.md` and `docs/ontology-model.md` correctly models `ApprovalDecision` as an immutable human decision and explicitly states it is not an execution authorization token. `src/fabric/dataset_mapper.py` registers `ApprovalDecision` and `RemediationPlan --hasApprovalDecision--> ApprovalDecision` as valid ontology types/relationships.

No ontology schema changes are needed for this phase. The needed work is implementation wiring: durable decision records must be persisted and then published into the existing ontology graph projection.

---

_Reviewed: 2026-08-31T23:55:47Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
