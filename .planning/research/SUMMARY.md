# Project Research Summary

**Project:** Azure AI Operations Platform  
**Domain:** Azure SRE, platform, and security operations workbench  
**Researched:** 2026-08-23  
**Confidence:** MEDIUM

## Executive Summary

This is an internal Azure operations workbench that unifies detection, cross-domain investigation, evidence-backed explanation, recommendation, and human-approved remediation. Research strongly favors extending the existing brownfield FastAPI, Next.js/Fluent UI, OneLake/Delta, Fabric Ontology, Entra, and Terraform foundations rather than creating a parallel platform. Azure Monitor, Resource Graph, Defender, Sentinel, Policy, Activity Log, and Update Manager remain systems of record; this product should be their governed evidence-and-decision layer.

The central architectural decision is to make durable, immutable evidence bundles and workflow state first-class. A situation must preserve scope, freshness, provenance, source links, quality warnings, and the exact evidence hash behind each recommendation. Approval must be server-enforced and bound to an immutable typed action, while a least-privilege job executes only allowlisted, idempotent actions and verifies the resulting Azure state. The largest risks are unsupported AI claims, stale or incomplete evidence, scope/privilege errors, prompt injection, cosmetic approval, and unreconstructable audit history; freshness gates, typed contracts, separated identities, durable jobs, append-only audit, and a read-only/canary rollout mitigate them.

## Key Findings

### Recommended Stack

Retain the current Python 3.11+/deployed 3.12, FastAPI, Uvicorn, Next.js 14.2.35, React 18/Fluent UI 9, OneLake Delta/Parquet, Azure identity, Key Vault, Terraform, and Azure Monitor/OpenTelemetry foundations. Use the existing ARG CLI adapter with a REST fallback, bounded Azure Monitor KQL, and narrow source adapters. Use Container Apps Jobs for scheduled and asynchronous work, and narrow pinned `azure-mgmt-*` or REST adapters for remediation. Keep Foundry read-only and downstream of structured evidence. Fabric IQ Ontology remains an optional preview projection, never the canonical store. See [STACK.md](STACK.md).

**Core technologies:**
- **FastAPI + Python 3.12:** API, contracts, workflow orchestration, and bounded workers — existing runtime and extension boundaries are already tested.
- **OneLake/Delta + Fabric REST:** immutable generations, evidence projections, decisions, and audit — preserves the established governed persistence boundary.
- **Azure Resource Graph, Monitor, Defender, Sentinel, Policy, Update Manager:** authoritative discovery and operational evidence — link compact records to source IDs, timestamps, and deep links rather than copying raw data.
- **Container Apps Jobs:** durable scheduled/manual execution — safer than request-bound background tasks and suitable for one bounded action per run.
- **Entra/RBAC, managed identities, Key Vault:** identity and secret isolation — separate discovery, publication, and execution permissions.
- **Next.js/Fluent UI:** structured operator workbench — preserve the existing accessible UI rather than making chat the primary surface.

### Expected Features

The MVP should prove one integrated cross-domain value loop, not broaden into a new monitoring or ITSM system.

**Must have (table stakes):**
- Unified situation/investigation record with scope, ownership, severity, lifecycle, and canonical links.
- Multi-source detection, freshness/degraded-state indicators, change correlation, and cross-domain navigation.
- Evidence-backed explanation with source, timestamp, query/link, provenance, quality, contradictions, and bounded graph context.
- Resource/service ownership and impact context; exposure/compliance views and vulnerability prioritization.
- Typed recommendation with rationale, confidence, prerequisites, risk, target, and verification/rollback plan.
- Explicit approval state machine, bounded execution, durable progress/retry visibility, post-action verification, and append-only audit.

**Should have (competitive):**
- One evidence graph across incidents, exposure, compliance, vulnerabilities, and the operational twin.
- Explainable blast radius, evidence-weighted deterministic ranking, and cited “why now?” narratives.
- Safe action preview/counterfactual, recommendation-to-versioned-runbook continuity, twin/evidence-quality scoring, and replayable investigations.
- A visible “no safe action” outcome and scope-aware operator/executive views.

**Defer (v2+):**
- Fully autonomous remediation, arbitrary shell/CLI or runbook execution, broad write permissions, and automated policy-exemption changes.
- New SIEM, telemetry, vulnerability, or ITSM systems; multi-cloud abstraction; real-time guarantees across every source.
- Automated model retraining and broad notifications/ITSM integrations until the core lifecycle is proven.

### Architecture Approach

Use two explicit planes: an evidence/projection plane (scoped source adapters → normalization → evidence registry → versioned canonical twin/ontology projection) and an investigation/decision/execution plane (situation → evidence bundle → bounded analysis → recommendation → policy/approval → idempotent execution → verification/audit). OneLake/Delta owns durable canonical history; Ontology is a replaceable projection. Keep routers, CLI, UI, and Foundry narration thin, with domain services owning contracts and state.

**Major components:**
1. **Source adapters and evidence registry** — retrieve minimum authorized observations, preserve source IDs/links, normalize provenance, enforce freshness, redaction, and retention.
2. **Canonical twin/ontology projection** — version entities, assertions, effective views, conflicts, quality, and publication watermarks without overwriting history.
3. **Situation and investigation services** — freeze scope/evidence snapshots, run bounded durable investigations, and produce cited explanations.
4. **Policy/approval service** — evaluate scope, allowlists, risk, expiry, separation of duties, and immutable proposal/evidence hashes.
5. **Execution adapters and audit ledger** — perform typed actions with managed identity, idempotency, verification, provider operation IDs, and append-only correlated events.

Key patterns are snapshot-pinned evidence bundles, durable orchestrators with idempotent activities, separate decision and execution capabilities, append-only audit correlation, and graph projection rather than graph ownership. Recommended state is explicit and monotonic: `created → investigating → explained → recommended → awaiting_approval → approved → executing → verifying → succeeded|failed|partially_succeeded|expired|cancelled`.

### Critical Pitfalls

1. **Fluent explanations outrun evidence** — require claim-to-evidence validation, distinguish facts/inferences/hypotheses/actions, apply freshness gates, and keep Foundry as a read-only narrator.
2. **Stale or partial data appears current** — attach generation, coverage, freshness, and quality to every bundle; publish only complete generations; represent unavailable providers explicitly.
3. **Recommendation crosses into unsafe execution** — use a typed allowlist, target/precondition validation, dry-run, immutable action hash, pre-dispatch revalidation, idempotency, bounded retries, and post-state verification.
4. **Identity, scope, or privilege mistakes** — validate Entra/gateway identity, filter immediately after provider retrieval and before execution, resolve authoritative IDs server-side, and separate read/publish/execute identities.
5. **Prompt injection becomes tool abuse or exfiltration** — treat all retrieved text as untrusted data, minimize/redact outbound context, use narrow typed read tools, validate outputs in code, and red-team direct/indirect injection.
6. **Approval or audit is cosmetic/incomplete** — persist approval against exact targets/evidence/version/expiry, enforce it at API/worker/retry surfaces, and append every decision, dispatch, provider, and verification event.
7. **Pilot and drift risk erode trust** — version schemas/policies/models, quarantine unknown records, start shadow/read-only, canary one subscription, rehearse rollback, and provide a kill switch.

## Implications for Roadmap

Based on the dependency chain and the architecture build order, use six phases:

### Phase 1: Evidence and Situation Foundation
**Rationale:** Every later decision depends on canonical IDs, durable records, provenance, freshness, and scope.  
**Delivers:** Situation schema/lifecycle, evidence bundles, source watermarks, quality/degraded states, ownership, audit primitives, and the first detect → explain slice.  
**Addresses:** Unified record, detection intake, evidence explanation, impact context, change correlation, stale-state UX.  
**Avoids:** Unsupported AI claims, stale evidence, noisy detections, and a mutable “current truth” graph.

### Phase 2: Investigation, Recommendation, and Approval
**Rationale:** Build the decision lifecycle before granting any mutation capability.  
**Delivers:** Bounded durable investigation jobs, graph context, deterministic ranking, cited recommendations, immutable approval state machine, expiry, separation of duties, and workflow UI.  
**Uses:** OneLake/Delta, semantic services, Entra/RBAC, Container Apps Jobs, and existing Next.js workbench.  
**Implements:** Situation, investigation, explanation, recommendation, policy, approval, and audit components.  
**Avoids:** Cosmetic/bypassable approval, request-bound work, uncited recommendations, and untraceable history.

### Phase 3: Security Boundary and One Bounded Remediation
**Rationale:** Prove safe execution only after server-side policy, identity, and AI boundaries exist.  
**Delivers:** Prompt/data boundary controls, narrow Foundry read tools, one or two reversible allowlisted actions, dry-run/preflight, managed execution identity, durable dispatch, and verification.  
**Addresses:** Bounded execution, safe preview, runbook continuity, “no safe action,” and audit completion.  
**Avoids:** Prompt injection, arbitrary commands, privilege escalation, stale approvals, and repeated non-idempotent writes.

### Phase 4: Domain Coverage and Operational Twin Hardening
**Rationale:** Expand representative value slices only after the core loop is safe and replayable.  
**Delivers:** Incident/change, Defender/Policy exposure, vulnerability, and twin-discrepancy slices; effective/evidence/incident-time graph views; ontology health, rollback, reconciliation, and source/curated/graph watermarks.  
**Addresses:** Cross-domain evidence graph, blast radius, vulnerability prioritization, quality scoring, and replayable investigations.  
**Avoids:** Shadow systems of record, hidden ontology preview dependency, and conflicting/overwritten assertions.

### Phase 5: Controlled Pilot Readiness
**Rationale:** Production rollout must be an explicit safety and reliability gate, not the result of feature completion.  
**Delivers:** Shadow/read-only baseline, canary scope, kill switch, error budgets, failure injection, stale/provider-outage tests, permission and cross-scope tests, rollback drills, privacy review, and operator feedback/evaluation cases.  
**Addresses:** Failure recovery, notifications/handoff minimums, audit retention, and operational readiness.  
**Avoids:** Alert fatigue, silent partial failure, drift, data leakage, and unsafe broad rollout.

### Phase 6: Scale and Integrations
**Rationale:** Add breadth and throughput only after measured pilot precision, safety, and recovery.  
**Delivers:** More source adapters/actions, queue-backed workers, concurrency limits, quotas, notification/ITSM adapters, and outcome labeling.  
**Addresses:** Learning from outcomes and broader operator workflows without prematurely building replacements for source systems.  
**Avoids:** Unbounded graph/context growth, broad permissions, and multi-cloud abstraction before there is a validated need.

### Phase Ordering Rationale

- Canonical identity, evidence, freshness, and authorization are prerequisites for trustworthy investigation and approval.
- Recommendation and approval must be independently durable before any write adapter is introduced.
- Execution starts with one reversible typed action so verification, idempotency, rollback, and audit can be proven.
- Domain breadth, ontology hardening, and scale follow the safety-critical vertical slice; this prevents architecture work from becoming a shadow CMDB or autonomous operator.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** Exact source connector contracts, pagination, watermarks, retention, tenant permissions, and cross-domain identity normalization.
- **Phase 2:** Durable workflow implementation choice, evidence/audit schema, approval expiry semantics, and target-tenant RBAC/separation-of-duties behavior.
- **Phase 3:** Exact Sentinel/Defender/Update Manager/ARM API versions, action capability and rollback semantics, Foundry tool/auth contract, and Prompt Shields/data-boundary controls.
- **Phase 4:** Fabric IQ Ontology tenant capability, refresh/relationship API behavior, preview lifecycle, and atomic publication/rollback.
- **Phase 5:** Pilot entry/exit criteria, privacy/residency, retention, failure-injection fixtures, and operational ownership.

Phases with comparatively standard patterns (still validate against the repository):
- **Phase 6:** Container Apps Jobs/queue scaling, OpenTelemetry correlation, and thin adapter patterns are well documented; research only specific provider limits and measured workload needs.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM | Existing code and official Microsoft documentation support retained runtime/storage/identity choices; exact provider and Foundry versions remain unverified. |
| Features | MEDIUM | Strongly grounded in PROJECT.md and official Azure systems of record; broad cross-vendor product-pattern claims are lower confidence because web search was unavailable. |
| Architecture | HIGH | Repository-specific boundaries and dependency/build order align across the architecture research and project constraints; external durable-workflow details are MEDIUM. |
| Pitfalls | MEDIUM | Official security/reliability guidance and repository concerns agree; implementation-specific failure modes still need tests. |

**Overall confidence:** MEDIUM

### Gaps to Address

- Verify target-tenant permissions, API shapes, pagination, retention, throttling, and package versions for Sentinel, Defender, Update Manager, Azure Monitor, and ARM runbooks.
- Spike Fabric IQ Ontology capability, refresh/relationship semantics, preview limitations, and rollback before making it a pilot dependency.
- Select and validate a durable worker approach (Container Apps Jobs versus Durable Functions/repository-native worker) under cancellation, retry, replica, and lease failure.
- Define evidence retention/redaction, Foundry data handling, model/version pinning, prompt-injection tests, and audit access/residency requirements.
- Establish pilot success metrics: precision, stale/duplicate rate, safe-action rate, verification success, recovery time, operator trust, and explicit stop conditions.

## Sources

### Primary (HIGH confidence)
- `.planning/PROJECT.md` — product contract, validated foundations, active requirements, constraints, and out-of-scope boundaries.
- `.planning/codebase/ARCHITECTURE.md`, `INTEGRATIONS.md`, `CONCERNS.md`, `STACK.md` — repository-specific architecture, integration, risk, and stack findings cited by the research documents.

### Secondary (MEDIUM confidence)
- [Azure Resource Graph REST API](https://learn.microsoft.com/rest/api/azure-resourcegraph/), [Azure Monitor Logs Query API](https://learn.microsoft.com/azure/azure-monitor/logs/api/overview), [Activity Log](https://learn.microsoft.com/azure/azure-monitor/essentials/activity-log) — discovery and operational evidence.
- [OneLake](https://learn.microsoft.com/fabric/onelake/onelake-overview), [Fabric lakehouse](https://learn.microsoft.com/fabric/data-engineering/lakehouse-overview), [Fabric Ontology Preview](https://learn.microsoft.com/fabric/iq/ontology/overview) — canonical storage and optional semantic projection.
- [Foundry Agent Service](https://learn.microsoft.com/azure/ai-foundry/agents/overview), [Prompt Shields](https://learn.microsoft.com/azure/ai-services/content-safety/concepts/jailbreak-detection), [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) — AI boundary and governance.
- [Container Apps Jobs](https://learn.microsoft.com/azure/container-apps/jobs), [Durable Functions](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-overview), [Managed identities](https://learn.microsoft.com/azure/active-directory/managed-identities-azure-resources/overview) — durable execution and identity.
- [Defender for Cloud](https://learn.microsoft.com/azure/defender-for-cloud/defender-for-cloud-introduction), [Sentinel](https://learn.microsoft.com/azure/sentinel/overview), [Azure Policy](https://learn.microsoft.com/azure/governance/policy/overview), [Azure RBAC](https://learn.microsoft.com/azure/role-based-access-control/overview) — authoritative domain and governance services.
- Google SRE, [Embracing Risk](https://sre.google/sre-book/embracing-risk/) — reliability and rollout principles.

### Tertiary (LOW confidence)
- Broad cross-vendor SRE product-pattern comparisons — validate during requirements and pilot design; web-search tooling was unavailable.

---
*Research completed: 2026-08-23*  
*Ready for roadmap: yes*
