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

- [x] **EXEC-01**: Platform exposes a typed, allowlisted catalog containing one or two low-risk Azure remediation actions and no arbitrary shell or CLI execution.
- [x] **EXEC-02**: An approver can preview the planned target set, API operations, preconditions, expected effect, and possible collateral impact before approval.
- [x] **EXEC-03**: Approved actions enforce least privilege, bounded targets, parameter validation, timeouts, idempotency, and explicit preconditions.
- [x] **EXEC-04**: Execution runs as a durable job with visible queued, running, succeeded, failed, retrying, and cancelled states.
- [x] **EXEC-05**: The platform performs post-action verification and records actual state, outcome, failure details, and rollback or compensation status when applicable.
- [x] **EXEC-06**: Retries are bounded, visible, idempotent, and revalidated when target state or approval context changes.

### Pilot Experience

- [ ] **PILOT-01**: Dashboard provides consistent views for situations, evidence, exposure/compliance, vulnerabilities, operational-twin context, recommendations, approvals, and execution history.
- [x] **PILOT-02**: Pilot demonstrates one incident/change-correlation case, one Defender/Policy exposure case, one vulnerability-prioritization case, and one operational-twin discrepancy case.
- [x] **PILOT-03**: Operators can replay the evidence snapshot and audit history used for a historical recommendation.
- [x] **PILOT-04**: Pilot includes failure and stale-source handling for ingestion, authorization, execution, verification, and provider outage scenarios.

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
- [x] **MED-02**: Expected Gold topology, assessment, and operational-context outputs are live and verified or explicitly retired through a versioned compatibility disposition.
- [x] **MED-03**: Every governed Bronze, Silver, Gold, and metadata product exposes configurable freshness objectives, source status, quality, row-count, lineage, and last-success evidence.
- [x] **MED-04**: High-value Silver operational datasets declared by the platform are populated or explicitly dispositioned, including security, incident, change, configuration, policy, predictive, and remediation domains.
- [x] **MED-05**: Gold exposes curated, versioned consumption contracts and a Direct Lake-compatible semantic serving definition while unified inventory remains the sole resource-identity authority.
- [x] **MED-06**: Graph publication enforces referential integrity and configurable ownership and tagging quality thresholds without inventing unsupported relationships.
- [x] **MED-07**: Cost, compliance, patch, change, incident, and lifecycle analytics retain governed historical facts under explicit retention contracts.
- [x] **MED-08**: The Fabric Data Agent is grounded only in curated Gold products and is evaluated reproducibly for groundedness, precision, freshness, citations, and safe degradation.
- [x] **MED-09**: Generated ontology projections are governed by a publication manifest, lifecycle status, and consumer-facing abstraction that prevents direct dependency on unstable physical tables.
- [x] **MED-10**: Fabric data access, lineage, capacity health, and Delta maintenance controls are implemented with least privilege and are visible through scope-enforced API and web surfaces.

### Operations Copilot Orchestration

- [ ] **COP-01**: Operations Copilot uses one scope-enforced orchestration contract for standalone, contextual drawer, investigation workspace, and multi-agent requests, with model-planned specialist delegation validated against deterministic allowlists and a safe deterministic fallback.
- [ ] **COP-02**: Every operator-facing page with actionable domain evidence exposes a consistent contextual Copilot entry point through a typed page-adapter registry that binds page kind, filters, selected entities, starter questions, freshness, pagination coverage, and evidence.
- [ ] **COP-03**: Specialist definitions, prompts, tool grants, page mappings, deployment metadata, and UI catalog are generated or validated from one versioned contract; existing agent gaps are closed and inventory/data-health, identity, FinOps, and resource-health domains have bounded specialists.
- [ ] **COP-04**: Context snapshot v2 deduplicates and prioritizes evidence, preserves canonical Azure and non-Azure entity identities, represents visible-versus-total result coverage, propagates freshness and uncertainty, and fails closed when evidence is insufficient.
- [ ] **COP-05**: Operations Copilot preserves an authorized investigation thread across page transitions, invokes executive synthesis over cited specialist outputs, exposes delegation/evidence/latency telemetry, and passes representative per-page and cross-domain evaluation cases.

### Network Topology Integrity and Scale

- [ ] **TOPO-01**: Every topology, gap, and rule-finding response enforces the effective subscription/resource scope across all resource and relationship collections, including private-link resources and semantic relationships, without disclosing or fabricating out-of-scope findings.
- [ ] **TOPO-02**: Every in-scope private-link candidate and every resource referenced by a topology finding is represented by a stable, de-duplicated topology node, including Microsoft Fabric capacities and Azure AI Foundry accounts.
- [ ] **TOPO-03**: Topology and finding APIs expose honest totals, truncation, pagination, and level-of-detail contracts so enterprise estates remain usable and no badge, metric, drawer, agent, or export silently implies complete coverage from a bounded result.
- [ ] **TOPO-04**: Design-policy mutations invalidate derived topology analysis, refresh gaps/findings/badges without a page reload, and allow operators to preview, validate, save, and diagnose declarative custom rules through the web UI.
- [ ] **TOPO-05**: Relationship normalization and projection are case-stable and observable, with dropped-edge diagnostics, snapshot freshness, DNS/private-endpoint/subnet integrity, actual flow-log provenance, and direct regression coverage of the scoped topology seam.

### Autonomous Ontology Discovery

- [ ] **AUTO-ONT-01**: A durable, browser-independent scheduler discovers due connection work, prevents concurrent publication for the same scope, resumes safely after restart, and exposes bounded retry, timeout, cancellation, and run-now controls.
- [ ] **AUTO-ONT-02**: Incremental discovery identifies added, changed, retired, unresolved, and stale ontology inputs from authoritative inventory and operational evidence, while scheduled full reconciliation detects drift.
- [ ] **AUTO-ONT-03**: A versioned Microsoft Foundry ontology agent receives only scope-filtered read-only evidence and the approved ontology contract, and returns structured, cited relationship proposals without direct authoritative Fabric write access.
- [ ] **AUTO-ONT-04**: Relationship proposals have deterministic identity, provenance, confidence, evidence, lifecycle, and review state; promotion enforces known endpoints, approved predicates and type pairs, scope, contradiction checks, and explicit human-review or allowlisted auto-accept policy.
- [ ] **AUTO-ONT-05**: The ontology publisher uses a dedicated least-privilege identity, fenced single-writer/version preconditions, fail-closed validation, immutable generation lineage, and atomic promotion with rollback to a prior valid generation.
- [ ] **AUTO-ONT-06**: Pending edges, run checkpoints, leases, proposal decisions, publication attempts, failures, and ontology quality metrics persist across restarts and remain visible through scope-enforced operational APIs and UI.
- [ ] **AUTO-ONT-07**: Offline and deployed evaluations enforce tenant isolation, prompt-injection resistance, relationship precision and recall, citation and freshness requirements, idempotency, bounded cost and latency, failure recovery, and audit completeness.

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
| EXEC-01 | Phase 3 | Complete |
| EXEC-02 | Phase 3 | Complete |
| EXEC-03 | Phase 3 | Complete |
| EXEC-04 | Phase 3 | Complete |
| EXEC-05 | Phase 3 | Complete |
| EXEC-06 | Phase 3 | Complete |
| PILOT-01 | Phase 4 | Pending |
| PILOT-02 | Phase 4 | Complete |
| PILOT-03 | Phase 4 | Complete |
| PILOT-04 | Phase 5 | Complete |
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
| MED-02 | Phase 10 | Complete |
| MED-03 | Phase 10 | Complete |
| MED-04 | Phase 10 | Complete |
| MED-05 | Phase 10 | Complete |
| MED-06 | Phase 10 | Complete |
| MED-07 | Phase 10 | Complete |
| MED-08 | Phase 10 | Complete |
| MED-09 | Phase 10 | Complete |
| MED-10 | Phase 10 | Complete |
| AUTO-ONT-01 | Phase 13 | Pending |
| AUTO-ONT-02 | Phase 13 | Pending |
| AUTO-ONT-03 | Phase 13 | Pending |
| AUTO-ONT-04 | Phase 13 | Pending |
| AUTO-ONT-05 | Phase 13 | Pending |
| AUTO-ONT-06 | Phase 13 | Pending |
| AUTO-ONT-07 | Phase 13 | Pending |

**Coverage:**

- v1 requirements: 51 total
- Mapped to phases: 51
- Unmapped: 0

---
*Requirements defined: 2026-08-23*
*Last updated: 2026-09-04 for Phase 13 autonomous ontology discovery*
