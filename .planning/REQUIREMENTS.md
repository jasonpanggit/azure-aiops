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

### Software and OS Inventory Visibility

- [x] **INV-01**: Platform ingests native Azure VM and Arc-enabled server OS observations from Azure Resource Graph and installed-software observations from the Log Analytics ConfigurationData table, preserving source-specific status, timestamps, and provenance.
- [x] **INV-02**: Platform normalizes and groups OS identity and current software name/version identity, preserves raw values and exact machine joins, and supports exact general-purpose software/version lookup without incident-casework semantics.
- [x] **INV-03**: Platform uses a curated request-time OS lifecycle catalog, presents all cited candidates from the required resolution sources for unmapped versions, and persists only explicit operator-confirmed or manually entered dates with revision protection.
- [x] **INV-04**: Platform provides a short risk narrative grounded in authorized inventory aggregates and visibly falls back to cited deterministic facts when AI narration is unavailable.
- [x] **INV-05**: Inventory collection, grouping, detail, narrative, review, and CSV responses enforce effective scope and expose evidence, freshness, pagination, partial/unavailable status, and source identity.
- [x] **INV-06**: A single Software Inventory page provides OS Inventory and Installed Software tabs with summary cards/charts, required filters, lifecycle badges, machine drill-down, and safe software/version CSV export.
- [x] **INV-07**: Inventory is an independent domain that owns its own acquisition, normalization, retention, source status, and Fabric/OneLake-backed publication, so an inventory refresh does not depend on a semantic-graph sync run.
- [x] **INV-08**: Platform represents every observed Azure resource family, including PaaS, through a common scope-enforced resource observation contract that preserves per-family identity, placement, SKU/tier/runtime, and provenance.
- [x] **INV-09**: Inventory availability and source status are reported per family, so a missing or degraded family degrades that family only and never blanks the inventory capability.
- [x] **INV-10**: Other subsystems, including the semantic graph, consume inventory exclusively through one scope-enforced Fabric-backed inventory contract rather than re-deriving resource lists from raw datasets.
- [x] **INV-11**: Inventory owns the resource identity plane — enumeration, type, placement, tags, containment hierarchy, raw provider properties, and per-family watermarks — losslessly enough that graph construction, relationship modelling, and semantic traversal need no separate resource acquisition path.
- [x] **INV-12**: Inventory is bounded to resource identity and does not absorb assessments about resources; patch, vulnerability, policy, advisor, metric, and health domains retain their own contracts and join to inventory by resource ID.

### Fabric Medallion Capability

- [x] **MED-01**: Fabric ontology publication validates entity and relationship vocabulary before commit, retries transient failures within bounded limits, and exposes terminal failures through durable state and telemetry.
- [ ] **MED-02**: Expected Gold topology, assessment, and operational-context outputs are live and verified or explicitly retired through a versioned compatibility disposition.
- [ ] **MED-03**: Every governed Bronze, Silver, Gold, and metadata product exposes configurable freshness objectives, source status, quality, row-count, lineage, and last-success evidence.
- [ ] **MED-04**: High-value Silver operational datasets declared by the platform are populated or explicitly dispositioned, including security, incident, change, configuration, policy, predictive, and remediation domains.
- [ ] **MED-05**: Gold exposes curated, versioned consumption contracts and a Direct Lake-compatible semantic serving definition while unified inventory remains the sole resource-identity authority.
- [x] **MED-06**: Graph publication enforces referential integrity and configurable ownership and tagging quality thresholds without inventing unsupported relationships.
- [ ] **MED-07**: Cost, compliance, patch, change, incident, and lifecycle analytics retain governed historical facts under explicit retention contracts.
- [ ] **MED-08**: The Fabric Data Agent is grounded only in curated Gold products and is evaluated reproducibly for groundedness, precision, freshness, citations, and safe degradation.
- [ ] **MED-09**: Generated ontology projections are governed by a publication manifest, lifecycle status, and consumer-facing abstraction that prevents direct dependency on unstable physical tables.
- [ ] **MED-10**: Fabric data access, lineage, capacity health, and Delta maintenance controls are implemented with least privilege and are visible through scope-enforced API and web surfaces.

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
| INV-01 | Phase 6 | Complete |
| INV-02 | Phase 6 | Complete |
| INV-03 | Phase 6 | Complete |
| INV-04 | Phase 6 | Complete |
| INV-05 | Phase 6 | Complete |
| INV-06 | Phase 6 | Complete |
| INV-07 | Phase 7, Phase 8 | Complete |
| INV-08 | Phase 7, Phase 8 | Complete |
| INV-09 | Phase 7, Phase 9 | Complete |
| INV-10 | Phase 7, Phase 8, Phase 9 | In Progress |
| INV-11 | Phase 8 | Complete |
| INV-12 | Phase 8 | Complete |
| MED-01 | Phase 10 | Complete |
| MED-02 | Phase 10 | Pending |
| MED-03 | Phase 10 | Pending |
| MED-04 | Phase 10 | Pending |
| MED-05 | Phase 10 | Pending |
| MED-06 | Phase 10 | Complete |
| MED-07 | Phase 10 | Pending |
| MED-08 | Phase 10 | Pending |
| MED-09 | Phase 10 | Pending |
| MED-10 | Phase 10 | Pending |

**Coverage:**

- v1 requirements: 44 total
- Mapped to phases: 44
- Unmapped: 0

---
*Requirements defined: 2026-08-23*
*Last updated: 2026-08-23 after initial definition*
