# Fabric Inventory Data Flow

## Reading Medallion health

Layer counts display **healthy / registered datasets**, not record counts or a
physical lakehouse table inventory. `0 healthy / 18 registered` can describe
populated Bronze datasets whose recorded freshness has expired. Individual
dataset row counts are reported separately from recorded metadata, not a live
table scan. No registered entries in a scope does not prove physical absence.

Connection discovery and Fabric publication are separate operations. A successful
subscription sync does not prove that full inventory/Fabric publication ran,
or that connection-attributed publication metadata is available.
Do not remove connection filters or attribute subscription-wide metadata to a
connection to make its health counts appear populated.

## Exploring Gold products and the Ontology Agent

The layers API also returns `gold_declarations`: source-schema names and their
registry version, separate from scope-filtered `tables` and healthy/registered
counts. The page exposes these under **Explore declared Gold products**.
`physical_inventory: not_collected` is intentional: a declared schema is not
proof of a deployed table, accepted generation, validated schema or fresh data.
Declarations do not make dataset status or contract reads available for
unregistered tables, and do not trigger additional data-plane reads.

The existing registry declares eight Gold products:

| Product family | Declared tables |
| --- | --- |
| Exposure analytics | `gold_exposure_facts`, `gold_exposure_dimensions`, `gold_exposure_facets`, `gold_exposure_summaries`, `gold_exposure_evidence` |
| Current exposure | `gold_exposure_current`, `gold_container_exposure_current`, `gold_container_exposure_coverage` |

Reuse the existing `FabricSyncService` and `ExposureGoldFabricPublisher` rather
than creating parallel empty tables to populate the dashboard. The producer
uses normalized Silver observations and container/workload inputs, writes
generation-qualified Gold products, reconciles persisted output, completes
finalization, and activates the readable-generation pointer. The sync checks
that the new pointer is observable. Derived snapshots are excluded from generic
source-status receipts; missing generic Gold health entries therefore do not
establish physical absence.

Before authorizing live creation or recovery, qualify the exact target,
producer configuration, authorized identity, scoped input quality/freshness,
persisted product reconciliation and readable-generation pointer. Then qualify
the consumer's actual schema/readback separately. Never mark products healthy
from declarations, a Job's process success, or staging alone.

The Ontology Agent's role is governed semantic evolution: propose entity types,
relationships and mappings grounded in observed sources. It does not perform
the Gold transformation or replace publication acceptance. Discovering or
creating Gold products does not unblock ontology lifecycle recovery or qualify
unattended agent writes. No schedule or freshness policy is changed by this
discovery feature.

```mermaid
sequenceDiagram
    participant Agent as AIOps Agent / CLI
    participant Source as Normalized ARG generation
    participant Quality as Data Quality
    participant State as ingestion_state Delta
    participant Delta as DeltaWriter
    participant OneLake as Fabric OneLake
    participant API as Fabric REST API
    participant OTel as OpenTelemetry

    Agent->>State: MERGE run=started
    Agent->>Source: Resolve current or replay generation
    Source->>Quality: Map Bronze/Silver/Ontology rows
    Quality->>OneLake: MERGE quality report
    alt quality failed
        Quality->>State: MERGE run=failed
        Quality->>OTel: failed_records + duration
    else quality passed
        loop every table
            Quality->>Delta: MERGE by resource_id/change_version
            Delta->>OneLake: Optimistic Delta transaction
            Delta->>OTel: processed/added/changed/removed
        end
        Agent->>OneLake: Write catalog metadata
        Agent->>API: Create configured shortcuts idempotently
        Agent->>API: Verify Delta table registration
        Agent->>State: MERGE run=completed + watermark
        Agent->>OTel: duration + success
    end
```

## Standard Lakehouse layout

```text
Files/
├── bronze/
│   ├── resources/
│   ├── subscriptions/
│   ├── resourcegroups/
│   ├── advisor/
│   └── patchassessment/
├── silver/
│   ├── vm_inventory/
│   ├── server_inventory/
│   ├── compliance/
│   └── resource_relationships/
├── ontology/
│   ├── entities/
│   ├── relationships/
│   └── metadata/catalog.json
└── metadata/
    ├── ingestion_state/
    └── quality_reports/

Tables/
├── bronze_resources
├── bronze_subscriptions
├── bronze_resourcegroups
├── bronze_advisor
├── bronze_patchassessment
├── bronze_resource_changes
├── silver_vm_inventory
├── silver_server_inventory
├── silver_compliance
├── silver_resource_relationships
├── ontology_entities
├── ontology_relationships
├── metadata_ingestion_state
└── metadata_quality_reports
```

Folders provide the requested medallion organization. Queryable Delta tables live in the Lakehouse `Tables` area with layer-prefixed names. `table_schema` optionally places them under `Tables/<schema>/`. Fabric automatically discovers valid Delta tables written under `Tables`; the sync verifies visibility through the Lakehouse tables REST endpoint before marking a cloud run complete.[1] This cloud registration path remains unverified in the current credential-free environment.

Current-state tables use idempotent full-snapshot overwrite, so resources absent from the latest authoritative ARG generation are removed. The ResourceChanges feed uses merge/upsert. Failures before catalog/registration commit trigger best-effort Delta rollback. After that publication boundary, tables are retained and a failed state is recorded for idempotent Ontology/shortcut retry, preventing an externally published definition from referencing rolled-back data.

Every business table contains:

- `tenant_id`
- `subscription_id`
- `resource_id`
- `timestamp`
- `change_version`
- `ingestion_run_id`

## Sources

[1] Microsoft, “Fabric REST API specifications — Lakehouse.” https://github.com/microsoft/fabric-rest-api-specs/tree/main/lakehouse
