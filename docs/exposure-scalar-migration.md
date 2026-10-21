# Finite exposure scalar migration composition

`fabric.exposure_scalar_migration.migrate_exposure_scalars` is a source-only
operational composition for the additive registry/connection contract on the
existing `ontology_container_image_exposure_entities` Delta table. It has no
CLI, credential selection, scheduled trigger or implicit cloud execution.
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
