# Requirements: Azure AI Operations Platform

**Defined:** 2026-08-23
**Core Value:** Operators can move from a detected Azure situation to an evidence-backed, auditable, human-approved remediation without losing context or control.

## v1 Requirements

Requirements for the controlled Azure pilot.

### Foundations

- [x] **FOUND-01**: Operator can open a durable situation record with type, lifecycle state, severity, priority, scope, owner, and affected resources.
- [x] **FOUND-02**: Situation records can link incidents, exposure findings, compliance findings, vulnerabilities, changes, and operational-twin entities.
- [x] **FOUND-03**: Operator can see source freshness, availability, provenance, and data-quality status for information used in a situation.
- [x] **FOUND-04**: The platform persists immutable audit events for observations, recommendations, approvals, executions, failures, and verification results.
- [x] **FOUND-05**: Authorized users can view only the subscriptions, resources, fields, evidence, and actions permitted by their Entra/RBAC scope.

### Detect and Explain

- [x] **DETECT-01**: Platform can ingest and normalize representative signals from existing Azure Resource Graph/Activity Log, Azure Monitor or Service Health, Defender for Cloud, Azure Policy, and vulnerability feeds.
- [x] **DETECT-02**: Platform deduplicates related signals and preserves source identifiers, timestamps, watermarks, and ingestion status.
- [ ] **DETECT-03**: Operator can view a situation timeline correlating relevant changes, incidents, findings, and source events.
- [ ] **DETECT-04**: Operator can inspect an evidence-backed explanation where every material claim links to source, timestamp, scope, query or deep link, provenance, freshness, and quality.
- [ ] **DETECT-05**: Operator can see affected resources, services, dependencies, ownership, environment, and business criticality within a bounded graph context.
- [ ] **DETECT-06**: Operator can see contradictory, missing, stale, or degraded evidence instead of receiving an unsupported definitive explanation.
- [ ] **DETECT-07**: Operator can search, filter, and navigate across situations, resources, services, vulnerabilities, policies, changes, and evidence without crossing authorization boundaries.

### Recommend and Approve

- [ ] **RECOMM-01**: Platform ranks recommended next actions using affected-resource criticality, exploitability or urgency, observed impact, evidence quality, and confidence.
- [ ] **RECOMM-02**: Each recommendation states its objective, target scope, rationale, supporting evidence, confidence, prerequisites, risks, and verification plan.
- [ ] **RECOMM-03**: Platform can explicitly return no safe action or escalation when evidence, permissions, scope, or confidence are insufficient.
- [ ] **APPROVE-01**: Authorized approver can approve, reject, or let a recommendation expire through server-side state transitions.
- [ ] **APPROVE-02**: Approval records capture approver identity, timestamp, reason, exact target scope, action version, and expiry.
- [ ] **APPROVE-03**: The platform revalidates permissions, evidence freshness, target state, and action scope before execution.

### Execute and Verify

- [ ] **EXEC-01**: Platform exposes a typed, allowlisted catalog containing one or two low-risk Azure remediation actions and no arbitrary shell or CLI execution.
- [ ] **EXEC-02**: An approver can preview the planned target set, API operations, preconditions, expected effect, and possible collateral impact before approval.
- [ ] **EXEC-03**: Approved actions enforce least privilege, bounded targets, parameter validation, timeouts, idempotency, and explicit preconditions.
- [ ] **EXEC-04**: Execution runs as a durable job with visible queued, running, succeeded, failed, retrying, and cancelled states.
- [ ] **EXEC-05**: The platform performs post-action verification and records actual state, outcome, failure details, and rollback or compensation status when applicable.
- [ ] **EXEC-06**: Retries are bounded, visible, idempotent, and revalidated when target state or approval context changes.

### Pilot Experience

- [ ] **PILOT-01**: Dashboard provides consistent views for situations, evidence, exposure/compliance, vulnerabilities, operational-twin context, recommendations, approvals, and execution history.
- [ ] **PILOT-02**: Pilot demonstrates one incident/change-correlation case, one Defender/Policy exposure case, one vulnerability-prioritization case, and one operational-twin discrepancy case.
- [ ] **PILOT-03**: Operators can replay the evidence snapshot and audit history used for a historical recommendation.
- [ ] **PILOT-04**: Pilot includes failure and stale-source handling for ingestion, authorization, execution, verification, and provider outage scenarios.

## v2 Requirements

Deferred until the core pilot loop is proven.

### Integrations and Scale

- **V2-01**: Deep ITSM, Teams, email, and external notification adapters.
- **V2-02**: Broad Azure resource-action coverage and complex multi-step runbooks.
- **V2-03**: Automated learning or model retraining from approved outcomes.
- **V2-04**: Multi-cloud source and remediation support.
- **V2-05**: Automated policy-exemption creation or mutation.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Fully autonomous production remediation | The pilot requires explicit human approval and accountability. |
| New SIEM, metrics platform, vulnerability database, or ITSM replacement | Azure and enterprise systems remain systems of record; this platform is an evidence-and-decision layer. |
| Uncited LLM root-cause claims | Unsupported explanations are unsafe during operations and security events. |
| Chat-first or arbitrary shell execution | Structured state, scope, approval, and auditability are primary safety controls. |
| Broad platform identity permissions | Least privilege and bounded blast radius are mandatory. |
| Real-time guarantees across every source | Source latency, retention, and outage behavior differ and must be visible. |
| Native mobile application | The controlled pilot is web and API based. |

## User Stories

- As an SRE, I can understand why a situation matters and what changed before deciding how to respond.
- As a platform operator, I can see compliance and exposure findings in resource and service context.
- As a security analyst, I can prioritize vulnerabilities using exploitability, exposure, ownership, and business impact rather than CVE count alone.
- As an approver, I can review a bounded action and its evidence before authorizing it.
- As an auditor, I can reconstruct what the platform observed, recommended, approved, executed, and verified.

## Definition of Done

- The four representative pilot cases complete the detect → explain → recommend → approve → execute → verify loop.
- Every explanation and recommendation is evidence-linked, scope-authorized, and explicit about uncertainty.
- No action executes without a valid approval, bounded action definition, permission check, and audit event.
- Stale, missing, contradictory, failed, and retried states are visible and testable.

## Traceability

Traceability is populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | Phase 1 | Complete |
| FOUND-02 | Phase 1 | Complete |
| FOUND-03 | Phase 1 | Complete |
| FOUND-04 | Phase 1 | Complete |
| FOUND-05 | Phase 1 | Complete |
| DETECT-01 | Phase 1 | Complete |
| DETECT-02 | Phase 1 | Complete |
| DETECT-03 | Phase 2 | Pending |
| DETECT-04 | Phase 2 | Pending |
| DETECT-05 | Phase 2 | Pending |
| DETECT-06 | Phase 2 | Pending |
| DETECT-07 | Phase 2 | Pending |
| RECOMM-01 | Phase 2 | Pending |
| RECOMM-02 | Phase 2 | Pending |
| RECOMM-03 | Phase 2 | Pending |
| APPROVE-01 | Phase 2 | Pending |
| APPROVE-02 | Phase 2 | Pending |
| APPROVE-03 | Phase 2 | Pending |
| EXEC-01 | Phase 3 | Pending |
| EXEC-02 | Phase 3 | Pending |
| EXEC-03 | Phase 3 | Pending |
| EXEC-04 | Phase 3 | Pending |
| EXEC-05 | Phase 3 | Pending |
| EXEC-06 | Phase 3 | Pending |
| PILOT-01 | Phase 4 | Pending |
| PILOT-02 | Phase 4 | Pending |
| PILOT-03 | Phase 4 | Pending |
| PILOT-04 | Phase 5 | Pending |

**Coverage:**

- v1 requirements: 28 total
- Mapped to phases: 28
- Unmapped: 0

---
*Requirements defined: 2026-08-23*
*Last updated: 2026-08-23 after initial definition*
