# Phase 7: Unified Resource Inventory - Context

**Gathered:** 2026-08-26
**Status:** Replanning required after Fabric pivot

<domain>
## Phase Boundary

Inventory becomes an independent domain that owns its own acquisition, normalization, retention, and source status, with Fabric/OneLake as the unified data platform and durable source of truth. An inventory refresh no longer requires a semantic-graph sync run. It generalizes to a common resource observation contract covering PaaS, reports availability per family, and exposes one scope-enforced read port that other subsystems consume.

**In scope:** ownership inversion, shared storage extraction, Fabric-backed inventory publication contracts, `ResourceObservation` contract, family registry, per-family availability, PaaS family, internal read port, and repointing the single existing cross-domain inventory dataset read.

**Out of scope (deliberately deferred):**
- Hermes dropping its ARG resource-identity queries, containment hierarchy ownership, watermark composition → **Phase 8**
- API provider rewiring, `agent_queries.py` migration, web page audit → **Phase 9**

Phase 7 delivers the *contract* that Phases 8 and 9 depend on. Getting the contract right matters more than breadth here.

</domain>

<decisions>
## Implementation Decisions

### Fabric pivot (operator decision, 2026-08-26)
- **D-00:** Fabric/OneLake is the unified inventory data platform. The neutral `DatasetStore` extraction from 07-02 remains useful shared infrastructure, but it is not the final inventory authority by itself.
- **D-00a:** The original 07-03 DatasetStore-only ownership inversion was superseded and replaced with a Fabric-backed plan. Phase 7 plans 04 through 06 were still written before this pivot and must be replanned before execution.
- **D-00b:** Inventory owns the pipeline lifecycle; Fabric owns the governed persistence/query boundary. Hermes, API, UI, and other subsystems consume inventory through inventory-owned read ports over Fabric-backed data, not by managing inventory writes or querying ARG independently for inventory identity.

### Ownership (the core correction driving this phase)
- **D-01:** Hermes is a **consumer** of inventory, never its owner. Acquisition, normalization, retention, and source status move into `src/intelligence/inventory/`; publication writes governed Fabric/OneLake inventory datasets through inventory-owned services.
- **D-02:** Inventory must be independently runnable — it refreshes and publishes without a Hermes sync. This is what removes the coupling behind the current `provider_unavailable` 503.
- **D-03:** Shared infrastructure (`DatasetStore`, generation/pointer/hash machinery in `storage.py`) is extracted to a **neutral module**. Inventory must not import Hermes for publication, and Hermes must not import inventory internals. Extraction must preserve `DatasetStore`'s public surface — 15 files depend on it.

### Regression safety (mandatory — the live-baseline gate was waived)
- **D-04:** **Characterization tests are a hard precondition for the first code-moving task.** Before anything moves, pin the observable contract against fixtures: dataset names, row shapes, `group_key()` semantics, source-status transitions, evidence fields, pagination, and the failed-refresh retention rule. These must pass unchanged after every subsequent task.
- **D-05:** The existing 79 inventory/sync tests do **not** satisfy D-04. They were written against the current *structure*, so they move with the code and would validate nothing. D-04 requires contract-level tests.
- **D-06:** Dataset names and row shapes do **not** change during inversion. Generalization is additive; OS and software rows keep their existing shapes byte-identical.

### Resource contract — `ResourceObservation`
- **D-07:** `ResourceObservation` is added **alongside** existing models. `MachineObservation` becomes a specialization; its API contract and `to_dict()` stay byte-identical so Phase 6 behavior is preserved.
- **D-08:** **`ResourceObservation` MUST carry the provider `properties` payload as an opaque, lossless passthrough.** This overrides the draft in `07-RESEARCH.md` §3.2, which specified `attributes: dict[str, str]` annotated "never raw payload". That draft predates the §7.3 finding and would make the Phase 8 Hermes pivot impossible — see the Conflict note below.
- **D-09:** Typed fields (`sku`, `tier`, `runtime`, `provisioning_state`, OS fields) are **derived projections alongside** the raw payload, never a replacement for it.
- **D-10:** `resource_id` (ARM id) is the universal join key. Assessment domains join to inventory by this key.

### Scope boundary — identity vs. assessments
- **D-11:** Inventory owns the **resource identity plane**: what exists, of what type, where, with what attributes and containment. It does **not** absorb assessments *about* resources — patch, vulnerability, policy, advisor, metrics, health stay with their own domains and join by `resource_id`. Without this fence, inventory becomes a god module worse than the current coupling.
- **D-12:** Relationship/topology modelling stays with Hermes. That is its actual job.
- **D-12a:** Hermes is **not** treated as an autonomous/self-learning discovery agent. Current Hermes discovery is deterministic code: fixed query specs, fixed normalizers, generated ontology metadata, and semantic/query services over the resulting rows. Under the Fabric unified-data-platform pivot, source discovery/acquisition/cataloguing/ETL belong to Fabric/inventory contracts; Hermes only adds value where it performs graph-specific work that Fabric tables alone do not: relationship inference, topology modelling, confidence/provenance modelling, bounded traversal, semantic query APIs, and agent-safe context packaging.

### Per-family availability
- **D-13:** Replace the all-or-nothing `from_store()` → `return None` (`service.py:214`) with per-family availability. A missing or degraded family degrades **that family only** and never blanks the inventory capability.
- **D-14:** The provider-level `provider_unavailable` error remains only for a genuinely absent provider, not for "one family has no snapshot yet".

### PaaS family
- **D-15:** Acquire PaaS via **option (a)** — project from the generic `Resources` query the inventory domain now issues itself. Zero extra ARG cost, covers every PaaS type immediately. PaaS is already ingested today; `_entity_type_for_resource()` buckets it into `entities/Resource`, so this is a projection gap, not an acquisition gap.
- **D-16:** Defer option (b) targeted `_paas_specs()` per family. Revisit when PaaS lifecycle/EOL signals (App Service runtimes, SQL versions, AKS versions) are actually needed — that reuses the Phase 6 `EOLReviewService` machinery and is better justified then.

### Read port
- **D-17:** Define one scope-enforced internal read port. `intelligence/{governance,vulnerability,lifecycle,predeploy,change,patch}` currently have **zero** dataset reads — establishing the port now prevents six subsystems each inventing their own resource-listing logic.
- **D-18:** Repoint the one existing cross-domain read (`hermes_arg_connector/service.py:116`, which implements the failed-refresh retention rule) to the read port. This is the only such read in the codebase.

### Sequencing
- **D-19:** Order is **characterize → extract → invert → expand → migrate consumer**. Ownership inversion precedes family expansion; adding families first would deepen the coupling this phase removes.
- **D-20:** Full Phase 7, not the 7a/7b split. The split existed only to de-risk starting before Phase 6 sign-off; with that gate waived it adds relocation cost for no benefit.

### Agent's Discretion
- Internal module layout under `src/intelligence/inventory/` (the `sources/`, `normalization/`, `registry.py`, `pipeline.py` shape in §3.1 is a suggestion, not a fixture).
- Name and exact signature of the read port.
- How `family` is derived and whether it is an enum or string.
- Task decomposition and count.

</decisions>

<specifics>
## Specific Ideas

**Conflict resolved — read this before implementing the model.**

`07-RESEARCH.md` §3.2 sketches `attributes: dict[str, str]` with the comment *"per-family, never raw payload"*. **D-08 overrides that.** §7.3 measured why:

- `properties` is referenced 32× in `normalize.py` and 43× in `network_normalize.py`
- access is not flat field-picking — it descends four levels and re-stores raw sub-bags:

```python
# network_normalize.py:156-161
"delegations": [
    _text((item.get("properties") or {}).get("serviceName"))
    for item in _list(subnet_props.get("delegations"))
],
"properties": subnet_props,   # raw nested bag retained wholesale
```

A flattened `dict[str, str]` cannot express this. If Phase 7 locks that contract, Phase 8's Hermes pivot is impossible without redesigning it. **Design the contract from Hermes's real read patterns, not from what the inventory UI displays.**

**Three behaviors carry the real risk** — not the file count. Characterization tests must pin all three:

1. **Failed-refresh retention rule** (`service.py:107-117`) — subtle, load-bearing, and the one place publication order and read order interact. A failed refresh must not turn a previously published inventory into an unqualified empty success.
2. **Publication timing** — inventory currently publishes as a side effect of a graph sync. Making it publish independently changes *when* datasets appear, and `from_store()`'s all-or-nothing check is implicitly coupled to that.
3. **`_preserve_created_timestamps` / `_preserve_source_watermarks`** (`service.py:123-124`) — graph-level machinery inventory rides along with today and will need its own equivalent.

**Blast radius is smaller than the headline number.** "53 files import `hermes_arg_connector`" measures module coupling, not inventory coupling. Actual inventory surface: **6 source files, 4 test files, and exactly one cross-domain dataset read.** The only genuinely wide step is the `DatasetStore` extraction (15 dependents), which must preserve its public surface.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design
- `.planning/phases/07-unified-resource-inventory/07-RESEARCH.md` — full analysis. §1 current state and the ownership table, §3 proposed design, §4 migration path, §6.3 corrected blast radius, §6.6 what replaces the waived gate, §7 scope boundary and the losslessness evidence.
  - **Caveat:** §3.2's `attributes` field is superseded by D-08. §6.4/§6.5 are marked SUPERSEDED/NOT TAKEN and are retained only as record.
- `.planning/REQUIREMENTS.md` — INV-07, INV-08, INV-09, INV-10 are this phase. INV-11/INV-12 are Phase 8 and constrain the contract shape.
- `.planning/ROADMAP.md` §Phase 7 — success criteria, waived entry gate, accepted risk. §Phase 8/9 show what this contract must support.

### Verification carried forward
- `.planning/phases/06-software-and-os-inventory-visibility/06-VERIFICATION.md` — Phase 6 is `human_needed` with no UAT. Its residual walkthroughs are now **Phase 7 exit criteria**.
- `.planning/WINDOWS.md` — windows #9-#13 re-scoped to close under Phase 7 exit.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `hermes_arg_connector/storage.py` — `DatasetStore` publish/read plus generation, pointer, and hash machinery. Extract to neutral module; do not reimplement.
- `hermes_arg_connector/inventory_normalize.py` — software normalization. Moves **wholesale** into the inventory domain, not rewritten. Already imports its contracts from `intelligence.inventory.models` (line 10) — the dependency is pre-inverted.
- `intelligence/inventory/service.py` — read model. Contract stays; internals move behind the read port.
- `intelligence/inventory/eol_review.py` — `EOLReviewService`, reusable for PaaS lifecycle when D-16 is revisited.
- `api/providers.py` `ProviderSpec` — existing registry seam; per-family availability should compose with it rather than bypass it.

### Established Patterns
- Inventory datasets must publish through a single governed Fabric/OneLake path. Any local immutable-generation path remains a compatibility/staging mechanism until the Fabric-backed source of truth is implemented.
- Inventory datasets currently ride inside `NormalizedGraph` as four bolt-on fields (`normalize.py:60-63`) published via `getattr` guards (`storage.py:90-101`). That bolt-on shape is structural evidence they don't belong to the graph — it is what this phase removes.
- Scope enforcement, evidence envelopes, and freshness/source-status reporting are established Phase 6 conventions. New families must match them, not invent variants.
- `_entity_type_for_resource()` (`normalize.py:863`) returns only `VirtualMachine`/`ArcServer`/`Resource` — every PaaS resource already lands in `entities/Resource`.

### Integration Points
- `hermes_arg_connector/service.py:97-122` — the seam to relocate: software fetch, normalization call, retention rule, source status.
- `hermes_arg_connector/service.py:116` — the single cross-domain inventory dataset read (D-18).
- `hermes_arg_connector/storage.py:90-101` — the four `inventory/*` dataset mappings to re-home.
- `intelligence/inventory/service.py:202-214` — `from_store()` and the all-on-nothing `return None` (D-13).
- `intelligence/inventory/narrative.py:25` — approved-source allow-list; extend for new families.
- `api/routers/inventory.py:36-44` — `_service()` raising `PROVIDER_UNAVAILABLE` (D-14).
- `HERMES_INVENTORY_FIXTURE` env var → `tests/fixtures/mock_inventory_arg.json` — existing fixture escape hatch, useful for characterization tests.

</code_context>

<deferred>
## Deferred Ideas

- **Targeted PaaS query specs** (`_paas_specs()`) with explicit SKU/tier/runtime projection, and PaaS lifecycle/EOL via `EOLReviewService` — D-16, revisit when PaaS EOL signals are needed.
- **Hermes drops ARG resource-identity queries**; inventory owns containment hierarchy and per-family watermarks in Fabric-backed contracts — **Phase 8** (INV-11, INV-12).
- **Hermes is graph consumer/modeller, not discovery learner.** Phase 8 must remove Hermes's ARG identity acquisition only if Fabric-curated `ResourceObservation`/identity tables are lossless enough for its deterministic normalizers and graph modelling. If Hermes contributes no graph-specific inference/traversal/context value beyond coded acquisition and row mapping, the separate "Hermes discovery" role should be deleted rather than preserved.
- **API provider rewiring, `agent_queries.py` migration, web page audit** — **Phase 9** (INV-09, INV-10), after Fabric-backed read ports are stable.
- **Open question for Phase 8 planning:** does the semantic graph still publish `entities/*` for identity types, or do those become views over inventory? Determines whether `agent_queries.py` changes shape or only source.
- **Pre-existing `web/src/app/compliance/page.test.tsx` failure** — unrelated to inventory; triage so full-suite green becomes a usable signal.

</deferred>

---

*Phase: 07-unified-resource-inventory*
*Context gathered: 2026-08-26*
*Updated: 2026-08-26 after operator pivot to Fabric as the unified data platform.*
*Source: design review conducted in-session (ownership correction, PaaS extension review, scope staging) rather than a separate discuss-phase run.*
