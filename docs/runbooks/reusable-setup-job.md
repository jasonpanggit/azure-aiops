# Reusable DEV setup Job

`infra/setup-job` independently manages `aiops-dev-setup`, its dedicated
`aiops-dev-setup-id` identity, and registry-scoped AcrPull. It does not manage
the existing publication Job, broker, environment, vault or networking.

The runner is manual-only, one replica, 300-second timeout, zero retries,
0.5 CPU / 1 GiB on Consumption in the existing private-network `aiops-dev-cae`.
Its digest-pinned image supplies Python, Azure SDKs and SQL ODBC; it is not an
Azure CLI/Terraform image. The default command checks runtime dependencies,
UID and the existing vault's private DNS without obtaining tokens or reading
secrets. The image is reused unchanged; no broker process starts.

## Provisioning

Use the approved subscription/tenant with existing Azure CLI authentication or
process-scoped `ARM_*` SPN environment variables. Never print credentials or
put them in tfvars, execution templates, command arguments or source control.

Keep Terraform state and saved plans outside the checkout in a protected,
explicit deployment directory:

```bash
export TF_DATA_DIR=/absolute/protected/setup-job/terraform-data
terraform -chdir=infra/setup-job init
terraform -chdir=infra/setup-job validate
terraform -chdir=infra/setup-job plan \
  -state=/absolute/protected/setup-job/terraform.tfstate \
  -out=/absolute/protected/setup-job/create.tfplan
```

Inspect the saved plan: exactly one identity, one registry-only AcrPull assignment
and one Job create; no changes to existing resources. Apply that exact plan only
after deployment validation and approval. Preserve state, lock file and receipts.
Local state is an isolated commissioning arrangement, not a shared operational
backend; adopt a reviewed encrypted/leased remote backend before shared ownership.
Do not initialize this root against the main infrastructure state.
Pass the same explicit state path to both plan and apply: the legacy local
`-state` option on plan does not select saved-plan apply's output location.
After a partial apply, preserve actual state and generate a fresh residual
plan; never replay a stale create plan or recreate an existing identity.

```bash
terraform -chdir=infra/setup-job apply \
  -state=/absolute/protected/setup-job/terraform.tfstate \
  /absolute/protected/setup-job/create.tfplan
az containerapp job start -g aiops-dev-rg -n aiops-dev-setup
```

Verify the execution is `Succeeded` and logs contain `SETUP_JOB_READINESS` with
`status=ready`. Capture terminal readback and a subsequent no-change plan.
The provisioned identity initially has **only AcrPull**, not Key Vault, SQL,
subscription Contributor/Owner or publication authority.

## Reusing the runner

For each task, review the script, exact resource scope, identity permissions,
timeout and expected readback. Use the supported Container Apps Job execution
template override (`az containerapp job start --yaml`) to replace the `setup`
container's Python arguments for that execution, not a persistent Job update.
Preserve the pinned image, identity, container name, resources and
`AZURE_CLIENT_ID`. Do not pass SPN secrets or private signing keys.
Only trusted operators with Job execution permissions should control overrides.
The runner is not an untrusted-code sandbox.

Grant only explicitly approved task-specific permissions to its dedicated
identity, and remove temporary permissions after verified completion according
to the task's approved plan. A new task's permission assignments are not included
in runner creation approval. Serialize setup executions: manual parallelism=1
limits replicas within one execution, not concurrent executions.

Scripts must fail on errors, support exact readback after an uncertain result,
and never silently retry mutations. Log sanitized outcomes and resource IDs,
never tokens, secret values or connection strings. Do not fetch and execute
unreviewed scripts. Restore/verify the default readiness template remains
unchanged after execution-only overrides.

This runner does not select trusted reviewers, generate approval evidence,
record publication authority, lock Blob retention or cut over production.
Those are separate operations requiring their own reviewed inputs and scope.
