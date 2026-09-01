# Phase 2: Investigation, Recommendation, and Approval - Context

**Gathered:** 2026-09-01
**Status:** Ready for planning
**Mode:** Autonomous recommendations accepted by operator

<domain>
## Phase Boundary

Turn ingested Microsoft Defender insights into a unified, evidence-backed remediation triage and recommendation workflow. This phase may generate plans and record durable human approval decisions, but it must not execute Azure changes. Safe execution remains Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Defender triage
- Add Defender assessments, active alerts, attack paths, vulnerability findings, and secure-score controls to the remediation backlog.
- Correlate related Defender records by canonical Azure resource, business service, and likely shared weakness so duplicate findings become one reviewable remediation case.
- Preserve source identifiers, observation timestamps, freshness, availability, and evidence provenance on every candidate.
- Rank candidates using severity, active alert/exploit evidence, attack-path position, reachability, asset criticality, finding age, secure-score impact, and evidence completeness.

### Recommendation and planning
- Match Defender evidence only to typed entries in the governed remediation action catalog; Defender prose may inform rationale but must not become executable instructions by itself.
- Show which alerts, assessments, CVEs, attack paths, and secure-score controls each option addresses.
- Generate plans with objective, scope, exact targets, prerequisites, dependency/blast-radius analysis, expected risk reduction, secure-score improvement, rollback, validation, approvals, and uncertainty.
- Keep observed facts, derived inference, and unknowns visibly distinct; return an explicit no-safe-action or escalation result when catalog coverage or evidence is insufficient.

### Agent behavior
- Extend the Remediation specialist with governed Defender evidence and remediation planning tools.
- The agent may triage, correlate, compare options, and generate approval-ready plans, but it may not invent actions or bypass scope and evidence contracts.
- Operations Copilot remains the shared orchestrator and delegates Defender remediation questions to the relevant Vulnerability, Network, Governance, Incident, Patch, and Remediation specialists.
- All material agent claims must cite source records and expose freshness, confidence, uncertainty, and the next safe check.

### Approval and execution boundary
- Preserve explicit human approval for every Azure-changing action; fully autonomous production remediation remains out of scope.
- Approval records remain durable, scoped, versioned, expiring, and server-revalidated.
- Candidate and plan views should prepare Phase 3 preflight inputs, but Phase 2 must keep execution disabled.
- Controlled execution will begin in Phase 3 with only one or two typed, allowlisted, low-risk actions and no arbitrary shell or CLI path.

### Ontology
- Reuse the existing Defender entity vocabulary and resource relationships.
- Add remediation lifecycle links from DefenderAssessment, SecurityAlert, AttackPath, and SecureScoreControl to RemediationPlan.
- Model planned targets, subsequent executions, and verified outcomes without claiming a finding is resolved until post-change evidence confirms it.
- Keep unified inventory as the resource identity authority; Defender and remediation remain assessment and action domains joined by canonical resource ID.

### the agent's Discretion
- Exact component composition, endpoint granularity, scoring weights, and presentation density may follow established repository patterns.
- Select the safest useful action types for Phase 3 based on existing Azure MCP capabilities and least-privilege support.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/onboarding/defender_normalize.py` normalizes assessments, vulnerability findings, alerts, attack paths, and remediation guidance.
- `src/api/routers/vulnerability.py` exposes Defender overview, posture, alerts, attack paths, secure score, and secure-score controls.
- `src/intelligence/remediation/` provides catalog matching, dependency/risk analysis, simulation, rollback planning, approval requirements, durable decisions, and ontology projection.
- `web/src/app/remediation/page.tsx` already provides a unified review backlog, plan detail, CAB evidence pack, Copilot drawer, and durable decision form.

### Established Patterns
- APIs return scoped evidence envelopes with warnings and pagination.
- Recommendation generation is deterministic and catalog-backed; Foundry narration is optional and grounded.
- Operations Copilot uses question-first Microsoft Agent Framework orchestration with deterministic rollback.
- Azure execution is separated from recommendations and requires server-side authorization and approval checks.

### Integration Points
- Add a Defender remediation projection/service between the vulnerability read model and `RemediationOpportunityEngine`.
- Extend operations API contracts and MCP tool registry rather than introducing page-only joins.
- Extend the remediation page service calls, types, filters, metrics, detail view, and Copilot snapshot.
- Extend ontology relationship vocabulary and Fabric dataset projection for plan-to-Defender evidence links.

</code_context>

<specifics>
## Specific Ideas

- Organize the page around Triage, Recommend, Approve, and Remediate/Verify lifecycle stages.
- Prioritize actions that break the most critical attack paths or consolidate many Defender findings.
- Support questions such as "Which single action breaks the most critical attack paths?" and "Did the approved remediation clear the Defender assessment?"
- Phase 2 delivers the first three stages and prepares, but does not activate, the final execution stage.

</specifics>

<deferred>
## Deferred Ideas

- Phase 3: controlled execution, durable jobs, cancellation, retry, rollback/compensation, and post-change verification.
- Phase 4: full Defender/Policy pilot workflow, historical replay, and cross-domain operational twin coverage.
- Phase 5: shadow/canary controls, kill switch, provider outage behavior, stale evidence handling, and operator readiness.
- Broad action coverage, complex multi-step runbooks, and unapproved autonomous production changes remain out of scope.

</deferred>
