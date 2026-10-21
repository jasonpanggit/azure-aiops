# Finite exposure scalar migration composition

`fabric.exposure_scalar_migration.migrate_exposure_scalars` is a source-only
operational composition for the additive registry/connection contract on the
existing `ontology_container_image_exposure_entities` Delta table. The core has
no credential selection, scheduled trigger or implicit cloud execution.
It depends on the separate explicit-scalar prerequisite in PR344.

The caller must provide the existing `OneLakeWriter` and `DeltaWriter`, an
independently reviewed `ExposureScalarMigrationPlan`, and an authority observer.
The Delta writer must be explicitly constructed with `max_attempts=1`; default
retrying writers are rejected before acquiring the lease or mutating anything.
The function never changes shared writer configuration. This prevents internal
write retries/backoff from committing after a lease or authority change.
The plan specifies the exact workspace/Lakehouse/schema, four existing Delta
versions (target, canonical entities, Silver exposure and registry entities),
SHA256 transaction ID, full projected-record hash and external authority proof
fingerprint. The observer must re-read the approved source/product pointers,
native binding and actual mutable-head consumption proof. A constant callback
is appropriate only in local tests, not production qualification. Neither an
`ONT_PinnedAtUtc` annotation nor absence of an explicit version selector proves
head consumption. Missing live proof blocks execution outside this composition.

Under the existing single-writer lease, the function checks all four heads and
authority repeatedly, reads pinned full Delta records and requires exact
all-scope active exposure membership and unchanged original fields. Explicit
registry keys must agree with pinned Silver records and unique active registry
endpoints in tenant/subscription/connection scope. Full registry Delta payload
JSON must parse, including explicit scope metadata; malformed/ambiguous/missing
authority is an error. No resource ID or registry host parsing is used.

Only the existing typed exposure table is overwritten, with its exact reviewed
schema, expected target version and durable transaction ID/digest. There is no
full sync, discovery, table creation/registration, definition write, catalog
update, pointer promotion or SQL DDL. Already-upgraded identical tables are
no-ops, including empty tables. Durable exact transaction replay reads/verifies
the existing result without another write. Changed input heads/authority,
conflicting content, rolled-back transactions and unproved outcomes fail.
Write errors are reconciled from Delta transaction evidence, not retried.

Readback checks the full schema and full-record hash. Failed post-write
qualification restores the captured old version only while the lease is held
and the target is still this transaction's version. Restore uses the public
version-guarded API and a distinct durable rollback transaction, then verifies
the old schema and full records. It creates another Delta commit; it does not
erase history. Intervening writers or lost leases prevent rollback. An uncertain
rollback is explicitly reported for manual reconciliation, not replayed.

The returned receipt does **not** qualify SQL endpoint propagation, native
consumption, deployment facts or relationship authoring. Independently capture
SQL scalar schema/key/multiplicity receipts and the pinned full Delta
registry scope. Fabric SQL may project long strings as `varchar(8000)`:
`ISJSON=0` on truncated SQL payload is not evidence that valid full Delta JSON
is corrupt, and SQL `JSON_VALUE` cannot prove that endpoint's connection scope.
Do not truncate canonical payload or alter SQL schemas to work around this.

This module is not wired to an application or Job. Current cloud/merge/build/
Job/native gates remain closed until the exact source, operational observer,
packaging/execution override and current cloud state are independently reviewed.

## Separate finite caller and read-only observer

`python -m fabric.exposure_scalar_migration_cli --request <local-json>
--request-sha256 <reviewed-file-sha256>` is the finite packaging path. The existing
Dockerfile already copies `src/`; no image build or Job change is needed to
describe this command. It inspects authority read-only by default. Adding
`--execute` selects the guarded one-table migration, but is **not authorization**
to execute it; existing source/CI/current-cloud approval gates still apply.
No entrypoint defaults to execute, and nothing invokes this module automatically.

The caller requires the exact existing Ops workspace/Lakehouse and combined
`Files/aiops` source root, `AIOPS_IDENTITY_CLASS=publisher`, and `AZURE_CLIENT_ID`
matching the explicitly reviewed publisher client ID. It obtains credentials
only through that managed identity and checks the SDK-obtained storage token's
tenant/object/client/audience against the reviewed request. It does not select
DefaultAzureCredential, fall back to API/local credentials, reveal tokens, use
the baked historical YAML defaults, call `build_runtime`, or provision anything.
It constructs a dedicated `DeltaWriter(max_attempts=1)`.

The concrete observer conditionally reads only existing files, with bounded
size and ETag rechecks, and reads public Delta version-qualified snapshots. It
requires `Files/aiops/current.json` to name a completed combined activation,
the latest completed ingestion marker to reference that generation and pinned
canonical versions, the current canonical heads to agree with the marker, and
the existing `Files/ontology/metadata/catalog.json` to match reviewed evidence.
It re-reads documents, native definition and marker head before returning a
fingerprint; the migration calls it repeatedly within its lease guards.

Two pre-existing independently reviewed evidence documents must live under
`Files/aiops/validation/native-scalar/`; the caller only reads them, never
creates or uploads them. The request pins each JSON document's exact
`document_hash`, not a boolean `qualified` flag:

- `product_authority_evidence`: exact `authority_mode=completed_ingestion`,
  workspace/Lakehouse/table/source generation/canonical version, source manifest
  and catalog hashes, and an independently reviewed inventory asserting no
  immutable product consumer owns this typed table. Maintenance/version-pinned
  consumer configurations are rejected, not overwritten.
- `consumption_evidence`: `kind=native-query-delta-head-observations/v1`,
  exact target and full `definition_hash`, and two actual native-query
  observations (`status=succeeded`, `reader=native_ontology_agent`, request ID,
  observation timestamp, Delta version and all active rows projected to
  resource_id/tenant_id/subscription_id/change_version).
  `query_contract=all-active-exposure-keys-no-version-filter/v1` identifies the
  reviewed all-scope native query without a version filter. The reviewer must
  verify the actual query/receipts, not manufacture this label.
  Their row hashes must differ, agree with retained full Delta snapshots at
  increasing versions, and end at the plan's target version. SQL queries,
  schema introspection, annotations, equal-result reads or narrative reports
  are insufficient.

The caller reads the existing native definition through `getDefinition` only.
It verifies the retained TMDL entity/backing-table/entity-partition/DirectLake
expression source and exact workspace/Lakehouse annotations and root; it never
calls create/updateDefinition/preview/Act. Definition content contributes to
the fingerprint. This checks binding, **not consumption**.

**Current evidence-only blocker:** retained native TMDL has a table-name
DirectLake binding and `ONT_PinnedAtUtc`, but there are no independently retained
two-version native result observations proving mutable-head consumption.
No such evidence documents have been created, no observer run in production,
and no execution is qualified. The fixtures intentionally supply synthetic
observations to exercise acceptance/rejection offline; they are not live proof.
Missing or changed evidence makes the concrete caller fail before table writes.
Execution-specific packaging/request delivery, current pinned plan and cloud
review remain operational gates; this source does not change a Job template.
