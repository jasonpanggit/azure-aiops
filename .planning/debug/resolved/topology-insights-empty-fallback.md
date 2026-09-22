---
slug: topology-insights-empty-fallback
status: resolved
trigger: "The deployed topology page responds with Insights unavailable: The bounded snapshot returned no supported findings or narration."
created: "2026-09-22T21:30:00Z"
updated: "2026-09-22T21:45:00Z"
goal: find_and_fix
---

# Debug Session: Topology Insights Empty Fallback

## Symptoms

- Expected: Operations Copilot shows grounded topology insights, or an evidence-only deterministic fallback when LLM narration is unavailable.
- Actual: The section shows `Insights unavailable` and `The bounded snapshot returned no supported findings or narration.`
- Error messages: No browser console or transport error after PR #278.
- Timeline: Visible after the PR #278 crash hotfix allowed the partial response to render safely.
- Reproduction: Open authenticated production `/network`, wait for `investigate-context` to return, and inspect the top insight section.

## Evidence

- Live response: HTTP 200, status=partial, synthesis.mode=deterministic, policy_status=fallback, fallback_reason=planner_unavailable; uncertainty notes Foundry narration timed out.
- synthesis.narration empty, synthesis.executive.claims empty, despite a fully successful `network_topology` tool finding (hub, isolated VNet, shared services, resources, relationships) in the same response.
- Traced canonical path: `/copilot/investigate-context` -> `_run_context_via_canonical` (src/api/routers/copilot.py) -> `OrchestrationService.execute` -> `OrchestrationService._synthesize` (src/operations/orchestration_service.py) -> `deterministic_network_claims`.
- `deterministic_network_claims` only ever built its primary claim from a successful `firewall_nsg_gaps` finding. When none existed (only `network_topology` succeeded), it hit `if network_claim is None: return []` **before** reaching the generic direct-citation fallback loop (which calls `normalize_cited_findings` and would have projected the `network_topology` finding into a citation-backed claim).
- API router (`copilot.py`) derives `synthesis.narration` by joining `claims[].summary` when `synthesis.narration` is empty -- so an empty `claims` list directly causes an empty narration too, explaining both symptoms from one root cause.

## Resolution

root_cause: >
  `deterministic_network_claims` in src/operations/orchestration_service.py returned an empty
  claims list before evaluating the generic direct-citation fallback whenever no
  `firewall_nsg_gaps` finding existed, silently discarding fully successful `network_topology`
  (and other cited specialist) findings even though they carried real citation-backed evidence.
fix: >
  Removed the early `if network_claim is None: return []` guard so the fallback
  direct-citation loop (backed by `normalize_cited_findings`) always runs. Also
  preferred the richer, already-computed `network_topology`/`hub_dependents`
  finding summary (topology counts, hub/spoke/isolated detail) over the generic
  templated sentence for those two tools specifically, while leaving the
  existing generic phrasing unchanged for all other specialist tools (no
  regression to `test_retained_mixed_firewall_turn_keeps_other_cited_specialist_claims`).
verification: >
  New backend regression tests (tests/test_topology_insights_empty_fallback.py) reproduce the
  exact live shape (planner_unavailable / Foundry timeout + successful network_topology finding,
  no firewall_nsg_gaps) and assert non-empty, citation-backed claims and narration; confirmed
  red (fail) on the pre-fix code and green (pass) on the fix via git stash toggling. New frontend
  test in TopologyInsights.test.tsx reproduces the same production response shape and asserts the
  "Evidence-only fallback" branch renders the deterministic narration instead of "Insights
  unavailable". Full frontend suite (832 tests) and directly related backend suites
  (test_foundry_agent.py, test_network_topology.py, test_network_analysis.py,
  test_copilot_evaluation.py, test_operations_smoke_contract.py, new regression file) pass.
  ruff and tsc --noEmit clean on changed files. A pre-existing, unrelated test-infrastructure
  defect (tests/copilot_authorization_fixtures.py referencing a `reviewed_tree_digest` attribute
  that src/operations/copilot_canary_authorization.py does not import) blocks running
  tests/test_api_copilot_unified.py and tests/test_orchestration_policy.py end-to-end; confirmed
  via `git stash` that this failure is identical on unmodified origin/main and therefore out of
  scope for this fix.
files_changed:
  - src/operations/orchestration_service.py
  - tests/test_topology_insights_empty_fallback.py (new)
  - web/src/components/network/TopologyInsights.test.tsx
