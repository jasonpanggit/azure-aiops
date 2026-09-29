# Lakehouse Table Inventory & Medallion Layering

Review of every Delta table in `operational_context_graph_v2` (workspace `aiops-dev-ops`),
how the bronze / silver / gold layers are decided, and which tables are redundant.

**No tables were deleted.** This document is the review record; deletion is deferred
pending the decisions in [Recommendations](#recommendations).

Survey method: enumerated `Tables/` over OneLake, then read each table's Delta log for
version, file count and `num_records`. Row counts come from Delta add-action statistics,
not from scanning data.

---

## 1. How bronze / silver / gold are determined

**Layer is a naming convention, nothing more.** There is no Fabric, Delta, or storage
construct behind it. The only place a layer is computed is a prefix match:

```python
# src/api/routers/fabric_medallion.py:431
def _layer_for_table(table_name: str) -> str:
    if table_name.startswith("bronze_"):
        return "bronze"
    if table_name.startswith("silver_"):
        return "silver"
    if table_name.startswith("gold_"):
        return "gold"
    return ""
```

A table is bronze because it is *named* `bronze_*`. The discipline that makes the name
meaningful lives in two places:

- `src/fabric/schema_registry.py` — declares the Arrow schema for every table name. This is
  the contract; a table cannot be published without an entry here.
- The producer that emits the rows — which determines what the layer actually *means*.

### Are ARG and Log Analytics tables bronze?

**No.** ARG and LAW are *upstream sources*, one hop before bronze. They never appear as
lakehouse tables.

The collectors write a **DatasetStore generation** to OneLake as JSONL files, not Delta:

```text
Files/aiops/inventory-source/generations/<generation-id>/
├── manifest.json
├── entities/<EntityType>.jsonl      ← ARG resources, VMs, Arc servers, Defender, Advisor…
├── relationships/relationships.jsonl
├── changes/resource_changes.jsonl
└── situations/…
```

That JSONL generation is the raw landing zone. `bronze_*` is the first *tabular,
schema-validated* copy of it. So the real chain is:

```text
ARG / LAW / Defender / Advisor / Cost
      │  (collectors)
      ▼
JSONL generation in Files/        ← raw capture, immutable, versioned
      │  InventoryDatasetMapper.load()
      ▼
bronze_*                          ← typed 1:1 passthrough
      │  same mapper pass
      ▼
silver_*                          ← conformed, deduped, joined
      │  exposure_projection.py (separate pipeline)
      ▼
gold_*                            ← serving aggregates
```

### Bronze — typed 1:1 passthrough

Built in `InventoryDatasetMapper.load()` (`src/fabric/dataset_mapper.py:1768+`). Each bronze
table is a direct row-for-row projection of one entity file, with no joins and no business
logic — only shaping into the registered schema:

```python
all_resources = [*entities["Resource"], *entities["VirtualMachine"], *entities["ArcServer"]]
...
"bronze_resources":     [_asset_row(row, ingestion_run_id) for row in all_resources],
"bronze_subscriptions": [_entity_row(row, "Subscription", ingestion_run_id)
                         for row in entities["Subscription"]],
```

**Rule of thumb:** if it is a renamed, retyped copy of exactly one source feed, it is bronze.

### Silver — conformed and joined

Also emitted by the same mapper pass, but silver rows are the result of dedupe, entity
resolution, or joining several bronze/entity feeds. `silver_vm_inventory`,
`silver_server_inventory` and `silver_resource_relationships` are resolved against a
`resource_index` rather than copied.

**Rule of thumb:** if producing it required correlating more than one source, it is silver.

### Gold — serving aggregates, a *different* producer

Gold is **not** produced by `InventoryDatasetMapper` at all. A healthy mapper run emits
`gold_` tables: **0**. Gold is built by
`src/intelligence/vulnerability/exposure_projection.py`, which consumes silver tables and
emits query-shaped facts and dimensions:

```python
GOLD_EXPOSURE_FACTS_TABLE      = "gold_exposure_facts"
GOLD_EXPOSURE_DIMENSIONS_TABLE = "gold_exposure_dimensions"
GOLD_EXPOSURE_FACETS_TABLE     = "gold_exposure_facets"
```

This split explains an otherwise confusing observation: **gold is populated while most
bronze and silver inventory tables are empty.** They are fed by two independent pipelines
from two different source roots. Gold's inputs are healthy; the inventory chain's are not
(see §4, Category B).

**Rule of thumb:** if it exists to be read by the API, semantic model, or Data Agent —
pre-aggregated and denormalised for serving — it is gold.

### The fourth family: `ontology_*`

`ontology_*` is deliberately outside the medallion naming scheme; `_layer_for_table` returns
`""` for it. It is a graph projection, not a medallion layer, generated from a declared
taxonomy (§3). Likewise `metadata_*` (control plane), `inventory_*` (raw observations) and
`topology_*` are non-medallion families.

---

## 2. Live inventory — 472 tables

| Family        | Total | With rows | Empty but written | Single empty commit |
|---------------|------:|----------:|------------------:|--------------------:|
| `ontology_`   |   399 |         6 |               393 |                   0 |
| `silver_`     |    30 |        16 |                14 |                   0 |
| `bronze_`     |    18 |         4 |                14 |                   0 |
| `metadata_`   |     9 |         9 |                 0 |                   0 |
| `gold_`       |     8 |         7 |                 0 |                   1 |
| `inventory_`  |     5 |         5 |                 0 |                   0 |
| `topology_`   |     2 |         2 |                 0 |                   0 |
| `assessment_` |     1 |         1 |                 0 |                   0 |
| **Total**     |**472**|    **50** |           **421** |               **1** |

**No table is unreferenced.** Every one has a schema-registry entry and a live producer.
421 of them are re-published on every run and simply receive zero rows — so "unused table"
is the wrong frame. The right questions are *why* each is empty, and whether it should have
been created at all.

### Largest live tables

| Table | Version | Rows |
|---|---:|---:|
| `silver_exposure_observations` | 6 | 373,302 |
| `silver_container_vulnerability_observations` | 5 | 327,122 |
| `gold_exposure_facts` | 5 | 193,187 |
| `gold_exposure_current` | 7 | 97,901 |
| `gold_container_exposure_current` | 11 | 8,502 |
| `bronze_resource_changes` | 62 | 3,931 |
| `silver_lifecycle_history` | 50 | 3,317 |
| `silver_cost_actuals` | 33 | 3,161 |
| `metadata_ingestion_state` | 903 | 533 |
| `ontology_entities` | 108 | 133 |

---

## 3. The 393 empty `ontology_*` tables are by design, not decay

Ontology tables are materialised **eagerly from the declared taxonomy**, whether or not any
instance exists:

```python
# src/fabric/dataset_mapper.py:1935
for entity_type in ONTOLOGY_ENTITY_TYPES:                 # one table per declared type
    datasets[ontology_entity_table(entity_type)] = [
        row for row in graph.entities if row["entity_type"] == entity_type
    ]
...
for relationship_type in ONTOLOGY_RELATIONSHIP_TYPES:     # …even with no rows
    datasets.setdefault(ontology_relationship_table(*relationship_type), [])
```

Names are mechanical: `ontology_{entity_type}_entities` and
`ontology_rel_{predicate}_{subject}_{object}`.

The taxonomy is far larger than the tenant's data:

| Measure | Count |
|---|---:|
| Declared entity types | 108 |
| Declared relationship types | 595 |
| **Declared ontology tables** | **703** |
| Ontology tables currently in lakehouse | 399 |
| Declared but not yet created | 313 |
| Core/context tables outside the taxonomy | 9 |

Running the mapper against the **current healthy source generation** shows the ceiling:

| Healthy-run result | Count |
|---|---:|
| Tables produced | 757 |
| Tables with at least one row | 172 |
| Tables empty | 585 |
| Ontology tables produced | 713 |
| Ontology tables with rows | **144** |

So even with a perfectly healthy pipeline, **569 ontology tables would still be empty**, and
the lakehouse would grow from 472 to ~757 tables. The empty-table count is a property of
taxonomy breadth, not a fault. Every one of these also costs a Delta commit per run, which
is why `write_workers` pressure and publish latency scale with taxonomy size rather than
with data volume.

The 9 tables outside the taxonomy are legitimate fixed tables:
`ontology_entities`, `ontology_relationships`, `ontology_health`, `ontology_quality_report`,
and the five `ontology_*_context` views.

---

## 4. Redundancy classification

Three distinct causes of emptiness. Only one is genuine redundancy.

### Category A — Eager taxonomy materialisation (393 ontology tables)

Not redundant per table; redundant *in aggregate strategy*. Created because the type is
declared, not because data exists. Deleting them is futile — the next publish recreates
them. Only a producer change (materialise on first non-empty projection) reduces this.

### Category B — Starved by a publisher defect (14 tables)

These have real source data available right now but are empty in the lakehouse. Marked
`WOULD-FILL` by replaying the mapper against the current live generation:

**Bronze (8):** `bronze_resources`, `bronze_subscriptions`, `bronze_resourcegroups`,
`bronze_advisor`, `bronze_defender_assessments`, `bronze_defender_secure_scores`,
`bronze_defender_secure_score_controls`, `bronze_container_image_exposure`

**Silver (6):** `silver_vm_inventory`, `silver_server_inventory`,
`silver_resource_relationships`, `silver_defender_assessments`,
`silver_defender_secure_score_controls`, `silver_container_image_exposure`

Their Delta versions split cleanly by write mode, which dates the damage (§6):

| Write mode | Count | Versions | Meaning |
|---|---:|---|---|
| OVERWRITE | 11 | 353–401 | Re-emptied on every run, still committing |
| SNAPSHOT_MERGE | 3 | 73, 78, 102 | Wiped once, inert since |

**Ontology:** `ontology_entities` holds 133 rows (only `ChangeEvent`, `LifecycleProduct`,
`RiskPattern`) against 1,482 available from the live source.

**These must not be deleted — they are the pipeline's intended output.** The proximate
cause is a starved projection: when `InventoryDatasetMapper.load()` finds no entity rows,
every entity-derived bronze/silver/ontology table projects to zero rows and is then
committed as empty.

**Root cause — confirmed live.** The starving writer is the hourly Fabric Data Pipeline
**"Inventory Refresh"** (`d879af68-e020-4c6f-941e-aa9967544b13`, 60-minute schedule). It
calls the API, which runs `run_inventory_refresh_all_connections`
(`src/api/inventory_orchestration.py` on `main`):

1. Each connection's `pipeline.refresh()` runs. Connection roots keep their entities,
   because carry-forward preserves them.
2. `publish_combined_inventory_snapshot` publishes a new generation,
   `inventory-activation-*`, into the **combined** root (`Files/aiops`). That generation
   holds only `inventory/*` datasets.
3. `runtime.service.sync(replay_source_run_id=<that generation>)` replays it. The full
   sync projects every bronze, silver and ontology table from `entities/*`, and there are
   none, so each table is overwritten with 0 rows.

Evidence:

- **Delta history.** `bronze_subscriptions`, `bronze_advisor`,
  `silver_resource_relationships` and `ontology_relationships` each record a 0-row
  OVERWRITE every hour at about :49 UTC, written by delta-rs 1.6.2. No ACA job runs
  hourly.
- **OneLake manifests.** The connection root `Files/aiops/connections/demo` is healthy:
  it holds 64 datasets, including 42 `entities/*` datasets with 12,993 rows. The
  combined root's `current.json` points at `inventory-activation-62cd2abf…`, which
  holds 11 datasets and **0 entity datasets**, and records
  `sourceRunIds=['0f0eeded…']`.

This resolves the earlier "divergent roots" hypothesis. The combined root never held
entity datasets, so there was nothing to carry forward.

**Fix.** The orchestration now publishes a second, entities-aware snapshot into the
combined root and replays *that*. The snapshot merges the just-refreshed connection
roots, and the orchestration pins the `inventory/*` datasets from the combined
generation it just built, via `publish_combined_snapshot(..., pinned_datasets=...)`.
Pinning matters: carry-forward would pick up whatever generation is current at publish
time, which is the concurrency hazard commit `99a0eb11e` was written to prevent. The
fix is covered by `test_refresh_all_connections_publishes_fabric_from_resolved_generation`.

**Latent hazard (not the hourly cause).** Both producers stamp the same `queryVersion`,
`combined-subscription-connections-v1`. `reuse_unchanged` dedupe is opt-in and today
only `patch_publication.py` enables it.

What *is* verified is the mechanism by which the loss goes unreported, and it differs by
write mode — see [§6 The silent publisher failure](#6-the-silent-publisher-failure).
`metadata_ingestion_state` shows `status: completed` with an empty `error` while
`ontology_entity_version` stays pinned at 108 across runs: a total inventory wipe is
byte-for-byte indistinguishable from a healthy run.

### Category C — No source data in this tenant (15 tables)

Correctly empty. The feature is wired end to end; the tenant simply has no such records.
Safe to keep — they will populate if the corresponding Azure feature is used.

`bronze_cost_actuals`, `bronze_defender_alerts`, `bronze_defender_findings`,
`bronze_defender_attack_paths`, `bronze_defender_attack_path_nodes`,
`bronze_defender_attack_path_connections`, `silver_defender_alerts`,
`silver_defender_findings`, `silver_defender_attack_paths`,
`silver_defender_attack_path_nodes`, `silver_defender_attack_path_connections`,
`silver_situations`, `silver_situation_evidence`, `silver_situation_links`,
`gold_exposure_evidence`

### Verdict

| Category | Tables | Redundant? | Action |
|---|---:|---|---|
| A — eager taxonomy | 393 | Aggregate strategy only | Change producer, not data |
| B — starved by defect | 14 | **No** | Fix publisher |
| C — no tenant data | 15 | No | Keep |
| Live | 50 | No | Keep |
| **Total** | **472** | | |

**Nothing qualifies for straightforward deletion.** There is no orphaned table — no table
without a schema entry, a producer, and a live commit history.

---

## 5. Recommendations

1. **Do not delete anything yet.** Every empty table is actively republished; deletion is
   undone on the next run and would destroy Category B tables that are supposed to hold data.

2. **Fix the silent failure first — as a preflight, not a post-hoc check.** *(Implemented.)*
   A version comparison in `_required_table_version()` cannot prevent the loss, because two
   of the three failure paths (§6) delete the rows before that code runs. The guard aborts
   *before writing*, and gates on data loss rather than snapshot shape — partial generations
   are legitimate, so it fires only when an empty projection would overwrite inventory that
   is currently live in Fabric. See `FabricSyncService._assert_entity_projection_intact`.

3. **Confirm the upstream trigger before changing `combine.py`.** The producer-collision
   theory is unconfirmed (§4 Category B): carry-forward already preserves entities in an
   established root. Determine `combine.py`'s runtime `target_root` and whether it differs
   from the publisher's source root before altering it. The preflight in recommendation 2
   is deliberately trigger-agnostic, so Category B tables are protected either way — but
   protection is not recovery, and recovery needs the real trigger.

4. **Make ontology materialisation lazy.** Create a typed ontology table on first non-empty
   projection instead of eagerly from the taxonomy. This avoids ~569 permanently empty tables
   and prevents growth to ~757 tables, cutting per-run Delta commits proportionally.

5. **Re-verify after the fixes.** `ontology_entity_version` should advance past 108 and
   `ontology_entities` should move from 133 toward ~1,482 rows; the 14 Category B tables
   should become non-empty.

6. **Revisit deletion only after (3).** Once the pipeline is healthy, re-run this survey —
   any table still empty then is genuinely Category A or C, and the lazy-materialisation
   change in (4) is the correct remedy rather than a one-off drop.

---

## 6. The silent publisher failure

Category B above is caused by a publication defect that reports success while destroying
data. It is worth its own section because the *mechanism differs by write mode*, and the
Delta version numbers are the forensic record of which path each table took.

### Why nothing catches it

`DeltaWriteResult` carries five signals that would each have exposed this:

```python
# src/storage/delta_writer.py:35
@dataclass(frozen=True)
class DeltaWriteResult:
    rows_processed: int
    rows_added: int = 0
    rows_changed: int = 0
    rows_removed: int = 0
    skipped: bool = False
    version: int | None = None
```

The only gate applied to them asks two questions — is a version present, and is it a
non-negative integer:

```python
# src/fabric/sync_service.py:2922
def _required_table_version(results, table_name) -> int:
    result = results.get(table_name)
    if result is None or result.version is None:
        raise RuntimeError(
            f"Completed Fabric publication is missing {table_name} Delta version"
        )
    return _validated_delta_version(result.version, field_name=f"{table_name} version")
```

It never asks whether the version *advanced*, whether `skipped` was set, or whether any rows
were written. `status="completed"` is therefore unconditional. `rows_removed` is even summed
into the state row and then never compared against anything:

```python
# src/fabric/sync_service.py:1156-1165
completed = _state_row(
    run_id, source_run_id, status="completed", ...,
    rows_removed=sum(value.rows_removed for value in table_results.values()),
    ontology_entity_version=ontology_entity_version, ...
)
```

### Three distinct failure paths

When the publisher consumes an inventory-only generation, the projection is empty — but what
happens next depends entirely on the table's write mode.

| Path | Tables | Write mode | Effect | Version behaviour |
|---|---:|---|---|---|
| 1 — identity skip | `ontology_entities` | OVERWRITE | Stale rows retained | **Frozen** (108) |
| 2 — overwrite to empty | 11 of 14 Category B | OVERWRITE | Wiped every run | **Climbs** (353–401) |
| 3 — merge-delete | 3 of 14 Category B | SNAPSHOT_MERGE | Wiped once, then inert | **Frozen early** (73/78/102) |

**Path 1 — `ontology_entities`, content-identical skip.** It is force-published even when
empty (§4), and each run re-projects the same 133 appended rows (`ChangeEvent`,
`LifecycleProduct`, `RiskPattern`). Content matches, so the writer short-circuits and returns
the *old* version:

```python
# src/storage/delta_writer.py:680
if current_versions == incoming_versions:
    return DeltaWriteResult(
        rows_processed=processed_count,
        skipped=True,
        version=table.version(),   # ← previous version, unchanged
    )
```

`_required_table_version` accepts 108 as success. This is precisely why
`ontology_entity_version` is pinned at 108 while `ontology_relationship_version` advances.

**Path 2 — bronze/silver under OVERWRITE.** Here `supports_version_compare` is
`bool(rows) and ...`, which is `False` for an empty projection, so the identity check is
skipped entirely and the table is genuinely overwritten with nothing:

```python
# src/storage/delta_writer.py:727
previous_count = 0
if exists:
    previous_count = DeltaTable(uri, storage_options=self.storage_options).count()
write_deltalake(uri, source, mode="overwrite", ...)
table = DeltaTable(uri, storage_options=self.storage_options)
return DeltaWriteResult(rows_processed=..., rows_added=len(rows),
                        rows_removed=previous_count, version=table.version())
```

A new commit is written **every run**, which is why these sit at versions 372–401 despite
holding zero rows. They are being actively re-emptied on an hourly cadence, and
`rows_removed` faithfully reports the loss each time.

**Path 3 — bronze/silver under SNAPSHOT_MERGE.** `bronze_resources` (v=102),
`silver_vm_inventory` (v=73) and `silver_server_inventory` (v=78) take the merge path, whose
snapshot semantics delete anything the source does not contain:

```python
# src/storage/delta_writer.py:713
if mode is DeltaWriteMode.SNAPSHOT_MERGE:
    builder = builder.when_not_matched_by_source_delete()
```

With an empty source nothing matches, so the *first* bad run deleted every row. Subsequent
runs have nothing left to delete, so the merge is a true no-op and stops producing commits.
**Their low, frozen versions date the original wipe** — these three tables have been empty
far longer than the others, and stopped recording evidence the moment they were emptied.

### Why this is dangerous

In `metadata_ingestion_state`, a total inventory wipe and a healthy run are identical:
`status: completed`, `error: ''`. The only distinguishing signal is a version that stopped
advancing (paths 1 and 3) or a large `rows_removed` (path 2) — and nothing reads either.

### Where the fix belongs

Not in `_required_table_version` alone. By the time that runs, paths 2 and 3 have already
deleted the data; a post-hoc version check can only report the damage after the fact.

1. **Preflight assertion (primary).** *(Implemented —
   `FabricSyncService._assert_entity_projection_intact`.)* Before any write, abort when an
   empty entity projection would overwrite inventory that is **currently live in Fabric**.
   The test is *loss*, not shape: partial generations are a legitimate pattern in this
   codebase (an exposure-only or inventory-only publication into a root holding no entity
   data destroys nothing), so the guard first checks the live witness table
   (`bronze_resources`) via Delta add-action statistics — metadata only, no data read — and
   returns immediately when there is nothing to lose. It then fails on either starvation
   shape: a generation declaring no `entities/*` datasets, or one declaring entity rows
   whose projection collapsed to zero. It runs immediately after `self.mapper.load(...)`,
   before the first Delta write.
2. **~~Treat `skipped=True` as failure on force-published tables~~ — rejected.** This was
   the original proposal for path 1, but it is wrong: with the preflight in place, a skip
   means the content genuinely matched, which is an ordinary no-change run. Failing on it
   would break every idempotent republish. Path 1 is instead covered by the preflight,
   which stops a starved generation from reaching the writer at all.
3. **Fail when a run removes rows and adds none** — catches path 2, and would have caught
   path 3 on the run that did the original damage. *(Implemented —
   `FabricSyncService._assert_no_wholesale_inventory_wipe`.)* Deliberately narrow: it fires
   only when rows were removed, **no** bronze/silver table gained a row, and no wiped table
   had rows to project. A tenant legitimately losing its last record of one kind must not
   fail the publication. It is placed before `data_committed = True` so `_rollback()` can
   still restore the prior table versions.

**Limits of these guards.** Delta writes are not transactional across tables, so rollback
is best-effort per table; the guards reduce the blast radius rather than making publication
atomic. They also protect against starvation without explaining it. §4 Category B gives the
confirmed root cause, the hourly inventory-only replay, and its fix.

**Deployment note.** These guards were first written against a feature branch that is
about 600 commits behind `main`, so they never reached production. They have since been
ported onto `main`'s `sync_service.py`. On their own, the guards cannot recover a
lakehouse that is *already* empty, because the loss-based preflight finds nothing to
lose. The root-cause fix is what repopulates it on the next hourly run.

---

## Appendix — reproducing this survey

```python
from concurrent.futures import ThreadPoolExecutor
from deltalake import DeltaTable
from azure.identity import DefaultAzureCredential

tok = DefaultAzureCredential().get_token("https://storage.azure.com/.default").token
so = {"bearer_token": tok, "use_fabric_endpoint": "true"}
base = ("abfss://aiops-dev-ops@onelake.dfs.fabric.microsoft.com/"
        "operational_context_graph_v2.Lakehouse/Tables/")

def scan(name):
    dt = DeltaTable(base + name, storage_options=so)
    adds = dt.get_add_actions(flatten=True)          # arro3 Table
    rows = sum(int(x or 0) for x in adds.column("num_records").to_pylist())
    return name, dt.version(), rows

with ThreadPoolExecutor(max_workers=32) as ex:
    results = list(ex.map(scan, table_names))
```

Notes:

- `get_add_actions()` returns an `arro3.core.Table`, not a `pyarrow.Table` — it has no
  `.to_pylist()`. Read columns individually.
- Listing top-level `.parquet` files is **not** a valid emptiness test: partitioned tables
  keep data in subdirectories. `gold_container_exposure_current` looks empty that way and
  actually holds 8,502 rows. Always use the Delta log.
- The Fabric SQL endpoint MCP tool returns HTTP 401; read OneLake directly as above.
