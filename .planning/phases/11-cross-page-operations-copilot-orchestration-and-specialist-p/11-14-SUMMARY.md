---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 14
subsystem: operations-copilot-browser-continuity
tags: [copilot, continuity, session-storage, evidence-aging, privacy]
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 06
    provides: Durable principal- and scope-bound server investigation threads
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 13
    provides: Canonical Inventory drawer and opaque thread integration
provides:
  - Root-scoped same-tab continuity for opaque server thread handles
  - Fail-closed cloned-tab ownership fencing without cross-device claims
  - Server-authoritative historical, revalidated, current, and reset evidence UI
  - Deterministic cited fallback during optional narration provider outages
affects: [11-15, 11-16]
actuals:
  tasks: 2
  commits: 7
tech-stack:
  added: []
  patterns:
    - Browser continuity stores only a validated opaque thread ID and positive server revision
    - Restored handles require server revalidation before continuity is trusted
    - Web Locks fence cloned session storage while unsupported ownership fails closed
    - Session reset generations invalidate every pre-reset asynchronous response
    - Evidence age and reset semantics are projected only from server-returned state
key-files:
  created:
    - web/src/lib/copilot/thread-context.tsx
    - web/src/lib/copilot/thread-context.test.tsx
  modified:
    - web/src/app/layout.tsx
    - web/src/components/ui/CopilotDrawer.tsx
    - web/src/components/ui/CopilotDrawer.test.tsx
key-decisions:
  - "The root continuity provider is nested directly beneath ScopeProvider so route remounts cannot discard the active opaque server handle."
  - "sessionStorage accepts exactly thread_id and thread_revision; any malformed value or extra field is removed."
  - "A restored handle is a continuity hint only and is marked for server revalidation against the current scope."
  - "Exclusive Web Locks use a SHA-256-derived key so duplicated tabs fail closed without exposing the raw opaque ID through coordination names."
  - "Logout and session-end events clear persisted and in-memory continuity and invalidate responses started before the reset."
  - "Historical, revalidated, current, expired, and mismatch presentation is derived from canonical server state, never browser inference."
  - "Optional narration failure cannot erase deterministic findings, citations, coverage, or uncertainty."
requirements-completed: [COP-01, COP-05]
completed: 2026-09-07
status: complete
---

# Phase 11 Plan 14: Same-Tab Browser Continuity Summary

**Operations Copilot investigations now survive route navigation in the same browser tab using only a server-issued opaque thread handle, while server reauthorization remains authoritative and stale evidence, reset conditions, and optional provider degradation remain explicit to the operator.**

## Accomplishments

- Added a root `ThreadContinuityProvider` directly beneath `ScopeProvider`, preserving continuity across page and drawer remounts without moving transcript, evidence, principal, scope, or authority into browser storage.
- Restricted `sessionStorage` to the exact two-field record `{ thread_id, thread_revision }`, with strict lowercase opaque-ID and positive safe-integer revision validation. Malformed or extended records are removed.
- Marked every restored handle as requiring server revalidation and retained the current effective scope in the canonical request path rather than the persisted record.
- Cleared in-memory and persisted continuity on MSAL logout and session-end events, with a reset generation that rejects every response started before the reset.
- Added fail-closed cloned-tab protection through exclusive Web Locks keyed by a SHA-256 digest of the opaque handle. Stored candidates are removed while ownership is pending and are not restored or persisted when locking or Web Crypto is unavailable.
- Moved drawer continuity out of page-local state and into the root provider while retaining an inert, no-persistence fallback for isolated component tests and non-root renders.
- Invalidated stale work on page-context changes, provider reset generations, and drawer unmount so prior-page or pre-logout responses cannot overwrite current continuity.
- Rendered evidence age only from the server's `observation_status`, distinguishing historical, revalidated/rechecked, and current evidence without treating tool outcome status as freshness.
- Collapsed expired, unknown, deleted, and principal/scope mismatch responses into one non-disclosing reset message.
- Preserved deterministic findings, citations, coverage, and uncertainty when optional narration is unavailable.

## Task and Review Commits

1. **Task 1 RED:** `62ad61bf` - `test(11-14): pin same-tab thread continuity`
2. **Task 1 GREEN:** `9a112375` - `feat(11-14): preserve same-tab thread continuity`
3. **Task 2 RED:** `d24a6891` - `test(11-14): pin evidence continuity states`
4. **Task 2 GREEN:** `bc9cce47` - `feat(11-14): surface server evidence continuity`
5. **Isolated-render compatibility review:** `b612c6c4` - `fix(11-14): preserve isolated drawer compatibility`
6. **Restored-state typing review:** `8936c889` - `fix(11-14): type restored continuity state`
7. **Ownership and stale-response review:** `1d2bbee2` - `fix(11-14): harden continuity ownership`

Every commit includes the required Copilot co-author trailer.

## Files Created/Modified

- `web/src/lib/copilot/thread-context.tsx` - Root continuity state, strict storage parsing, reset generations, scope revalidation, logout/session reset, and cloned-tab ownership fencing.
- `web/src/lib/copilot/thread-context.test.tsx` - Navigation, StrictMode, malformed storage, scope change, logout, lock failure, deferred ownership, cloned-tab denial, and exact-schema coverage.
- `web/src/app/layout.tsx` - Root provider composition directly beneath `ScopeProvider`.
- `web/src/components/ui/CopilotDrawer.tsx` - Provider-backed continuity, stale-response invalidation, server evidence-age projection, generic reset semantics, and deterministic outage fallback.
- `web/src/components/ui/CopilotDrawer.test.tsx` - Evidence-age, privacy reset, provider outage, logout race, legacy result, navigation/unmount race, and direct-render compatibility coverage.

## Trust and Privacy Decisions

- Possession of a browser-stored handle never grants ownership or scope. The browser submits only the opaque ID/revision and current scope; the server revalidates principal, scope, lifetime, and revision.
- The persisted record rejects every property beyond `thread_id` and `thread_revision`. Transcript, findings, evidence, citations, principal, tenant, subscription, scope, authorization flags, and provider state remain absent.
- The design claims same-tab navigation continuity only. It does not claim cross-tab, cross-browser, or cross-device discovery.
- Browser-cloned session storage is treated as an adversarial restoration path. Exclusive ownership is acquired before a stored handle becomes usable; unsupported or rejected ownership fails closed.
- Raw opaque IDs are not broadcast and are not used directly as lock names.
- Not-found, expiry, deletion, ownership mismatch, and scope mismatch share one generic reset presentation, preventing thread-existence disclosure.
- Evidence age is shown only when the server explicitly returns the corresponding observation state. Browser navigation history does not infer that evidence is historical or current.

## Independent Review

Independent review rounds identified and verified fixes for these high-confidence issues:

1. Tool/source outcome status was initially treated as evidence age; the drawer now reads only server `observation_status`.
2. Late responses could repersist continuity after logout or session end; reset generations now fence every post-await path.
3. Duplicated tabs could inherit cloned `sessionStorage`; exclusive Web Locks now prevent concurrent restoration.
4. Timeout-based ownership probing could race; ownership now waits for the lock contract and fails closed on unsupported/rejected locking.
5. Legacy and error result paths were not uniformly invalidated by session reset; all asynchronous exits now check the live reset generation.
6. An unmounted page-local drawer could overwrite root continuity; unmount increments the request generation without setting React state.
7. Stored handles could remain visible while lock acquisition was pending; candidates are removed immediately and persisted only after exclusive ownership.
8. Strict provider access broke adjacent isolated drawer/page tests; an inert optional-provider path preserves isolated rendering without adding persistence or production authority.

The final reviews reported no remaining high-confidence actionable findings in the five Plan 11-14 files.

## Verification

| Gate | Result |
|---|---|
| Provider-focused suite | **16 passed** |
| Drawer-focused suite | **21 passed** |
| Refreshed combined corrected-main provider/drawer gate | **37 passed** |
| Full web Vitest suite | **55 files, 540 tests passed** |
| ESLint | passed with no warnings or errors |
| TypeScript `tsc --noEmit` | passed |
| Whitespace | clean |
| Synthetic merge-tree with corrected Plan 11-06 and disjoint Exposure Plan 19 | clean (`7d7e767e`) |

The existing Vite CommonJS deprecation notice and unrelated Keyborg/page-test warnings remain non-failing.

## Deviations from Plan

### Auto-fixed browser boundary hardening

- **Issue:** `sessionStorage` may be cloned into a newly opened tab, so storage scope alone could not prove the same-tab boundary.
- **Fix:** Added fail-closed exclusive ownership with a digest-derived Web Lock name while retaining the exact two-field persisted record.

### Auto-fixed isolated render compatibility

- **Issue:** Adjacent page tests render `CopilotDrawer` outside the production root layout.
- **Fix:** Added an inert optional-provider consumer used only when the root provider is absent. It neither restores nor persists continuity; production remains rooted under `ScopeProvider`.

## Baseline and Delivery Status

- Implementation base: `c5595f7a7790d7b6cd86cff8e6d53e10d38b314b`.
- Final corrected Plan 11-06 head: `8ce485ae93670134058a8e798b396f10013bc6ab`.
- Latest fetched `origin/main`: `c5595f7a7790d7b6cd86cff8e6d53e10d38b314b`.
- Latest local `main`, including disjoint Exposure Plan 19: `8438aef9f07021bc7f9665a124ead47e97f8e16c`.
- The synthetic merge of Plan 11-14, corrected Plan 11-06, and local `main` produced tree `7d7e767eaf0a860ae4962ec3b263434f813b5294` without conflicts; the focused 37-test gate passed from that exact tree.
- Concurrent Exposure Plan 19 remained disjoint and changed no Plan 11-14 web file.
- No runtime, telemetry, Terraform, exposure, remediation, network, `services.ts`, `types.ts`, or page-adapter implementation was changed.
- `.planning/STATE.md` and `.planning/ROADMAP.md` remain unchanged.
- Nothing was pushed or deployed.

---
*Phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p*
*Completed: 2026-09-07*
