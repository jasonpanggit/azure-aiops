---
phase: 12-network-topology-integrity-and-scale
reviewed: 2026-09-06T07:06:02Z
depth: deep
diff_base: d57f6137d747c344c56028d7e6211811927d0b43
diff_head: c2020d1f
verified_source_head: c2020d1f
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
  warning: 0
  info: 0
  total: 0
resolved_findings: 1
status: clean
---

# Phase 12: Final Deep Code Review Report

**Reviewed:** 2026-09-06T07:06:02Z
**Depth:** deep
**Implementation range:** `d57f6137d747c344c56028d7e6211811927d0b43..c2020d1f`
**Files Reviewed:** 49
**Status:** clean

## Summary

The final review re-read the complete Phase 12 source diff, the historical
review iterations, and `12-REVIEW-FIX.md`; traced the backend and browser
identity, scope, policy, provider, evidence, and asynchronous-error paths; and
reran the focused backend/web gates.

All specifically requested closure probes pass at current HEAD:

- unknown-subscription resources reserve the browser's one synthetic group,
  so the summary boundary is 1,499 resources plus one group;
- persisted `InventoryDatasetMapper` Traffic Analytics rows decode to
  canonical `subject_id`/`object_id` values and reach analyzed provenance;
- strict provider construction rejects corrupt governed policy bodies and
  keeps the last-good provider degraded;
- a known newer but unreadable revision leaves the stale provider servable
  with one failed refresh attempt and retry backoff;
- a summary-withheld private endpoint target is not called out-of-scope;
- invalid and timezone-naive live timestamps remain unknown;
- missing-zone logs contain only a count/reason code and no ARM identifier;
- drill-down, policy-save, and policy-form asynchronous critical errors use
  `role="alert"`.

The resolved history and commit ledger remain in `12-REVIEW-FIX.md`.

The final policy-management blocker is resolved. Strict policy document
decoding now covers read, preview, and update as well as provider construction;
present malformed bodies return a provider-unavailable response and PATCH
cannot persist generated defaults. Genuinely absent revision-zero documents
still bootstrap defaults.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01 [RESOLVED]: Policy management fails open on a corrupt governed body and can overwrite it with defaults

**File:** `src/network/design.py:464-468,528-566`
**Also affected:** `src/api/routers/network.py:444-453,489-608`

**Issue:** `read_with_revision_or_raise()` now correctly rejects a present
document whose `policy` is missing or not an object. The management methods do
not use that strict path:

- `read()` converts every non-object policy to `{}` and returns a default
  policy;
- `preview()` calls `_merge_changes()`, which falls back through that same
  fail-open `read()`;
- `update()` uses non-strict `_read_document()`, converts a malformed policy to
  `{}`, merges the operator's partial change into defaults, and writes the
  result as the next revision.

The API therefore tells operators that generated defaults are the current
policy while the network provider is serving a different last-good governed
policy in degraded state. Worse, the next ordinary PATCH can permanently
replace the corrupt revision with defaults plus the small requested delta,
discarding all custom governed rules and settings that remain available in
the last-good provider.

An executed current-HEAD probe against
`{"revision": 8, "policy": "corrupt"}` produced:

```text
read_description= ''
preview_rule_count= 2
write_expected_revision= 8
written_revision= 9
written_description= 'operator edit'
written_rule_count= 2
```

This proves the read and preview fabricate the seed policy and a partial
update persists that fabricated state rather than refusing the corrupt base.
It is a policy data-loss and governance-weakening path.

**Fix:** Centralize strict document/schema decoding and use it for every
persisted-policy operation. `update()` and `preview()` must call a strict
read that rejects present documents with a missing/non-mapping `policy`
member before merging; no write may occur after that rejection. The GET route
should either return the actual retained provider policy with explicit
degraded/stale metadata, or return a provider-unavailable/corrupt-policy error
instead of claiming defaults are current. Add regressions for string, list,
and missing-policy documents proving:

```python
with pytest.raises(NetworkDesignPolicyValidationError):
    store.update({"description": "operator edit"})
assert documents.write_calls == []
```

Apply the same fail-closed assertion to `read()`/`preview()` or introduce
explicit strict management variants used by all three API routes. Preserve
the genuinely absent revision-zero bootstrap behavior.

**Resolution:** Fixed by failing-first regression commit `8b502206` and source
commit `c2020d1f`. `NetworkDesignPolicyStore` now decodes every management
operation through one strict body path. String, list, and missing-policy
documents raise `NetworkDesignPolicyDocumentError` (a
`NetworkDesignPolicyValidationError`) before merge or write; the three HTTP
management routes map that persisted-state fault to `503
provider_unavailable`. Valid documents preserve their governed fields and CAS
revision, absent `{}` documents retain revision-zero defaults, and provider
construction continues to retain its last-good instance on corruption.

## Resolved History

`12-REVIEW-FIX.md` remains the authoritative ledger for the earlier review
iterations and fixes, including WR-05, WR-10, WR-11, WR-15, and WR-16. Those
fixes were re-inspected at current HEAD:

- the detail cache is scope-keyed, capped at 64 entries, generation-invalidated
  on topology/scope/detail changes, and ignores stale in-flight completions;
- normalization warnings are surfaced while log diagnostics are
  identifier-free;
- nested topology integrity warnings are typed, deduplicated, rendered, and
  exported;
- policy preview preserves semantic relationships, flow observations, and peer
  resolutions;
- validation counts are reconciled at the current docs-only HEAD.

No previously resolved blocker or warning was reproduced by the focused
regression suites. CR-01 above is a distinct management-path gap exposed by
tracing the final strict-provider fix through all callers.

## Verification Evidence

Commands were run in the assigned Phase 12 checkout. The test/lint runs
verified source head `f67d55f1`; current HEAD `c66a5c5b` adds only the
Phase 12 validation-count documentation update.

- Focused Phase 12 backend suite: **279 passed**.
- Finding-specific backend probes: **9 passed**.
- Focused Phase 12 web suite: **7 files, 165 tests passed**.
- Requested UI probe slice: **3 files, 115 tests passed**.
- TypeScript: **passed** (`npx --no-install tsc --noEmit`).
- Next.js ESLint: **passed with zero warnings/errors**.
- Ruff over all Phase 12 Python source and tests: **passed**.
- `git diff --check d57f6137..HEAD`: **passed**.
- Unknown-subscription regression: **1,499 returned resources + 1 returned
  `subscription:unknown` group = 1,500**, with server group coverage
  `{total: 1, returned: 1, truncated: false}` and matching browser group
  construction.
- Persisted-flow regression uses a real `InventoryDatasetMapper` row and
  verifies canonical lower-cased `object_id`, decoded Traffic Analytics
  attributes, and `flow_log_provenance.state == "analyzed"`.
- Corrupt-provider regressions cover string, list, and missing-policy bodies;
  all retain the governed provider and report degraded health.
- Newer-unreadable revision regression returns the same provider identity,
  reports `cache_key_stale: true`, and records one failed refresh/retry.
- Invalid/naive timestamp, identifier-free diagnostic, withheld-target, and
  live-alert regressions all passed.
- Independent adversarial policy-management probe: **failed the release
  criterion**, demonstrating the default-policy overwrite described in CR-01.

### CR-01 Resolution Verification

Verification ran in the isolated review-fix worktree against `c2020d1f`:

- Exact adversarial probe before the fix reproduced the review output,
  including revision 9 being written from corrupt revision 8.
- The same probe after the fix raised on read, preview, and update and reported
  `write_calls= []`.
- Failing-first regressions: **6 failed, 2 passed** before the implementation.
- Finding-focused policy/provider regressions: **13 passed**.
- Focused policy/provider/API files: **110 passed**.
- G-4 and downstream contracts: **21 passed**.
- Full backend: **2,728 passed, 33 skipped** (**2,761 collected**).
- Ruff over `src` and `tests`: **passed**.
- Python AST checks and `git diff --check c66a5c5b..c2020d1f`: **passed**.

No `STATE.md`, `ROADMAP.md`, `REQUIREMENTS.md`, or `12-VALIDATION.md` file was
modified by this resolution.

---

_Reviewed: 2026-09-06T07:06:02Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
