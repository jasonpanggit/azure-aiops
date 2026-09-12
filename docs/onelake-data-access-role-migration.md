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

The same reconciler also owns the coordinator's narrower production-source
contract:

- workspace role: `Viewer` on the production connection workspace;
- OneLake role: `Phase13CoordinatorConnectionRead`;
- path: `/Files/aiops/connections`;
- action: `Read`;
- member: the ontology coordinator managed identity.

This lets the fixed validation prepare Job mirror one server-selected
non-production connection into the isolated validation registry without
granting the coordinator broader Fabric write access.

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
- **Isolated Azure CLI context** — ambient service-principal credentials are removed
- **Operator-invoked** — not a Terraform `local-exec`

## Migration Procedure

### Prerequisites

1. The five `fabric_onelake_data_access_security` resources were previously
   applied via Terraform and exist in the Terraform state file.
2. `AIOPS_DEPLOYER_AZURE_CONFIG_DIR` names the deployment principal's
   mode-0700 Azure CLI directory.
3. Terraform exposes the sensitive `ontology_evidence_role_contract` output.

### Step 1: Verify live roles via REST (read-only)

Write the Terraform contract to a mode-0600 temporary file:

```bash
contract_file="$(mktemp)"
chmod 0600 "$contract_file"
terraform -chdir=infra/terraform output -json \
  ontology_evidence_role_contract >"$contract_file"
source_contract_file="$(mktemp)"
chmod 0600 "$source_contract_file"
terraform -chdir=infra/terraform output -json \
  ontology_coordinator_source_role_contract >"$source_contract_file"
```

Run a dry-run to verify current state:

```bash
uv run python scripts/reconcile_onelake_data_access_roles.py \
  --contract-file "$contract_file" \
  --coordinator-source-contract-file "$source_contract_file" \
  --azure-config-dir "$AIOPS_DEPLOYER_AZURE_CONFIG_DIR" \
  --output .planning/eval/ontology-onelake-role-dry-run.json
```

Expected output for each item: `"already_converged": true` if Terraform
previously applied the roles successfully, or `"would_change": true` if the
roles need reconciliation.

### Step 2: Apply roles via REST (if needed)

If any item shows `"would_change": true`:

```bash
uv run python scripts/reconcile_onelake_data_access_roles.py \
  --contract-file "$contract_file" \
  --coordinator-source-contract-file "$source_contract_file" \
  --azure-config-dir "$AIOPS_DEPLOYER_AZURE_CONFIG_DIR" \
  --output .planning/eval/ontology-onelake-role-reconciliation.json \
  --apply
rm "$contract_file"
rm "$source_contract_file"
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
