# Phase 8: Resource Identity Plane - Research

**Researched:** 2026-08-27
**Domain:** Inventory/Hermes identity-plane inversion + Fabric-native graph/topology viability comparison
**Confidence:** MEDIUM (codebase findings HIGH; Fabric IQ / NSG flow-log external domain claims LOW — no web search tool was reachable this session, see Assumptions Log)

## Summary

Phase 8 has two distinct engineering problems that must not be conflated (D-12). First, a **mechanical migration**: Hermes's `queries.py` issues its own `resources`/`resource_containers` ARG queries and `normalize.py` re-derives 14+ entity types from them — this duplicates what inventory (Phase 7) now owns as `ResourceObservation`. The fix is for Hermes to stop querying ARG for identity and instead read from the inventory Fabric read port, while keeping its own genuinely graph-specific logic: relationship/edge derivation (`_add_edge`, `_normalize_network`) and the `SemanticEngine` traversal (`get_impact_context`, "blast radius"). Second, a **viability experiment**: build a real Fabric-native pipeline that reproduces this same edge-derivation logic directly against Fabric/OneLake, expose it through Fabric IQ ontology, and run one comparable blast-radius scenario against both Hermes and the Fabric pipeline to decide retain/reduce/remove.

The codebase evidence is unambiguous about scope: `_add_edge()` (normalize.py:768) and the `_normalize_network()` method (normalize.py:280-447) contain 100% deterministic, rule-based edge derivation (`belongsTo`, `contains`, `protectedBy`, `attachedTo`, `peersWith`, `hasRule`, `enforcesPolicy`, `resolvesFor`, `loadBalances`, etc.) — no ML, no learning, entirely reproducible as a KQL/Spark job over the same raw `properties` payloads inventory now owns losslessly (per Phase 7 D-08). This is squarely "bounded data-engineering logic" (D-11), not something intrinsically exclusive to Python/Hermes.

Critically, **no NSG flow-log or Traffic Analytics ingestion exists anywhere in the repo today** — `src/network/tightening.py` and `src/network/gaps.py` explicitly state flow logs are "not ingested" and findings are qualified accordingly. Directional network topology (D-11) is therefore new work for this phase, not a refactor of existing code, and needs its own data-source design (NSG rule tables — already flattened by `network_normalize.py` — joined with a **new** flow-log source).

The existing Fabric publication path (Phase 7, `src/intelligence/inventory/onelake_publication.py`, `src/storage/onelake_writer.py`) is a **Python client writing Delta tables directly to OneLake via the ADLS Gen2 filesystem API** (`adlfs`/`deltalake`), not a Fabric-hosted Spark notebook or Data Pipeline item. The Fabric-native pipeline this phase must build (D-04a, success criterion 7) is therefore new infrastructure: either (a) a genuine Fabric notebook/Spark job registered as a workspace item, or (b) a KQL/Eventhouse-based transform, or (c) an extension of the existing Python OneLake-writer pattern that additionally derives edges (closest to today's architecture, cheapest to build, but arguably not "Fabric-native" in the sense the roadmap's success criterion 7 wants — this is a discretion point the planner must resolve explicitly, not silently default).

**Primary recommendation:** Sequence Phase 8 as (1) inventory read-port migration for identity fields only [mechanical, low risk, characterization-test-gated per Phase 7 D-04 precedent], (2) a real Fabric-native edge-derivation pipeline that mirrors `_add_edge`/`_normalize_network` logic exactly (reuse the same predicate vocabulary, confidence values, and containment rules verbatim so the comparison is apples-to-apples), (3) one bounded blast-radius scenario run against both `SemanticEngine.get_impact_context()` and the Fabric IQ ontology/query surface, (4) an explicit operator-approved retain/reduce/remove decision gate (D-09) — do not let the plan silently assume an outcome.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Resource identity (enumeration, type, containment, raw properties, watermarks) | Database/Storage (Fabric/OneLake inventory tables) | API/Backend (inventory read port) | Phase 7 already made inventory the source of truth; Phase 8 only removes Hermes's parallel ARG read of the same data |
| Entity/edge derivation from ARG identity data | API/Backend (Hermes normalize.py, until D-09 gate) OR Database/Storage (Fabric Spark/KQL pipeline, comparison arm) | — | This is the exact thing under viability test — do not assign it a single tier prematurely |
| NSG+flow-log directional network topology | Database/Storage (new Fabric pipeline joining NSG rule table + flow-log/Traffic Analytics table) | — | Never built by Hermes today; D-11 explicitly scopes this as new bounded data-engineering work, default-owned by Fabric regardless of the Hermes gate outcome (D-12) |
| Bounded blast-radius traversal / semantic query | API/Backend (`SemanticEngine`) OR Fabric IQ ontology traversal (comparison arm) | — | Also under viability test; do not presume Hermes retains this |
| Assessment domains (patch, vuln, policy, advisor, metric, health) | API/Backend (existing domain services) | Database/Storage (Fabric tables, unchanged) | Explicitly out of scope (D-12 project-level, INV-12) — never touch |
| Agent-safe context packaging / `ContextQueryService` | API/Backend (`agent_queries.py`) | — | Phase 9 territory for API rewiring, but Phase 8 must decide whether this class's identity reads (VirtualMachine/ArcServer) move to the read port now or wait |

## User Constraints

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Hermes viability gate**
- **D-01:** Keeping Hermes requires demonstrated unique graph value in at least one end-to-end operator workflow, not merely a technically unique implementation.
- **D-02:** The minimum proof workflow is bounded blast-radius analysis from a changed or unhealthy resource.
- **D-03:** The proof must measure bounded relationship/topology inference, blast-radius traversal, provenance/confidence, and agent-safe context packaging against Fabric IQ plus the API.
- **D-04:** Use the same curated Fabric snapshot and representative operator scenarios for repeatable comparison, measuring correctness, evidence links, authorization, latency, and operational cost. An optional live smoke test may follow.
- **D-04a:** The comparison arm is not hypothetical — build a real Fabric-native pipeline (Spark/KQL notebook or DataPipeline) that reproduces Hermes's current relationship/topology construction (entity/edge derivation from ARG identity data, plus NSG+flow-log-derived network topology per D-11) directly against the Fabric lakehouse, and expose it through Fabric IQ ontology. Run the same blast-radius scenarios against this pipeline's output as against Hermes.
- **D-05:** Unknown, stale, conflicting, or unauthorized edges must remain explicit; unsupported certainty is a failed result.

**Hermes reduction or removal**
- **D-06:** If Hermes passes only partially, retain only a small graph library/service for dependency inference and bounded traversal. Remove source acquisition, normalization ownership, inventory publication, and "discovery agent" branding.
- **D-07:** Preserve compatible semantic/query read contracts during migration while changing their backing source to Fabric/API; remove APIs that have no unique consumer after the comparison.
- **D-08:** Before deleting Hermes responsibilities, no direct ARG/LAW reads or duplicate inventory publication may remain. Contract tests and one end-to-end proof must pass first.
- **D-09:** The final retain/reduce/delete decision is an architecture gate requiring operator approval after the reproducible comparison report.

**Network topology derivation**
- **D-10:** Fabric IQ's ontology generation promotes existing Power BI semantic model entities/relationships; it does not infer new entity types or relationships by analyzing raw data (e.g., NSG rules, flow logs). It hosts and traverses topology once defined, but does not derive it.
- **D-11:** Directional network topology (source/dest/port/protocol, allowed vs. observed) is computable today from NSG rule tables joined with flow log/Traffic Analytics data. This is bounded data-engineering logic, not AI/self-learning discovery, and is not exclusive to Hermes — it can run as a Fabric pipeline/notebook that writes a topology-edges table for Fabric IQ ontology to expose.
- **D-12:** The Hermes viability proof (D-01 through D-05) must treat "who derives network topology edges" as a separate, bounded engineering question from "does Hermes provide unique graph value." A Fabric-native topology pipeline is an explicit fallback/default if Hermes does not clear the viability gate.

### the agent's Discretion
- Exact comparison harness, scenario fixture shape, graph-library module boundaries, and migration sequencing are open to research and planning, provided they satisfy the locked viability and safety decisions above.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within Phase 8 scope.
</user_constraints>

## Phase Requirements

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|--------------|-------------------|
| INV-07 | Inventory is an independent domain owning acquisition, normalization, retention, source status, Fabric/OneLake publication | Already delivered by Phase 7; Phase 8 only needs to confirm Hermes stops duplicating the ARG `resources`/`resource_containers` reads that `queries.py` still issues |
| INV-08 | Platform represents every observed Azure resource family through a common scope-enforced contract preserving per-family identity/placement/SKU/tier/runtime/provenance | Constrains what `ResourceObservation` must expose to Hermes's normalizers — see §Code Examples for the exact `properties` access patterns Hermes needs |
| INV-10 | Other subsystems, including the semantic graph, consume inventory exclusively through one scope-enforced Fabric-backed inventory contract | Directly names Hermes/semantic graph as the consumer this phase must repoint — `queries.py` "resources"/"resource_containers" specs and `normalize.py`'s container-mapping loop (lines 90-114) are what must be replaced by reads from the inventory read port |
| INV-11 | Inventory owns resource identity plane — enumeration, type, placement, tags, containment hierarchy, raw provider properties, per-family watermarks — losslessly enough that graph construction/relationship modelling/semantic traversal need no separate resource acquisition path | This is the phase's core test: does `ResourceObservation.properties` (Phase 7 D-08) actually carry everything `_normalize_network()` and `normalize.py`'s entity builders read? See §Common Pitfalls — Pitfall 1 |
| INV-12 | Inventory bounded to resource identity; does not absorb patch/vulnerability/policy/advisor/metric/health assessments | Confirms scope fence — `_add_edge()`'s `assessedBy`/`impacts` edges (patch, advisor) stay assessment-domain joins by `resource_id`, not inventory-owned fields |
</phase_requirements>

## Package Legitimacy Audit

No new external packages are required for the mechanical inventory-read-port migration. The Fabric-native pipeline arm has two candidate paths with different package implications:

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `deltalake` | PyPI | already in `pyproject.toml` (`>=1.0,<2`) | — | delta-io/delta-rs | OK (already vetted) | Reuse — no new install |
| `adlfs` | PyPI | already in `pyproject.toml` (`>=2024.7,<2025`) | — | fsspec/adlfs | OK (already vetted) | Reuse — no new install |
| `azure-kusto-data` | PyPI | not currently a dependency | unverified this session | Azure/azure-kusto-python | `[ASSUMED]` — not checked via registry this session | **Only required if the planner chooses KQL graph-match/make-graph as the traversal engine (see Open Question 3).** If chosen, gate the install behind `checkpoint:human-verify` and run `pip index versions azure-kusto-data` before use. |

**Packages removed due to [SLOP] verdict:** none — no new packages recommended without gating.
**Packages flagged as suspicious [SUS]:** none.

*`azure-kusto-data` is tagged `[ASSUMED]` — the planner must add a `checkpoint:human-verify` task before installing it, and must run `pip index versions azure-kusto-data` to confirm it is current before use.*

## Architecture Patterns

### System Architecture Diagram (current state → target)

```
CURRENT (pre-Phase-8):
  ARG (Resources, ResourceContainers)  ──┐
                                          ├──> Hermes queries.py (QueryCatalog.build)
  ARG (network_* specs, identity_*)  ──┘         │
                                                  v
                                          Hermes normalize.py (Normalizer.normalize)
                                            ├── entity rows (14+ ENTITY_TYPES)
                                            └── edge rows (_add_edge / _normalize_network)
                                                  │
                                                  v
                                          NormalizedGraph ──> DatasetStore.publish ──> entities/*.jsonl
                                                  │                                        │
                                                  v                                        v
                                          SemanticEngine (bounded traversal)     ContextQueryService (agent_queries.py)

  [separately, Phase 7]:
  ARG (Resources, ResourceContainers) ──> intelligence/inventory/* ──> Fabric/OneLake Delta tables (inventory_*)

TARGET (post-Phase-8, mechanical migration only):
  Fabric/OneLake inventory_resource_observations (identity, containment, raw properties, watermarks)
                │
                v
  Inventory read port (scope-enforced)
                │
                v
  Hermes edge-derivation logic (same _add_edge/_normalize_network rules, reading from read port instead of ARG)
                │
                v
  NormalizedGraph (entities minus duplicated identity fields, relationships unchanged) ──> SemanticEngine

TARGET (comparison arm, D-04a):
  Fabric/OneLake inventory tables + new NSG-rule/flow-log tables
                │
                v
  Fabric-native Spark/KQL pipeline (mirrors _add_edge/_normalize_network predicate vocabulary exactly)
                │
                v
  Delta table(s): topology_entities, topology_edges
                │
                v
  Fabric IQ ontology binding (entities + typed relationships)
                │
                v
  Blast-radius query via Fabric IQ traversal API or KQL graph-match — run against the SAME scenario as SemanticEngine.get_impact_context()
```

### Recommended Project Structure

```
src/
├── intelligence/inventory/           # Phase 7 — read port lives here; extend for Hermes-facing reads
│   ├── fabric_contracts.py           # existing — add any new identity-plane fields Hermes needs
│   └── read_port.py                 # NEW (or wherever D-17's port lands) — scope-enforced reads
├── hermes_arg_connector/
│   ├── queries.py                    # REMOVE "resources"/"resource_containers" specs (D-08); keep network_*/identity_* if still needed for edge derivation inputs not yet in inventory
│   ├── normalize.py                  # KEEP _add_edge, _normalize_network, edge logic; REPLACE entity-row construction for identity types with reads from inventory read port
│   ├── network_normalize.py          # KEEP wholesale — this is graph-specific value (D-01), the exact logic the Fabric pipeline must mirror
│   └── agent_queries.py              # Phase 9 territory, but flag identity reads (entities/VirtualMachine, entities/ArcServer) for eventual read-port migration
├── fabric_pipelines/                 # NEW — the D-04a comparison-arm pipeline
│   ├── topology_pipeline.{py,ipynb}  # mirrors _add_edge/_normalize_network predicate vocabulary
│   ├── flowlog_ingest.py             # NEW — NSG rule + flow-log/Traffic Analytics join (no prior art in repo)
│   └── ontology_binding.py           # registers topology_entities/topology_edges as Fabric IQ ontology objects
└── semantic/
    └── semantic_engine.py            # UNCHANGED unless D-06 reduction triggers module trimming
```

### Pattern 1: Deterministic edge derivation (existing, to be mirrored not rewritten)

**What:** `_add_edge()` builds a content-addressed relationship row (`sha256(subject|predicate|object|source)` truncated to 24 hex chars as `relationshipId`) with explicit `confidence`, `source`, timestamps, and `assertionState`.
**When to use:** Any new edge type the Fabric pipeline derives must use this exact id-derivation and field shape so a like-for-like comparison is possible.
**Example:**
```python
# Source: src/hermes_arg_connector/normalize.py:768-783 (read this session)
def _add_edge(index: dict[str, dict], subject: str, predicate: str, obj: str, source: str, observed: str, confidence: float) -> None:
    if not subject or not obj:
        return
    digest = hashlib.sha256(f"{subject}|{predicate}|{obj}|{source}".encode()).hexdigest()[:24]
    index[digest] = {
        "relationshipId": digest,
        "subjectId": subject,
        "predicate": predicate,
        "objectId": obj,
        "confidence": confidence,
        "source": source,
        "createdTimestamp": observed,
        "lastObservedTimestamp": observed,
        "assertionState": "accepted",
        "schemaVersion": "1.0.0",
    }
```

### Pattern 2: Predicate vocabulary the Fabric pipeline must reproduce for a fair comparison

**Verbatim, read from `src/hermes_arg_connector/normalize.py:301-447` this session:**
```python
# containment (line 301-304)
def containment(row: dict, entity: dict) -> None:
    parent = _resource_group_key(row) or _subscription_key(row)
    link(entity["id"], "belongsTo", parent)

# VNet -> subnet (line 313-321)
link(vnet["id"], "contains", subnet["id"])
if subnet.get("nsgId"):
    link(subnet["id"], "protectedBy", subnet["nsgId"], 0.99)
if subnet.get("routeTableId"):
    link(subnet["id"], "routedBy", subnet["routeTableId"], 0.99)
if subnet.get("natGatewayId"):
    link(subnet["id"], "egressesVia", subnet["natGatewayId"], 0.99)

# VNet peering (line 322-326)
link(vnet["id"], "hasPeering", peering["id"])
if peering.get("remoteVnetId"):
    link(peering["id"], "peersWith", peering["remoteVnetId"], 0.99)

# NSG -> rule (line 335-337)
link(nsg["id"], "hasRule", rule["id"])

# NIC (line 357-362)
if nic.get("subnetId"):
    link(nic["id"], "attachedTo", nic["subnetId"], 0.99)
if nic.get("nsgId"):
    link(nic["id"], "protectedBy", nic["nsgId"], 0.99)
if nic.get("attachedResourceId"):
    link(nic["attachedResourceId"], "hasNetworkInterface", nic["id"], 0.99)

# Firewall (line 371-374)
if firewall.get("subnetId"):
    link(firewall["id"], "attachedTo", firewall["subnetId"], 0.99)
if firewall.get("policyId"):
    link(firewall["id"], "enforcesPolicy", firewall["policyId"], 0.99)

# Firewall policy -> collection -> rule (line 386-389)
link(collection["policyId"], "hasRuleCollection", collection["id"], 0.99)
link(rule["collectionId"], "hasRule", rule["id"])

# Private endpoint (line 398-401)
if endpoint.get("subnetId"):
    link(endpoint["id"], "attachedTo", endpoint["subnetId"], 0.99)
if endpoint.get("targetResourceId"):
    link(endpoint["id"], "exposesPrivately", endpoint["targetResourceId"], 0.98)

# Private DNS zone -> vnet (line 417-421)
link(zone_id, "resolvesFor", vnet_id, 0.98)

# Gateway (line 432-435)
if gateway.get("subnetId"):
    link(gateway["id"], "attachedTo", gateway["subnetId"], 0.99)
elif gateway.get("vnetId"):
    link(gateway["id"], "attachedTo", gateway["vnetId"], 0.95)

# Load balancer (line 444-447)
if balancer.get("subnetId"):
    link(balancer["id"], "attachedTo", balancer["subnetId"], 0.99)
for backend in balancer.get("backendResourceIds", []):
    link(balancer["id"], "loadBalances", backend, 0.9)
```
`[VERIFIED: src/hermes_arg_connector/normalize.py:301-447]` — every predicate string, confidence value, and containment rule above is copied verbatim from the read file; nothing paraphrased.

### Pattern 3: NSG rule row shape already flattened by Hermes (needed as the join-left side for D-11)

`[VERIFIED: src/hermes_arg_connector/network_normalize.py:198-251]`, quoted verbatim:
```python
rules.append(
    {
        **_child_base(base, "NetworkSecurityRule", rule_id, rule.get("name")),
        "nsgId": nsg_id,
        "priority": int(rule_props.get("priority") or 0),
        "direction": _text(rule_props.get("direction")) or "Inbound",
        "access": _text(rule_props.get("access")) or "Allow",
        "protocol": _text(rule_props.get("protocol")) or "*",
        "sourceAddress": ",".join(source_addresses),
        "destinationAddress": ",".join(dest_addresses),
        "sourcePort": ",".join(source_ports),
        "destinationPort": ",".join(dest_ports),
        "description": _text(rule_props.get("description")),
        "isDefault": is_default,
        "properties": rule_props,
    }
)
```
This is the deterministic-side data the Fabric pipeline joins against flow-log records for D-11's "allowed vs. observed" comparison. The `isDefault` flag matters: Azure's implicit `DenyAllInBound`/`AllowVNetInBound` default rules are retained here and must be retained in the Fabric-native reproduction too, or the two topology outputs will disagree on baseline deny behavior.

### Anti-Patterns to Avoid
- **Re-deriving entity identity fields (location, tags, SKU, provisioning state) inside the Fabric topology pipeline.** Those come from inventory's `ResourceObservation`; the topology pipeline should join to inventory by `resource_id`, not re-query ARG (this repeats the exact anti-pattern INV-10 targets, just moved to a new pipeline).
- **Building the comparison harness against different scenario fixtures for Hermes vs. Fabric IQ.** D-04 requires the *same* curated snapshot; a harness that generates fixtures independently per arm is not a valid comparison.
- **Letting Fabric IQ ontology generation "infer" relationships.** D-10 is explicit: Fabric IQ promotes existing semantic-model relationships, it does not derive new ones from raw NSG/flow-log data. The derivation must happen in the pipeline *before* ontology binding, not be delegated to Fabric IQ itself.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Content-addressed relationship IDs | A new hashing scheme for the Fabric pipeline's edge IDs | Reuse `sha256(subject|predicate|object|source)[:24]` exactly (Pattern 1) | Any deviation makes edge-level diffing between the two arms impossible, defeating D-04's "same scenario" comparison requirement |
| Delta table writes to OneLake | A bespoke HTTP/REST writer against the OneLake DFS API | `storage.delta_writer.DeltaWriter` + `storage.onelake_writer.OneLakeWriter` (already exist, already used by Phase 7's `InventoryOneLakePublisher`) | This machinery already handles Delta write modes, key columns, schema, and lease-based locking (`storage.locking.RunLock`) — a new writer would re-introduce risk Phase 7 already retired |
| Bounded/limited-depth graph traversal accounting | A new truncation/budget tracker for the Fabric IQ comparison arm | Reuse the `max_traversal_nodes`/`max_traversal_depth`/`truncated` pattern already in `SemanticEngine` (lines 63-79, 397-463) as the yardstick the Fabric arm's traversal must be measured against | D-04 requires measuring "correctness, evidence links, authorization, latency, and operational cost" on comparable terms; inventing a different truncation semantics for the Fabric side breaks comparability |

**Key insight:** Because this phase is fundamentally a controlled comparison (D-04), the biggest hand-rolling risk is building two arms that are subtly incomparable — different predicate names, different confidence semantics, different truncation rules. Treat `normalize.py`/`network_normalize.py` as the literal spec for the Fabric pipeline's output shape, not just inspiration.

## Runtime State Inventory

This phase is not a rename/refactor, but it moves a real data-acquisition path (Hermes's ARG queries for identity) and stands up new infrastructure (Fabric topology pipeline, potentially a new flow-log source). Applying the inventory as a discipline check:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `NormalizedGraph`/`DatasetStore` published entity rows for identity types (`entities/Resource`, `entities/VirtualMachine`, etc.) are regenerated each run from `Normalizer.normalize()`, not incrementally patched (`07-CONTEXT.md`: "inventory created/observed timestamps are regenerated per run" — same non-preservation behavior applies to Hermes's own entity rows per `service.py`). No historical row needs migration. | None |
| Live service config | None found — no NSG Flow Logs, VNet Flow Logs, or Traffic Analytics diagnostic settings are referenced anywhere in the repo (`grep` for "flow log"/"NetworkWatcher"/"TrafficAnalytics" returns only the two files that explicitly say this data is *not* ingested). Enabling flow logs is an Azure-side configuration action (diagnostic settings on NSGs / Network Watcher), out-of-repo, and is new infrastructure this phase must provision, not migrate. | Provision NSG Flow Logs v2 + Traffic Analytics workspace binding as a new task (with `checkpoint:human-verify` — this is a billable Azure resource with retention/cost implications) |
| OS-registered state | None applicable — no OS-level task scheduler/pm2/systemd state ties to this phase's rename/refactor scope | None |
| Secrets/env vars | Existing Fabric workspace/lakehouse IDs (`fabric.config.yaml`: `workspace_id: 1c328da7-2490-48dc-9ba6-de8c1f333756`, `lakehouse_id: aef9854d-ab23-413e-a86d-99a344a269c0`) `[VERIFIED: fabric.config.yaml:26-29]` are reused, not renamed. If a new Fabric IQ ontology item or a new lakehouse/table for topology data is created, its identifiers must be added to `fabric.config.yaml` following the existing pattern — not hardcoded in the pipeline. | Extend `fabric.config.yaml` schema for new topology table/ontology item IDs |
| Build artifacts | None found tied to this phase specifically | None |

## Common Pitfalls

### Pitfall 1: Assuming `ResourceObservation.properties` already carries everything `_normalize_network()` reads
**What goes wrong:** Phase 7's D-08 states the raw `properties` bag must be preserved losslessly, but this phase is the first to actually *exercise* that claim against Hermes's real 4-level-deep nested access patterns (`subnet_props.get("delegations")` → `item.get("properties").get("serviceName")`, confirmed at `network_normalize.py:156-161`, referenced in `07-CONTEXT.md` as the exact conflict that overrode the original flattened-attributes design).
**Why it happens:** Inventory's `ResourceObservation` was designed and characterized in Phase 7 against inventory's own read patterns (VM/software), not against Hermes's network-normalization read patterns, because Hermes wasn't yet reading from it.
**How to avoid:** Before writing the migration plan, run `_normalize_network()` against a raw payload sourced from the actual `ResourceObservation.properties` field (not the current direct-ARG payload) and diff the output against today's output. Byte-identical output is the acceptance bar, not "looks similar."
**Warning signs:** Any `KeyError`/`AttributeError` inside `network_normalize.py`'s nested `.get()` chains when fed inventory-sourced payloads; any subnet/rule row missing `delegations`, `serviceEndpoints`, or raw nested `properties`.

### Pitfall 2: Building the Fabric topology pipeline against Fabric IQ's inference expectations instead of D-10's explicit boundary
**What goes wrong:** A planner unfamiliar with D-10 might expect Fabric IQ to "figure out" relationships from raw NSG/resource tables once they're in the lakehouse. It does not — Fabric IQ ontology generation promotes existing Power BI semantic-model relationships; it is a hosting/traversal layer, not an inference engine (D-10, locked decision).
**Why it happens:** "Ontology" sounds like it implies automatic relationship discovery.
**How to avoid:** The edge-derivation step (mirroring `_add_edge`) must run and materialize a `topology_edges` Delta table *before* any Fabric IQ binding step. Fabric IQ's job is only to expose that already-derived table's entities/relationships as typed ontology objects.
**Warning signs:** A plan step that says "configure Fabric IQ to detect NSG relationships" rather than "write topology_edges, then bind it."

### Pitfall 3: Comparing Hermes and the Fabric pipeline on different scenario fixtures
**What goes wrong:** If the comparison scenario for Hermes reuses `tests/semantic_scenario.py`'s existing synthetic fixture (`vm-identity`, `Identity`/`Payments` applications, per `tests/test_impact_analysis.py:11-24` — `[VERIFIED: tests/test_impact_analysis.py:8-24]`) while the Fabric arm is tested against a different curated snapshot, the D-04 comparison is invalid by construction.
**Why it happens:** Existing test fixtures are convenient and already wired into `SemanticEngine.from_rows()`; standing up an equivalent Fabric lakehouse snapshot is more work, tempting a planner to take a shortcut on one side only.
**How to avoid:** Define one curated snapshot (a fixed set of VNets/NSGs/subnets/NICs/rules with a known expected blast radius) and materialize it into *both* the Hermes-consumable shape (JSONL entities/edges, feedable to `SemanticEngine.from_rows()`) and the Fabric-consumable shape (Delta tables in the lakehouse). Golden-value the expected blast-radius result once, then assert both arms against it.
**Warning signs:** Any PLAN.md task that stands up fixtures for one arm without a corresponding equivalent-shape fixture for the other arm.

### Pitfall 4: Removing Hermes's `queries.py` "resources"/"resource_containers" specs before the read-port migration is proven equivalent
**What goes wrong:** D-08 requires "no direct ARG/LAW reads... may remain" only *after* contract tests and one end-to-end proof pass. Deleting the ARG query specs first, then discovering `ResourceObservation` is missing a field Hermes needs, leaves Hermes broken with no fallback.
**Why it happens:** Removing dead-looking code feels like "cleanup" and is often done eagerly in the same task as adding the replacement read.
**How to avoid:** Sequence as: add read-port consumption alongside existing ARG reads → characterization-test that both paths produce identical `NormalizedGraph` output → only then remove the ARG query specs (mirrors Phase 7's own D-19 characterize→extract→invert→expand sequencing, which this phase should follow by precedent).
**Warning signs:** A single task that both "add inventory read port consumption" and "remove ARG identity queries" in the same commit with no equivalence test in between.

## Code Examples

### Existing `_normalize_network` entry point (the logic to mirror in Fabric)
```python
# Source: src/hermes_arg_connector/normalize.py:280-305 (read this session)
def _normalize_network(
    self,
    payload: dict[str, list[dict]],
    observed: str,
    entity_index: dict[str, dict[str, dict]],
    edge_index: dict[str, dict],
) -> None:
    """Flattens network payloads into entities plus topology edges.

    Sub-resources (subnets, rules, routes, peerings) become first-class
    entities because ``_add_edge`` drops any edge whose endpoints are not
    emitted, and topology analysis needs to address them individually.
    """
    source = "arg:Resources"

    def record(entity_type: str, entity: dict) -> None:
        entity_index[entity_type][entity["id"]] = entity

    def link(subject: str, predicate: str, obj: str, confidence: float = 1.0) -> None:
        _add_edge(edge_index, subject, predicate, obj, source, observed, confidence)

    def containment(row: dict, entity: dict) -> None:
        """Anchors an entity to its resource group / subscription."""
        parent = _resource_group_key(row) or _subscription_key(row)
        link(entity["id"], "belongsTo", parent)
```

### Existing blast-radius entry point (the scenario the comparison must reproduce)
```python
# Source: src/semantic/semantic_engine.py:344-490 (read this session; method is get_impact_context)
result = {
    "root": self.indexes.public(root_id),
    "cause_type": cause_type,
    "impacted_applications": application_rows,
    "impacted_business_services": business_rows,
    "impacted_services": service_rows,
    "blast_radius": {
        "resource_count": len(resources),
        "application_count": max(len(discovered_applications), len(applications)),
        "business_service_count": len(business_services),
        "service_count": len(services),
    },
    "tree": tree,
    "collection_metadata": collection_metadata,
    "truncated": truncated,
    "freshness": self.freshness,
    "knowledge_version": self.knowledge_version,
}
```
`[VERIFIED: src/semantic/semantic_engine.py:464-483]` — this exact response shape (root/cause_type/impacted_*/blast_radius/tree/truncated/freshness/knowledge_version) is what the Fabric IQ comparison output must be mapped to (or explicitly diffed against) for D-03's "measure... blast-radius traversal" requirement to be checkable.

### Existing Fabric OneLake write pattern to reuse for the topology pipeline's output tables
```python
# Source: src/intelligence/inventory/onelake_publication.py:29-46 (read this session)
def publish_table(
    self,
    contract: InventoryFabricContract,
    rows: Sequence[Mapping[str, Any]],
) -> InventoryTableWrite:
    table_uri = self.onelake.table_uri("inventory", contract.table_name.removeprefix("inventory_"))
    result = self.delta_writer.write(
        table_uri,
        [_fabric_row(contract, row) for row in rows],
        mode=DeltaWriteMode.OVERWRITE,
        key_columns=contract.identity_fields,
        schema=contract.schema,
        required_columns=contract.required_fields,
    )
    return InventoryTableWrite(
        table_name=contract.table_name,
        table_uri=table_uri,
        result=result,
    )
```
The topology pipeline's `topology_entities`/`topology_edges` tables should follow this identical contract → write → result pattern (new `TopologyFabricContract` dataclasses mirroring `InventoryFabricContract`), not a new writer abstraction.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hermes queries ARG directly for `Resources`/`ResourceContainers` (`queries.py` lines 39-49) | Inventory owns identity acquisition via Fabric/OneLake (Phase 7, `intelligence/inventory/*`) | Phase 7, 2026-08-26 | This phase (8) is the consumer-side half of that pivot — Hermes must stop being a second acquisition path for the same data |
| Original Phase 7 draft: `attributes: dict[str, str]` flattened identity contract (`07-RESEARCH.md` §3.2) | `properties` opaque lossless passthrough (D-08, Phase 7 CONTEXT) | Phase 7, 2026-08-26, superseded mid-phase after §7.3 finding | Directly unblocks this phase — a flattened contract would have made the Hermes pivot impossible per Phase 7's own conflict note |
| No flow-log/Traffic Analytics ingestion anywhere in repo | (this phase, if D-11 pursued) new NSG-rule + flow-log join pipeline | Not yet built — greenfield in Phase 8 | `src/network/tightening.py`/`gaps.py` currently qualify every finding with "flow logs are not ingested"; those disclaimers should be revisited (not necessarily removed) once the Fabric pipeline exists, since `tightening.py`/`gaps.py` are separate modules Phase 8 does not own but should be aware may want updated caveats later |

**Deprecated/outdated:**
- Hermes's "discovery agent" framing (branding only) — explicitly disallowed to survive past this phase unless D-01 is cleared (D-06).

## Assumptions Log

> Everything below is `[ASSUMED]` because no external web-search or documentation-retrieval tool (WebSearch/Context7/Brave seam) was reachable in this session — the `gsd-tools.cjs` shim could not be located on this environment and no MCP web tool was available. All external-domain claims (Fabric IQ, NSG Flow Logs schema, KQL graph operators) rely on training-data knowledge and MUST be verified against Microsoft Learn before the plan locks any Fabric IQ binding steps or flow-log schema field names.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Fabric IQ ontology binding is configured via a workspace ontology item that maps Delta table columns to entity/relationship types, roughly analogous to Power BI semantic model relationship definitions, and does not itself run inference over raw data (this matches locked decision D-10, which the user/operator already confirmed via CONTEXT.md — but the *mechanism* — API shape, config format — is training-data only, not fetched this session) | Architecture Patterns, Common Pitfalls #2 | If the actual Fabric IQ binding API differs materially (e.g., requires a specific manifest schema, has undocumented entity-count limits, or requires the source table to already be a "Gold" layer table with specific naming), the pipeline task breakdown will need rework mid-execution |
| A2 | Azure NSG Flow Logs v2 (or VNet Flow Logs) written to a storage account, optionally piped through Traffic Analytics into Log Analytics tables (commonly `AzureNetworkAnalytics_CL` or newer schema tables), carries source/dest IP, port, protocol, and allow/deny decision fields sufficient to join against the NSG rule rows already flattened by `network_normalize.py` | Summary, Pattern 3, Runtime State Inventory | If the actual current flow-log schema (Microsoft has iterated this — v1 vs v2, and Traffic Analytics vs. raw NSG Flow Logs vs. VNet Flow Logs are genuinely different products with different schemas) doesn't map cleanly to `sourceAddress`/`destinationAddress`/`protocol`/`destinationPort` as flattened here, the join logic needs redesign |
| A3 | KQL's `make-graph`/`graph-match` operators exist in Kusto/ADX and could serve as a traversal engine alternative to Fabric IQ's own traversal API, and/or that `azure-kusto-data` would be the Python client if this path is chosen | Package Legitimacy Audit, Open Question 3 | If these operators require a specific Kusto/ADX cluster tier not available in the project's Fabric capacity, or the operators have moved/renamed, the "concrete technical approach" recommendation in Open Question 3 is wrong and needs re-derivation |
| A4 | The existing OneLake Python-client write pattern (`DeltaWriter`/`OneLakeWriter`) is NOT what the roadmap's success criterion 7 means by "Fabric-native Spark/KQL pipeline" — i.e., that criterion implies an actual Fabric workspace item (notebook/pipeline), not just another Python script writing Delta files | Summary, Architecture Patterns | If the operator actually considers the existing Python-writer pattern sufficiently "Fabric-native" (since it does write real Delta tables Fabric can read), this assumption over-scopes the phase; the planner should raise this as an explicit question before committing to building a Spark notebook |

**If this table is empty:** N/A — table is populated; see above.

## Open Questions

1. **Does "Fabric-native Spark/KQL pipeline" (roadmap success criterion 7, D-04a) require an actual Fabric workspace notebook/pipeline item, or does extending the existing Python `DeltaWriter`/`OneLakeWriter` pattern (already proven in Phase 7) satisfy the intent?**
   - What we know: The existing pipeline writes real Delta tables to OneLake from a Python client outside Fabric's own compute (no notebook, no Spark session, no Fabric Data Pipeline item observed in the repo).
   - What's unclear: Whether the operator's intent behind "the gate must be decided from an actual working Fabric pipeline, not a documentation-based estimate" (ROADMAP.md §Phase 8) requires genuine Fabric-hosted compute (Spark notebook or KQL database) as opposed to any code path that lands correct Delta tables Fabric IQ can bind to.
   - Recommendation: Raise this explicitly in `/gsd-discuss-phase` follow-up or flag as a planning decision point — building a real Fabric notebook is materially more infrastructure work (workspace item creation via Fabric REST API, notebook content authoring, Spark session config) than extending the existing Python writer. Do not let the planner silently pick the cheaper option without operator visibility, given D-04a's explicit "not hypothetical" language.

2. **What is the actual current schema of NSG Flow Logs v2 / VNet Flow Logs / Traffic Analytics tables in this specific Azure environment?**
   - What we know: The repo has zero flow-log ingestion; D-11 names "NSG rule tables joined with flow log/Traffic Analytics data" as the source.
   - What's unclear: Whether Traffic Analytics is (or will be) enabled on the target Log Analytics workspace, what table name/schema it actually produces (Microsoft has multiple generations of this product), and whether raw NSG Flow Logs JSON (in a storage account, ungoverned by Traffic Analytics) is a simpler source to ingest directly via a Fabric shortcut/pipeline instead.
   - Recommendation: This needs a live-environment check (does the target subscription have Network Watcher + flow logs already enabled anywhere?) before the planner commits to a specific schema in task descriptions — treat as a Wave 0 discovery task, not an assumption to plan around blind.

3. **What Fabric-native mechanism actually executes the blast-radius traversal query against the Fabric IQ-bound topology data — Fabric IQ's own query surface, KQL `graph-match`/`make-graph` against an Eventhouse/KQL database, or a Gremlin/Cosmos DB graph (not currently used anywhere in this repo)?**
   - What we know: No Cosmos DB Gremlin usage exists in the repo (not searched for directly this session but no signal of it in dependencies or fabric config). `pyproject.toml` has no `azure-kusto-data` dependency, meaning no KQL client is wired up today.
   - What's unclear: Which of these three paths Fabric IQ's own documented traversal capability actually supports out of the box versus what requires standing up a parallel KQL/Eventhouse item.
   - Recommendation: This is squarely a "verify against Microsoft Learn Fabric IQ docs" item the planner must resolve with live documentation lookup before locking a specific technical approach — do not let the plan default to KQL graph-match without confirming Fabric IQ doesn't already expose an equivalent traversal API natively.
   - **(DEFERRED TO CHECKPOINT: 08-02 decision checkpoint "Traversal mechanism for Fabric IQ-bound topology data", placed before Task 2/`ontology_binding.py`)** — no external documentation-retrieval tool was reachable this session (see Assumptions Log preamble), so this cannot be silently resolved by the planner; the operator picks the traversal mechanism explicitly at execution time, with an instruction in the checkpoint to check current Microsoft Learn Fabric IQ docs first if tooling is available then.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Fabric workspace + lakehouse (`operational_context_graph`) | Both arms (identity read port, topology pipeline output) | ✓ (per STATE.md: workspace `1c328da7-2490-48dc-9ba6-de8c1f333756`, lakehouse `aef9854d-ab23-413e-a86d-99a344a269c0` already deployed) | — | — |
| Fabric IQ ontology feature | Comparison arm ontology binding | Not verified this session — requires live Fabric tenant check | — | If unavailable in this Fabric capacity/region, comparison arm cannot be built as specified; escalate to operator before continuing |
| NSG Flow Logs / Traffic Analytics on target subscriptions | D-11 topology derivation | ✗ — confirmed absent (no ingestion code, no config reference found) | — | Must be provisioned (Azure-side, billable, needs `checkpoint:human-verify`); no code fallback exists — this is genuinely new infrastructure |
| `azure-kusto-data` (if KQL graph path chosen) | Open Question 3, conditionally | ✗ — not in `pyproject.toml` | — | Only needed if planner selects the KQL graph-match traversal path over Fabric IQ's native query surface |
| `deltalake`, `adlfs`, `pyarrow` | Both arms' Delta table writes | ✓ (in `pyproject.toml`) | deltalake>=1.0,<2; adlfs>=2024.7,<2025; pyarrow>=23.0.1,<24 | — |

**Missing dependencies with no fallback:**
- NSG Flow Logs / Traffic Analytics data source — must be provisioned before D-11 topology derivation can be tested against real data (a curated/synthetic fixture can unblock development, but the roadmap's "actual working Fabric pipeline" language implies eventual real-data validation).

**Missing dependencies with fallback:**
- Fabric IQ ontology feature availability — if unavailable, the comparison arm can still demonstrate the topology_edges Delta table + a manual/KQL query as a partial proxy, but this should be flagged to the operator as a scope reduction, not silently substituted.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest `[VERIFIED: pyproject.toml:37-39]` — `[tool.pytest.ini_options] testpaths = ["tests"] addopts = "-q"` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]` section) |
| Quick run command | `pytest tests/test_impact_analysis.py tests/test_agent_queries.py -x` |
| Full suite command | `pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INV-10/INV-11 | Hermes reads identity via inventory read port, not direct ARG | characterization/contract | `pytest tests/inventory_harness.py -x` (existing harness, extend for Hermes-side reads) | ✅ existing harness, ❌ Hermes-read-port assertions — Wave 0 |
| INV-11 | `network_normalize.py` produces byte-identical output fed from `ResourceObservation.properties` vs. today's direct ARG payload | characterization (new) | `pytest tests/test_network_normalize_from_inventory.py -x` | ❌ Wave 0 |
| D-01/D-02/D-03 | Bounded blast-radius scenario produces comparable result from `SemanticEngine.get_impact_context()` and Fabric IQ query surface | integration/comparison harness | `pytest tests/test_hermes_fabric_comparison.py -x` | ❌ Wave 0 |
| D-05 | Unknown/stale/conflicting/unauthorized edges remain explicit in both arms (no silently-dropped uncertainty) | unit | Extend `tests/test_impact_analysis.py` and the new comparison test with an "unknown edge" fixture case | ❌ Wave 0 (extension) |
| INV-12 | Assessment-domain edges (`assessedBy`, `impacts`) unchanged, still join by `resource_id` | regression | `pytest tests/test_impact_analysis.py -x` (existing) | ✅ existing |

### Sampling Rate
- **Per task commit:** `pytest tests/test_impact_analysis.py tests/inventory_harness.py -x`
- **Per wave merge:** `pytest -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_network_normalize_from_inventory.py` — covers INV-11 (properties losslessness proof, Pitfall 1)
- [ ] `tests/test_hermes_fabric_comparison.py` — covers D-01 through D-05 (the comparison harness itself; needs a shared curated-snapshot fixture module, e.g. `tests/topology_comparison_scenario.py`)
- [ ] `tests/topology_comparison_scenario.py` — shared fixture module feeding both arms identically (Pitfall 3)
- [ ] Framework install: none — pytest already configured

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surface — reuses existing Fabric/Entra service-principal auth already in `FabricClient`/`OneLakeWriter` |
| V3 Session Management | no | N/A |
| V4 Access Control | yes | Inventory read port must remain scope-enforced per Phase 7 pattern (subscription/RG scope filtering already established in `intelligence/inventory/service.py`); Fabric IQ ontology binding must not expose topology data outside the requesting connection's authorized scope — D-05's "unauthorized edges must remain explicit" is itself an access-control requirement |
| V5 Input Validation | yes | Reuse `InventoryQualityReport`/`validate_inventory_dataset` pattern (`fabric_contracts.py`) for the new `topology_entities`/`topology_edges` tables rather than skipping validation for the "comparison-only" pipeline |
| V6 Cryptography | no | No new crypto — reuses existing Fabric/OneLake TLS + token-credential auth |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-connection data leakage via topology edges (a peering/route edge spanning subscriptions the requesting connection isn't authorized for) | Information Disclosure | Scope-filter topology_edges reads the same way `intelligence/inventory/service.py` scope-filters resource reads; do not expose an unscoped Fabric IQ traversal endpoint |
| Flow-log data containing sensitive traffic metadata (internal IPs, potentially sensitive port/service mappings) landing in a less-access-controlled lakehouse zone | Information Disclosure | Land flow-log-derived data in the same governed lakehouse zone/ACLs as other inventory tables, not a separate less-guarded staging area |
| Stale/conflicting edge silently presented as confident in the Fabric IQ UI (defeats D-05) | Repudiation / Tampering (in the sense of silently-wrong data being trusted) | Carry `confidence`/`assertionState`/`source` fields through to the Fabric IQ-bound table exactly as Hermes does (Pattern 1) — do not drop these columns during ontology binding for simplicity |

## Sources

### Primary (HIGH confidence — read directly this session)
- `src/hermes_arg_connector/queries.py` (full file, 232 lines)
- `src/hermes_arg_connector/normalize.py` (full file read via two view calls, 864 lines)
- `src/hermes_arg_connector/network_normalize.py` (partial, lines 1-260; remainder consistent with header docstring and referenced elsewhere)
- `src/hermes_arg_connector/ontology.py` (full file, 55 lines)
- `src/hermes_arg_connector/agent_queries.py` (full file, 157 lines)
- `src/semantic/semantic_engine.py` (targeted sections: class header, `get_impact_context`, `_bounded_public` region — outline via grep + view of lines 320-490)
- `src/fabric/fabric_client.py`, `src/intelligence/inventory/fabric_contracts.py`, `src/intelligence/inventory/fabric_publication.py`, `src/intelligence/inventory/onelake_publication.py`, `src/storage/onelake_writer.py` (targeted sections)
- `src/network/tightening.py`, `src/network/gaps.py` (headers — confirming no flow-log ingestion)
- `.planning/phases/08-resource-identity-plane/08-CONTEXT.md`, `.planning/phases/07-unified-resource-inventory/07-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` §Phase 8, `.planning/STATE.md`
- `tests/test_impact_analysis.py`, `tests/semantic_scenario.py`, `tests/test_agent_queries.py`, `pyproject.toml`

### Secondary (MEDIUM confidence)
- None this session (no working web-search/documentation seam reachable — see Assumptions Log preamble).

### Tertiary (LOW confidence — training knowledge, not verified this session)
- Fabric IQ ontology binding mechanism/API shape (Assumption A1)
- NSG Flow Logs v2 / Traffic Analytics schema field names (Assumption A2)
- KQL `make-graph`/`graph-match` operator availability and `azure-kusto-data` client (Assumption A3)
- Interpretation of "Fabric-native Spark/KQL pipeline" as requiring genuine Fabric-hosted compute (Assumption A4)

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM — existing repo patterns (DeltaWriter/OneLakeWriter, pytest) are HIGH confidence; Fabric IQ/KQL graph tooling recommendations are LOW confidence, unverified this session
- Architecture: HIGH for the migration/mirroring plan (grounded in read source); MEDIUM for the comparison-arm Fabric-native pipeline shape (Open Question 1 unresolved)
- Pitfalls: HIGH — all four pitfalls are grounded in specific verified code/decision citations
- Security: MEDIUM — patterns follow existing project conventions but ASVS mapping for Fabric IQ specifically is not externally verified

**Research date:** 2026-08-27
**Valid until:** 14 days — Fabric IQ is an actively evolving product area; re-verify externally-sourced claims (Assumptions A1-A3) before locking any task that depends on them, ideally via a documentation-lookup seam if one becomes available before planning executes.
