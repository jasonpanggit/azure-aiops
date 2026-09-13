# Roadmap: Azure AI Operations Platform

## Overview

This milestone turns the existing Azure and Fabric foundations into a controlled vertical MVP: operators detect and investigate cross-domain situations, receive evidence-backed recommendations, approve bounded actions, and observe durable execution and verification. Domain coverage and pilot readiness follow only after the core safety and audit loop is proven.

## Phases

- [x] **Phase 1: Evidence and Situation Foundation** - Establish durable situations, governed evidence, source quality, authorization, and audit primitives.
- [x] **Phase 2: Investigation, Recommendation, and Approval** - Deliver bounded investigation, cited recommendations, and server-enforced approval.
- [ ] **Phase 3: Safe Remediation Execution** - Execute one or two typed, allowlisted actions with preview, durable jobs, verification, and bounded retries.
- [ ] **Phase 4: Domain Coverage and Operational Twin** - Prove representative incident, exposure, vulnerability, and twin-discrepancy workflows with replayable views.
- [ ] **Phase 5: Controlled Pilot Readiness** - Validate failure behavior, stale sources, authorization boundaries, rollout controls, and operator readiness.
- [x] **Phase 6: Software and OS Inventory Visibility** - Deliver scoped, evidence-backed OS and installed-software inventory with lifecycle risk and export.
- [ ] **Phase 7: Unified Resource Inventory** - Establish Fabric/OneLake-backed inventory as the unified data platform for every resource family including PaaS, consumed by the semantic graph and other subsystems rather than owned by them.
- [x] **Phase 8: Resource Identity Plane** - Extend inventory to own complete resource identity — all types, containment hierarchy, raw properties, and watermarks — so Hermes stops querying ARG for resource identity and consumes inventory for graph construction, relationship modelling, and semantic traversal.
- [x] **Phase 9: Consumer Pivot** - Repoint API providers, agent queries, and affected web pages at the inventory read port so the UI is powered by unified inventory.

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

### Phase 2: Investigation, Recommendation, and Approval ✅

**Goal:** Operators can move from an authorized situation to a bounded, evidence-backed decision and a durable approval outcome.
**Mode:** mvp
**Depends on:** Phase 1
**Requirements:** DETECT-03, DETECT-04, DETECT-05, DETECT-06, DETECT-07, RECOMM-01, RECOMM-02, RECOMM-03, APPROVE-01, APPROVE-02, APPROVE-03
**Success Criteria** (what must be TRUE):

  1. ✅ Operator can view a correlated situation timeline, search and filter across authorized domains, and inspect affected resources, dependencies, ownership, environment, and business criticality in bounded graph context.
  2. ✅ Every material explanation claim links to source, timestamp, scope, query or deep link, provenance, freshness, and quality; contradictory, missing, or stale evidence is visibly qualified.
  3. ✅ Operator receives ranked recommendations that state objective, scope, rationale, evidence, confidence, prerequisites, risks, and verification plan, or an explicit no-safe-action/escalation result.
  4. ✅ Authorized approver can approve, reject, or expire a recommendation, with identity, timestamp, reason, exact scope, action version, expiry, and server-side revalidation recorded.

**Status:** ✅ COMPLETE — All 8 plans executed, code reviewed, and verified (47/47 Phase 2 tests passing)

**Plans:** 8/8 complete

Plans:

- [x] 02-01-PLAN.md — Investigation, recommendation, and approval foundation
- [x] 02-02-PLAN.md — Tracer: end-to-end Defender-correlated business-decision case
- [x] 02-03-PLAN.md — Governed action catalog and idempotent seeder
- [x] 02-04-PLAN.md — Business decision intelligence: dispositions, costs, alternatives
- [x] 02-05-PLAN.md — Read-only Defender MCP tools and remediation specialist contract
- [x] 02-06-PLAN.md — Ontology relationships for plan-to-Defender evidence
- [x] 02-07-PLAN.md — Business-impact-first ranking, risk signals, correlation hardening
- [x] 02-08-PLAN.md — Decision workspace, decision audit route, approval freshness

**Verification:** Code review (02-REVIEW.md) identified 6 findings; all fixed and tested. Phase 2 ready for Phase 3 dependency gate.

**UI hint:** yes

### Phase 3: Safe Remediation Execution

**Goal:** As a platform operator, I want to run an approved remediation as a bounded, observable Azure job, so that I receive a verified and auditable outcome.
**Mode:** mvp
**Depends on:** Phase 2
**Requirements:** EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05, EXEC-06
**Success Criteria** (what must be TRUE):

  1. Operator can choose only one or two typed, allowlisted low-risk actions; arbitrary shell or CLI execution is unavailable.
  2. Approver can preview exact targets, API operations, preconditions, expected effect, and possible collateral impact before approval.
  3. Approved execution enforces least privilege, bounded and validated targets, preconditions, timeouts, idempotency, and revalidation, then exposes queued, running, retrying, succeeded, failed, and cancelled states.
  4. Operator and auditor can see post-action actual state, outcome, failure details, verification results, and rollback or compensation status, including bounded retry history.

**Plans:** 6/6 plans executed (3 executed, 3 gap-closure)
Plans:

- [x] 03-01-PLAN.md — Remediation router mounted with plan list/get/preview/approvals/business-decision reads (closes the 404 API gap)
- [x] 03-02-PLAN.md — Execution adapter generalization, approval-gated execute endpoint, durable job tracking
- [x] 03-03-PLAN.md — Post-action verification against upstream Azure source of truth, rollback guidance, bounded idempotent retries
- [x] 03-04-PLAN.md — Bind exact server-derived patch selection and deterministic business evidence to approval; remove direct patch mutation
- [x] 03-05-PLAN.md — Enforce atomic execution/retry, authoritative verification, scope, cancellation, history, and eligibility contracts
- [x] 03-06-PLAN.md — Deliver remediation execution UI and remove direct patch inventory mutation

**UI hint:** yes

### Phase 03.1: Exposure Reliability and Scale (INSERTED)

**Goal:** Make Exposure authoritative, failure-tolerant, temporally correct, ontology-complete for container images, and operable at Defender-scale volumes before Phase 4 pilot validation.
**Requirements:** PILOT-01, PILOT-02, PILOT-03, PILOT-04 (reliability prerequisites; final pilot completion remains downstream)
**Depends on:** Phase 3
**Plans:** 23/25 plans executed

Plans:

- [x] 03.1-01-PLAN.md — Create Wave 0 Exposure fixtures, test scaffolds, benchmark, and Fabric SQL readiness probe
- [x] 03.1-02-PLAN.md — Human-verify the flagged pyodbc package before any install
- [x] 03.1-03-PLAN.md — Prove the governed tracer through persistence, API, vulnerabilityApi, and a real Exposure section
- [x] 03.1-21-PLAN.md — Gate permanent typed-image ontology identities, then complete the production tracer through ontology, remediation review handoff, and Copilot parity
- [x] 03.1-04-PLAN.md — Productionize Fabric SQL/ODBC and managed Key Vault cursor-key rotation
- [x] 03.1-05-PLAN.md — Normalize typed AUM/Defender acquisition outcomes without failure rows
- [x] 03.1-06-PLAN.md — Acquire and persist exact Container Insights workload-to-digest evidence
- [x] 03.1-07-PLAN.md — Publish source checkpoints/LKG and per-family freshness/completeness
- [x] 03.1-08-PLAN.md — Persist immutable observations and replay deterministic current state
- [x] 03.1-09-PLAN.md — Serve temporal state with honest first-detection and SLA semantics
- [x] 03.1-10-PLAN.md — Persist granular image/digest/deployment evidence
- [x] 03.1-11-PLAN.md — Expand the approved typed-image ontology with exact round-trip and traversal integrity
- [x] 03.1-23-PLAN.md — Refresh MSRC/NVD/EPSS/KEV asynchronously with durable per-item status and provider-free API reads
- [x] 03.1-12-PLAN.md — Materialize and publish generation-pinned Gold
- [x] 03.1-13-PLAN.md — Enforce scope-first Fabric SQL queries and managed signed cursors
- [x] 03.1-14-PLAN.md — Consolidate scoped consumers and enforce handoff-only container remediation
- [x] 03.1-15-PLAN.md — Build cursor-aware web query, same-scope LKG, and independent-section contracts
- [x] 03.1-18-PLAN.md — Add complete low-cardinality Exposure telemetry, alerts, and shadow reconciliation
- [x] 03.1-24-PLAN.md — Extend and test the actual shared PageHeader, MetricCard, TablePagination, and governed risk dialog
- [x] 03.1-16-PLAN.md — Deliver trustworthy Defender sections and explicit safe deep links
- [x] 03.1-17-PLAN.md — Deliver governed Patch/remediation handoffs with responsive accessibility
- [x] 03.1-22-PLAN.md — Correct ordinary navigation and wire every lean Overview section state
- [x] 03.1-25-PLAN.md — Wire complete independent states, context continuity, and governed risk feedback into existing CVE/KB `[id]` routes
- [ ] 03.1-19-PLAN.md — Benchmark, canary, rollback-test, live-validate, and produce the Phase 4 handoff
- [ ] 03.1-20-PLAN.md — Human-approve authenticated Exposure behavior and Phase 4 evidence

### Phase 03.2: Durable Remediation Identity and Audit Continuity (INSERTED)

**Goal:** Give each remediation target/action a stable plan identity, preserve approval and execution audit continuity across evidence refreshes, and make execution reads independent of regenerated plan availability.
**Requirements:** Derived from Phase 03 deep-review recommendation 1
**Depends on:** Phase 3
**Plans:** 2/2 plans complete

Plans:

- [x] 03.2-01-PLAN.md — Stable plan identity end-to-end with scope-attribute-authorized execution reads, fail-closed repository guards, and orphaned-execution diagnostics
- [x] 03.2-02-PLAN.md — One planner/repository view per request via TTL-cached hybrid_remediation resolution

### Phase 03.3: Recoverable Remediation Attempts and Supersession (INSERTED)

**Goal:** Count only proven provider submissions against retry limits, classify refusal and provider failure causes, and provide an audited supersession path after external blockers are resolved.
**Requirements:** Derived from Phase 03 deep-review recommendation 2
**Depends on:** Phase 03.2
**Plans:** 3/3 plans complete

Plans:

- [x] 03.3-01-PLAN.md — Classify provider_submitted/failure_class at the Azure patch and Defender-configuration adapter boundary
- [x] 03.3-02-PLAN.md — Derive the retry ceiling from submitted-only attempts, with legacy-compatible defaults
- [x] 03.3-03-PLAN.md — Audited POST supersede endpoint with bidirectional lineage and API/web projections

### Phase 03.4: Autonomous Remediation Verification and Evidence Reconciliation (INSERTED)

**Goal:** Move verification to a bounded server-side lifecycle, interpret complete Azure patch results, and reconcile terminal outcomes against refreshed target evidence without requiring an open browser.
**Requirements:** Derived from Phase 03 deep-review recommendation 3
**Depends on:** Phase 03.2, Phase 03.3
**Plans:** 3/3 plans complete

Plans:

- [x] 03.4-01-PLAN.md — Durable verification scheduling/deadline fields on the execution store, plus deep nested Azure patch-result parsing (installed/failed/pending counts, provider errors) in the verifier
- [x] 03.4-02-PLAN.md — Deadline-enforced poll_verification (explicit unknown/timed-out terminal outcome), selected-KB evidence reconciliation, and submission-ambiguous reconciliation, safe under concurrent callers
- [x] 03.4-03-PLAN.md — Bounded background verification coordinator wired into API startup/shutdown, backed by the existing live vulnerability evidence path, with restart-recovery and browser-independence tests

### Phase 03.5: Unified Remediation Approval Governance (INSERTED)

**Goal:** Enforce one evidence-sensitive approval policy across patch and Defender action families, with machine-checkable requirements, explicit demo self-approval, and distinct approve/operate authorization.
**Requirements:** Derived from Phase 03 deep-review recommendation 4
**Depends on:** Phase 03.2
**Plans:** 7/7 plans complete

Plans:

- [x] 03.5-01-PLAN.md — Shared action_version_for() helper, ApprovalEngine.policy_version, and durable decision-store self-approval/role facts
- [x] 03.5-02-PLAN.md — Distinct approve/operate RBAC action and dependency
- [x] 03.5-03-PLAN.md — Shared approval-requirement satisfaction and staleness evaluation engine
- [x] 03.5-04-PLAN.md — Live patch/Defender planners on the shared action_version and ApprovalEngine-shaped requirements
- [x] 03.5-05-PLAN.md — Execution-service gate enforces per-role satisfaction and cross-family separation of duties
- [x] 03.5-06-PLAN.md — Decision/workflow routes require approve and project the shared satisfaction/staleness functions
- [x] 03.5-07-PLAN.md — Minimal approved UI contract: requirement rows, self-approval disclosure, approve/operate gating, stale state

### Phase 03.6: Remediation Workflow Safety and Operator Guidance (INSERTED)

**Goal:** Expose server-derived blockers and degraded inputs, render lifecycle failures honestly, make patch selection fail-safe, and provide bounded, actionable operator recovery controls.
**Requirements:** Derived from Phase 03 deep-review recommendation 5 (EXEC-04, EXEC-05, EXEC-06, APPROVE-03)
**Depends on:** Phase 03.2, Phase 03.3, Phase 03.4, Phase 03.5
**Plans:** 6/6 plans complete

Plans:

- [x] 03.6-01-PLAN.md — Backend Failure Details Authoritative Contract (execution_service.py, exhaustive terminal-failure test)
- [x] 03.6-02-PLAN.md — Backend blockers[]/degradation[] assembly, honest verify-step projection, real citation freshness
- [x] 03.6-03-PLAN.md — Frontend types + fail-safe patch selection (CR-07) + bounded/independently-testable polling
- [x] 03.6-04-PLAN.md — Frontend WorkflowBlockers/WorkflowDegradation panels + honest Verify-step failure_details rendering
- [x] 03.6-05-PLAN.md — Frontend RecoveryControls (Cancel/Retry/Supersede) + always-visible facts + reconciliation + lineage
- [x] 03.6-06-PLAN.md — Playwright E2E setup + smoke/workflow-safety specs + Manual QA backstop sign-off

### Phase 03.7: Fabric Publication Decoupling and Query Scale (INSERTED)

**Goal:** Reduce Fabric publication and request-time load by separating domain projection from atomic publication, retiring legacy generation remapping from production reads, and pushing inventory scope/filter/count/pagination into the Fabric-backed read path.
**Requirements:** MED-11, MED-12, MED-13
**Depends on:** Phase 03.1, Phase 7, Phase 9, Phase 13
**Planning status:** 11/11 plans verified; planning completion does not authorize execution.
**Execution status:** BLOCKED — `/gsd-execute-phase 03.7` must hard-stop in Plan 01 before any file change until every dependency has all required summaries and passing phase verification evidence. Phase 03.1 remains blocked on the exact live Defender digest-to-workload evidence after successful Fabric publication (03.1-19/20 incomplete); Phase 7 lacks passing phase verification evidence; Phase 9 lacks 09-10/09-11 summary evidence; Phase 13 remains incomplete and lacks final verification consistent with its final plan set. No dependency is waived.
**Success Criteria** (what must be TRUE):

  1. Fabric publication stages and promotes versioned domain products without running unrelated change, predictive, incident, or other domain intelligence pipelines inside the publication transaction.
  2. Production health, semantic, network, and vulnerability providers do not rebuild the full mapped medallion model from every connection generation at request time.
  3. Inventory list and lookup operations push authorized scope, filters, ordering, counts, and pagination into the Fabric-backed query adapter without a fixed 10,000-row pre-pagination ceiling.
  4. Existing immutable observations, generation replay, active-pointer rollback, ontology consistency, source status, Exposure Gold contracts, and bounded PageSnapshot behavior remain intact.

**Plans:** 0/11 plans executed (11/11 planned; execution blocked by prerequisites)
Plans:

- [ ] 03.7-01-PLAN.md — Create Wave 0 publication, probe, query-scale, and benchmark contracts
- [ ] 03.7-02-PLAN.md — Gate generation-qualified inventory storage and namespaced product-pointer layout
- [ ] 03.7-03-PLAN.md — Trace one five-table inventory product through atomic promotion to a scoped SQL page
- [ ] 03.7-04-PLAN.md — Move unrelated domain projection outside product publication while preserving outputs
- [ ] 03.7-05-PLAN.md — Cut production providers and health probes to published status/read ports
- [ ] 03.7-06-PLAN.md — Complete scope-first inventory querying and wire the request read port
- [ ] 03.7-07-PLAN.md — Add measured shadow, staged cutover, alias registry/telemetry, and non-destructive rollback
- [ ] 03.7-08-PLAN.md — Approve deployed evidence, observe duplicate writes, and record per-alias dispositions
- [ ] 03.7-09-PLAN.md — Migrate onboarding identity consumers to generation-pinned complete scans
- [ ] 03.7-10-PLAN.md — Apply alias dispositions and prove retired aliases receive no writes
- [ ] 03.7-11-PLAN.md — Qualify the immutable deployed baseline in the same environment and generate complete cutover/scale/rollback evidence
**UI hint:** no

### Phase 4: Domain Coverage and Operational Twin

**Goal:** SRE, platform, and security operators can validate the complete workflow across representative domains and replay the evidence and twin context behind decisions.
**Mode:** mvp
**Depends on:** Phase 3, Phase 03.1, Phase 03.7
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
| 3. Safe Remediation Execution | 6/6 | In Progress|  |
| 03.7 Fabric Publication Decoupling and Query Scale | 0/8 | Not started | - |
| 4. Domain Coverage and Operational Twin | 0/TBD | Not started | - |
| 5. Controlled Pilot Readiness | 0/TBD | Not started | - |
| 6. Software and OS Inventory Visibility | 9/9 | Code-complete, UAT pending | - |
| 7. Unified Resource Inventory | 6/6 | Implementation complete; live verification pending | - |
| 8. Resource Identity Plane | 3/3 | In Progress|  |
| 9. Consumer Pivot | 9/9 | ✅ Complete — Operations MCP + Network Agent Integration | ✅ 2026-08-28 |

### Phase 6: Software and OS Inventory Visibility

**Goal:** Operators can inspect authorized, evidence-backed OS and installed-software inventory across Azure VMs and Arc-enabled servers, understand lifecycle risk, and export exact software/version matches for follow-up.
**Requirements**: INV-01, INV-02, INV-03, INV-04, INV-05, INV-06
**Depends on:** Phase 5
**Plans:** 9 plans

Plans:

- [x] 06-01-PLAN.md — Establish the scoped OS inventory tracer and Software Inventory route
- [x] 06-02-PLAN.md — Acquire native VM and Arc OS observations through immutable ARG generation
- [x] 06-03-PLAN.md — Trace ConfigurationData through canonical exact software lookup and detail
- [x] 06-04-PLAN.md — Integrate configured Logs workspaces and source lifecycle status
- [x] 06-05-PLAN.md — Deliver the server-owned EOL review and confirmation tracer
- [x] 06-06-PLAN.md — Add bounded official-vendor scraping and all-source EOL adapters
- [x] 06-07-PLAN.md — Add executable D-16 mapping review, approval, rejection, and audit
- [x] 06-08-PLAN.md — Add scoped grounded risk narrative with deterministic fallback
- [x] 06-09-PLAN.md — Complete the two-tab dashboard, drill-down, filters, and CSV export

### Phase 7: Unified Resource Inventory

**Goal:** As a platform operator, I want one authoritative Fabric/OneLake-backed inventory covering every Azure resource family including PaaS, owned by the inventory domain itself, so that I can trust a single governed source of truth that the semantic graph and every other subsystem consumes rather than re-derives.
**Requirements**: INV-07, INV-08, INV-09, INV-10
**Depends on:** Phase 6
**Plans:** 6/6 plans executed after Fabric unified-data-platform pivot
Plans:

- [x] 07-01-PLAN.md — Contract-level characterization suite pinning dataset names, row shapes, and the three high-risk behaviors (hard precondition)
- [x] 07-02-PLAN.md — Extract DatasetStore and generation machinery to the neutral storage package, public surface preserved
- [x] 07-03-PLAN.md — Fabric-backed ownership inversion and inventory publication contracts
- [x] 07-04-PLAN.md — Fabric-aligned `ResourceObservation`, payload serialization, API redaction, and family registry
- [x] 07-05-PLAN.md — PaaS family and per-family availability over Fabric-backed inventory contracts
- [x] 07-06-PLAN.md — Fabric-backed read port, direct-read/Hermes ownership guards, and Phase 7 exit evidence

**UI hint:** yes

**Context:** Inventory acquisition, normalization, retention, source status, and publication currently live inside the Hermes ARG connector, while the read model lives in `intelligence/inventory`. The dependency is already inverted — `hermes_arg_connector/inventory_normalize.py` imports its contracts from `intelligence.inventory.models`. Hermes must be a consumer of inventory, never its owner. This coupling is why inventory availability is gated on a semantic-graph sync run and why the inventory API returns `provider_unavailable` until one completes.

**Fabric pivot (2026-08-26):** Fabric/OneLake is now the unified inventory data platform and durable source of truth. The 07-01 characterization baseline and 07-02 neutral storage extraction remain valid. 07-03 through 07-06 have been replanned so inventory writes governed Fabric-backed datasets/tables, resource contracts serialize safely to Delta/Parquet/Fabric tables, PaaS and per-family availability land on those contracts, and read ports consume Fabric-backed inventory without Hermes lifecycle ownership.

PaaS resources are already ingested: `_entity_type_for_resource()` buckets every non-VM/Arc resource into `entities/Resource`. There is no acquisition gap for PaaS, only a projection, ownership, and read-model gap.

`intelligence/{governance,vulnerability,lifecycle,predeploy,change,patch}` have zero dataset reads today, so the inventory read contract can be established before six subsystems each grow their own resource-listing logic.

**Success Criteria** (what must be TRUE):

  1. Inventory refreshes and publishes its own Fabric/OneLake-backed datasets/tables without a semantic-graph sync run, and the semantic graph reads inventory as a consumer rather than producing it.
  2. Operators can inspect PaaS inventory grouped by resource type and SKU/tier, with the same scope enforcement, evidence, freshness, and pagination guarantees as OS and software inventory.
  3. A missing or degraded inventory family reports as partial for that family only, while every other family continues to serve.
  4. A single scope-enforced cross-family inventory read answers "what resources exist in this scope" for both the API and internal subsystems, with no consumer reading raw inventory datasets directly.
  5. Existing OS and software inventory behavior, dataset names, row shapes, and the failed-refresh retention rule are preserved without regression.
  6. Every consumer of `inventory/*` datasets reads through the inventory read port instead — specifically the one cross-domain read at `hermes_arg_connector/service.py:116` — with no direct dataset reads remaining outside the inventory domain. *(Broader consumer pivot — Hermes identity acquisition, API providers, web — is Phases 8 and 9.)*

**Sequencing note:** Ownership inversion must precede family expansion, but the inversion now targets Fabric/OneLake as the authoritative data platform. Extract shared dataset/generation machinery to a neutral module, define Fabric-backed inventory publication contracts, move normalization and acquisition into the inventory domain, and make inventory publish its own Fabric-backed datasets before adding the PaaS family or the generalized resource observation contract. Adding families first would deepen the coupling this phase removes. Consumer migration — including the Hermes side — comes last, once the read port is stable: **characterize → extract → Fabric-backed invert → expand → migrate consumers**.

**Entry gate: WAIVED by operator decision (2026-08-26).** The prior gate required Phase 6 UAT against live Azure before starting. The operator waived it on the grounds that Phase 7 relocates the very pipeline that UAT would exercise, making a pre-Phase-7 run largely disposable. Phase 6 UAT is therefore **not cancelled — it is deferred and folded into Phase 7's exit criteria**, paid once against the final pipeline instead of twice.

**Accepted risk:** Phase 7 proceeds without a verified live baseline. There is no known-good reference for real freshness, evidence, exact joins, or partial/outage behavior, so any live-only regression introduced by the refactor cannot be distinguished from a pre-existing Phase 6 defect. Mitigation is contract-level rather than empirical: preserve dataset names, row shapes, and the failed-refresh retention rule exactly; assert them with characterization tests written **before** any code moves.

**Deferred verification (now Phase 7 exit criteria, not entry):**

  1. Authenticated Azure/ARG/LAW walkthrough covering OS and software inventory end to end.
  2. Healthy and failed workspace refresh, including the failed-refresh retention rule.
  3. Unknown-OS lifecycle review: candidate inspection, explicit confirmation, refresh persistence, stale-revision conflict.
  4. Exact software/version search with linked and unlinked environment-bearing details.
  5. EOL citation review and external-provider configuration (`APPROVED_SEARCH_API_ENDPOINT` / `APPROVED_SEARCH_API_KEY`).
  6. Browser UX and accessibility walkthrough of the inventory pages.
  7. Triage the pre-existing `web/src/app/compliance/page.test.tsx` failure so full-suite green is a usable signal.

**Blast radius (measured, revised):** The often-quoted "53 files import `hermes_arg_connector`" measures module coupling, not inventory coupling, and overstates this phase. Re-measured against actual inventory usage: **6 source files and 4 test files** touch inventory data, and there is exactly **one** cross-domain read of an `inventory/*` dataset in the entire codebase (`hermes_arg_connector/service.py:116`, implementing the failed-refresh retention rule). `intelligence/{governance,vulnerability,lifecycle,predeploy,change,patch}` still have zero dataset reads, so there is no consumer sprawl to migrate — the read port can be established before those subsystems grow their own.

The genuinely wide step is extracting `DatasetStore`/generation machinery, which 15 files depend on; that extraction must preserve the public surface. The real risk is behavioral, not structural: (1) the failed-refresh retention rule, (2) publication timing — inventory currently publishes as a side effect of a graph sync, and `from_store()`'s all-or-nothing check is implicitly coupled to that, and (3) `_preserve_created_timestamps` / `_preserve_source_watermarks`, graph-level machinery inventory rides along with today. These three are what characterization tests must pin. See `07-RESEARCH.md` §6.3.

**Related windows:** `.planning/WINDOWS.md` #9-#12 (`unrun-verify`) and #13 (`deviation`) remain open and are re-scoped to close under Phase 7 exit rather than Phase 6.

**Sequencing decision:** the operator elected the **full Phase 7** path (ownership inversion first, then family expansion, then consumer migration) rather than the 7a/7b split. The split existed only to de-risk starting before Phase 6 sign-off; with the gate waived it adds a relocation cost for no benefit. See `07-RESEARCH.md` §6.

### Phase 8: Resource Identity Plane

**Goal:** As a platform operator, I want unified inventory to own the complete resource identity plane, so that the Hermes semantic graph performs graph construction, relationship modelling, and semantic traversal from inventory instead of querying ARG for resource identity itself.
**Requirements**: INV-07, INV-08, INV-10, INV-11, INV-12
**Depends on:** Phase 7
**Plans:** 3/6 plans executed
Plans:

- [x] 08-01-PLAN.md — Extend inventory read port with containment hierarchy; prove lossless equivalence for Hermes's real normalizer read patterns
- [x] 08-02-PLAN.md — Build the real Fabric-native topology-derivation pipeline (edges + NSG/flow-log network topology) and bind to Fabric IQ ontology
- [x] 08-03-PLAN.md — Run the Hermes-vs-Fabric viability comparison, produce the report, and execute the operator-approved retain/reduce/remove decision

**UI hint:** no

**Context:** `queries.py:build()` issues ~20 deterministic ARG query specs, then `Normalizer` maps known payloads into known entity/relationship rows and ontology metadata is generated from emitted row shapes. That is coded acquisition and normalization, not autonomous/self-learning discovery. Hermes independently queries `Resources` and `ResourceContainers` for the same resource identity that inventory owns, then normalizes it into 14+ `ENTITY_TYPES`. That duplicate acquisition path is what this phase removes; Hermes remains only if it adds graph-specific value such as relationship inference, topology modelling, confidence/provenance modelling, bounded traversal, semantic query APIs, and agent-safe context packaging.

**Scope boundary — identity vs. assessments.** Inventory owns the **resource identity plane**: what exists, of what type, where, with what attributes and containment. It does **not** absorb assessments *about* resources — patch compliance, vulnerabilities, policy state, advisor recommendations, metrics, health — which remain owned by their domains and join to inventory by resource ID. Nor does it absorb relationship/topology modelling, which is Hermes's actual job. Without this boundary the phase would produce a god module worse than the current coupling.

**Success Criteria** (what must be TRUE):

  1. Inventory exposes complete resource enumeration in scope across all resource types, not only VM/Arc families.
  2. Inventory carries the containment hierarchy (management group → subscription → resource group → resource) so no consumer needs a separate `ResourceContainers` acquisition path.
  3. Inventory preserves the full raw property bag per resource, losslessly enough that Hermes's normalizers, network modelling, and identity modelling read everything they read today.
  4. Inventory exposes per-family freshness and watermarks sufficient for incremental sync, with no regression to full refresh.
  5. Hermes builds and traverses the semantic graph from the inventory read port, with its ARG resource-identity queries removed and no separate "discovery agent" role preserved unless it adds graph-specific inference or context-packaging value.
  6. Assessment domains and relationship modelling are unchanged, joining to inventory by resource ID.
  7. A real Fabric-native Spark/KQL pipeline is built that reproduces Hermes's current relationship/topology construction (entity/edge derivation from ARG identity data, plus NSG+flow-log-derived network topology) directly against the Fabric lakehouse and exposes it through Fabric IQ ontology, and the same blast-radius scenarios are run against its output for the viability comparison — the gate must be decided from an actual working Fabric pipeline, not a documentation-based estimate.

**Primary risk:** criteria 3 and 4. If `ResourceObservation` projects a lossy subset of `properties`, or cannot express watermark semantics, Hermes must retain its own ARG path and the pivot fails. **Design the contract from Hermes's real read patterns, not from what the inventory UI displays.** See `07-RESEARCH.md` §7.3.

### Phase 9: Consumer Pivot

**Goal:** As a platform operator, I want the API and UI powered by unified inventory, so that every surface reflects one source of truth about what resources exist.
**Requirements**: INV-09, INV-10
**Depends on:** Phase 8
**Plans:** 11/11 plans executed

Plans:

- [x] 09-01-PLAN.md — Deliver the typed page-snapshot Network Copilot backend tracer and governed bounded findings loop
- [x] 09-02-PLAN.md — Pivot inventory consumers to the read port and configure named Foundry/Fabric IQ seams
- [x] 09-03-PLAN.md — Deliver the accessible contextual Copilot drawer across supported pages
- [x] 09-04-PLAN.md — Close stale/partial finding and complete snapshot resource-scope validation
- [x] 09-05-PLAN.md — Implement real bounded contextual orchestration and configurable Fabric IQ runtime wiring
- [x] 09-06-PLAN.md — Isolate, fix, or precisely assign the three full backend suite failures
- [x] 09-07-PLAN.md — Deliver the governed read-only Operations MCP server contract and adapter
- [x] 09-08-PLAN.md — Put the Operations MCP server behind Azure API Management with Terraform, policy, and rollback
- [x] 09-09-PLAN.md — Integrate named Foundry specialists and optional Fabric IQ grounding with live smoke validation (expanded to all 8 specialists; see 09-09-EXPANSION-PLAN.md)
- [x] 09-10-MAF-PIVOT-PLAN.md — Adopt Microsoft Agent Framework as the default question-first orchestrator across specialists
- [x] 09-11-AZURE-MCP-ACA-PLAN.md — Deploy Microsoft's official Azure MCP Server standalone in ACA behind APIM as a second, independent tool-caller for live Azure resource state; wire per-specialist tool registry, explicit dual-MCP routing rule, and (this session) network-specialist `arm_execute_query` access plus a classic-firewall inline rule-collection ingestion fix

**UI hint:** yes

**Context:** The API already has the right seam. `runtime.py` registers providers via `ProviderSpec`, and routers depend on providers rather than datasets — verified: no router reads `read_dataset` or `entities/` directly; only `runtime.py` does the wiring. The API pivot is therefore mostly a wiring change, not a router rewrite, and if route contracts hold, most web pages need no change.

The exception is `hermes_arg_connector/agent_queries.py`, which reads `entities/VirtualMachine`, `entities/ArcServer`, and `entities/PatchAssessment` directly. Its server/VM reads are identity-plane and move to the read port; its `PatchAssessment` reads stay with the patch domain.

The `/agents` page is not merely a static stub: `web/src/app/agents/page.tsx` calls `/api/v1/agents/catalog` and `/api/v1/agents/investigations`, and `src/api/routers/multi_agent.py` backs those routes with the deterministic `operations.autonomous_investigation` orchestrator. However, the specialist agents are currently in-process deterministic roles over governed tools, while Foundry is only an optional single `FoundryPromptAgent` narrator for already-collected evidence.

Phase 9 should position Operations Copilot as the single orchestrator entry point across pages. Each page supplies its current scoped context — for example selected resource, topology view, investigation objective, active filters, source freshness, and evidence rows — and Operations Copilot routes that context to specialized agents such as Network, Vulnerability, Patch, Incident, Change, Governance, Remediation, and Executive Summary. The page-local experience should therefore be "ask the copilot about this page" rather than "open a different agent app"; the orchestrator decides which specialists to invoke and returns cited analysis, synthesis, uncertainty, and next checks back into the current page.

Specialized LLM agents can provide page-specific analysis without fragmenting the UX. For example, a Network Agent on topology-oriented pages can compare the observed graph against design policy rules and Azure best practices, flag NSG/route/firewall/blast-radius gaps, explain evidence quality, and recommend bounded validation steps. Similar agents can analyze vulnerability exposure, patch urgency, incident timelines, change correlation, ownership/governance gaps, and remediation plans. Phase 9 planning should evaluate whether the specialist implementation remains deterministic with optional Foundry narration, uses Foundry prompt agents as specialist synthesizers, or migrates to Foundry-managed orchestration. Any option must preserve scoped evidence, visible uncertainty, no hidden chain-of-thought, human ledger controls, and degradation when Foundry is unavailable. Microsoft Foundry guidance favors prompt agents for managed no-code/low-code agents, hosted agents for custom orchestration, toolboxes/MCP for governed tools, and new Agent Service workflows over deprecated classic connected agents.

**Success Criteria** (what must be TRUE):

  1. API providers serving resource identity resolve through the inventory read port, with route contracts unchanged.
  2. `agent_queries.py` reads servers and VMs from the read port rather than `entities/*`, while patch assessment reads remain with the patch domain.
  3. Web pages surfacing resource identity are audited and confirmed to render from unified inventory, with per-family availability surfaced rather than an all-or-nothing outage.
  4. Page-level Operations Copilot entry points pass bounded page context to the shared orchestrator instead of duplicating agent UX or bypassing scope/evidence contracts.
  5. The `/agents` page and `/api/v1/agents/*` routes have an explicit Phase 9 implementation decision: retain deterministic in-process specialists with optional Foundry narration, integrate Foundry prompt agents as specialist synthesizers, or migrate to Foundry-managed agent orchestration. The selected path is tested against evidence grounding, scope isolation, audit ledger behavior, human controls, latency/timeouts, and Foundry-unavailable fallback.
  6. Specialized agents, starting with Network Agent, can produce cited page-specific analysis against design policy and Azure best practices without inventing unsupported topology, ownership, or remediation claims.
  7. No consumer anywhere reads raw `inventory/*` or identity `entities/*` datasets directly.

### Decision record — orchestration mechanism (closes Success Criterion 5)

**Selected path: local orchestration with Foundry prompt agents as tool-using specialists.**

Verified against the live deployment on 2026-08-30:

- `operations-copilot` is `kind: prompt` with an empty `tools` array. It is a
  narrator, not an orchestrator, and cannot delegate to anything.

- Each of the eight specialists (`aiops-network-agent` and peers) carries its
  own governed MCP toolset via APIM and orchestrates those tools itself.

- Routing is `page_kind -> specialist_id` in `run_context_investigation`. One
  entry point, no agent-to-agent hop.

"Operations Copilot is the single orchestrator entry point" is therefore
satisfied by the API surface (`/api/v1/copilot/investigate-context`), not by
the `operations-copilot` agent delegating to sub-agents.

**Why not agent-level delegation:** Foundry removed classic connected agents
from the new Agent Service in March 2026; the classic service retires in March

2027. Building `operations-copilot` as a delegating parent would target a

deprecated API. The current replacements are A2A (agent-as-tool) or Microsoft
Agent Framework for code-driven orchestration. Local orchestration already
gives us scope enforcement, budgets, the audit ledger, human controls, and
deterministic fallback when Foundry is unavailable -- the properties this
criterion requires.

**Correction applied:** the local layer had over-reached. It pre-computed
findings *and* instructed the specialist to answer "using only the operational
context below", which forbade the agent from calling its own MCP tools. Any
question naming a resource absent from the pre-computed context degraded into
an unrelated findings dump. The page context is now a starting point rather
than a ceiling; the specialist retrieves what it needs. Verified end-to-end:
"What depends on demo-vnet?" now calls `hub_dependents` and answers directly
with citations, where it previously returned unrelated `aiops-dev-vnet`
findings.

**Revisit when:** Microsoft Agent Framework orchestration is warranted if
cross-page questions need several specialists composed in one answer. That is
a deliberate future change, not a gap in this phase.

## Decision record — Microsoft Agent Framework evaluation (2026-08-30)

**Question:** Should Phase 09-09 migrate to Microsoft Agent Framework (MAF) for future-proofing?

**Decision:** No. Continue on Foundry prompt agents + Responses API.

**Evidence — we already use the current surface, not the deprecated one:**

| Surface | Retirement | Our usage |
|---|---|---|
| Assistants API | 2026-08-26 | not used |
| threads / runs | 2026-08-26 | not used |
| Connected agents | removed 2026-03-16 | not used |
| Portal workflow designer | 2026-12-01 | not used |
| Responses API (`/openai/v1/responses`) | current | **in use** |
| Prompt agents | current, supported in new Agent Service | **in use** (9 agents) |

Verified by `grep` for `assistants|/threads|/runs` in `src/operations/foundry_agent.py`
— zero matches. Sole endpoint is `/openai/v1/responses` (line 511).

**Why MAF does not apply:** MAF is a client-side orchestration SDK that calls the
same Responses API underneath. It would replace our local routing layer, not our
transport. Our governance controls (scope enforcement, audit ledger, human approval
gates, deterministic fallback) live in that layer; migrating means reimplementing
them in a third-party abstraction for no deprecation benefit.

**What was actually broken:** one sentence in `_build_prompt` — "using only the
operational context below" — forbade every specialist from calling its own governed
MCP tools. One line presented as nine broken agents. Fixed in `d43f0891`.

**Live verification after fix (3 of 9 specialists, distinct tool selection per domain):**

- `network` — called `network_topology`, `hub_dependents`; correctly answered no dependents on demo-vnet
- `vulnerability` — called `cve_exposure`, `cve_detail` x3; returned CVE list for vm1
- `governance` — called `fabric_iq_policy_context` + 5 others; correctly answered
  "I cannot determine" rather than speculating (grounding working as designed)

**Revisit if:** cross-page questions require composing several specialists in one
answer. MAF remains the right tool for that, and adopting it later is unblocked —
prompt agents are reusable as MAF-invoked agents.

## Evaluation — Microsoft Agent Framework (2026-08-30, supersedes the entry above)

The earlier entry dismissed MAF on stale assumptions. Re-evaluated against current
facts and a read-only audit of our own governance layer. **Revised verdict: MAF is
a credible future target, but is not the next step.**

### What changed

MAF reached **1.0 GA on 2026-04-03** (Python + .NET, MIT, production-supported;
successor to AutoGen and Semantic Kernel). It ships the things the earlier entry
assumed we would have to reimplement:

- native **MCP** support (agents consumable *and* exposable as MCP tools)
- first-class **Foundry** integration (`FoundryChatClient`)
- **human-in-the-loop approvals** (Agent Harness / ToolApprovalAgent middleware)
- **OpenTelemetry** instrumentation, checkpointing, durable session state

The "you'd reimplement your governance in someone else's abstractions" argument is
therefore weaker than stated. It is not zero, but it is not wholesale either.

### Audit of our governance layer (read-only, 2026-08-30)

Core: `src/operations/*.py` = **3,363 lines**, covered by **209 test functions**
across 21 files (~4,178 lines).

**Portable to MAF as-is (~1,100 lines)** — pure functions, no loop coupling:

- `page_context.py:160` `deterministic_network_findings` (~74 L, snapshot → findings)
- `tools.py:693` `TOOL_REGISTRY` + `call_tool:829` (unknown tool → `STATUS_DENIED`,
  deliberately never revealing that a tool exists)

- `tools.py:54` `_filter_scoped` / `:264` scope denial; `page_context.py:126`
  `validate_effective_scope`

- all of `foundry_agent.py` — per-agent field contracts (`:181-270`), the
  `evidence_refs` citation validator (`:268`), `_CircuitBreaker` (`:102`), retry/backoff

**Coupled to the custom loop, would need reimplementation (~500-600 lines)**, all in
`autonomous_investigation.py`: ledger assembly + `InvestigationLedgerStore:836`,
deterministic selection (`page_specialists:612`, `_select_agents:103`), the shared
`remaining_tools` budget and per-turn `AgentDefinition` re-narrowing (`:635-680`),
wall-clock `stop_reason` propagation, `_deterministic_plan:351`, `_failed_run:808`.

### Findings that outrank the MAF question

1. **Approval gates do not gate.** There is no enforcing check anywhere in the
   operations layer — no `requires_approval`, no `dry_run` guard. `human_controls.
   available_actions` (`:570`, `:795`) is ledger *metadata*, and `record_decision:851`
   appends to `approvals` **after** the fact. The sole `requires_approval: True` is a
   static field on generated plans (`remediation_generator.py:79`). Migrating to MAF
   would not fix this; it is a gap in our design, and MAF's ToolApprovalAgent is a
   genuine reason to reconsider later.

2. **The audit ledger is not durable.** `InvestigationLedgerStore` is an in-memory
   `OrderedDict` in a module-level singleton (`_LEDGER_STORE:877`), FIFO-evicted at
   `MAX_LEDGER_ENTRIES = 1000`, lost on every container restart. For an audit trail
   backing operator decisions on production infrastructure, this is the highest-risk
   item found — and it is independent of any orchestration framework.

3. **The model never selects the specialist.** Routing is the static `page_kind` dict
   at `:612`. Question-keyword routing (`_select_agents:103`) already exists but is
   wired only to the autonomous path, never the page drawer — which is precisely why
   the Network page answers network-shaped questions regardless of what was asked.

### Decision

Do not migrate now. Sequence:

1. **Durable ledger** — highest risk, framework-independent, needed either way.
2. **Enforcing approval gate** — close the real HITL gap before adding orchestration.
3. **Question-aware routing** — wire `_select_agents` into the page path (~1 day,
   reuses tested code, fixes the complaint that motivated this).

4. **Reassess MAF** once 1-3 land. By then the portable ~1,100 lines carry over
   cleanly, and the ~500-600 coupled lines are what MAF replaces rather than what we
   port. Prompt agents remain reusable as MAF-invoked agents, so nothing is a dead end.

Deprecation is **not** a forcing function: we are on the current Responses API with
zero exposure to the Aug 2026 Assistants retirement or the Mar 2026 connected-agent
removal (verified by grep — no `assistants`/`/threads`/`/runs` usage). Migrate for
capability when we need it, not for survival.

## Decision: the orchestrator is the deterministic loop, not `operations-copilot` (2026-08-30)

The stated design was "operations-copilot orchestrates and delegates to
specialists." That is not what runs, and after tracing it end to end the
current shape is the better one. Recording why, because the gap between the
stated design and the running system was itself a source of confusion.

**What actually runs.** `run_context_investigation` in
`src/operations/autonomous_investigation.py` is the orchestrator. It selects
specialists, executes their tools through the scope-filtered registry, records
every call in the ledger, and produces a deterministic synthesis. A Foundry
prompt agent is then handed the already-collected, already-scoped evidence and
asked to narrate it. Narration never invents facts and never fails the
investigation (`autonomous_investigation.py:425-428`).

**What `operations-copilot` is.** Evidence, not inference:

- `GET /agents/operations-copilot?api-version=v1` → `tools: NONE`. It is
  physically incapable of delegating.

- `grep -rn "operations-copilot" src/**/*.py` → **zero** references. Its only
  appearances are the Terraform default for `FOUNDRY_AGENT_NAME`
  (`variables.tf:369`) and test fixtures.
It is the default narrator identity, not an orchestrator.

**Why not promote it.** Delegation would move specialist and tool selection
into model output. Three current guarantees depend on that not happening:
scope filtering is applied to a fixed tool registry before execution; the
ledger is a complete record of what ran, because what ran was decided
deterministically; and a specialist that fails degrades to fewer findings
rather than to an unpredictable plan. An LLM router would trade all three for
flexibility we have not yet shown we need.

**What was actually broken** was narrower and is now fixed: routing consulted
`page_kind` alone and never the question, so a change question asked on the
Network page ran only the network specialist. Selection is now page-anchored
*and* question-aware (`2d4731a1`), verified live: "what changed recently?" on
the Network page routes `[network, change]`; "who owns this and is there an
approval?" routes `[network, governance]`; a topic-free question stays
`[network]`.

**Consequence for the MAF evaluation.** MAF's headline capability is exactly
the thing we are choosing not to adopt: model-driven multi-agent
orchestration. So the MAF question is not "does it work" but "do we want
model-chosen delegation at all, given governance depends on deterministic
selection?" That is now the real question, and it should be answered against
measured agent quality rather than framework features.

## Decision: MAF is now a measurable question, and the answer is "not yet" (2026-08-30)

Two earlier records argued this from framework features. Both were arguing
without an instrument. There is one now, and it changes what the question is.

### What the instrument found

`scripts/evaluate_agents.py` scores ten fixed questions against a deployment.
Its first three runs found three defects, none of which had been visible from
one-off probes:

1. **A metric that measured the caller, not the agent.** Groundedness was
   scored over snapshot-derived findings, so investigations whose specialists
   returned real resource IDs scored 0.0. Fixed in `ab017125`.

2. **A latency failure masquerading as a routing regression.** A 108s
   wall-clock timeout dropped a specialist; scoring routing on timed-out runs
   would have made the routing score a latency proxy. Now scored separately.

3. **One malformed tool call aborting entire investigations.** Foundry returns
   HTTP 400 for the *whole response* when any tool result carries
   `isError=true`. The governance specialist, routed onto the incident page,
   called `business_service_context` with no service name -- there is none in
   "what is the root cause of the latest incident?" -- and the operator got
   "Foundry narration unavailable" in ~6s with every other specialist's
   evidence discarded. Fixed in `78733fc7`.

The third is the one that matters for this decision. It had been dismissed as
Foundry flakiness. It was our bug, in our MCP server, and no framework change
would have fixed it.

### Measured baseline

    routing_rate           1.0    (9 scored, 1 wall-clock timeout)
    narration_rate         1.0    was 0.8 before the MCP fix
    groundedness_mean      0.44   was 0.29
    tool_correctness_mean  1.0
    latency_ms_median      25.6s

`groundedness` is a data-availability signal, not answer quality: `gov-owner`
scores 0.0 while correctly answering "I cannot determine who owns this from
the governed sources", and `vuln-remediate` scores 0.0 while naming a specific
KB and VM. Read as "how much did the deterministic layer have to stand on."

### The decision

**Stay on Foundry prompt agents. Revisit MAF against this baseline, not against
its feature list.**

Three reasons, in order of weight:

1. **The defects were ours.** Every failure the harness surfaced was in our
   routing, our metrics, or our MCP server. A framework migration would have
   carried all three across unchanged and cost weeks.

2. **MAF's headline capability is the one we are deliberately not adopting.**
   Its value is model-driven multi-agent orchestration. Our governance
   properties -- scope filtering applied to a fixed registry before execution,
   a ledger complete because selection was deterministic, graceful degradation
   when a specialist fails -- all rest on *not* letting a model choose what
   runs. Adopting MAF to then suppress its main feature is a poor trade.

3. **Zero deprecation exposure.** Prompt agents and the Responses API are the
   current supported surface. Nothing forces a move.

### What would change the answer

Concrete triggers, so this is falsifiable rather than a preference:

- Latency: median 25.6s is tolerable for investigation, poor for chat. If
  interactive latency becomes a requirement, MAF's streaming and parallel tool
  execution are a real argument.

- A question genuinely needing multi-turn planning -- where the second tool
  call depends on the first's *content*, not just its presence. Nothing in the
  current ten cases does.

- `routing_rate` falling as the catalog grows. Keyword routing is deterministic
  and auditable, but it does not generalise. If it drops below ~0.8 with more
  specialists, an LLM router earns its governance cost.

Re-run `python3 scripts/evaluate_agents.py --baseline .planning/eval/baseline.json`
before re-opening this. Argue from the numbers.

### Phase 10: Fabric Medallion Capability Expansion

**Goal:** Deliver a reliable, governed Fabric medallion platform whose Bronze, Silver, and Gold products are observable, freshness-bounded, consumable through curated semantic contracts, and consistently surfaced through the API and web application.
**Requirements**: MED-01, MED-02, MED-03, MED-04, MED-05, MED-06, MED-07, MED-08, MED-09, MED-10
**Depends on:** Phase 9
**Plans:** 15/15 plans executed

Plans:

- [x] 10-01-PLAN.md — Stabilize, verify, and commit existing uncommitted Defender/ontology work end-to-end (tracer)
- [x] 10-02-PLAN.md — Referential integrity & ownership/tag governance quality gate (MED-06)
- [x] 10-03-PLAN.md — Durable ontology publication terminal state & telemetry (MED-01)
- [x] 10-04-PLAN.md — Dataset-agnostic freshness/status/quality health provider (MED-03)
- [x] 10-05-PLAN.md — Publication manifest & lifecycle disposition registry (MED-09)
- [x] 10-06-PLAN.md — Change-domain ontology forwarding fix + predictive/remediation disposition audit (MED-04)
- [x] 10-07-PLAN.md — OneLake data access, capacity health, Delta maintenance, lineage surfacing (MED-10)
- [x] 10-08-PLAN.md — Historical retention extension for cost/compliance/patch/change/incident (MED-07)
- [x] 10-09-PLAN.md — Gold/Silver restoration, staged rollout & disposition classification (MED-02)
- [x] 10-10-PLAN.md — Direct Lake semantic model manager (MED-05)
- [x] 10-11-PLAN.md — Gold-grounding Data Agent client, contract & guardrails (MED-08, TDD)
- [x] 10-12-PLAN.md — Gold-grounding specialist wiring & evaluation dataset (MED-08)
- [x] 10-13-PLAN.md — Fabric medallion health & capabilities API (MED-03/09/10)
- [x] 10-14-PLAN.md — Web "Fabric medallion" tab on /connections (MED-03/09/10)
- [x] 10-15-PLAN.md — Live rollout validation & evaluation baseline (MED-02/08/10)

**Success Criteria** (what must be TRUE):

1. Ontology publication rejects undefined endpoint types before committing, retries transient publication failures within a bounded policy, emits actionable telemetry, and records an operator-visible terminal state.
2. Every expected Gold topology, assessment, and operational-context output is either live and verified or explicitly retired with a versioned compatibility disposition.
3. Bronze, Silver, Gold, and metadata datasets expose configurable freshness SLOs, source status, row-count and quality evidence through a scope-enforced API and the web application.
4. Code-declared Silver datasets have an evidence-backed disposition and all high-value operational gaps required by current API/web capabilities are populated and served.
5. Gold provides curated, versioned consumption contracts and a Direct Lake-compatible semantic serving definition without replacing the inventory read port as the resource-identity authority.
6. Graph publication enforces referential integrity and configurable ownership/tag quality thresholds while preserving uncertainty and avoiding unsupported relationship inference.
7. Historical facts needed for cost, compliance, patch, change, incident, and lifecycle trend analysis are retained under explicit history and retention contracts.
8. The Fabric Data Agent is grounded in curated Gold products and has reproducible offline and live evaluation coverage for groundedness, precision, freshness, and citation behavior.
9. Generated ontology projections are governed by a publication manifest and lifecycle state so consumers do not need to discover or depend directly on hundreds of physical tables.
10. Fabric-native and application-layer security, lineage, capacity health, and Delta maintenance controls are implemented, documented, observable, and verified in the deployed API and web experience.

### Phase 11: Cross-Page Operations Copilot Orchestration and Specialist Parity

**Goal:** Make Operations Copilot the single governed reasoning orchestrator across the web experience, with consistent page context, complete specialist/tool parity, cited cross-domain synthesis, and measurable behavior.
**Requirements**: COP-01, COP-02, COP-03, COP-04, COP-05
**Depends on:** Phase 10
**Plans:** 16 plans

Plans:

- [ ] 11-01-PLAN.md — Prove the production `/inventory` unified-orchestration tracer
- [ ] 11-13-PLAN.md — Project the inventory tracer through the canonical API, adapter, and drawer
- [ ] 11-02-PLAN.md — Complete canonical evidence snapshot identity, coverage, and citation semantics
- [ ] 11-04-PLAN.md — Expand the tracer manifest to twelve specialists and backend tool parity
- [ ] 11-05-PLAN.md — Project specialist parity through Terraform, packaging, and live validation
- [ ] 11-03-PLAN.md — Converge canonical API paths while retaining explicit legacy rollback/shadow seams
- [ ] 11-06-PLAN.md — Add durable authorized server continuity, conditional synthesis, and telemetry
- [ ] 11-14-PLAN.md — Carry same-tab opaque-thread continuity through the root browser provider
- [ ] 11-07-PLAN.md — Migrate the six existing drawer pages to typed adapters
- [ ] 11-15-PLAN.md — Integrate remediation through read-only explanation and governed handoff
- [ ] 11-08-PLAN.md — Integrate Defender, patch, change, and predeploy pages
- [ ] 11-09-PLAN.md — Integrate data health, governance, identity, FinOps, and resource health
- [ ] 11-10-PLAN.md — Integrate situation detail, services, and twin
- [ ] 11-16-PLAN.md — Enforce all 28 route dispositions and exact manifest/API/UI mapping parity
- [ ] 11-11-PLAN.md — Converge standalone, workspace, and multi-agent dedicated surfaces
- [ ] 11-12-PLAN.md — Evaluate and stage compatibility, shadow, canary, promotion, and rollback

**Success Criteria** (what must be TRUE):

1. Standalone, drawer, investigation-workspace, and multi-agent requests share one orchestration contract; the planner may select specialists and tools only from a versioned allowlist, with scope enforcement, bounded budgets, and deterministic fallback.
2. Every eligible operational page supplies typed page context with selected entities, filters, evidence, freshness, result coverage, and domain starter questions; utility and redirect routes have an explicit non-integration disposition.
3. Specialist runtime definitions, Foundry prompt/tool grants, Terraform wiring, API catalog, and UI presentation cannot silently drift, and missing inventory/data-health, identity, FinOps, and resource-health capabilities are covered.
4. Snapshot v2 preserves canonical identity and uncertainty, prioritizes and deduplicates evidence without implying full-dataset coverage from a visible page, and all synthesized claims cite authorized evidence.
5. Cross-page investigations retain a 12-turn, 1-hour-idle, 24-hour-absolute authorized same-tab thread; executive synthesis consumes cited specialist outputs; and automated evaluations enforce the predetermined routing, groundedness, citation, latency, reliability, and cost thresholds.

### Phase 12: Network Topology Integrity and Scale

**Goal:** Deliver a scope-safe, complete, scalable, and diagnosable network topology experience whose nodes, relationships, findings, policy changes, freshness, and evidence coverage remain accurate from inventory ingestion through API, web, agents, MCP, and export.
**Requirements**: TOPO-01, TOPO-02, TOPO-03, TOPO-04, TOPO-05
**Depends on:** Phase 10
**Plans:** 11/11 plans complete

Plans:

- [x] 12-01-PLAN.md — Scope-isolation tracer and security gate across web/API/service/agents/MCP and policy preview
- [x] 12-02-PLAN.md — Test harness, scale fixtures, and measured baseline gates
- [x] 12-03-PLAN.md — Identifier correctness, relationship retention, freshness threading, and peer resolution
- [x] 12-04-PLAN.md — Policy revision invalidation, declarative rule targets, and the client refetch primitive
- [x] 12-05-PLAN.md — Checkpoint: resolve Fabric and AI Services private-endpoint semantics before surfacing gaps
- [x] 12-06-PLAN.md — Private-link projection, provider type mapping, de-duplication, and official icons
- [x] 12-07-PLAN.md — Level of detail, lean payload, pagination, coverage disclosure, and drill-down route
- [x] 12-08-PLAN.md — Page-level honest totals, policy round-trip, and data-derived provenance
- [x] 12-09-PLAN.md — Canvas detail control, badge fan-out, live fold index, and disclosing footnote
- [x] 12-10-PLAN.md — Drawer states, on-demand drill-down, private-link facts, and self-describing export
- [x] 12-11-PLAN.md — Downstream compatibility contracts and representative scale validation

**Success Criteria** (what must be TRUE):

1. Scoped topology, gaps, rule findings, agents, and MCP expose no out-of-scope resource or relationship, preserve in-scope semantic edges, and do not fabricate missing-private-endpoint findings through asymmetric filtering.
2. Fabric capacities, Azure AI Foundry accounts, and all other in-scope private-link candidates appear exactly once and every open topology finding resolves to a visible or explicitly retrievable resource node.
3. Findings expose truthful totals and truncation; summary topology stays within a verified enterprise node/payload budget; detail is loaded on demand without silently changing downstream agent, MCP, or export contracts.
4. Enabling, disabling, creating, previewing, or deleting a design-policy rule refreshes derived gaps, findings, metrics, and badges without a reload, while invalid declarative rules fail visibly and are not persisted.
5. Relationship drops, normalization gaps, snapshot freshness, DNS/subnet/private-endpoint integrity, and flow-log provenance are observable and covered by regression, integration, and representative scale tests.

### Phase 13: Autonomous Ontology Discovery and Fabric Synchronization

**Goal:** Keep the Fabric ontology current without an open browser or manual Sync click by running durable, incremental discovery on a schedule, using a scoped Microsoft Foundry agent to propose evidence-backed relationships, and publishing only relationships that pass deterministic governance, validation, concurrency, and audit controls.
**Requirements**: AUTO-ONT-01, AUTO-ONT-02, AUTO-ONT-03, AUTO-ONT-04, AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07
**Depends on:** Phase 10, Phase 12
**Plans:** 19/22 plans executed
**Targeted review artifacts:** 1 (`13-07-TARGETED-PLAN.md`; review-only and excluded from the 21 numbered-plan denominator)

Plans:

Targeted review artifact (not a numbered executable plan):

- [x] 13-07-TARGETED-PLAN.md — Reviewed targeted deployment evidence; excluded from numbered plan accounting

- [x] 13-01-PLAN.md — Fail-fast Phase 10/12 preflight and non-authoritative Wave 0 contract tracer
- [x] 13-02-PLAN.md — Durable coordinator, run-once CLI, and enqueue-only Manual Sync intake
- [x] 13-03-PLAN.md — Incremental evidence, exact batch bounds, pending edges, and reconciliation
- [x] 13-04-PLAN.md — Bounded proposal-only prompt curator and four read-only tools
- [x] 13-05-PLAN.md — Hard server-side shadow admission and disabled pair-release eligibility machinery
- [x] 13-06-PLAN.md — Complete consumer inventory, generation resolver, and cutover compatibility
- [x] 13-07-PLAN.md — ACA Job, prompt-agent provisioning, publisher identity, and live RBAC evidence
- [x] 13-08-PLAN.md — Blocking consumer-cutover, publisher-RBAC, and agent-runtime decisions
- [x] 13-09-PLAN.md — Service-enforced CAS/fencing, immutable deterministic publication tracer, and rollback
- [x] 13-10-PLAN.md — Manual Sync delegation through the dedicated publisher
- [x] 13-11-PLAN.md — Durable versioned EvaluationSnapshot store and freshness reconstruction
- [x] 13-12-PLAN.md — Scope-enforced lifecycle and EvaluationSnapshot APIs
- [x] 13-13-PLAN.md — Approved `/connections` ontology automation and evaluation UI
- [x] 13-14-PLAN.md — Pinned Promptfoo evaluation and sanitized self-hosted Phoenix trace inspection
- [x] 13-15-PLAN.md — Exact alerts, durable shadow metrics, authoritative exclusion, and blocked release evidence
- [x] 13-16-PLAN.md — Exact coordinator matrix, durable starvation-free one-connection-per-pass eligible-set draining, reauthorizing intake, dispatch-only store, full reconciliation, and corrected Foundry transport
- [x] 13-17-PLAN.md — Exact publisher root/capability matrix, guarded publisher-only validation drill, ordered publication, and fenced rollback
- [x] 13-18-PLAN.md — Four-root read-only API, guarded maintenance intake, and reconstructed manual/publish/rollback topology tests
- [x] 13-19-PLAN.md — Exact process RBAC/env matrix, explicit dispatch deployment allowlist, isolated drill workspace, and immutable targeted rollout
- [ ] 13-20-PLAN.md — Three isolated live credential contexts plus deployed multi-connection drain, bounded maintenance, ARG, replacement, guarded stale-writer/rollback, and cleanup drills
- [ ] 13-21-PLAN.md — Dedicated live Playwright/API/RBAC audit and deployed-only fairness/matrix/allowlist/credential/drill shadow closeout

**Success Criteria** (what must be TRUE):

1. A durable scheduled coordinator refreshes every eligible connection without an open browser: each pass processes at most one connection, while a restart-safe eligible-set epoch and durable round-robin cursor skip terminal/duplicate work, rotate bounded retries behind later members, and drain every snapshotted connection to an exact terminal result or explicit closed exclusion. It prevents overlapping writers and retains the existing manual Sync action as an audited run-now/recovery control.
2. Incremental discovery packages only added, changed, retired, unresolved, or stale entities and relationships for evaluation, while periodic full reconciliation proves that incremental state has not drifted from authoritative inventory and Azure evidence.
3. A code-first Foundry prompt agent receives only scope-filtered, read-only evidence and approved ontology vocabulary, emits structured relationship proposals with citations and calibrated confidence, and cannot write authoritative Fabric ontology tables directly.
4. Every proposal is content-addressed, deduplicated, schema-checked, endpoint-resolved, scope-checked, vocabulary-checked, contradiction-checked, and recorded in an auditable lifecycle; a hard server-side shadow gate keeps all model-derived edges out of authoritative candidates until a separately audited predicate/type-pair release is enabled.
5. API, coordinator, and publisher match one exact connection/command/state/dispatch/publication root-capability matrix; the coordinator has no publication authority, `PublisherDispatchStore` uses only the dispatch root, and the separate least-privilege publisher validates, fences, promotes, checks all five consumers, and rolls back under its own identity. A default-off publisher-only validation drill may deterministically pause pre-CAS or fail one allowlisted post-check only in the isolated non-production validation workspace, with drill ID, expiry, audit, one-shot use, and cleanup.
6. Pending relationships, proposal decisions, run checkpoints, leases, publication attempts, failures, metrics, and versioned EvaluationSnapshot records are durable across restarts; stale or timed-out runs cannot continue writing over a newer successful generation, and stale evaluation evidence cannot authorize release.
7. Offline and live evaluations demonstrate no-click refresh, exact batch/token/deadline bounds, idempotent reruns, tenant/subscription isolation, prompt-injection resistance, publisher separation, explicit dispatch deployment-address coverage, three isolated least-privilege live service-principal contexts with no credential bleed, exact production alerts, relationship precision/recall thresholds, safe degradation, guarded stale-writer/rollback drills, consumer cutover, and complete sanitized operator-visible audit history.
