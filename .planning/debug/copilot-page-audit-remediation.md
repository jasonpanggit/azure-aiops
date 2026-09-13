---
status: awaiting_human_verify
trigger: Phase 11 live Copilot page-audit failures
created: 2026-09-13T09:37:49+08:00
updated: 2026-09-13T12:56:00+08:00
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
hypothesis: "Confirmed and fixed: all six final-review blockers are green together, causal revert/reconfirm passes, and broad committed Phase 11 offline validation is clean."
test: "Final committed validation passed the broad backend selection, all six web files, Ruff, strict TypeScript, evaluator/corpus syntax, and 9/9 offline specialist parity checks."
expecting: "An independent final validation/review finds no remaining blocking issue; live/provider readiness remains explicitly BLOCKED and no deployment is attempted."
next_action: "Run independent final validation/review of commits ae34e35ae, ed3751d79, and 6c82cf4e0; if clean, record human confirmation. Do not archive before that confirmation."
reasoning_checkpoint:
  hypothesis: "The review blockers occur because shared boundaries preserve legacy or presentation-level behavior after the canonical contracts became authoritative: CAS validation is outside the store lock, evaluator dispatch/schema gates cover only legacy kinds, reviewed cross-domain grants were removed from selector policy and corpus data, fallback ignores the selector result, adapter trimming does not update trust metadata, and conflict grouping bypasses canonical entity identity."
  confirming_evidence:
    - "The agent-authored focused Python run produced 9 deterministic failures exactly at the six reported seams, including both ARM/domain alias variants and all routing/evaluator/CAS assertions."
    - "The agent-authored focused Vitest run produced 7 deterministic failures across the byte- and row-retention boundary assertions; 104 unrelated tests in the same file were skipped by name filtering rather than failing."
    - "Direct source inspection shows the stale comparison after mutating authorize, the six-kind evaluator allowlist, corpus set reductions, appended page owners, silent retention pop/limit, and raw entity serialization."
  falsification_test: "Any focused regression passing before its corresponding source/data fix, or remaining red after reverting only that fix, would disprove that seam's causal diagnosis."
  fix_rationale: "Move each invariant to its authoritative boundary: CAS under the store lock before mutation; canonical v2 fixture construction for every integrated case; explicit reviewed cross-domain grants with restored gold sets; selected-first valid call construction with one fallback; retention metadata plus conservative coverage; and shared canonical entity keys for conflict grouping."
  blind_spots: "Adjacent legacy callers, release artifact recomputation, selector page-safety accounting, exact snapshot byte accounting, and full Phase 11 backend/web compatibility are not yet rerun after fixes."
  candidate_causes:
    - "code: ordering/filtering/normalization logic at six shared boundaries violates the intended contracts"
    - "data: four reviewed gold-corpus expected specialist sets were edited to bless narrowed production behavior"
    - "config/environment: no live provider or runtime configuration is required to reproduce any failure, so these branches are currently disfavored"
  and_gate: "yes — all six independent findings must be green for the review checkpoint to pass, although each individual deterministic symptom has its own sufficient code or corpus cause"
remaining_external_uncertainty:
  - "The referenced live 11-UAT matrix and correlation payloads remain absent, so exact production replay is still unavailable."
  - "The reported Foundry project has only one governed connection named `demo`; exact distinct `operations-mcp` and `azure-mcp` project-connection resource IDs and payloads remain absent."
  - "No real candidate artifact proving all twelve specialist plus coordinator provider-version IDs exists in this offline cycle."
  - "Live Foundry/MCP parity, deployed revision identity, compatibility→shadow→canary observation, and promotion baseline remain BLOCKED and were not fabricated or contacted."
  - "Terraform provider-schema validation remains locally blocked because the existing `.terraform` cache lacks all locked provider packages; no provider initialization was attempted."
candidate_causes:
  - "config: rollout mode may be declared but not consumed by runtime wiring"
  - "environment: provider onboarding/deployed revision evidence is unavailable in this offline cycle"
and_gate: "possibly — source readiness and external provider readiness are independent required conditions for release promotion"

## Evidence

- timestamp: 2026-09-13T11:18:23+08:00
  observation: The continuation review reports six deterministic blockers after the prior checkpoint: stale CAS is checked after authorization mutation; integrated v2 fixtures bypass exact canonical dispatch/schema gating; reviewed cross-domain grants were removed and fixture expectations weakened; fallback appends all page specialists; adapter trimming preserves false complete coverage without omission metadata; and conflict identity bypasses repository canonical entity normalization.
  implication: Human verification failed. The session returns to investigation; all six require focused RED tests and root-cause fixes before final validation, while live/deployment actions and listed owned files remain excluded.
- timestamp: 2026-09-13T11:21:00+08:00
  observation: `.planning/STATE.md` still names Phase 4 planning and its unrelated entry gate, but this continuation explicitly authorizes the six Phase 11 review blockers. Git status contains only the active debug-file update on top of the prior checkpoint commits, and no project `rules/*.md` overlay exists.
  implication: The work remains an isolated Phase 11 exception. Shared thread/orchestration/evaluation/routing/page-context/adapter files and focused tests are in scope; all listed ownership exclusions and live operations remain out of scope.
- timestamp: 2026-09-13T11:21:00+08:00
  observation: Initial source search directly locates expected-revision comparisons after both `thread_store.authorize` calls, a context-page allowlist in evaluator dispatch, fallback construction that starts from `decision.selected_ids` and later references page specialists, raw conflict logic in page context, and explicit adapter trimming paths.
  implication: The review findings map to deterministic code paths suitable for test-first reproduction; SBFL remains skipped because these are static contract failures with no per-test coverage spectrum.
- timestamp: 2026-09-13T11:26:00+08:00
  observation: `InvestigationThreadStore.authorize()` runs under its lock but unconditionally ages every retained turn, replaces scope/fingerprint, updates `last_seen`, and persists. Both `execute_turn()` and `unsupported()` compare `expected_thread_revision` only after this method returns.
  implication: Finding 1 is confirmed at the mechanism level: stale CAS is side-effecting before rejection, and the correct atomic seam is an optional expected revision checked inside locked authorization before any mutation or persistence.
- timestamp: 2026-09-13T11:26:00+08:00
  observation: `_investigate()` in `scripts/evaluate_agents.py` sends only six legacy page kinds to `/copilot/investigate-context`; every other integrated v2 case falls through to question-only `/copilot/investigate`. `_deterministic_applicable_case_ids()` and `result_to_release_evidence()` likewise limit snapshot-schema evidence to those six kinds.
  implication: Finding 2 is source-confirmed: most integrated fixtures neither carry their exact `page_kind` nor produce fail-closed schema evidence, so the live release gate cannot validate the canonical v2 contract for the full integrated corpus.
- timestamp: 2026-09-13T11:26:00+08:00
  observation: `select_specialists_for_turn()` now intersects intent only with the page-owned set, removing reviewed cross-domain grants; `build_deterministic_fallback()` then appends every page owner after the question-first `selected_ids`, even when a selected valid call already exists.
  implication: Findings 3 and 4 share the routing seam but are distinct: reviewed cross-domain pairs need explicit allowlisted grants, while fallback call construction must honor the selected result and add at most one page-safe call only when selection yields no valid call.
- timestamp: 2026-09-13T11:26:00+08:00
  observation: `buildCoreCopilotContext()` limits rows to 200 and repeatedly pops retained IDs until the 128-KiB snapshot bound fits, but it does not alter coverage or uncertainty when these retention operations omit candidate rows. `select_browser_evidence_for_retention()` groups conflicts using raw `row.entity.model_dump()` or raw fallback resource text rather than the canonical entity key used by canonicalization.
  implication: Findings 5 and 6 are source-confirmed data-contract defects: truncation can be mislabeled complete, and semantically identical ARM/domain aliases can evade conflict exclusion.
- timestamp: 2026-09-13T11:35:00+08:00
  observation: The complete agent-authored RED set fails as predicted before production changes: 9 Python failures cover store-level CAS API absence/no-mutation, two canonical alias conflicts, four weakened corpus sets, legacy/noncanonical integrated dispatch, missing v2 schema gating, absent reviewed cross-domain grants, and fallback over-invocation. Seven focused Vitest cases fail across the existing trim case plus 64/65/66 byte-neighborhood and 199/200/201 total-row-neighborhood checks.
  implication: All six findings are reproducible offline with specified oracles and no live provider, environment, secret, or excluded-file dependency. Root cause is confirmed and implementation may begin.
- timestamp: 2026-09-13T11:39:00+08:00
  observation: After moving expected-revision comparison into locked `authorize()` before mutation and passing it from both service paths, the new durable no-mutation regression and existing stale-before-tool-I/O regression both pass.
  implication: Finding 1 is corrected at the atomic store boundary; stale narrower requests no longer alter scope, retained observation state, last_seen, or durable storage revision before 409.
- timestamp: 2026-09-13T11:42:00+08:00
  observation: After replacing the evaluator's six-kind branch with strict v2 construction and `/api/v1/copilot/investigations` for every integrated disposition, both all-integrated request-capture and snapshot-schema-gating regressions pass.
  implication: Finding 2 is corrected; every integrated fixture now carries its exact page kind through the canonical contract and contributes required schema evidence.
- timestamp: 2026-09-13T11:49:00+08:00
  observation: Five of six focused routing/fallback checks pass after introducing reviewed grants and selected-only call construction. The sole failure is the corpus assertion: `cross.net.cve` remains narrowed, proving the generic JSON hunk did not target the named case and may have touched earlier matching arrays.
  implication: Production findings 3-4 are behaviorally corrected, but corpus data must be repaired by case identity rather than context-free textual replacement before acceptance.
- timestamp: 2026-09-13T11:54:00+08:00
  observation: After reverting the four accidental generic JSON edits and restoring only the four named reviewed cases, all six focused selector, policy, corpus, page-safety, and fallback checks pass.
  implication: Findings 3 and 4 are corrected: reviewed cross-domain pairs are explicit and exact, unrelated keyword broadening remains denied, the gold corpus is no longer weakened, and fallback no longer appends unselected page owners.
- timestamp: 2026-09-13T11:58:00+08:00
  observation: Refactoring canonical entity identity into one helper used by both canonicalization and browser conflict grouping makes the existing conflict test plus ARM-case and domain-case alias regressions pass.
  implication: Finding 6 is corrected without a competing normalization algorithm; contradictory aliases are excluded and surface uncertainty before synthesis.
- timestamp: 2026-09-13T12:02:00+08:00
  observation: The first retention implementation run fails all seven cases at one new `Object.entries(coverage)` TypeError, before any boundary assertion.
  implication: This is an implementation control-flow error in the new build closure, not evidence against the retention root cause; inspect and correct the return shape before evaluating semantics.
- timestamp: 2026-09-13T12:05:00+08:00
  observation: After correcting the return shape, metadata assembly succeeds, but all seven tests fail only when normalizing the retained v1 adapter snapshot to strict v2 because v2 expansion exceeds 128 KiB.
  implication: The original trimming measured the smaller legacy shape rather than the actual canonical wire payload. Byte retention must be gated against strict v2 serialization to satisfy the cross-runtime bound.
- timestamp: 2026-09-13T12:09:00+08:00
  observation: After gating retention against the normalized strict-v2 wire size, all seven adapter tests pass across the existing large-payload case, 64/65/66 byte-pressure neighborhood, and 199/200/201 total-row neighborhood.
  implication: Finding 5 is corrected: omissions are bounded and counted, returned and wire coverage become incomplete, uncertainty names the exact omitted count, and both 200-row and 128-KiB limits remain enforced.
- timestamp: 2026-09-13T12:12:00+08:00
  observation: The complete focused regression set passes together: 10 Python cases (including two canonical alias parameters) and 7 web retention cases.
  implication: All six blockers are green in their driving tests; proceed to held-out Phase 11 adjacency and static validation.
- timestamp: 2026-09-13T12:18:00+08:00
  observation: All six Copilot web files pass 169/169. The broad backend run has only three routing failures: two API tests still require the now-rejected narrowed Network-only behavior for the explicitly restored Governance/Vulnerability grants, and one legacy `remediation_page` test loses its existing Governance selection because grants are keyed by canonical `remediation`.
  implication: The first two are stale assertions directly contradicted by the required reviewed grant restoration; the third is a real compatibility gap in legacy page-kind alias handling and needs a minimal canonical-key lookup fix.
- timestamp: 2026-09-13T12:22:00+08:00
  observation: The two corrected Network API tests pass and the remediation alias now preserves Governance, but the same held-out remediation test also requires the previously reviewed Vulnerability grant for CVE intent.
  implication: Positive grant restoration must include both existing remediation-page cross-domain paths; this is not global keyword broadening because the grant remains an explicit page-and-intent pair.
- timestamp: 2026-09-13T12:27:00+08:00
  observation: After adding the explicit remediation-to-Vulnerability grant, all three held-out routing tests pass. The complete backend Phase 11 selection then passes with one pre-existing packaging skip, and all six web files pass 169/169.
  implication: Canonical and legacy API routing, reviewed cross-domain grants, fallback, thread continuity, evaluation, providers, specialists, MCP contracts, adapters, drawer continuity, and manifest parity remain compatible.
- timestamp: 2026-09-13T12:31:00+08:00
  observation: Strict TypeScript passes, the changed Python evaluator compiles, the corpus parses as JSON, and offline specialist parity passes all 9 checks. Ruff reports only one auto-fixable import-order issue in `orchestration_policy.py`; the first collection-count command ended on warning text rather than the summary line.
  implication: No semantic/static regression is present in those gates; apply the deterministic import reorder and recollect the test count explicitly.
- timestamp: 2026-09-13T12:34:00+08:00
  observation: After the import reorder, full Ruff passes. No shell file changed, so shell syntax validation is not applicable; the changed Python script and JSON corpus already passed syntax/parse checks.
  implication: Static validation is green. Remaining guardrails are final diff/scope review and causal revert-and-reconfirm.
- timestamp: 2026-09-13T12:38:00+08:00
  observation: Final changed paths are limited to the active debug file, seven shared backend source/policy files, the evaluator script and reviewed corpus, five focused backend tests, and the shared web adapter/test. `git diff --check` passes, no excluded ownership file appears, and no Stryker/mutmut/cosmic-ray configuration exists.
  implication: The no-op/deletion and scope guardrails pass; mutation testing is unavailable and explicitly skipped. Revert-and-reconfirm remains.
- timestamp: 2026-09-13T12:43:00+08:00
  observation: With only production/evaluator/corpus fixes path-stashed and all driving tests retained, the focused run restores 9 Python failures and all 7 web failures at the original six seams; the pre-existing service-level stale-before-tool test remains green because it does not assert authorization persistence.
  implication: The bug set causally returns when the fixes are removed. Restore the same stash and require every focused case to return green to complete guardrail signal 5.
- timestamp: 2026-09-13T12:47:00+08:00
  observation: The path-scoped stash restored without conflict, and the identical focused commands returned 10/10 Python cases and 7/7 web cases to green.
  implication: Revert-and-reconfirm passes for all six blockers; the fix—not environment or test drift—is necessary and sufficient for the focused behavior.
- timestamp: 2026-09-13T12:51:00+08:00
  observation: The six review fixes were committed atomically as `ae34e35ae` (locked stale-CAS rejection), `ed3751d79` (canonical evaluator dispatch, reviewed routing/fallback, canonical conflicts), and `6c82cf4e0` (truthful bounded web retention); each commit contains the required Copilot co-author trailer.
  implication: Source and tests are durably separated by concern. Final post-commit validation and review is now the only remaining action; the session must remain active and unarchived.
- timestamp: 2026-09-13T12:56:00+08:00
  observation: Final post-commit validation passes the complete selected backend Phase 11 suite with one pre-existing packaging skip, all six Copilot web files with 169/169 tests, strict TypeScript, full Ruff, evaluator bytecode and corpus JSON validation, and offline specialist parity 9/9. Git scope review lists only the authorized shared source/tests/corpus/active-debug paths and the worktree was clean before this final debug update.
  implication: All six blocking findings and adjacent offline contracts are green in committed state. The active session remains unarchived for independent final review/human confirmation; live provider/deployment evidence remains BLOCKED and was not contacted or fabricated.
- timestamp: 2026-09-13T15:20:00+08:00
  observation: The active session and `.planning/STATE.md` confirm this is an explicitly authorized Phase 11 source/config exception while Phase 4 remains the nominal planning phase; the worktree is clean except for the active debug session, and no configured debugger skill overlay was returned.
  implication: Investigation may touch only the requested provider/deployment-readiness source, tests, and documentation; live infrastructure and the listed owned-file exclusions remain out of scope.
- timestamp: 2026-09-13T15:28:00+08:00
  observation: Phase 11 Plan 05 requires persisted real provider-version mappings and a BLOCKED live gate when external configuration is absent; Plan 12 and its runbook promise compatibility→shadow→canary→default via `AIOPS_COPILOT_ROLLOUT_MODE`, while the continuation explicitly forbids treating absent deployed evidence as a pass.
  implication: Offline remediation must wire deterministic non-secret values and runtime control only; it must not create a second governed connection, provider ID, candidate mapping, or deployed baseline.
- timestamp: 2026-09-13T15:36:00+08:00
  observation: `outputs.tf` exposes only `foundry_project_endpoint` among the requested provider values. Terraform computes both exact APIM MCP URLs, the APIM audience, rollout mode/percentage/rollback mode, and a promotion-artifact path internally, but provides no authoritative sourceable output contract for them.
  implication: Operators currently must hand-author deterministic non-secret parity inputs, creating drift risk even though Terraform already owns the values.
- timestamp: 2026-09-13T15:36:00+08:00
  observation: Repository runtime code has no reference to `AIOPS_COPILOT_ROLLOUT_MODE`, `AIOPS_COPILOT_CANARY_PERCENTAGE`, or `AIOPS_COPILOT_ROLLBACK_MODE`; route branches consume only `canonical_orchestration_enabled()` from `AIOPS_AGENT_ORCHESTRATION_MODE`.
  implication: The runbook's compatibility/shadow/canary/default behavior is declarative only; a deployed rollout variable cannot currently alter request routing or fail closed on malformed/missing values.
- timestamp: 2026-09-13T15:36:00+08:00
  observation: Live parity loads specialist names/provider version IDs from `FOUNDRY_CANDIDATE_MAPPING` and compares allowed tool names by `server_label`, but `_agent_allowed_tools` discards each Foundry tool's `project_connection_id`.
  implication: A candidate can appear grant-correct while pointing at a wrong, absent, or hand-invented project connection; real governed connection identity is not part of the live parity proof.
- timestamp: 2026-09-13T15:51:00+08:00
  observation: The agent-authored focused readiness suite produced 22 deterministic RED failures: the sourceable exporter is absent, the rollout decision API is absent, the Terraform output map is absent, route calls do not provide stable canary identity, and candidate parsing still returns only agents/coordinator.
  implication: The regressions independently reproduce each source/config omission before production changes; the oracle is specified by the Phase 11 rollout/provider contracts.
- timestamp: 2026-09-13T16:15:00+08:00
  observation: After adding the allowlisted exporter/output map, fail-closed stable rollout selector, request-bound consumption, and candidate connection identities, all 22 focused readiness tests pass; the 66-test specialist packaging suite also passes with one pre-existing package-build skip, and focused Ruff is clean.
  implication: The direct regressions are green; adjacent canonical API behavior and stronger live connection/binding negative cases remain to be verified.
- timestamp: 2026-09-13T16:31:00+08:00
  observation: The expanded provider/package suite now proves publication stops before any provider call when either connection ID is missing or duplicated, a live inventory containing only `demo` returns `BLOCKED`, and an agent version bound to the wrong project connection fails parity. All focused and adjacent route/provider tests pass.
  implication: Source wiring no longer converts one observed connection into two invented identities; live promotion remains held until both Terraform-created connection resource IDs and pinned agent versions are externally observable.
- timestamp: 2026-09-13T16:31:00+08:00
  observation: `terraform fmt -check`, shell syntax, scoped Ruff, and the strengthened nine-check offline specialist parity gate pass. `terraform validate -no-color` cannot run because the local `.terraform` cache lacks all locked provider packages; no init was attempted because this cycle forbids provider/network contact.
  implication: HCL formatting and source-level parity are verified offline; provider-backed Terraform schema validation remains an explicit local-tooling blocker rather than a fabricated pass.
- timestamp: 2026-09-13T16:43:00+08:00
  observation: The complete selected provider/orchestration adjacency passes, including focused readiness, packaging, canonical/legacy API, context routing, manifest/policy parity, Foundry, and Operations MCP tests; scoped Ruff, shell syntax, Terraform formatting, and strengthened offline parity pass.
  implication: The new source/config behavior coexists with legacy compatibility, deterministic rollback, exact-FQDN/bearer guards, and existing provider degradation contracts.
- timestamp: 2026-09-13T16:43:00+08:00
  observation: Running live parity in an empty environment makes zero network calls, reports only the eight missing variable names, returns `status=blocked`, and exits 3.
  implication: External prerequisites remain explicitly BLOCKED and no credential, endpoint, provider identity, or successful live status was fabricated.
- timestamp: 2026-09-13T16:52:00+08:00
  observation: Reverting only the provider/rollout production and config source restored every focused readiness failure plus the connection-publication/parity failures; restoring the source returned the focused provider/package suite to green.
  implication: Revert-and-reconfirm proves the implementation—not environment or test drift—closes the reproduced source/config defects.
- timestamp: 2026-09-13T17:02:00+08:00
  observation: Commit `d09843e87` contains the complete provider/readiness source, tests, Terraform, and runbook changes with the required Copilot co-author trailer. Its 13 paths exclude every owned remediation, Fabric mapper, Exposure CVE/quarantined launcher, and Patch Priorities publication/data file.
  implication: The final source/config cluster is atomically committed within scope; only final whole-branch validation/review and human confirmation remain, not live deployment.
- timestamp: 2026-09-13T13:53:00+08:00
  observation: Independent orchestration review reports three deterministic blockers before provider/config work: invalid `{}` no-hint tool fallback across exact v2 pages, retained browser claims bypassing canonical conflict/completeness admissibility, and a 64-citation preselection cap suppressing synthesis for 65-200 accepted material rows.
  implication: The active session remains in shared orchestration/MAF/evidence-selection scope; focused RED tests must reproduce all three before source changes, and provider/config work remains deferred.
- timestamp: 2026-09-13T14:05:00+08:00
  observation: `build_deterministic_fallback` chooses each selected specialist's first tool with `{}` and raises when no tool-bearing specialist exists. Manifest/tool-schema inspection proves Governance, Identity, and FinOps have no empty-argument-valid tool, while Overview/Copilot/Agents map only to tool-less `executive_summary`; multi-owner pages may also include an invalid Governance step.
  implication: A policy-valid candidate cannot be guaranteed by page mapping alone. The fallback must validate each proposed call, derive only explicit snapshot-backed arguments, omit invalid steps, and support a deterministic no-tool result.
- timestamp: 2026-09-13T14:05:00+08:00
  observation: `execute_turn` passes the original browser snapshot directly to `_current_retained_evidence`; that method admits every material-referenced `ok`/`partial` row in input order and never consults canonical conflict groups or `MaterialClaim.requires_complete_coverage`.
  implication: Browser claims can bypass the fail-closed admissibility used by canonical evidence, so contradictory variants and completeness-dependent partial claims can directly drive synthesis and confidence.
- timestamp: 2026-09-13T14:05:00+08:00
  observation: `_current_retained_evidence` breaks at 64 rows even though `EvidenceSnapshotV2.evidence` and `material_claims` each accept 200 and `OrchestrationResult.citations` accepts 256; `_deterministic_page_claims` then rejects all claims unless every material reference survived.
  implication: At 65-200 material rows, pre-closure input-order truncation can suppress all deterministic synthesis. The retained page-evidence capacity must be bounded to the existing 200-row contract, selected deterministically before closure, with any exclusion/truncation surfaced.
- timestamp: 2026-09-13T14:05:00+08:00
  observation: The defects reproduce from static deterministic branches and no per-test coverage artifact is configured for this focused path.
  implication: Failure class remains Bohrbug; SBFL is skipped with a logged reason and test-first working-backwards reproduction is the appropriate first move.
- timestamp: 2026-09-13T14:09:00+08:00
  observation: Focused RED retained-evidence tests fail exactly as predicted: conflicting totals 7 and 11 both become high-confidence claims, a 1/100 completeness-required total becomes a high-confidence claim, and both 65-row and 200-row snapshots retain only 64 citations.
  implication: Issues 2 and 3 are directly reproduced with specified output oracles; the 64-row pre-closure limit, not snapshot validation or environment drift, causes the cardinality failures.
- timestamp: 2026-09-13T14:13:00+08:00
  observation: The all-page no-hint RED test fails for exactly 10 of 30 PageMapping values—Overview, Compliance, Governance, Identity, FinOps, Remediation, Resource, Services, Copilot, and Agents—and the selected-Identity derivation test also fails with `invalid_arguments: business_service_context`.
  implication: Failure spans tool-less pages, required-argument specialists, and mixed valid/invalid multi-owner sets; validating and selecting each call before CandidatePlan construction plus an explicit no-tool service branch is required.
- timestamp: 2026-09-13T14:19:00+08:00
  observation: After fallback construction validates every call, derives only `subject` or `query` from explicit snapshot context, omits invalid mapped steps, and returns `None` for a no-tool outcome handled by the service, all 31 exact-page/selected-entity focused tests pass.
  implication: Every PageMapping now produces either policy-valid read-only calls or an explicit `no_safe_tool_arguments` result without a ValueError; adjacent and causal guardrails remain.
- timestamp: 2026-09-13T14:25:00+08:00
  observation: Fallback-adjacent orchestration policy/routing/parity tests pass, Ruff passes, reverting only the two fallback production files restores the same 11 failures, and reapplying returns 31/31 focused cases to green.
  implication: All applicable fallback fix-acceptance signals pass except mutation testing, which remains unavailable because no configured Python mutation framework exists; the change is ready for an isolated atomic commit.
- timestamp: 2026-09-13T14:29:00+08:00
  observation: The validated deterministic fallback fix and its focused exact-page tests were committed atomically as `401f1bd44` with the required Copilot co-author trailer.
  implication: The remaining uncommitted test changes isolate retained-evidence conflict/completeness/cardinality behavior for the second coherent fix.
- timestamp: 2026-09-13T14:36:00+08:00
  observation: A shared page-context selector now excludes contradictory variants and incomplete completeness-required claims before citation minting, reuses canonical selected/direct/actionable/severity/freshness/quality ranking, and caps at the existing 200-row snapshot contract. All four retained-evidence regression tests pass, including deterministic 65-row and 200-row closure.
  implication: The focused behavior is corrected without raising an unbounded cap; adjacent canonicalization, synthesis, API, and lint validation are now required.
- timestamp: 2026-09-13T14:42:00+08:00
  observation: The full focused synthesis/page-context suite and adjacent canonical API suites pass, and Ruff reports no findings for the shared selector, service integration, and regression tests.
  implication: Canonical normalization, API scope/CAS behavior, and existing synthesis contracts remain intact; causal revert/reconfirm is the remaining acceptance signal for this fix.
- timestamp: 2026-09-13T14:49:00+08:00
  observation: Reverting only `page_context.py` and the uncommitted retained-evidence portion of `orchestration_service.py` restores all four exact failures—two inadmissible claims and the 64-row cap at both 65 and 200 rows—while reapplying returns 4/4 to green.
  implication: Revert-and-reconfirm establishes that shared admission/ranking causes the corrected behavior; mutation testing remains unavailable, and the additive selector does not delete or bypass evidence behavior.
- timestamp: 2026-09-13T14:53:00+08:00
  observation: The retained-evidence admission/ranking fix and its focused conflict, completeness, 65-row, and 200-row tests were committed atomically as `37cd88f6e` with the required Copilot co-author trailer.
  implication: Both coherent root-cause fixes are committed; only combined Phase 11 validation, scope review, and active debug checkpoint documentation remain.
- timestamp: 2026-09-13T15:00:00+08:00
  observation: Combined validation passes all selected tests except two legacy `/investigate-context` tests that still assert Network questions broaden to Governance or Vulnerability. Those expectations directly contradict the already accepted exact page-safe selector contract; Ruff and all 8 offline specialist parity checks pass.
  implication: This is stale test debt exposed by the broader run, not a regression in the two new fixes. The tests must assert Network-only delegation and no out-of-page agent call.
- timestamp: 2026-09-13T15:04:00+08:00
  observation: The two stale assertions were replaced with Network-only page-safe expectations; all 8 tests in `test_api_copilot_snapshot.py` pass, and the test-only correction was committed as `b9b199ac4` with the required trailer.
  implication: The broader cluster suite can now measure current exact-routing behavior instead of requiring the superseded permissive contract.
- timestamp: 2026-09-13T15:12:00+08:00
  observation: Final combined validation collected 371 selected cluster 1-4/Phase 11 tests and completed with 370 passing and 1 pre-existing skip; full `ruff check src tests` passes and offline specialist parity passes all 8 checks.
  implication: The no-hint, canonical admission, citation closure, scope/CAS, routing, packaging, and parity contracts remain green together; no TypeScript or response-rendering file changed, so web/tsc reruns are not applicable to this correction.
- timestamp: 2026-09-13T15:12:00+08:00
  observation: Commits `401f1bd44`, `37cd88f6e`, and `b9b199ac4` each contain the required Copilot co-author trailer. Their six changed paths are limited to shared MAF/orchestration/page-context code and focused tests; no excluded remediation, Fabric, Exposure CVE, Patch Priorities publication/data, provider, deployment, or infrastructure file changed.
  implication: The orchestration blockers are atomically committed within the authorized ownership boundary, and the active session can return to source/config readiness without archive.
- timestamp: 2026-09-13T12:53:00+08:00
  observation: `.planning/STATE.md` still identifies Phase 4 planning and its unrelated entry gate, while this continuation explicitly authorizes the Phase 11 page-audit exception; the worktree contains only this active debug-file edit on top of the already committed cluster fixes.
  implication: The requested exact-set routing and redirect-contract work remains a safely isolated exception and must not touch Phase 4/provider/deployment scope.
- timestamp: 2026-09-13T12:53:00+08:00
  observation: The configured `gsd-debugger` agent-skills query returned no skills, and no repository-owned `rules/*.md` files exist outside installed dependencies.
  implication: No additional project rule overlay applies; the loaded debugger workflow and repository tests/contracts remain authoritative.
- timestamp: 2026-09-13T12:57:00+08:00
  observation: Git history shows `/vulnerabilities` began redirecting to `/exposure/patch-priorities` in Phase 03.1 commit `d29c24b74`, before Phase 11 commit `629c1023e` added the reviewed disposition described only as consolidation under Exposure; the implementation and query allowlist have remained unchanged.
  implication: Product navigation history favors patch-priority consolidation, while the later disposition appears to have lost target precision rather than intentionally changing navigation.
- timestamp: 2026-09-13T12:57:00+08:00
  observation: Phase 11 summaries explicitly describe `select_specialists_for_turn` as constrained by `page_mappings`, but also identify it as keyword-based deterministic fallback; Plan 11-16 requires exact manifest parity and exact-set equality for contract gates.
  implication: The intended shared fix is an exact page-safe manifest intersection at selection time, not per-question special cases or another routing table.
- timestamp: 2026-09-13T13:03:00+08:00
  observation: `select_specialists_for_turn` scans every catalog keyword and returns globally matched IDs without intersecting `page_specialists[page_kind]`; `build_deterministic_fallback` then drops non-page IDs and, when none survive, adds only the first tool-bearing page owner.
  implication: The same root cause has two deterministic failure modes: direct/legacy callers can over-route outside the page-safe set, while canonical callers can under-route by collapsing an exact multi-owner page mapping to one specialist.
- timestamp: 2026-09-13T13:03:00+08:00
  observation: Existing routing tests explicitly require Network questions to add Change or Governance even though the supplied page map contains only Network, while manifest parity tests validate only global portfolio reachability and a few broad page projections.
  implication: Current tests encode permissive cross-page broadening and do not assert route-specific exact ordered sets for the newly precise page kinds.
- timestamp: 2026-09-13T13:03:00+08:00
  observation: The vulnerability page test already asserts the full implementation pathname and unsafe-query rejection, but `COPILOT_ROUTE_DISPOSITIONS` declares only `/exposure`; Plan 11-16's prose used the broad product destination without changing the earlier Phase 03.1 navigation.
  implication: Redirect remediation should update the authoritative disposition and add cross-contract exact equality, preserving implementation and allowlist behavior.
- timestamp: 2026-09-13T13:10:00+08:00
  observation: The exact manifest projections are currently Services=`[resource_health_observability]`, Twin=`[network]`, Predeploy=`[change]`, and Identity=`[identity_access]`; Services starters are Resource Health-only and Twin starters are Network-only, while the supplied acceptance explicitly requires Services Governance and Twin Resource Health participation.
  implication: Selector filtering alone cannot satisfy the reviewed target; the manifest must explicitly authorize those two co-owners, with routing tests pinning deterministic order.
- timestamp: 2026-09-13T13:10:00+08:00
  observation: Both legacy contextual modes are unsafe: deterministic `_select_context_specialists` anchors page owners then appends any global keyword match, and MAF `select_specialists_for_turn` returns only global keyword matches; the canonical builder filters afterward and may collapse to one owner.
  implication: Page authorization must occur inside the shared selector so every caller receives the same fail-closed ordered set.
- timestamp: 2026-09-13T13:10:00+08:00
  observation: The release artifact's deterministic fields cover scope, mutation, unknown IDs, route/manifest/tool parity, schema, and citations, but contain no page-safe routing measurement; metric gates also treat `None` as pass until later generic completeness checks and do not identify page safety.
  implication: A dedicated deterministic page-safety field/gate is required so missing measurements produce a whole-build HOLD rather than an optional-mode pass.
- timestamp: 2026-09-13T13:14:00+08:00
  observation: The focused RED run failed seven routing/evaluation assertions: Network broadened to Change/Governance, an unknown page routed to Vulnerability, Services routed only to Vulnerability, Services lacked Governance in the manifest, and the new page-safety threshold had no result-field mapping. The redirect RED test independently observed `/exposure` versus `/exposure/patch-priorities`.
  implication: The tests reproduce the reported broadening, manifest under-specification, missing fail-closed measurement, and exact redirect mismatch without touching production code.
- timestamp: 2026-09-13T13:22:00+08:00
  observation: After the routing implementation, 139 focused routing, policy, manifest parity, and evaluation tests pass. Services resolves exactly to Resource Health then Governance, Twin to Network then Resource Health, Predeploy to Change, Identity to Identity & Access, and all mapped no-hint page kinds preserve their ordered manifest set.
  implication: Moving page authorization inside the shared selector and adding manifest-owned co-owner/priority metadata removes both broadening and canonical under-routing in the focused reproductions.
- timestamp: 2026-09-13T13:22:00+08:00
  observation: The new deterministic `page_safe_specialist_routing` gate carries a controlled per-case Boolean, applies to every integrated case, and the focused missing-measurement test now produces a false gate and whole-build HOLD.
  implication: Missing page-safety evidence can no longer be interpreted as a passing zero-violation measurement.
- timestamp: 2026-09-13T13:28:00+08:00
  observation: Adjacent verification passes all selected canonical/legacy API, routing, policy, manifest packaging/parity, and release-evaluation tests; 110 web adapter/integration tests preserve Predeploy, Services, Identity, and Twin healthy-empty versus unavailable semantics; Ruff and all eight offline specialist parity checks pass.
  implication: The routing fix preserves prior endpoint/security/adapter contracts and updates the versioned manifest consistently across runtime, API, Terraform, package, and model projections.
- timestamp: 2026-09-13T13:34:00+08:00
  observation: Reverting only the routing production/config files restored six focused failures, including global Network broadening, Services→Vulnerability, missing co-owners, and a PROMOTE decision with absent page-safety evidence; reapplying returned all seven focused tests to green.
  implication: Revert-and-reconfirm proves the routing/manifest/evaluation patch, not fixture or environment drift, removes the reproduced failures.
- timestamp: 2026-09-13T13:34:00+08:00
  observation: No Stryker, mutmut, or cosmic-ray configuration is present. Diff review shows root-cause-directed intersection/manifest/evaluation additions plus replacement of the duplicate legacy selector; excluded page/provider/deployment/Fabric/Exposure publication files are untouched.
  implication: Mutation checking is unavailable and explicitly skipped; target, adjacent, no-op/deletion, offline parity, and revert/reconfirm guardrail signals pass.
- timestamp: 2026-09-13T13:37:00+08:00
  observation: The accepted routing/evaluation change was committed atomically as `fe8599f17` with the required Copilot co-author trailer.
  implication: Redirect alignment can proceed as an independent one-line declaration fix and focused test commit.
- timestamp: 2026-09-13T13:41:00+08:00
  observation: The exact redirect test failed before the fix because runtime produced `/exposure/patch-priorities` while the disposition declared `/exposure`; after changing only the declaration and replacing the prefix assertion with exact equality, 122 focused/adjacent web tests and strict TypeScript pass.
  implication: Current navigation and query allowlisting remain unchanged while implementation, authoritative disposition, and tests now agree exactly.
- timestamp: 2026-09-13T13:44:00+08:00
  observation: Reverting only `COPILOT_ROUTE_DISPOSITIONS` restored both exact redirect failures; reapplying it returned both tests green. The diff is one declaration change plus stronger tests, and no mutation framework is configured.
  implication: All applicable redirect guardrail signals pass, including revert-and-reconfirm, with no behavior deletion or unsafe query propagation.
- timestamp: 2026-09-13T13:47:00+08:00
  observation: Redirect alignment was committed independently as `5cf201a5a`; both new commits contain the required Copilot co-author trailer, and neither commit includes an excluded remediation, Fabric, Exposure CVE, Patch Priorities publication/data, provider, deployment, or infrastructure file.
  implication: The requested routing and redirect scope is complete and atomic, while the debug session remains active for provider/config readiness.
- timestamp: 2026-09-13T13:49:00+08:00
  observation: A focused Predeploy regression now proves authorized 0/0 assessment state is complete and fresh while unavailable 0/0 state is incomplete and explicitly unavailable; it passes with strict TypeScript and was committed as `069c01bdf`.
  implication: Exact-set routing did not collapse the required healthy-empty versus unavailable semantics.
- timestamp: 2026-09-13T13:52:00+08:00
  observation: Final post-commit verification passes the complete selected Python routing/policy/parity/packaging/API/evaluation suite, 122 web redirect/manifest/integration/adapter tests, Ruff, strict TypeScript, and all eight offline specialist parity checks.
  implication: The committed routing and redirect fixes remain green together and preserve the adjacent cluster 1-3 contracts; only the intentionally deferred provider/config readiness cluster remains open.
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
6. Runtime rollout/provider configuration has three source omissions: Terraform lacks a
   complete sourceable non-secret provider environment, request boundaries ignore the staged
   rollout controls, and candidate/live parity omits exact governed project-connection
   identities. Remaining live provider parity additionally requires external onboarding
   evidence that must not be fabricated.
7. Deterministic fallback construction did not validate required tool arguments or represent
   a no-tool result, while retained browser evidence bypassed canonical conflict/completeness
   admission and stopped at 64 rows before the strict 200-row snapshot closure boundary.

## Resolution

review_blockers_root_cause: "Six final-review regressions remained: stale CAS was outside locked authorization and mutated continuity before rejection; integrated evaluator fixtures used legacy/question-only endpoints and only six kinds were schema-gated; explicit reviewed cross-domain grants and four gold expected sets were removed; fallback appended every page owner after question-first selection; adapter row/byte trimming did not downgrade coverage or report bounded omissions and measured only the smaller legacy shape; browser conflict grouping serialized raw ARM/domain entity text instead of canonical identity."
review_blockers_fix: "Moved expected-revision validation into locked thread authorization before mutation; routed every integrated fixture through strict v2 `/copilot/investigations` with exact page kind and universal schema gating; restored explicit reviewed cross-domain grants, policy/page-safety recognition, legacy alias compatibility, and the four original multi-specialist gold sets; built fallback calls from selected IDs with one page-safe fallback only when none is valid; added strict-v2 retention fitting, exact bounded omission metadata, conservative completeness, and uncertainty; and reused one canonical entity-key helper for canonicalization and browser conflict exclusion."
root_cause: "Cluster 1: v1/v2 schema drift plus an inventory-only canonical boundary bypassed the shared v2 canonicalizer. Cluster 2: integrated drawers selected legacy endpoints and omitted the retained thread revision, while the service reconciled conflicts instead of honoring caller CAS. Cluster 3: v2 dropped normalized page filters/query and retained turns had no immutable page/entity/scope/generation selection identity; the no-Foundry path emitted no direct citation-closed page claims and the KB adapter dropped provided product/target facts. Independent-review correction: the compatibility seam still copied broad v1 page kinds and fabricated coverage from evidence cardinality; the drawer rendered canonical synthesis beside duplicate tool cards and retained stale CAS continuity after 409. Cluster 4: both legacy and MAF selectors admitted global keyword matches before page authorization, canonical filtering happened too late, the manifest omitted reviewed Services/Twin co-owners/order, and release evidence had no fail-closed page-safety measurement. Cluster 5: the Phase 11 route disposition retained `/exposure` after Phase 03.1 intentionally moved the legacy alias to `/exposure/patch-priorities`. Blocking orchestration review: fallback construction treated page grants as proof that `{}` was valid and had no no-tool outcome; retained browser rows bypassed canonical conflict/completeness admission; and input-order retention stopped at 64 before closure despite the 200-row snapshot contract. Provider/deployment readiness: Terraform did not expose the complete deterministic non-secret provider environment, request boundaries ignored `AIOPS_COPILOT_ROLLOUT_MODE` and canary percentage, and candidate/live parity discarded exact Foundry project-connection identities; live readiness additionally lacks external evidence for two distinct governed connections and immutable provider versions."
fix: "Clusters 1-5 plus independent-review corrections complete: added strict shared TypeScript v2 normalization and canonical-only drawer/CAS behavior; added normalized filter/query plus content-derived generation identity, exact retained-evidence selection, deterministic cited fallback, and KB fact retention; maps every integrated page ID/route to its exact manifest v2 kind and typed coverage; renders citation-adjacent synthesis without duplicate tool cards; clears stale 409 continuity; intersects intent inside the shared selector with an ordered manifest page-safe set, adds Services Governance and Twin Resource Health ownership with manifest-declared primary ordering, makes missing page-safety release evidence a deterministic HOLD, and aligns the `/vulnerabilities` disposition exactly to the established `/exposure/patch-priorities` implementation while preserving its query allowlist. The blocking review fix validates every fallback call, supports a deterministic no-tool result, and applies shared conflict/completeness/ranking rules through the 200-row closure boundary. Provider readiness now exports one allowlisted non-secret Terraform environment through an atomic mode-0600 source file, consumes compatibility/shadow/canary/default controls at every request boundary with stable fail-closed canary selection and deterministic rollback, publishes candidates only with two distinct full project-connection resource IDs, validates those IDs against the live governed connection inventory and every pinned agent definition, and documents exact external evidence while leaving `demo`-only onboarding BLOCKED."
verification:
  review_round_2:
    target_test:
      result: pass
      details: "10 focused Python cases and 7 focused web boundary cases pass after starting RED across all six review findings."
    mutation_check:
      result: skipped
      reason_if_skipped: "No Stryker, mutmut, or cosmic-ray configuration exists."
      mutant_killed: false
    no_op_deletion:
      result: pass
      deletion_justified_by_rca: true
      details: "Diff adds or tightens atomic validation, exact dispatch/grants, canonical identity, and retention truthfulness; no production behavior is deleted or bypassed."
    adjacent_tests:
      result: pass
      suites_run:
        - "Complete selected Phase 11 backend Copilot/orchestration/thread/provider/specialist suite: pass with one pre-existing packaging skip"
        - "All six Copilot web test files: 169 passed"
        - "Full Ruff across src, tests, and evaluate_agents.py"
        - "Strict TypeScript tsc --noEmit"
        - "Python evaluator bytecode compilation and corpus JSON parse"
        - "Offline specialist parity: 9/9 checks passed"
    revert_and_reconfirm:
      result: pass
      bug_returned_on_revert: true
      fixed_on_reapply: true
    guardrail_verdict: accepted
  target_test:
    result: pass
    details: "Provider/readiness RED suite failed all 22 initial cases; final focused provider/package suite passes missing, malformed, complete, rollout-boundary, connection-identity, exact-FQDN, bearer-secrecy, and BLOCKED cases with one pre-existing wheel-build skip."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker, mutmut, or cosmic-ray configuration exists."
    mutant_killed: false
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    details: "Provider readiness is additive authority/validation/routing logic; it does not delete provider behavior, weaken grants, bypass gates, or silently enable candidates. Earlier fallback/evidence changes remain root-cause-directed."
  adjacent_tests:
    result: pass
    suites_run:
      - "281 Python canonical snapshot/API/evaluation/policy/parity/thread tests"
      - "130 web drawer and page-adapter tests"
      - "Two adjacent web runs (47 and 33 passing assertions, with manifest/continuity overlap) covering integration, Inventory, Investigate, and drawer-button behavior"
      - "Ruff on src and tests"
      - "TypeScript `tsc --noEmit`"
      - "Offline specialist parity: 8/8 checks passed"
      - "122 focused/adjacent redirect, manifest, route-disposition, and page-adapter web tests"
      - "371 selected cluster 1-4/Phase 11 Python tests: 370 passed, 1 pre-existing skip"
      - "Full Ruff check across src and tests"
      - "Offline specialist parity: 8/8 checks passed"
      - "Complete provider/orchestration adjacency: readiness, packaging, canonical/legacy APIs, context routing, manifest/policy parity, Foundry, and Operations MCP"
      - "Scoped Ruff across src, tests, and both changed scripts"
      - "Shell syntax for create-foundry-agent.sh and validate-runtime-e2e.sh"
      - "Terraform fmt -check"
      - "Offline specialist parity: 9/9 checks passed, including runtime rollout consumption and provider environment"
      - "Empty-env live parity: BLOCKED, exit 3, no network"
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
  guardrail_verdict: accepted
  terraform_validate:
    result: blocked
    details: "Local `.terraform` cache lacks the locked azurerm, azapi, Fabric, and random provider packages; validation was not initialized because provider/network contact is forbidden."
external_blockers:
  status: BLOCKED
  required_evidence:
    - "Full immutable Foundry project-connection resource ID and read-only payload for `operations-mcp`, matching the exported exact endpoint and audience."
    - "Full distinct immutable Foundry project-connection resource ID and read-only payload for `azure-mcp`, matching the exported exact endpoint and audience."
    - "Script-created candidate artifact containing all twelve exact specialist identities, shared coordinator identity, service-returned provider-version IDs, and both exact connection IDs."
    - "Read-only live parity result proving both connections exist and every pinned definition has exact connection/grant/model parity."
    - "Immutable deployed revision evidence plus compatibility→shadow→canary observation and one real corpus artifact recording PROMOTE/HOLD."
commits:
  - "ff05206e4 docs(debug): record six review remediations"
  - "6c82cf4e0 fix(web): report Copilot evidence truncation"
  - "ed3751d79 fix(copilot): close orchestration review blockers"
  - "ae34e35ae fix(copilot): reject stale thread CAS before mutation"
  - "d09843e87 fix(copilot): wire provider rollout readiness"
  - "b9b199ac4 test(copilot): align legacy page-safe routing"
  - "37cd88f6e fix(copilot): admit retained evidence consistently"
  - "401f1bd44 fix(copilot): validate deterministic fallback calls"
  - "069c01bdf test(copilot): pin predeploy empty-state semantics"
  - "5cf201a5a fix(web): align vulnerability redirect contract"
  - "fe8599f17 fix(copilot): constrain specialists to page-safe sets"
  - "8143a0207 fix(copilot): bind retained evidence to page context"
  - "ec491f753 fix(copilot): close canonical migration review gaps"
files_changed:
  - docs/PRODUCTION_RUNTIME_ACTIVATION.md
  - docs/runbooks/copilot-orchestration-rollout.md
  - infra/README.md
  - infra/scripts/create-foundry-agent.sh
  - infra/terraform/foundry.tf
  - infra/terraform/outputs.tf
  - scripts/export_copilot_provider_env.py
  - scripts/evaluate_agents.py
  - scripts/validate_specialist_parity.py
  - src/api/routers/copilot.py
  - src/api/routers/multi_agent.py
  - src/operations/maf_orchestrator.py
  - src/operations/autonomous_investigation.py
  - src/operations/orchestration_contract.py
  - src/operations/orchestration_service.py
  - src/operations/page_context.py
  - src/operations/specialist_manifest.py
  - src/operations/specialists.v1.json
  - tests/fixtures/copilot_evaluation_cases.v1.json
  - tests/fixtures/copilot_release_thresholds.v1.json
  - tests/test_context_specialist_routing.py
  - tests/test_copilot_evaluation_v2.py
  - tests/test_orchestration_policy.py
  - tests/test_investigation_thread_store.py
  - tests/test_api_copilot_snapshot.py
  - tests/test_api_copilot_snapshot.py
  - tests/test_orchestration_parity.py
  - tests/test_copilot_provider_readiness.py
  - tests/test_specialist_manifest_packaging.py
  - web/src/app/vulnerabilities/page.test.tsx
  - web/src/components/ui/CopilotDrawer.test.tsx
  - web/src/components/ui/CopilotDrawer.tsx
  - web/src/lib/copilot/thread-context.tsx
  - web/src/lib/copilot/page-adapters.test.ts
  - web/src/lib/copilot/page-adapters.ts
  - web/src/lib/types.ts
oracle_type: specified
