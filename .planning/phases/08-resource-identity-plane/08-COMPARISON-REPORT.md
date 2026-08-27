# Phase 8 Plan 3: Hermes vs. Fabric-Native Comparison Report

**Generated from:** `tests/test_hermes_fabric_comparison.py` harness run against
`fabric_pipelines/comparison_report.py`'s `compare()` function, 2026-08-27
fixture (`tests/topology_comparison_scenario.py`, shared by both arms per
Pitfall 3 — one fixture, not two).

**Scenario:** One VNet/Subnet/NSG (with one allow rule, one default-deny rule)
raw-ARG-shaped snapshot. Root: the NSG (`nsg-fixture`).

**Arms compared:**
- **Hermes** — `hermes_arg_connector.normalize.Normalizer.normalize()` (the
  engine underlying `SemanticEngine.get_impact_context()`'s data layer)
- **Fabric-native** — `fabric_pipelines.topology_pipeline.derive_edges()`
  (08-02's Fabric IQ comparison arm)

**Comparison method note:** `SemanticEngine.get_impact_context()`'s own
`cause_type` branches (`PatchAssessment`/`Subscription`/`Application`/
`ASSET_TYPES`) do not cover network-topology entity types (VNet/Subnet/NSG) —
a network root falls into the `else: resources = set()` branch and would
report a near-empty blast radius regardless of graph richness, which is not
a fair comparison point on its own. The harness instead reduces both arms to
a uniform bounded BFS traversal over each arm's own relationship/edge index
starting from the same root — the literal shared capability D-04 asks about
("what is reachable from this root"), and the one traversal both
`Normalizer.normalize()`'s `NormalizedGraph.relationships` and
`derive_edges()`'s edge dict actually support natively. This is documented
here rather than silently worked around, per the plan's `<action>` requiring
each dimension be actually measured, not proxied without a label.

---

## 1. Correctness

| Metric | Hermes | Fabric |
|---|---|---|
| Impacted-entity count from NSG root | 4 | 4 |
| Impacted-set match | **True** | **True** |

Both arms reach the same 4 entities (VNet, Subnet, NSG, NetworkSecurityRule)
via the `contains`/`protectedBy`/`hasRule` edge chain from the NSG root. No
divergence in the impacted set for this scenario.

## 2. Evidence-link presence

| Metric | Hermes | Fabric |
|---|---|---|
| Edges missing source/confidence evidence | none | none |

Every edge in both arms carries a non-empty `source` tag and positive
`confidence` — no evidence-free edges in either arm for this scenario.

## 3. Authorization / scope enforcement

| Metric | Hermes | Fabric |
|---|---|---|
| Edges referencing an entity outside the emitted/authorized scope | none | none |

Neither arm's edge set references an entity that was never itself emitted as
part of the same run (post dangling-edge filtering, see §6).

## 4. Latency (wall-clock, single-run measurement)

| Arm | Seconds |
|---|---|
| Hermes (`Normalizer.normalize()`) | ~0.44s |
| Fabric (`derive_edges()`) | ~0.0001s |

Hermes's full `Normalizer.normalize()` pass does substantially more work per
call (it normalizes all ~15 ARG entity families defined in `ENTITY_TYPES`,
even though this fixture only populates the network sub-resource keys),
while `derive_edges()` only processes the network-shaped keys it's given.
This is a single-run, single-fixture measurement, not a load-tested
benchmark — treat as directional, not authoritative.

## 5. Operational cost (documented proxy — not live Azure billing telemetry)

| Metric | Hermes | Fabric |
|---|---|---|
| Query-count proxy (fixture payload key count) | 10 | 10 |
| Edge count (post dangling-filter) | 4 | 4 |

Both arms are fed the identical fixture (same `topology_comparison_scenario()`
dict), so the query-count proxy is necessarily identical here — this
dimension would need a live ARG-vs-Fabric-read cost comparison (out of scope
for a fixture-only harness) to be more informative than "equal by
construction." Documented explicitly as a proxy per the plan's requirement
that this dimension never be silently omitted.

## D-05: Explicit non-accepted edge states

An edge deliberately marked `assertionState: "conflicting"` (simulating a
stale/unauthorized observation, e.g. from an external flow-log join) was
injected into both arms' edge collections. Result: **both arms preserve the
`"conflicting"` state explicitly** — neither arm silently drops the edge nor
upgrades it to `"accepted"`. This satisfies D-05's requirement that
unknown/stale/conflicting/unauthorized edges remain explicit in both arms.

## D-05 edge case: dangling-edge (unemitted endpoint) drop parity — divergence found and resolved

A real divergence was discovered between the two arms' **raw** output, before
any harness-level filtering:

| Arm | Raw edge count | Dangling edges present in raw output? |
|---|---|---|
| Hermes (`Normalizer.normalize()`) | 4 | **No** — already filtered internally |
| Fabric (`derive_edges()`) | 6 | **Yes** — 2 `belongsTo` edges to the never-emitted resource-group container (`rg-topology-fixture`) |

`Normalizer.normalize()` has an internal `known_entity_ids` filter
(`normalize.py:218-234`) that drops any relationship whose subject/object
isn't itself an emitted entity — in this fixture, no `resource_containers`
payload key is supplied, so the resource group is never emitted, and Hermes
silently drops the two `belongsTo` edges pointing to it.
`fabric_pipelines.topology_pipeline.derive_edges()` has **no equivalent
filter** — it returns all edges from its internal index regardless of
whether both endpoints were actually emitted as entities in the same call.

**Resolution:** rather than modifying `derive_edges()` (not in this plan's
`files_modified` list, and changing production pipeline behavior mid-report
would confound the very comparison being measured), the comparison harness
(`fabric_pipelines/comparison_report.py::filter_dangling_edges`) applies the
same "drop edges with unemitted endpoints" rule uniformly to **both** arms'
raw output before any comparison is made. After this harness-level filter:
both arms' edge sets are dangling-edge-free, and the *effective* comparison
surface treats this drop identically — satisfying the plan's Test 3
requirement that the drop be "consistent... not silently kept in one arm
only."

**Flagged for follow-up (not a blocker for this report):** `derive_edges()`
itself should likely gain the same internal filter Hermes's
`Normalizer.normalize()` already has, so that any *direct* consumer of
`derive_edges()`'s raw output (not routed through this comparison harness)
doesn't unknowingly receive dangling edges. This is out of scope for
`08-03`'s declared `files_modified`, and is recorded here as a scoped
follow-up rather than silently fixed inline.

---

## Summary for the D-09 architecture gate

For the one shared network-topology blast-radius scenario measured here:

- **Correctness**: identical impacted sets from the same root — **parity**.
- **Evidence links**: identical (both fully populated) — **parity**.
- **Authorization/scope**: identical (no violations in either arm) —
  **parity**.
- **Latency**: Fabric-native (`derive_edges()`) is measurably faster in this
  single-run measurement, because it only processes the network-shaped
  input it's given, whereas Hermes's `Normalizer.normalize()` always
  processes all ARG entity families it's designed to handle — **Fabric-native
  favored**, directionally.
- **Operational cost proxy**: equal by construction in this fixture-only
  harness (same input, no live billing signal available) — **inconclusive
  from this measurement alone**.
- **D-05 edge case**: a real behavioral divergence exists in the *raw* output
  of the two pipelines (Fabric's `derive_edges()` does not itself drop
  dangling edges the way Hermes's `Normalizer.normalize()` does), but is
  fully resolved at the harness level and does not represent a correctness
  gap once accounted for — flagged as a scoped follow-up for `derive_edges()`
  itself, not a viability blocker.

No dimension measured here shows Hermes providing correctness, evidence, or
authorization value the Fabric-native arm lacks for this scenario. The one
measured advantage Hermes retains in this report is none — Fabric-native
matched or exceeded it on every measured dimension for this bounded scenario.
This is a single shared scenario, not exhaustive coverage of every graph
shape Hermes's engine has historically handled (application/business-service
traversal via `get_impact_context()`'s app-centric branches was not
exercised here, since it has no Fabric-native equivalent yet built) — that
gap should be weighed explicitly at the D-09 gate rather than assumed away.
