# Phase 12: Network Topology Integrity and Scale - Context

## Phase Goal

Deliver a scope-safe, complete, scalable, and diagnosable network topology experience from upstream inventory and normalization through API, web, agents, MCP, and export.

## Source Evidence

- Deep review: `12-REVIEW.md`
- Confirmed review scope: network page/workspace/graph/drawer, API contracts, topology projection, relationship derivation, inventory/ARG/Fabric inputs, policy/gap analysis, agents/MCP, and exports.
- Review result: 20 findings (6 critical, 11 warning, 3 info), consolidated into five implementation recommendations.

## Locked Decisions

1. Scope isolation is the first tracer and release gate. Fix `private_link_resources` filtering and semantic relationship preservation before projecting additional resources.
2. Private-link candidates must appear as topology context nodes even when they have no private endpoint; resources referenced by findings cannot remain orphaned.
3. Enterprise scale uses an explicit level-of-detail contract and on-demand child expansion. Truncation, withheld detail, and pagination must never be silent.
4. Design-policy mutations must invalidate server-derived analysis and refetch dependent web views. The existing backend declarative-rule contract must be exposed through preview-first UI validation rather than duplicated client validation.
5. Relationship projection must case-fold canonical ARM IDs, report dropped relationships by type, preserve snapshot-level freshness, and expose actual flow-log provenance.
6. API changes must preserve downstream agent/MCP/export compatibility through additive fields or an explicit deprecation window; do not silently flip the topology default contract.
7. Findings should identify both the control and affected resources so badges and drawers reflect operational impact, not only the NSG or firewall collection that owns a rule.

## Scope

### In Scope

- Subscription/resource authorization boundaries across topology, gaps, findings, agents, and MCP.
- Private-link resource projection, including Fabric and Foundry.
- Honest totals, pagination/truncation, topology level of detail, and on-demand drill-down.
- Policy mutation invalidation, web refetch, declarative custom-rule authoring and preview.
- ARM-ID normalization, semantic/DNS/subnet/private-endpoint edges, dropped-edge diagnostics, freshness, and flow-log provenance.
- Frontend badge/drawer semantics, metric accuracy, selection/filter consistency, and auditable export context.
- Regression, integration, contract, and representative scale tests.

### Out of Scope

- Provisioning new Azure private endpoints or changing live network posture.
- Replacing Cytoscape or redesigning the entire Network page visual language.
- Broad inventory ownership changes already completed in Phases 7-10.
- Cross-page Copilot orchestration owned by Phase 11, except compatibility checks for existing topology tools.

## Delivery Order

1. Scope-safe end-to-end tracer.
2. Complete private-link resource projection and finding-to-node integrity.
3. Bounded topology/finding contracts and scalable drill-down.
4. Policy invalidation and declarative-rule workflow.
5. Relationship-quality diagnostics, freshness/provenance, and downstream compatibility hardening.

## Verification Expectations

- Include direct tests of `NetworkIntelligenceService.scoped()`.
- Prove zero out-of-scope gaps and preserve semantic relationships.
- Exercise more than 100 gaps/findings and assert honest totals.
- Measure summary topology against explicit node and payload budgets.
- Verify a saved custom rule updates gaps and badges without reload.
- Verify mixed-case ARM IDs, dangling relationships, DNS links, snapshot freshness, and flow-log provenance.
