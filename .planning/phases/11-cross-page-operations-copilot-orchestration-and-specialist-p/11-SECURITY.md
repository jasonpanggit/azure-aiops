---
phase: 11
slug: cross-page-operations-copilot-orchestration-and-specialist-p
status: verified
threats_open: 0
asvs_level: 1
created: 2026-09-08
---

# Phase 11 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Browser → canonical API | Page observations, selected entities, hints, and opaque thread handles cross into authenticated server policy. | Authorized but untrusted page context and user input |
| Model → orchestration policy | Model-proposed specialists, tools, scopes, budgets, DAGs, and citations cross into deterministic authorization. | Untrusted candidate plans |
| Manifest → runtime and deployment | The reviewed specialist portfolio becomes API, MCP, Foundry, Terraform, and browser projections. | Read-only grants and deployment metadata |
| API → durable thread store | Principal- and scope-bound results cross persistence and cache boundaries. | Historical findings, evidence, citations, and opaque IDs |
| Runtime → telemetry and release evidence | Controlled operational measurements cross into monitoring and release artifacts. | Enumerated metadata, aggregate metrics, and decisions |
| Copilot result → remediation UI | Advisory findings appear beside independently governed production controls. | Read-only explanations and handoff identifiers |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-11-01 | Elevation | orchestration policy | critical | mitigate | Exact specialist/tool/scope/budget/DAG/citation/mutation validation runs before dispatch (`src/operations/orchestration_policy.py:65-162`; `tests/test_orchestration_policy.py:171-199`). | closed |
| T-11-02 | Information disclosure | thread store | high | mitigate | Opaque server IDs, owner checks, scope checks, TTLs, and uniform not-found semantics (`src/operations/investigation_thread_store.py:403-553`). | closed |
| T-11-03 | Tampering | manifest/MCP grant | high | mitigate | Strict manifest schema and exact read-only grant projection reject credentials and mutation grants (`tests/test_orchestration_parity.py:163-170,384-532`). | closed |
| T-11-04 | Denial of service | planner/tool fan-out | medium | mitigate | Specialist, depth, token, and wall-clock bounds produce explicit partial outcomes (`src/operations/orchestration_policy.py:33-36,90-162`; `src/operations/orchestration_service.py:478-570`). | closed |
| T-11-05 | Spoofing | entity references | high | mitigate | Canonical resource/domain resolution and effective-scope authorization ignore browser authority claims (`src/operations/page_context.py:41-146,275-320`). | closed |
| T-11-06 | Tampering | evidence retention | high | mitigate | Stable evidence identities, conflict-set retention, deterministic ranking, and retained-reference closure (`src/operations/page_context.py:176-240,339-429`). | closed |
| T-11-07 | Information disclosure | scope filtering | high | mitigate | Authorization precedes retention and serialization (`src/operations/page_context.py:275-320`; `tests/test_page_context_v2.py:141-166`). | closed |
| T-11-08 | Denial of service | snapshot parser | medium | mitigate | Snapshot, row, list, selected-entity, citation, and byte bounds are enforced before processing (`src/operations/orchestration_contract.py:14-19,107-203`). | closed |
| T-11-09 | Elevation | candidate validator | critical | mitigate | Full-plan allowlists, scope intersection, schema, DAG, budget, citation, and mutation denial execute before I/O (`src/operations/orchestration_policy.py:65-162`). | closed |
| T-11-10 | Tampering | compatibility adapters | high | mitigate | Canonical and compatibility routes share the same policy/evidence service with parity tests (`src/api/routers/copilot.py:756-846`; `tests/test_orchestration_parity.py:337-370`). | closed |
| T-11-11 | Repudiation | legacy ledger projection | medium | mitigate | Durable immutable turns retain source contract and historical observation status (`src/operations/investigation_thread_store.py:158-207,628-678`). | closed |
| T-11-12 | Information disclosure | route errors | high | mitigate | Every canonical boundary injects current principal/scope and maps foreign, expired, or out-of-scope threads to not found (`src/api/routers/copilot.py:968-997,1120-1167`). | closed |
| T-11-13 | Elevation | specialist grants | high | mitigate | Manifest parsing asserts exact implemented-tool membership, read-only mode, and forbidden mutation grants (`src/operations/orchestration_policy.py:110-135`; `tests/test_orchestration_parity.py:163-170`). | closed |
| T-11-14 | Tampering | manifest projections | high | mitigate | One committed manifest drives exact backend, Terraform, API, and frontend projections (`infra/terraform/foundry.tf:13-42`; `web/src/lib/copilot/page-adapters.manifest-parity.test.ts:92-187`). | closed |
| T-11-15 | Information disclosure | specialist outputs | medium | mitigate | Scope filtering and retained-citation validation bound serialized specialist output (`src/api/routers/copilot.py:425-496`; `src/operations/orchestration_service.py:608-659`). | closed |
| T-11-16 | Elevation | Terraform grants | high | mitigate | Manifest-derived grants and promotion gates require exact validated provider/tool mappings (`infra/terraform/foundry.tf:13-42,1153-1187`; `tests/test_specialist_manifest_packaging.py:174-193`). | closed |
| T-11-17 | Tampering | package/deployment | high | mitigate | Packaging checks, manifest digests, immutable provider IDs, and validate-before-activation gates fail closed (`tests/test_specialist_manifest_packaging.py:109-165,535-555,631-678`). | closed |
| T-11-18 | Information disclosure | rollout scripts | medium | Reports carry controlled IDs/status/counts and tests prove credential values are absent (`tests/test_specialist_manifest_packaging.py:332-342,459-473`). | closed |
| T-11-19 | Information disclosure | thread continuity | high | Principal recheck, scope intersection, TTL/bounds, and not-found mismatch semantics apply on every access (`src/operations/investigation_thread_store.py:285-295,523-553,662-712`). | closed |
| T-11-20 | Tampering | executive claims | high | Synthesis admits only citation-closed claims over retained specialist evidence and degrades to deterministic findings (`src/operations/orchestration_service.py:672-793`). | closed |
| T-11-21 | Information disclosure | telemetry | high | Telemetry records controlled stage/specialist/status/count/budget metadata rather than questions, arguments, or evidence payloads (`src/operations/orchestration_service.py:805-842`). | closed |
| T-11-22 | Denial of service | synthesis | medium | At most one optional synthesis call is constrained by the existing wall-clock and evidence budgets (`src/operations/orchestration_service.py:672-757`). | closed |
| T-11-23 | Tampering | route adapters | medium | Stable SHA-256-backed identities, explicit freshness, and visible/total/truncation coverage are centralized and fixture-tested (`web/src/lib/copilot/page-adapters.ts:302-540,2595-2792`). | closed |
| T-11-24 | Elevation | remediation handoff | high | Adapters emit `actionable: false` and `mutation_authorized: false`; approval and execution remain separate server workflows (`web/src/lib/copilot/page-adapters.ts:727-740,2689-2690`; `tests/test_api_copilot_unified.py:2933-2963`). | closed |
| T-11-25 | Information disclosure | page continuity | high | Browser retains only an opaque handle and requires server revalidation after scope changes (`web/src/lib/copilot/thread-context.tsx:186-210,389-397`; `web/src/lib/copilot/thread-context.test.tsx:226-483`). | closed |
| T-11-26 | Tampering | partial security evidence | high | Adapters retain explicit source status, totals, freshness, and truncation and never present unavailable data as complete (`web/src/lib/copilot/page-adapters.ts:2670-2792,2918-2954`). | closed |
| T-11-27 | Elevation | patch/change handoff | high | Specialist/tool hints are manifest-validated candidates and every adapter remains read-only (`web/src/lib/copilot/page-adapters.manifest-parity.test.ts:115-145`; `src/operations/orchestration_policy.py:84-135`). | closed |
| T-11-28 | Spoofing | KB/change identity | medium | Stable source namespace/kind/key identities and citations are preserved by the central adapter (`web/src/lib/copilot/page-adapters.ts:302-540,727-740`). | closed |
| T-11-29 | Information disclosure | identity adapter | high | Identity context contains only already-authorized bounded fields; canonical server entity resolution rechecks scope (`web/src/lib/copilot/page-adapters.ts:4410-4458`; `src/operations/page_context.py:121-146`). | closed |
| T-11-30 | Tampering | cost/health completeness | medium | Time windows, currencies, totals, coverage, and source states stay explicit (`web/src/lib/copilot/page-adapters.ts:4549-4621`). | closed |
| T-11-31 | Tampering | optional provider state | high | Unavailable, partial, blocked, and empty states remain distinct with deterministic evidence fallback (`web/src/lib/copilot/page-adapters.ts:3893-3967,4306-4334`). | closed |
| T-11-32 | Tampering | graph context | high | Provenance, truncation, scenario markers, stale status, and retained citations are explicit (`web/src/lib/copilot/page-adapters.ts:4788-4895,4998-5024`). | closed |
| T-11-33 | Information disclosure | service continuity | high | New snapshots and thread references are always reauthorized under current principal and scope (`src/api/routers/copilot.py:968-997,1120-1167`). | closed |
| T-11-34 | Repudiation | route disposition | low | accept | Filesystem-derived route inventory and explicit disposition reasons make exclusions auditable (`web/src/lib/copilot/page-adapters.test.ts:3702-3754`). | closed |
| T-11-35 | Tampering | client converters | high | Dedicated and compatibility surfaces converge on canonical policy, evidence, scope, and fallback semantics (`tests/test_api_copilot_unified.py:107-137`; `tests/test_orchestration_parity.py:337-370`). | closed |
| T-11-36 | Elevation | ledger actions | high | Principal isolation and ledger decisions confer no execution authority (`tests/test_api_copilot_unified.py:2882-2963`). | closed |
| T-11-37 | Spoofing | UI agent catalog | medium | UI specialist ownership and deployment metadata are manifest/API-backed rather than local invented cards (`web/src/lib/copilot/page-adapters.manifest-parity.test.ts:92-187`). | closed |
| T-11-38 | Tampering | evaluation thresholds/results | high | Versioned corpus/threshold loaders, deterministic gates, provenance checks, and impossible-PROMOTE validation are committed (`scripts/evaluate_agents.py:75-81,507-542,688-823`). | closed |
| T-11-39 | Denial of service | canary/live evaluation | medium | Live calls have explicit timeouts; release gates HOLD on reliability/latency regressions and preserve rollback targets (`scripts/evaluate_agents.py:369-427,761-791`; `tests/test_specialist_manifest_packaging.py:631-678,1011-1154`). | closed |
| T-11-40 | Information disclosure | evaluation artifact | high | Artifact validation accepts controlled version/revision/gate/decision metadata; it does not require prompts, principals, thread IDs, arguments, or resource IDs (`scripts/evaluate_agents.py:796-905`). | closed |
| T-11-41 | Elevation | rollout mode | high | All modes retain the same deterministic read-only policy and mutation fence (`src/operations/orchestration_policy.py:65-135`; `tests/test_context_specialist_routing.py:160-169`). | closed |
| T-11-42 | Elevation | inventory hints | high | Hints are typed candidate inputs and only dispatch after policy validation (`src/operations/orchestration_service.py:1116-1236`; `src/operations/orchestration_policy.py:79-135`). | closed |
| T-11-43 | Tampering | page coverage/citations | high | Stable evidence keys, exact coverage counts, and submitted-context tests preserve source meaning (`web/src/lib/copilot/page-adapters.ts:463-540,2670-2792`; `tests/test_page_context_v2.py:170-399`). | closed |
| T-11-44 | Information disclosure | browser continuity | high | Browser stores only opaque thread ID/revision; API rechecks principal and scope (`web/src/lib/copilot/thread-context.test.tsx:226-483`; `src/operations/investigation_thread_store.py:523-553`). | closed |
| T-11-45 | Information disclosure | thread provider | high | Same-tab session storage contains no transcript and possession never bypasses server ownership/scope checks (`web/src/lib/copilot/thread-context.tsx:186-210`; `src/operations/investigation_thread_store.py:523-553`). | closed |
| T-11-46 | Tampering | historical evidence UI | high | Historical evidence is explicitly marked non-current and scope narrowing redacts wider turns (`web/src/lib/copilot/page-adapters.ts:5522`; `web/src/components/ui/CopilotDrawer.test.tsx:955-1063`). | closed |
| T-11-47 | Elevation | remediation handoff | critical | Canonical result and page adapter types make mutation authorization impossible; server eligibility and approval routes remain authoritative (`src/operations/orchestration_contract.py:337-352`; `web/src/lib/copilot/page-adapters.ts:2689-2690`). | closed |
| T-11-48 | Tampering | historical eligibility | high | Current server projection wins and historical records are visibly non-current (`src/operations/investigation_thread_store.py:158-207,696-759`; `web/src/lib/copilot/page-adapters.ts:5522`). | closed |
| T-11-49 | Elevation | frontend specialist hints | high | Bidirectional manifest/API/adapter equality rejects invented owners and ungranted tools; backend policy still authorizes dispatch (`web/src/lib/copilot/page-adapters.manifest-parity.test.ts:92-187`; `src/operations/orchestration_policy.py:110-135`). | closed |
| T-11-50 | Repudiation | route exclusions | low | accept | Exact route inventory and asserted reasons make every non-integration auditable (`web/src/lib/copilot/page-adapters.test.ts:3702-3754`). | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-11-01 | T-11-34 | A dedicated registry and filesystem-derived tests provide adequate auditability for route dispositions; no runtime privilege or data boundary depends on the registry. | Phase 11 plan | 2026-09-08 |
| AR-11-02 | T-11-50 | Explicit reasons and exact route-set equality make exclusions reviewable; the backend remains the authority for any integrated route. | Phase 11 plan | 2026-09-08 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-08 | 50 | 50 | 0 | GitHub Copilot secure-phase artifact audit |

The dedicated security-auditor subprocess returned no actionable audit output. Per the workflow fallback, the authored Phase 11 STRIDE register was checked directly against committed implementation and regression-test evidence at ASVS level 1. Plan 11-12 Task 3's missing live release baseline is a release-verification gap, not an unimplemented security mitigation; promotion remains fail-closed until that evidence exists.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-08
