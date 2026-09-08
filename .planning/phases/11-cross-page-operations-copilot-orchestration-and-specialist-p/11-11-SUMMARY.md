---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 11
subsystem: ui
tags: [copilot, orchestration, canonical-contract, multi-agent, investigation-workspace, react, typescript, fastapi, read-only]

# Dependency graph
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 03
    provides: Canonical OrchestrationService result contract (policy/coverage/citations/thread) and the /copilot/investigations canonical route
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 06
    provides: Canonical-backed /copilot/investigate and /agents/investigations compatibility routing plus legacy-session→thread binding
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 16
    provides: Exhaustive route disposition registry and manifest specialist parity (the three dedicated surfaces /copilot, /investigate, /agents)
provides:
  - One shared canonical client helper (askCanonicalInvestigation) and one presentation converter (toCanonicalInvestigationView) consumed by every dedicated Copilot surface
  - Standalone Copilot and investigation workspace migrated onto the canonical contract with a shared ROOT_COPILOT_SESSION thread, rendering policy/fallback, citations, and uncertainty consistently
  - Manifest-backed agent catalog with explicit configured/unavailable deployment status projected into the multi-agent ledger UI
  - Backend route-equivalence, principal-isolation, catalog-status, and no-execution-authority tests for the dedicated multi-agent surface
affects: []

# Actuals (#2632)
actuals:
  tokens: 10700
  tasks: 2
  commits: 5

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One shared wire/client split: canonical result semantics live as optional fields on the CopilotInvestigation wire type (types.ts); a single fetch helper (askCanonicalInvestigation) and a single presentation converter (toCanonicalInvestigationView) in services.ts keep every dedicated surface from drifting"
    - "Root thread continuity: every dedicated surface submits with the shared ROOT_COPILOT_SESSION so the server binds one principal-scoped canonical thread, and best-effort mirrors the returned thr- handle into the root ThreadContinuity provider"
    - "Manifest-derived catalog status: AutonomousAgent.foundry carries the API's configured/unavailable deployment status so the UI renders it directly and no local specialist list can drift (D-05)"

key-files:
  created: []
  modified:
    - web/src/lib/types.ts
    - web/src/lib/services.ts
    - web/src/app/copilot/page.tsx
    - web/src/app/investigate/page.tsx
    - web/src/app/investigate/page.test.tsx
    - web/src/app/agents/page.tsx
    - web/src/app/agents/page.test.tsx
    - tests/test_api_copilot_unified.py

key-decisions:
  - "The canonical HTTP route /copilot/investigations is inventory/connections-specific (it hardcodes the inventory selector and a Literal page_kind), so a context-free standalone question cannot use it meaningfully. The dedicated /copilot and /investigate surfaces therefore submit through the general canonical-backed /copilot/investigate route, whose canonical projection already returns contract_version, thread_id/thread_revision, policy_status, fallback_reason, coverage, citations, and synthesis. Convergence is a shared-semantics migration, not a route swap — and it required no backend router change (backend routers were out of the plan's file scope)."
  - "'Use the root thread ID' is implemented as a shared ROOT_COPILOT_SESSION constant. The server keys session→thread bindings by (principal, session_id), so one shared session id makes both surfaces converge on a single principal-scoped canonical thread contract. Using the opaque thr- continuity handle as the session id was rejected because /copilot/investigate derives (not adopts) a thread from the session key, which would mint a new thread every turn and break continuity."
  - "Presentation is shared through exactly one converter (toCanonicalInvestigationView) rather than a new shared component, honouring the plan's 'explicit presentation converters only where required' and the scope rule to touch only the eight plan files. Each page keeps its own distinct JSX composition (chat thread vs. executive/engineer workspace) while rendering narration, a policy/fallback degradation note, citations, and uncertainty identically."
  - "Narration is derived only from synthesis.status == 'synthesized' claims (their cited summaries); a withheld or single-domain narrator yields no invented text and instead surfaces a degradation note while preserving the specialists' own deterministic tool evidence (D-09)."
  - "The multi-agent ledger backend already routes through the canonical service and projects the legacy ledger shape, so the only /agents frontend change was rendering the manifest-backed foundry deployment status; the shared task ledger, reconciliation, conditional synthesis, and principal-scoped human controls were already canonical-projected and left intact."

patterns-established:
  - "Wire/client split for canonical semantics: optional canonical fields on the wire type + one fetch helper + one converter, so multiple surfaces cannot diverge in how they present policy/citations/uncertainty/degradation."
  - "Shared root session for cross-surface continuity: a single principal-scoped session id gives every dedicated surface one authorized canonical thread without a second identity system."

requirements-completed: [COP-01, COP-02, COP-05]

coverage:
  - id: D1
    description: "Standalone Copilot and the investigation workspace submit the canonical contract through the one shared helper on the shared root thread, and render synthesis narration, policy/fallback degradation, citations, and uncertainty consistently while keeping their distinct compositions and workspace controls"
    requirement: COP-01
    verification:
      - kind: unit
        ref: "web/src/app/investigate/page.test.tsx#connects service risk, topology, vulnerability, evidence, Copilot conclusion, and remediation in one flow"
        status: pass
      - kind: unit
        ref: "web/src/components/ui/CopilotDrawer.test.tsx (canonical drawer path unchanged)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The dedicated /agents surface is a canonical result projection: it renders the manifest-backed catalog with explicit configured/unavailable deployment status, keeps principal-scoped human ledger decisions, and confers no execution authority"
    requirement: COP-05
    verification:
      - kind: unit
        ref: "web/src/app/agents/page.test.tsx#renders the manifest-backed catalog with explicit configured/unavailable status"
        status: pass
      - kind: unit
        ref: "web/src/app/agents/page.test.tsx#keeps ledger decisions principal-scoped and confers no execution authority"
        status: pass
    human_judgment: false
  - id: D3
    description: "Backend route equivalence: the dedicated /agents surface and /copilot/investigate share one canonical service (same policy/coverage/citation/thread semantics), the catalog exposes manifest deployment status, a canonical ledger is isolated from a foreign principal, and approve_plan records a governed decision without execution authority"
    requirement: COP-02
    verification:
      - kind: integration
        ref: "tests/test_api_copilot_unified.py#test_canonical_multi_agent_route_shares_orchestration_semantics_with_copilot"
        status: pass
      - kind: integration
        ref: "tests/test_api_copilot_unified.py#test_canonical_multi_agent_catalog_exposes_manifest_deployment_status"
        status: pass
      - kind: integration
        ref: "tests/test_api_copilot_unified.py#test_canonical_multi_agent_ledger_isolated_from_foreign_principal"
        status: pass
      - kind: integration
        ref: "tests/test_api_copilot_unified.py#test_canonical_multi_agent_ledger_action_confers_no_execution_authority"
        status: pass
    human_judgment: false

# Metrics
duration: 50min
completed: 2026-09-08
status: complete
---

# Phase 11 Plan 11-11: Converge the Dedicated Copilot Surfaces on the Canonical Service Summary

**The standalone Copilot, the investigation workspace, and the multi-agent ledger now share one canonical request/result contract, one client helper, one presentation converter, and one authorized root thread — each keeping its distinct presentation — while the agent catalog renders manifest-backed configured/unavailable status so no UI specialist list can drift.**

## Performance

- **Duration:** ~50 min
- **Tasks:** 2 (both TDD RED/GREEN)
- **Commits:** 5 (4 task commits + this summary)

## Accomplishments

### Task 1 — Standalone Copilot and investigation workspace on canonical semantics
- Added `CanonicalInvestigationSemantics`/`CanonicalInvestigationSynthesis`/`CanonicalSynthesisClaim` wire types and extended `CopilotInvestigation` with the canonical result fields the `/copilot/investigate` projection already returns (contract_version, thread_id/thread_revision, policy_status, fallback_reason, coverage, citations, synthesis).
- Added the single shared canonical client helper `askCanonicalInvestigation`, the single presentation converter `toCanonicalInvestigationView`, and the `ROOT_COPILOT_SESSION` constant in `services.ts`.
- Migrated `/copilot` off its per-tab random session and `/investigate` off its per-entity session onto the shared helper and root session; both mirror the server-issued `thr-` handle into the root `ThreadContinuity` provider (best-effort, null-safe for isolated renders).
- Both surfaces now render, consistently: synthesis narration (only when synthesis actually ran), a policy/fallback **degradation note**, **citations**, and **uncertainty** — while `/copilot` keeps its chat composition and `/investigate` keeps its executive/engineer workspace and all save/reopen/share/export controls.

### Task 2 — Canonical projection into the multi-agent ledger UI
- Added `AgentDeploymentStatus` and the `AutonomousAgent.foundry` field so the API catalog's manifest-backed deployment status is typed.
- Rendered each catalog specialist's explicit **Ready/Unavailable** status from the API projection (no UI-owned specialist list), leaving the already-canonical ledger (specialist runs, findings, reconciliation, conditional synthesis, principal-scoped human controls, rollback-safe projection) intact.
- Added backend route-equivalence tests proving the dedicated `/agents` surface and `/copilot/investigate` project identical canonical policy/coverage/citation/thread semantics, the catalog exposes manifest deployment status, a canonical ledger is isolated from a foreign principal (404 read + action), and `approve_plan` records a governed decision without conferring execution authority.

## Verification

- Task 1 verify (`investigate/page.test.tsx` + `CopilotDrawer.test.tsx` + `tsc --noEmit`): **pass** (22 tests, tsc clean).
- Task 2 verify (`tests/test_api_copilot_unified.py` + `tests/test_api_multi_agent.py` **92 passed**; `agents/page.test.tsx` **3 passed**): **pass**.
- Full web suite: **630 passed / 57 files**.
- Relevant backend suite (9 copilot/agent/orchestration/evaluation modules): **217 passed**.
- `next lint` (full project): no warnings or errors. `tsc --noEmit`: clean.
- Diff scope: exactly the 8 plan-declared files; working tree clean. No backend routers, Terraform, drawer/thread-context, STATE/ROADMAP, or unrelated routes touched. No push, merge, deploy, production build, Terraform, or live external API run.

## Deviations from Plan

None — plan executed as written. The plan cited stale line ranges in `types.ts`/`services.ts`; the canonical wire/client split was located at its current position (`investigateCanonical`, `CanonicalCopilotResult`, `CopilotInvestigation`) and followed there.

## Known Stubs

None. Every rendered field is wired to real canonical/API data.

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary surface were introduced (frontend consumes existing routes; the only backend change is test coverage).

## Notes for the phase
- Phase 11 is **not** marked complete by this plan; STATE.md and ROADMAP.md were intentionally left unchanged per the plan scope and the execution freeze.

## Independent Review

An independent cross-AI reviewer was not available: only a same-family `claude` CLI is installed (not an independent second opinion), and the phase freeze prohibits live external API calls. Verification relied on the full TDD suite (frontend + backend), the full web suite, the relevant backend suite, `tsc`, `next lint`, and diff-scope inspection — all green.

## Self-Check: PASSED
