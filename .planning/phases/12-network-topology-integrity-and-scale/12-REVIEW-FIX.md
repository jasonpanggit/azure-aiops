---
phase: 12-network-topology-integrity-and-scale
fixed_at: 2026-09-06T06:48:10Z
review_path: .planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md
iteration: 3
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 12: Code Review Fix Report

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

## Out-of-Scope Review Findings

The requested fix scope did not include `WR-01`–`WR-08`, `WR-10`–`WR-16`, or `IN-01`–`IN-03`; they were not modified or marked resolved by this report.

---

_Fixed: 2026-09-06T05:16:29Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_

---

# Phase 12: Code Review Fix Report — Iteration 2

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

# Phase 12: Code Review Fix Report — Iteration 3

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
