# OneLake Data-Access Role Migration

## Background

Phase 13 Plan 20 introduced five `fabric_onelake_data_access_security` Terraform
resources to grant the evidence identity (`azure_mcp` UAI) read-only OneLake
access to the five isolated Phase 13 Lakehouse items:

| Terraform address | Workspace | Lakehouse |
|---|---|---|
| `fabric_onelake_data_access_security.ontology_evidence_ontology_discovery_state[0]` | ontology-state | ontology_discovery_state |
| `fabric_onelake_data_access_security.ontology_evidence_ontology_command[0]` | ontology-command | ontology_command |
| `fabric_onelake_data_access_security.ontology_evidence_ontology_dispatch[0]` | ontology-dispatch | ontology_dispatch |
| `fabric_onelake_data_access_security.ontology_evidence_ontology_publication[0]` | ontology-publication | ontology_publication |
| `fabric_onelake_data_access_security.ontology_evidence_ontology_rbac_validation[0]` | ontology-rbac-validation | ontology_rbac_validation |

Each role was named `Phase13EvidenceRead` with:
- **Path:** `*` (all paths in the Lakehouse)
- **Action:** `Read` (read-only)
- **Member:** `ManagedIdentity` with the `azure_mcp` UAI `principal_id`

## Problem

The Fabric Terraform provider version 1.13 has a **ManagedIdentity
round-tripping bug**: when the provider reads back a
`fabric_onelake_data_access_security` resource whose member has
`objectType = "ManagedIdentity"`, the read response does not preserve the
`objectType` field correctly, causing Terraform to detect perpetual drift and
propose a replacement on every plan. This makes the resources unmanageable
through Terraform.

## Replacement

The five roles are now managed by a deterministic, idempotent REST
reconciliation script:

```
scripts/reconcile_onelake_data_access_roles.py
```

This script uses the official Fabric REST API:

```
PUT /v1/workspaces/{workspaceId}/items/{itemId}/dataAccessRoles
```

Key properties:
- **Preserves unrelated roles** in the PUT payload
- **ETag If-Match** preconditions for optimistic concurrency
- **Dry-run** mode before any write
- **Bounded retries** on 412/429 with refetch and recompute
- **Post-write GET verification** proves exact desired state
- **DefaultAzureCredential** — no secrets on CLI
- **Operator-invoked** — not a Terraform `local-exec`

## Migration Procedure

### Prerequisites

1. The five `fabric_onelake_data_access_security` resources were previously
   applied via Terraform and exist in the Terraform state file.
2. You have operator access to the deployment subscription with
   `DefaultAzureCredential`.
3. You have the workspace and lakehouse IDs from Terraform outputs.

### Step 1: Verify live roles via REST (read-only)

Create an items JSON file with the five targets:

```bash
cat > /tmp/evidence-items.json << 'EOF'
[
  {"name": "ontology_discovery_state", "workspace_id": "<STATE_WS_ID>", "item_id": "<STATE_LH_ID>"},
  {"name": "ontology_command", "workspace_id": "<COMMAND_WS_ID>", "item_id": "<COMMAND_LH_ID>"},
  {"name": "ontology_dispatch", "workspace_id": "<DISPATCH_WS_ID>", "item_id": "<DISPATCH_LH_ID>"},
  {"name": "ontology_publication", "workspace_id": "<PUB_WS_ID>", "item_id": "<PUB_LH_ID>"},
  {"name": "ontology_rbac_validation", "workspace_id": "<RBAC_WS_ID>", "item_id": "<RBAC_LH_ID>"}
]
EOF
```

Run a dry-run to verify current state:

```bash
uv run python scripts/reconcile_onelake_data_access_roles.py \
  --items-json /tmp/evidence-items.json \
  --object-id <AZURE_MCP_PRINCIPAL_ID> \
  --tenant-id <TENANT_ID>
```

Expected output for each item: `"already_converged": true` if Terraform
previously applied the roles successfully, or `"would_change": true` if the
roles need reconciliation.

### Step 2: Apply roles via REST (if needed)

If any item shows `"would_change": true`:

```bash
uv run python scripts/reconcile_onelake_data_access_roles.py \
  --items-json /tmp/evidence-items.json \
  --object-id <AZURE_MCP_PRINCIPAL_ID> \
  --tenant-id <TENANT_ID> \
  --apply
```

Verify all items return `"verified": true`.

### Step 3: Remove old resources from Terraform state

**Only after Step 2 confirms all five items are verified**, remove the old
Terraform state entries. These `state rm` commands do **not** destroy the live
roles — they only remove Terraform's tracking of them:

```bash
terraform state rm 'fabric_onelake_data_access_security.ontology_evidence_ontology_discovery_state[0]'
terraform state rm 'fabric_onelake_data_access_security.ontology_evidence_ontology_command[0]'
terraform state rm 'fabric_onelake_data_access_security.ontology_evidence_ontology_dispatch[0]'
terraform state rm 'fabric_onelake_data_access_security.ontology_evidence_ontology_publication[0]'
terraform state rm 'fabric_onelake_data_access_security.ontology_evidence_ontology_rbac_validation[0]'
```

### Step 4: Verify clean Terraform plan

```bash
terraform plan
```

The plan should show **no changes** related to `fabric_onelake_data_access_security`
resources. The five `fabric_workspace_role_assignment.ontology_evidence_*`
resources remain Terraform-managed and should show no drift.

## Safety Constraints

- **Never run `terraform state rm` before live REST verification.** The state
  entries are the only record of Terraform's ownership; removing them before
  confirming the REST roles exist would leave the roles unmanaged and
  unverifiable.
- **Never run `terraform state rm` automatically.** Each removal must be an
  explicit operator step after reviewing the verification output.
- **The REST script preserves unrelated roles.** The PUT payload merges the
  desired `Phase13EvidenceRead` role with all existing roles on the item. No
  unrelated roles are removed or modified.
- **The REST script fails closed.** If post-write verification detects any
  drift from the desired state, the script raises an error and returns
  non-zero. No silent failures.

## Future

When the Fabric Terraform provider fixes the ManagedIdentity round-tripping
bug, these roles can optionally be imported back into Terraform management via
`terraform import`. Until then, the REST reconciliation script is the
authoritative management path.
