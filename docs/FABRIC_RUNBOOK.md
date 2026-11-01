# Fabric Inventory Persistence Runbook

## Purpose

Operate, diagnose, replay, and recover the Azure inventory to OneLake synchronization. This runbook covers persistence only; it does not enable semantic models, ontology reasoning, remediation, or Copilot workflows.

## Prerequisites

1. A Fabric workspace on capacity and a Lakehouse.
2. A managed identity or service principal with access to the workspace/Lakehouse and OneLake data paths.
3. A completed local ARG generation under the configured `source_data_root`.
4. The project environment provisioned with `uv sync --extra test`.
5. `AIOPS_FABRIC_CONFIG` set for AIOps gateway agent commands.

Fabric workspace roles govern item operations and OneLake access.[1] Use least privilege and immutable workspace/Lakehouse IDs in production.

## Authentication

### Managed identity

Copy `fabric.config.example.yaml` and set workspace/Lakehouse IDs. For a user-assigned identity, set `managed_identity_client_id`. No secret is stored.

### Service principal

Copy `fabric.service-principal.example.yaml` and export the configured secret variable:

```bash
export FABRIC_CLIENT_SECRET='retrieve-from-approved-secret-store'
```

Never write the secret into YAML, source control, run state, or catalog metadata.

## Standard operations

```bash
# Persist the current normalized ARG generation
uv run aiops-inventory fabric \
  "Sync Azure inventory to OneLake" \
  --config fabric.config.yaml

# Refresh idempotently
uv run aiops-inventory fabric \
  "Refresh inventory lakehouse" \
  --config fabric.config.yaml

# Read durable OneLake state
uv run aiops-inventory fabric \
  "Show ingestion status" \
  --config fabric.config.yaml

uv run aiops-inventory fabric \
  "Show last Fabric sync" \
  --config fabric.config.yaml

# Validate without writing inventory tables
uv run aiops-inventory fabric \
  "Validate inventory data" \
  --config fabric.config.yaml
```

These phrases are operator CLI commands and are intentionally not exposed to agents.

## Replay

List source generations under `<source_data_root>/generations/`, select the immutable source run ID, then run:

```bash
uv run aiops-inventory fabric \
  "Sync Azure inventory to OneLake" \
  --config fabric.config.yaml \
  --replay-source-run-id '<source-run-id>'
```

Replay records a new Fabric ingestion run and retains the original source run ID.

### Empty workload products versus missing sources

An explicitly present empty `exposure/workload_observations.jsonl`,
`exposure/workload_deployments.jsonl`, or
`exposure/workload_source_checkpoints.jsonl` retains its declared typed table
during publication, including first publication. The legacy `workload/` path
is used only when the corresponding canonical file is absent; an empty
canonical file must not revive legacy rows. Missing product files remain
missing inputs and do not request creation or clearing of those tables.
Existing workload APPEND/MERGE modes and rollback version tracking remain
unchanged.

Table/schema availability is not evidence of a successful or fresh workload
acquisition, authoritative zero workloads, tenant-qualified coverage, or an
exact Defender-digest deployment match. Inspect checkpoint scope, source
status, effective generation and provider observation times independently.

### AMA default-stream workload proof

The [documented AMA default Container Insights stream group](https://learn.microsoft.com/azure/azure-monitor/containers/kubernetes-monitoring-enable)
includes `ContainerInventory` and `KubePodInventory`, but not
`ContainerImageInventory`. Deployment proof requires successful acquisition of
the two supported families in the same connection/workspace generation: an
exact immutable Defender digest matched to `ContainerInventory.ImageID`, and
a `KubePodInventory` record linked by the same nonempty `ContainerID`. Both
workload provider timestamps must be valid and within the existing 15-minute
window of the real Defender provider timestamp. Tags, repositories and names
never substitute for digest or container-ID evidence.

`ContainerImageInventory` is still queried independently where available.
Fresh, time-valid exact-digest image rows may add corroborating provenance and
repository/tag metadata, but empty, absent, failed or stale supplemental image
evidence cannot block a valid two-family proof or supply a missing runtime
digest/pod link. Its query failure and partition LKG remain visible in its
checkpoint; they do not force fresh supported-family deployments to carry an
old generation. Failure of either required family retains only its existing
same-tenant deployment LKG; no LKG means unavailable, and a missing required
query means no current proof.

This source-contract alignment is not live acceptance. Generation-bound
connector/projection/persistence/readback evidence, the 100k benchmark,
canary/rollback, approvals and other release gates remain separate and unchanged.

## Failed-run recovery

1. Run `Show ingestion status` and locate the failed row.
2. Read `metadata_quality_reports` for the same `ingestion_run_id`.
3. Correct source/configuration/permission failures; never edit committed Delta log files manually.
4. Run `Validate inventory data`.
5. Run `Refresh inventory lakehouse`.
6. Confirm a later `completed` state row. Failed state remains as audit history.

Current-state Delta tables compare `resource_id` and `change_version`, skip unchanged snapshots, and overwrite changed snapshots so deletions are reconciled. The ResourceChanges feed merges by change ID. Pre-publication write failures restore prior Delta versions or remove new tables. Failures after catalog/registration commit retain coherent graph tables and record failed state for idempotent external-publication retry.

## Common failures

| Symptom | Action |
|---|---|
| Workspace/Lakehouse not found | Confirm configured immutable IDs and identity workspace role. |
| 401/403 Fabric REST | Confirm identity, tenant, Fabric API permissions, and workspace role. |
| OneLake 401/403 | Confirm OneLake access and the storage token scope. |
| Table registration timeout | Confirm Delta table is under `Tables/`, inspect `_delta_log`, then check Fabric item provisioning. |
| Data quality failure | Inspect `metadata_quality_reports`; fix missing keys, duplicates, orphans, or subscription mismatch. |
| Delta conflict/transient 429/5xx | The writer retries bounded transient failures; investigate persistent concurrent writers or throttling. |
| State says `started` after interruption | Run refresh. The same source is idempotent; a new completed or failed run is appended. |

## Scheduling

Use the existing AIOps script-only cron framework. Create a wrapper under `$AIOPS_HOME/scripts/fabric-inventory-sync.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /absolute/path/to/azure-aiops
uv run aiops-inventory fabric \
  "Sync Azure inventory to OneLake" \
  --config /absolute/path/to/fabric.config.yaml
```

Then register it:

```bash
aiops cron create "every 30m" "" \
  --name fabric-inventory-sync \
  --script fabric-inventory-sync.sh \
  --no-agent \
  --workdir /absolute/path/to/azure-aiops \
  --deliver local
```

## Sources

[1] Microsoft, “Roles in workspaces in Microsoft Fabric.” https://learn.microsoft.com/en-us/fabric/fundamentals/roles-workspaces
