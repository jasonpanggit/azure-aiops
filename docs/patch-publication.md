# Patch-only Exposure publication

Patch Priorities reads use the authoritative Silver patch snapshot in
`silver_patch_snapshot_findings`, gated by `metadata_patch_snapshot`. The API
may request a connection-scoped ingestion refresh, but it does not publish
Fabric tables and does not start the publisher job.

## Scheduled writer

Terraform provisions the finite `${local.base}-patch-publication` Container
Apps Job. It runs every five minutes by default with one replica, no retries,
and a 30-minute execution timeout. The job uses the existing ontology
publisher managed identity and the API image, but executes only:

```text
python -m onboarding.cli patch-publish \
  --config /app/config.yaml \
  --fabric-config /app/fabric.config.yaml \
  --connection-home <onelake-files-root>/aiops/connections \
  --source-root <onelake-files-root>/aiops/patch-publication-source
```

The connection home is the API-owned registry root. Connection snapshots are
therefore read from its existing `connections/<connection-id>` child (for the
deployed layout this is `aiops/connections/connections/demo`). The distinct
source root owns only the idempotent combined snapshot consumed by the Patch
publisher. Production rejects missing, local, or aliased roots before reading
or writing. Local configurations may retain config-derived roots for tests and
development. The writer then calls `FabricSyncService.sync_patch_tables`; it
does not run live Azure discovery, build ontology, project Gold Exposure
tables, or advance the Gold pointer.

## Safety and recovery

- `Files/metadata/ingestion.lock` is the single-writer lease for every Fabric
  table publication. Lock contention fails the job without writing.
- `metadata_patch_snapshot` records the combined source generation and is
  written last. A generation already represented by a complete or
  healthy-empty barrier is a no-op.
- Assessment, installation, and missing AUM source families must all be
  present. Partial, stale, or unavailable source barriers fail before the
  first table write, preserving the last-known-good snapshot.
- If a later table or registration step fails, mutable patch tables and the
  barrier roll back. Immutable snapshot findings remain append-only and are
  not made visible without the barrier.
- CLI output contains only status, a source-generation hash, bounded counts,
  and duration. Lock conflicts and other expected failures emit stable reason
  codes rather than exception details.

The API and web app continue serving the current LKG while refresh is pending
or failed. The scheduled job observes the newly ingested connection snapshot
on its next cadence; no request thread waits for publication.
