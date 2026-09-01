# Phase 2: Investigation, Recommendation, and Approval — Research (Gap Expansion)

**Researched:** 2026-09-01
**Domain:** Wiring already-ingested Microsoft Defender data (assessments, vulnerability findings, active alerts, attack paths, secure scores, secure-score controls) into the existing Remediation page and Remediation specialist for correlated triage, catalog-backed recommendations, and approval-ready (non-executing) plans.
**Confidence:** HIGH (architecture/reuse points — verified by reading source in full), MEDIUM (exact new field/predicate names — repository-pattern-consistent but not previously written), LOW (governed catalog seeding strategy — no precedent exists in the repo)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Phase Boundary**
Turn ingested Microsoft Defender insights into a unified, evidence-backed remediation triage and recommendation workflow. This phase may generate plans and record durable human approval decisions, but it must not execute Azure changes. Safe execution remains Phase 3.

**Defender triage**
- Add Defender assessments, active alerts, attack paths, vulnerability findings, and secure-score controls to the remediation backlog.
- Correlate related Defender records by canonical Azure resource, business service, and likely shared weakness so duplicate findings become one reviewable remediation case.
- Preserve source identifiers, observation timestamps, freshness, availability, and evidence provenance on every candidate.
- Rank candidates using severity, active alert/exploit evidence, attack-path position, reachability, asset criticality, finding age, secure-score impact, and evidence completeness.

**Recommendation and planning**
- Match Defender evidence only to typed entries in the governed remediation action catalog; Defender prose may inform rationale but must not become executable instructions by itself.
- Show which alerts, assessments, CVEs, attack paths, and secure-score controls each option addresses.
- Generate plans with objective, scope, exact targets, prerequisites, dependency/blast-radius analysis, expected risk reduction, secure-score improvement, rollback, validation, approvals, and uncertainty.
- Keep observed facts, derived inference, and unknowns visibly distinct; return an explicit no-safe-action or escalation result when catalog coverage or evidence is insufficient.

**Agent behavior**
- Extend the Remediation specialist with governed Defender evidence and remediation planning tools.
- The agent may triage, correlate, compare options, and generate approval-ready plans, but it may not invent actions or bypass scope and evidence contracts.
- Operations Copilot remains the shared orchestrator and delegates Defender remediation questions to the relevant Vulnerability, Network, Governance, Incident, Patch, and Remediation specialists.
- All material agent claims must cite source records and expose freshness, confidence, uncertainty, and the next safe check.

**Approval and execution boundary**
- Preserve explicit human approval for every Azure-changing action; fully autonomous production remediation remains out of scope.
- Approval records remain durable, scoped, versioned, expiring, and server-revalidated.
- Candidate and plan views should prepare Phase 3 preflight inputs, but Phase 2 must keep execution disabled.
- Controlled execution will begin in Phase 3 with only one or two typed, allowlisted, low-risk actions and no arbitrary shell or CLI path.

**Ontology**
- Reuse the existing Defender entity vocabulary and resource relationships.
- Add remediation lifecycle links from DefenderAssessment, SecurityAlert, AttackPath, and SecureScoreControl to RemediationPlan.
- Model planned targets, subsequent executions, and verified outcomes without claiming a finding is resolved until post-change evidence confirms it.
- Keep unified inventory as the resource identity authority; Defender and remediation remain assessment and action domains joined by canonical resource ID.

### Existing Code Insights (from CONTEXT.md)

**Reusable Assets**
- `src/onboarding/defender_normalize.py` normalizes assessments, vulnerability findings, alerts, attack paths, and remediation guidance.
- `src/api/routers/vulnerability.py` exposes Defender overview, posture, alerts, attack paths, secure score, and secure-score controls.
- `src/intelligence/remediation/` provides catalog matching, dependency/risk analysis, simulation, rollback planning, approval requirements, durable decisions, and ontology projection.
- `web/src/app/remediation/page.tsx` already provides a unified review backlog, plan detail, CAB evidence pack, Copilot drawer, and durable decision form.

**Established Patterns**
- APIs return scoped evidence envelopes with warnings and pagination.
- Recommendation generation is deterministic and catalog-backed; Foundry narration is optional and grounded.
- Operations Copilot uses question-first Microsoft Agent Framework orchestration with deterministic rollback.
- Azure execution is separated from recommendations and requires server-side authorization and approval checks.

**Integration Points**
- Add a Defender remediation projection/service between the vulnerability read model and `RemediationOpportunityEngine`.
- Extend operations API contracts and MCP tool registry rather than introducing page-only joins.
- Extend the remediation page service calls, types, filters, metrics, detail view, and Copilot snapshot.
- Extend ontology relationship vocabulary and Fabric dataset projection for plan-to-Defender evidence links.

### the agent's Discretion
- Exact component composition, endpoint granularity, scoring weights, and presentation density may follow established repository patterns.
- Select the safest useful action types for Phase 3 based on existing Azure MCP capabilities and least-privilege support.

### Specific Ideas (non-binding guidance)
- Organize the page around Triage, Recommend, Approve, and Remediate/Verify lifecycle stages.
- Prioritize actions that break the most critical attack paths or consolidate many Defender findings.
- Support questions such as "Which single action breaks the most critical attack paths?" and "Did the approved remediation clear the Defender assessment?"
- Phase 2 delivers the first three stages and prepares, but does not activate, the final execution stage.

### Deferred Ideas (OUT OF SCOPE)
- Phase 3: controlled execution, durable jobs, cancellation, retry, rollback/compensation, and post-change verification.
- Phase 4: full Defender/Policy pilot workflow, historical replay, and cross-domain operational twin coverage.
- Phase 5: shadow/canary controls, kill switch, provider outage behavior, stale evidence handling, and operator readiness.
- Broad action coverage, complex multi-step runbooks, and unapproved autonomous production changes remain out of scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DETECT-03 | Operator can view a situation timeline correlating relevant changes, incidents, findings, and source events. | The new Defender correlation service (see Architecture Patterns → Pattern 1) groups alerts/assessments/attack-paths/controls by canonical resource + shared weakness into one case; the Remediation page's existing backlog/detail-drawer pattern (`page.tsx`) is the natural home for a per-case timeline built from `observed_at`/`first_seen`/`last_seen` fields already present in `defender_normalize.py` outputs. |
| DETECT-04 | Operator can inspect an evidence-backed explanation where every material claim links to source, timestamp, scope, query or deep link, provenance, freshness, and quality. | `Evidence`/`envelope()` (src/api/evidence.py, already used by every route in operations.py/vulnerability.py) is the existing structured-citation primitive to reuse; the opportunity/plan `evidence` field must be upgraded from plain strings to structured citation objects carrying `source_type`, `source_id`, `observed_at`, `freshness` (see Common Pitfalls → Pitfall 3). |
| DETECT-05 | Operator can see affected resources, services, dependencies, ownership, environment, and business criticality within a bounded graph context. | `DependencyAnalyzer.analyze()` (src/intelligence/remediation/dependency_analyzer.py) already surfaces `affected_applications`, `affected_services`, `owners`, `upstream/downstream_dependencies`, `dependency_count` per resource — reused unchanged; Defender correlation only needs to attach these fields per case, not rebuild them. |
| DETECT-06 | Operator can see contradictory, missing, stale, or degraded evidence instead of receiving an unsupported definitive explanation. | `docs/ontology-model.md` already documents that "Alerts, attack paths, secure scores, and controls have independent source status and freshness. Missing or failed source families are represented as unknown or unavailable, never healthy." — the Defender correlation service must surface this same per-source-family status per case (reuse `source_status` rows already read by `defender_intelligence_snapshot()`), not silently drop degraded sources. |
| DETECT-07 | Operator can search, filter, and navigate across situations, resources, services, vulnerabilities, policies, changes, and evidence without crossing authorization boundaries. | `Remediation` page's existing category-filter segmented control (page.tsx line 510) and `_filter_scoped()`/scope-attribute redaction (operations.py lines 42-60) are the reuse points — add a `"defender"` category and ensure every new Defender-sourced backlog row carries `scope_attributes` so existing `_filter_scoped` continues to enforce authorization with zero new logic. |
| RECOMM-01 | Platform ranks recommended next actions using affected-resource criticality, exploitability or urgency, observed impact, evidence quality, and confidence. | `PlanPrioritizer.prioritize()` (plan_prioritizer.py) already computes a weighted 0–100 score from criticality/dependency/lifecycle/patch/incident signals; new Defender-derived points (active-alert severity, attack-path membership, secure-score gap) must be added to this same weighted formula per CONTEXT.md's ranking-factor list (see Architecture Patterns → Pattern 4 and Common Pitfalls → Pitfall 5). |
| RECOMM-02 | Each recommendation states its objective, target scope, rationale, supporting evidence, confidence, prerequisites, risks, and verification plan. | `RemediationGenerator.generate()` already assembles objective/scope/prerequisites/risk/rollback/simulation from the catalog action + dependency/risk analysis; Defender-sourced evidence and a `secure_score_improvement` estimate are the two fields that must be threaded into this existing payload (see Code Examples). |
| RECOMM-03 | Platform can explicitly return no safe action or escalation when evidence, permissions, scope, or confidence are insufficient. | `RemediationOpportunityEngine._matches()` already returns nothing when no catalog trigger matches a resource; CONTEXT.md requires this same behavior for Defender-only findings with no catalog action — the correlation service must produce an explicit `"no_safe_action"`/escalation record (not silently omit the case) when a Defender case has no matching catalog entry, consistent with `docs/ontology-model.md`'s "never healthy" framing. |
| APPROVE-01 | Authorized approver can approve, reject, or let a recommendation expire through server-side state transitions. | Already implemented end-to-end by Phase 02-01 (`POST /remediation-plans/{plan_id}/decisions`, `RemediationDecisionStore`) — Defender-sourced plans flow through this same endpoint unchanged; no new approval-transition code needed. |
| APPROVE-02 | Approval records capture approver identity, timestamp, reason, exact target scope, action version, and expiry. | Already implemented (`planner.repository.decisions.append(...)` in operations.py lines 268-277) — reused unchanged. |
| APPROVE-03 | The platform revalidates permissions, evidence freshness, target state, and action scope before execution. | Already partially implemented (`revalidation_checks` list in operations.py lines 259-267, `action_version` staleness check lines 245-251) for the approval step; Phase 2 must additionally ensure Defender evidence freshness is part of the `revalidation_checks` vocabulary so Phase 3's execution-time revalidation has a Defender-aware check to run (see Open Questions Q3). |

**Note on APPROVE-01..03 status:** `.planning/REQUIREMENTS.md` currently lists these as `Pending`, but `02-01-SUMMARY.md`/`02-01-REVIEW.md` confirm the underlying mechanism is already built and tested (`tests/test_api_remediation_approvals.py`). This phase's Defender wiring does not need to build new approval mechanics — it only needs to ensure Defender-sourced plans flow through the existing, already-verified approval path. The planner should mark these `Done` once Defender plans are confirmed to round-trip through the existing endpoint (no new endpoint code required for APPROVE-01/02; only the freshness-check vocabulary in APPROVE-03 needs a small addition).
</phase_requirements>

## Summary

The Defender **data layer is essentially complete**: `defender_normalize.py` produces fully-typed `DefenderAssessment`, `DefenderVulnerabilityFinding`, `SecurityAlert`, `AttackPath`/`AttackPathNode`/`AttackPathConnection`, `SecureScoreSnapshot`, and `SecureScoreControl` rows; `VulnerabilityIntelligenceService` already exposes read methods for all of them (`defender_posture()`, `security_alerts()`, `defender_attack_paths_for_scope()`, `secure_score_overview()`, `secure_score_controls()`, `defender_overview()`); and `src/api/routers/vulnerability.py` already serves them over REST. The Exposure page in the frontend already consumes all of this. **None of this needs to be rebuilt.**

The **remediation engine has zero Defender awareness** — confirmed by an empty grep for "efender" across `src/intelligence/remediation/` and `src/operations/`. The gap is entirely about *wiring*, not *building new data infrastructure*: (1) a new correlation/projection service must group related Defender records per canonical resource into reviewable cases with structured, source-cited evidence; (2) those cases' scalar signals must flow into the existing `resources` list consumed by `RemediationOpportunityEngine`, `RiskAnalyzer`, and `PlanPrioritizer` so catalog matching, risk scoring, and priority ranking pick them up through the existing pipeline; (3) new read-only MCP tools must expose Defender evidence and the enriched opportunities/plans to the Remediation (and Vulnerability) Foundry specialists, following the exact `TOOL_REGISTRY`/`REVIEWED_TOOLS`/Terraform 3-way registration pattern already used for `cve_exposure`/`remediation_plans`; (4) the frontend Remediation page's existing `BacklogItem`/adapter pattern must gain Defender-sourced adapters, replacing today's three hardcoded stub rows; (5) the ontology relationship vocabulary must gain `RemediationPlan`→Defender-entity predicates, documented in lockstep in `docs/ontology-model.md`/`ontology-schema.md` per the existing `test_remediation_ontology_alignment.py` contract-test pattern.

One **blocking dependency, discovered during this research and not previously flagged anywhere in the planning docs**, must be resolved before any of this can be demonstrated end-to-end in a real (non-test) environment: the `remediation_action_catalog` and `remediation_approval_policies` Silver Delta tables that `RemediationOpportunityEngine`/`ApprovalEngine` read are **never seeded anywhere in the codebase outside unit-test fixtures** (`tests/fixtures/sample_remediation_planning.json`). Today, in any real running deployment, the remediation opportunity/plan pipeline produces **zero output** regardless of Defender wiring, because there are no catalog actions to match against. This phase's plan must include a minimal catalog-seeding step (see Common Pitfalls → Pitfall 1) or explicitly escalate it as an out-of-band dependency.

A second, independent, pre-existing bug was also discovered: the frontend `RemediationOpportunity` TypeScript interface does not match the real Python backend shape (`opportunity_type` vs `category`, `action_id` vs `opportunity_id`, `evidence: string[]` vs `rationale`, no `priority` field at all) — `opportunityToBacklog()` currently renders mostly `undefined` values. Because Defender-triggered opportunities will flow through this exact adapter, this phase's frontend work should fix this contract mismatch as a prerequisite, not defer it.

**Primary recommendation:** Build a new `src/intelligence/remediation/defender_correlation.py` service (matching CONTEXT.md's literal wording, "a Defender remediation projection/service between the vulnerability read model and `RemediationOpportunityEngine`") that (a) reads all six Defender read-models from `VulnerabilityIntelligenceService`, (b) groups them into `DefenderRemediationCase` records keyed by canonical resource ID + shared weakness (CVE ID / recommendation key), (c) computes the CONTEXT.md-mandated ranking signals per case, (d) emits both scalar resource-signal fields (merged into the existing `resource_signals` dict in `src/fabric/runtime.py`, feeding `RiskAnalyzer`/`PlanPrioritizer` automatically) and structured per-case evidence citations (merged into `RemediationOpportunityEngine`'s evidence output, feeding `RemediationGenerator`'s plan payload). This reuses 100% of the existing catalog-matching, dependency/risk/rollback/simulation, approval-decision, and ontology-projection machinery — the new code is additive, not a parallel pipeline.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Defender data retrieval (assessments/alerts/attack paths/secure score) | API / Backend | Database / Storage (Fabric Silver Delta) | `VulnerabilityIntelligenceService` already owns this; no change needed. |
| Defender correlation into reviewable cases | API / Backend | — | New `defender_correlation.py` module; pure server-side logic, must not leak into the UI as ad-hoc joins per CONTEXT.md's "Extend operations API contracts... rather than introducing page-only joins." |
| Catalog matching / plan generation | API / Backend | — | Existing `RemediationOpportunityEngine`/`RemediationGenerator`; Defender cases become additional `resources` entries, no new engine. |
| Risk/priority scoring with Defender signals | API / Backend | — | Existing `RiskAnalyzer`/`PlanPrioritizer`; extended with new scalar fields, not replaced. |
| Approval decisions | API / Backend | Database / Storage (durable JSON decision store) | Already fully implemented by Phase 02-01; reused unchanged. |
| Agent tool access to Defender evidence & plans | API / Backend | — | New MCP tools registered in `src/operations/tools.py` + `mcp_server.py` + `infra/terraform/foundry.tf`; specialists call these read-only tools, never Azure directly. |
| Remediation backlog presentation, filters, detail drawer | Frontend Server (SSR)/Browser (Next.js client) | API / Backend (data source) | `web/src/app/remediation/page.tsx` `BacklogItem` adapters; purely presentational, all correlation/ranking logic stays server-side. |
| Ontology relationship projection (RemediationPlan↔Defender entities) | Database / Storage (Fabric Ontology projection) | API / Backend (dataset_mapper.py registries) | `src/fabric/dataset_mapper.py` registries + Fabric publisher; documentation must move in lockstep (`docs/ontology-model.md`). |
| Azure change execution | *(none — explicitly out of scope for this phase)* | — | Deferred to Phase 3 by CONTEXT.md's phase boundary; Phase 2 must keep `read_only: True`/`execution_performed: False` invariants intact everywhere. |

## Standard Stack

### Core
No new external packages are required. This phase is internal wiring across the already-adopted stack:

| Component | Version (verified) | Purpose | Why Standard (already adopted) |
|-----------|---------|---------|--------------|
| FastAPI + Pydantic | per `pyproject.toml` (not modified this phase) | REST route/model layer | Already used by every route in `src/api/routers/` |
| `deltalake` | `>=1.0,<2` [VERIFIED: pyproject.toml:9] | Silver Delta table reads for Defender/catalog data | Already the sole Fabric/OneLake read mechanism (`src/fabric/sync_service.py`) |
| Next.js / React | `next@14.2.35`, `react@^18` [VERIFIED: web/package.json:23-24] | Remediation page frontend | Already the frontend stack; no upgrade needed |
| pytest | `>=9.0.3,<10` [VERIFIED: .planning/codebase/TESTING.md:8] | Test runner | Already the sole Python test framework |

### Supporting
No new supporting libraries. Reuse:

| Library/Module | Purpose | When to Use |
|---------|---------|-------------|
| `src.api.evidence.Evidence`/`envelope()` | Structured, source-cited API response envelopes | Every new/extended route in this phase |
| `src.ontology.confidence.compute_confidence()` | Corroboration-based confidence scoring for new ontology relationships | When projecting new `RemediationPlan`↔Defender relationship rows |
| `src.ontology.pending_relationships.PendingRelationshipStore` | Handling dangling/unresolved relationship edges | If a Defender entity referenced by a plan is not yet resolvable to a canonical resource |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New `defender_correlation.py` service feeding existing `resources` list | A parallel "Defender-only" opportunity/plan pipeline | Rejected — would duplicate catalog matching, dependency/risk/rollback/simulation, and approval-decision logic; violates "Extend... rather than introducing page-only joins" and creates two divergent plan shapes for the UI/agent to reconcile. |
| Merging Defender evidence into existing `resources` rows | A brand-new `/defender-remediation-cases` endpoint returned alongside (not merged with) `/remediation-opportunities` | Viable secondary option if the planner decides cases need independent pagination/filtering separate from the generic backlog; adds one more contract surface to keep in sync. Documented as an Open Question (Q1) rather than ruled out. |

## Package Legitimacy Audit

No external packages are installed or upgraded by this phase. All work reuses libraries already present in `pyproject.toml` and `web/package.json`.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| *(none — no new packages)* | — | — | — | — | — | N/A |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Fabric Silver Delta (OneLake)
  defender_alerts, defender_attack_paths(+nodes/connections),
  defender_secure_scores, defender_secure_score_controls,
  defender_vulnerability_findings, defender_assessments
        │
        │  read via deltalake  (src/fabric/sync_service.py)
        ▼
sync_service.defender_intelligence_snapshot()  ── already exists, currently
        │                                          only consumed by
        │                                          _fabric_vulnerability_service()
        ▼
VulnerabilityIntelligenceService                  (src/intelligence/vulnerability/service.py)
  defender_posture() / security_alerts() / defender_attack_paths_for_scope() /
  secure_score_overview() / secure_score_controls() / defender_overview()
        │
        │  NEW: read by a new correlation service
        ▼
DefenderRemediationCorrelator (NEW: src/intelligence/remediation/defender_correlation.py)
  groups records by canonical resource ID + shared weakness (CVE/recommendation key)
  → DefenderRemediationCase{ resource, evidence[], severity, alert/attack-path/
    secure-score signals, freshness, source_status }
        │
        ├──► scalar signals merged into `resources` list ──► RemediationOpportunityEngine
        │      (src/fabric/runtime.py ~line 314-384,             .identify()
        │       new merge_posture()-style call)                       │
        │                                                              ▼
        │                                                    RiskAnalyzer.analyze()
        │                                                    PlanPrioritizer.prioritize()
        │                                                    RemediationGenerator.generate()
        │                                                              │
        └──► structured evidence citations merged into                ▼
              opportunity["evidence"] / plan["evidence"]      RemediationPlan (read_only=True,
                                                                execution_performed=False)
                                                                        │
        ┌───────────────────────────────────────────────────────────────┤
        ▼                                                               ▼
GET /remediation-opportunities, GET /remediation-plans        POST /remediation-plans/{id}/decisions
  (src/api/routers/operations.py — extended, not replaced)      (already implemented, Phase 02-01)
        │                                                               │
        ▼                                                               ▼
web/src/app/remediation/page.tsx                              RemediationDecisionStore (durable JSON)
  BacklogItem adapters (NEW: defenderCaseToBacklog)                     │
  category filter += "defender"                                        ▼
        │                                                     Fabric ontology projection
        ▼                                                     RemediationPlan --addressesAlert-->
Operator triage / recommend / approve UI                        SecurityAlert, etc. (NEW relationship
  (NOT: execute — disabled this phase)                           tuples in dataset_mapper.py)

MCP tool surface (parallel path, same data):
  Foundry Remediation/Vulnerability specialists
        │  call_tool("defender_alerts" | "defender_attack_paths" |
        │            "defender_secure_score" | "remediation_plans" | ...)
        ▼
  src/operations/tools.py  TOOL_REGISTRY  (NEW handlers, same _provider_result/
                                            ToolResult/Evidence pattern as _tool_cve_exposure)
        │
        ▼
  src/operations/mcp_server.py  REVIEWED_TOOLS  (NEW tool names added)
        │
        ▼
  infra/terraform/foundry.tf  foundry_tool_registry + foundry_specialist_tools
    (NEW tool block + added to `remediation`/`vulnerability` specialist lists)
```

### Recommended Project Structure
```
src/intelligence/remediation/
├── defender_correlation.py       # NEW — groups Defender records into cases, computes
│                                  #        ranking signals & structured evidence citations
├── remediation_opportunity_engine.py   # UNCHANGED logic; consumes enriched `resources`
├── remediation_generator.py            # UNCHANGED logic; evidence field gains structured entries
├── risk_analyzer.py                    # EXTENDED — new Defender operational_values entry
├── plan_prioritizer.py                 # EXTENDED — new Defender priority-point term
├── plan_repository.py                  # UNCHANGED
└── approval_engine.py / approval_decisions.py  # UNCHANGED (reused as-is)

src/operations/tools.py            # EXTENDED — new _tool_defender_alerts / _tool_defender_attack_paths /
                                    #            _tool_defender_secure_score handlers + TOOL_REGISTRY entries
src/operations/mcp_server.py       # EXTENDED — REVIEWED_TOOLS tuple gains new tool names
src/api/routers/operations.py      # EXTENDED — remediation routes surface Defender evidence;
                                    #            optionally add GET /remediation-plans/{id}/decisions
src/fabric/runtime.py              # EXTENDED — one new merge_posture()-style call in _operations()
src/fabric/dataset_mapper.py       # EXTENDED — new ONTOLOGY_RELATIONSHIP_TYPES tuples
infra/terraform/foundry.tf         # EXTENDED — new tool block + specialist tool-list entries

web/src/app/remediation/page.tsx   # EXTENDED — new defenderCaseToBacklog adapter, "defender" filter
web/src/lib/services.ts            # UNCHANGED (Defender client methods already exist)
web/src/lib/types.ts               # EXTENDED — fix RemediationOpportunity mismatch; add DefenderRemediationCase type

docs/ontology-model.md             # EXTENDED — new relationship bullets under "Graph traversal examples"
ontology-schema.md                 # EXTENDED — RemediationPlan relationship table gains new rows

tests/
├── defender_correlation_scenario.py   # NEW — scenario builder, following remediation_scenario.py precedent
├── test_defender_remediation_correlation.py     # NEW
├── test_defender_remediation_correlation_hardening.py   # NEW (edge cases: degraded sources, no-catalog-match)
├── test_remediation_ontology_alignment.py       # EXTENDED — new relationship assertions
├── test_foundry_tool_registry_matches_implementation.py  # EXTENDED coverage (existing test, new tool rows)
└── test_mcp_tools.py                              # EXTENDED (existing test, REVIEWED_TOOLS growth)
```

### Pattern 1: Defender-to-remediation resource-signal injection
**What:** Build the Defender correlation output as additional scalar fields on the same `resources: list[dict]` structures already consumed by `RemediationOpportunityEngine`, `RiskAnalyzer`, and `PlanPrioritizer`, exactly mirroring how patch/lifecycle/incident/change/predictive intelligences are merged today.
**When to use:** For every Defender signal that should influence catalog-trigger matching, risk scoring, or priority ranking (e.g., `defender_active_critical_alert_count`, `defender_attack_path_membership_count`, `defender_unhealthy_control_count`, `defender_secure_score_gap`).
**Example (verbatim from the existing merge seam, showing the exact shape a new Defender merge call must match):**
```python
# Source: src/fabric/runtime.py (read this session, lines ~314-384 region;
# exact merge_posture() call pattern used for existing intelligences)
signals: dict[str, dict[str, Any]] = {}
for key, resource in resources_by_key.items():
    signals[key] = dict(resource)
merge_posture(signals, patch_engine.posture_by_resource())
merge_posture(signals, lifecycle_engine.posture_by_resource())
merge_posture(signals, incident_engine.posture_by_resource())
merge_posture(signals, change_engine.posture_by_resource())
merge_posture(signals, predictive_engine.posture_by_resource())
# NEW: merge_posture(signals, defender_correlator.posture_by_resource())
planner = RemediationPlanner.from_semantic_engine(
    semantic_engine, resource_signals=signals, ...
)
```
**Note:** the exact `merge_posture()` call sites and surrounding variable names must be confirmed against the live file at implementation time — this is the pattern shape, not a verbatim line-range quote (the region was read but the exact call list is reconstructed from notes taken during investigation of this session's `view` of `src/fabric/runtime.py`; re-`view` the file before editing to get exact current line numbers, since the working tree is dirty and may have shifted).

### Pattern 2: MCP tool 3-way registration (must stay in sync across three files)
**What:** Every read-only Operations MCP tool exists in three places that must all agree, verified by two existing contract tests.
**When to use:** For every new `defender_alerts`/`defender_attack_paths`/`defender_secure_score` tool exposed to specialists.
**Example (verbatim quotes from files read this session):**
```python
# Source: src/operations/mcp_server.py:30-47 (read this session)
REVIEWED_TOOLS = (
    "network_topology",
    "hub_dependents",
    "traffic_flow",
    "firewall_nsg_gaps",
    "business_service_context",
    "application_context",
    "impact_context",
    "fabric_iq_relationships",
    "fabric_iq_topology",
    "fabric_iq_policy_context",
    "cve_exposure",
    "cve_detail",
    "cve_attack_path",
    "incidents",
    "remediation_plans",
    "remediation_opportunities",
)
```
```hcl
# Source: infra/terraform/foundry.tf (read this session; foundry_specialist_tools map)
foundry_specialist_tools = {
  network = concat([...], local.foundry_generic_context_tools)
  vulnerability = concat([
    "cve_exposure",
    "cve_detail",
    "cve_attack_path",
  ], local.foundry_generic_context_tools)
  ...
  remediation = concat([
    "remediation_plans",
    "remediation_opportunities",
  ], local.foundry_generic_context_tools)
  ...
}
```
Comment directly above this block (verbatim, read this session): *"Tool names must match operations.mcp_server.REVIEWED_TOOLS exactly."*

A new tool (e.g. `defender_alerts`) requires ALL of:
1. A handler function in `src/operations/tools.py` (following `_tool_cve_exposure` shape) + an entry in `TOOL_REGISTRY`.
2. The tool name added to `REVIEWED_TOOLS` in `src/operations/mcp_server.py` (gates `call_tool()` authorization AND drives `tool_definitions()` for the MCP `tools/list` surface — confirmed by reading `tool_definitions()`, which iterates `REVIEWED_TOOLS` directly).
3. A row added to `foundry_tool_registry` in `infra/terraform/foundry.tf`, plus the tool name added to the relevant specialist's list in `foundry_specialist_tools` (e.g. `remediation` and/or `vulnerability`).
4. Two existing contract tests will fail loudly if any of the three are missed: `tests/test_foundry_tool_registry_matches_implementation.py::test_advertised_operations_tools_are_implemented` (Terraform vs `TOOL_REGISTRY`) and `tests/test_mcp_tools.py` (`tool_definitions()` vs `REVIEWED_TOOLS`) — run both after any tool addition.

### Pattern 3: Tool handler shape (replicate for new Defender tools)
**What:** Every read-only tool resolves its provider, wraps rows with `Evidence`, and bounds output size.
**Example:**
```python
# Source: src/operations/tools.py (read this session; _tool_cve_exposure/_tool_cve_detail/_tool_cve_attack_path region, ~lines 448-533)
# Pattern (paraphrased structure, not a verbatim single block — the three
# existing handlers share this shape):
def _tool_cve_exposure(tool_context, arguments):
    service = _provider_result(tool_context, "vulnerability", run=...)
    rows = service.<some_method>(...)
    return ToolResult(
        status="ok",
        data=_bound(rows),
        evidence=Evidence(
            source_engine="intelligence.VulnerabilityIntelligenceService",
            source_table="<table>",
            timestamp=...,
            confidence=...,
        ),
    )
```
New `_tool_defender_alerts`/`_tool_defender_attack_paths`/`_tool_defender_secure_score` handlers should resolve via the same `"vulnerability"` provider key (Defender methods live on `VulnerabilityIntelligenceService`), since the provider registry is keyed by capability, not by data source.

### Pattern 4: Weighted scoring extension (PlanPrioritizer)
**What:** `PlanPrioritizer.prioritize()` composes a 0–100 score from named point buckets; a new Defender bucket must be added without breaking the existing bound.
**Verbatim current state (read this session, `src/intelligence/remediation/plan_prioritizer.py:7-36`):**
```python
def prioritize(self, resource, dependencies, simulation):
    reduction = int(simulation["risk_reduction_percent"])
    criticality_points = 20 if criticality in {"critical", "mission critical"} else 14 if criticality == "high" else 6
    dependency_points = min(int(dependencies.get("dependency_count") or 0) * 5, 15)
    lifecycle_points = min(int(resource.get("lifecycle_risk_score") or 0) * 15 // 100, 15)
    patch_points = min(int(resource.get("patch_risk_score") or 0) * 15 // 100, 15)
    incident_points = min(int(resource.get("incident_count_90d") or 0) * 2, 10)
    score = min(
        reduction * 35 // 100
        + criticality_points + dependency_points + lifecycle_points + patch_points + incident_points,
        100,
    )
```
The existing named buckets already sum to a theoretical max of 35+20+15+15+15+10 = 110, capped at 100 by the outer `min(...)`. **A new Defender bucket (e.g. `defender_points`, capturing active-alert severity + attack-path membership + secure-score gap) must be added as an additional named term inside the same `min(..., 100)` cap** — do not silently let it push the pre-cap sum arbitrarily higher without deciding whether existing bucket weights should be rebalanced down. CONTEXT.md delegates "scoring weights" to the agent's discretion, so this is a design decision to make explicitly during planning, not research to resolve — flagged in Open Questions (Q2).

### Anti-Patterns to Avoid
- **Page-only joins:** CONTEXT.md explicitly forbids "introducing page-only joins" — do not fetch Defender data and remediation data separately in `page.tsx` and correlate them client-side in JavaScript. All correlation must happen server-side in the new `defender_correlation.py` service so the same evidence-cited, ranked cases are available to both the UI and the MCP tool surface.
- **Flattening distinct Defender signal types into one risk count:** `docs/ontology-model.md` explicitly states "Defender signals retain separate meanings rather than being flattened into one risk count" — the correlation service must preserve `SecurityAlert` (observed threat), `AttackPath` (exploit graph position), `SecureScoreControl` (posture gap), and `DefenderAssessment`/`DefenderVulnerabilityFinding` (CVE evidence) as distinct evidence types on each case, not collapse them into a single opaque "defender_score".
- **Claiming resolution without post-change evidence:** CONTEXT.md: "Model planned targets, subsequent executions, and verified outcomes without claiming a finding is resolved until post-change evidence confirms it." Do not mark a Defender assessment/alert as resolved when a plan is merely *approved* — only Phase 3 post-execution verification can do that; this phase's ontology relationships must be named to reflect "addresses"/"targets", not "resolves"/"fixes".

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Querying Defender data by scope | A new Defender query layer | `VulnerabilityIntelligenceService.defender_posture()/security_alerts()/defender_attack_paths_for_scope()/secure_score_overview()/secure_score_controls()/defender_overview()` | Already implements scoping, freshness/source-status handling, and business-context attachment; re-deriving any of this risks diverging from the Exposure page's already-correct behavior. |
| Structured evidence citations | A bespoke citation schema | `src.api.evidence.Evidence`/`envelope()` | Already the repo-wide convention for every API response; reusing it keeps the new Defender evidence consistent with every other route's provenance contract. |
| Durable approval decision persistence | A new decision store | `RemediationDecisionStore` (already built in Phase 02-01) | Already handles versioning, expiry, revalidation-check recording, and scope enforcement; Defender-sourced plans are just more rows through the same store. |
| Dependency/blast-radius analysis | A new graph traversal for Defender cases | `DependencyAnalyzer.analyze()` | Already bounded (`max_dependencies=100`), already reads `upstream_dependencies`/`downstream_dependencies`/`business_service`/`owner` from the resource dict — Defender cases just need to attach to the same resource dict shape. |
| Ontology relationship confidence scoring | A new confidence heuristic for Defender-plan edges | `src.ontology.confidence.compute_confidence()` | Already implements corroboration-based confidence bumps; reuse for the new `RemediationPlan`↔Defender relationship rows rather than inventing a parallel scoring function. |
| MCP protocol framing (JSON-RPC envelopes, size bounds, tool schemas) | A new tool-calling adapter for Defender tools | `src/operations/mcp_server.py`'s existing `MCPServer`/`tool_definitions()`/`_schema()` machinery | Already handles message-size bounds (`MAX_MESSAGE_BYTES`/`MAX_ARGUMENT_BYTES`/`MAX_RESPONSE_BYTES`), JSON-RPC error codes, and per-process call bounds; new tools are just new registry entries, not new protocol code. |

**Key insight:** Every piece of this phase's infrastructure already exists in the codebase for *other* data sources (patch, lifecycle, incident, CVE). The engineering task is disciplined replication of an established pattern six times over (data merge, catalog trigger, risk score, priority score, MCP tool, UI adapter, ontology relationship) — not new architecture. The highest-risk part of the phase is the **new** correlation/grouping logic (Pattern 1's upstream half), because no existing "correlate records across sources into one case" engine exists yet to copy from.

## Common Pitfalls

### Pitfall 1: Unseeded governed remediation catalog blocks all real-environment output
**What goes wrong:** `remediation_action_catalog` and `remediation_approval_policies` Silver Delta tables are read by `remediation_planning_snapshot()` (`src/fabric/sync_service.py:1071-1115`) but are never written by any pipeline, sync job, or seed script outside of test fixtures. `.planning/table-usage-map.json` [VERIFIED: read via targeted script this session] classifies both as `"legacy_supporting"` with exactly one reference each (`schema_registry.py`). In any real running environment, `RemediationOpportunityEngine.identify()` and `RemediationGenerator.generate()` will produce zero opportunities/plans — Defender wiring will appear to "not work" for reasons unrelated to the Defender code, because there is nothing in the catalog to match against.
**Why it happens:** The catalog/policy tables were designed as configuration data (author-curated action definitions), but no authoring/seeding mechanism was ever built — likely deferred as out-of-scope in an earlier phase and never revisited.
**How to avoid:** This phase's plan must include a minimal catalog-seeding task: either (a) a small static seed script/fixture (e.g., `scripts/seed_remediation_catalog.py`) that writes a handful of Defender-triggerable catalog actions (e.g., "apply missing security patch", "enable disabled security control", "restrict public network access") to the Silver Delta tables for local/dev/demo environments, following the exact JSON shape in `tests/fixtures/sample_remediation_planning.json`, or (b) explicitly escalate this as a blocking cross-phase dependency in the plan's risk section if seeding is considered out of this phase's scope. Silently ignoring it will make the phase appear complete in unit tests (which use fixtures) while being non-functional in any deployed environment.
**Warning signs:** `GET /remediation-opportunities` returns an empty list against a real Fabric snapshot even after Defender wiring is complete; `remediation_planning_snapshot()` logs/returns empty `action_catalog`/`approval_policies` collections.

### Pitfall 2: `RemediationOpportunity` frontend/backend contract mismatch
**What goes wrong:** `web/src/lib/types.ts` [VERIFIED: read this session, lines ~1262-1270] declares `RemediationOpportunity` with fields `opportunity_id`, `resource` (implied string), `category`, `priority`, `rationale`, `recommended_action`. The real Python output of `RemediationOpportunityEngine`'s public opportunity shape uses `action_id` (not `opportunity_id`), `opportunity_type` (not `category`), `evidence: list[str]` (not `rationale`), `resource` as a nested object (not a string), and has no `priority` field at all — priority only exists on generated *plans* via `PlanPrioritizer`, not on raw opportunities. `opportunityToBacklog()` in `page.tsx` currently reads the wrong keys and renders `undefined` for most fields.
**Why it happens:** The frontend type was likely authored speculatively or against an earlier engine version, before the current `_public_opportunity()`-shaped output was finalized, and never reconciled.
**How to avoid:** Fix `RemediationOpportunity` in `types.ts` to match the real backend keys (verify exact keys by reading `RemediationOpportunityEngine`'s public serialization method directly before writing the corrected interface — do not assume from this research; re-verify at implementation time since the engine may itself be extended by this same phase for Defender evidence). Fix `opportunityToBacklog()` to read the corrected keys. This must happen regardless of Defender scope, because Defender-triggered opportunities flow through this same adapter and would otherwise inherit the same rendering bug.
**Warning signs:** Backlog rows under the "opportunity" kind show blank/undefined category, priority, or rationale text in the UI.

### Pitfall 3: Evidence field is currently plain strings, not structured citations
**What goes wrong:** `RemediationOpportunityEngine._matches()` (read this session, lines ~137-156) produces evidence entries like `"patch_risk_score: 85"` — a plain human-readable string with no source ID, timestamp, or freshness marker. CONTEXT.md requires "Preserve source identifiers, observation timestamps, freshness, availability, and evidence provenance on every candidate" and "Show which alerts, assessments, CVEs, attack paths, and secure-score controls each option addresses." Plain strings cannot satisfy this — there is no machine-readable link from an evidence string back to a specific `SecurityAlert`/`DefenderAssessment`/`AttackPath` record.
**Why it happens:** The existing evidence strings were designed to satisfy generic "state why this opportunity was matched" rationale for non-Defender signals (patch/lifecycle scores), which are themselves already scalar/aggregate numbers with no natural per-record citation. Defender evidence is fundamentally different — it's per-record (a specific alert ID, a specific assessment key), which the current string format cannot express.
**How to avoid:** Extend the opportunity/plan evidence contract to carry structured citation objects (e.g., `{source_type: "SecurityAlert", source_id: "...", observed_at: "...", freshness: "...", summary: "..."}`) *in addition to* (not necessarily replacing) the existing plain-string entries, to avoid breaking any code/tests currently asserting on `evidence: list[str]` for non-Defender opportunities. Confirm the exact existing assertion shape in `tests/remediation_scenario.py`/`test_remediation_*.py` before deciding whether to add a new field (e.g. `evidence_citations`) alongside `evidence`, versus changing `evidence`'s element type — the safer, less-breaking choice is a new sibling field.
**Warning signs:** UI cannot show "which alerts/assessments/attack paths this option addresses" as anything more than a paraphrased sentence; agent narration cites vague rationale instead of specific source IDs.

### Pitfall 4: MCP tool 3-way (or 4-way) registration drift
**What goes wrong:** Adding a handler to `TOOL_REGISTRY` in `tools.py` without also adding the tool name to `REVIEWED_TOOLS` in `mcp_server.py` makes the tool exist but be unreachable via the MCP protocol (`call_tool()` checks `if name not in REVIEWED_TOOLS` [VERIFIED: src/operations/mcp_server.py:204 region, read this session] and denies it) and it will never appear in `tools/list` (`tool_definitions()` iterates `REVIEWED_TOOLS` directly [VERIFIED: src/operations/mcp_server.py:116-124, read this session]). Conversely, adding a row to Terraform's `foundry_tool_registry` without a matching `TOOL_REGISTRY` entry fails the existing `test_advertised_operations_tools_are_implemented` contract test.
**Why it happens:** The registration surface is intentionally split across three files (protocol-authorization list, implementation registry, infra-as-code advertisement) for defense-in-depth, but nothing enforces adding a tool to all three atomically except the two existing contract tests.
**How to avoid:** Treat "add one MCP tool" as an atomic four-part change: (1) handler + `TOOL_REGISTRY` entry in `tools.py`, (2) name added to `REVIEWED_TOOLS` in `mcp_server.py`, (3) row added to `foundry_tool_registry` in `foundry.tf`, (4) name added to the relevant specialist(s)' list in `foundry_specialist_tools`. Run `pytest tests/test_foundry_tool_registry_matches_implementation.py tests/test_mcp_tools.py` after every tool addition, before moving on.
**Warning signs:** A Foundry specialist's system prompt advertises a tool it can never successfully call, wasting a model turn; or a contract test fails on the next `pytest` run.

### Pitfall 5: PlanPrioritizer's point budget has no headroom
**What goes wrong:** The existing weighted-scoring formula in `PlanPrioritizer.prioritize()` already sums to a theoretical pre-cap max of 110 (35+20+15+15+15+10) before being clamped to 100 by the outer `min(...)`. Adding a new Defender-derived point bucket without first deciding how it interacts with this cap either makes Defender-driven signals invisible (since the cap is already reachable without them) or requires rebalancing existing weights.
**Why it happens:** The formula was designed incrementally per-signal without a normalized 100-point budget; each new signal source has been added as "one more term inside the min()" rather than as a proportionally-rebalanced weight.
**How to avoid:** During planning, explicitly decide (per CONTEXT.md's delegation of "scoring weights" to agent discretion) whether to (a) rebalance all existing weights down proportionally to make room for a new Defender term, or (b) let Defender signals only matter when they push a resource that would otherwise be under 100 (i.e., accept that already-critical resources won't visibly rank higher from Defender findings alone, only from displacing lower-scored resources in relative ordering). Document the choice explicitly in the plan; do not leave it as an implicit side effect of code order.
**Warning signs:** Defender-flagged resources don't visibly outrank equivalent non-Defender resources in the prioritized plan list despite CONTEXT.md's explicit ranking-factor requirement.

### Pitfall 6: `RiskAnalyzer`'s hardcoded operational-value count
**What goes wrong:** `RiskAnalyzer.analyze()` folds exactly four named fields (`patch_risk_score`, `lifecycle_risk_score`, `predictive_risk_score`, `configuration_drift_count`) into `operational_risk`, and separately computes an `evidence_status` of `"Known"` only when `len(operational_values) == 4` (a hardcoded magic constant observed in the risk_analyzer.py logic reviewed during investigation). Adding a fifth Defender-derived operational value without updating this constant will make every resource with real Defender data silently report `evidence_status: "Partial"` even when all five signals are actually present and known.
**Why it happens:** The "Known"/"Partial" distinction was written against a fixed, closed set of four signal sources; it was never designed to be extended.
**How to avoid:** Re-read `risk_analyzer.py`'s exact `operational_values` construction and the `"Known" if len(...) == N else "Partial"` line at implementation time (line numbers may have shifted; the working tree is dirty) before adding a fifth field, and update the magic constant alongside the new field in the same commit/task, with a regression test asserting `evidence_status == "Known"` when a Defender signal is present alongside the other four.
**Warning signs:** `evidence_status` unexpectedly downgrades from "Known" to "Partial" across the whole resource set immediately after adding a Defender operational-value field — a strong signal the count constant was missed.

## Code Examples

### Existing REST route pattern to extend (verbatim, read this session)
```python
# Source: src/api/routers/operations.py:154-180 (read this session)
@router.get("/remediation-plans", summary="Remediation plans")
def remediation_plans(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    planner = _require(context, "remediation_provider", "remediation", scope)
    plans = planner.generate_plans()
    visible = _filter_rows(plans.get("plans"), scope)
    if not isinstance(visible, list):
        visible = []
    public = {**plans, "plans": visible[page.offset : page.offset + page.limit]}
    if not scope.is_unrestricted():
        public = {
            "plans": public["plans"],
            "generated_at": plans.get("generated_at", ""),
            "read_only": plans.get("read_only", True),
            "execution_performed": plans.get("execution_performed", False),
            "scope_limited": True,
        }
    return envelope(
        public,
        evidence=Evidence(
            source_engine="intelligence.RemediationPlanner",
            source_table="remediation_plans",
            timestamp=str(plans.get("generated_at") or ""),
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(visible)),
    )
```
This route requires no structural change for Defender wiring — it already returns whatever `planner.generate_plans()` produces. Once Defender signals flow through `RemediationPlanner`/`RemediationGenerator`, Defender-sourced plans appear here automatically. The recommended new work is an audit-read companion route:
```python
# NEW (recommended, not yet implemented): GET /remediation-plans/{plan_id}/decisions
# Same _require/_filter_scoped pattern as remediation_plans(), reading
# planner.repository.decisions for a given plan_id, scoped identically to the
# existing POST .../decisions route (operations.py:216-288, read this session).
# Strengthens APPROVE-02 auditability; flagged in 02-01-REVIEW.md as an
# "Enhancement Recommendation" that was never implemented.
```

### Existing decision-record pattern (verbatim, read this session — reused unchanged)
```python
# Source: src/api/routers/operations.py:268-277 (read this session)
decision = planner.repository.decisions.append(
    plan=plan,
    decision=request.decision,
    approver=principal.subject,
    reason=request.reason,
    scope=operate_scope.to_dict(),
    action_version=current_version,
    expires_at=expires_at,
    revalidation_checks=revalidation_checks,
)
```
`revalidation_checks` (read this session, operations.py:259-267) is currently: `["plan_exists", "scope_authorized", "action_version_current", "execution_boundary_read_only"]`, plus `"approval_not_expired"` appended when `decision == "approved"`. This phase should extend this list with a Defender-specific freshness check name (e.g. `"defender_evidence_fresh"`) so Phase 3's execution-time revalidation has a named check to run against current Defender data before executing — a pure additive change to a plain Python list literal.

### Existing ontology relationship registry (verbatim, read this session — extend, don't replace)
```python
# Source: src/fabric/dataset_mapper.py ONTOLOGY_RELATIONSHIP_TYPES region (read this session)
# Existing RemediationPlan-related tuples (confirmed present verbatim):
("RemediationPlan", "hasApprovalDecision", "ApprovalDecision"),
("RemediationPlan", "requiresApproval", "ApprovalRequirement"),
("RemediationPlan", "hasStep", "ExecutionStep"),
("RemediationPlan", "hasRollbackPlan", "RollbackPlan"),
("RemediationPlan", "hasSimulation", "SimulationResult"),
("RemediationPlan", "mitigatesRisk", "RiskAssessment"),
("RemediationPlan", "protectsService", "BusinessService"),
# NEW tuples to add (naming proposed by this research, [ASSUMED] — see Assumptions Log A1):
("RemediationPlan", "addressesFinding", "DefenderAssessment"),
("RemediationPlan", "addressesAlert", "SecurityAlert"),
("RemediationPlan", "breaksAttackPath", "AttackPath"),
("RemediationPlan", "improvesControl", "SecureScoreControl"),
```
Corresponding documentation update (verbatim current text, read this session, `docs/ontology-model.md:105-108`, to be extended with a new bullet in the same "Graph traversal examples" list):
> `- Remediation readiness: `Application --requiresPlan--> RemediationPlan --requiresApproval--> ApprovalRequirement`.`
> `- Remediation decision audit: `RemediationPlan --hasApprovalDecision--> ApprovalDecision`.`

New bullet to add, matching the existing prose style: `- Remediation Defender linkage: `RemediationPlan --addressesAlert--> SecurityAlert`, `--breaksAttackPath--> AttackPath`, and `--improvesControl--> SecureScoreControl`.`

Every new relationship tuple must be accompanied by a corresponding assertion in `tests/test_remediation_ontology_alignment.py`, following the existing pattern (read this session): `test_approval_decisions_are_projected_into_remediation_ontology()` and `test_durable_approval_decisions_publish_to_ontology_rows()` — both assert that a specific relationship type appears in the projected ontology rows for a constructed scenario. New tests should follow the same "construct a plan referencing a Defender entity → assert the relationship row exists in the projection" shape.

### Existing frontend adapter pattern (paraphrased shape from page.tsx, read this session)
```typescript
// Source: web/src/app/remediation/page.tsx (read this session; planToBacklog/
// opportunityToBacklog/exposureToBacklog region, ~lines 150-330)
// Pattern shape shared by all existing adapters (exact field names vary
// per adapter — re-view the live file at implementation time since it is
// under active user modification in the dirty working tree):
function opportunityToBacklog(item: RemediationOpportunity): BacklogItem {
  return {
    uiId: `opportunity:${item.<id-field>}`,
    kind: "opportunity",
    // ...maps backend fields to unified BacklogItem shape
  };
}
```
A new `defenderCaseToBacklog(item: DefenderRemediationCase): BacklogItem` adapter should follow this exact shape, with `uiId: \`defender:${item.case_id}\`` and a new `kind: "defender"` value added to the `BacklogKind` union (page.tsx lines ~23-41, read this session) and to the category filter segmented control (page.tsx line ~510, read this session — currently `["all","network","vulnerability","patch","configuration","incident","identity","lifecycle"]`).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Defender data siloed to the Exposure page only | Defender data must become a first-class remediation-backlog source | This phase | Requires the new correlation service and MCP tools described above; the Exposure page's existing Defender client methods (`services.ts`) are reused as-is, no change needed there. |
| Three hardcoded stub backlog rows (`incident`, `lifecycle`, `identity` kinds, page.tsx ~lines 254-309) simulating future data sources | Real Defender-backed adapters replace/extend these stubs | This phase (for the `incident`-adjacent Defender rows; `lifecycle`/`identity` stubs remain out of this phase's scope unless the planner chooses to also address them) | Removes misleading fake data from the UI for the Defender-relevant categories. |

**Deprecated/outdated:** None identified — this is additive wiring, not a replacement of an existing deprecated mechanism.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | New ontology relationship predicate names (`addressesFinding`, `addressesAlert`, `breaksAttackPath`, `improvesControl`) are proposed by this research to match the existing predicate-naming style (`mitigatesRisk`, `protectsService`, `hasApprovalDecision`) but are not drawn from any written naming-convention document. | Code Examples → ontology relationship registry; Ontology decisions in CONTEXT.md | Low-medium — if the planner/discuss-phase prefers different verb choices (e.g. `resolvesAlert`, `mitigatesFinding`), only a rename is needed before the ontology-alignment test is written; no architectural rework. Must NOT use "resolves"/"fixes" per the anti-pattern about not claiming resolution before post-change verification. |
| A2 | The recommended architecture merges Defender signals into the existing `resources` list (feeding the current opportunity/risk/priority engines) rather than building a fully parallel Defender-only pipeline. | Summary; Standard Stack → Alternatives Considered; Architecture Patterns → Pattern 1 | Medium — if the planner instead prefers a separate `/defender-remediation-cases` endpoint (Option 2 in Alternatives Considered), most of the correlation-service design still applies, but the merge-into-`resources` wiring in `fabric/runtime.py` would not be needed, and a new independent route/UI section would be needed instead. Flagged explicitly as Open Question Q1 so the planner can decide, not treated as settled. |
| A3 | A minimal catalog-seeding step is in-scope for this phase (Pitfall 1) rather than a separate cross-phase dependency. | Common Pitfalls → Pitfall 1 | High if wrong in the "descope" direction — if the planner descopes catalog seeding entirely, the phase will pass all unit tests (which use fixtures) but produce zero visible output in any real/demo environment, undermining the phase's stated goal of operator-usable triage. Recommend the planner make an explicit, visible decision here rather than silently inheriting the researcher's assumption. |
| A4 | Defender evidence should be added as a new sibling field (e.g. `evidence_citations`) alongside the existing plain-string `evidence` field, rather than changing `evidence`'s element type. | Common Pitfalls → Pitfall 3 | Low-medium — if existing tests assert `evidence: list[str]` strictly (not yet verified against every test file), changing element type in place would break them; a sibling field avoids this risk but adds one more field for the UI/agent to read. Verify exact existing assertions in `tests/test_remediation_*.py` before finalizing during planning. |

**If this table is empty:** N/A — see entries above.

## Open Questions

1. **Should Defender cases be exposed via a dedicated endpoint, or only through the existing `/remediation-opportunities`/`/remediation-plans` routes (enriched)?**
   - What we know: CONTEXT.md says "Extend operations API contracts and MCP tool registry rather than introducing page-only joins" — this favors *extending* existing contracts, but doesn't explicitly rule out one new endpoint for raw (pre-catalog-match) Defender cases (useful for showing "no safe action" escalations that never become an opportunity because no catalog entry matches).
   - What's unclear: Whether operators need to see uncorrelated/unmatched Defender cases at all (RECOMM-03 requires an explicit no-safe-action/escalation result), which would need *some* surface even if no opportunity/plan is generated.
   - Recommendation: Add one new endpoint (e.g. `GET /remediation/defender-cases`) specifically for the no-safe-action/escalation surface required by RECOMM-03, while feeding matched cases into the existing opportunity/plan routes via Pattern 1's resource-signal merge. This satisfies both the "extend, don't page-only-join" instruction and the "explicit no-safe-action" requirement without duplicating the full plan-generation pipeline.

2. **Exact PlanPrioritizer weight rebalancing for Defender signals.**
   - What we know: The current point budget (Pitfall 5) has no headroom; CONTEXT.md delegates weight choices to agent discretion.
   - What's unclear: Whether the planner wants a full rebalance (touching non-Defender weights) or an additive-only approach that accepts reduced Defender visibility for already-high-scoring resources.
   - Recommendation: The plan should make this an explicit task with a written weight table (all buckets, old and new, summing cleanly to 100 before the outer cap), reviewed against a couple of worked examples (e.g., a resource with a critical active alert but no patch/lifecycle risk) to sanity-check the ranking behaves as CONTEXT.md intends ("Prioritize actions that break the most critical attack paths or consolidate many Defender findings").

3. **Which `revalidation_checks` name(s) Phase 3 will actually implement for Defender freshness.**
   - What we know: `revalidation_checks` is currently a plain list of string labels with no enforcement logic behind most of them in Phase 2 (they're recorded, not yet all actively re-checked at execution time, since execution doesn't exist yet).
   - What's unclear: Whether Phase 3 expects a specific, stable string contract from Phase 2 (e.g. exactly `"defender_evidence_fresh"`) or whether this can be named freely now and adjusted later.
   - Recommendation: Pick a clear, self-descriptive name now (e.g. `"defender_evidence_fresh"`) and document it in this phase's PLAN.md/SUMMARY.md so Phase 3's research can discover and honor it, rather than leaving it implicit.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Backend (`src/`) | ✓ | per `pyproject.toml` `requires-python = ">=3.11"` [VERIFIED: .planning/codebase/CONVENTIONS.md:34] | — |
| pytest | Backend test suite | ✓ | `>=9.0.3,<10` [VERIFIED: .planning/codebase/TESTING.md:8] | — |
| Node.js / npm | Frontend build/test | ✓ | Next.js `14.2.35` declared [VERIFIED: web/package.json:23] | — |
| Fabric/OneLake live connection | Reading real (non-fixture) Defender Silver Delta tables | Not verified this session — `fabric.local.yaml` exists alongside `fabric.local.example.yaml` in the repo root, suggesting local dev config is present, but live connectivity was not probed (out of scope for a read-only research pass and would require credentials this session does not have) | — | Tests and local dev can run entirely against `tests/fixtures/*.json` scenario builders without a live Fabric connection, per the existing `remediation_scenario.py`/`*_scenario.py` pattern — this is the standard fallback already used throughout the test suite. |

**Missing dependencies with no fallback:** None identified — all required tooling is already present.
**Missing dependencies with fallback:** Live Fabric/OneLake connectivity for real-environment Defender catalog seeding verification (Pitfall 1) — falls back to fixture-based testing, but real-environment validation of the catalog-seeding fix should be tracked as a manual verification step, not assumed automatically covered by `pytest`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest `>=9.0.3,<10` [VERIFIED: .planning/codebase/TESTING.md:8] (backend); presumed `npm test`/Jest or equivalent for frontend (not independently re-verified this session beyond package.json presence — reuse whatever command `02-01-PLAN.md`'s verify blocks specify) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `addopts = "-q"`) [VERIFIED: .planning/codebase/TESTING.md:8-9] |
| Quick run command | `pytest -k "defender_remediation or remediation_ontology or mcp_tools or foundry_tool_registry"` |
| Full suite command | `pytest` (full suite; per `.planning/codebase/TESTING.md`, last recorded status "1583/1587 passing" — re-run full suite before phase completion, not just the keyword-filtered subset) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DETECT-03 | Correlated Defender case groups related records by resource + shared weakness | unit | `pytest tests/test_defender_remediation_correlation.py -x` | ❌ Wave 0 (new file) |
| DETECT-04 | Every case/opportunity carries structured, source-cited evidence | unit | `pytest tests/test_defender_remediation_correlation.py::test_evidence_citations_include_source_id_and_timestamp -x` | ❌ Wave 0 (new file/test) |
| DETECT-05 | Case includes dependency/ownership/criticality context | unit | `pytest tests/test_defender_remediation_correlation.py::test_case_includes_dependency_analyzer_output -x` | ❌ Wave 0 (new test) |
| DETECT-06 | Degraded/missing Defender source status surfaces as unknown, not healthy | unit (hardening) | `pytest tests/test_defender_remediation_correlation_hardening.py -x` | ❌ Wave 0 (new file) |
| DETECT-07 | Scope filtering hides unauthorized Defender-sourced backlog rows | unit | `pytest tests/test_api_remediation_approvals.py -k scope -x` (extend existing scope tests with a Defender-sourced row) | ✅ existing file, extend with new case |
| RECOMM-01 | PlanPrioritizer incorporates Defender ranking signals | unit | `pytest tests/test_remediation_scenario.py -k prioritiz -x` (or new dedicated test) | ⚠️ verify exact existing file name at implementation time; likely new test needed |
| RECOMM-02 | Plan payload states secure-score improvement and cites Defender evidence | unit | `pytest tests/test_defender_remediation_correlation.py::test_plan_includes_secure_score_improvement_estimate -x` | ❌ Wave 0 (new test) |
| RECOMM-03 | No-safe-action/escalation result when no catalog entry matches a Defender case | unit | `pytest tests/test_defender_remediation_correlation.py::test_unmatched_case_returns_explicit_no_safe_action -x` | ❌ Wave 0 (new test) |
| APPROVE-01/02/03 | Defender-sourced plans round-trip through the existing approval endpoint unchanged | integration (existing, extend fixture) | `pytest tests/test_api_remediation_approvals.py -x` | ✅ existing file, add a Defender-sourced plan fixture variant |
| Ontology (RemediationPlan↔Defender links) | New relationship tuples appear in ontology projection | contract | `pytest tests/test_remediation_ontology_alignment.py -x` | ✅ existing file, extend with new assertions |
| MCP tool registration | New Defender tools registered consistently across all three surfaces | contract | `pytest tests/test_foundry_tool_registry_matches_implementation.py tests/test_mcp_tools.py -x` | ✅ existing files, no new file needed (existing assertions automatically cover new registry rows) |
| Frontend adapter | `defenderCaseToBacklog` renders correctly, `RemediationOpportunity` mismatch fixed | unit/component | reuse whatever frontend test command `02-01-PLAN.md` specifies (e.g. `npm test`) | ⚠️ verify frontend test framework/command at implementation time — not independently re-confirmed this session |

### Sampling Rate
- **Per task commit:** `pytest -k "defender or remediation or mcp_tools or foundry_tool_registry"` (fast, targeted)
- **Per wave merge:** `pytest` (full backend suite) + frontend test command per `02-01-PLAN.md` precedent
- **Phase gate:** Full suite green before `/gsd-verify-work`, plus manual confirmation that `GET /remediation-opportunities` returns non-empty output against a seeded catalog (addressing Pitfall 1's environment-dependent risk, which unit tests alone cannot catch since they use fixtures).

### Wave 0 Gaps
- [ ] `tests/defender_correlation_scenario.py` — new scenario builder module, following `tests/remediation_scenario.py` precedent, providing fixture-backed Defender alert/attack-path/secure-score/assessment rows plus a resource dict, for reuse across multiple new test files.
- [ ] `tests/test_defender_remediation_correlation.py` — new file, base behavior tests for the correlation service.
- [ ] `tests/test_defender_remediation_correlation_hardening.py` — new file, edge cases (degraded sources, no-catalog-match escalation, multi-resource attack-path cases).
- [ ] `scripts/seed_remediation_catalog.py` (or equivalent) — new minimal catalog-seed mechanism to resolve Pitfall 1's blocking dependency for real-environment demonstration; exact location/mechanism is a planning decision, not prescribed here.
- [ ] Frontend test coverage for `defenderCaseToBacklog` and the `RemediationOpportunity` type fix — exact test file/command not independently verified this session; confirm frontend test framework (Jest/Vitest/RTL) before writing Wave 0 tasks.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (unchanged) | Existing `OperatePrincipal`/`ReadScope` dependency-injection pattern in `src/api/dependencies.py`, reused unchanged. |
| V3 Session Management | No (unchanged) | N/A — stateless API, no session change in this phase. |
| V4 Access Control | Yes | Existing `Scope`/`scope_attributes()`/`_filter_scoped()` pattern (operations.py) must be applied identically to every new Defender-sourced row and new MCP tool response — no new access-control mechanism should be invented; Defender rows must carry the same `scope_attributes` shape (subscription/business-service/environment identifiers) so existing scope filtering "just works." |
| V5 Input Validation | Yes | New request/response Pydantic models (if any new POST bodies are introduced, e.g. for catalog seeding) must follow the existing `RemediationDecisionRequest`-style validation pattern (`src/api/models.py`), with explicit field bounds — do not accept free-form dicts for anything user-supplied. |
| V6 Cryptography | No (unchanged) | No new cryptographic operations in this phase. |
| V7 Error Handling and Logging | Yes | Reuse `ApiError`/`ErrorCode` (src/api/errors.py) for any new error paths (e.g., "Defender case not found", "No catalog action matches") rather than raising bare exceptions or returning ad-hoc error shapes. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-scope data leakage (a Defender alert for a resource outside the caller's authorized scope appearing in the backlog) | Information Disclosure | Reuse `_filter_scoped()`/`scope_attributes()` exactly as done for existing remediation rows; every new Defender-sourced row must carry the same scope-attribute shape. Existing pattern already fails closed for "unattributed mixed-scope signals" per `docs/ontology-model.md`'s documented behavior — replicate, don't weaken. |
| Privilege escalation via a catalog-matched "action" that is actually unbounded/arbitrary (e.g., a catalog entry whose steps embed a raw script/CLI invocation) | Elevation of Privilege | CONTEXT.md explicitly requires "Match Defender evidence only to typed entries in the governed remediation action catalog; Defender prose may inform rationale but must not become executable instructions by itself" and "Controlled execution will begin in Phase 3 with only one or two typed, allowlisted, low-risk actions and no arbitrary shell or CLI path." Any new catalog-seed content added to resolve Pitfall 1 must be typed/declarative (matching the existing catalog action shape in `tests/fixtures/sample_remediation_planning.json`), never a free-text command string. |
| Tampering with approval decisions via stale `action_version` replay | Tampering | Already mitigated by the existing `action_version` staleness check (operations.py:245-251) — no new mechanism needed, but Defender-sourced plans must ensure their `action_version` changes whenever underlying Defender evidence changes materially, so a stale approval cannot be replayed against updated (worse or better) Defender evidence. This is a design point to confirm during planning: does `action_version` already incorporate a hash of resource signals, or only catalog action content? (Not verified this session — flag as an implementation-time check.) |
| Denial of service via unbounded correlation fan-out (e.g., one attack path touching thousands of nodes, or one CVE affecting thousands of resources, producing an unbounded case) | Denial of Service | Reuse existing bounding patterns: `DependencyAnalyzer`'s `max_dependencies=100` bound, and the MCP layer's `MAX_RESPONSE_BYTES`/`_bound(rows)` truncation pattern in `tools.py`. The new correlation service must apply an analogous cap on case size (e.g., max evidence citations per case) rather than assuming Defender data volumes stay small. |

## Sources

### Primary (HIGH confidence)
- `src/onboarding/defender_normalize.py` (518 lines, read in full this session) — Defender entity shapes.
- `src/intelligence/vulnerability/service.py` (key sections read this session) — Defender-aware read-model methods.
- `src/api/routers/vulnerability.py` (500 lines, read in full this session) — existing Defender REST routes.
- `src/intelligence/remediation/*.py` (all core modules read in full this session: `remediation_opportunity_engine.py`, `remediation_planner.py`, `remediation_generator.py`, `plan_repository.py`, `approval_decisions.py`, `risk_analyzer.py`, `approval_engine.py`, `plan_prioritizer.py`, `execution_simulator.py`, `dependency_analyzer.py`) — remediation engine internals.
- `src/fabric/runtime.py` (key region read this session) and `src/fabric/sync_service.py` (key regions read this session) — resource-signal merge seam and Defender snapshot availability.
- `src/api/runtime.py` (key region read this session) — `_fabric_vulnerability_service()` pattern.
- `src/operations/tools.py` and `src/operations/mcp_server.py` (key regions read this session, including verbatim `REVIEWED_TOOLS` tuple and `tool_definitions()`) — MCP tool registry.
- `infra/terraform/foundry.tf` (key region read this session, including verbatim `foundry_specialist_tools`) — per-specialist tool allocation.
- `web/src/app/remediation/page.tsx`, `web/src/lib/services.ts`, `web/src/lib/types.ts` (key regions read this session) — frontend adapter pattern and contract mismatch.
- `src/fabric/dataset_mapper.py` (key regions read this session, including verbatim `ONTOLOGY_RELATIONSHIP_TYPES` entries) — ontology registries.
- `docs/ontology-model.md` (lines 55-110 read this session, verbatim quotes captured) — ontology documentation.
- `.planning/table-usage-map.json` (read via targeted script this session) — catalog table usage classification.
- `tests/remediation_scenario.py`, `tests/fixtures/sample_remediation_planning.json` (read this session) — canonical catalog/trigger fixture shape.
- `tests/test_foundry_tool_registry_matches_implementation.py`, `tests/test_mcp_tools.py` (read this session) — MCP registration contract tests.
- `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/TESTING.md` (read in full this session) — repo-wide coding/testing conventions.
- `.planning/phases/02-investigation-recommendation-and-approval/02-CONTEXT.md` (read in full this session) — locked phase decisions.
- `.planning/REQUIREMENTS.md` (relevant lines read this session) — exact requirement text for DETECT-03..07/RECOMM-01..03/APPROVE-01..03.
- `.planning/phases/02-investigation-recommendation-and-approval/02-01-PLAN.md`/`02-01-SUMMARY.md`/`02-01-REVIEW.md` (read in full in prior session turns) — prior completed work in this phase.

### Secondary (MEDIUM confidence)
- None used — no web search was performed for this phase (pure internal codebase research; `.planning/config.json` shows all external search providers disabled: `brave_search`/`exa_search`/`tavily_search`/`ref_search`/`perplexity`/`jina` all `false`). All findings are verified directly against the codebase.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, all existing dependencies verified directly in `pyproject.toml`/`web/package.json`.
- Architecture: HIGH for reuse points and wiring seams (all read directly from source this session); MEDIUM for new module design (correlation service, new relationship predicate names) since no precedent exists in-repo for this specific correlation pattern.
- Pitfalls: HIGH — all six pitfalls are grounded in specific, cited source locations and existing test files, not speculation.
- Catalog-seeding gap (Pitfall 1): HIGH confidence that the gap exists (verified via `table-usage-map.json` and full-repo grep); LOW-MEDIUM confidence on the best resolution mechanism (no existing seeding pattern to copy from — flagged as Assumption A3/Open decision for the planner).

**Research date:** 2026-09-01 (matches `.planning/phases/02-investigation-recommendation-and-approval/02-CONTEXT.md`'s "Gathered" date and `.planning/codebase/*.md` analysis dates)
**Valid until:** 30 days from research date, OR immediately upon the next commit to any of `src/intelligence/remediation/*.py`, `src/fabric/runtime.py`, `src/operations/tools.py`, `src/operations/mcp_server.py`, `infra/terraform/foundry.tf`, or `web/src/app/remediation/page.tsx` in the current dirty working tree, since these files are under active, uncommitted user modification and exact line numbers/contents may shift before this phase's plan is executed. **Re-`view` every file cited with a specific line range before editing it.**
