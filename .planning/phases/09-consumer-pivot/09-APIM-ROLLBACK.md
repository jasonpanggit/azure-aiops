# APIM MCP rollback runbook

The rollout is opt-in and reversible. `deploy.sh apply` captures a pre-apply
snapshot under `AIOPS_DEPLOY_ARTIFACT_DIR` (default: the system temporary
directory). Use a directory with mode `0700`; snapshots can contain backend
URLs and policy configuration, but must never contain bearer tokens, client
secrets, or Terraform state.

## Preflight

```bash
export AIOPS_DEPLOY_ARTIFACT_DIR=/secure/aiops-deploy-artifacts
chmod 700 "$AIOPS_DEPLOY_ARTIFACT_DIR"
./infra/scripts/deploy.sh plan -out="$AIOPS_DEPLOY_ARTIFACT_DIR/apim.tfplan"
terraform -chdir=infra/terraform show -no-color "$AIOPS_DEPLOY_ARTIFACT_DIR/apim.tfplan" >/dev/null
```

Record the plan filename and snapshot directory in the change ticket. Do not
copy `terraform.tfstate` into the artifact directory. A remote, access-
controlled Terraform backend should provide state version history; with local
state, the existing `terraform.tfstate.backup` is the only state rollback
source and must remain operator-controlled.

## Disable / restore

Stop the forward rollout if apply fails. Do not retry an unknown partial apply.
Choose the snapshot printed by `deploy.sh apply`, then restore only resources
confirmed present in that snapshot:

```bash
export AIOPS_APIM_ROLLBACK_SNAPSHOT=/secure/aiops-deploy-artifacts/apim/<timestamp>
./infra/scripts/rollback-apim-mcp.sh
./infra/scripts/deploy.sh plan
```

The restore is idempotent: rerunning it imports the same API definition and
sets the same saved policies. It does not delete the APIM service or unrelated
APIs. If the prior route was disabled, restore the saved policy and then set
the API/revision state in the portal or with the documented APIM CLI command;
never infer a missing snapshot.

## Acceptance tests

1. `GET`/MCP initialize on the prior route returns its known healthy status.
2. The MCP route is disabled or inaccessible when the rollout is disabled.
3. `terraform plan` reports no unexpected APIM drift after restore.
4. No token, client secret, or authorization header appears in artifacts:
   `grep -R -E 'Bearer |client_secret|AIOPS_MCP_BEARER_TOKEN' "$AIOPS_DEPLOY_ARTIFACT_DIR"`

State restore is a backend/platform operation and is deliberately not
automated by this script. Use the backend's version restore procedure, then
rerun `terraform plan` before any apply.
