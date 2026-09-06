---
phase: 12-network-topology-integrity-and-scale
reviewed: 2026-09-06T07:14:38Z
depth: deep
diff_base: d57f6137d747c344c56028d7e6211811927d0b43
diff_head: 3b4508be8cfa244127bee244d35db8ab6aa90717
verified_source_head: c2020d1f
resolved_at: 2026-09-06T07:23:33Z
resolution_head: 811883f3
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
  critical: 0
  warning: 2
  info: 0
  total: 2
resolved: 2
unresolved: 0
status: clean
---

# Phase 12: Final Independent Certification Review

**Reviewed:** 2026-09-06T07:14:38Z
**Depth:** deep
**Implementation range:** `d57f6137d747c344c56028d7e6211811927d0b43..3b4508be8cfa244127bee244d35db8ab6aa90717`
**Files Reviewed:** 49
**Status:** clean

## Summary

The complete Phase 12 diff and the current `12-REVIEW-FIX.md` history were
reviewed at HEAD `3b4508be8cfa244127bee244d35db8ab6aa90717`.
No source changed after the policy fix at `c2020d1f`; the later commits are
Phase 12 review and validation documentation.

The exact revision-8/string-policy probe now fails closed as required:
`read()`, `preview()`, and `update()` raise
`NetworkDesignPolicyDocumentError`; GET, the preview endpoint, and PATCH each
return `503 provider_unavailable`; both store and API probes record zero
writes. The absent revision-zero case still seeds defaults and writes revision
1, while a valid governed revision 8 preserves its description and
`require_private_dns_zone_link: false` through preview/update and writes
revision 9.

The prior scale, scope, persisted-flow, timestamp, diagnostic-redaction,
withheld-target, alert, provider-retention, and downstream contract tests also
pass. The two independently reproduced robustness defects were resolved by
`653c99c0` and `811883f3`; the focused, full-backend, G-4/downstream, Ruff, and
diff gates are green. This review now certifies the phase as clean.
`12-REVIEW-FIX.md` remains the historical ledger and includes the final
resolution evidence.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01 [RESOLVED]: Concurrent stale-policy reads bypass the provider retry backoff

**File:** `src/api/providers.py:310-349`

**Issue:** `_refresh_changed_cache_key()` computes `retry_pending` before
acquiring `_refresh_lock`, then waits for that lock and only rechecks whether
the cache key became current. If two request threads observe a newer policy
revision while its body is unreadable, both can pass the pre-lock retry check.
The first failed refresh establishes `next_retry_at`; the second queued thread
does not re-read that state after acquiring the lock and immediately performs
another forced load. Because this method is called synchronously from `get()`,
the second request also blocks behind the first provider I/O despite `get()`'s
documented non-blocking request-path contract.

An event-controlled two-thread probe at current HEAD produced two failed loads
after one initial successful load:

```text
initial_plus_failed_loader_attempts=3
concurrent_get_results=[True, True]
retry.attempts=2
retry.next_retry_at=2026-09-06T00:00:04Z
```

Both callers received the last-good provider, but the second unavailable-body
load occurred inside the first retry window. Under concurrent traffic this can
serialize request threads on failing storage and defeat the bounded retry
policy.

**Fix:** Make changed-key refresh acquisition non-blocking on the request
path, and after acquiring `_refresh_lock`, re-read both the cache key and
`state.cache_key_stale`/`state.next_retry_at` under `_state_lock` before
calling `_refresh_provider()`. Add an event-controlled concurrent regression
that starts a second `get()` while the first failing loader is blocked and
asserts one failed load, one retry attempt, and both callers receiving the
same last-good instance.

**Resolution:** Fixed in `653c99c0`. Changed-key refresh ownership is now
acquired without blocking, stale/backoff state is revalidated by the owner,
and a known-stale last-good instance remains servable while that owner performs
the load. The event-controlled two-caller regression proves one failing load,
one retry attempt, and identical retained-provider results.

### WR-02 [RESOLVED]: A malformed persisted revision is misreported as an invalid caller request

**File:** `src/network/design.py:558-573`
**Also affected:** `src/api/routers/network.py:454-460,558-565,592-599`

**Issue:** The centralized persisted-document decoder validates the `policy`
member but converts `revision` with an unguarded `int(...)`. A governed
document such as
`{"revision": "not-an-integer", "policy": {"description": "governed"}}`
therefore raises a plain `ValueError`, not
`NetworkDesignPolicyDocumentError`. The API's generic value-error handling
maps all three management routes to `400 invalid_request`, incorrectly blaming
the caller for corrupt server-side state instead of returning the
`503 provider_unavailable` contract used for other malformed persisted policy
fields.

The current-HEAD probe produced:

```text
read ValueError invalid literal for int() with base 10: 'not-an-integer'
preview ValueError invalid literal for int() with base 10: 'not-an-integer'
update ValueError invalid literal for int() with base 10: 'not-an-integer'
store_writes []
api_statuses [400, 400, 400]
api_codes ['invalid_request', 'invalid_request', 'invalid_request']
api_writes []
```

This remains fail-closed and does not write, but it violates the persisted
corruption error contract and gives operators the wrong remediation signal.

**Fix:** Validate and normalize the revision inside
`_read_policy_document()`. Catch `TypeError`/`ValueError` from conversion and
raise `NetworkDesignPolicyDocumentError` instead; reject negative revisions as
invalid persisted state. Add direct and HTTP regressions proving malformed
revisions produce no writes and map GET, preview, and PATCH to
`503 provider_unavailable`.

**Resolution:** Fixed in `811883f3`. Persisted revision conversion now raises
`NetworkDesignPolicyDocumentError` for non-convertible values and rejects
negative revisions before CAS or writes. Direct store and HTTP regressions
cover string, collection, and negative revisions; all three management routes
return `503 provider_unavailable` with zero writes, while malformed operator
payloads remain `400 invalid_request`. Absent and valid revision paths remain
covered.

## Resolution Verification

- Failing-first WR-01 regression reproduced the blocked duplicate load, then
  passed with one refresh owner and one failed loader attempt.
- Failing-first WR-02 regressions reproduced the raw `ValueError`/HTTP 400
  behavior; **7 direct/API cases passed** after the fix.
- Focused provider/policy/API suite: **118 passed**.
- G-4 scale and downstream contract/scope suite: **37 passed**.
- Full backend: **2,736 passed, 33 skipped**.
- Ruff over `src` and `tests`: passed.
- Python compilation and committed/working-tree diff checks: passed.
- Verification ran in the isolated review-fix worktree.

## Verification Evidence

- Exact corrupt revision-8/string-policy probe:
  - `read`, `preview`, `update`:
    `NetworkDesignPolicyDocumentError`
  - GET, preview endpoint, PATCH:
    `503 provider_unavailable`
  - store writes: `[]`
  - API writes: `[]`
- Absent revision-zero probe: defaults retained, preview does not write,
  update writes revision 1 with two seed rules.
- Valid governed revision-8 probe: governed description and private-DNS
  setting retained, preview does not write, update writes revision 9.
- Focused policy/provider/runtime/downstream backend suite:
  **130 passed**.
- Decisive Phase 12 analysis/scale/topology/storage/tool suite:
  **153 passed**.
- Full backend: **2,728 passed, 33 skipped** (**2,761 collected**).
- Focused Phase 12 web suite: **6 files, 160 tests passed**.
- Full web: **43 files passed; 347 tests passed; 15 todo**.
- TypeScript (`npx --no-install tsc --noEmit`): passed.
- Next.js ESLint (`--max-warnings=0`): passed.
- Ruff over `src` and `tests`: passed.
- Python compilation and `git diff --check d57f6137..HEAD`: passed.
- Security/debug-artifact scan over Phase 12 production paths found no
  actionable secret, dangerous-evaluation, or debug patterns.

---

_Reviewed: 2026-09-06T07:14:38Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
