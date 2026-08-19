# Fabric Inventory Data Flow

```mermaid
sequenceDiagram
    participant Agent as Hermes Agent / CLI
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
