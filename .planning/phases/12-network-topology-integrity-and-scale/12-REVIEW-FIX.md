---
phase: 12-network-topology-integrity-and-scale
fixed_at: 2026-09-06T07:23:33Z
review_path: .planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md
iteration: consolidated
review_observations: 54
findings_in_scope: 51
fixed: 51
non_actionable: 3
skipped: 0
status: all_fixed
verified_source_head: 811883f3
---

# Phase 12: Consolidated Code Review Fix Report

**Closed at:** 2026-09-06T07:23:33Z
**Source review:** `.planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md`
**Iterations represented:** implementation review, supplemental review, and three independent post-fix verification iterations

**Authoritative summary:**
- Review observations adjudicated: **54**
- Actionable findings in scope: **51**
- Fixed or resolved with commit evidence: **51**
- Adjudicated non-actionable: **3**
- Skipped or open: **0**
- Final status: **all resolved**

Later verification intentionally re-opened some earlier fixes, so these are
observation counts rather than deduplicated defect counts. The historical
iteration sections below retain their point-in-time counts; this frontmatter
and the following ledger are the authoritative final state.

## Consolidated Disposition Ledger

### Implementation review — 10/10 fixed

| ID | Resolution | Commit evidence |
|---|---|---|
| CR-01 | Preserve active scope in drawer requests and cache keys | `543c9be4`, `99c03223` |
| CR-02 | Clear prior-scope `useApi` records on dependency changes | `dadf80ce` |
| CR-03 | Retain populated canvas during refetch | `0bc94e7c` |
| CR-04 | Render private-link-only topologies | `e910226a` |
| CR-05 | Publish the projected full graph size | `dca12bd2` |
| CR-06 | Reset pagination on scope changes | `c71bb46a` |
| CR-07 | Clear selection when scope/detail graph changes | `12d62358` |
| CR-08 | Order, deduplicate, and clean up drill-down requests | `2a0ac8ba`, `43efb950` |
| WR-01 | Settle failed post-policy refresh state | `d44467c8` |
| WR-02 | Exercise retained-canvas behavior through the real workspace | `0bc94e7c` |

### Supplemental review against `eafdf47f` — 22/22 adjudicated

| ID | Resolution | Commit evidence / reason |
|---|---|---|
| CR-01 | Complete summary payload is byte- and canvas-bounded | `9dc901f3`, `c45f75ea`, `949bf4b1`, `93501a4b`, `1624765e`, `2f0359fa` |
| CR-02 | Nested agent payloads use recursive bounds and disclosure | `1944e0fa` |
| CR-03 | Unreadable/corrupt/newer policy state retains the last-good provider | `69b446ac`, `232cd91a`, `e9113df0`, `18e0fa74` |
| WR-01 | Scope-filter flow observations | `ed8895e1` |
| WR-02 | Make analyzed flow provenance reachable with persisted rows | `4c08d698`, `495cb79a`, `48a42db8` |
| WR-03 | Validate and normalize observation timestamps | `578b0c21`, `f6c7c196` |
| WR-04 | Preserve active scope in detail requests | `543c9be4`, `99c03223` |
| WR-05 | Scope, bound, and invalidate the detail cache; clean in-flight entries | `543c9be4`, `2a0ac8ba`, `43efb950`, `30832b47` |
| WR-06 | Serialize drill-down paging and ignore stale completions | `2a0ac8ba`, `43efb950` |
| WR-07 | Settle policy refresh failures with explicit feedback | `d44467c8` |
| WR-08 | Resolve legacy shared-service IDs case-insensitively | `fc79e096` |
| WR-09 | Bind scale tests to production constants | `c14c43dc` |
| WR-10 | Surface bounded, identifier-free normalization diagnostics | `b4e644ef`, `09b1ba08`, `f67d55f1` |
| WR-11 | Type, render, and export server-authored topology warnings | `1f5cd472` |
| WR-12 | Keep audit time real and suffix only colliding filenames | `a85715bb`, `1634f68e` |
| WR-13 | Export authoritative relationship coverage | `949bf4b1`, `93501a4b` |
| WR-14 | Announce incomplete-result callouts | `04203af9`, `86b5bd05`, `7a802531` |
| WR-15 | Preserve flow and peer derivation context in policy preview | `5ed9cd3a` |
| WR-16 | Reconcile validation state with all eleven completed plans | `9dc5d8c9`, `c66a5c5b` |
| IN-01 | No source change | Non-actionable for this phase: pre-existing behavior explicitly retained by UI-SPEC C-10; all Phase 12 canvas signals have DOM-text equivalents, while a full Cytoscape keyboard model is not a surgical fix. |
| IN-02 | No source change | Intentional non-disclosure: the uniform empty response avoids revealing whether an unknown resource exists outside the caller's scope. |
| IN-03 | No source change | Latent only: current private-link candidate types cannot collide with first-class `Microsoft.Network/*` nodes. |

### Independent post-fix verification

- Iteration 2: **11/11 fixed**, commits `211a116e` through `7a802531`
  as itemized in the historical section below.
- Iteration 3: **8/8 fixed**, commits `1624765e`, `2f0359fa`,
  `495cb79a`, `48a42db8`, `e9113df0`, `18e0fa74`, `f0b25410`,
  `f6c7c196`, `09b1ba08`, `f67d55f1`, `afb333c3`, and `5d8916bd`.
- Final policy-management review: **1/1 fixed** by failing-first regression
  `8b502206` and implementation `c2020d1f`.
- Final concurrency/revision review: **2/2 fixed** by atomic test-and-fix
  commits `653c99c0` and `811883f3`.

## Final Verification

Verification ran against the final source in both locations:

- **Isolated review-fix worktree** (removed after integration): the latest
  concurrency/revision backend run passed **2,736 tests, skipped 33**
  (**2,769 collected**); Ruff, Python parsing, and diff checks passed.
- **Assigned Phase 12 checkout**
  `/Users/jasonmba/workspace/copilot-worktrees/azure-aiops/jasonpanggit-potential-broccoli`:
  the full web run passed **43 files / 347 tests**, with **15 pre-existing
  todo**, in 8.71s; TypeScript (`tsc --noEmit`) passed with zero diagnostics;
  Next.js ESLint passed with zero warnings or errors.
- Supplemental WR-05 cache lifecycle: **46 web tests passed across 2 files**.
- Supplemental WR-10 normalization diagnostics: **15 backend tests passed**;
  the identifier-redaction follow-up passed its focused regression.
- Supplemental WR-11 topology warning rendering: **27 web page tests passed**.
- Supplemental WR-15 policy preview parity: **3 focused backend tests passed**.
- Supplemental WR-16 validation reconciliation: all eleven summary statuses,
  Wave-0 artifacts, both manual evidence artifacts, and Markdown diff checks passed.
- Additional per-finding counts for the independent iterations are retained
  in their historical sections below.

---

## Historical Fix Iteration 1 — Supplemental Blockers

**Fixed at:** 2026-09-06T05:16:29Z
**Source review:** `.planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 4
- Fixed: 4
- Skipped: 0

## Fixed Issues

### CR-01: `detail=summary` can return zero nodes and still exceed the byte ceiling

**Files modified:** `src/network/topology.py`, `tests/test_network_scale.py`
**Commit:** `9dc901f3`
**Status:** fixed — requires human verification
**Applied fix:** Budgeted the complete summary payload, including legacy classifications, links, shared services, relationships, unresolved-peer collections, and connection IDs. Resource serialization reserves space for graph relationships, retains a non-zero useful node floor whenever one normal node fits, and reports per-collection coverage. Added a 100-VNet/4,950-link dense-mesh regression that binds directly to the production node and byte constants while retaining the byte-identical default/full contract.

### CR-02: Nested lists were not bounded with the same semantics as disclosure

**Files modified:** `src/operations/tools.py`, `tests/test_operations_tools.py`
**Commit:** `1944e0fa`
**Status:** fixed — requires human verification
**Applied fix:** Made `_bound()` recurse through list elements and dictionaries, matching `_bound_disclosure()`. Disclosure paths are de-duplicated while preserving the largest observed total. Added an end-to-end agent-tool regression proving `affected_resource_ids` returns 25 identifiers and warns that it returned 25 of 300.

### CR-03: Revision read failures discarded the last-known-good provider and read under `_state_lock`

**Files modified:** `src/api/providers.py`, `src/api/runtime.py`, `src/network/design.py`, `src/storage/onelake_documents.py`, `tests/test_api_providers.py`, `tests/test_api_network.py`, `tests/test_onelake_documents.py`
**Commit:** `69b446ac`
**Status:** fixed — requires human verification
**Applied fix:** Added a strict document-read path and a short-lived, write-through policy revision cache so a missing revision and an unreadable revision are distinguishable. Provider cache-key failures now fail open to the published instance, prevent an uncertain refresh from replacing it, and are resolved outside `_state_lock`. Tests cover a simulated OneLake revision failure, retained provider identity/load count, strict corrupt-document reads, and lock ownership at every cache-key callback.

### WR-09: Summary budget test asserted duplicated test literals

**Files modified:** `tests/test_network_scale.py`
**Commit:** `c14c43dc`
**Status:** fixed
**Applied fix:** Replaced the tautological assertions with direct equality checks between G-1/G-2 measured limits and `SUMMARY_SMALL_NODE_CAP`, `SUMMARY_SMALL_BYTE_CEILING`, `SUMMARY_NODE_CAP`, and `SUMMARY_BYTE_CEILING`.

## Verification

### Isolated review-fix worktree

- Post-integration targeted blocker regression suite: **90 passed** in 12.01s.
- Per-finding checks before integration: CR-01/WR-09 scale module **14 passed**; CR-02 Operations tool module **3 passed**; CR-03 affected provider/document/network modules **73 passed**.
- `ruff check src tests`: clean.
- Python AST parse checks for every modified Python file: clean.
- Default/full payload compatibility remained pinned by the existing byte/hash gate in `tests/test_network_scale.py`.

### Main Phase 12 checkout

The final full gates ran after fast-forwarding the atomic fixes and integrating concurrent Phase 12 commits:

- Full backend suite: **2,701 passed, 33 skipped** in 105.70s.
- Full Vitest suite: **43 files passed; 339 tests passed; 15 todo** in 8.90s.
- `ruff check src tests`: clean.
- `tsc --noEmit`: clean.
- `next lint`: clean with no warnings or errors.

The four finding commits were retained unchanged. Integration is recorded by merge commit `58cc3f9a`.

## Supplemental Findings Deferred at Iteration 1

At this point only the blockers and WR-09 were in scope. `WR-01`–`WR-08`,
`WR-10`–`WR-16`, and `IN-01`–`IN-03` were subsequently adjudicated in the
authoritative ledger above.

---

_Fixed: 2026-09-06T05:16:29Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_

---

## Historical Fix Iteration 2

**Fixed at:** 2026-09-06T06:02:30Z
**Source review:** `.planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md`
**Iteration:** 2

**Summary:**
- Findings in scope: 11
- Fixed: 11
- Skipped: 0

Logic, concurrency, identity, and scope fixes are marked **fixed: requires
human verification** because syntax and automated tests cannot alone prove
every distributed or asynchronous execution order.

## Fixed Issues

### CR-01: Exact projected count matches resource-client graph identity

**Status:** Fixed — requires human verification
**Files modified:** `src/network/topology.py`, `tests/test_network_scale.py`
**Commit:** `211a116e`
**Applied fix:** Removed synthetic shared-service IDs that the active resource graph does not render and counted the same case-folded resource and unresolved-peer identity union as the client. The 1,330-node production fixture now reports exactly 1,330 projected full nodes.

### CR-02: Summary canvas is bounded across every node source

**Status:** Fixed — requires human verification
**Files modified:** `src/network/topology.py`, `tests/test_network_scale.py`
**Commit:** `c45f75ea`
**Applied fix:** Applied one 1,500-element canvas budget across de-duplicated resource nodes, unresolved peers introduced by collections or links, client-added peers, and subscription group nodes while retaining the complete serialized byte ceiling.

### CR-03: Coverage discloses node and edge truncation honestly

**Status:** Fixed — requires human verification
**Files modified:** `src/network/topology.py`, `tests/test_network_scale.py`, `web/src/lib/types.ts`, `web/src/components/network/TopologyWorkspace.tsx`, `web/src/components/network/TopologyWorkspace.test.tsx`
**Commits:** `949bf4b1`, `93501a4b`
**Applied fix:** Added authoritative node, group, relationship, and per-collection coverage; made top-level truncation the OR of all truncation states; updated UI badges, footnotes, and JSON exports to consume those totals; and retained shared-service metadata when its provider resource is present.

### CR-04: Policy body failures retain the last-good provider

**Status:** Fixed — requires human verification
**Files modified:** `src/network/design.py`, `src/api/runtime.py`, `tests/test_api_network.py`
**Commit:** `232cd91a`
**Applied fix:** Added one strict policy-and-revision read for provider construction. Managed, Fabric, and hybrid network construction now fail on unreadable policy bodies, allowing `ProviderRuntime` to retain the last-good governed service in `degraded` state rather than publishing a ready default policy.

### CR-05: OneLake policy CAS is atomic across replicas

**Status:** Fixed — requires human verification
**Files modified:** `src/storage/onelake_documents.py`, `tests/test_onelake_documents.py`
**Commit:** `ae8cb456`
**Applied fix:** Remote writes now bind the read ETag to an ADLS `If-Match` upload and use create-if-absent semantics for revision zero. Local writes use an inter-process file lock and atomic temporary-file replacement. Mutation reads no longer fail open, and a storage-boundary race test proves a stale writer is rejected.

### WR-01: Scoped flow provenance no longer leaks estate-wide counts

**Status:** Fixed — requires human verification
**Files modified:** `src/network/service.py`, `tests/test_network_analysis.py`
**Commit:** `ed8895e1`
**Applied fix:** Scoped services now filter flow observations with the same surviving-endpoint rule used for semantic relationships.

### WR-02: Production constructors can reach the analyzed flow state

**Status:** Fixed — requires human verification
**Files modified:** `src/api/runtime.py`, `src/network/service.py`, `tests/test_api_runtime.py`
**Commit:** `4c08d698`
**Applied fix:** Managed and Fabric constructors extract ingested Traffic Analytics relationships as analysis input, and hybrid ARG construction carries the already-scoped managed observations into rule analysis.

### WR-03: Observation timestamps are validated and normalized

**Status:** Fixed — requires human verification
**Files modified:** `src/network/loader.py`, `tests/test_network_topology_links_regression.py`
**Commit:** `578b0c21`
**Applied fix:** Loader timestamps are parsed as timezone-aware instants, compared chronologically, normalized to UTC `Z`, and ignored when malformed or timezone-naive.

### WR-04: Rapid exports retain truthful audit timestamps

**Status:** Fixed
**Files modified:** `web/src/components/network/TopologyGraph.tsx`, `web/src/components/network/TopologyGraph.test.tsx`, `tests/test_network_downstream_contracts.py`
**Commits:** `a85715bb`, `1634f68e`
**Applied fix:** `exported_at` now always equals the supplied real clock value. Same-second collisions add only a filename sequence suffix while preserving the established first-export filename contract.

### WR-05: Legacy shared-service edges are case-insensitive

**Status:** Fixed
**Files modified:** `web/src/lib/network-graph.ts`, `web/src/lib/network-graph.test.ts`
**Commit:** `fc79e096`
**Applied fix:** Registered legacy shared-service nodes in the folded-ID index and resolved mixed-case consumer IDs before creating edges.

### WR-06: Incomplete-results warnings are announced

**Status:** Fixed
**Files modified:** `web/src/app/network/page.tsx`, `web/src/app/network/page.test.tsx`
**Commits:** `04203af9`, `86b5bd05`, `7a802531`
**Applied fix:** Added a named polite status region to the dynamic incomplete-results callout and made existing policy-status tests select their intended live message without ambiguity.

## Verification

Verification ran in both locations:

- **Isolated review-fix worktree:** failing-first backend regressions, the
  240-test targeted backend slice, G-1 through G-6 modules, downstream
  contracts, downstream scope tracer, Ruff, TypeScript syntax checks, and
  committed diff checks.
- **Main Phase 12 checkout after fast-forward:** targeted and full web suites,
  the reproducible full backend suite, TypeScript, ESLint, Ruff, and final diff
  checks.

Exact results:

- Targeted backend regression slice: **240 passed**
- Targeted web regression slice: **129 passed across 4 files**
- G-1/G-2/G-3/G-6 modules: **19 passed**
- G-4/G-5 and downstream contracts: **16 passed**
- Downstream scope tracer: **4 passed**
- Full backend suite: **2,708 passed, 33 skipped**
- Full web suite: **43 files passed; 340 tests passed; 15 todo**
- TypeScript: passed with zero diagnostics
- ESLint: passed with zero warnings or errors
- Ruff: passed
- `git diff --check`: passed

## Skipped Issues

None.

## Unresolved Items

None.

---

_Fixed: 2026-09-06T06:02:30Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 2_

---

## Historical Fix Iteration 3

**Fixed at:** 2026-09-06T06:48:10Z
**Source review:** `.planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md`
**Iteration:** 3

**Summary:**
- Findings in scope: 8
- Fixed: 8
- Skipped: 0

Logic, lifecycle, identity, scope, and timestamp fixes are marked **fixed:
requires human verification** because syntax and automated tests cannot alone
prove every distributed or asynchronous execution order.

## Fixed Issues

### CR-01: Unknown-subscription compound nodes share the canvas budget

**Status:** Fixed — requires human verification
**Files modified:** `src/network/topology.py`, `tests/test_network_scale.py`, `web/src/lib/network-graph.test.ts`
**Commits:** `1624765e`, `2f0359fa`
**Applied fix:** Mirrored the browser's resource grouping rule on the server so every resource without usable subscription metadata contributes the single `subscription:unknown` group. The boundary regression starts from 1,500 such resources and proves the summary returns 1,499 resources plus one group, with correct group and top-level truncation coverage.

### CR-02: Persisted Traffic Analytics relationships reach rule analysis

**Status:** Fixed — requires human verification
**Files modified:** `src/api/runtime.py`, `src/network/tightening.py`, `src/api/routers/network.py`, `tests/test_api_runtime.py`, `tests/test_network_analysis.py`, `tests/test_api_network.py`
**Commits:** `495cb79a`, `48a42db8`
**Applied fix:** Normalized the production mapper shape by decoding `payload_json.attributes` while retaining canonical `subject_id` and `object_id`; taught the analyzer to consume canonical `object_id`; and made route confidence and basis copy reflect analyzed flow provenance. The integration regression runs an actual `InventoryDatasetMapper` output row through provider construction.

### CR-03: Schema-corrupt policy bodies cannot replace governed state

**Status:** Fixed — requires human verification
**Files modified:** `src/network/design.py`, `tests/test_api_network.py`
**Commit:** `e9113df0`
**Applied fix:** Strict policy construction now permits only a genuinely absent revision-zero document to default. Present documents with string/list policy values or no policy member raise validation errors, leaving the governed last-good provider published with degraded health.

### CR-04: A retained provider remains servable after a newer body outage

**Status:** Fixed — requires human verification
**Files modified:** `src/api/providers.py`, `tests/test_api_providers.py`
**Commit:** `18e0fa74`
**Applied fix:** Provider health now records `cache_key_stale` when a known newer key cannot be loaded. `get()` serves that explicitly degraded last-good instance without relabeling its cache key, and changed-key refreshes respect retry backoff so one request does not perform duplicate failing loads.

### CR-05: Summary withholding is distinct from scope exclusion

**Status:** Fixed — requires human verification
**Files modified:** `web/src/components/network/TopologyDetailDrawer.tsx`, `web/src/components/network/TopologyDetailDrawer.test.tsx`
**Commit:** `f0b25410`
**Applied fix:** Private endpoint facts now claim out-of-scope only from explicit server facts. An in-scope target missing from the rendered summary is described as absent from this response and potentially withheld by summary limits.

### WR-01: Invalid live timestamps remain unknown

**Status:** Fixed — requires human verification
**Files modified:** `src/network/service.py`, `tests/test_network_analysis.py`
**Commit:** `f6c7c196`
**Applied fix:** Live ARG construction now uses the loader's aware-UTC timestamp parser and formatter. Invalid and timezone-naive inputs are not replaced by the wall clock, generated normalizer stamps are cleared from evidence, and valid offsets normalize to UTC.

### WR-02: Missing-zone diagnostics contain no ARM identifiers

**Status:** Fixed
**Files modified:** `src/onboarding/graph_normalize.py`, `tests/test_network_topology_links_regression.py`
**Commits:** `09b1ba08`, `f67d55f1`
**Applied fix:** The post-review branch already contained the atomic redaction fix: missing-zone diagnostics retain only a bounded count and reason code. The strengthened regression proves no subscription path and neither the zone nor VNet ARM identifier is logged.

### WR-03: Asynchronous critical UI errors are live alerts

**Status:** Fixed
**Files modified:** `web/src/components/network/TopologyDetailDrawer.tsx`, `web/src/components/network/TopologyDetailDrawer.test.tsx`, `web/src/app/network/page.tsx`, `web/src/app/network/page.test.tsx`
**Commits:** `afb333c3`, `5d8916bd`
**Applied fix:** Drill-down load failures, policy-save failures, and policy-form validation failures now mount as `role="alert"` regions; regressions select the active asynchronous message by its alert semantics.

## Verification

Verification ran in two locations:

- **Isolated review-fix worktree:** all failing-first backend probes, targeted
  backend regressions, G-1 through G-6 and downstream contracts/scope, full
  backend, Ruff, Python parsing, and committed diff checks.
- **Main Phase 12 checkout after fast-forward:** web regressions/full suite,
  TypeScript, ESLint, and final cross-tree diff checks.

Results recorded before worktree cleanup:

- Finding-focused backend regression slice, including G/downstream gates:
  **216 passed**
- G-1 through G-6 and downstream scope/contracts: **37 passed**
- Full backend: **2,753 collected; 2,720 passed, 33 skipped**
- Ruff: passed
- Python AST parsing: passed
- Committed `git diff --check`: passed

- Targeted web regression slice: **3 files, 115 passed**
- Full web: **43 files passed; 347 tests passed; 15 todo**
- TypeScript: passed with zero diagnostics
- ESLint: passed with zero warnings or errors
- Final main-checkout Ruff and diff checks: passed

## Skipped Issues

None.

## Unresolved Items

None.

---

_Fixed: 2026-09-06T06:48:10Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 3_

---

## Final Fix — CR-01 Policy Management Fail-Closed

**Fixed at:** 2026-09-06T07:06:02Z
**Source review:** `.planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md`
**Status:** Fixed — requires human verification

### CR-01: Reject malformed governed policy bodies on every management path

**Files modified:** `src/network/design.py`, `src/api/routers/network.py`,
`tests/test_api_network.py`

**Commits:**

- `8b502206` — failing-first read, preview, update/PATCH no-persist, valid, and
  absent-document regressions.
- `c2020d1f` — centralized strict policy decoding and fail-closed API mapping.

**Applied fix:** Added `NetworkDesignPolicyDocumentError` to distinguish an
invalid persisted body from an invalid operator request. `read()`,
`read_with_revision_or_raise()`, `preview()`, and `update()` now share one
strict decoder. Only the genuinely absent `{}` document produces revision-zero
defaults; present string, list, or missing-policy bodies raise before merge and
before the document store's `write()` can run. GET, preview, and PATCH map the
persisted-state error to `503 provider_unavailable`. Valid policy updates still
merge against the governed body and write with its current revision, preserving
optimistic CAS behavior. Provider construction uses the same decoder, so its
existing degraded last-good behavior remains intact.

### Adversarial Probe

The exact pre-fix probe from the final review reproduced:

```text
read_description= ''
preview_rule_count= 2
write_expected_revision= 8
written_revision= 9
written_description= 'operator edit'
written_rule_count= 2
```

After `c2020d1f`, the equivalent probe produced:

```text
read_error= Network policy document policy must be an object
preview_error= Network policy document policy must be an object
update_error= Network policy document policy must be an object
write_calls= []
```

### Verification

Verification ran in the isolated review-fix worktree
`/Users/jasonmba/workspace/azure-aiops/.github/worktrees/rf-12-78052-1788678016`
using the assigned Phase 12 checkout's Python environment:

- Failing-first regression slice: **6 failed, 2 passed** before implementation,
  proving read, preview, and all three API document shapes remained vulnerable.
- Finding-focused policy/provider regression slice: **13 passed**.
- Focused policy/provider/API suite
  (`test_api_network.py`, `test_api_providers.py`, `test_api_runtime.py`):
  **110 passed**.
- G-4 and downstream contract slice: **21 passed**.
- Full backend: **2,728 passed, 33 skipped** (**2,761 collected**).
- Ruff (`src`, `tests`): **passed**.
- Python AST parsing of all modified Python files: **passed**.
- `git diff --check c66a5c5b..c2020d1f`: **passed**.
- Both source commits contain the required Copilot co-author trailer and were
  created with repository hooks enabled.

No source or test changes were rolled back or skipped. `STATE.md`,
`ROADMAP.md`, `REQUIREMENTS.md`, and `12-VALIDATION.md` were not modified.

---

_Fixed: 2026-09-06T07:06:02Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: final blocker_

---

## Final Warning Fixes — Concurrent Refresh and Persisted Revision

**Fixed at:** 2026-09-06T07:23:33Z
**Source review:** `.planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md`
**Iteration:** final warnings

**Summary:**
- Findings in scope: **2**
- Fixed: **2**
- Skipped: **0**
- Status: **all_fixed**

## Fixed Issues

### WR-01: Concurrent stale-policy reads bypass provider retry backoff

**Status:** Fixed — requires human verification
**Files modified:** `src/api/providers.py`, `tests/test_api_providers.py`
**Commit:** `653c99c0`
**Applied fix:** Changed stale cache-key refresh acquisition to non-blocking,
marked the retained provider stale while the sole owner loads, and revalidated
the cache key plus stale/backoff state under `_state_lock` after ownership was
acquired. An event-controlled two-thread regression proves the concurrent
reader returns the same last-good instance without waiting, only one failing
load runs, and only one retry attempt is recorded.

### WR-02: Malformed persisted revision maps to an invalid caller request

**Status:** Fixed — requires human verification
**Files modified:** `src/network/design.py`, `tests/test_api_network.py`
**Commit:** `811883f3`
**Applied fix:** Normalized persisted revisions in the shared policy decoder,
translated conversion failures to `NetworkDesignPolicyDocumentError`, and
rejected negative revisions before compare-and-swap or persistence. Direct and
HTTP regressions prove malformed string, collection, and negative revisions
perform no writes and map GET, preview, and PATCH to
`503 provider_unavailable`; malformed operator payloads remain
`400 invalid_request`. Existing absent-document, valid revision, and optimistic
CAS paths remain covered.

## Verification

All gates in this iteration ran in the isolated review-fix worktree:

- WR-01 failing-first regression: failed by timing out the queued reader and
  showed two failed loads before implementation; passed afterward with one
  failed load/retry owner and both callers receiving the retained instance.
- WR-02 failing-first slice: **3 failed, 1 passed** before implementation;
  all **7 parametrized direct/API/operator cases passed** afterward.
- Focused provider/policy/API suite
  (`test_api_network.py`, `test_api_providers.py`, `test_api_runtime.py`):
  **118 passed**.
- G-4 scale plus downstream contracts and scope: **37 passed**.
- Full backend: **2,736 passed, 33 skipped** (**2,769 collected**).
- Ruff (`python3 -m ruff check src tests`): passed.
- Python compilation of all modified source/test files: passed.
- `git diff --check 3b4508be..811883f3` and working-tree diff check: passed.
- Both commits contain the required Copilot co-author trailer and were created
  with repository hooks enabled; `--no-verify` was not used.

No fixes were skipped or rolled back. `STATE.md`, `ROADMAP.md`,
`REQUIREMENTS.md`, and `12-VALIDATION.md` were not modified.

---

_Fixed: 2026-09-06T07:23:33Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: final warnings_
