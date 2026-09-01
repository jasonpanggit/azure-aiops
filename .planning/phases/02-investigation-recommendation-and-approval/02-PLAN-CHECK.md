---
phase: 02-investigation-recommendation-and-approval
checked: 2026-09-01
plans_checked:
  - 02-02-PLAN.md
  - 02-03-PLAN.md
  - 02-04-PLAN.md
  - 02-05-PLAN.md
  - 02-06-PLAN.md
  - 02-07-PLAN.md
  - 02-08-PLAN.md
status: issues_found
blockers: 4
warnings: 7
---

# Phase 2 Plan Check

Goal-backward review of plans `02-02` through `02-08` against the phase goal, the
locked decisions in `02-CONTEXT.md`, and the actual codebase. Every structural
claim below was verified against source, not against plan prose.

## Verdict

**ISSUES FOUND — 4 blockers, 7 warnings.**

The plan set is strong on the non-negotiable objective. Business-decision
intelligence is genuinely designed in, not bolted on: the five dispositions are a
hard-constrained vocabulary, cost-of-action and cost-of-inaction are mandatory
sections with explicit unknown markers, no-change is given equal reasoning depth,
and the "technical severity cannot drive priority" rule is enforced by arithmetic
(the 65-point ceiling in the `02-07` weight table) rather than by convention. The
no-execution boundary is defended mechanically. The single highest-value catch in
the set is `02-03`: the governed action catalog is genuinely unwritten in any real
deployment, which would have made the entire pipeline return empty.

The blockers are wiring and gating defects, not conceptual ones. Three are
mechanical; one is a pre-existing red baseline the plans do not account for.

## What Was Verified as Correct

| Claim | Verified |
|---|---|
| `defender_posture`, `security_alerts`, `defender_attack_paths_for_scope`, `secure_score_overview`, `secure_score_controls`, `defender_overview` | Present in `src/intelligence/vulnerability/service.py` |
| `DependencyAnalyzer` field names (`affected_applications`, `service_owners`, `dependency_count`, …) | Exact match, `dependency_analyzer.py:17-27` |
| `PredictiveContextBuilder.canonical_key` is a staticmethod used by `RemediationOpportunityEngine.identify` | Confirmed, `predictive_context_builder.py:91`, `remediation_opportunity_engine.py:30` |
| `_require`, `_filter_scoped`, `_filter_rows`, `Page`, `ReadScope`, `Evidence`, `envelope` | Present/imported in `src/api/routers/operations.py` |
| `_fabric_vulnerability_service`, `_attach_remediation_decisions`, `_fabric_remediation_planner` | Present in `src/api/runtime.py` |
| Catalog tables have a reader and a schema but **no writer** | Confirmed — `remediation_action_catalog` appears only in `schema_registry.py:299`, `sync_service.py:1101`, and docs |
| `merge_posture` closure and sibling merges | `src/fabric/runtime.py:327-367` |
| RiskAnalyzer hardcoded `len(operational_values) == 4` (Pitfall 6) | Confirmed verbatim, `risk_analyzer.py:80` |
| Prioritizer buckets currently sum to 110 before clamp | Confirmed: 35+20+15+15+15+10 = 110, `plan_prioritizer.py:15-23` |
| Defender ontology entity types already registered | `dataset_mapper.py:39-46` |
| Approval-decision publication seam | `sync_service.py:26,71,189-191` |
| `compute_confidence` | `src/ontology/confidence.py:56` |
| MCP seams: `_bound`, `ToolResult`, `ToolSpec`, `_provider_result`, `_tool_cve_*`, `REVIEWED_TOOLS`, `foundry_tool_registry` | All present |
| All 11 phase requirements appear in plan `requirements` frontmatter | DETECT-03/04/05/06/07, RECOMM-01/02/03, APPROVE-01/02/03 |
| Every task has files + action + verify + done (+ behavior); checkpoint task has what-built/how-to-verify | All 20 tasks |
| `npm test` is `vitest run`, not watch mode | `web/package.json:13` |
| Baseline `npx tsc --noEmit` | Exit 0 |
| Wave 3 internal file ownership (`02-03`/`02-04`/`02-05`/`02-06`) | No overlaps |

---

## Blockers

### BL-1 — `02-06` reads a field that `02-04` creates in the same wave

**Dimension:** dependency_correctness

`02-06` declares `depends_on: [02-02]`, `wave: 3`. `02-04` is also `wave: 3`, so
they run in parallel. But `02-06` Task 1's action says verbatim:

> "Extend `PlanRepository.ontology_projection` so that for each plan it reads the
> `evidence_citations` list **added in plan 02-04**"

Verified: `grep -rn "evidence_citations" src/` returns **nothing**. The plan-level
`evidence_citations` list is created by `02-04` Task 3. `02-06` cannot project
Defender relationships from a field that does not exist yet, and its Task 1
Tests 2, 3 and 5 will fail on an empty citation list.

**Fix:** `02-06` `depends_on: [02-02, 02-04]`, `wave: 4`.

### BL-2 — `02-05` returns a business decision that `02-04` builds in the same wave

**Dimension:** dependency_correctness

`02-05` declares `depends_on: [02-02]`, `wave: 3`, parallel with `02-04`. Task 2's
action says verbatim:

> "Add a companion `remediation_business_decision` handler that returns … the
> business decision section **built in plan 02-04**"

`BusinessDecisionEngine` is created by `02-04` Task 1. `02-05`'s own `must_haves`
also assert the specialist can read "their business decisions". Task 1 of `02-05`
is genuinely independent, but Task 2 is not.

**Fix:** `02-05` `depends_on: [02-02, 02-04]`, `wave: 4` — or split Task 1 into a
wave-3 plan and move Tasks 2-3 to wave 4.

### BL-3 — `02-08` Task 1 verifies against a test file that does not exist

**Dimension:** task_completeness / verify format

```
<automated>uv run pytest tests/test_api_operations_endpoints.py -q</automated>
```

Verified: no file matching `test_api_operations_endpoint*` exists in `tests/`.
`pytest` exits 4 (usage error) on a missing path, so this gate fails
unconditionally and tells the executor nothing about the work.

**Fix:** point at a real file — `tests/test_api_http.py` is the neighbouring
route-level suite `02-02` already uses.

### BL-4 — The baseline is red in exactly the file `02-08` must extend, and no plan repairs it

**Dimension:** verify format / scope sanity

`uv run pytest -q` on the current tree: **5 failures**, including two in
`tests/test_api_remediation_approvals.py`:

```
FAILED tests/test_api_remediation_approvals.py::test_operator_records_approval_decision_without_execution
FAILED tests/test_api_remediation_approvals.py::test_remediation_decision_survives_provider_rebuild
E  {"error":{"code":"invalid_request",
    "message":"Approved remediation decision expires_at must be in the future"}}
E  assert 400 == 201
```

Root cause: the fixtures hardcode `"expires_at": "2026-09-01"` (lines 70 and 106).
Today is 2026-09-01. The future-expiry validation added by the `02-01` review fix
(WR-01) now rejects them. This is a time-bomb fixture that expired today, not a
regression from these plans.

Impact on the plan set:
- `02-08` Task 1 verify — `uv run pytest tests/test_api_remediation_approvals.py -q` — cannot pass.
- `02-08` Task 3 verify — same file, plus a bare `uv run pytest -q` which currently fails on 5 tests.
- `02-04` Task 3 also verifies `tests/test_api_remediation_approvals.py`.

An executor hitting a red gate it did not cause will either stall or "fix" it by
weakening the expiry assertion — which would quietly undo a security control that
a prior review deliberately added.

**Fix:** add an explicit repair step (earliest plan that touches the file, i.e.
`02-04` Task 3 or a new `02-08` Task 0) that rewrites both fixtures to a computed
relative future expiry (e.g. `now + 30d`) so they cannot expire again. Replace the
bare `uv run pytest -q` in `02-08` Task 3 with a gate that tolerates the three
remaining known-failing tests (`test_service.py::test_end_to_end_mock_ingestion_tracks_incremental_state`,
`test_situations_tracer.py::test_production_ingestion_retains_failed_arg_status_without_watermark`,
`test_situations_tracer.py::test_normalizer_production_graph_contains_all_six_signal_families`)
or asserts no *new* failures against a recorded baseline.

---

## Warnings

### WN-1 — `02-07` modifies an undeclared file
Task 3's `<files>` includes `src/intelligence/remediation/defender_correlation.py`,
but that path is absent from `02-07`'s `files_modified` frontmatter. No parallel
conflict results (`02-08`, the other wave-4 plan, does not touch it), but the
change manifest is wrong for undo/attribution.

### WN-2 — `02-08` renders `02-07`'s output without depending on it
`02-08` Task 2 Test 8 renders "the priority factor breakdown from plan 02-07".
`02-07` renames and re-weights `priority_factors`, adding `business_impact` and
`defender_exposure`. Both plans are wave 4 with no dependency between them, so
`02-08`'s UI fixtures may be written against the old bucket names. `priority_factors`
does exist today (`plan_prioritizer.py:28`), so this degrades to fixture drift
rather than a hard break — but add `02-07` to `02-08` `depends_on` (wave 5) or
pin the bucket names in both plans.

### WN-3 — Wave-4 plans run test selectors over each other's live edits
`02-07` Task 2 runs `uv run pytest -k "remediation" -q` and `02-08` Task 3 runs
`uv run pytest -q`. Both sweep files the other plan is concurrently editing in the
same wave, which can produce failures unattributable to either plan. Scope the
selectors to owned paths, or serialize the two.

### WN-4 — VALIDATION.md is missing while `nyquist_validation: true`
`.planning/config.json` sets `workflow.nyquist_validation: true`, `02-RESEARCH.md`
has a `## Validation Architecture` section, and phases 06/08/09 all carry a
`NN-VALIDATION.md`. Phase 2 has none.

Substantively the sampling checks pass: every one of the 19 implementation tasks
carries at least one `<automated>` command, `npm test` resolves to `vitest run`
(no watch mode), no delay exceeds 30s except the full-suite call flagged in BL-4,
and there is no window of three consecutive implementation tasks without an
automated gate. This is a missing process artifact, not a missing feedback loop —
but it is a documented convention this phase breaks.

### WN-5 — `02-RESEARCH.md` open questions are not marked resolved
`## Open Questions` at line 566 lacks the `(RESOLVED)` suffix. In substance they
*are* resolved — `02-02` carries an explicit "Planner Decisions On Research Open
Questions" block settling Q1, Q2, Q3, A1, A3 and A4, and each resolution is
traceable to the plan that implements it. Bookkeeping gap only; mark the section.

### WN-6 — Stale working-tree assertions in read_first blocks
The plans instruct executors to preserve in-flight edits in files that are clean,
and are silent about several that are genuinely dirty.

Claimed dirty but **clean**: `ontology-schema.md` (`02-06` Task 2 says "user edits
in both documents" — only `docs/ontology-model.md` is modified);
`web/src/app/remediation/page.tsx` (`02-08` Task 2 says "preserve the unrelated
in-flight edits already present in this file").

Genuinely dirty and touched by these plans: `src/api/runtime.py`, `src/api/models.py`,
`src/fabric/runtime.py`, `src/fabric/sync_service.py`, `src/fabric/dataset_mapper.py`,
`docs/ontology-model.md`, `web/src/lib/types.ts`, `web/src/lib/services.ts`.
`02-02` Task 3 and `02-07` Task 2 do warn correctly; the rest do not. Harmless in
isolation, but it trains executors to discount the warnings that matter.

### WN-7 — Decision-ID mis-citations in `02-08` Task 2
Test 1 cites D-16 (extend the Remediation **specialist** with tools) for a UI
row-ordering behavior — D-10 (inspectable rationale) is the applicable decision.
Test 2 cites D-05 (join to the semantic graph) for "both pros and cons render" —
pros/cons is D-13. The behaviors themselves are correct and in scope; only the
traceability tags are wrong, which weakens the decision-coverage audit trail.

### WN-8 (observation) — DETECT-03 is covered by inheritance, not by this phase
`02-02` and `02-06` both claim DETECT-03. What they actually deliver is Defender
record *grouping* and graph *traversability* — neither is a situation timeline.
The real timeline exists from Phase 1 (`web/src/app/situations/[id]/page.tsx:211`,
"Evidence timeline" over `source_family`/`observed_at`). No Phase 2 plan wires
correlated Defender cases into that timeline; the Defender surface lives only on
the Remediation page. Acceptable if inheritance is the intent — but the coverage
claims should say so rather than implying this phase builds the timeline.

---

## Dimension Summary

| Dimension | Result |
|---|---|
| Requirement coverage | PASS — all 11 requirements mapped; see WN-8 on DETECT-03 framing |
| Task completeness | PASS — 20/20 tasks complete |
| Dependency correctness | **FAIL** — BL-1, BL-2; WN-2 |
| Key links planned | PASS — correlator → runtime → route → UI, and MCP/ontology wiring, are explicit |
| Scope sanity | PASS — 2-4 tasks and 4-9 files per plan; 368k tokens total, `confidence: low` (uncalibrated) |
| Verification derivation | PASS — `must_haves.truths` are user-observable throughout |
| Context compliance | PASS — D-01…D-29 mapped; no deferred idea (Phase 3/4/5 work) appears in any plan |
| Scope reduction | PASS — no "v1", "static for now", "future enhancement" hedges found on any locked decision |
| Architectural tier | PASS — correlation/ranking held server-side; `02-02` Task 3 explicitly forbids browser-side joins |
| Cross-plan data contracts | PASS — canonical signal vocabulary fixed in `02-02` and consumed verbatim by `02-03`/`02-07`; A4 preserves `evidence` element type |
| Nyquist compliance | WARN — WN-4 (artifact missing, sampling substantively met) |
| Research resolution | WARN — WN-5 |
| Verify command format | **FAIL** — BL-3, BL-4 |

## Recommendation

Return to the planner for a bounded revision. All four blockers are local edits —
two frontmatter dependency corrections, one verify path, and one baseline repair
step. No task needs to be rewritten and no architecture needs to change.

The non-negotiable objective — evidence-backed business decision intelligence with
dispositions, pros/cons, cost of action and inaction, uncertainty, and a hard
prohibition on severity-driven priority — is met by these plans as written.
