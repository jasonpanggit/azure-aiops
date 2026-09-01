---
status: awaiting_human_verify
trigger: "On the Network topology map, nodes with a red dot indicate findings, but clicking some red-dot nodes shows no findings in the side drawer."
created: 2026-09-01T09:46:44+08:00
updated: 2026-09-01T10:53:00+08:00
---

# Debug Session: Topology Finding Drawer

## Symptoms

- Network topology nodes with a red dot indicate findings.
- Clicking some red-dot nodes opens a side drawer with no findings.
- Follow-up bug after completed phase 09-11.

## Current Focus

- bug_class: bohrbug
- hypothesis: CONFIRMED — TopologyGraph clears obsolete finding data with removeData("badge"), but Cytoscape retains the already-computed two-layer background-image, while the drawer immediately filters against the current record map.
- test: Human verification in the real Network topology workflow.
- expecting: A node whose current findings disappear loses its red dot; every node that still has a red dot shows current findings in the drawer.
- next_action: Await user confirmation from the browser workflow; do not archive or commit before confirmation.
- tdd_checkpoint:
    test_file: web/src/components/network/TopologyGraph.test.tsx
    test_name: removes a stale badge when the node no longer has findings
    status: green
    failure_output: expected icon-plus-badge background-image to equal the single Azure icon after syncFindingBadge(node, undefined)

## Evidence

- timestamp: 2026-09-01T09:49:00+08:00
  checked: Project scope and working tree
  found: The requested follow-up UI bug is compatible with the completed phase scope; the repository already contains many unrelated modified and untracked files that must be preserved.
  implication: Investigation and any fix must be surgical and limited to the topology drawer path and focused tests.
- timestamp: 2026-09-01T09:49:00+08:00
  checked: Debug knowledge base
  found: No .planning/debug/knowledge-base.md exists.
  implication: There is no known-pattern candidate to prioritize.
- timestamp: 2026-09-01T09:49:00+08:00
  checked: Project rules and configured agent skills
  found: No rules/*.md files and no configured gsd-debugger agent skills were returned; the project provides the gsd-debug command skill.
  implication: Follow the repository's gsd-debug skill plus the debugger protocol.
- timestamp: 2026-09-01T09:53:00+08:00
  checked: Frontend search for topology finding marker and drawer paths
  found: TopologyWorkspace derives and passes findingSeverityByResource to TopologyGraph while separately passing selected-node findings to TopologyDetailDrawer; graph node identity originates in lib/network-graph.ts.
  implication: The likely divergence is localized to TopologyWorkspace's two projections or the graph node ids they consume.
- timestamp: 2026-09-01T09:58:00+08:00
  checked: Complete topology marker and drawer implementations
  found: Both aggregation functions index gaps by gap.resource_id and rule findings by finding.control_id. The graph badges via findingSeverityByResource.get(node.id()), while a click returns the node's detail object and the drawer uses findingsByResource.get(selection.node.id).
  implication: For a stable render, both paths should be equivalent because Cytoscape element data spreads the same TopologyNodeData.id into both node.id() and detail.id; a persistent mismatch requires an identity/lifecycle divergence not visible in the two aggregators alone.
- timestamp: 2026-09-01T09:58:00+08:00
  checked: Existing focused topology tests and SBFL preconditions
  found: Tests cover graph construction and badge stylesheet rendering but not TopologyWorkspace's finding aggregation/selection invariant. No failing focused test or per-test coverage spectrum currently exists.
  implication: SBFL is skipped; a minimal agent-authored regression test is needed once the exact trigger is confirmed.
- timestamp: 2026-09-01T10:03:00+08:00
  checked: NetworkGap and RuleFinding TypeScript contracts plus mapping history
  found: NetworkGap has resource_id; RuleFinding has control_id but no generic resource_id. Badge mapping was introduced first, and drawer record grouping was added later by duplicating the same exact-key loops.
  implication: The duplication creates two sources of mapping behavior but does not itself explain a stable mismatch; the concrete producer semantics and failing identity class must be traced.
- timestamp: 2026-09-01T10:03:00+08:00
  checked: Baseline topology test invocation
  found: The first command ran npm from the repository root, which has no package.json, so no tests executed.
  implication: This is a test-invocation setup error, not product evidence; rerun against web/package.json.
- timestamp: 2026-09-01T10:11:00+08:00
  checked: Network page data flow and corrected frontend baseline
  found: NetworkPage passes the same current gaps and rule-findings arrays directly into TopologyWorkspace. The focused graph suites pass 62/62; none exercises workspace mapping or selection.
  implication: There is no page-level filtering divergence and no existing regression; the fault lies below that boundary or in an uncovered data equivalence class.
- timestamp: 2026-09-01T10:11:00+08:00
  checked: Backend identity references and existing graph tests
  found: Backend network models generally test case-folded resource ids, but the frontend graph already contains case-insensitive relationship resolution and a regression for relationship/resource casing differences. Resource node insertion itself remains case-sensitive.
  implication: Case variation is a concrete data-category candidate worth testing before pursuing lifecycle timing.
- timestamp: 2026-09-01T10:16:00+08:00
  checked: Topology resource construction and a minimal case-variant graph input
  found: Backend topology resources copy model resource_id values verbatim and append attached workload ids verbatim. buildTopologyGraph preserves two resources whose ids differ only by casing as two separate nodes.
  implication: The data class is possible at the frontend boundary, but it is not yet evidence that a badged element can select a no-finding detail object; the real fixture must show whether this ambiguity actually occurs.
- timestamp: 2026-09-01T10:21:00+08:00
  checked: Real network scenario topology/finding identity equivalence classes
  found: The fixture has 30 topology resources, 9 gap identities, and 11 rule-finding identities; every finding identity matches a topology node exactly, with zero folded duplicates and zero folded-only matches.
  implication: The realistic fixture does not reproduce case ambiguity and confirms that stable exact-key mapping is internally consistent.
- timestamp: 2026-09-01T10:26:00+08:00
  checked: useApi refresh semantics
  found: Scope refresh preserves old data while loading, all three Network hooks share the same scope dependency, and TopologyWorkspace unmounts the graph whenever topology.loading is true. Both finding maps are still rebuilt from the same arrays.
  implication: An ordinary scope refresh does not provide a durable or practically clickable passive-effect divergence; test whether Cytoscape itself fails to clear the visual badge instead.
- timestamp: 2026-09-01T10:32:00+08:00
  checked: Focused Cytoscape mapped-style removal experiment
  found: Before removeData("badge"), computed background-image was the Azure icon plus the badge data URI. After removal, node.data("badge") was undefined but computed background-image remained the same icon-plus-badge value.
  implication: Root cause is confirmed: the graph's current clear path removes lookup data without clearing the visual marker, so subsequent drawer lookup can honestly be empty while a stale red dot remains visible.
- timestamp: 2026-09-01T10:36:00+08:00
  checked: Agent-authored TDD regression for badge add/remove lifecycle
  found: The focused test fails at TopologyGraph.test.tsx:57. Expected /azure-icons/vnet.svg after finding removal, but received the icon plus the encoded critical badge SVG even though node.data("badge") is undefined.
  implication: The test reproduces the exact stale-marker mechanism and is RED before the behavioral fix.
- timestamp: 2026-09-01T10:40:00+08:00
  checked: Focused working-tree diff and frontend test tooling
  found: The only topology changes are the prior helper extraction and RED lifecycle test; Vitest is configured, while no Stryker configuration or dependency exists.
  implication: The production fix can remain a surgical change inside syncFindingBadge; mutation checking will require a documented skip unless the existing stack provides another configured runner.
- timestamp: 2026-09-01T10:41:00+08:00
  checked: First isolated style-lifecycle probe invocation
  found: Node was invoked from the repository root and could not resolve the frontend-only Cytoscape package, so the experiment did not run.
  implication: This is an invocation setup error; rerun unchanged from web/ before drawing any product conclusion.
- timestamp: 2026-09-01T10:42:00+08:00
  checked: Explicit background-image synchronization across add, remove, and re-add
  found: Cytoscape returned icon-plus-badge after add, icon-only after removal, and icon-plus-badge after re-add; the remaining multi-value sizing kept the primary icon's original first-layer values.
  implication: Updating background-image in both branches is a minimal reversible lifecycle fix and does not strand a bypass that prevents a later badge from rendering.
- timestamp: 2026-09-01T10:44:00+08:00
  checked: Minimal production fix
  found: syncFindingBadge now explicitly sets icon-plus-badge when a finding exists and icon-only/none when it does not, while preserving the existing badge data and title lifecycle.
  implication: The rendered marker and current finding state are synchronized at their existing single production boundary.
- timestamp: 2026-09-01T10:45:00+08:00
  checked: Focused GREEN run
  found: TopologyGraph.test.tsx passed 10/10, including the previously RED stale-badge regression; Vitest emitted only pre-existing Cytoscape fixture mapping warnings.
  implication: The target test is green, but adjacent transition boundaries should be added before guardrail acceptance so both lifecycle branches are protected.
- timestamp: 2026-09-01T10:47:00+08:00
  checked: Hardened lifecycle boundaries
  found: TopologyGraph.test.tsx passed 11/11 after adding badge re-addition and no-service-icon removal assertions; the same non-failing fixture mapping warnings remain.
  implication: The regression now protects both explicit style assignments and the icon-or-none boundary around the fixed state transition.
- timestamp: 2026-09-01T10:48:00+08:00
  checked: Held-out adjacent network suites
  found: network-graph.test.ts passed 53/53 and network-services.test.ts passed 9/9.
  implication: Graph construction and network service projections remain unaffected by the badge rendering fix.
- timestamp: 2026-09-01T10:50:00+08:00
  checked: Guardrail reproduction with only the production fix removed
  found: The named stale-badge regression returned to RED, receiving the icon-plus-critical-badge background where icon-only was expected.
  implication: The failure is causally controlled by the explicit style synchronization rather than by the helper extraction or test setup.
- timestamp: 2026-09-01T10:52:00+08:00
  checked: Guardrail fixed-on-reapply
  found: After restoring the exact production fix, TopologyGraph.test.tsx passed 11/11 again.
  implication: Revert-and-reconfirm passes: the bug returned without the fix and disappeared when the same fix was reapplied.
- timestamp: 2026-09-01T10:53:00+08:00
  checked: Static validation and final diff
  found: web TypeScript no-emit and git diff --check both passed; the production diff preserves existing behavior and adds rendered-style synchronization at the existing badge helper boundary.
  implication: The fix is type-correct, clean, minimal, and not a deletion-only or behavior-suppressing patch.
- timestamp: 2026-09-01T10:53:00+08:00
  checked: Fix-acceptance guardrail
  found: Target test, adjacent tests, no-op/deletion inspection, and revert-and-reconfirm passed. Mutation check was skipped because the frontend has no Stryker dependency or configuration.
  implication: All applicable automated guardrail signals accept the fix; only real browser workflow confirmation remains.

## Eliminated

- hypothesis: For stable string resource ids, Cytoscape's rendered node id differs from the selected detail object's id.
  evidence: Elements are built with data spread from the same TopologyNodeData object and detail references that object; node.id() and detail.id therefore originate from the same id value, while both finding maps use identical exact keys.
  timestamp: 2026-09-01T10:11:00+08:00
- hypothesis: Case-variant duplicate topology resource ids cause a badged node click to resolve to a no-finding duplicate.
  evidence: Although the frontend preserves case-variant duplicate nodes, the realistic backend fixture has no folded duplicates and all 20 finding identities match exactly; moreover each Cytoscape element retains its own matching detail id, so duplicate existence alone does not make a badge click select the other element.
  timestamp: 2026-09-01T10:21:00+08:00
- hypothesis: An ordinary useApi scope refresh leaves a stale clickable badge while the drawer has newer findings.
  evidence: useApi retains old records while loading, and the topology graph is replaced by a loading panel as soon as the shared scope triggers topology.loading; when responses land, severity and record maps still derive from the same current arrays.
  timestamp: 2026-09-01T10:26:00+08:00

## Resolution

- root_cause: TopologyGraph uses node.removeData("badge") to clear obsolete finding markers, but Cytoscape 3.34.1 retains the previously computed multi-layer background-image after that data removal. The drawer reads the current findingsByResource map, so after a finding disappears the canvas can retain a stale red dot while the selected-node drawer has no current records.
- fix: syncFindingBadge now updates Cytoscape's background-image bypass in both lifecycle branches, replacing a removed badge with the node's current service icon (or none) and restoring icon-plus-badge whenever a finding exists.
- verification:
    target_test:
      result: pass
      suite: web/src/components/network/TopologyGraph.test.tsx
      tests: 11
    mutation_check:
      result: skipped
      reason_if_skipped: No Stryker dependency or configuration exists in the frontend package.
      mutant_killed: false
    no_op_deletion:
      result: pass
      deletion_justified_by_rca: false
    adjacent_tests:
      result: pass
      suites_run:
        - web/src/lib/network-graph.test.ts (53 passed)
        - web/src/lib/network-services.test.ts (9 passed)
    revert_and_reconfirm:
      result: pass
      bug_returned_on_revert: true
      fixed_on_reapply: true
    typecheck:
      result: pass
      command: cd web && npx tsc --noEmit
    guardrail_verdict: accepted
- prevention: Agent-authored regressions in web/src/components/network/TopologyGraph.test.tsx cover finding add/remove/re-add and badge removal with and without a service icon.
- oracle_type: specified — a topology node displays a finding badge if and only if its current finding lookup contains at least one record.
- files_changed:
  - web/src/components/network/TopologyGraph.tsx
  - web/src/components/network/TopologyGraph.test.tsx
