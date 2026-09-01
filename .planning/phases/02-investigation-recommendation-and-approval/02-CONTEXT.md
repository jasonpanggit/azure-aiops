# Phase 2: Investigation, Recommendation, and Approval - Context

**Gathered:** 2026-09-01
**Status:** Ready for planning
**Mode:** Autonomous recommendations accepted by operator

<domain>
## Phase Boundary

Turn ingested Microsoft Defender insights and the semantic business context into a unified, evidence-backed decision-support workflow. The objective is not to remediate findings for their own sake: the platform must explain business impact, urgency, trade-offs, and whether action should happen immediately, be delayed, or be marked not applicable. This phase may generate plans and record durable human approval decisions, but it must not execute Azure changes. Safe execution remains Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Defender triage
- Add Defender assessments, active alerts, attack paths, vulnerability findings, and secure-score controls to the remediation backlog.
- Correlate related Defender records by canonical Azure resource, business service, and likely shared weakness so duplicate findings become one reviewable remediation case.
- Preserve source identifiers, observation timestamps, freshness, availability, and evidence provenance on every candidate.
- Rank candidates using evidenced business impact first, then severity, active alert/exploit evidence, attack-path position, reachability, asset criticality, finding age, secure-score impact, and evidence completeness.

### Business decision intelligence
- Every candidate must join technical evidence to the semantic graph's applications, business services, environments, owners, dependencies, criticality, customer/SLA exposure, and blast radius where those facts exist.
- Recommendations must explain the business consequence of acting and not acting, including service risk, user/customer impact, operational continuity, compliance exposure, change risk, downtime, effort, and opportunity cost.
- The supported dispositions are `act_now`, `schedule`, `defer`, `not_applicable`, and `escalate`; a recommendation to make no change is a valid and valuable outcome.
- Urgency must be reason-coded from evidence: immediate action requires an active or imminent business-impact path; scheduling requires bounded risk with an appropriate maintenance window; deferral requires low current exposure or higher change risk; not-applicable requires evidence that the finding does not affect the scoped service/resource.
- Unknown business mappings or contradictory evidence must reduce confidence and produce an explicit mapping/review requirement rather than defaulting to technical severity.
- The page must make the recommendation rationale inspectable so the user, not the agent, decides what action to take.

### Recommendation and planning
- Match Defender evidence only to typed entries in the governed remediation action catalog; Defender prose may inform rationale but must not become executable instructions by itself.
- Show which alerts, assessments, CVEs, attack paths, and secure-score controls each option addresses.
- Compare at least the recommended action, delay/defer, and no-change/not-applicable alternatives when evidence permits, with explicit pros, cons, residual risk, effort, downtime, reversibility, and business impact.
- Generate plans with objective, scope, exact targets, prerequisites, dependency/blast-radius analysis, business impact, urgency rationale, expected risk reduction, secure-score improvement, rollback, validation, approvals, and uncertainty.
- Keep observed facts, derived inference, and unknowns visibly distinct; return an explicit defer, not-applicable, no-safe-action, or escalation result when that is the evidence-backed choice.

### Agent behavior
- Extend the Remediation specialist with governed Defender evidence and remediation planning tools.
- The agent may triage, correlate, compare business and technical options, and generate approval-ready plans, but it may not optimize for closure count, invent actions, or bypass scope and evidence contracts.
- Operations Copilot remains the shared orchestrator and delegates Defender remediation questions to the relevant Vulnerability, Network, Governance, Incident, Patch, and Remediation specialists.
- All material agent claims must cite source records and expose freshness, confidence, uncertainty, pros, cons, urgency reasoning, and the next safe check.

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
- Present a business-impact decision matrix rather than prioritizing raw finding closure.
- Prioritize actions that protect critical services or break evidenced high-impact attack paths; consolidating many findings is secondary.
- Show "Why now?", "Why later?", "Why not applicable?", "Pros", "Cons", and "Cost of inaction" for each recommendation.
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
