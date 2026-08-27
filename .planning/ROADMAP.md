# Roadmap: Azure AI Operations Platform

## Overview

This milestone turns the existing Azure and Fabric foundations into a controlled vertical MVP: operators detect and investigate cross-domain situations, receive evidence-backed recommendations, approve bounded actions, and observe durable execution and verification. Domain coverage and pilot readiness follow only after the core safety and audit loop is proven.

## Phases

- [x] **Phase 1: Evidence and Situation Foundation** - Establish durable situations, governed evidence, source quality, authorization, and audit primitives.
- [ ] **Phase 2: Investigation, Recommendation, and Approval** - Deliver bounded investigation, cited recommendations, and server-enforced approval.
- [ ] **Phase 3: Safe Remediation Execution** - Execute one or two typed, allowlisted actions with preview, durable jobs, verification, and bounded retries.
- [ ] **Phase 4: Domain Coverage and Operational Twin** - Prove representative incident, exposure, vulnerability, and twin-discrepancy workflows with replayable views.
- [ ] **Phase 5: Controlled Pilot Readiness** - Validate failure behavior, stale sources, authorization boundaries, rollout controls, and operator readiness.
- [~] **Phase 6: Software and OS Inventory Visibility** - Deliver scoped, evidence-backed OS and installed-software inventory with lifecycle risk and export. *(code-complete; awaiting UAT sign-off)*
- [ ] **Phase 7: Unified Resource Inventory** - Establish Fabric/OneLake-backed inventory as the unified data platform for every resource family including PaaS, consumed by the semantic graph and other subsystems rather than owned by them.
- [ ] **Phase 8: Resource Identity Plane** - Extend inventory to own complete resource identity — all types, containment hierarchy, raw properties, and watermarks — so Hermes stops querying ARG for resource identity and consumes inventory for graph construction, relationship modelling, and semantic traversal.
- [ ] **Phase 9: Consumer Pivot** - Repoint API providers, agent queries, and affected web pages at the inventory read port so the UI is powered by unified inventory.

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
| 6. Software and OS Inventory Visibility | 9/9 | Code-complete, UAT pending | - |
| 7. Unified Resource Inventory | 6/6 | Implementation complete; live verification pending | - |
| 8. Resource Identity Plane | 3/3 | In Progress|  |
| 9. Consumer Pivot | 0/TBD | Not started | - |

### Phase 6: Software and OS Inventory Visibility

**Goal:** Operators can inspect authorized, evidence-backed OS and installed-software inventory across Azure VMs and Arc-enabled servers, understand lifecycle risk, and export exact software/version matches for follow-up.
**Requirements**: INV-01, INV-02, INV-03, INV-04, INV-05, INV-06
**Depends on:** Phase 5
**Plans:** 9/9 plans executed

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
**Plans:** 3/3 plans executed
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
**Plans:** TBD
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
