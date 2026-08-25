# Roadmap: Azure AI Operations Platform

## Overview

This milestone turns the existing Azure and Fabric foundations into a controlled vertical MVP: operators detect and investigate cross-domain situations, receive evidence-backed recommendations, approve bounded actions, and observe durable execution and verification. Domain coverage and pilot readiness follow only after the core safety and audit loop is proven.

## Phases

- [x] **Phase 1: Evidence and Situation Foundation** - Establish durable situations, governed evidence, source quality, authorization, and audit primitives.
- [ ] **Phase 2: Investigation, Recommendation, and Approval** - Deliver bounded investigation, cited recommendations, and server-enforced approval.
- [ ] **Phase 3: Safe Remediation Execution** - Execute one or two typed, allowlisted actions with preview, durable jobs, verification, and bounded retries.
- [ ] **Phase 4: Domain Coverage and Operational Twin** - Prove representative incident, exposure, vulnerability, and twin-discrepancy workflows with replayable views.
- [ ] **Phase 5: Controlled Pilot Readiness** - Validate failure behavior, stale sources, authorization boundaries, rollout controls, and operator readiness.

## Phase Details

### Phase 1: Evidence and Situation Foundation

**Goal:** As a platform operator, I want to open a durable authorized situation and inspect its qualified evidence and audit history, so that I can trust the operational picture before investigation or action.
**Mode:** mvp
**Depends on:** Existing Azure ingestion, OneLake/Delta, Fabric projection, FastAPI, Entra, and Next.js foundations
**Requirements:** FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, DETECT-01, DETECT-02
**Success Criteria** (what must be TRUE):

  1. Operator can open a durable situation with lifecycle, severity, priority, scope, ownership, and affected resources, then link related operational entities.
  2. Representative ARG/Activity Log, Monitor or Service Health, Defender, Policy, and vulnerability signals appear as normalized records with source identifiers, timestamps, watermarks, and ingestion status.
  3. Operator can see freshness, availability, provenance, quality, and authorization scope for information used by the situation.
  4. Auditor can see immutable events for observations and other lifecycle activity without unauthorized users seeing out-of-scope data.

**Plans:** 3/3 plans executed (2 executed, 1 gap-closure)
Plans:

- [x] 01-PLAN.md

- [x] 01-01-PLAN.md — Deliver the durable situation, evidence, audit, authorization, and operator-trust foundation
- [x] 01-02-PLAN.md — Close production ingestion, trust, audit, authorization, UI, and MVP verification blockers

- [x] 01-03-PLAN.md — Close remaining audit scope, trust freshness, audit-error, queue, and walkthrough blockers

**UI hint:** yes

### Phase 2: Investigation, Recommendation, and Approval

**Goal:** Operators can move from an authorized situation to a bounded, evidence-backed decision and a durable approval outcome.
**Mode:** mvp
**Depends on:** Phase 1
**Requirements:** DETECT-03, DETECT-04, DETECT-05, DETECT-06, DETECT-07, RECOMM-01, RECOMM-02, RECOMM-03, APPROVE-01, APPROVE-02, APPROVE-03
**Success Criteria** (what must be TRUE):

  1. Operator can view a correlated situation timeline, search and filter across authorized domains, and inspect affected resources, dependencies, ownership, environment, and business criticality in bounded graph context.
  2. Every material explanation claim links to source, timestamp, scope, query or deep link, provenance, freshness, and quality; contradictory, missing, or stale evidence is visibly qualified.
  3. Operator receives ranked recommendations that state objective, scope, rationale, evidence, confidence, prerequisites, risks, and verification plan, or an explicit no-safe-action/escalation result.
  4. Authorized approver can approve, reject, or expire a recommendation, with identity, timestamp, reason, exact scope, action version, expiry, and server-side revalidation recorded.

**Plans:** TBD
**UI hint:** yes

### Phase 3: Safe Remediation Execution

**Goal:** An approved recommendation can safely run as a bounded, observable Azure job and produce a verified, auditable outcome.
**Mode:** mvp
**Depends on:** Phase 2
**Requirements:** EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05, EXEC-06
**Success Criteria** (what must be TRUE):

  1. Operator can choose only one or two typed, allowlisted low-risk actions; arbitrary shell or CLI execution is unavailable.
  2. Approver can preview exact targets, API operations, preconditions, expected effect, and possible collateral impact before approval.
  3. Approved execution enforces least privilege, bounded and validated targets, preconditions, timeouts, idempotency, and revalidation, then exposes queued, running, retrying, succeeded, failed, and cancelled states.
  4. Operator and auditor can see post-action actual state, outcome, failure details, verification results, and rollback or compensation status, including bounded retry history.

**Plans:** TBD
**UI hint:** yes

### Phase 4: Domain Coverage and Operational Twin

**Goal:** SRE, platform, and security operators can validate the complete workflow across representative domains and replay the evidence and twin context behind decisions.
**Mode:** mvp
**Depends on:** Phase 3
**Requirements:** PILOT-01, PILOT-02, PILOT-03
**Success Criteria** (what must be TRUE):

  1. Dashboard provides consistent authorized views for situations, evidence, exposure/compliance, vulnerabilities, operational-twin context, recommendations, approvals, and execution history.
  2. Pilot users can complete representative incident/change-correlation, Defender/Policy exposure, vulnerability-prioritization, and operational-twin discrepancy cases through the integrated workflow.
  3. Auditor can replay the evidence snapshot and append-only audit history used for a historical recommendation, including the relevant graph and source context.

**Plans:** TBD
**UI hint:** yes

### Phase 5: Controlled Pilot Readiness

**Goal:** The controlled Azure pilot remains safe and diagnosable when data, permissions, providers, execution, or verification fail.
**Mode:** mvp
**Depends on:** Phase 4
**Requirements:** PILOT-04
**Success Criteria** (what must be TRUE):

  1. Operators can distinguish and recover from ingestion, authorization, execution, verification, stale-source, and provider-outage failures without an unsupported success state.
  2. Pilot operators can exercise shadow/read-only and canary scope controls, a kill switch, rollback procedures, and visible handoff or failure outcomes before broader use.

**Plans:** TBD
**UI hint:** yes

## Progress

**Execution Order:** Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Evidence and Situation Foundation | 3/3 | In Progress|  |
| 2. Investigation, Recommendation, and Approval | 0/TBD | Not started | - |
| 3. Safe Remediation Execution | 0/TBD | Not started | - |
| 4. Domain Coverage and Operational Twin | 0/TBD | Not started | - |
| 5. Controlled Pilot Readiness | 0/TBD | Not started | - |

### Phase 6: Software and OS Inventory Visibility

**Goal:** Operators can inspect authorized, evidence-backed OS and installed-software inventory across Azure VMs and Arc-enabled servers, understand lifecycle risk, and export exact software/version matches for follow-up.
**Requirements**: INV-01, INV-02, INV-03, INV-04, INV-05, INV-06
**Depends on:** Phase 5
**Plans:** 6/9 plans executed

Plans:

- [x] 06-01-PLAN.md — Establish the scoped OS inventory tracer and Software Inventory route
- [x] 06-02-PLAN.md — Acquire native VM and Arc OS observations through immutable ARG generation
- [x] 06-03-PLAN.md — Trace ConfigurationData through canonical exact software lookup and detail
- [x] 06-04-PLAN.md — Integrate configured Logs workspaces and source lifecycle status
- [x] 06-05-PLAN.md — Deliver the server-owned EOL review and confirmation tracer
- [x] 06-06-PLAN.md — Add bounded official-vendor scraping and all-source EOL adapters
- [ ] 06-07-PLAN.md — Add executable D-16 mapping review, approval, rejection, and audit
- [ ] 06-08-PLAN.md — Add scoped grounded risk narrative with deterministic fallback
- [ ] 06-09-PLAN.md — Complete the two-tab dashboard, drill-down, filters, and CSV export
