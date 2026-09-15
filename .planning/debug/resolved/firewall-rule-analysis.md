---
slug: firewall-rule-analysis
status: resolved
trigger: "The Network flow analyzer should analyze the firewall rules that the firewall has and explain what they allow instead of stopping at a generic unknown."
created: "2026-09-15T14:50:55+08:00"
updated: "2026-09-15T15:44:00+08:00"
goal: find_and_fix
---

# Debug Session: Firewall Rule Analysis

## Symptoms

- Expected: For a selected VM/subnet to `Internet` or a public FQDN, evaluate the observed Azure Firewall rule collections in priority order for the source, destination, protocol, and port; identify the definite matching allow/deny rule and explain what it permits. If an IP group or FQDN reference is unavailable, identify that exact unresolved input without discarding definite results from other rules.
- Actual: Live `vm1903 -> Internet` correctly resolves the subnet default route through Azure Firewall after PR #136, but the firewall hop is only `unknown` with `firewall rules reference IP groups or FQDNs that cannot be evaluated`.
- Error messages: No runtime error. The product returns an incomplete semantic analysis.
- Timeline: Observed during post-deployment validation of PR #136 on 2026-09-15.
- Reproduction: Network > Path analysis; source `vm1903 — Network Interface`; destination `Enter manually` = `Internet`; TCP/443; Analyze path.

## Current Focus

reasoning_checkpoint:
  hypothesis: "`_firewall_rule_matches` in src/network/flow.py short-circuited to `None` (uncertain) for ANY rule that referenced `source_ip_groups` or `destination_fqdns` BEFORE checking protocol/port/other-side address, and the outer loop treated 'uncertain seen anywhere' as a global flag that survived even after a later, unrelated, fully-resolvable rule was found -- so a single irrelevant IP-group/FQDN rule (wrong port, wrong protocol, or wrong source) poisoned the whole verdict to 'unknown' instead of letting the search reach the true deny/allow decision."
  confirming_evidence:
    - "Direct read of `_firewall_rule_matches` (pre-fix): `if rule.source_ip_groups or rule.destination_fqdns: return None` executed before any protocol/port/address check, so a totally irrelevant rule (wrong port) still forced `uncertain=True`."
    - "Direct read of `_evaluate_firewall` (pre-fix): `uncertain=True; continue` kept scanning, and any later definite match still returned immediately -- but once no definite match existed anywhere, the accumulated `uncertain` flag (which could have been set by an irrelevant rule) forced the final decision to 'unknown' rather than 'deny'."
    - "New regression test `test_a_rule_referencing_an_fqdn_for_a_different_port_does_not_cause_unknown` reproduced 'unknown' pre-fix and now returns a definite 'deny'."
    - "New regression test `test_a_manually_entered_public_fqdn_matches_an_application_rule` reproduced 'deny' pre-fix (FQDN never evaluated) and now returns 'allow' citing the matching Application Rule -- also required recognizing that Application Rule protocols (Http/Https/Mssql) ride over TCP, since the API's default/observed query protocol is 'Tcp' (confirmed in src/api/routers/network.py:349)."
  falsification_test: "If protocol/port pre-filtering and FQDN-aware destination matching did not change the outcome, the new regression tests added in tests/test_network_flow.py::TestFirewallRuleEvaluation would still fail after the fix. They pass."
  fix_rationale: "The fix does not touch the deny-by-default rule or introduce guesses: it (1) evaluates protocol and port -- always fully observed data -- before treating an IP-group/FQDN reference as unresolved, so irrelevant rules are eliminated instead of poisoning the result; (2) evaluates the resolvable side of a rule (source_addresses OR destination_addresses) independently from the unresolved side (source_ip_groups OR destination_fqdns), so a rule can be a definite non-match on one dimension without needing the other; (3) adds real FQDN pattern matching (exact + `*.` wildcard) against a manually entered public hostname, returning a definite allow/deny; (4) preserves indeterminate when the destination is the generic `Internet` tag (no specific host) and an FQDN rule could still apply, matching the explicit 'must never falsely match' constraint; (5) changes the outer loop so an unresolved rule encountered before any definite decision stops the search (matches Azure's own evaluate-until-first-match semantics: we cannot claim a later rule decided the flow if an earlier ambiguous rule might already have matched)."
  blind_spots: "IP group membership is still never resolved (no IP group definitions are ingested), so any rule whose relevant side depends on an IP group remains indeterminate when it cannot be eliminated by protocol, port, or the other address side. FQDN tags are preserved separately from literal hostnames and remain indeterminate because their Microsoft-managed membership is not part of the observed snapshot."
  candidate_causes:
    - "code: premature short-circuit in `_firewall_rule_matches` (source_ip_groups/destination_fqdns checked before protocol/port)"
    - "code: missing FQDN-pattern matching logic entirely (destination_fqdns was never evaluated against a resolved public hostname)"
    - "data/config: Application Rule protocol values (Http/Https) never reconciled with the API's TCP-default query protocol"
  and_gate: "yes -- the live symptom required both the premature short-circuit fix AND the protocol reconciliation fix simultaneously: fixing only the short-circuit still left FQDN rules unmatched for realistic TCP/443 queries, and fixing only protocol reconciliation without removing the short-circuit still returned 'unknown' immediately. Confirmed via test_a_manually_entered_public_fqdn_matches_an_application_rule failing until both changes were present."

next_action: "Resolved. Create the focused pull request without merging or deploying it."

## Constraints

- Preserve truthful indeterminate behavior whenever no definite firewall rule can be selected.
- Do not infer that generic `Internet` matches a specific FQDN-only application rule.
- Evaluate Azure Firewall collection and rule priority semantics accurately.
- Keep the fix focused on Network flow analysis and directly related UI copy/tests.
- Do not merge or deploy.

## Evidence

- timestamp: "2026-09-15T14:46:38+08:00"
  observation: "Live UI resolves route-to-firewall (0.0.0.0/0 -> VirtualAppliance 10.0.2.4) but reports the firewall hop unknown because rules reference IP groups or FQDNs that cannot be evaluated."
  source: "Authenticated Playwright validation of deployed PR #136"

- timestamp: "2026-09-15T14:53:00+08:00"
  checked: "src/network/flow.py `_evaluate_firewall`/`_firewall_rule_matches` (pre-fix)"
  found: "`if rule.source_ip_groups or rule.destination_fqdns: return None` ran before any protocol/port/address check; the outer loop's `uncertain` flag was global and never reset, and the final decision used `unknown if uncertain else deny` regardless of whether the uncertain rule could possibly have applied to the query."
  implication: "Any single IP-group or FQDN rule anywhere in any collection -- even for an unrelated port, protocol, or source -- downgrades every flow through the firewall to 'unknown', which matches the observed symptom exactly."

- timestamp: "2026-09-15T14:55:00+08:00"
  checked: "src/network/models.py FirewallRule / src/network/loader.py `_firewall_rule` ingestion"
  found: "`destination_fqdns` and `source_ip_groups` are ingested verbatim from the live provider payload (`destinationFqdns`/`sourceIpGroups`), and `source_addresses`/`destination_addresses` are populated independently -- a rule can have one or the other, not necessarily both blocked at once."
  implication: "The provider snapshot is not the problem; the evaluator was discarding usable, already-ingested data (the other side's resolvable addresses, and the FQDN list itself) instead of evaluating it."

- timestamp: "2026-09-15T14:59:00+08:00"
  checked: "src/api/routers/network.py:349 (path-analysis query default protocol)"
  found: "The API defaults `protocol` to `\"Tcp\"`, matching the live UI repro (TCP/443); Application Rules typically list `protocols=[\"Https\"]` or `[\"Http\"]`, which never equals `\"Tcp\"` under plain `ProtocolSpec` matching."
  implication: "Even after fixing the short-circuit and adding FQDN matching, Application Rules would never match a realistic TCP/443 query unless Http/Https/Mssql are recognized as TCP-based application protocols."

- timestamp: "2026-09-15T15:02:00+08:00"
  checked: "tests/test_network_flow.py::TestFirewallRuleEvaluation (new, 6 tests) + full tests/test_network_flow.py suite (29 tests)"
  found: "All 6 new regression tests pass after the fix; all 23 pre-existing tests in the file continue to pass unchanged."
  implication: "The fix resolves the reported behavior without regressing existing firewall/routing/NSG semantics covered by the file."

- timestamp: "2026-09-15T15:05:00+08:00"
  checked: "Full repo test suite (`python3 -m pytest tests/ -q`, excluding a pre-existing `opentelemetry.sdk` import error unrelated to this change)"
  found: "13 failures remain, all pre-existing and confirmed present on `git stash` (unmodified tree) via `AttributeError: '_NetworkContext'/'Context' object has no attribute 'onboarding'` -- unrelated to `src/network/flow.py`."
  implication: "No new regressions introduced by this fix; the 13 failures are out-of-scope baseline issues."

- timestamp: "2026-09-15T15:06:00+08:00"
  checked: "`python3 -m ruff check src/network/flow.py tests/test_network_flow.py`"
  found: "Clean after one auto-fixed import-ordering issue (multi-import from `.addressing` reformatted to parenthesized block)."
  implication: "No lint regressions."

## Eliminated

- hypothesis: "The provider snapshot omits IP group / FQDN reference data needed to evaluate the live rule."
  evidence: "loader.py ingests `destinationFqdns`/`sourceIpGroups` verbatim from the payload; the data is present on the FirewallRule model. The gap was in the evaluator discarding it (destination_fqdns was never compared against anything), not in ingestion. IP group *membership* (which addresses an IP group actually contains) is genuinely never ingested anywhere in this codebase, so that part of the hypothesis holds only for IP groups, not FQDNs -- and remains a correctly-reported indeterminate case, not a fixable gap."
  timestamp: "2026-09-15T14:57:00+08:00"

## Resolution

root_cause: "In `TrafficFlowValidator._firewall_rule_matches` (src/network/flow.py), any rule referencing `source_ip_groups` or `destination_fqdns` was marked fully unresolved (`return None`) before protocol, port, or the rule's other (resolvable) address dimension were checked, and `_evaluate_firewall`'s outer loop treated any single such occurrence as a global 'uncertain' flag that forced the final firewall decision to 'unknown' even when a later, unrelated rule (or the default deny) was the true, definite answer. Additionally, `destination_fqdns` was never actually compared against a manually entered public FQDN, and Application Rule protocol values (Http/Https/Mssql) were never reconciled with the API's default TCP query protocol, so even a correct FQDN match would have been eliminated by an unrelated protocol mismatch."
fix: "Reordered `_firewall_rule_matches` to check protocol and port first (always fully observed), then evaluate source and destination independently via new `_firewall_source_match`/`_firewall_destination_match` helpers that only return `None` (unresolved) for the specific side that actually depends on an unresolved IP group or FQDN -- a definite non-match on the other, resolvable side (or on protocol/port) now short-circuits to `False` without setting uncertainty. Added `_fqdn_match`/`_destination_hostname`/`_fqdn_pattern_matches` to evaluate `destination_fqdns` against a manually entered public hostname (exact and `*.` wildcard matching), returning `None` only when the destination is the generic `Internet` tag (no specific host to compare), per the 'must never falsely match' constraint. Added `_firewall_protocol_matches` so Http/Https/Mssql Application Rule protocols are recognized as TCP-based when the query protocol is Tcp/any. Changed `_evaluate_firewall`'s loop so an unresolved rule stops the scan (`break`) rather than continuing past it: any match found strictly before the first unresolved rule is trusted as the definite decision (satisfies 'must not erase a definite higher-priority result'), while an unresolved rule encountered before any definite match keeps the verdict indeterminate even if a later, fully-resolvable rule would otherwise seem to decide it (correct because Azure evaluates rules in strict priority order and stops at first match, so a still-ambiguous earlier rule could already have decided the flow)."
verification: "Focused and adjacent backend tests pass, including application/network rule ordering, rule-collection-group priority, public FQDN matching, generic Internet summaries, and normalization of FQDN tags/protocol ports. `python3 -m ruff check src tests` passes. Frontend ESLint passes, all 62 Vitest files and 768 tests pass, `npx tsc --noEmit` passes, and the Next.js production build succeeds."
files_changed:
  - "src/network/flow.py"
  - "src/network/loader.py"
  - "src/network/models.py"
  - "src/network/topology.py"
  - "src/onboarding/network_normalize.py"
  - "tests/test_network_flow.py"
  - "tests/test_network_normalize_from_inventory.py"
  - "web/src/app/globals.css"
  - "web/src/app/network/page.test.tsx"
  - "web/src/app/network/page.tsx"
  - "web/src/lib/types.ts"
