---
phase: 09-consumer-pivot
verified: 2026-08-28T08:02:42Z
status: human_needed
score: 8/10 must-haves verified
behavior_unverified: 1
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/10
  gaps_closed:
    - "Network findings distinguish stale or partial evidence from verified actionable findings."
    - "The contextual Copilot request is scope-safe for all submitted snapshot evidence and selected resources."
    - "The bounded plan/observe/delegate/request-evidence/reassess loop performs governed delegation rather than only labeling stages."
    - "Fabric IQ is wired as an opt-in governed enrichment when configured, while remaining non-authoritative for identity."
  gaps_remaining:
    - "Exact visible page-state replay and tenant-dependent provider behavior require human verification."
    - "Repository-wide classification of raw inventory/identity reads versus authorized acquisition seams remains a human/owner decision."
  regressions: []
behavior_unverified_items:
  - truth: "Supported pages submit exactly the bounded visible page state to the shared contextual API."
    test: "On each supported page, change filters and selected resources, open Copilot, and submit a question."
    expected: "The request and returned ledger contain only the current visible filters, selections, freshness, scope, and named evidence rows."
    why_human: "Unit tests cover snapshot construction and one drawer submission, but not every rendered page's live state transition through the browser and API."
human_verification:
  - test: "Exact visible snapshot replay across supported pages"
    expected: "Home, Network, exposure/CVE, compliance, situations, and remediation send the exact currently rendered bounded state; no hidden rehydration or broader scope appears."
    why_human: "The browser state, rendered rows, API payload, and ledger replay must be compared together."
  - test: "Accessible contextual drawer UX"
    expected: "Launcher and drawer remain discoverable and operable by keyboard and screen reader at desktop and narrow widths; focus, Escape, live status, retry, partial, fallback, and error states are understandable."
    why_human: "Visual, responsive, and assistive-technology behavior cannot be established by source inspection or shallow component tests."
  - test: "Configured Fabric IQ and Foundry behavior in the target tenant"
    expected: "Configured specialists and IQ operations return attributable version/provenance, freshness, authorization, bounded scope-safe data, and identity_authority=false; disabled or denied dependencies preserve deterministic findings."
    why_human: "Tenant permissions, deployment identity, preview availability, and external data-plane behavior are not reproducible in this repository."
  - test: "Repository-wide inventory identity ownership decision"
    expected: "Confirm remaining raw dataset reads are authorized ingestion/publication seams, not consumers; all resource-identity consumers use InventoryReadPort."
    why_human: "Static guards cover the declared consumer paths, while acquisition/normalization code still reads raw datasets and needs domain-owner classification."
---

# Phase 9: Consumer Pivot Verification Report

**Phase Goal:** As a platform operator, I want the API and UI powered by unified inventory, so that every surface reflects one source of truth about what resources exist.

**Verified:** 2026-08-28T08:02:42Z
**Status:** human_needed
**Re-verification:** Yes — after gap closure plans 09-04, 09-05, and 09-06

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | API resource-identity providers resolve through the inventory read port with unchanged route contracts. | ✓ VERIFIED | `src/api/runtime.py` registers `inventory_read_port`; focused Phase 9 backend suite passed 134 tests. |
| 2 | `agent_queries.py` reads servers/VMs through inventory identity while patch assessments remain a separate domain join. | ✓ VERIFIED | `ContextQueryService` calls `InventoryReadAdapter.resources()` and joins patch rows by `targetResourceId`; `test_agent_queries.py` and consumer guards pass. |
| 3 | Web resource-identity pages use unified inventory and preserve per-family availability/warnings. | ✓ VERIFIED | Inventory/read-port status contracts and page integration tests pass; no page-level raw identity read was found in the audited paths. |
| 4 | Page-level Copilot submits the exact bounded page state it displays to the shared orchestrator. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | All six supported integrations call `buildCopilotSnapshot`; focused drawer test proves one exact typed submission, but every page's live rendered-state transition is not browser-proven. |
| 5 | The accessible shared drawer preserves `/agents` as the full workspace. | ✓ VERIFIED | `CopilotDrawer` has dialog labeling, focus, Escape, live status, retry and staged rendering; `/agents` remains a separate route. Focused web tests and lint pass. Visual/AT checks remain human-only. |
| 6 | Loading, partial, deterministic fallback, retry, failure, and Foundry narration are distinct and honest. | ✓ VERIFIED | Drawer has separate status branches; API returns deterministic findings and explicit warnings; focused backend/web tests pass. |
| 7 | Operations Copilot performs a bounded plan/observe/delegate/request-evidence/reassess loop. | ✓ VERIFIED | `run_context_investigation` invokes allowlisted `_agent_run` tools, named rechecks, deterministic reassessment, specialist metadata, budgets, retry/timeout handling, ledger calls, and human controls. A fresh probe observed `network_topology`, `firewall_nsg_gaps`, and recheck execution with all five stages. |
| 8 | Network findings are cited and stale/partial/unavailable evidence is uncertainty-qualified and non-actionable. | ✓ VERIFIED | `deterministic_network_findings` downgrades degraded freshness to `hypothesis`, medium/low confidence, `stale=true`, and `actionable=false`; focused snapshot/network tests pass. |
| 9 | Foundry specialists have a separate boundary and deterministic fallback; Fabric IQ is configurable, governed, and optional. | ✓ VERIFIED | Runtime resolves `_load_fabric_iq_adapter` through optional `ProviderRuntime`; adapter allowlists operations, scope-filters/bounds payloads, stamps provenance/freshness/authorization and `identity_authority=false`; runtime/adapter/fallback tests pass. |
| 10 | No consumer anywhere reads raw inventory or identity datasets directly. | ? UNCERTAIN | Declared identity consumers pass `test_inventory_consumer_guards.py`, but raw reads remain in ingestion/activation/normalization acquisition seams. Their consumer-versus-authorized-publication classification needs owner confirmation. |

**Score:** 8/10 truths verified (1 present, behavior-unverified; 1 uncertain)

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/operations/page_context.py` | Bounded snapshot, scope validation, freshness-aware findings | ✓ VERIFIED | Canonical IDs validate selected/evidence resources; stale/partial/unavailable findings downgrade safely. |
| `src/api/routers/copilot.py` | Validate before contextual orchestration and return ledger | ✓ VERIFIED | `investigate_context` calls `validate_effective_scope` before `run_context_investigation`, then stores/returns the ledger. |
| `src/operations/autonomous_investigation.py` | Real bounded contextual orchestration | ✓ VERIFIED | Actual tool handler calls, rechecks, reassessment, budgets, statuses, ledger metadata, and human controls are implemented and probe-exercised. |
| `src/onboarding/agent_queries.py` | Inventory-read-port identity consumer | ✓ VERIFIED | Resource identity flows through `InventoryReadAdapter`; patch rows remain separate. |
| `src/operations/tools.py` | Governed allowlisted Fabric IQ boundary | ✓ VERIFIED | Adapter is scope-filtered, bounded, metadata-stamped, optional, and non-authoritative. |
| `src/api/runtime.py` | Configurable Fabric IQ provider wiring | ✓ VERIFIED | Environment/configured Fabric runtime reaches the adapter; no config returns explicit unavailable. |
| `web/src/components/ui/CopilotDrawer.tsx` | Shared accessible staged drawer | ✓ VERIFIED | Component is substantive, imported by supported pages, and focused tests/lint pass; visual/AT behavior is human-gated. |
| `.planning/phases/09-consumer-pivot/09-REGRESSION-OWNERSHIP.md` | Evidence-backed residual failure ownership | ✓ VERIFIED | Three failures reproduce at pre-Phase-9 boundary and remain visible without skips/xfails. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Context API | Scope enforcement | `investigate_context` → `snapshot.validate_effective_scope` | ✓ WIRED | Selected and evidence resource IDs are canonicalized and checked against effective scope before orchestration. |
| Context API | Deterministic findings | `run_context_investigation` → `deterministic_network_findings` | ✓ WIRED | Submitted evidence is consumed directly; freshness controls status/confidence/actionability. |
| Context loop | Governed tools/ledger | `_agent_run`/named rechecks → `call_tool` → `tool_calls` | ✓ WIRED | Fresh probe recorded delegate and request-evidence calls; reassessment recomputes findings. |
| Runtime | Fabric IQ | `ProviderRuntime.get("fabric_iq")` → `_load_fabric_iq_adapter` | ✓ WIRED | Configured runtime reaches `FabricIQToolAdapter`; optional failure is explicit unavailable. |
| Agent queries | Inventory identity | `ContextQueryService` → `InventoryReadAdapter` → `InventoryReadPort` | ✓ WIRED | Focused identity and consumer-guard tests pass. |
| Pages | Context API | page `buildCopilotSnapshot` → `CopilotDrawer` → `investigateContext` | ✓ WIRED | Six supported pages use the common path; exact browser state replay remains human-gated. |

## Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| Context findings | `snapshot.evidence` | Submitted page evidence | Yes | ✓ FLOWING |
| Agent query identity | `resources` | Runtime-bound `InventoryReadPort` | Yes | ✓ FLOWING |
| Fabric IQ enrichment | adapter `raw` | Managed Fabric runtime ontology query | Configured path | ✓ FLOWING (optional) |
| Foundry narration | curated findings/context | Optional configured Foundry agent | Tenant-dependent | ⚠️ EXTERNAL / HUMAN |
| Page Copilot snapshot | filters/resources/evidence | Rendered page state | Typed builder path | ⚠️ BROWSER REPLAY HUMAN |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Focused Phase 9 backend suites | `uv run python -m pytest tests/test_page_context.py tests/test_api_copilot_snapshot.py tests/test_api_copilot_investigation.py tests/test_network_analysis.py tests/test_agent_queries.py tests/test_inventory_read_port.py tests/test_api_runtime.py tests/test_foundry_agent.py tests/test_fabric_client.py tests/test_inventory_consumer_guards.py -q` | 134 passed | ✓ PASS |
| Governed contextual loop | Fresh `uv run python -c ...` probe after normal app import | Delegate tools and named evidence recheck executed; stages were plan/observe/delegate/request-evidence/reassess; hidden reasoning false | ✓ PASS |
| Focused web Copilot tests | `cd web && npm test -- --run src/components/ui/CopilotDrawer.test.tsx src/components/ui/CopilotDrawerButton.test.tsx src/components/ui/CopilotPageIntegrations.test.tsx` | 4 tests passed | ✓ PASS |
| Web lint | `cd web && npm run lint` | No warnings/errors | ✓ PASS |
| Full web suite | `cd web && npm test -- --run` | Exit code 0 | ✓ PASS |
| Production build | `cd web && npm run build` | Build succeeded; existing MSAL `window is not defined` prerender messages | ✓ PASS |
| Three documented backend failures | Isolated three-test command | All three failed with the documented assertions | ⚠️ BASELINE |
| Full backend suite | `uv run python -m pytest -q` | `3 failed, 1532 passed, 2 warnings`; exact residual set matches ownership record | ⚠️ BASELINE |

## Probe Execution

No phase-declared or conventional `scripts/*/tests/probe-*.sh` probe was found.

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| INV-09 | 09-01 through 09-06 | Per-family availability/status remains usable instead of blanking inventory | ⚠️ NEEDS HUMAN | Read-port and focused web/backend checks preserve statuses and warnings; live degraded-family page behavior remains untested. |
| INV-10 | 09-01 through 09-06 | Consumers use one scope-enforced inventory contract and no raw identity reads | ⚠️ NEEDS HUMAN | Main identity path and snapshot scope boundary pass; repository-wide acquisition-seam classification remains unresolved. |

No additional Phase 9 requirement IDs are mapped in `REQUIREMENTS.md`; no orphaned Phase 9 requirement was found.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `web/src/components/ui/CopilotDrawer.tsx` | 305 | `placeholder` input text | ℹ️ Info | Normal form affordance, not an implementation stub. |
| `src/api/app.py` / dependency stack | build/test output | Existing deprecation warnings (`on_event`, httpx/TestClient) | ℹ️ Info | Does not fail Phase 9 tests or affect the verified goal. |

No `TBD`, `FIXME`, or `XXX` markers were found in Phase 9 implementation files.

## Human Verification Required

### 1. Exact visible snapshot replay

**Test:** On home, Network, exposure/CVE, compliance, situations, and remediation, alter filters/selections and submit through the drawer.
**Expected:** The ledger hash and evidence rows correspond exactly to the visible state at submission, without hidden rehydration.
**Why human:** This requires comparing browser-rendered state with the live request and ledger.

### 2. Accessible page UX

**Test:** Use mouse, keyboard, and a screen reader at desktop and narrow widths; launch, navigate, close with Escape, submit, retry, and inspect partial/fallback/error states.
**Expected:** The current page remains visible and the shared drawer is discoverable, operable, and understandable.
**Why human:** Visual, responsive, and assistive-technology behavior cannot be proven by repository tests.

### 3. Tenant-dependent specialists and Fabric IQ

**Test:** In the target tenant, invoke configured specialist and Fabric IQ relationship/topology/policy paths, then disable or deny them.
**Expected:** Results retain source/provenance/freshness/authorization and `identity_authority=false`; deterministic inventory/findings remain usable on fallback.
**Why human:** External permissions, preview availability, deployment identity, and data-plane behavior are not available to automated verification.

### 4. Inventory consumer ownership boundary

**Test:** Have the inventory/ingestion owners classify raw reads in acquisition, activation, and normalization code.
**Expected:** Those reads are authorized publication/acquisition internals, and every actual identity consumer remains on `InventoryReadPort`.
**Why human:** Static guard scope cannot decide domain ownership intent.

## Gaps Summary

Plans 09-04 and 09-05 close the prior implementation blockers: canonical selected/evidence scope validation, stale/partial downgrade semantics, actual governed delegation/evidence/reassessment, and configurable optional Fabric IQ are present, wired, and focused-tested. Plan 09-06's three full-suite failures were independently reproduced and are explicitly pre-Phase-9 governance, situation/ontology, and storage baseline failures; they remain visible and are not hidden by skips or weakened assertions.

The remaining gate is human verification, not an observed Phase 9 implementation blocker: exact browser snapshot replay, accessible/responsive/assistive UX, target-tenant provider behavior, and owner classification of raw acquisition seams.

---

_Verified: 2026-08-28T08:02:42Z_
_Verifier: the agent (gsd-verifier)_
