---
status: fixing
trigger: Phase 11 live Copilot page-audit failures
created: 2026-09-13T09:37:49+08:00
updated: 2026-09-13T11:24:00+08:00
---

# Copilot Page Audit Remediation

## Symptoms

### Expected

All 26 supported routes submit bounded, schema-valid snapshots through one canonical v2
investigation contract, route only to page-safe specialists, answer page-specific factual
questions from retained evidence during Foundry degradation, and cite claim-level evidence.

### Actual

The supplied live audit baseline reports 0 clean pass, 6 partial, 12 fail, and 8 blocked.
Failures cluster around snapshot schema/bounds drift, v1/v2 endpoint divergence, generic
degraded answers, insufficient citations, stale or unrelated evidence selection, broadened
specialist routing, redirect-contract disagreement, and missing live provider configuration.

### Reproduction

Use focused contract and routing tests derived from the supplied audit matrix. The referenced
`11-UAT.md` and raw correlation payloads are not present in HEAD, main, origin/main, or session
artifact storage, so exact live-request attribution remains an explicit external evidence gap.

## Current Focus

bug_class: bohrbug
hypothesis: Clusters 1 and 2 are fixed and guardrail-verified; the next unresolved root cause is cluster 3, where evidence and claims lack immutable page/entity/filter/query/generation identity and retained claim-level citation closure.
test: Add focused RED tests that distinguish current page evidence from stale or unrelated retained evidence and require every material response claim to close over retained citations.
expecting: Existing orchestration can select stale/unrelated evidence or return material claims whose evidence identity is not bound to the current page/query/generation.
next_action: Start cluster 3 by tracing canonical snapshot identity through retained thread evidence and synthesis claim citation closure; do not alter clusters 4-6 yet.

## Evidence

- timestamp: 2026-09-13T09:37:49+08:00
  observation: `.planning/STATE.md` declares Phase 4 active with one unrelated entry blocker.
  implication: Parent explicitly authorized this Phase 11 gap-closure exception.
- timestamp: 2026-09-13T09:45:00+08:00
  observation: Frontend v1 accepts `remediation`, backend v1 rejects it, and most pages still emit v1 while Inventory emits v2.
  implication: Page-specific HTTP 400 responses are downstream effects of cross-language contract drift.
- timestamp: 2026-09-13T09:47:00+08:00
  observation: Python and TypeScript apply inconsistent character, UTF-8, numeric, and structural bounds.
  implication: Snapshot acceptance varies by runtime and payload timing rather than one deterministic schema.
- timestamp: 2026-09-13T09:50:00+08:00
  observation: Integrated drawers use `/copilot/investigate-context`, dedicated surfaces use `/copilot/investigate`, and Inventory/Connections use `/copilot/investigations`.
  implication: Canonical thread, response, and CAS semantics are not shared by all callers.
- timestamp: 2026-09-13T09:52:00+08:00
  observation: Browser state retains `thread_revision`, but requests do not carry an expected revision.
  implication: Stale same-tab writes cannot be rejected before provider I/O.
- timestamp: 2026-09-13T09:55:00+08:00
  observation: Page-specific deterministic fallback exists only for vulnerability pages; other paths return generic text or raw tool data.
  implication: Foundry degradation loses direct factual answers and claim-level citation closure.
- timestamp: 2026-09-13T09:58:00+08:00
  observation: Evidence identity is not bound end-to-end to page, selected entity, filter/query, and immutable generation.
  implication: Stale or unrelated lower-priority evidence can dominate visible facts.
- timestamp: 2026-09-13T10:00:00+08:00
  observation: Global substring routing can add specialists outside the page manifest; tests permit broadening and missing evaluation measurements.
  implication: Services, Twin, Predeploy, and Identity route sets are not deterministic or fail closed.
- timestamp: 2026-09-13T10:02:00+08:00
  observation: Registry declares `/vulnerabilities` to `/exposure`, implementation redirects to `/exposure/patch-priorities`, and a prefix assertion masks the mismatch.
  implication: The authoritative route disposition is not exact.
- timestamp: 2026-09-13T10:05:00+08:00
  observation: Runtime does not consume `AIOPS_COPILOT_ROLLOUT_MODE`; live provider parity also lacks external onboarding evidence.
  implication: Source wiring can be fixed locally, but live readiness remains blocked on real immutable provider evidence.
- timestamp: 2026-09-13T09:51:00+08:00
  observation: `.planning/STATE.md` still marks Phase 4 planning active, while the parent request explicitly scopes this continuation to Phase 11 clusters 1 and 2; the worktree contains only the untracked active debug file.
  implication: The exception is in scope, and atomic commits can isolate this work without absorbing unrelated changes.
- timestamp: 2026-09-13T09:52:00+08:00
  observation: No project `rules/*.md` files or configured `gsd-debugger` agent skills were found; relevant code is concentrated in shared Copilot contracts/adapters/router/thread-store files.
  implication: Repository conventions and the loaded debugger workflow govern the surgical fix; no additional project rule overlay applies.
- timestamp: 2026-09-13T09:56:00+08:00
  observation: `EvidenceSnapshotV2` and `canonicalize_snapshot_v2` already define the intended 200-row, 8-KiB-row, 128-KiB-snapshot, 50-entity shape, but the canonicalizer has no production caller and the TypeScript core adapters still call the v1 `buildCopilotSnapshot`.
  implication: Cluster 1 is reuse/wiring work, not a reason to invent a second schema or raise limits.
- timestamp: 2026-09-13T09:58:00+08:00
  observation: `/copilot/investigations` narrows `snapshot.page_kind` to inventory variants and always derives an inventory selector, so strict v2 remediation and other integrated page snapshots are rejected before orchestration.
  implication: The canonical route must accept the manifest-backed v2 page union and retain its inventory-specific selector as a safe branch rather than as the whole endpoint contract.
- timestamp: 2026-09-13T10:00:00+08:00
  observation: `CopilotDrawer` only uses the canonical endpoint for snapshots already marked v2; all shared core page adapters, including remediation, emit v1 and therefore call `/copilot/investigate-context`.
  implication: A shared frontend v1-to-v2 normalization seam at the drawer/API boundary can migrate all integrated pages without editing excluded page components.
- timestamp: 2026-09-13T10:02:00+08:00
  observation: Same-tab storage strictly retains `{thread_id, thread_revision}`, but canonical requests send only `thread_id`; `OrchestrationService` automatically reconciles append conflicts after tool execution.
  implication: Add an optional expected revision to the canonical request, compare it immediately after principal/scope authorization and before planning/tool I/O, and disable post-I/O conflict reconciliation for CAS-bearing requests.
- timestamp: 2026-09-13T10:07:00+08:00
  observation: The focused Python RED run produced exactly three new failures: missing production canonicalizer import/call, remediation rejected by the inventory-only page-kind literal, and `expected_thread_revision` rejected as an extra field; all new N-1/N/N+1 model-boundary tests passed.
  implication: The backend reproduction is deterministic and isolates the three missing wiring points without weakening existing validators.
- timestamp: 2026-09-13T10:08:00+08:00
  observation: The first web RED command ran from the repository root and failed before collection because `package.json` lives under `web/`.
  implication: This is a test-harness invocation error, not product evidence; rerun with `npm --prefix web`.
- timestamp: 2026-09-13T10:10:00+08:00
  observation: The corrected web command reached the package script but `vitest` was unavailable because this isolated worktree has no installed `web/node_modules`.
  implication: Install exactly the lockfile state with `npm ci`; no product conclusion can be drawn from this pre-test dependency gap.
- timestamp: 2026-09-13T10:14:00+08:00
  observation: `npm ci` installed the lockfile state without changing tracked product files; npm reported pre-existing dependency advisories that are outside these two root-cause clusters.
  implication: Focused web tests are now runnable; dependency upgrades are not part of this surgical fix.
- timestamp: 2026-09-13T10:17:00+08:00
  observation: The corrected Vitest RED run has 12 targeted failures: ten boundary/normalization assertions fail because the shared v2 normalizer is absent, and two drawer assertions show legacy remediation/first-turn requests never call the canonical client; 92 neighboring tests pass.
  implication: The frontend reproduction directly distinguishes the missing migration seam from unrelated drawer behavior.
- timestamp: 2026-09-13T10:34:00+08:00
  observation: After cluster 1 implementation, 81/81 page-adapter tests and 40/40 focused Python snapshot/API tests pass, including remediation v2 acceptance, production canonicalizer invocation, and N-1/N/N+1 character/UTF-8/list boundaries.
  implication: The shared normalizer and manifest-wide route branch address the cluster 1 reproduction without raising limits.
- timestamp: 2026-09-13T10:35:00+08:00
  observation: The first TypeScript check used `npm exec` without its argument separator and printed compiler help instead of checking the project.
  implication: This is another harness invocation issue; rerun as `npm --prefix web exec -- tsc --noEmit`.
- timestamp: 2026-09-13T10:39:00+08:00
  observation: Adjacent orchestration parity plus snapshot suites pass 64/64; Ruff found only a deterministic style preference (`min` instead of sorting), while the second npm-prefix TypeScript invocation again printed help without compiling.
  implication: Cluster 1 behavior is green; make the one non-semantic lint correction and invoke the local compiler from `web/` directly.
- timestamp: 2026-09-13T10:43:00+08:00
  observation: `npx tsc --noEmit` from `web/` passes after two local typing corrections; Ruff is clean and the excluded-file diff check is empty.
  implication: Cluster 1 satisfies target, adjacent, lint, and type signals; only revert-and-reconfirm remains before commit.
- timestamp: 2026-09-13T10:47:00+08:00
  observation: With only cluster 1 production files temporarily restored from HEAD, the Python route tests returned the two original failures and all ten TypeScript normalizer assertions failed; restoring the staged fix returned Python 40/40, adapter 81/81, and TypeScript checking to green.
  implication: Revert-and-reconfirm proves the cluster 1 implementation, not an environment change, removes the reproduced defects.
- timestamp: 2026-09-13T10:48:00+08:00
  observation: No Stryker configuration or dependency exists, so the mutation signal is unavailable; diff review shows additive validation/adapter routing plus the explicitly RCA-justified removal of the inventory-only payload restriction, not behavior deletion.
  implication: Cluster 1 passes all applicable fix-acceptance guardrail signals, with mutation checking explicitly skipped.
- timestamp: 2026-09-13T10:51:00+08:00
  observation: Cluster 1 was committed atomically as `71218ca0a` with only the six shared contract/router/normalizer and focused test files.
  implication: Cluster 2 can now be implemented and verified independently without mixing endpoint/CAS changes into the snapshot normalization commit.
- timestamp: 2026-09-13T11:01:00+08:00
  observation: The first adjacent canonical API run exposed nine compatibility failures because production normalization tried to authorize browser rows that the endpoint deliberately discards; normalizing the authority-free projection restored all 85 canonical API/snapshot tests.
  implication: Strict structural validation belongs at request parsing, while shared canonicalization must run on the exact authority-free projection that can reach orchestration; untrusted browser rows remain non-authoritative.
- timestamp: 2026-09-13T11:03:00+08:00
  observation: The first drawer run exposed legacy-only test fixtures and three incomplete v2 fixtures; after replacing those with strict canonical fixtures and removing the obsolete legacy-response test, 22/22 drawer tests pass.
  implication: The remaining failures were test-contract drift caused by intentional removal of the legacy drawer path, not product regressions.
- timestamp: 2026-09-13T11:04:00+08:00
  observation: The cluster 1 commit was amended to `864200eba` to include the authority-free production-normalization correction; the worktree now contains only cluster 2 source/tests plus the active debug file.
  implication: Atomic separation between snapshot normalization and endpoint/CAS migration is preserved.
- timestamp: 2026-09-13T11:10:00+08:00
  observation: Cluster 2 focused/adjacent verification passes 163 Python tests and 139 web tests; Ruff and strict TypeScript checking pass, with only pre-existing React `act(...)` warnings in the Inventory test output.
  implication: Canonical-only drawer submission, first-turn compatibility, stale 409-before-tool-I/O, thread continuity, inventory, and investigation neighbors remain green.
- timestamp: 2026-09-13T11:11:00+08:00
  observation: Diff review confirms the deleted drawer branch is exactly the legacy `/investigate-context`/`/copilot/investigate` submission path replaced by one canonical request path; no excluded file appears in the diff.
  implication: The deletion is root-cause-directed consolidation rather than behavior suppression; revert-and-reconfirm is the remaining guardrail signal.
- timestamp: 2026-09-13T11:15:00+08:00
  observation: With cluster 2 production files temporarily restored from HEAD, both expected-revision tests failed because the field was forbidden and five drawer tests failed because requests returned to legacy behavior; restoring the staged files returned the two CAS tests, 22 drawer tests, and TypeScript checking to green.
  implication: Revert-and-reconfirm proves the cluster 2 implementation is necessary and sufficient for the focused endpoint/CAS behavior.
- timestamp: 2026-09-13T11:17:00+08:00
  observation: Stryker remains unavailable; the mutation signal is explicitly skipped. Target, adjacent, no-op/deletion review, and revert/reconfirm signals all pass.
  implication: Cluster 2 satisfies every applicable fix-acceptance guardrail signal.
- timestamp: 2026-09-13T11:20:00+08:00
  observation: Cluster 2 was committed atomically as `3e30cb8b1`; both code commits contain the required Copilot co-author trailer.
  implication: The requested implementation is durable in two reviewable commits while the overall debug session remains open for later clusters.

## Eliminated

- hypothesis: Each affected page has an independent validation bug.
  evidence: Failures align with shared v1/v2 models, common adapter submission, and shared backend bounds.
  timestamp: 2026-09-13T09:48:00+08:00
- hypothesis: Raising backend evidence limits is a safe complete fix.
  evidence: Cross-runtime sizing and missing deterministic structural normalization would remain divergent and unbounded.
  timestamp: 2026-09-13T09:49:00+08:00
- hypothesis: Foundry availability alone explains generic responses.
  evidence: Non-vulnerability deterministic answer synthesis and material claim/citation closure are absent in source.
  timestamp: 2026-09-13T09:56:00+08:00

## Root Causes

1. Shared snapshot contracts and normalization are not authoritative across Python and
   TypeScript, and production callers bypass the existing v2 canonicalizer.
2. Investigation submission is split across three endpoint contracts and omits optimistic
   thread revision CAS on most integrated pages.
3. Evidence and claims lack immutable page/entity/filter/query/generation identity and
   retained claim-level citation closure.
4. Specialist routing broadens from global keywords rather than intersecting question intent
   with the page manifest's reviewed safe set.
5. Redirect declarations, implementation, and tests encode different exact destinations.
6. Runtime rollout/provider configuration is only partially wired; remaining live provider
   parity requires external onboarding evidence that must not be fabricated.

## Resolution

root_cause: "Cluster 1: v1/v2 schema drift plus an inventory-only canonical boundary bypassed the shared v2 canonicalizer. Cluster 2: integrated drawers selected legacy endpoints and omitted the retained thread revision, while the service reconciled conflicts instead of honoring caller CAS."
fix: "Clusters 1-2 complete: added strict shared TypeScript v2 normalization with matching character/UTF-8/structural bounds; invoked backend canonicalization on the authority-free production projection; accepted all manifest-backed page kinds while preserving the inventory selector adapter; moved every CopilotDrawer turn to `/copilot/investigations`; added optional same-tab expected revision and pre-I/O conflict rejection. Clusters 3-6 remain open."
verification:
  target_test:
    result: pass
    details: "Python snapshot/API/CAS targets and web normalizer/drawer targets pass."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker dependency or configuration exists."
    mutant_killed: false
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    details: "The removed drawer branches were the divergent legacy endpoints identified by root cause 2."
  adjacent_tests:
    result: pass
    suites_run:
      - "163 Python canonical API, snapshot, thread-store, and orchestration parity tests"
      - "139 web drawer, thread continuity, page adapter, Inventory, and Investigate tests"
      - "Ruff on touched Python files"
      - "TypeScript `tsc --noEmit`"
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
  guardrail_verdict: accepted
files_changed:
  - src/api/routers/copilot.py
  - src/operations/orchestration_contract.py
  - src/operations/orchestration_service.py
  - tests/test_api_copilot_snapshot_v2.py
  - tests/test_api_copilot_unified.py
  - tests/test_page_context_v2.py
  - web/src/components/ui/CopilotDrawer.test.tsx
  - web/src/components/ui/CopilotDrawer.tsx
  - web/src/lib/copilot/page-adapters.test.ts
  - web/src/lib/copilot/page-adapters.ts
  - web/src/lib/types.ts
oracle_type: specified
