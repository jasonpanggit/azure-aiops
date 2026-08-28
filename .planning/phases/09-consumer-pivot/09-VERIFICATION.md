---
phase: 09-consumer-pivot
verified: 2026-08-28T07:40:00Z
status: gaps_found
score: 5/10 must-haves verified
behavior_unverified: 1
overrides_applied: 0
gaps:
  - truth: "Network findings distinguish stale or partial evidence from verified actionable findings."
    status: failed
    reason: "A stale freshness record still produces status=verified, confidence=high, and actionable=true."
    artifacts:
      - path: "src/operations/page_context.py"
        issue: "deterministic_network_findings sets stale=true but derives status/actionable from row.status only."
    missing:
      - "Downgrade stale/partial findings to an uncertainty-qualified non-actionable state."
  - truth: "The contextual Copilot request is scope-safe for all submitted snapshot evidence and selected resources."
    status: failed
    reason: "Effective-scope validation checks selected-resource attributes only when supplied and does not validate evidence row resource IDs or resource IDs without attributes."
    artifacts:
      - path: "src/operations/page_context.py"
        issue: "validate_effective_scope does not scope-check evidence rows and conditionally checks selected resource attributes."
      - path: "src/api/routers/copilot.py"
        issue: "The route relies on the incomplete snapshot scope validation before returning findings."
    missing:
      - "Validate every selected/evidence resource against server-derived effective scope or reject unverifiable rows."
  - truth: "The bounded plan/observe/delegate/request-evidence/reassess loop performs governed bounded delegation rather than only labeling stages."
    status: failed
    reason: "run_context_investigation appends delegate/reassess labels but performs no specialist delegation, no concurrency budget, and no reassessment; named rechecks are only copied into ledger tool_calls."
    artifacts:
      - path: "src/operations/autonomous_investigation.py"
        issue: "Context loop has stage labels and a timeout check, but no governed specialist execution or bounded concurrency enforcement."
    missing:
      - "Implement or explicitly narrow the contextual loop contract and test actual delegation, evidence requests, reassessment, concurrency, and timeout behavior."
  - truth: "Fabric IQ is wired as an opt-in governed enrichment when configured, while remaining non-authoritative for identity."
    status: failed
    reason: "ApiContext exposes fabric_iq_provider, but production runtime unconditionally wires fabric_iq_provider=lambda: None; no configured provider can reach the adapter."
    artifacts:
      - path: "src/api/runtime.py"
        issue: "Runtime wiring makes Fabric IQ permanently unavailable."
      - path: "src/operations/tools.py"
        issue: "The adapter exists, but is not reachable from the managed runtime."
    missing:
      - "Add runtime/provider configuration for a real or explicitly injected governed Fabric IQ adapter."
---

# Phase 9: Consumer Pivot Verification Report

**Phase Goal:** As a platform operator, I want the API and UI powered by unified inventory, so that every surface reflects one source of truth about what resources exist.
**Verified:** 2026-08-28T07:40:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | API identity providers resolve through the inventory read port with unchanged route contracts. | ✓ VERIFIED | `src/api/runtime.py` registers `inventory_read_port`; `InventoryReadPort` is runtime-bound and focused runtime/read-port tests pass. |
| 2 | `agent_queries.py` uses inventory identity while patch assessments remain a separate domain join. | ✓ VERIFIED | `ContextQueryService` reads `_adapter.resources()` and joins patch rows by `targetResourceId`; focused agent-query tests pass. |
| 3 | Per-family degradation preserves usable rows and family status. | ✓ VERIFIED | `InventoryReadPort.list_resources()` returns rows, `family_availability`, and warnings together; focused inventory/runtime tests pass. |
| 4 | Supported pages submit bounded typed visible context through the shared drawer. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Typed builder, six page integrations, and drawer tests exist; no browser/API runtime test proves each page's rendered state is the exact submitted state. |
| 5 | The shared drawer is accessible and `/agents` remains the full workspace. | ✓ VERIFIED | Shared `CopilotDrawer`/`CopilotDrawerButton`, dialog semantics, Escape handling, live status, and independent `/agents` route are present; focused tests and lint pass. Visual/assistive verification remains human-only. |
| 6 | Loading, partial, deterministic fallback, retry, and failure states are distinct and honest. | ✓ VERIFIED | Drawer has separate live-region strings and retry/fallback/partial branches; focused Copilot tests pass. |
| 7 | Operations Copilot is bounded and agentic across plan/observe/delegate/request-evidence/reassess. | ✗ FAILED | The contextual function emits stage names but does not delegate a specialist or perform reassessment; it only records named recheck IDs. |
| 8 | Network findings are deterministic, cited, uncertainty-qualified, and non-actionable when evidence is stale/partial. | ✗ FAILED | Deterministic checks include check/policy IDs and evidence refs, but an independently probed stale snapshot returned `status=verified`, `confidence=high`, `stale=true`, and `actionable=true`. |
| 9 | Foundry specialists have a separate boundary and deterministic fallback; Fabric IQ is governed and optional. | ✗ FAILED | Specialist catalog/provisioning metadata and fallback tests pass, but runtime Fabric IQ wiring is hardcoded to `None`. |
| 10 | No consumer reads raw inventory or identity datasets directly. | ? UNCERTAIN | The phase guard passes for its limited paths, but it is not repository-wide; `src/onboarding/query_catalog.py` still defines `Resources`/`ResourceContainers` acquisition specs and `graph_normalize.py` retains ARG provenance. Human/owner decision is needed on whether these are authorized acquisition seams or prohibited consumers. |

**Score:** 5/10 truths verified (1 present, behavior-unverified)

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/operations/page_context.py` | Versioned bounded snapshot and finding contracts | ⚠️ PARTIAL | Substantive and used, but evidence/resource scope enforcement and stale-state semantics are incomplete. |
| `src/api/routers/copilot.py` | Snapshot-aware API route and ledger response | ✓ VERIFIED | `POST /api/v1/copilot/investigate-context` validates, runs, stores, and returns snapshot hash/version and ledger data. |
| `src/operations/autonomous_investigation.py` | Governed bounded contextual orchestration | ✗ STUB/PARTIAL | Legacy autonomous orchestration is substantive; contextual path is mostly stage bookkeeping. |
| `src/onboarding/agent_queries.py` | Inventory-read-port identity consumer | ✓ VERIFIED | Runtime adapter path and patch-domain separation are present. |
| `src/operations/foundry_agent.py` | Separate specialist metadata and fallback client | ✓ VERIFIED | Eight specialist IDs, versions, legacy Network fallback, retries, circuit breaker, and curated prompt are present. |
| `src/operations/tools.py` | Allowlisted Fabric IQ boundary | ⚠️ ORPHANED | Adapter and allowlisted tools exist, but runtime always supplies no provider. |
| `web/src/components/ui/CopilotDrawer.tsx` | Shared accessible staged drawer | ✓ VERIFIED | Shared component renders cited findings/tool status and explicit fallback/error states. |
| `web/src/app/{page,network,exposure,compliance,situations,remediation}.tsx` | Page-specific snapshot wiring | ✓ VERIFIED | All six planned page paths call the shared builder/drawer; exact runtime payload behavior is not browser-proven. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Page components | Context API | `CopilotDrawer` → `copilotApi.investigateContext` | ✓ WIRED | Drawer posts the supplied typed snapshot with the current question. |
| Context API | Scope enforcement | `investigate_context` → `snapshot.validate_effective_scope` | ✗ NOT_WIRED | Validator does not cover evidence resource IDs or selected resources lacking attributes. |
| Context API | Deterministic Network checks | `run_context_investigation` → `deterministic_network_findings` | ✓ WIRED | Submitted evidence is consumed directly. |
| Findings | Foundry narration | `run_context_investigation` → optional `foundry_agent.answer` | ✓ WIRED | Foundry receives findings only; fallback is explicit. |
| Runtime | Fabric IQ tools | `ApiContext.fabric_iq_provider` → adapter | ✗ NOT_WIRED | Runtime provider is unconditionally `lambda: None`. |
| Agent queries | Inventory identity | `ContextQueryService` → `InventoryReadAdapter` → `InventoryReadPort` | ✓ WIRED | Patch rows remain separate compatibility/domain data. |
| `/agents` | Full investigation workspace | page → `/agents/catalog`, `/agents/investigations` | ✓ WIRED | Existing activity, reconciliation, evaluation, ledger, and human-control UI remains. |

## Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| Network snapshot | `evidence` | Rendered topology/gap/rule results | Yes | ✓ FLOWING |
| Context findings | `snapshot.evidence` | Submitted page snapshot | Yes | ⚠️ HOLLOW scope boundary |
| Agent query identity | `resources` | Runtime-bound `InventoryReadPort` over inventory service | Yes | ✓ FLOWING |
| Fabric IQ enrichment | `raw` in `FabricIQToolAdapter.run` | Runtime provider | No in production runtime | ✗ DISCONNECTED |
| Foundry narration | curated findings/context | Optional configured Foundry agent | Tenant-dependent | ⚠️ EXTERNAL/UNCERTAIN |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Phase 9 backend focused tests | `uv run python -m pytest tests/test_page_context.py tests/test_api_copilot_snapshot.py tests/test_api_copilot_investigation.py tests/test_network_analysis.py tests/test_agent_queries.py tests/test_inventory_read_port.py tests/test_api_runtime.py tests/test_foundry_agent.py tests/test_fabric_client.py tests/test_inventory_consumer_guards.py -q` | 115 tests passed | ✓ PASS |
| Web focused Copilot tests | `cd web && npm test -- --run ...Copilot... ...agents/page.test.tsx` | 5 tests passed | ✓ PASS |
| Web lint | `cd web && npm run lint` | No ESLint warnings/errors | ✓ PASS |
| Production build | `cd web && npm run build` | Build succeeded; repeated MSAL `window is not defined` prerender messages | ✓ PASS |
| Stale finding invariant | direct Python probe using stale freshness | Returned actionable verified finding | ✗ FAIL |
| Full backend suite | `uv run python -m pytest -q` | 3 failures, 1532 passed, 2 warnings; all three reproduce at detached pre-Phase-9 boundary `1b730f77` | ⚠️ BASELINE FAILURES — ownership recorded in `09-REGRESSION-OWNERSHIP.md`; no Phase 9 regression |
| Full web suite | `cd web && npm test -- --run` | Exit code 0 | ✓ PASS |

## Probe Execution

No phase-declared or conventional `scripts/*/tests/probe-*.sh` probe was found.

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| INV-09 | 09-01, 09-02, 09-03 | Per-family availability/status never blanks the whole inventory capability | ⚠️ NEEDS HUMAN / PARTIAL | Read-port status is preserved and web tests pass, but live page state and all-family degradation are not browser/live verified. |
| INV-10 | 09-01, 09-02, 09-03 | Consumers use one scope-enforced inventory contract and no raw identity reads | ✗ BLOCKED | Main agent-query path is migrated, but contextual snapshot scope validation is incomplete and repository-wide guard coverage is not exhaustive. |

No additional Phase 9 requirement IDs are mapped in `REQUIREMENTS.md`; no orphaned Phase 9 requirement was found.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `src/operations/page_context.py` | 148-150 | Stale evidence sets `stale` but does not affect verified/actionable classification | 🛑 Blocker | Operators may treat stale evidence as verified remediation-capable evidence. |
| `src/api/runtime.py` | 1652 | `fabric_iq_provider=lambda: None` | 🛑 Blocker | Fabric IQ adapter cannot be used when configured. |
| `src/operations/autonomous_investigation.py` | 522-540 | Contextual loop records stage names without specialist delegation/reassessment | 🛑 Blocker | The claimed bounded agentic loop is not implemented end-to-end. |
| `src/operations/page_context.py` | 104 | Conditional scope check only for resources with attributes; no evidence-row check | 🛑 Blocker | Out-of-scope snapshot evidence can become returned findings. |
| `web/src/components/ui/CopilotDrawer.tsx` | 305 | `placeholder` input text | ℹ️ Info | Normal form affordance, not an implementation stub. |

## Human Verification Required

### 1. Contextual page UX and assistive technology

**Test:** Open Network, home, exposure, CVE detail, compliance, situations, and remediation at desktop and narrow widths. Launch with mouse and keyboard, inspect focus, Escape, dialog/live-region behavior, and submit a question.
**Expected:** The page stays visible, the drawer is discoverable and operable by keyboard/screen reader, and citations correspond to the exact visible state.
**Why human:** Visual, responsive, and assistive-technology behavior cannot be established by source inspection or shallow unit tests.

### 2. Foundry specialist and Fabric IQ tenant availability

**Test:** In the target tenant, verify each configured specialist name/version and invoke a governed Fabric IQ relationship/topology/policy query, then disable each dependency.
**Expected:** Specialist identity/version is attributable; IQ results carry scope, freshness, provenance, and authorization metadata; unavailable/denied states preserve deterministic findings and never replace inventory identity.
**Why human:** Tenant permissions, preview availability, deployment identity, and data-plane behavior are external runtime properties.

### 3. Exact visible snapshot replay

**Test:** On each supported page, change filters and selection, open Copilot, submit a question, and compare the ledger snapshot hash/evidence rows with what was rendered.
**Expected:** Only the bounded named state visible at submission is cited; no hidden page query or broader rehydration appears.
**Why human:** The current tests assert builder shape but do not exercise the browser state transition and API payload together.

## Gaps Summary

Phase 9 has substantial implementation and its focused checks pass. Earlier verification blockers were addressed by Plans 04 and 05. The full backend suite still has three failures outside the Phase 9 focused path; detached-boundary reproduction and commit/file provenance in `09-REGRESSION-OWNERSHIP.md` establish that they are pre-existing governance, situation/ontology, and storage failures rather than consumer-pivot regressions.

The existing UI and specialist catalog are substantive and wired, but the exact page-state replay and tenant-dependent Foundry/IQ behavior still require human verification after the blockers are closed.

---

_Verified: 2026-08-28T07:40:00Z_
_Verifier: the agent (gsd-verifier)_
