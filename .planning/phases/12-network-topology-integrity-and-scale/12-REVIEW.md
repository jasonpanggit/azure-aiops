---
phase: 12-network-topology-integrity-and-scale
reviewed: 2026-09-06T06:13:43Z
depth: deep
diff_base: d57f6137d747c344c56028d7e6211811927d0b43
diff_head: 76b31dd3b6c401bd9f23684bf983c7d395b7a68a
files_reviewed: 49
files_reviewed_list:
  - src/api/providers.py
  - src/api/routers/network.py
  - src/api/runtime.py
  - src/network/design.py
  - src/network/gaps.py
  - src/network/loader.py
  - src/network/models.py
  - src/network/rule_engine.py
  - src/network/service.py
  - src/network/tightening.py
  - src/network/topology.py
  - src/onboarding/graph_normalize.py
  - src/operations/tools.py
  - src/storage/onelake_documents.py
  - tests/network_baseline.py
  - tests/network_scale_fixtures.py
  - tests/test_api_network.py
  - tests/test_api_providers.py
  - tests/test_api_runtime.py
  - tests/test_network_analysis.py
  - tests/test_network_downstream_contracts.py
  - tests/test_network_downstream_scope.py
  - tests/test_network_prephase_baseline.py
  - tests/test_network_scale.py
  - tests/test_network_topology.py
  - tests/test_network_topology_links_regression.py
  - tests/test_onelake_documents.py
  - tests/test_operations_tools.py
  - web/public/azure-icons/README.md
  - web/public/azure-icons/ai-services.svg
  - web/src/app/globals.css
  - web/src/app/network/page.test.tsx
  - web/src/app/network/page.tsx
  - web/src/components/network/TopologyDetailDrawer.test.tsx
  - web/src/components/network/TopologyDetailDrawer.tsx
  - web/src/components/network/TopologyGraph.test.tsx
  - web/src/components/network/TopologyGraph.tsx
  - web/src/components/network/TopologyWorkspace.test.tsx
  - web/src/components/network/TopologyWorkspace.tsx
  - web/src/components/ui/EvidenceBar.test.tsx
  - web/src/components/ui/EvidenceBar.tsx
  - web/src/components/ui/StatusBadge.test.tsx
  - web/src/hooks/useApi.test.ts
  - web/src/hooks/useApi.ts
  - web/src/lib/network-graph.test.ts
  - web/src/lib/network-graph.ts
  - web/src/lib/services.ts
  - web/src/lib/types.ts
  - web/src/test/network-fixtures.ts
findings:
  critical: 5
  warning: 3
  info: 0
  total: 8
status: resolved
resolution:
  fixed: 8
  skipped: 0
  verification: automated_passed_human_logic_review_recommended
---

# Phase 12: Final Independent Deep Code Review

**Reviewed:** 2026-09-06T06:13:43Z
**Depth:** deep
**Diff:** `d57f6137d747c344c56028d7e6211811927d0b43..76b31dd3b6c401bd9f23684bf983c7d395b7a68a`
**Files Reviewed:** 49
**Status:** resolved

## Summary

At review time, the Phase 12 implementation was **not clean after the two fix
iterations**. The focused committed suites passed, and most original findings
were closed, but independent probes found five remaining correctness blockers
and three warnings. Iteration 3 has now resolved all eight. The original probes
found:

- summary budgeting still disagrees with the browser about the synthetic
  `subscription:unknown` group and can render 1,501 Cytoscape node elements
  under a 1,500-element limit;
- the newly wired production flow-observation path does not understand the
  persisted ontology relationship shape and, on a partially adapted row, does
  not recognize `object_id`;
- two policy failure modes still defeat the documented last-good-provider
  behavior;
- the drawer can call an in-scope target “outside the collected scope” merely
  because summary truncation withheld its node.

The OneLake remote ETag precondition, local inter-process lock plus atomic
replace, export filename sequencing/audit timestamp separation, legacy
shared-service casefolding, scoped flow filtering, top-level edge truncation,
and the incomplete-results live region were independently traced and found
present.

## Iteration 3 Resolution Status

All five blockers and three warnings were fixed and regression-covered on
2026-09-06. Identity budgeting, persisted ontology normalization, governed
policy retention, provider lifecycle, scope/truncation semantics, and timestamp
handling remain marked as requiring human logic verification even though all
automated gates pass.

| Finding | Status | Resolution evidence |
|---|---|---|
| CR-01 | Fixed — human verification recommended | `1624765e`, `2f0359fa`; resource nodes with no subscription now reserve the browser's single `subscription:unknown` compound node, keeping the rendered resource-plus-group total at or below 1,500 with authoritative group coverage and a browser regression. |
| CR-02 | Fixed — human verification recommended | `495cb79a`, `48a42db8`; persisted mapper rows decode `payload_json.attributes`, canonical `subject_id`/`object_id` are preserved, the analyzer accepts `object_id`, and route confidence/basis follows analyzed flow provenance with a full mapper integration regression. |
| CR-03 | Fixed — human verification recommended | `e9113df0`; strict policy reads reject malformed string/list bodies and present documents missing `policy`, retaining the governed provider as degraded while still allowing a genuinely absent revision-zero document. |
| CR-04 | Fixed — human verification recommended | `18e0fa74`; a failed refresh against a known newer cache key explicitly marks the retained provider stale/degraded, serves it, and respects retry backoff instead of retrying twice in one request. |
| CR-05 | Fixed — human verification recommended | `f0b25410`; private-endpoint copy uses only authoritative server scope facts for exclusion and identifies an absent summary target as potentially withheld. |
| WR-01 | Fixed — human verification recommended | `f6c7c196`; live ARG timestamps use the loader's aware-UTC parser, invalid/naive values remain unknown, and valid offsets normalize to UTC. |
| WR-02 | Fixed | `09b1ba08`, `f67d55f1`; missing-zone diagnostics retain count/reason only and the regression proves no subscription path or full ARM identifier reaches logs. |
| WR-03 | Fixed | `afb333c3`, `5d8916bd`; asynchronous drill-down, policy-save, and policy-form critical errors are mounted as live alerts with accessibility regressions. |

## Structural Findings (fallow)

No structural pre-pass was supplied.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01 [BLOCKER] [RESOLVED]: Server and browser disagree on the unknown-subscription group, allowing 1,501 canvas elements under the 1,500 cap

**File:** `src/network/topology.py:81-127,524-584`
**Also affected:** `web/src/lib/network-graph.ts:211-217,517-525`;
`tests/test_network_scale.py:78-91`

**Issue:** The browser assigns every resource with an empty
`subscription_id` to the compound parent `subscription:unknown`.
`_summary_canvas_identity()` instead omits a group when neither the explicit
subscription field nor a parseable ARM subscription segment exists. Its test
helper repeats the server behavior rather than the browser behavior.

An executed 1,500-resource probe using valid model objects with non-ARM IDs and
empty subscription metadata returned all 1,500 resources, reported zero
groups, set top-level `coverage.truncated` to `false`, and would make the
browser instantiate 1,501 Cytoscape node elements (1,500 resources plus
`subscription:unknown`). This breaks both exact client/server identity and the
hard canvas bound.

**Fix:** Share or exactly duplicate the browser grouping rule on the server:
resource nodes with no subscription must contribute
`subscription:unknown`; unresolved nodes should retain their current
conditional grouping behavior. Update the scale helper and add a 1,500-node
missing-subscription regression that compares `resources + groups` with the
actual browser graph.

### CR-02 [BLOCKER] [RESOLVED]: Production Traffic Analytics observations are not consumed, and canonical `object_id` observations are mis-attributed

**File:** `src/api/runtime.py:638-665,1928-1937,2881-2893`
**Also affected:** `src/fabric/dataset_mapper.py:884-908`;
`src/network/tightening.py:695-707`; `src/api/routers/network.py:344-367`

**Issue:** `_load_ontology_rows()` supplies rows produced by
`InventoryDatasetMapper._relationship_row()`. Those rows expose
`subject_id`, `object_id`, and `payload_json`; they do **not** expose
`attributes` at the top level. `_traffic_analysis_observations()` requires a
top-level `attributes.dataSource`, so it returns `None` for real persisted
Traffic Analytics relationships. The production `analyzed` state therefore
remains unreachable on the managed path.

There is a second schema mismatch: if a caller does provide top-level
`attributes` with the canonical `object_id`, `ObservedTrafficAnalyzer` accepts
only `objectId` or `object`. It marks live data present but records no matched
rule IDs, which can falsely classify every allow rule as unobserved. The
rule-findings route still stamps fixed medium confidence and claims no flow
logs are ingested even when the service reports analyzed observations.

Executed probe:

```text
extracted_from_mapper_shape = None
has_live = True
matched_rule_ids = set()
```

**Fix:** Normalize ontology relationships once at the runtime boundary:
decode the preserved `payload_json.attributes`, retain canonical
`subject_id`/`object_id`, and pass that canonical shape to the analyzer.
Teach `ObservedTrafficAnalyzer` to read `object_id` as well as legacy
`objectId`/`object`. Derive route confidence and basis copy from
`service.flow_log_provenance`. Add an integration test using the actual
`InventoryDatasetMapper` output, not a hand-written relationship with
top-level attributes.

### CR-03 [BLOCKER] [RESOLVED]: A schema-corrupt policy body is accepted as an empty default and published as healthy

**File:** `src/network/design.py:470-488`
**Also affected:** `src/api/runtime.py:655-665`;
`src/api/providers.py:223-273`

**Issue:** `read_with_revision_or_raise()` is strict only about transport and
JSON-object decoding. If a revisioned document contains a missing or non-object
`policy` member, it silently calls `NetworkDesignPolicy.from_mapping({})`.
The runtime then replaces the last-good governed provider with the default
policy and marks it `ready`.

Executed provider probe:

```text
before: description="governed", state=ready
stored document: {"revision": 8, "policy": "corrupt"}
after: description="", state=ready
```

This reintroduces the exact failure mode the last-good fix was intended to
close, except through schema corruption rather than a transport exception.

**Fix:** In the strict read path, allow an absent document at revision zero,
but reject a present/revisioned document whose `policy` is absent or is not a
mapping. Let that exception reach `ProviderRuntime` so the prior provider
remains published and health becomes degraded. Add malformed-string,
malformed-list, and missing-policy-at-nonzero-revision regressions.

### CR-04 [BLOCKER] [RESOLVED]: A known newer revision plus a body-read outage makes the retained provider unservable

**File:** `src/api/providers.py:301-366`
**Also affected:** `src/network/design.py:505-519`

**Issue:** When the policy revision cache already knows revision 8 but the
strict body read fails, `_refresh_provider()` correctly leaves the revision-7
instance in `_instances` and marks it degraded. `get()` nevertheless rejects
that retained instance because `_cache_keys[name]` is still revision 7 while
the current cache key is revision 8. It retries the failing load twice in one
request and raises `ProviderUnavailableError`.

Executed probe:

```text
initial p7
observed key ('network-policy', 8)
ProviderUnavailableError: The network provider is degraded
loaded=true, state=degraded, retry.attempts=2
```

That contradicts `ProviderRuntime`'s documented guarantee that failed
refreshes continue serving the last completed provider.

**Fix:** Track “last-good but stale relative to known key” explicitly. After a
failed refresh, return the retained instance with degraded/stale policy
metadata rather than requiring key equality; do not relabel the old instance
as revision 8. Also avoid the duplicate immediate retry and add a regression
where the revision cache advances before the body transport fails.

### CR-05 [BLOCKER] [RESOLVED]: Summary truncation is misreported as an authorization exclusion in private-endpoint facts

**File:** `web/src/components/network/TopologyDetailDrawer.tsx:723-742`

**Issue:** `PrivateLinkFacts` declares a target out of scope whenever its ID is
absent from `visibleNodeIds`. At summary detail, an in-scope target can be
absent simply because the 1,500-node/2 MB budget withheld it. The drawer then
asserts “Target resource is outside the collected scope,” turning payload
truncation into a false authorization statement.

**Fix:** Use only explicit server facts (`target_out_of_scope`,
`target_resource_out_of_scope`, or `target_in_scope === false`) for the
out-of-scope claim. If the target is absent from the rendered summary without
an authoritative reason, say that it is not present in this topology response
and may have been withheld, or add a server-provided target-resolution enum.
Cover an in-scope target omitted by summary truncation.

## Warnings

### WR-01 [WARNING] [RESOLVED]: Invalid live observation timestamps are rewritten as “now”

**File:** `src/network/service.py:293-299`

**Issue:** `from_arg_rows()` initializes the normalization timestamp to the
current clock and silently keeps it when `observed_at` is malformed. The later
loader validation therefore sees a newly generated valid timestamp and reports
fresh evidence instead of ignoring the invalid source value. An executed probe
with `observed_at="not-a-date"` produced the current UTC timestamp.

**Fix:** Parse with the same aware-UTC helper used by
`NetworkSnapshotLoader`; preserve unknown/empty freshness when a supplied
timestamp is invalid or timezone-naive. If live query time is intended as a
fallback, pass it as a separate trusted value rather than deriving freshness
from rejected input.

### WR-02 [WARNING] [RESOLVED]: Missing-zone normalization logs full ARM identifiers

**File:** `src/onboarding/graph_normalize.py:764-778`

**Issue:** The new missing-parent diagnostic embeds and logs both `zone_id`
and `vnet_id`. A missing parent commonly means the zone is outside the synced
scope, so this records cross-scope resource identifiers despite the phase rule
that new diagnostics contain counts/predicate names, not ARM IDs.

**Fix:** Log a count and predicate/reason code only, or hash/redact the IDs.
Keep detailed identifiers in a properly authorized diagnostic surface if they
are operationally required.

### WR-03 [WARNING] [RESOLVED]: Several dynamic critical errors are not announced as live alerts

**File:** `web/src/components/network/TopologyDetailDrawer.tsx:689-705`
**Also affected:** `web/src/app/network/page.tsx:1149,1167`

**Issue:** The findings-unavailable callout correctly uses `role="alert"`, but
the asynchronous drill-down error and policy save/form errors are plain
critical `<div>` elements. Keyboard and screen-reader users may not be
notified when these failures appear after an action, despite the UI contract's
live-region requirement.

**Fix:** Add `role="alert"` to newly rendered critical error regions, ensuring
only the active error is mounted at a time. Add assertions that the
drill-down and policy mutation failures are announced.

## Resolved History

The detailed implementation and two fix-series histories remain in
`12-REVIEW-FIX.md`. Independent HEAD verification found the following:

| Prior review area | Final status |
|---|---|
| Original scope leak and semantic-relationship loss | Closed |
| Private-link node projection and Fabric per-capacity gap suppression | Closed |
| Gap/finding pagination and metric totals | Closed |
| Additive summary/full LOD and drill-down scope enforcement | Closed, except CR-01 and CR-05 above |
| Policy refetch and declarative-rule authoring | Closed |
| Casefolded relationship projection and dropped-edge diagnostics | Closed |
| OneLake CAS | Closed: remote ETag preconditions plus create-if-absent; local inter-process lock plus atomic replace |
| Iteration-1 recursive agent bounds and disclosure | Closed |
| Iteration-1 revision-read failure retention | Closed for an unavailable cache-key read; CR-03/CR-04 remain |
| Iteration-2 exact resource/shared-service identity | Closed for resource nodes; unknown subscription compound identity remains open in CR-01 |
| Iteration-2 complete summary byte bound | Closed for the serialized topology object; dense-mesh probe was 1,999,772 bytes |
| Iteration-2 node/group/relationship coverage | Closed for covered fixtures; unknown-subscription group coverage remains open in CR-01 |
| Iteration-2 scoped flow filtering | Closed for canonical in-memory observations |
| Iteration-2 production flow analysis | Not closed; see CR-02 |
| Iteration-2 timestamp normalization | Closed at `NetworkSnapshotLoader`; live ARG fallback remains open in WR-01 |
| Iteration-2 export filenames and audit time | Closed: suffix affects filename only; `exported_at` uses the supplied real instant |
| Iteration-2 legacy shared-service casefolding | Closed |
| Iteration-2 incomplete-results live region | Closed |

## Verification Evidence

Commands were executed against
`76b31dd3b6c401bd9f23684bf983c7d395b7a68a`.

- Focused backend Phase 12 suite: **264 passed**.
- Focused web suite: **7 files, 161 tests passed**.
- TypeScript: **passed** (`npx --no-install tsc --noEmit`).
- ESLint: **passed with zero warnings/errors**.
- Ruff over all changed Python source/tests: **passed**.
- `git diff --check d57f6137..HEAD`: **passed**.
- Dense 40-VNet mesh: topology object **1,999,772 bytes**;
  compact complete API envelope **1,911,510 bytes**; relationship coverage
  remained truncated and top-level truncation remained true.
- Unknown-subscription boundary probe: **1,500 resources + 1 browser group**,
  while server coverage reported **0 groups** and `truncated=false`.
- Persisted-flow-shape probe:
  `_traffic_analysis_observations(...) -> None`; canonical
  `object_id` probe set `_has_live_data=True` but matched **0** rule IDs.
- Malformed-policy probe: governed revision 7 was replaced at revision 8 by
  the empty default policy while provider state remained `ready`.
- Advanced-revision/body-outage probe: retained provider remained present and
  degraded internally, but `get("network")` raised
  `ProviderUnavailableError` after two failed load attempts.
- Invalid-live-timestamp probe: `"not-a-date"` became a current UTC
  `snapshot.observed_at`.

The pre-existing untracked `.gsd/` directory was not modified. No source,
test, `STATE.md`, or `ROADMAP.md` file was changed by this review.

---

_Reviewed: 2026-09-06T06:13:43Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
