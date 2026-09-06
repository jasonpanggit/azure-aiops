---
phase: 12-network-topology-integrity-and-scale
verified: 2026-09-06T07:36:27Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
requested_verification_head: 3b4508be8cfa244127bee244d35db8ab6aa90717
verified_at_head: 96e812578de28e9c128854cabb7d7e7ee9123c11
verified_source_head: 811883f3
head_moved_during_verification: true
requirements:
  TOPO-01: satisfied
  TOPO-02: satisfied
  TOPO-03: satisfied
  TOPO-04: satisfied
  TOPO-05: satisfied
gates:
  backend: "2,736 passed / 33 skipped / 2,769 collected / 0 failed"
  web: "347 passed / 15 todo / 43 files / 0 failed"
  ruff: clean
  typescript: clean
  eslint: clean
  g_gates: "G-1..G-6 pass (40 gate tests)"
  a39_360px: pass
warnings:
  - id: W1
    summary: "Verification target moved during verification: 4 commits landed after the requested HEAD 3b4508be, 2 of which changed source."
    impact: "Evidence in the submitted closure record does not describe the shipped tree."
    resolution_required: "Resolved: 96e81257 was accepted as the verified implementation head; later closure commits are documentation-only."
  - id: W2
    summary: "The '52 review observations, zero open' claim was stale at 3b4508be; a later deep review of that exact commit found 2 additional warnings (WR-01, WR-02)."
    impact: "Ledger now reads 54 observations / 51 fixed / 3 non-actionable / 0 open."
    resolution_required: "Resolved: consolidated review ledger records 54 observations / 51 fixed / 3 non-actionable / 0 open."
  - id: W3
    summary: "12-VALIDATION.md is stale relative to HEAD."
    impact: "Records verified_source_head c2020d1f and 2,728 passed / 2,761 collected; actual HEAD source is 811883f3 with 2,736 passed / 2,769 collected."
    resolution_required: "Resolved: 12-VALIDATION.md now records source head 811883f3 and 2,736 / 2,769."
  - id: W4
    summary: "27 pre-existing repo-wide Ruff findings in infra/scripts and scripts."
    impact: "None — zero overlap with the 49 Phase 12 files; documented in deferred-items.md."
    resolution_required: "None for this phase."
---

# Phase 12: Network Topology Integrity and Scale — Verification Report

**Phase Goal:** Deliver a scope-safe, complete, scalable, and diagnosable network topology experience whose nodes, relationships, findings, policy changes, freshness, and evidence coverage remain accurate from inventory ingestion through API, web, agents, MCP, and export.

**Verified:** 2026-09-06T07:36:27Z
**Status:** passed
**Re-verification:** No — initial verification
**Requested target:** `3b4508be` · **Actually verified at:** `96e81257` (see W1)

---

## Verification-Head Resolution

**The verification target moved while this verification was running.** This is
recorded first because it changes what the closure record describes.

At the start of verification HEAD was `3b4508be`, as requested. During the run,
four commits landed from a concurrently-executing review-fix loop:

| Commit | Type | Description |
|---|---|---|
| `653c99c0` | **source** | fix(12): WR-01 serialize stale policy retry ownership |
| `811883f3` | **source** | fix(12): WR-02 classify malformed stored revisions |
| `416dd11a` | docs | docs(12): certify final review warnings resolved |
| `96e81257` | docs | docs(12): record clean code review |

Two of these changed production source (`src/api/providers.py`,
`src/network/design.py`) plus their tests.

**Consequence for the submitted premise:** the claim *"all 52 review
observations adjudicated with zero open"* was **not accurate at `3b4508be`**. A
subsequent deep review of exactly that commit found two previously-undetected
warnings. The ledger now reads **54 observations / 51 fixed / 3 non-actionable /
0 open**.

**Both new findings were WARNING severity and fail-closed** (no data loss, no
scope leak, no write on the corrupt path) and both are now fixed with
regressions that I executed and confirmed at HEAD. The phase goal is achieved —
but at `96e81257`, not at the commit submitted for verification.

`96e81257` is accepted as the verified implementation head. Subsequent phase
closure changes are planning documentation only; the verified source head
remains `811883f3`.

I re-ran every gate after the tree stabilised (5 consecutive clean samples over
2.5 minutes, working tree clean). All evidence below is from `96e81257`, whose
source tree is byte-identical to `811883f3`.

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Scoped topology, gaps, rule findings, agents, and MCP expose no out-of-scope resource or relationship, preserve in-scope semantic edges, and do not fabricate missing-private-endpoint findings through asymmetric filtering | ✓ VERIFIED | `NetworkScope.filter_snapshot` enumerates all **15** snapshot collections incl. the previously-omitted `private_link_resources` (`service.py:66-99`). `scoped()` forwards `semantic_relationships`/`flow_observations` through `_scope_relationships()`, which keeps an edge only when **both** endpoints survive scoping (`service.py:190-201`) — closing the leak without reopening it from the relationship side. Single enforcement point: `_service()` → `scoped()`; `_scoped_topology` is absent from `src/` (asserted by `test_service_has_one_scope_enforcement_path`). 9 tracer tests pass incl. `test_in_scope_private_endpoint_still_protects_its_target` (no false negative) and `test_agent_network_tools_inherit_service_scope_isolation`, `test_digital_twin_router_inherits_service_scope_isolation`, `test_azure_mcp_server_is_only_a_relay_for_network_topology` |
| 2 | Fabric capacities, Azure AI Foundry accounts, and all other in-scope private-link candidates appear exactly once and every open topology finding resolves to a visible or explicitly retrievable resource node | ✓ VERIFIED | `topology.py:1343-1344` maps `microsoft.cognitiveservices/accounts`→`AIFoundryAccount`, `microsoft.fabric/capacities`→`FabricCapacity`. Tests pass: `test_fabric_and_ai_resources_project_with_workload_types_and_details`, `test_private_link_resource_already_projected_as_workload_is_not_duplicated` (exactly-once), `test_missing_private_endpoint_gap_ids_resolve_to_projected_nodes` (every finding resolves), `test_scoped_projection_excludes_out_of_scope_private_link_resources` |
| 3 | Findings expose truthful totals and truncation; summary topology stays within a verified enterprise node/payload budget; detail is loaded on demand without silently changing downstream agent, MCP, or export contracts | ✓ VERIFIED | G-1 (200 nodes / 250 KB), G-2 (1,500 nodes / 2 MB) pass **and** G-2 additionally asserts `coverage.total > cap` and `truncated is True` — a fits-trivially pass is impossible. G-4 asserts byte-identity after removing 9 narrow, plan-attributed additive paths; loader fails closed. Drill-down handler resolves real data from the already-scoped snapshot. G-6 agent-bound disclosure passes. A39 screenshot renders "Showing 100 of 3800 inspection gaps and 100 of 72000 rule findings. Metric totals are complete; the lists below are not." |
| 4 | Enabling, disabling, creating, previewing, or deleting a design-policy rule refreshes derived gaps, findings, metrics, and badges without a reload, while invalid declarative rules fail visibly and are not persisted | ✓ VERIFIED | 38 policy tests pass incl. `test_write_invalidates_cached_derived_analysis`, `test_malformed_declarative_rule_is_rejected_without_persisting`, `test_valid_declarative_rule_previews_then_saves`. `useApi` exposes a debounced `refetch` with `refetchNonce` in the effect deps (`useApi.ts:83`); `page.tsx:134-136` refetches topology/gaps/findings and `981/1006/1039` refetch policy on mutation. **Independently probed:** corrupt policy bodies (string/list/missing) fail closed on read+preview+update with `write_calls == []`; bootstrap and CAS preserved |
| 5 | Relationship drops, normalization gaps, snapshot freshness, DNS/subnet/private-endpoint integrity, and flow-log provenance are observable and covered by regression, integration, and representative scale tests | ✓ VERIFIED | 15 regression tests pass incl. `test_mixed_case_estate_preserves_subnet_containment_edges`, `test_dangling_relationship_is_counted_without_disclosing_endpoint_ids` (ASVS V7 — count only, no ARM ids), `test_snapshot_observation_backfills_unstamped_ontology_rows`, `test_flow_observations_are_forwarded_and_provenance_is_three_state`, `test_loader_ignores_invalid_timestamps_and_compares_normalized_instants`. A39 footnote renders "17 relationships dropped (hosts, resolves_for)", "20 peers not ingested / 10 peers outside current scope", "Snapshot observed 2 hours ago" |

**Score: 5/5 truths verified (0 present-but-behavior-unverified)**

### Requirements Coverage

| Requirement | Plans | Status | Evidence |
|---|---|---|---|
| TOPO-01 | 12-01, 12-03, 12-06, 12-09 | ✓ SATISFIED | SC-1 evidence; single scope seam; agent/twin/MCP inheritance proven |
| TOPO-02 | 12-05, 12-06, 12-09, 12-10, 12-11 | ✓ SATISFIED | SC-2 evidence; Fabric decision implemented in code **and** assets |
| TOPO-03 | 12-02, 12-07, 12-08, 12-09, 12-10, 12-11 | ✓ SATISFIED | SC-3 evidence; G-1..G-6; drawer confirmed-clean contract |
| TOPO-04 | 12-04, 12-08, 12-11 | ✓ SATISFIED | SC-4 evidence; CR-01 + WR-02 fail-closed probes |
| TOPO-05 | 12-03, 12-06, 12-08, 12-09, 12-10, 12-11 | ✓ SATISFIED | SC-5 evidence; 15 link regressions |

> REQUIREMENTS.md still shows `- [ ]` for TOPO-01..05. That is ship-step
> bookkeeping, not a phase gap — the reviewer deliberately did not mutate
> REQUIREMENTS.md.

---

## Closure Evidence Audit

Every claim in the submission was independently re-executed. Nothing below is
quoted from SUMMARY.md.

| Claim submitted | Verdict | Measured at `96e81257` |
|---|---|---|
| 2,728 backend passed / 33 skipped | ✓ **confirmed at `3b4508be`**, superseded at HEAD | `3b4508be`: exactly 2,728 / 33 / 2,761. HEAD: **2,736 / 33 / 2,769** (+8 WR-01/WR-02 regressions), 0 failed |
| 347 web passed / 15 todo | ✓ VERIFIED | 43 files, 347 passed, 15 todo, exit 0 (re-run at HEAD) |
| Ruff clean | ✓ VERIFIED | `ruff check src tests` → "All checks passed!" |
| TypeScript clean | ✓ VERIFIED | `tsc --noEmit` exit 0 |
| ESLint clean | ✓ VERIFIED | "✔ No ESLint warnings or errors" |
| G-1..G-6 within bounds | ✓ VERIFIED | 40 gate tests pass; re-confirmed 49 gate+tracer tests at HEAD |
| G-4 byte compatibility | ✓ VERIFIED | Byte-identity asserted after 9 registered additive paths; `allowed_additive_nodes: []`; removal helper raises on a stale registration (cannot silently pass) |
| A39 360px pass | ✓ VERIFIED | Real 360×1462 Chromium 145 PNG; failed-first run documented (`4fb3d19c` fixed drawer overflow) |
| 52 observations, zero open | ⚠️ **SUPERSEDED** | Now **54 / 51 fixed / 3 non-actionable / 0 open** — see Escalation |

### G-4 byte-compatibility — why the allowance is honest

The gate does **not** wave through arbitrary drift. `allowed_additive_keys`
contains 9 explicit paths, each attributed to the plan that introduced it
(12-03, 12-07, 12-REVIEW-CR-05). `_first_difference()` rejects both **removals**
("missing key") and **unregistered additions** ("unregistered additive key"), so
a downstream consumer reading any pre-phase key is provably unbroken. A
registered path that goes absent raises `BaselineArtifactInvalidError` rather
than passing vacuously.

### Behavioral Spot-Checks (independently executed)

| Behavior | Method | Result | Status |
|---|---|---|---|
| CR-01 corrupt policy fails closed on read/preview/update | Adversarial probe, 3 corrupt shapes | All raise `NetworkDesignPolicyDocumentError`; `write_calls == []` | ✓ PASS |
| CR-01 bootstrap preserved | Absent `{}` document | Defaults at revision 0; first write → revision 1 | ✓ PASS |
| CR-01 governed doc preserved | Valid doc rev 8 | Reads `'governed'`; writes rev 9 with CAS `expected_revision=8` | ✓ PASS |
| WR-02 malformed persisted revision | string / list / negative | All raise `NetworkDesignPolicyDocumentError` (not bare `ValueError`); zero writes | ✓ PASS |
| WR-01 concurrent retry-backoff ownership | `test_concurrent_changed_key_failure_has_one_nonblocking_refresh_owner` | PASSED — event-controlled two-thread regression | ✓ PASS |
| Lock-ordering invariant | `test_cache_key_is_never_resolved_while_state_lock_is_held` | PASSED | ✓ PASS |
| Scope tracer after all 11 plans | 9 isolation tests | All PASSED | ✓ PASS |

Because WR-01 asserts a concurrency/ordering invariant, presence checks would
have been insufficient; it is marked VERIFIED only because the event-controlled
regression executes and passes.

### Anti-Patterns

| Scan | Scope | Result |
|---|---|---|
| Debt markers (`TBD`/`FIXME`/`XXX`) | 49 phase files | **Zero** — gate passes |
| `TODO`/`HACK`/`PLACEHOLDER` | 49 phase files | Zero |
| Stub phrases | 49 phase files | Only HTML `placeholder=` attributes and the legitimate "placeholder nodes" domain term; one test asserts an *unknown placeholder instead of zero*, which is the honest-totals behaviour |
| Static/hollow returns | drill-down, gaps, policy | None — all resolve from the scoped snapshot |

### Fabric Private-Link Decision — implemented, not just documented

| Directive | Verified |
|---|---|
| Suppress per-capacity `missing_private_endpoint` gap | ✓ `gaps.py:395-397`; `test_fabric_capacity_gap_is_suppressed_but_cognitive_account_remains` |
| Add tenant/workspace scope qualification to node facts | ✓ `topology.py:1354-1360` |
| Preserve Cognitive Services finding | ✓ same test |
| Install V21 Cognitive Services icon only | ✓ `ai-services.svg` present, listed in README |
| Do **not** add `fabric.svg` | ✓ absent; README records the intentional icon-less fallback |

### Drawer "confirmed clean" honesty contract

The highest-risk *silently-implies-complete* surface is correctly closed
(`TopologyDetailDrawer.tsx:282-335`): error → `role="alert"` + "not confirmed
clean"; loading → `aria-busy`, no claim; zero-but-truncated/unexhausted →
warning + **heading count suppressed** (`Open findings`); only zero **and**
exhausted **and** untruncated yields `Open findings (0)`.

---

## Gaps

**None blocking.** No truth FAILED, no artifact MISSING or STUB, no key link
NOT_WIRED, no blocker anti-pattern.

## Warnings

| # | Warning | Blocking |
|---|---|---|
| W1 | Verification target moved `3b4508be` → `96e81257`; 2 source commits landed mid-verification | Resolved — re-verified and accepted at `96e81257` |
| W2 | "52 observations / zero open" was stale at `3b4508be`; actual ledger is 54 / 51 / 3 / 0 | Resolved — consolidated ledger records all findings |
| W3 | `12-VALIDATION.md` previously recorded stale source/count evidence | Resolved — refreshed to `811883f3`, 2,736 / 2,769 |
| W4 | 27 pre-existing repo-wide Ruff findings in `infra/scripts`, `scripts` | No — zero overlap with phase files; documented deferral |

---

## Summary

Phase 12 achieves its goal. The scope-isolation defect that motivated the phase
is closed at a single enforcement point covering all 15 snapshot collections
plus both relationship families, and that closure is re-proven after all eleven
plans landed. Private-link projection is de-duplicated and every open finding
resolves to a node. Scale is bounded by gates that assert honest truncation
rather than mere fit. Policy mutation invalidates derived analysis and fails
closed on corrupt persisted state — verified by independent adversarial probes,
not by reading tests. Relationship, freshness, and provenance diagnostics are
observable and identifier-free.

The submitted closure record was, however, **one review generation behind the
code**: a later deep review of the very commit under verification surfaced two
genuine warnings that have since been fixed. Both were fail-closed and neither
weakened scope isolation or persisted state, so the goal is not compromised —
but the developer should confirm `96e81257` as the phase-close commit and
refresh `12-VALIDATION.md` before shipping.

---

_Verified: 2026-09-06T07:36:27Z_
_Verifier: the agent (gsd-verifier)_
_Verified at HEAD: `96e81257` (source `811883f3`)_
