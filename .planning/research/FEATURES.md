# Feature Landscape

**Domain:** Azure SRE, platform, and security operations workbench  
**Researched:** 2026-08-23  
**Scope:** Pilot workflow: detect → explain with evidence → recommend → human-approved execution, across incidents, exposure, compliance, vulnerabilities, and the operational twin.

## Product Position

Azure already has strong systems of record: Azure Monitor and Service Health for telemetry and platform signals, Defender for Cloud for posture and workload security, Sentinel for security incidents and playbooks, Azure Policy for compliance evaluation/remediation, and Resource Graph plus Activity Log for inventory and control-plane evidence. The pilot should therefore be an **evidence-and-decision layer across those systems**, not another monitoring portal, SIEM, vulnerability scanner, or ITSM replacement.

The existing repository is unusually well positioned for this boundary: ARG ingestion, OneLake/Delta persistence, Fabric Ontology, semantic/evidence-backed queries, domain intelligence, Entra/RBAC, and a Next.js workbench already exist. The missing product capability is a durable, cross-domain case and action lifecycle that makes source freshness, provenance, confidence, ownership, approval, and execution state first-class.

Research confidence is **MEDIUM** for Microsoft product capabilities (cross-checked against official documentation URLs below) and **LOW** for broad cross-vendor SRE product-pattern claims because web-search tooling was unavailable. Feature recommendations are consequently grounded primarily in the project context and official Azure capabilities.

## Table Stakes

Features users expect. Missing = product feels incomplete.

| Feature | Why Expected | Complexity | Notes / Dependencies |
|---------|--------------|------------|----------------------|
| Unified situation/investigation record | Operators need one place to work an incident, exposure, compliance finding, vulnerability, or twin discrepancy | High | Core domain model; depends on canonical entity IDs, scope, lifecycle, evidence references, and durable job/state storage |
| Multi-source detection intake | A platform spanning SRE, platform, and security must ingest signals rather than require manual copying | High | Start with existing ARG/Activity Log, Azure Monitor/Service Health, Defender, Policy, and vulnerability feeds; connectors need watermarks, retries, freshness, and deduplication |
| Severity, priority, and impact assessment | Teams need triage order and an explanation of why something matters | Medium | Combine source severity with affected-resource criticality, blast radius, exploitability, compliance policy, and confidence; avoid pretending the score is authoritative |
| Evidence-backed explanation | Every claim must be inspectable by an operator | High | Evidence cards should include source, timestamp, query/link, scope, provenance, freshness, quality, and contradictory/missing evidence; depends on semantic/evidence services |
| Resource, service, and ownership context | Findings without an owner or business impact do not move to resolution | High | Operational twin must link resources, dependencies, environments, services, subscriptions, teams, and business criticality; depends on ontology stewardship and scope filtering |
| Change correlation | Recent deployments/configuration/control-plane changes are a standard incident investigation path | High | Correlate Activity Log, resource changes, deployment metadata, and incident time windows; freshness and clock skew must be visible |
| Exposure and compliance views | Security/platform users expect posture, policy state, exemptions, and remediation status | Medium | Use Defender for Cloud and Azure Policy as source systems; preserve exemptions and policy versions rather than flattening findings |
| Vulnerability prioritization | CVE count alone is not actionable | High | Existing NVD/EPSS/CISA/MSRC enrichment should be joined to affected assets, exposure, exploit status, ownership, and compensating controls; depends on identity normalization and feed freshness |
| Recommended next action with rationale | Detection alone does not deliver operational value | High | Recommendation must state objective, target, expected effect, prerequisites, risk, evidence, confidence, and rollback/verification plan |
| Human approval workflow | Explicit approval is a stated pilot safety requirement and a normal control for production changes | High | Need proposed/approved/rejected/expired/executing/succeeded/failed/rolled-back states, approver identity, timestamp, reason, and approval scope; must not be inferred from UI visibility |
| Bounded execution | Approved actions still need least privilege and blast-radius controls | High | Action catalog, allowlists, target scope, parameter validation, dry-run, preconditions, timeout, idempotency, and post-action verification; depends on RBAC/managed identity and durable jobs |
| Audit history | Security and operations teams need to reconstruct what was observed, recommended, approved, and changed | High | Append-only event trail with correlation ID and source/evidence hashes; separate platform audit from source-of-record ticket/change history |
| Stale/degraded-state indication | Operational data is inherently delayed or partially unavailable | Medium | Show per-source freshness, last successful ingestion, unavailable providers, and evidence quality; never present a stale twin as current truth |
| Search, filtering, and cross-domain navigation | Operators must move from finding to affected resource, service, vulnerability, policy, incident, and action | Medium | Existing semantic/hybrid/live query foundation; enforce tenant/subscription/business-service row filtering at every response boundary |
| Notifications and handoff | Approval, ownership, failure, and escalation need to leave the screen | Medium | Email/Teams/ITSM integration can be a later adapter; MVP can provide in-product state and exportable audit record |
| Failure recovery and retry visibility | Long-running sync and remediation cannot be opaque request/response calls | High | Existing code map identifies missing durable job model and process-local refresh; required before reliable execution at more than one replica |

## Differentiators

Features that set product apart. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes / Dependencies |
|---------|-------------------|------------|----------------------|
| One evidence graph across incidents, exposure, compliance, vulnerabilities, and twin | Turns disconnected portal findings into a shared explanation of cause, impact, and related risk | High | Leverages Fabric Ontology and semantic graph; requires canonical IDs, temporal edges, provenance, and conflict handling |
| Explainable blast-radius analysis | Shows which services, dependencies, environments, and business capabilities could be affected | High | Depends on operational twin quality, dependency discovery, ownership, and graph traversal limits; present confidence and unknown edges |
| Evidence-weighted recommendation ranking | Prioritizes actions using actual asset criticality, exploitability, policy urgency, observed change, and confidence | High | Must be deterministic/auditable enough to inspect; model-generated narrative may assist but cannot be the sole decision basis |
| Cross-domain “why now?” narrative | Correlates a new incident with change, vulnerability, compliance drift, platform health, or dependency degradation | High | Requires aligned timestamps and freshness; should cite each causal hypothesis and show alternatives |
| Safe action preview / counterfactual | Lets an approver see target set, planned API calls, expected policy effect, and possible collateral impact before approval | High | Requires dry-run support or simulation per action; no preview should be marketed as a guarantee |
| Recommendation-to-runbook continuity | Preserves evidence and rationale from detection through the exact approved runbook execution | High | Use versioned action definitions and runbook references; avoid copying mutable instructions into unversioned prompts |
| Twin health and evidence-quality scoring | Makes uncertainty in the operational model visible instead of hiding it behind a graph | Medium | Score freshness, completeness, reconciliation, source agreement, and ownership coverage; depends on existing quality reports |
| “No safe action” outcome | A trustworthy assistant can recommend investigation/escalation rather than force automation | Low | Essential safety differentiator; include missing permissions, stale evidence, ambiguity, and human escalation reason |
| Learning from approved outcomes | Improves future ranking and runbook selection using successful/failed/rolled-back actions | High | Defer automated model retraining; first capture structured outcome labels and post-action verification |
| Scope-aware executive and operator views | Same governed evidence can serve a service owner, security analyst, and executive without leaking unrelated estate data | Medium | Depends on Entra/RBAC plus field/row-level projection tests; do not rely only on frontend hiding |
| Replayable investigations | Reconstructs the evidence snapshot used for a historical recommendation | High | Needs immutable source generations, query/version metadata, and retention policy; aligns with existing generation-based storage |

## Anti-Features

Features to explicitly NOT build in the pilot.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Fully autonomous production remediation | Violates the explicit human-approval safety boundary and makes accountability ambiguous | Require named approval, bounded action policy, expiry, audit, and verification |
| New SIEM, metrics platform, or vulnerability database | Duplicates Azure/Sentinel/Defender/ARG systems of record and creates freshness/conflict problems | Materialize governed projections and link back to authoritative sources |
| Generic ITSM/project-management replacement | Expands scope beyond the pilot and competes with enterprise systems of record | Provide a focused situation/action record and adapters or deep links to existing systems later |
| Uncited LLM root-cause claims | Plausible prose without evidence is dangerous during incidents and security events | Ground every explanation in retrieved evidence, show uncertainty and alternatives, and permit “insufficient evidence” |
| Chat-first product surface | Chat can obscure state, approvals, target scope, and auditability | Make structured situation, evidence, recommendation, and approval views primary; use chat as a constrained assistant |
| Arbitrary shell/CLI execution | Makes target and privilege boundaries difficult to review or constrain | Use a typed allowlisted action catalog backed by Automation/Logic Apps or approved APIs |
| Broad write permissions for the platform identity | Increases blast radius and turns a workbench compromise into estate compromise | Separate read, propose, approve, and execute permissions; use managed identities and least privilege |
| Real-time guarantee across every source | Azure services and external feeds have different latency, retention, and outage behavior | Show per-source freshness and degraded status; support refresh/reconcile actions |
| Multi-cloud abstraction in the pilot | Dilutes Azure integration depth and ontology quality | Keep Azure-native contracts; design ports only where an actual later source requires them |
| Unbounded graph traversal or full-estate AI context | Increases latency, cost, and cross-scope data leakage risk | Apply query budgets, explicit scope, bounded neighborhoods, field minimization, and evidence limits |
| Automated policy-exemption creation | Exemptions are governance decisions and can conceal risk | Surface exemption state and recommend review; require separate governed approval for any exemption change |
| Silent remediation retries | Repeated writes can worsen an incident or violate change controls | Make retries idempotent, bounded, visible, and subject to revalidation/approval when the target state changes |

## Feature Dependencies

```text
Canonical resource/service/identity model
  → operational twin and ownership
  → cross-domain evidence links
  → situation/investigation record
  → explanation and blast-radius analysis
  → recommendation ranking
  → approval state machine
  → bounded action catalog
  → durable execution jobs
  → verification, audit, and outcome learning

Source connectors + watermarks/freshness
  → reliable detection
  → evidence quality and stale-state handling
  → trustworthy explanations/recommendations

Entra authentication + row/field scope projection
  → every read view
  → evidence retrieval
  → recommendation visibility
  → approval eligibility
  → execution target authorization

Action catalog + preconditions + dry-run
  → human approval
  → Automation/Logic Apps/API execution
  → post-action verification and rollback/compensation
```

## MVP Recommendation

Prioritize:

1. **A durable, cross-domain situation record** with lifecycle, ownership, severity, scope, and links to incidents, exposure, compliance, vulnerabilities, and twin entities.
2. **Evidence-backed investigation** using existing ARG/OneLake/Fabric/semantic foundations, with source provenance, timestamps, freshness, quality, contradictory evidence, and bounded graph context.
3. **Actionable recommendations** that include target, rationale, confidence, prerequisites, risk, and a proposed verification plan.
4. **Explicit approval and audit state machine** with Entra identity, approval expiry, reason, immutable history, and separation of duties where configured.
5. **One or two low-risk, allowlisted execution actions** using dry-run, preconditions, idempotency, bounded scope, durable job progress, and post-action verification.
6. **Pilot domain coverage** through representative slices: one incident/change correlation, one Defender/Policy exposure, one vulnerability prioritization case, and one operational-twin discrepancy.

Defer: broad ITSM integration, automated learning/retraining, arbitrary runbooks, multi-cloud support, policy-exemption mutation, fully autonomous response, and every possible Azure resource action. These add risk or integration breadth before the core value loop is proven.

## Complexity and Delivery Ordering

1. **Foundations — High:** canonical IDs, situation/action schemas, evidence references, freshness/quality contracts, durable job and audit events. This is prerequisite work, not visible polish.
2. **Detect and explain — High:** integrate existing domain engines into one situation view; add cross-domain linking, timeline/change correlation, ownership, and evidence rendering.
3. **Recommend — High:** deterministic prioritization plus grounded narrative; make confidence, alternatives, missing evidence, and “no safe action” explicit.
4. **Approve — High:** implement server-side authorization and state transitions before any write adapter; record approver, scope, version, expiry, and revalidation.
5. **Execute and verify — High:** begin with a very small action catalog; use Azure Automation/Logic Apps or typed Azure APIs behind policy; persist progress and verify actual post-state.
6. **Pilot hardening — Medium/High:** failure injection, stale-source scenarios, concurrent workers, token/permission failures, prompt-injection and cross-scope tests, rollback/recovery, and replayable audit.

## Sources

Official Microsoft documentation, verified as reachable on 2026-08-23:

- [Azure Monitor overview](https://learn.microsoft.com/en-us/azure/azure-monitor/overview) — metrics, logs, monitoring, and alerting foundation.
- [Azure Service Health overview](https://learn.microsoft.com/en-us/azure/service-health/overview) — service issues, planned maintenance, and health advisories.
- [Microsoft Defender for Cloud introduction](https://learn.microsoft.com/en-us/azure/defender-for-cloud/defender-for-cloud-introduction) — posture, workload protection, and security recommendations.
- [Microsoft Sentinel overview](https://learn.microsoft.com/en-us/azure/sentinel/overview) — incident investigation and security operations.
- [Microsoft Sentinel automation](https://learn.microsoft.com/en-us/azure/sentinel/automation/automation) — automation rules and playbooks.
- [Azure Policy overview](https://learn.microsoft.com/en-us/azure/governance/policy/overview) — policy evaluation, compliance, and governance.
- [Azure Policy remediation](https://learn.microsoft.com/en-us/azure/governance/policy/how-to/remediate-resources) — managed-identity-backed remediation tasks.
- [Azure Resource Graph overview](https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview) — estate-scale resource queries and inventory.
- [Azure Activity Log](https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/activity-log) — subscription control-plane evidence and export.
- [Azure Automation overview](https://learn.microsoft.com/en-us/azure/automation/overview) — runbook execution primitive.
- [Azure Logic Apps overview](https://learn.microsoft.com/en-us/azure/logic-apps/logic-apps-overview) — workflow and integration execution primitive.
- [Azure RBAC overview](https://learn.microsoft.com/en-us/azure/role-based-access-control/overview) — least-privilege authorization model.

**Repository sources consulted:** `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/INTEGRATIONS.md`, `.planning/codebase/CONCERNS.md`, and `.planning/codebase/STACK.md`. External ecosystem-pattern findings are LOW confidence where not directly supported by an official product source.
