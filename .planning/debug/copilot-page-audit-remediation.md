---
status: investigating
trigger: Phase 11 live Copilot page-audit failures
created: 2026-09-13T09:37:49+08:00
updated: 2026-09-13T12:50:00+08:00
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
hypothesis: The four independent-review gaps in the canonical migration are corrected and committed; the next unresolved root cause is cluster 4, where global keyword routing can broaden beyond the exact specialist set allowed by the newly precise manifest-backed page kind.
test: Add exact-set routing tests across Services, Twin, Predeploy, and Identity that vary only free-form question keywords and assert selected specialists equal the reviewed page mapping rather than a broader global match.
expecting: Current substring routing can add globally matching specialists outside the active exact page mapping, and existing tests permit subset behavior.
next_action: Trace `select_specialists_for_turn` and canonical fallback with the now-exact v2 page kinds, then begin exact-set specialist-routing RED tests; do not modify redirects/readiness or archive this session.
remaining_external_uncertainty:
  - "The referenced live 11-UAT matrix and correlation payloads remain absent, so exact production replay is still unavailable."
  - "Live Foundry/provider onboarding and immutable deployment parity remain external readiness evidence and were not fabricated or contacted."
candidate_causes:
  - "code: compatibility normalization and UI/retry projections discard canonical contract fields or reuse stale client state"
  - "data: legacy snapshots may omit hints and contain evidence counts unrelated to source coverage, while server 409 bodies may intentionally omit authorized revision metadata"
and_gate: "no for each reported gap — each is independently reproducible from a deterministic code path; data shape selects the branch but does not need to be corrupt"

## Evidence

- timestamp: 2026-09-13T12:18:00+08:00
  observation: `normalizeCopilotSnapshotV2` copies the legacy seven-value `page_kind` directly into v2 and sets coverage to `{visible_count: evidence.length, total_count: evidence.length, complete: false}` even though every typed core adapter emits explicit `page/coverage` observations with visible/total/complete fields.
  implication: Exact manifest routing and observed partial coverage are both lost at the same compatibility boundary; evidence cardinality is not a coverage observation.
- timestamp: 2026-09-13T12:18:00+08:00
  observation: The 23 integrated routes already have stable page IDs and exact v2 manifest keys, but `COPILOT_ROUTE_DISPOSITIONS` and legacy builders still use broad v1 anchors for Connections, Identity, FinOps, Services, Twin, and other route-specific adapters.
  implication: A deterministic page-ID-to-v2-kind projection can migrate every integrated adapter without editing excluded page components.
- timestamp: 2026-09-13T12:18:00+08:00
  observation: Cluster 3 already added `synthesis` to `CanonicalCopilotResult` and maps cited claims into drawer narration, but the render branch displays narration and `toolCalls` together; tool result data is therefore duplicated when synthesis summarizes it.
  implication: The independent synthesis gap is partially corrected in HEAD, leaving a focused presentation de-duplication defect rather than a missing contract field.
- timestamp: 2026-09-13T12:18:00+08:00
  observation: `CopilotDrawer` resets continuity only for a non-disclosing thread 404. A 409 conflict becomes a normal error turn, while the provider retains the rejected `{thread_id, thread_revision}`, so pressing Retry submits the identical stale CAS.
  implication: Without exposing server revision metadata, fail-closed recovery is to discard local continuity on 409 and require the next explicit user action to start a new server thread.
- timestamp: 2026-09-13T12:25:00+08:00
  observation: The focused RED run produced 23 failures and 107 passes: 18 broad-to-exact page-kind failures, two coverage failures, one synthesis/tool duplication failure, and one stale-CAS reset failure (plus the route-disposition half of the table assertions folded into the same page-kind cases).
  implication: All four review gaps are reproducible before production edits, while 107 neighboring tests establish a stable local baseline.
- timestamp: 2026-09-13T12:31:00+08:00
  observation: After the surgical implementation, the two focused Vitest files pass 130/130 tests, including all route-specific no-hint mappings, observed partial coverage, synthesis de-duplication, and threadless recovery after a stale 409.
  implication: The targeted fixes satisfy their regression oracles; adjacent manifest, continuity, cluster 1-3, lint, and type gates remain to be checked.
- timestamp: 2026-09-13T12:38:00+08:00
  observation: Adjacent web manifest/continuity/integration/Inventory/Investigate tests pass 47/47; 281 adjacent Python canonical snapshot/API/evaluation/policy/parity/thread tests pass; Ruff and strict TypeScript checking pass.
  implication: The corrections preserve clusters 1-3, backend authorization/CAS behavior, route-manifest parity, and same-tab continuity; only revert-and-reconfirm and final scope/diff review remain.
- timestamp: 2026-09-13T12:45:00+08:00
  observation: With only the three production files stashed, the focused suite returned to the exact 23 RED failures; restoring them returned 130/130 tests and strict TypeScript to green. The citation-adjacency assertion also passes.
  implication: Revert-and-reconfirm proves the implementation removes all four reproduced gaps, including adjacent claim citations, rather than the environment or test fixtures masking them.
- timestamp: 2026-09-13T12:45:00+08:00
  observation: No Stryker dependency or configuration exists; mutation testing is unavailable. Diff review is additive or directly replaces the incorrect broad mapping/evidence-count behavior, and no excluded page, Fabric mapper, Exposure CVE page, launcher, or Patch Priorities publication/data file is touched.
  implication: All applicable fix-acceptance signals pass and the constrained ownership boundary is preserved.
- timestamp: 2026-09-13T12:50:00+08:00
  observation: The five scoped web source/test files were committed atomically as `ec491f753` with the required Copilot co-author trailer.
  implication: The independent-review corrections are durable and isolated; the active session can proceed to exact-set specialist routing without reopening canonical migration work.
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
- timestamp: 2026-09-13T11:35:00+08:00
  observation: The first RED commands repeated two known harness mistakes: root-level npm could not find `package.json`, and the worktree `.venv` lacked pytest.
  implication: These are invocation failures only; corrected commands are `npm --prefix web ...` and `uv run --extra test pytest ...`.
- timestamp: 2026-09-13T11:39:00+08:00
  observation: The corrected focused Python RED run fails three tests exactly at the missing seams: `_retained_evidence` rejects an `evidence_selection_id`, and snapshot v2 rejects normalized `filters` and `query`.
  implication: Current retained selection cannot distinguish stale zero-count evidence by page/entity/filter/query/generation, and the identity dimensions are absent from the canonical contract.
- timestamp: 2026-09-13T11:40:00+08:00
  observation: The focused KB adapter RED test shows visible `product`, `target_date`, `product_name`, and finding `target_date` inputs are dropped while publication date and affected count remain.
  implication: KB detail cannot answer product/target factual questions from retained evidence even when the page provides those values.
- timestamp: 2026-09-13T11:41:00+08:00
  observation: The focused drawer RED test renders the generic fallback status, 1-of-137 coverage, uncertainty, and retained citation but omits the supplied direct claim and renders `No matching context was found`.
  implication: Provider-unavailable canonical output has no visible direct-answer projection even when a citation-closed deterministic claim is present.
- timestamp: 2026-09-13T11:47:00+08:00
  observation: The first adjacent run exposed four inventory authority regressions because newly minted page citations were returned beside authoritative inventory tool citations, including one citation-bound overflow.
  implication: Browser inventory rows must remain selector-only; retained page-observation citations are now limited to non-inventory material claims, preserving the existing inventory authority fence and citation bound.
- timestamp: 2026-09-13T11:48:00+08:00
  observation: The first web adjacent run exposed two intentional contract-expectation changes: normalized v2 snapshots now retain filters/query/generation and generate per-row material claims instead of dropping all of them.
  implication: Updating the old assertions to require the stronger contract is appropriate; no runtime regression caused those two failures.
- timestamp: 2026-09-13T11:50:00+08:00
  observation: Focused and immediate adjacent verification now passes 184 Python canonical snapshot/API/synthesis tests, 104 web adapter/drawer tests, Ruff, and strict TypeScript checking.
  implication: Exact selection identity, KB fact retention, deterministic cited answers, inventory authority isolation, and visible output projection coexist without weakening the tested scope/CAS/citation boundaries.
- timestamp: 2026-09-13T11:56:00+08:00
  observation: Broader Phase 11 adjacency passes 142 Python orchestration/policy/thread/provider tests and 52 web manifest-parity/thread/integration/Inventory/Investigate tests; the web run emits only pre-existing Inventory React `act(...)` warnings.
  implication: The cluster preserves specialist policy, durable continuity, provider contracts, route integration, and inventory behavior beyond the driving tests.
- timestamp: 2026-09-13T11:57:00+08:00
  observation: Diff review shows additive validation, identity, bounded retained-fact, deterministic-claim, and UI projection logic; no excluded or Patch Priorities publication/data file is modified.
  implication: The no-op/deletion guard passes and scope constraints remain intact; revert-and-reconfirm is the final applicable acceptance signal.
- timestamp: 2026-09-13T12:01:00+08:00
  observation: With only the seven production files stashed, all three Python identity/fallback tests, the KB adapter test, and the drawer direct-answer test returned to their original RED failures; restoring the stash returned all five focused tests to green.
  implication: Revert-and-reconfirm proves this implementation, not environment or fixture drift, removes the stale-selection and generic-fallback defects.
- timestamp: 2026-09-13T12:02:00+08:00
  observation: No Stryker dependency or configuration is present; mutation testing is unavailable. The diff is additive/root-cause-directed, target and adjacent suites pass, and the temporary guardrail stash was dropped.
  implication: All applicable fix-acceptance signals pass, with mutation checking explicitly skipped rather than assumed.
- timestamp: 2026-09-13T12:06:00+08:00
  observation: Cluster 3 code and focused tests were committed atomically as `8143a0207` with the required Copilot co-author trailer; no excluded file is present in the commit.
  implication: Immutable evidence selection and deterministic cited fallback are durable while the debug session remains open for exact-set routing, redirect, and readiness clusters.

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

root_cause: "Cluster 1: v1/v2 schema drift plus an inventory-only canonical boundary bypassed the shared v2 canonicalizer. Cluster 2: integrated drawers selected legacy endpoints and omitted the retained thread revision, while the service reconciled conflicts instead of honoring caller CAS. Cluster 3: v2 dropped normalized page filters/query and retained turns had no immutable page/entity/scope/generation selection identity; the no-Foundry path emitted no direct citation-closed page claims and the KB adapter dropped provided product/target facts. Independent-review correction: the compatibility seam still copied broad v1 page kinds and fabricated coverage from evidence cardinality; the drawer rendered canonical synthesis beside duplicate tool cards and retained stale CAS continuity after 409."
fix: "Clusters 1-3 plus independent-review corrections complete: added strict shared TypeScript v2 normalization and canonical-only drawer/CAS behavior; added normalized filter/query plus content-derived generation identity, exact retained-evidence selection, deterministic cited fallback, and KB fact retention; now maps every integrated page ID/route to its exact manifest v2 kind, aggregates only typed coverage observations with unknown 0/0 fallback, renders synthesis claims with adjacent citations while suppressing overlapping tool cards, and clears stale continuity on 409 so the next explicit attempt starts a new thread. Exact-set specialist routing remains next."
verification:
  target_test:
    result: pass
    details: "130 focused page-adapter/drawer tests pass after 23 targeted RED failures were reproduced."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker dependency or configuration exists."
    mutant_killed: false
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    details: "The review fix adds exact mapping/coverage validation and conflict recovery; the only render suppression removes raw tool cards when a citation-bearing synthesis already presents the same result."
  adjacent_tests:
    result: pass
    suites_run:
      - "281 Python canonical snapshot/API/evaluation/policy/parity/thread tests"
      - "130 web drawer and page-adapter tests"
      - "Two adjacent web runs (47 and 33 passing assertions, with manifest/continuity overlap) covering integration, Inventory, Investigate, and drawer-button behavior"
      - "Ruff on src and tests"
      - "TypeScript `tsc --noEmit`"
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
  guardrail_verdict: accepted
commits:
  - "8143a0207 fix(copilot): bind retained evidence to page context"
  - "ec491f753 fix(copilot): close canonical migration review gaps"
files_changed:
  - src/api/routers/copilot.py
  - src/operations/orchestration_contract.py
  - src/operations/orchestration_service.py
  - tests/test_copilot_evaluation_v2.py
  - web/src/components/ui/CopilotDrawer.test.tsx
  - web/src/components/ui/CopilotDrawer.tsx
  - web/src/lib/copilot/thread-context.tsx
  - web/src/lib/copilot/page-adapters.test.ts
  - web/src/lib/copilot/page-adapters.ts
  - web/src/lib/types.ts
oracle_type: specified
