# Azure Deployment Plan

## Coordinated release (2026-10-30)

Status: Validated
Validation scope: existing image-bearing Container Apps only. The full
Terraform plan remains blocked and must not be applied. The exact post-build
plan must still be reviewed before any apply.

Objective: integrate the completed, bounded changes and release them once from
the final `main` revision. Preserve current production behavior, API sizing, and
Network behavior.

Scoped rollout: target only `azurerm_container_app.api`,
`azurerm_container_app.web`, `azurerm_container_app.mcp_server`, and
`azurerm_container_app.azure_mcp` after the final images are built from merged
`main`. Do not apply APIM, Fabric workspace/Data Agent, role-assignment, or Job
changes from the broader plan. The post-build plan must contain no creates or
destroys; preserve API 4 CPU/16 GiB, NVD configuration, native-ontology
configuration, and the absence of a deployer-SPN gateway grant. Stop before
apply if the exact plan exceeds this scope or changes those invariants.

Included: optional managed-identity Key Vault configuration transport (empty
by default); the reusable manual-only setup Job and its existing
registry-scoped `AcrPull` identity; the disabled, non-operable publication
backend Terraform preparation, whose only conditional assignment is
registry-scoped `AcrPull` and which has no artifact-writer assignment; the
standalone, create-only immutable Blob artifact verifier; bounded Copilot evaluation
snapshot-schema validation; combined-snapshot source provenance; the narrow
26-hour freshness policy for the two daily inventory products; bounded
transient retries for Azure Resource Graph and Cost Management; and collector
setup validation. The validation-only collector gateway grant remains
inactive under the production environment default.

Excluded: incomplete publication broker client/transport prototypes and their
tests, because their immutable-attempt protocol and test fixture are absent.
The `78f9fa72` Foundry Project Manager assignment is excluded and has been
reverted by `d7476f54`; it was outside the approved no-grant scope, and its
auth-mode change did not resolve live parity for the deployment SPN. The quarantined
`aiops-api:compliance-bounded-39080ceba-20260912T1156Z` image must not be
deployed.

### Inclusion/exclusion manifest

| Candidate | Owner/evidence | Decision |
|---|---|---|
| `e7edb5dd` | Existing commit author; scoped collector/setup changes, targeted tests passed | Include only under the current `production` default; its subscription-reader gateway grant is conditional on the validation environment and is not activated by this release |
| `9872811f` | Existing commit author; source-provenance binding, `test_combined_source_provenance.py` passed | Include, subject to complete validation |
| `b9af7598` | Existing commit author; daily inventory freshness policy, `test_inventory_freshness_policy.py` passed | Include; limited to the two declared inventory products and not consumer-readiness evidence |
| `0f8d9499` | Existing commit author; bounded Azure acquisition retries, `test_arg_transient_retry.py` passed | Include, subject to complete validation |
| `43a1a530` | Existing commit author; setup readiness, immutable artifact, maintenance-admission, and Terraform contract tests | Include, subject to complete validation |
| `6784295c` | Existing commit author; Copilot evaluation schema tests | Include, subject to complete validation |
| `78f9fa72` | Existing commit author; introduces `deployer_spn_foundry_manager` role assignment; no grant authorization | Exclude; reverted by `d7476f54` |
| `d7476f54` | Reverts the unapproved Foundry Project Manager assignment | Include; preserve the no-new-grant boundary |
| `19efd404` | Specialist parity regression tests pass; live generic-catalog comparison passes, while API authorization remains a separate blocker | Include; no grant or activation change |
| `4e9935f7` | 16 Terraform contract tests, formatting, and validation pass; scoped plan is 0 add / 2 change / 0 destroy, but the full plan remains unsafe | Include as production-safety alignment; do not apply the full plan |
| PR `#51` | Its relevant role, runtime, and evidence-test contracts are already represented in the release tree; the old-base patch would replace newer runtime behavior | Do not replay the stale patch |
| PR `#53` | Revision-bound runtime evidence emission and strict case-derived gates are already present in `origin/main` and the release tree | No additional integration required |
| Data Agent checkpoint `160c0c6e` | Core definition/configuration code is already in `origin/main`; remaining differences remove newer Fabric LRO/telemetry and consumer-inventory behavior, broaden a capacity Reader assignment, and remove the deployer workspace role. The deployer sees `aiops-dev-ops` (`2c1fea36-104d-4c26-86db-12e09e432b41`), not requested workspace `1c328da7-2490-48dc-9ba6-de8c1f333756`; item `8a8cf431-f881-46a0-b669-463d4c1d5535` was not found in either workspace | Do not replay regressions, change roles, create, import, or repoint the Data Agent |
| Main-sync commits `11ba8979`, `c24eae07`, `22a6ee37`, `ea8382f8` | Merge/alignment commits; no independent tree changes | Retain ancestry only; upstream main content is already in the baseline |
| Untracked publication-broker prototypes | Ownership/evidence not established; required immutable-attempt module is absent | Exclude and leave untouched |
| PR `#428` | Already merged to `main` as `1b8829a45bb8254e509ca2b97816da5ef56c5c63` | Already on baseline; not a new candidate |

Safety: no trust secret, key, gateway grant, authority row, or trust activation
is applied by this release. The validation-only collector gateway grant stays
inactive under the production environment default. The optional Key Vault
input remains unset. The setup Job's only standing permission remains
registry-scoped `AcrPull`; the publication backend remains disabled and
unqualified. Preserve the observed live API baseline of 4 CPU/16 GiB and
existing Network behavior.

## All validation checks pass (pre-deployment scope; post-merge gates pending)

Validation evidence is recorded below. The full Terraform plan is explicitly
out of scope and remains unsafe to apply; the pre-build, four-app targeted plan
has 0 additions, 3 updates, and 0 destroys. The exact post-build plan and
deployment-specific checks are still required before validation can complete.

### Terraform validation recipe (`infra/terraform`)

- [x] Terraform is installed.
- [x] Azure CLI is installed.
- [x] Azure CLI authentication is valid and subscription
      `890c9bfc-d09c-4143-9ce5-465e75e3eecc` is selected.
- [x] `terraform init -input=false` completed for the application root.
- [x] `terraform fmt -check -recursive` passed.
- [x] `terraform validate` passed.
- [x] Generate and inspect the refresh-enabled full `terraform plan`. It
      proposes 23 additions, 9 changes, and 4 destroys; this plan is rejected
      for deployment and must not be applied.
- [x] Generate and inspect the canonical, pre-build targeted plan using
      `environments/dev.native-ontology.tfvars`; it proposes 0 additions,
      3 updates, and 0 destroys for the scoped rollout. This is not the final
      post-build plan.
- [x] Inspect the application root's Terraform state list.
- [x] Scan for unresolved `{{ .Env.* }}` templates.
- [x] Check `main.tfvars.json` syntax; the file is absent, so the recipe skips
      this check.
- [x] Run the official Terraform preflight with the scoped inputs and restore
      the pre-existing `infra/terraform/tfplan` byte-for-byte. The corrected
      run passed every applicable check; `main.tfvars.json` was absent and
      skipped. See the timestamped proof below.

### Release-specific validation

- [x] Run the complete local Python suite: 9,487 passed, 1 intentional skip;
      Ruff and Terraform contract tests passed.
- [x] Run web ESLint, Vitest (1,993 tests across 151 files), and production
      build. Build completed with 29 pages generated; MSAL static-generation
      `window is not defined` logs were observed.
- [x] GitHub PR checks passed: backend shards, frontend, security scan, and
      Trivy. GitHub Actions failures before job steps were infrastructure
      billing failures and are not treated as validation evidence.
- [x] Static scope review confirms no deployer-SPN gateway grant, role
      assignment, Fabric Data Agent/workspace, APIM, or Job change is included
      in the narrowed app-only rollout.

### Role assignment verification — four-app scope

- The targeted Terraform plan contains no role-assignment resources or changes.
  No role assignment was mutated by this rollout.
- The API/web shared identity's seven live assignment triples exactly match
  the preserved pre-deployment snapshot: registry-scoped `AcrPull`, project-
  scoped Foundry Agent Consumer / Foundry Project Runtime User / custom prompt
  runtime roles, account-scoped custom response runtime, vault-scoped Key Vault
  Secrets Officer, and Fabric-capacity Reader. The snapshot does not contain a
  Virtual Machine Contributor assignment; the earlier static expectation for
  that role was not supported by live state.
- The post-deployment read of the MCP identity returned vault-scoped Key Vault
  Secrets User and no Reader assignment in this subscription. Other
  subscriptions were not assessed by this read. The Azure MCP identity returned
  registry-scoped `AcrPull` plus subscription-scoped Reader and Monitoring
  Reader. The protected pre-deployment role snapshot covers only the shared
  API/web identity, so equality to a pre-deployment MCP/Azure MCP snapshot is
  not claimed.
- These readbacks correct the earlier static expectations; they are not
  evidence of release-caused drift. The four apps retain username/password
  registry configuration, so the existing managed-identity `AcrPull`
  propagation gate is not applicable. No deployer-SPN gateway grant or new
  role assignment is included.
- Azure pre-deploy context: current subscription
  `ME-MngEnvMCAP448721-pangj-1`
  (`890c9bfc-d09c-4143-9ce5-465e75e3eecc`) matches the validated Terraform
  inputs. All four existing apps report `Australia East`; no new region or
  resource is planned. `azure.yaml` is absent, so AZD environment/provisioning
  steps do not apply.
- The Container Apps use ACR username/password configuration rather than
  managed-identity registry authentication: Terraform has
  `enable_role_assignments=false`, and live registry configuration reports a
  blank identity plus a configured username for API, web, MCP, and Azure MCP.
  Therefore the managed-identity `AcrPull` propagation gate is not applicable;
  no `azd provision` or role mutation was run. Existing ACR authentication
  configuration is outside this rollout and remains unchanged.

### Section 7: Validation Proof — scoped app-only release

- Timestamp: `2026-10-30T05:08:30Z`.
- Official recipe command:
  `bash /Users/jasonmba/.agents/skills/azure-validate/references/recipes/terraform/scripts/validate-terraform.sh infra/terraform 890c9bfc-d09c-4143-9ce5-465e75e3eecc`.
  Process-local Terraform inputs were parsed from `web/.env.local` using the
  repository deployment script's supported mapping. The plan was restricted
  with `environments/dev.native-ontology.tfvars` and the four existing app
  targets. Terraform installed, Azure CLI installed/authenticated, subscription
  selected, init, fmt, validate, plan, state list, and template scan all passed;
  absent `main.tfvars.json` was skipped. The earlier unconfigured invocation
  failed because required `TF_VAR_*` inputs were not supplied; it made no
  infrastructure changes and was superseded by this passing run.
- Credential-backed target-plan command:
  `./infra/scripts/deploy.sh plan -no-color -var-file=environments/dev.native-ontology.tfvars -target=azurerm_container_app.api -target=azurerm_container_app.web -target=azurerm_container_app.mcp_server -target=azurerm_container_app.azure_mcp`.
  Result: 0 additions, 3 in-place updates, 0 destroys (`api`,
  `mcp_server`, and `terraform_data.foundry_specialist_promotion_gate`).
  No API CPU/memory diff was present. This is a pre-build plan, not approval
  to apply; the exact post-build plan remains a release execution gate.
- The active specialist-promotion artifact was independently checked without
  exposing its contents: status validated, current manifest digest matched,
  exact 12-specialist ID set and provider-version IDs were present, and the
  coordinator provider ID was present.
- Current Azure context and registry mode were checked read-only:
  `az account show --query '{name:name,id:id}' -o json` matched the planned
  subscription; `az containerapp show` reported Australia East and
  username/password registry auth for all four existing apps. The managed-
  identity-only AcrPull propagation gate is not applicable to this plan.
- The full unscoped Terraform plan remains rejected (23 additions, 9 changes,
  4 destroys) and was not applied. The pre-existing
  `infra/terraform/tfplan` was restored with SHA-256
  `553c77d3b29b02ab3e4fb6759b5753fafea36fc0e6b03a4284edf0afe8665492`.
- Local source validation at release HEAD passed: Python suite 9,487 passed
  with 1 intentional skip; Ruff and Terraform contract tests passed; web
  ESLint passed; Vitest passed 1,993 tests across 151 files; and `next build`
  completed with 29 pages. GitHub checks for PR #429 passed (backend shards,
  frontend, security scan, and Trivy). The build's existing MSAL static
  generation `window is not defined` logs did not fail the build.

## Release execution gates (after merge)

- [x] Build all four application images once from the final merged `main`
      commit.
- [x] Generate and review the exact post-build targeted plan. Proceed only if
      it has no creates or destroys and preserves API 4 CPU/16 GiB, NVD,
      native-ontology, Network, and gateway-grant invariants.
- [x] Verify deployed digests, healthy revisions, live role assignments, API
      sizing, and Network behavior. Do not claim release completion until these
      checks pass.

Deployment: after committing and merging the validated release, use the
repository's `build-and-push.sh` once for all four application images, then
`deploy.sh apply`. Verify the deployed API/web digests, healthy revisions,
baseline API sizing, Network behavior, and runtime readiness. Do not rebuild or
deploy any candidate until the final merged `main` commit is known.

### Post-deployment verification (2026-10-30)

- Source: merged `main` commit `ee7dcceccb7952e6405a8312d3f2875c60d80c63`.
  The four images were built once with tag
  `release-ee7dcce-20261030-052958`. The reviewed targeted apply contained
  0 additions, 5 in-place changes, and 0 destructions.
- All four latest-ready revisions are provisioned, Healthy, have one ready
  replica, and receive 100% traffic:

  | App | Revision | Image digest | Resources |
  | --- | --- | --- | --- |
  | API | `aiops-dev-api--0000013` | `sha256:d647ed2f17c892ac442a801a8afd71e94e9d437dc8dbc3bb53d5b5b0ac30cbd0` | 4 CPU / 16 GiB |
  | Web | `aiops-dev-web--0000029` | `sha256:40626158ca36d2cc170c32910ea0e386dfb7462403c4aeb702128ed645fe7846` | 0.5 CPU / 1 GiB |
  | MCP server | `aiops-dev-mcp-server--0000007` | `sha256:04849072f7332a9e7b2a992c301ed38b4ca004bfaf12f6448009d9ed314da1e6` | 0.5 CPU / 1 GiB |
  | Azure MCP | `aiops-dev-azure-mcp--0000001` | `sha256:4a77d0fb457f3c6c041f5e5dd3ce800497d314df51d2c3f22075f95658baf6f4` | 0.5 CPU / 1 GiB |

- API `/health` is ready; web `/` returns HTTP 200; MCP `/health` reports
  healthy. Azure MCP's HTTP `/health` returns 405 by design; its revision is
  Healthy under the configured TCP health check. An authenticated
  `/api/v1/network/summary` read returned HTTP 200 without warnings, and
  `tests/test_api_network.py` passed against the merged release source.
- The API remains 4 CPU / 16 GiB. Live shared API/web identity assignments
  exactly match the saved pre-deployment assignment snapshot (7 of 7; no
  additions or removals). MCP and Azure MCP live assignments are recorded in
  the role-verification section above; no role changes were part of the plan.
- The unused zero-traffic API revision `aiops-dev-api--r420-99193f04` was
  deactivated only to free the existing profile slot; the healthy
  `aiops-dev-api--f03-b841d1ce` fallback was retained. No profile increase,
  broad Terraform apply, role mutation, or Network configuration change was
  made. The API's `RunningAtMaxScale` state is Healthy with one ready replica.

### Validation attempt (2026-10-29)

- Official Terraform preflight: Terraform/Azure CLI/authentication, subscription
  selection, init, formatting, validate, state list, and template scan passed;
  `main.tfvars.json` was absent and skipped.
- Terraform plan was not applied and failed the existing specialist promotion
  gate: the validated artifact digest does not match the current manifest, and
  the active target lacks an exact validated provider-ID mapping.
- Live parity's Operations MCP 401 is not an issuer or audience mismatch: a
  read-only SPN probe confirmed its token tenant and audience match the deployed
  APIM policy. The API rejected the SPN because its principal ID has no entry in
  `AIOPS_API_GATEWAY_GRANTS`; APIM intentionally strips caller-supplied roles,
  and the API authorizes only explicitly configured subjects. No new grant was
  authorized, so keep this gate blocked rather than broaden the SPN's read
  access. Source review confirms an empty scope is explicitly unrestricted;
  there is no safe catalog-only, grant-free bypass to use for parity.
- The pre-existing `infra/terraform/tfplan` was restored after the preflight.
  Leave the plan status unchanged; validation is blocked.
- A credential-backed `infra/scripts/deploy.sh plan -no-color` loaded the
  configured inputs and reached the active Terraform state, but failed both
  specialist promotion preconditions: the candidate digest is stale and the
  active target has no exact provider-ID mapping. The complete plan action set
  was reviewed (20 adds, 8 updates, 2 destroys). Adds:
  `azurerm_api_management_api.mcp[0]`,
  `azurerm_api_management_api.mcp_proxy[0]`,
  `azurerm_api_management_api_operation.mcp_proxy_health[0]`,
  `azurerm_api_management_api_operation.mcp_proxy_subscriptions[0]`,
  `azurerm_api_management_api_operation.mcp_proxy_tool[0]`,
  `azurerm_api_management_api_policy.mcp[0]`,
  `azurerm_api_management_api_policy.mcp_proxy_inbound[0]`,
  `azurerm_api_management_product.azure_mcp[0]`,
  `azurerm_api_management_product.mcp[0]`,
  `azurerm_api_management_product_api.mcp[0]`,
  `azurerm_container_app_job.inventory_publication[0]` (replacement),
  `azurerm_container_app_job.ontology_fixture_cleanup[0]`,
  `azurerm_container_app_job.ontology_fixture_prepare[0]`,
  `azurerm_container_app_job.ontology_rbac_validation[0]`,
  `azurerm_container_app_job.patch_publication[0]`,
  `fabric_data_agent.ai_ops[0]`,
  `fabric_lakehouse.ontology_rbac_validation[0]`,
  `fabric_workspace.ontology_rbac_validation[0]`,
  `fabric_workspace_role_assignment.ontology_publisher[0]`, and
  `fabric_workspace_role_assignment.patch_publisher[0]`.
  Updates: `azapi_resource.azure_mcp_server_policy[0]`,
  `azapi_resource.mcp_server_policy[0]`,
  `azurerm_container_app.mcp_server`,
  `azurerm_container_app_environment.main`,
  `azurerm_container_app_job.exposure_enrichment`,
  `azurerm_container_app_job.exposure_prefetch`,
  `azurerm_container_app_job.ontology_discovery`, and
  `azurerm_container_app_job.ontology_publisher`. Destroys:
  `azurerm_container_app_job.inventory_publication[0]` (old instance of the
  replacement) and `azurerm_role_assignment.deployer_spn_foundry_manager[0]`.
  These broad resource changes are not approved for this candidate; no plan
  was applied.
- `fabric_data_agent.ai_ops[0]` is absent from Terraform state. A read-only
  Fabric lookup using the configured deployment SPN returned 404 for the
  required item ID `8a8cf431-f881-46a0-b669-463d4c1d5535`. This is not proof
  that the item does not exist: the signed-in Fabric UI account was denied
  access to target workspace `1c328da7-2490-48dc-9ba6-de8c1f333756` and
  redirected to My workspace. The accessible `aiops-dev-ontology-publication`
  workspace (`4938f885-3e79-41b1-810a-80b55c01dbb7`) contains four items
  (publication SQL database/endpoint and ontology Lakehouse/endpoint); an exact
  ID search there returns no result. It is a different workspace, so this does
  not establish whether the target item exists. The plan would create a new
  item rather than import the requested ID. Do not create or import a
  replacement until an authorized workspace reader confirms the live item and
  ID.
- The signed-in UI opens `aiops-dev-ops`
  (`2c1fea36-104d-4c26-86db-12e09e432b41`), matching Terraform state's
  `fabric_workspace_id`. Its 10 listed items include
  `operational_context_graph_v2` Lakehouse
  (`f995229d-970e-44ec-8af5-df9e25261d19`) but no Data-Agent entry.
  `fabric.config.deploy.yaml` instead pairs that workspace name with ID
  `1c328da7-2490-48dc-9ba6-de8c1f333756`, Lakehouse
  `6317eaf6-e597-4b4e-a07d-c53027c01feb`, and Data Agent
  `8a8cf431-f881-46a0-b669-463d4c1d5535`. A global UI search for that exact
  item ID returned no result, and FabricIQ resolution is unavailable pending
  reauthentication. This is a workspace/lakehouse/item configuration drift,
  not an issuer mismatch. Do not repoint the runtime config or create a
  replacement: its source-data path and SQL endpoint are also tied to the
  configured IDs, and the intended live Data Agent remains unverified.
- FabricIQ's `ResolveFabricItem` lookup could not be completed because the
  FabricIQ MCP server requires reauthentication; no retry was attempted.
- The first direct Terraform preflight omitted the required `TF_VAR_*` inputs.
  The official preflight was repeated with the service-principal inputs read
  from `web/.env.local`, matching `infra/scripts/deploy.sh`; Terraform
  installed/authenticated, init, fmt, validate, state list, and template scan
  passed, while the plan failed the specialist-promotion digest and
  provider-ID preconditions. `main.tfvars.json` was absent and skipped.
  `infra/terraform/tfplan` was restored and its SHA-256 remained
  `5bd57c9f046fa8c8047359e5ac730ac779446f22d0f6257060f9a812f40e043d`.
  The complete credential-backed plan contains 20 additions, 8 updates, and 2
  destroys, including unapproved workspace Contributor assignments and
  existing-job changes; no plan was applied.

### Section 7: Validation Proof — coordinated release (2026-10-29)

- `python -m pytest -q` passed for the complete Python suite on clean candidate
  `6784295c` (one intentional skip). After removing the excluded Foundry role
  change, focused Foundry parity/contract tests and Ruff passed on
  `d7476f54`.
- `terraform fmt -check -recursive` and `terraform validate` passed after the
  revert. The earlier full preflight's plan step remains blocked by the
  specialist promotion artifact digest/provider-ID mapping; no plan was applied.
- Web lint passed; Vitest passed all 151 files / 1,993 tests with the
  repository virtualenv added to `PATH` as an absolute path (the subprocesses
  run from the repository root); `next build` completed successfully.
- `78f9fa72`'s unapproved role assignment and auth-mode change were removed by
  conventional commit `d7476f54`. No new grant or trust change was made.
- Candidate-scoped Ruff passed. The isolated publication-backend Terraform
  root passed formatting, validation, and all 24 Terraform tests; the reusable
  setup-job root passed formatting and validation. The complete Python suite
  reached 100% on exact `d7476f54`, but its single failure was the global
  namespace placeholder guard scanning `tests/test_publication_broker_client.py`
  from the excluded untracked prototypes; one intentional test skip occurred.
-  A full run from a Git archive is not valid evidence because five network
  contract tests require historical Git objects that archives omit. The clean
  detached Git worktree, excluding the unrelated untracked prototypes while
  retaining repository history, completed the full suite with exit code 0 and
  one intentional skip.
- Candidate Python Ruff and `git diff --check` passed. The frontend lint and
  `next build` passed; the build logged existing MSAL `window is not defined`
  messages during static generation but completed all 29 routes.
- Focused tests for the branch-only collector/setup, provenance, inventory
  freshness, retry, immutable-artifact, setup-job, publication-backend, and
  Copilot evaluation changes all passed. A clean detached worktree run of the
  complete Python suite is still in progress.
- The credential-backed official Terraform preflight passed authentication,
  init, format, validation, state, and template checks; the plan step failed
  the active specialist digest and exact provider-ID preconditions. Live
  specialist parity also fails with Operations MCP HTTP 401. Its offline
  parity checks all pass, and the available 12-specialist artifact is only
  `candidate` (its manifest digest matches, but it is not validated).
- A read-only live parity retry with the existing Azure CLI identity reached
  Foundry and Operations MCP. Foundry version lookups completed for all 12
  specialists and the coordinator; the only parity failures were the live
  global catalog lacking `governance_summary`, `identity_summary`, and
  `finops_summary`. The catalog contains 26 legacy tools. This matches the
  server contract: `tools/list` returns the legacy catalog when no specialist
  identity is present, while specialist-specific tools require
  `principal.mcp_specialist_id()`. Terraform's separate specialist-identity
  connection is default-off and requires a complete, distinct principal map
  for the manifest. Do not enable it or add grants without authorization.
- Validation remains incomplete: live parity still returns 401 because the
  deployment SPN is not in `AIOPS_API_GATEWAY_GRANTS`; the Azure CLI identity
  probe instead exposes the legacy catalog and cannot satisfy the
  specialist-specific tool gate. The Terraform promotion artifact/provider-ID
  gate also remains unsatisfied. Do not mark the plan `Validated`, merge,
  build release images, or deploy.

### Validation continuation (2026-10-29)

- The user approved only narrowly scoped gateway grants for verified Foundry
  specialist identities; this does not authorize changing the operator-owned
  issuer or unrelated role assignments. Read-only GETs of all twelve deployed
  specialist agents returned distinct `instance_identity.principal_id` values.
  All twelve principals differ from the shared project identity and existing
  grant subjects. The four responses without an identity status field still
  returned principal IDs whose Entra service principals exist and are enabled.
- A Terraform plan with the reviewed identity map was not applied. It proposed
  21 additions, 8 updates, and 2 destroys, including the new specialist
  identity MCP connection, broad APIM and Container Apps changes, a new Fabric
  Data Agent, two Fabric workspace role assignments, and removal of the
  Foundry manager assignment. The plan still fails the active promotion
  digest and exact provider-ID mapping preconditions. Do not apply this plan
  or target away those failures.
- Candidate-scoped Ruff, Python compilation, and `git diff --check` pass. The
  clean full Python suite completed successfully with one intentional skip.
  Repository-wide Ruff remains non-green due 20 findings in three unchanged
  baseline scripts; no unrelated lint fixes were made.
- No gateway grant or specialist identity connection has been applied. The
  deployment remains blocked; keep runtime grounding and the current
  specialist activation target unchanged, and do not mark validation complete,
  merge, build, or deploy.

### Validation continuation (2026-10-30)

- The configured deployment SPN authenticated successfully in an isolated Azure
  CLI profile. Its observed Azure roles are subscription `Contributor`,
  `Foundry Project Manager` on the existing Foundry project, and AKS namespace
  `Azure Kubernetes Service RBAC Writer`. The SPN is not a subject in the
  configured API gateway grant map; no gateway grant was added.
- The Fabric capacity is `Active` (F8). The SPN's Fabric API workspace listing
  returned five visible workspaces, none with the configured workspace ID
  `1c328da7-2490-48dc-9ba6-de8c1f333756`. The configured Data Agent ID
  `8a8cf431-f881-46a0-b669-463d4c1d5535` returned 404. The visible
  `aiops-dev-ops` workspace is `2c1fea36-104d-4c26-86db-12e09e432b41` and is
  not a substitute; do not create, import, grant access, or repoint it.
- The persisted promotion artifact is currently `validated`/`promoted`, its
  manifest digest matches `src/operations/specialists.v1.json`, and its
  recorded live/offline parity is pass. A fresh read-only live parity run using
  the already-authorized Azure CLI operator identity and the exact candidate
  mapping also passed. This resolves the prior parity/promotion precondition
  report without adding an SPN grant.
- A fresh refresh-enabled Terraform plan exited successfully but proposes
  23 additions, 9 changes, and 4 destroys. It includes APIM API/product
  creation, new or replaced Jobs, Foundry candidate resource recreation,
  creation of the unverified Fabric Data Agent/workspace resources and
  workspace role assignments, and deletion of the Foundry manager role
  assignment. Do not apply it.
- A canonical, read-only plan targeted to the four image-bearing Container
  Apps, generated through `infra/scripts/deploy.sh` with `web/.env.local` and
  `-var-file=environments/dev.native-ontology.tfvars`, proposed 0 additions,
  3 updates, and 0 destroys at the current pre-build tag. It preserves the API
  at 4 CPU/16 GiB, the NVD API-key secret/environment reference, and the native
  ontology workspace/item environment references; the configured deployment
  SPN is absent from the planned gateway grants.
- That targeted plan still changes API candidate metadata, specialist
  versions/digest, gateway grants, and traffic routing from the currently
  active `f03-b841d1ce` revision to a new planned `0000012` revision while the
  image digest is unchanged. It also changes the MCP operations URL and the
  Foundry promotion-gate fingerprints. A read-only live revision query
  confirmed `f03-b841d1ce` currently serves 100% of API traffic and `0000012`
  is not yet present. This is a pre-build plan, not authorization to apply;
  review the exact post-build changes before any rollout.
- The official `azure-validate` Terraform preflight completed successfully:
  `terraform init`, `fmt -check`, `validate`, `plan`, `state list`, and the
  template-variable scan passed. Its full plan still contains the unapproved
  23 additions, 9 changes, and 4 destroys above, so this is not deployment
  authorization. The pre-existing user-dirty `infra/terraform/tfplan` was
  restored and its SHA-256 verified unchanged after the preflight.
- The shared-worktree full Python run fails only because the excluded,
  untracked publication-broker prototypes are scanned by the global storage
  placeholder test. The clean detached exact-HEAD full suite completed with
  exit code 0: 9,487 passed and 1 intentional skip. The validation worktree
  remained clean.
- Web validation passed: ESLint reported no warnings/errors; Vitest passed all
  1,993 tests across 151 files when run with the repository virtualenv on
  `PATH`; and `next build` exited 0 after compiling, type-checking, and
  generating all 29 static pages. MSAL emitted `window is not defined` logs
  during static generation, but the build completed successfully.
- GitHub checks for open PR #429 also completed successfully (backend test
  shards, frontend, security scan, and Trivy); the earlier billing-blocked
  check state is no longer current.
- No release image was built or pushed; nothing was merged, applied, or
  deployed. Keep the release blocked pending authorization of the narrowed
  rollout scope: the full Terraform plan remains unsafe, and the configured
  Fabric Data Agent workspace/item is not accessible to the deployment SPN.
  The separate existing-Container-App-only plan has no creates or destroys,
  but its exact post-build changes must be reviewed before applying. Do not
  create/repoint the Fabric target or delete existing authorization to bypass
  those gates.

## Role Assignment Verification (2026-10-29)

- Status: Verified by static Terraform review only; no live role state queried.
- Identities checked: application, MCP server, ontology coordinator, ontology
  publisher, reusable setup Job, and publication-backend verifier.
- Roles confirmed: application Key Vault Secrets Officer is vault-scoped for
  the API's secret-write path; MCP and ontology identities use vault-scoped
  Key Vault Secrets User where needed; Foundry application roles are scoped to
  the project/account operations they support; publication verifier roles are
  definitions only and remain unassigned.
- The setup Job identity has only registry-scoped `AcrPull`. It cannot read or
  modify Key Vault or Foundry authorization under the approved release scope.
  Any setup task requiring those permissions needs a separately reviewed,
  task-specific grant; no grant or trust change was made.
- The separate publication-backend Terraform root defaults to `enable = false`.
  Its scaffold `AcrPull` assignment is gated by explicit enablement; the
  verifier role definitions remain unassigned. This root was not applied.
- Static review and Terraform tests confirm the broker root has only an exact
  registry-scoped `AcrPull` assignment; its proposed artifact read/write role
  definition and three verifier read-role definitions are unassigned, with no
  data actions on verifier roles. The main Terraform candidate adds only an
  optional secret-URI environment variable and no role assignment.

## Isolated DEV broker backend preparation (2026-10-29)

Status: Deployed (reusable setup Job); publication authority remains separate

## Active reusable setup Job request (2026-10-29 13:46+08)

User: "create a new setup job which we can resuse for any setup".
New scope supersedes target-only validation status, not its successful receipts.
Prepare a Terraform-managed manual-only setup Job, reusable through explicit
reviewed execution overrides. Dedicated identity, no standing broad setup role,
no schedule, no automatic retries, bounded timeout, digest-pinned image.
Use existing DEV networking for private endpoint access; preserve existing
apps/Jobs, broker and accepted image. Creating a runner does not select trust
roots, approve publication, authorize arbitrary grants, or lock retention.

- [x] Inspect existing Terraform/Job/image patterns and private network context.
  Existing aiops-dev-cae in Australia East uses aiops-dev-vnet/container-apps,
  with verified vault private DNS path10.50.8.4. Use this environment, not the
  separate broker environment. Existing registry aiopsdevacr7h0ih3.
  Pure standalone Terraform follows existing isolated root deployment pattern,
  avoiding changes to the main infrastructure state or existing workloads.
  Proposed creates: aiops-dev-setup-id UAI, exact-registry AcrPull assignment,
  aiops-dev-setup manual Job in existing aiops-dev-rg/c ae (aiops-dev-cae).
  Job: Consumption0.5CPU/1Gi, timeout300s, retry0, parallelism1/completion1.
  Reuse verified broker digest6d9478ab as Python/ODBC/Azure-SDK tool runtime;
  override entrypoint to a harmless readiness command (no broker startup).
  Dedicated UAI receives only AcrPull initially. No vault/SQL/ARM data mutation
  permissions. Each future setup supplies explicit reviewed code and scoped
  permissions; do not make a standing Owner/Contributor runner.
  Durable Terraform/docs in infra/setup-job and docs/runbooks, no commit/push.
  Validate create-only three-resource plan, apply only after approval and
  azure-validate/deploy, run harmless default readiness probe, verify parity.
- [x] Present exact resource/identity/permission plan for approval.
  Actual user terminal approval APPROVE SETUP JOB recorded05:54:33Z,
  receipt setup-job-operator-approval.json SHA98ed0009d720fb3856a6bc116a0f8d4c49c6c50493cca320ae35d3ee56ab1489;
  approved plan predecessor SHA291e506d13fe04479fe2a623157cfdbb7c39008afa1f2230892dcd7ee5b12872.
- [x] Implement reusable Job and operational instructions after plan approval.
  infra/setup-job/main.tf, readiness.py, provider lock; reusable-setup-job runbook.
  Dedicated UAI receives only registry-scoped AcrPull, no other standing grants.
- [x] Validate create-only plan, deploy, execute harmless readiness check.
  - [x] All validation checks pass (Terraform recipe).
    - [x] Terraform/Azure CLI installed and exact context authenticated.
    - [x] Isolated init, fmt-check, validate and saved plan pass.
    - [x] State preflight, unresolved-template scan and applicable policy review.
    - [x] Static identity/registry role scope and readiness dependencies verified.
    - [x] Existing immutable image unchanged; readiness tests5/5 and Ruff pass.
- [x] Verify existing workload parity and persist setup Job receipt.

### Section 7: Setup Job validation proof (2026-10-29 05:56Z)

Terraform5.2.0 pinned provider initialized; terraform fmt/validate PASS.
Readiness unit tests5/5 PASS; targeted Ruff PASS. Actual SPN authentication and
existing environment read PASS; no shared CLI login change. Existing environment
and region confirmed, Consumption workload profile already available.
Saved SPN-authenticated plan:3create/0change/0destroy; closed plan assertion PASS,
identity name, exact registry role/scope, image digest, environment, resources,
manual-only/no retries/300s timeout and complete readiness source verified.
Saved plan SHA5fdd3d4fac0b3d4ef72f9d65f7ed416695bb8202e8a7708a88a168a47090b619.
Policy inventory and predeployment original workload snapshots captured.
No new image/build or existing workload change. Root npm lint:fix/test command
not applicable: root package.json absent (ENOENT); no frontend sources changed.
Operational code covered by Python tests and actual Job readiness after deploy.
State preflight: new isolated state absent as expected; no unresolved templates
or tfvars JSON. Used explicit-state commands rather than generic preflight script
which writes tfplan/state in source root; never point this deployment at shared
main state. Policy assignments concern SQL/Arc SQL, relational DB and data
protection; no new DB/storage resources, no applicable conflicting setting found.
Role assignment review: sole dedicated setup UAI, exact-registry AcrPull;
readiness performs DNS/local dependency checks only, no data-plane permissions
needed. Canonical LoadPlan/AddValidationSteps/RunValidation/BuildVerification/
StaticRoleVerification actions completed. No deployment validation errors remain.
Apply not yet performed.

### Setup apply recovery (2026-10-29 05:59Z)

First exact plan apply created setup identity, then failed403
Microsoft.Authorization/roleAssignments/write for deployment SPN0ac8c43c
(Contributor); Job not created. Preserve isolated partial state; no recreate.
Recovery: use already-authenticated operator with existing inherited Owner
for the SAME approved registry-only assignment and Job. No SPN elevation/new
grant. Read back partial identity and assignment, generate fresh residual
2create/0change/0destroy plan, verify and validate before deploy. Never replay
stale original plan or change existing apps/Jobs.

Recovery completed: original saved-plan apply wrote partial state to
infra/setup-job/terraform.tfstate despite the earlier plan's explicit state flag.
Preserved that actual identity state by relocating it to protected session
setup-job.tfstate. Rejected the first recovery plan (incorrect three creates).
Fresh v2 plan verified identity no-op plus only the approved role and Job creates,
all previously known values identical and newly resolved principal/identity exact.
Plan SHA609cfa4cbf5da1ec376c35da7b45239c70dd11c53cb24331f5639bb0427d6319.
Applied v2 with explicit state path and existing CLI Owner:2added/0changed/0destroyed.
No-change refresh plan exit0; sole registry-scoped AcrPull confirmed.
Original four apps and ten Jobs exactly match before/after raw configuration;
only new setup Job added. Default readiness execution aiops-dev-setup-02kuo51
Succeeded with status=ready, UID10001, vault DNS10.50.8.4 and all dependencies.
No token/secret read or cloud mutation in readiness. Runbook corrected to pass the
same explicit state path to saved-plan apply; no identity recreation/import.
Sealed setup-job-delivery-receipt.json SHA256:
f5fb6eb7a51b236e76d9e78d0f24170df3bc349e7c3bbf546fbf45accdb82c0d.
Actual runtime/source/configuration and17artifact hashes preserved.

## Explicit user commissioning continuation (2026-10-29 13:30+08)

User: "i already said approve everything". This is an actual user response,
not the earlier unavailable tool result. Resume commissioning described in the
sealed recipe. First bounded write: existing deployment operator invokes
create-only ProvisionTarget once using exact sealed target/backend/horizon,
no new setup/authority role grants. Guard absence/zero rows and exact config
hash, explicit transaction, verify complete binding before commit; on ambiguous
outcome read back before retry, never delete/recreate.
Recipe: scoped SQLcmd Entra/TLS transaction against existing Fabric OLTP.
Fresh validation and deploy workflow precede execution. Preserve accepted image,
source and all existing workload settings. No fabricated signed authority;
reuse existing maintenance_release verifier patterns for future publication
authority wiring. Lock remains a separately guarded irreversible step requiring
actual policy ETag and destructive-action confirmation per deployment guidance.

- [x] Prepare protected exact target transaction and no-write validation.
  Exact applySQL SHA14a6fd8fe875b0e1513baea8c991af1e411494e13b6fa19863835509d3305d8b;
  config SHAbcc6fec2345b9f91c9444540494c6da697b03f0ae0fe437870b5ab8b72daadcb.
  Live SQL05:31:23Z pristine rows and operator EXECUTE verified.
  Live registry/ontology05:32:01Z revision106 and exact fingerprint unchanged.
  Statement uses transaction/absence guard/full binding+null-control readback,
  no role/grant/policy/authority/attempt changes; explicit failure rollback.
- [x] Validate/deploy target; verify actual worker authenticated control read.
  Exact create-only transaction committed, independent complete binding readback
  passed. Actual Target1/AuthorityGrant0/Attempt0 at05:34:32Z, no new roles.
  Worker groatvr Succeeded: unauth401, signed exact v2/idtypapp worker200,
  active/session null and revision0, elapsed2.891s. This proves actual control-MI
  ownership-chain table read, not publication.
  Receipt broker-dev-target-commission-terminal-receipt-20261029.json
  SHAaf30e5589e5062e93adb6382696777843df445e2df2132cbf711e5ea739ab5d5.
  - [x] All validation checks pass (scoped data-plane SQL recipe, no ARM/template changes).
    - [x] Core: CLI/auth/context, exact live SQL preflight, actual operator EXECUTE,
      sealed config/applySQL and fresh registry/definition comparison.
    - [x] Docker build not applicable: immutable accepted image unchanged.
    - [x] Azure ARM policy/template build/what-if not applicable to existing
      SQL procedure transaction; no ARM resource/configuration mutation.
    - [x] Compile helpers and validate exact transaction allowlist/hashes.
    - [x] Live identity/context readback and validation proof recorded.
- [ ] Separately scope retention configuration and guarded irreversible lock.
- [ ] Qualify bounded immutable artifacts and actual publication authority.

### Section 7: Validation Proof - target commissioning 2026-10-29 05:32Z

Canonical azure-validate workflow: LoadPlan/AddValidationSteps/RunValidation/
BuildVerification/StaticRoleVerification actions completed for scoped SQL recipe.
`prepare-broker-dev-target-commission-20261029.py`: config pin+SQL manifest pass.
`sqlcmd ... -N true -l30 -t30 -b -W -i ...preflight.sql`: actual engine pristine
Target/AuthorityGrant/Attempt and current operator effective EXECUTE pass05:31Z.
`check-broker-dev-target-freshness-20261029.py`: fresh live registry revision106,
actual item and exact decoded definition fingerprint match05:32:01Z.
`python -m py_compile` both helpers: pass. SQL hash/closed write allowlist and
explicit rollback/commit assertion: pass. `az account show`: exact approved
subscription890c9bfc/tenant262a3a77. No new SQL/ARM roles or provider grants.
No app/source/container/ARM change; rebuild/Bicep/what-if and ARM-policy checks
not applicable to this closed data-plane procedure. Future retention/authority
changes require their own prepared/validated stage, not this proof.

## Current actual outcome (supersedes historical preparation below)

The approved access package, private service, manual worker-only probe Job and
idtyp-only application correction have actually applied. No further grant/app
correction is pending. Hosted revision `4h0fjlp` is Healthy, one replica; service
and worker roots have zero-change plans. Original four apps/ten Jobs retain
exact normalized parity. Accepted image and 494 baked source paths unchanged.

Supported portal Share added exact control/verifier item Read only (no extra
data checkboxes or workspace role). Actual distinct MI ODBC18/TLS connections
now succeed: publication DML native373, cross-role EXECUTE229, control51001
missing-target and verifier51008 binding refusals. These are connection/read/
refusal checks, not full ownership-chain or publication acceptance. Private
Blob MI read succeeds; Fabric SQL routing remains public and unqualified.

Resource app optionalClaims.accessToken idtyp readback matches required
configuration; no new roles, grants, credentials or identity/policy changes.
Three earlier signed worker HTTP attempts lacked idtyp and correctly returned401.
The timing diagnostic then verified idtyp=app at05:21:00.972532Z: iat/nbf05:16:02Z,
exp2026-10-30T05:21:02Z. Correction readback persisted05:17:01Z. Backdated iat is
not conclusive cache evidence. No raw JWT/token/hash retained, forced refresh,
identity/audience workaround or claim relaxation. An expiry-based recheck is no
longer needed because the required claim is actually present.

Unchanged worker execution `v65obss` terminated Succeeded; exact signed identity/
role/idtyp verification passes. No token returns401; reviewed worker reaches
closed503 `broker_provider_unavailable` in3.639s. This establishes authenticated
provider refusal, NOT successful control read or publication. Raw control
ReadControl independently reaches51001 with zero target rows; HTTP503 alone
does not distinguish provider causes. Source sanitizes SqlPublicationError to503.
Actual same-container diagnostic subsequently read PID1 service configuration,
used the baked SqlBrokerControl.read_control and its exact _connection method:
control MI is publication_broker1/verifier0, native51001 publication_target_invalid,
wrapper SqlPublicationError(sql_publication:procedure_failed), source hashes match
the accepted image manifest. Thus this instance is missing-target business refusal
sanitized to503, not infrastructure/TLS/identity/config failure. Do not label it
qualified expected-business409 or successful ownership-chain control read.

No target/authority rows, WORM lock or authority/setup grants were added. Mirror
reader confidentiality, private Fabric path, live pause, Blob write/WORM,
authority setup and publication remain unqualified/excluded. No commit/push.

Read-only commissioning preparation is sealed separately in session artifacts:
`broker-dev-commissioning-recipe-20261029.md` and preparation receipt
`aeb935d98d9b350a6d960246448e9555f3270829a5ffbefd2425a4a0a4a51de3`.
Actual SQL prestate confirms no setup/authority roles or explicit procedure
grants, all operational rows0; container has no immutability policy/legal hold.
Proposed31day policy covers configured November29 horizon subject to provider
UTC recomputation; lock/target/authority and publicTLS/mirror-reader acceptance
remain pending explicit new decision. Packaged RecordGrant client is not a
commissioned signed-review authority verifier; source has no runtime caller.
No exception-mapping delta, image rebuild or additional cloud write performed.

## Historical correction preparation (executed, not current instructions)

First real worker token verified signed v2
issuer/aud/tid/azp/oid/Publication.Worker, but idtyp absent; broker correctly401.
Worker Job execution b4w48cg terminated Succeeded (probe completion only, not auth
acceptance). Configure optional access-token `idtyp` emission on the already
approved new broker app only. Official Entra optional-claims reference documents
idtyp=app for app-only JWT access tokens; resource app controls claim emission.
This is required auth configuration of the approved application, not an additional
permission/app-registration/role/identity or weakening the broker requirement.
Guard verifies every selected app field matches original approved readback;
only PATCH optionalClaims.accessToken idtyp; preserve all other fields and claims.
Recipe for this stage: scoped Entra configuration via guarded `az rest` (not
an ARM deployment; Bicep build/what-if and Azure Policy deployment checks do not
apply to this Graph resource). No Terraform/provider changes. All validation
checks: compile correction script, exact live app prestate/unchanged approved
fields, official supported optional-claim semantics, exact PATCH-only plan hash,
no new role/permission/credential, existing auth/source/image unchanged.
Run check/compile and fresh validation workflow before correction; no new grant.
Current worker/probe/service/source/image are unchanged; after readback, repeat
same bounded worker execution, acknowledging MI token cache may retain old JWT.

Historical initial provider probe, before supported item Read sharing:
Hosted service applied successfully (two creates, no updates/deletes).
Revision `4h0fjlp` Healthy/RunningAtMaxScale, one replica; no-change plan exit0.
Actual in-environment HTTP401 confirmed, private Blob MI read succeeds via10.73.2.4.
Actual control/verifier MI tokens reach Fabric SQL over TLS but engine refuses
28000/18456: missing item Read. Fabric resolves public20.53.46.128, not private.
Complete sanitized receipt `broker-dev-hosted-readonly-probe-result-20261029.json`.

Historical worker preparation (now applied): one NEW manual-only worker probe Job in the
same isolated environment/service RG; no existing Job changes. Attach worker MI
plus registry-pull MI only, NEVER control/verifier/Blob identities. Same accepted
digest, 0.5CPU/1Gi, timeout180s/retry0/one completion. In-memory worker token and
signed JWKS/issuer/audience/tenant/worker-role verification; log only allowlisted
nonsecret claims and bounded HTTP401/authenticated read-control refusal. No
SQL/Blob mutation, authority/setup, app-registration/grant change or cutover.
This is the already requested real dedicated-worker/identity wiring qualification,
not a new worker authorization package. No secrets in command/config/logs.
Prepared worker root initialized/validated and explicit one-create plan generated;
canonical preflight plus script compilation, exact managed identity/image/trigger/
read-only-command guard, live role/context and no existing Job changes required.

Historical create-only isolated hosted broker preparation, using the existing immutable
image and actual observed DEV ontology pins. Access-only deployment completed:
app/SP/sole worker role, exact SQL runtime users/roles and five scoped ARM
assignments read back. Fabric item Read is still pending supported portal sharing:
both browser MCP processes fail ENOENT and the working canvas is signed out.
This does not prevent fail-closed service installation or independent checks.

Prepared service plan: exactly a new `aiops-pub-dev-service-rg` resource group
and `aiops-pub-dev-broker` app, using existing private `aiops-pub-dev-cae`.
No existing app/Job, network, authority/setup, schema or workspace changes.
One replica, 0.5 CPU/1Gi, internal-only TLS ingress, separate registry and three
provider MIs; worker is never attached to the broker. No image rebuild.
Saved plan and runtime configuration are in the isolated delivery service root;
settings hash `4929e235948153cf2f416fa83480764201559ea7a66824a13ebad943d1c8717f`.
Observed target receipt records registry revision106/connection demo and native
DEV ontology `191c9b47-2839-4983-97e8-2d8c6f1889eb` in ops workspace2c1fea36,
exact repository definition fingerprint `sha256:991aa9eac6f1c98b5d135cbf8c43017953561a45b493b5c6fc2c071e6f018f82`.
Use that actual item UUID as proposed isolated control key, not a fictional live
UUID. No target row exists or is installed. API audience is bare new app GUID;
token request still uses api://GUID/.default. Expected result is refusal, not
live publication. Retain-until is configuration only; absent locked Blob policy
must refuse publication. Fabric private routing and mirror confidentiality
remain separate unqualified gates. The user already approved this exact DEV
subscription/location/cost/access scope; do not repeat resolved prompts.

## Active approval 2026-10-29 12:53+08

Fabric forwarded the user's explicit "approve everything" against exact
runtime-access package SHA25679d15671 and SQL SHA256394bad49. This supersedes
the historical unavailable answers below only for that reviewed package.
Execute one single-tenant app/SP, Application-only worker role, registry AcrPull,
Fabric item Read for control/verifier, exact two SQL users/roles/nine EXECUTE
grants, and narrow Blob data/ARM evidence reads. Preserve sealed sources/image.
Prepare exact execution artifacts and pre-read guards, run azure-validate then
azure-deploy, record actual changes/readbacks before hosted service deployment.
No secrets/delegated Graph/directory roles, workspace changes, authority/setup
grants/rows, WORM lock, existing API/Job changes, cutover, commit or push.
Private Fabric routing and inherited mirror-reader trust are still unqualified;
approval does not waive them. Current scope remains Phase03.7 publication backend,
not the stale historical Phase4 header's admission.

- [x] Inspect exact app/SP/SQL prestate; no broker app and no SQL runtime roles/users.
- [x] Verify five dedicated MI client/object bindings and all six approved Storage actions.
- [x] Prepare guarded hash-bound CLI access execution; Ruff and read-only preflight pass.
- [x] Fabric item Read completed through supported portal Share; exact two MIs Read only, no extra data/workspace roles.
- [x] Prepare guarded approved access execution and validate/deploy it.
- [x] Read back exact actual grants; compose private service using actual app ID.
- [x] Validate/deploy service and qualify actual provider read/refusals plus signed worker authenticated closed503; no successful control/publication claim.
  - [x] Terraform init/fmt/validate and nine isolated mocked safety tests.
  - [x] Saved actual two-create plan and strict image/identity/config guard.
  - [x] All validation checks pass: tools/auth/subscription/init/fmt/validate/plan/state/template/JSON.
  - [x] Verify deployer Owner, actual registry AcrPull and image digest, exact RG absence.
  - [x] Complete azure-validate workflow and record new service-specific proof.

Validation runner initially reported missing state on this deliberately new
isolated root (not existing infrastructure drift); initialize an explicitly empty
local Terraform state through `terraform state push` before repeating preflight.
Never import or claim resources in this empty bootstrap. Mock tests initially
inherited auto-tfvars review hash; moved deployment values to explicit
`dev.tfvars.json`, isolating tests. Nine tests pass without source changes.

Historical foundation-only status below is superseded by explicit approval and
the actual access write/readback results above; its sealed receipts are immutable.

Original deployment terminated exit 1: the environment SUCCEEDED after 19m7s,
but Azure automatically created the new account's default Blob service before
AzAPI attempted its create. Exact "Resource already exists" error and partial
state are preserved. Environment is internal/public-disabled, IP 10.73.0.170.
Documented pinned-AzAPI import adopted only that automatic default service into
isolated state, with no cloud mutation. Recovery plan is NOT a replay: exactly
one in-place default-service versioning=false setting and the one remaining
original private container create, no replacement/delete/grants/new scope.
Current default CORS is empty and delete retention disabled; guard pins these
before values as well as exact account/service/container IDs and sealed source.
Recovery apply completed exit 0 after fresh azure-validate and azure-deploy.
All 16 exact explicit ARM resources read back and match state; subsequent
Terraform detailed-exitcode is 0, no changes. Four existing apps and ten Jobs
retain exact image/identity/resource/revision/schedule snapshots. No broker app
registration or privilege grant ran. Container has no immutability policy or
legal hold; publication must still refuse rather than claim WORM acceptance.
Terminal receipt `broker-dev-foundation-terminal-receipt-20261029.json`,
SHA256 `862f07abc010319fbadfaadd97cfd9d29798ea85ab504d2825f328aee1da6e7c`,
seals 32 supporting receipts, including the original error and safe recovery.
Local state remains isolated; encrypted/locked remote adoption is required
before team-operated updates. Do not replay either saved creation plan.

The final immutable image has been pushed:
`aiopsdevacr7h0ih3.azurecr.io/aiops-publication-broker@sha256:6d9478ab8877efb97c92e7c39d40dce92e589f61416a91b7a9b4aa61795195bd`.
Parent independently verified all 494 baked source bytes, nonroot execution,
entrypoint and HEALTHCHECK NONE. Baked-image actual Fabric TLS/UUID/timeout/
reconnect and local HTTP401 are accepted source/connectivity evidence, not
dedicated-runtime-MI acceptance or live publication.

Historical proposal (subsequently explicitly approved/executed as above):
`broker-dev-runtime-access-REVIEW-ONLY-20261029.json`, SHA256
`79d1567137902c4ea2b381ed5d4d2459c745916c45fe3b3546f78aca4cb73f48`.
SQL companion SHA256
`394bad49a4070b218d5579b6f97fb55953ffe9eea6471b88a34e18b93f26e5e1`
creates only two runtime users/roles and nine object-level EXECUTE grants,
never publication_authority/setup. Actual read-only engine conversion confirms
the proposed service-principal CLIENT-ID SIDs; current runtime users remain zero.
The original unavailable response was not consent; the later explicit approval
resolved that hold. App/role, AcrPull, SQL and Blob bindings have now executed;
Fabric item Read remains a supported-interface/sign-in issue, not missing consent.
Current source uses the Blob credential for narrow ARM policy/account reads
as well as Blob data; do not incorrectly assign those reads to SQL verifier.
Private Blob/service ingress does not qualify Fabric SQL private routing;
workspace-private-link/item-sharing compatibility remains unresolved, with no
workspace policy/role changes or Viewer/Contributor workaround authorized.

Further read-only confidentiality proof: complete workspace-role listing has
existing apps identity `1701d43c-bdc3-4ab7-9964-02cbbbc35a93` and MCP identity
`99771d97-d5d5-497f-8787-aca353201502` as Viewer, publisher as Contributor,
and two Admin principals. Official SQLDatabase authorization explicitly maps
all these roles to ReadAll and ReadData; ReadAll permits reading mirrored
OneLake files. These are actual inherited reader trust boundaries, not merely
a hypothetical SQL permission concern. No impersonated-reader or exhaustive
item/analytics permission test is claimed. No existing roles changed.
Sanitized receipt `broker-dev-fabric-mirror-boundary-review-20261029.json`,
SHA256 `b1bc2f9179302bea73fae550c9150680410ee470392ac513907a7a955e377d47`.
Direct exact runtime-access approval question also returned user unavailable
at 12:23+08; no consent inferred. Further hosted-runtime provisioning is gated
on that exact privilege decision and separate private-routing/confidentiality
qualification, not on resource cost or a nonexistent SQL admin group.

## All validation checks pass (isolated foundation scope)
- [x] Terraform/CLI installed, exact authenticated context and existing approval.
- [x] Init exact pinned providers; format, validate and mocked regressions.
- [x] Exact saved plan; all 16 changes CREATE-only, no existing resource writes.
- [x] State accessible; isolated ARM-only foundation has no secret inputs/listKeys.
- [x] No unresolved Go template variables or generated tfvars.
- [x] Policy/regional quota and non-overlapping address-space inspection.
- [x] Static role verification: foundation intentionally assigns NO privileges
  and hosts NO app. Runtime data access and registry/app roles remain separate;
  this foundation does not claim an operable broker.
- [x] Frozen source image locally built/nonroot and full 494-path manifest checked.
- [x] Required recipe preflight runner all applicable checks pass.
- [x] Validation workflow proof recorded; initial provider-field/type and absent-state failures resolved through supported tools; all applicable checks pass.
- [x] Recovery recipe preflight rerun after supported automatic-service import.
- [x] Recovery guard: exact one service update/one container create; no other writes.
- [x] Recovery authoritative workflow completion and new Section 7 proof.

Recipe: existing standalone Terraform with exact saved-plan/protective guard;
no azd wrapper or placeholder workload. The approved foundation is separate
from the later service/app-identity gate.

## Section 7: Validation Proof (2026-10-29 continuation)

Claim correction stage (2026-10-29): script py_compile PASS; guarded live GET
matches every original approved app field and optionalClaims=null. Only planned
payload accessToken idtyp, reviewed JSON hash
`39aef2da9d2f8c19f349670a1330f51e0dba40dd0cabac17493181c4e7b8e39e`.
Official optional-claims reference verifies `idtyp` app-only access JWT and resource
app configuration. No Graph/API consent, new role, directory grant, credential,
SP assignment or runtime policy changes. Guarded CLI check PASS; no ARM resource
deployment exists in this stage, so Bicep what-if/ARM policy checks in generic CLI
recipe are inapplicable (not claimed passed). Existing build/source/digest unchanged.

Worker probe stage (2026-10-29): canonical Terraform preflight `validation.txt`
PASS (explicit empty local new-root state, no claimed resources). Script compiles.
Actual guarded plan `0a97077b9e15b72c2926d011e19cf6fe78e82a02dfd28a1ccf6bb3bad40ad7a5`
creates exactly one manual Job, no other changes; only worker+registry MI attached,
no privileged provider credential. Script SHA256
`656130bec7cf5ceb6798bc1fadc63c0732b1dbdb5504fb3402776fc79c09a66d`.
Same accepted image digest reused; no build delta. Existing isolated service RG/
environment healthy; serviceRG Job list is empty; existing jobs untouched.
Live subscription/deployer Owner/registry AcrPull already verified this stage.
Static role review: no role or permission resources. Probe only obtains in-memory
worker token, verifies signature/expected claims and makes read-control requests.
No known preflight errors. Read-only Graph optionalClaims currently null; actual
worker token will establish whether required idtyp=app is emitted. Never weaken
authentication if the claim is missing.

Supported portal sharing subsequently succeeded: selected exact control and
verifier AppIDs; all three SQL/analytics/Spark extra-data checkboxes unchecked.
Manage permissions readback: each dedicated identity Read only, no workspace role.
Actual ODBC18/TLS now connects under both distinct MIs with exact separate roles.
No workspace role changes. Updated portal inherited Viewer permission is
Read/ReadData, not ReadAll; publisher/Admins additionally retain ReadAll.

Hosted service-specific checks (2026-10-29, after approved access execution):
`terraform init/fmt -check/validate/plan` PASS through canonical Terraform
preflight runner; explicitly empty new-root local state initialized, state-list
PASS. Full stdout `broker-dev-service-validation-preflight-20261029.txt`.
Nine service mocked tests PASS, with deployment variables explicit/not automatic.
Actual runtime strict service construction PASS with exact observed target pins.
`check-broker-dev-service-plan-20261029.py` PASS: exactly two creates, no deletes,
updates, roles, policy, authority or existing-workload changes. New saved plan
SHA256 `33a4bbae89e3c079d038697487f81582610156a6ec5f38959942947b2b8dd673`.
Runtime settings hash4929e235 pinned, real three-provider/four-attached MI set,
worker excluded; internal TLS-only ingress and fixed digest/command/replicas.
Live subscription/tenant exact; new serviceRG absent; deployer inherited Owner;
registry MI exact AcrPull read back; ACR exact image digest exists.
Existing independently accepted build/source494 seal reused unchanged as directed,
not rebuilt. Docker inspect exact digest: UID10001, /broker, actual broker
entrypoint, HEALTHCHECK NONE. Static review no new roles in service root.
SQL item Read and real MI auth/refusal remain post-install qualification gates;
TCP probe is not authentication/publication evidence. No claim they passed.

Runtime-access validation 2026-10-29 after explicit approval:
`broker-dev-approved-access-20261029.py check` passes live exact subscription/
tenant, five dedicated ManagedIdentity app/object pins, immutable package and
SQL hash guards, and six Storage provider operation names/dataAction flags.
Ruff passes execution script. Actual SQL prestate proves engine12, no target/
authority rows or existing runtime users/roles, and no EXECUTE AS contexts.
Recipe for access-only stage is bounded Azure CLI/Graph + SQL, not ARM template
deployment: no Bicep/app/image changes exist to compile or what-if. Script
stages limit app to one secretless single-tenant app/SP, sole Application worker
role, five ARM bindings/four exact custom definitions, without retry or broad
fallback. Each write retains actual readback immediately; unsupported/error
stops that stage. This stage does not claim whole broker functional acceptance.
Frozen image build/proof remains applicable; no rebuild. Static role review
matches sealed reviewed package exactly and does not create authority/setup,
delegated API access, directory roles, SAS/key/policy-write permissions.
SQL execution uses original exact reviewed transactional file, not whole
permissions.sql. Official Fabric item Read sharing is separate if API unsupported.

Recovery proof: pinned AzAPI 2.12 documented import adopted only the new account's
automatic `/blobServices/default` after original apply exit 1. No cloud writes
occurred in import. Recipe runner rerun passes CLI/auth/subscription/init/fmt/
validate/plan/state/template checks; absent tfvars JSON is explicitly skipped.
Independent recovery guard permits only `azapi_resource.blob_service` update
to originally approved versioning=false and `azapi_resource.container` create
with publicAccess=None, exact parent/account/container IDs. It pins current
empty CORS and disabled delete-retention defaults; no replacement/deletion or
other resource writes. Saved recovery plan SHA256
`230953c97da00f0d438554f7caa4a5addffc4798c1a36e6c9f132609de744c2d`,
JSON SHA256 `d690e3ffb2bc20788548ffa7026751e4bd9e3dc513e1866668a495588c79c705`.
Guard verified all nine accepted source hashes unchanged; existing immutable
image build/proof remains applicable and is not rerun. Static role review
confirms zero grants and zero apps in foundation. Recovery apply completed
exit 0; independent 16-resource readback and subsequent no-change plan passed.

`terraform init`, `fmt -check`, `validate`, `test` (one mocked security test)
and fresh saved `plan` pass on publication-fabric-dev. The recipe preflight
initially identified a genuinely absent state file; supported `terraform
refresh` initialized empty local state without cloud writes. Recipe rerun
passes every applicable check (tfvars JSON is absent/not applicable).
Saved plan was regenerated against that initialized state, then independent
guard proved all 16 actions create-only and exactly the allowed foundation
resource types. Guard receipt broker-dev-foundation-plan-guard-20261029.json
binds source and plan hashes; no shared API/Job/Fabric resource, role, SQL
server, grant or WORM resource is present.

Image aiops-publication-broker:dev-20261029 built successfully with exact
frozen API+fabric-sql extras, dependency check, Microsoft Driver18 base and
494-path source manifest SHA256
f60d678f86624fce8019eff3116f7a3e34610fda83adc0eb9d066c9d0ed0dfc6.
Local full source readback matches; service origin /broker/src and
distribution origins /broker/.venv; UID10001; HEALTHCHECK NONE; explicit
broker entrypoint. Registry upload and actual baked-image connectivity are now
complete; runtime-MI/full broker qualification remains separate.

Validation scope: isolated DEV foundation only in the new additive scratch
`/Users/jasonmba/.copilot/session-state/f13dff91-b486-4191-a5ce-95039edefbf5/files/broker-dev-delivery-20261029/infra/publication-fabric-dev`.
Exact saved `foundation.tfplan` SHA256
`a097e16b3e794a40e79c0fe37c50c003972fc61fbea93ab196e56f7ca96ade54`
creates 16 new resources only in `aiops-pub-dev-rg`, Australia East:
dedicated control/verifier/Blob/registry/worker UAIs, VNet10.73.0.0/16,
two subnets, internal/public-disabled Consumption environment, private
OAuth-only Blob account/container and private endpoint/DNS. No SQL resource,
SQL/item/app grants, role definitions/assignments, WORM policy/lock,
API/Job changes or existing-resource updates. Terraform validate, mocked
private-foundation test and independent strict saved-plan guard pass.
Deployer readback: approved subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc,
tenant262a3a77-7d74-4684-8937-897d98d2a17a; inherited Owner observed.
Environment quota1/50; Australia East registered; exact Blob name available.
Existing shared environment is external/public and is not reused or modified.
State remains isolated in session scratch, contains no passwords/keys:
ARM-only storage resources explicitly avoid listKeys; no secrets are supplied.
Remote-state adoption is separately required before team-operated updates.
Protected app/Job image/identity/resource/cron snapshots captured before apply.
Source-hashed frozen broker image build and upload completed independently;
foundation apply does not enable service execution or confer authority.

Active continuation: inspect dedicated identity, Blob, private-network and
service composition; build a source-proven digest-pinned broker image and
prepare an exact protective saved plan for already approved isolated DEV
resources. Run azure-validate before azure-deploy. Prior bounded-backend
closeout is not a revocation of the existing isolated DEV provisioning approval.
No existing API/Job or workspace-role changes, authority grants, irreversible
WORM lock, production cutover, commit or push. New app registrations and SQL
privilege grants require separately reviewed exact scope. Complete independent
safe prerequisites rather than treating those narrow boundaries as a blanket
stop. Preserve all frozen bundles and the existing database; never replay create.

Active backend decision (supersedes Azure SQL/group/password preparation):
user selected Fabric SQL Database OLTP for the publication control plane.
Discover the existing reviewed dev workspace/capacity and dedicated SQLDatabase
items; reuse only a compatible dedicated control database, otherwise create
one after capacity/type/collation checks and read back its exact connection pins.
No Warehouse/Lakehouse mutation or separate Azure SQL server/password work.
Implement and validate a separate Fabric target in an additive scratch copy,
preserving frozen v5 and Azure target validation. Bootstrap schema only after
safe dedicated-database pre-read. Authority grants, retention locking, runtime
enablement and production cutover remain excluded. Every Fabric REST call,
including polls, carries x-ms-fabric-skill: sqldb-cli.

Historical superseded preparation (not an active task): research and replace the scaffold-only GROUP
administrator assumption with an explicit reviewed bootstrap administrator
contract supporting a dedicated user-assigned managed identity, preserving
legacy group configuration where safe. Work is source/offline only, in a
separate copy of v5; v5 seals remain immutable. No SQL administrator assignment,
membership, grants or deployment is authorized by this source change.
Validate provider/platform constraints before implementation, then add mock
and static regressions and document the separate privilege decision.

Historical superseded SQL-auth direction (not implemented): evaluate explicit opt-in SQL password
bootstrap, with private SQL/TLS unchanged and runtime managed identities
unchanged. Stop the group/MI-only contract change. Research provider write-only
password and Terraform ephemeral inputs first; never generate/export a secret
or persist it in source, artifacts, command arguments or local state. Default
legacy Entra-only behavior stays unchanged. Secret-store access/runner and
any runtime Entra authority remain separately reviewed deployment gates.

Completed bounded Fabric bootstrap:
- Dedicated SQLDatabase `b003a6fb-eb2a-4226-b079-6033be2ff354`, workspace
  `4938f885-3e79-41b1-810a-80b55c01dbb7`; exact actual connection pins are in
  the additive scratch `infra/publication-service/fabric-sql-target.dev.json`.
- Guarded schema-only transaction committed: eight tables, twelve procedures,
  version 1. Independent readback: no target/authority/operational rows, no new
  publication roles/permissions and no EXECUTE AS module context. LRO headers
  were not retained for creation; direct item and actual engine readback are
  retained instead. No repeat create.
- macOS Driver 18's OpenSSL library-loading 08001 was diagnosed and resolved
  process-locally, without certificate/encryption downgrade. Representative
  source-overlay Linux probe in digest-pinned existing runtime passed actual
  Fabric TLS, UUID JSON normalization, one-second timeout refusal and reconnect.
  This is deployer-token evidence, not least-privilege runtime-MI qualification.
- Mirroring is always on. Same-name companion endpoint
  `a3568a0a-8aff-4b60-ac04-b63a02427a90` was discovered separately; actual
  item/analytics/OneLake effective-reader proof remains unresolved.
- Existing publisher Contributor privileges remain unchanged and disqualify
  that identity as a credential-free worker/procedure-only provider.
- Pinned Fabric provider 1.13.0 already supports SQLDatabase import. Metadata-
  only adoption with prevent_destroy is a handoff, not an applied state change.
  No new Azure SQL server, SQL password path, role changes, authority rows,
  service deployment, API/Job changes, WORM lock or cutover occurred.

Latest source state: consolidated **v5**, 85 paths, now includes the accepted
resolver-produced lock reconciliation in the isolated assembly. Patch SHA-256
`220e908e05ea8c85b938b583e143718e511bebf974fbf943cb6cd5754aa1a1ca`;
manifest `84137806fb2622a6594ea33a9d423c1f1e662d2ec656ae9f7e948bc900e7645d`.
The historical baseline lock gate described below is resolved in v5 only.
Final assembly `uv lock --check` passes. Exact 22 telemetry version-set shifts
are recorded, not silently bundled: fresh frozen test/SQL 313 cases, separate
API 244 cases and eval 179 cases pass with dependency checks and guarded
offline actual integration initialization. No full-suite or live-export claim.
All 85 path hashes, 473 other base source bytes and forward/reverse tree checks
pass; v1-v4 and individual layer receipts remain immutable. No deployment
qualification or reviewed identity inputs are inferred from lock reconciliation.

The Fabric session reports user approval ("proceed then") for the disclosed
new billable isolated DEV SQL/Blob backend, dedicated identities and private
broker service. This records the forwarded decision, not a broader permission
or a validated deployment. No irreversible retention locking, authority grants,
production cutover, existing API/Job changes or source commit/push is included.

Target: subscription `890c9bfc-d09c-4143-9ce5-465e75e3eecc`, tenant prefix
`262a3a77`, Australia East; exact tenant and context require live readback.
Use a separate Terraform root/state and isolated resource group, Entra-only
SQL, no public SQL/Blob endpoints or key authentication. Do not repurpose the
exit-78 scaffold as a service. Preserve all active workloads and daily cron.

- [x] Confirm exact subscription/tenant/location from live context.
- [x] Fabric SQLDatabase schema-only bootstrap; no SQL administrator group input.
- [x] Prepare isolated foundation/IaC and exact saved protective plan.
- [x] Run azure-validate for foundation; historical F05 is not reused.
- [x] Invoke azure-deploy for approved foundation only.
- [x] Finish current apply and independent readback/no-change/protection checks.
- [x] Prepare exact principal-bound, unexecuted runtime-access review package.
- [ ] Obtain explicit runtime-access approval; configure actual new audience,
      app role and dedicated worker only after that decision.
- [ ] Resolve Fabric private-route/item-permission compatibility without
      changing existing workspace policy or broadening runtime roles.
- [ ] Deploy/qualify isolated service after its actual prerequisites are met.

Historical Azure SQL/group-only scaffold assessment is superseded by the
Fabric backend decision and current 16-resource foundation plan. It is not an
active missing-input gate. No personal/group administrator substitute is
required or authorized. The runtime-access decision above remains distinct
from the already approved dedicated database/foundation resource provisioning.

### Executable opt-in hosted-service increment

Source preparation is in isolated session assembly
`files/broker-main-prep-20261029`, not the active source checkout:
`src/ontology_discovery/publication_broker_service.py`,
`Dockerfile.publication-broker`, `infra/publication-service`,
`docs/publication-broker-service.md` and offline tests. Frozen v3 remains
unchanged. This is a separate additive layer, not a relabeled deployed service.

The entrypoint requires all target/audience/identity/worker/resolver pins and
three explicit dedicated managed-identity client IDs. One persistent runtime,
one asyncio server worker, ASGI lifespan enabled. Host v4 drains workers and
closes artifacts before caller-owned credential cleanup; partial assembly and
unstarted-server failure also clean up deterministically.

The new root defaults disabled and creates only a new service RG and Container
App, using explicit actual existing isolated environment, dedicated provider
identities and already-authorized registry identity. It creates no grants,
SQL/Blob/network/retention resources or Jobs. It requires a private internal
environment with public network disabled, TLS-only environment-internal
ingress, same-registry digest pin and exact provider client-ID correlation.
Min/max replicas 1, Single revision, 0.5 CPU/1 GiB, TCP listener probes only.
This layer does not solve cross-environment producer reachability, authorize
worker grants, or qualify restart/forced-kill behavior.

Terraform validate and 9 mocked plan cases pass without cloud mutation.
817 offline coupled Python cases pass, including 39 focused service/static
cases and a real bounded loopback Uvicorn 401/shutdown smoke with zero provider
actions. Ruff and web lint-fix/151 files/1,993 tests pass. Sealed additive
11-path patch `publication-broker-hosted-service-20261029.patch` SHA-256
`168f21f56781c4d98007e91dd8f1f4490aa3ebfe512924c84568a190f357b614`,
manifest `844bcd23747465cb988156a76ad479ba699dfe1d5303f6269a773db3b54bc69f`,
is under this session's files directory. All 73 v3 source hashes remain
unchanged and disposable-index forward/reverse checks pass.
Combined v4 is sealed separately: 84 paths, patch
`048fcdcd428e9b8878c9a549c9650ce57dd74d3324d0d0461178bc950d498d73`,
manifest `78ad50647653d8059b014f3d9b619badc367da7d9140970a872c4944f698a9e8`.
All 473 base source paths outside its manifest remain byte-identical.

Parent found a declared-test uvicorn dependency gap. Separate pyproject-only
follow-on `f819d0163a27d2657c9ebca8c2020f3ecc6ca2a9382d83b6133b583c1adf2d4a`
adds the existing API bound to test without installing the API extra. A fresh
manifest install of test+fabric-sql passes 96 service/static/runtime/host cases
and dependency compatibility check, with no agent-framework packages.
Frozen lock remains an explicit gate: original main independently fails
`uv lock --check` (test opentelemetry-sdk declaration missing from root lock),
and this follow-on also fails it. Broad regeneration changed unrelated telemetry
branches and was discarded; original lock bytes retained. No reproducible
frozen-sync or final lock-qualified bundle claim.
Actual group selection, backend provisioning, reviewed identities/audience/maps,
data permissions, image/package proof, reachable client placement and exact
saved plan remain deployment gates. Do not mark the overall deployment Ready
for Validation from offline source tests or invoke deployment with dummy pins.
No new cost approval request is needed for the already-authorized isolated DEV
scope; missing concrete configuration is not a resource-cost approval hold.

## F05 bounded acquisition retries (2026-10-28)

Status: Validated

Review the sealed two-path F05 candidate against current main and existing
producer contracts before integration. Preserve all unrelated dirty work.
Use the established dev subscription/resource group and existing-resource
AZCLI recipe. Only the inventory-publication Job image may change; API/web,
cron `30 14 * * *`, grants, roots, sizing and retention remain untouched.
No manual publication is permitted.

- [x] Review phase blockers, patch integrity, retry semantics and existing tests.
- [x] Validate accepted source, commit/push, open PR and await exact-head CI.
- [x] Merge, build exact merged-main native image and verify packaged parity.
- [x] Complete Azure validation and guarded producer-image-only deployment.
- [x] Arrange bounded read-only verification of the next natural 14:30 UTC run.
- [x] Seal exact rollout evidence and bounded retry/cost outcomes.

The next eligible natural run is 2026-10-29 at 14:30 UTC. Until it completes,
report source/runtime adoption separately from live retry observations.
No acquisition-completeness claim without actual cost-actuals evidence.

### F05 preparation and bounded release decision

The established autonomous release request governs integration; no new target
or infrastructure is introduced. Existing dev subscription
`890c9bfc-d09c-4143-9ce5-465e75e3eecc`, `aiops-dev-rg`, Australia East.
Source input3f1092bb is integrated as0f8d9499, PR428, exactly two paths.
361coupled Python cases and1,993web cases pass; Ruff and lint-fix pass.
The integration adds sanitized retry logs and finite numeric-header handling,
plus continuation/exhaustion/no-partial-success coverage beyond the five input
tests. Public class docstrings describe bounded behavior.

STATE.md retains Phase4 traversal/100k/canary gates and Phase13 fixed-lifecycle
gates. F05 closes none of those. Cost429 and service_health ConnectError were
observed acquisition caveats, not proof this retry change guarantees completeness.
Full runtime preimage is retained as `files/f05-runtime-preimage.json`.
No producer is running; latest execution29886630 Succeeded on the older F04
image. Actual registry uses existing `acr-password` secretRef; no new RBAC,
identity, AZD provisioning or Terraform apply is appropriate.

Build once after successful CI and merge from an immutable merged-main archive.
Smoke the actual image with network disabled/read-only filesystem: retry scope,
page identity, bounded failure, five Cost retries,120s cap, finite headers,
all91unchanged F03 thresholds and every packaged source hash.
Deployment helper `files/f05-rollout.py` submits a Job-template-only image PATCH,
checks full protected preimages immediately beforehand, then verifies API/web,
serving revision/traffic/env, other Jobs and normalized Job state unchanged
except the image. Recovery is read-only post-check, never blind PATCH replay.
Rollback, if required, is the exact prior Job image only after drift checks.

### F05 all validation checks pass

- [x] Core AZCLI checks: exact established subscription/RG/environment/registry,
  no running producer, immutable sanitized preimage and no infrastructure delta.
  Bicep validation/what-if and Terraform apply are inapplicable to an existing
  Job image-only PATCH; no resources or role assignments are created.
- [x] Configuration/static role review: no permissions/identity/env/root/sizing
  changes; working existing registry secretRef retained. Applicable policy
  assignments and publisher roles captured; no managed-identity ACR repair.
- [x] Docker build and real-package verification: exact merge, native amd64,
  every packaged source hash, config hash, metadata and offline retry smoke.
- [x] Validation proof below records executed commands/results; no unresolved
  build, test, context or package errors.

### Section 7: F05 validation proof (2026-10-28)

PR428 merged at2026-10-28T16:11:02Z as
`1b8829a45bb8254e509ca2b97816da5ef56c5c63`.
Exact-head CI40721263357 completed success: all7jobs, no bypass.
`pytest` selected9coupled suites:361cases passed; retry suite34cases.
`ruff check`, `git diff --check`, web `lint:fix` and1,993web cases passed.
`az account/group/env/acr show/list` confirmed Enabled subscription and
Succeeded existing environment/registry. `job execution list` showed no Running.
`az role assignment list` and `az policy assignment list` retained readbacks.
Only two Python source/test paths differ from prior main; no IaC or role delta.

`az acr build --platform linux/amd64` from immutable merged-main archive
succeeded as nativecr38 in4m22s; digest
`sha256:acba3e4533737ab841bb04e2d22ce996503327d98f9473c9da756311a54dabf8`.
`docker run --network none --read-only --entrypoint python` on that digest
passed ARG transport/throttle retry, exact scoped continuation, bounded
exhaustion, Costfive retries/120scap and nonfinite-header checks.
All478packaged source hashes and build metadata match the exact archive;
config hash48f22850 retains all91F03thresholds unchanged.
`files/f05-build-receipt.json` and `f05-packaged-smoke-result.json` retain proof.
No live Job image mutation has occurred at validation time.

### F05 rollout complete; future live acceptance pending

Superseding user-directed immediate test (2026-10-28T22:46Z): exactly one
execution `aiops-dev-inventory-publication-8ju7tvv` started without overrides
after no-running/exact-image checks. The future one-shot was cleared.
This execution FAILED before acquisition: remote RunLock `create_file`
returned ResourceNotFoundError because Fabric capacity
`517c0d4e-9472-4288-8e61-343060396887` is unavailable. Independent ARM read
confirms capacity `aiopsdevcap7h0ih3` is Paused. Container exited1 at22:47:19Z.
Counted retrieval includes43matching ingested console rows. ARG/Cost retry
paths were not reached; no new generation/cost landing or completeness is claimed.
Protected settings still match; cron unchanged. No resume or second start.
Live failure receipt `files/f05-live-receipt.json` SHA-256
`b4554f2f41dc2861652165f78e8d510967f51681fc8d4bda8ce190b48687c5f8`.
Blocker: administrator restores capacity availability before a separately
authorized retest. This is not established as an F05 code regression.
The read-only postcheck helper overwrote its historical fixed-name artifact;
the original rollout receipt remains unchanged but its postcheck artifact hash
is superseded. The live receipt explicitly seals the replacement postcheck.

### F05 user-authorized resumed-capacity retest complete

The user confirmed capacity had resumed and explicitly directed one immediate
retest. Prestart checks confirmed capacity Active, no running execution, exact
qualified image and unchanged daily cron. Exactly one run,
`aiops-dev-inventory-publication-l2aoold`, started at
`2026-10-29T00:15:08Z` and Succeeded at `00:26:12Z` using digest
`sha256:acba3e4533737ab841bb04e2d22ce996503327d98f9473c9da756311a54dabf8`.
No overrides or extra starts.

The complete set of currently ingested matching Log Analytics console records
was queried and count-checked:1row retrieved of1reported, the publisher's
completed summary. It contains no retry warning or failure; therefore this
live run did not demonstrate an actual retry. The merged implementation's
retry path remains supported by the 34 targeted regression cases and actual
offline packaged smoke, while the initial paused-capacity execution never
reached acquisition. Do not equate no observed warning to loss-free log
ingestion or infer retries occurred.

Summary identifies combined generation
`activation-ef2d4127-9f9a-403d-9328-1c11fcb8748c`. Merged F04/F05
`DatasetStore.verify_combined_activation_generation` and
`read_verified_generation` verified its exact pinned live bytes; source
`demo/e89fe1a4-b60d-4396-a4e2-1efa05f26280`, scope subscription
`890c9bfc-d09c-4143-9ce5-465e75e3eecc`, manifest integrity
`e3c2875cc6ab1bd67e2f973b11d8f0ed8a78d5d1618d664c555d9b954ababa1c`.
The pinned `entities/CostActual` dataset contains **690 integrity-verified
normalized rows**. This confirms actual cost rows landed for the pinned source;
it does not assert raw provider fidelity or global acquisition completeness.

Post-run full normalized protected-state comparison passed: Job image was the
only changed template property; API/web, grants, roots, sizing and cron are
unchanged. Prior paused-capacity failure receipt remains preserved as separate
history. Final bounded retest receipt:
`files/f05-resumed-retest-receipt.json`, SHA-256
`612d0cb608696944a82284e66ee269c293a014e15f34cc772857d6d8a0fd87a6`.
No consumer-readiness, raw-fidelity, scale, SQL/Blob or broker qualification.

The guarded Job-template-only image PATCH was accepted and provisioned
Succeeded. Post-readback exactly preserves API resource, serving revision
`aiops-dev-api--f03-b841d1ce`, serving template/traffic, web/other Apps, other
Jobs and full normalized Job state except its image. Publisher roles match
preimage; API health is ok/ready and Workbench Identity returns HTTP200.
Cron remains `30 14 * * *`; latest execution remains the historical
`aiops-dev-inventory-publication-29886630`. No run was started.

Sealed rollout receipt `files/f05-release-receipt.json` has SHA-256
`6fa30317adf893650baf9db153cf96af9588141c3265352841da7a4cbded43a5`.
It explicitly reports natural-run acceptance PENDING, not completed.
One-shot same-session automation `f973cd4b-bd0d-489f-93b0-44f6adba7acb`
wakes at2026-10-29T14:50Z to inspect the natural14:30Z execution read-only,
verify exact image/terminal outcome and complete correlated retry/failure logs.
The finite helper deadline is15:40Z. No browser, manual Job run, redeployment
or schedule/grant change is authorized by that check.

Final live receipt will be a separate artifact; preserve this adoption receipt
and all historical F02/F03/F04 evidence. Costs landing requires exact new-source
dataset evidence, not merely a successful Job. No completeness or readiness
claim has been made.

## F03 daily inventory freshness policy release (2026-10-28)

Status: Validated

The user directed continued autonomous implementation after the F03 release
handoff. Integrate sealed patch `a6d41bf97c57856489bfa7e4e7c8b2d14cf57ce7751ff45bb62733aa2c51055a`
on current main, pass CI and merge, then adopt only the two-table freshness
policy on established dev consumers. Existing F04 acceptance remains historical.

Recipe: AZCLI existing-resource update in subscription
`890c9bfc-d09c-4143-9ce5-465e75e3eecc`, Australia East, `aiops-dev-rg`.
No new resources, infrastructure apply, grants, schedule changes or manual runs.
Only `bronze_resources` and `silver_vm_inventory` receive 93,600 seconds.
All other product budgets remain 10,800 seconds.

- [x] Integrate the exact two-path candidate and validate coupled health behavior.
- [x] Commit/push, open PR, await actual CI completion and merge.
- [x] Inspect live config composition and choose minimal runtime adoption.
- [x] Capture protected preimages; run azure-validate before azure-deploy.
- [x] Adopt merged policy and verify live API thresholds and unchanged products.
- [x] Seal merge/runtime/receipt/preservation evidence and close the loop.

Rollback will restore only changed config/image properties from exact preimages,
after checking for concurrent changes. Preserve actual API 4 CPU/16 GiB, identities,
storage roots, secrets, all unrelated env, web and other job pins, and daily
cron `30 14 * * *`. Existing publication receipts suffice; do not start a job.

### F03 prepared adoption decision and validation inputs

The two-path reviewed candidate is commit `b9af7598611d4364cc81ca391a327bf84d651931`.
PR 427 CI run `40712057587` passed before merge. Local policy/health/evidence
90 cases and medallion HTTP 49 cases pass; Ruff/format/diff pass. Required web
lint-fix and 1,993 cases pass after putting the existing venv on PATH (the first
attempt used system Python without FastAPI; no dependency changes were needed).

Both API and inventory Job resolve `AIOPS_FABRIC_CONFIG=/app/fabric.config.yaml`,
copied from deploy YAML by Dockerfile. Freshness config reads this file, not
the unrelated Fabric connection JSON override. Therefore build once from exact
merged main and update these two image pins only (plus API source/digest
metadata). Do not inject a runtime JSON policy that the freshness reader ignores.

Captured `files/f03-runtime-preimage.json`. Actual serving API revision is
`aiops-dev-api--r420-99193f04`, 100% traffic, 4 CPU/16 GiB; preserve actual live
sizing rather than an older 8-GiB historical baseline. The inactive latest
`fabric-reader-20261028` has a different gateway grants value; construct the new
revision from the actual serving template, not that unrelated latest template.
Keep serving grants/secrets identical and keep that existing inactive revision.
Job has no active execution and remains 2 CPU/4 GiB, cron `30 14 * * *`.

Use existing-resource ARM template-only PATCH with concurrency prechecks and
explicitly route API traffic only after candidate health. Preserve app-wide
identity/config, normalized serving template, other Apps and Job image pins.
Rollback is original traffic to serving revision and original Job image only.
No AZD init/provision, Terraform apply, grants, new infrastructure, or job start.
User confirmed autonomous continuation; existing dev context is unchanged.

### All validation checks pass - F03 existing-resource AZCLI rollout

- [x] Core validation: CLI authentication, exact dev subscription and RG,
  actual serving API and Job preimages, no running producer.
  No infrastructure template deployment is involved; Bicep build,
  deployment validate and what-if are inapplicable to template-only image PATCH.
- [x] Docker build: exact merged-main archive, native linux/amd64 ACR build,
  packaged source/config/metadata parity and offline freshness boundary smoke.
- [x] Azure Policy validation: applicable assignments captured; no resource
  type/region/identity/permission changes and existing registry path retained.
- [x] Static role verification: two YAML/test paths introduce no data operations
  or identity edges. Preserve all registry and managed identity relationships;
  no provision/AcrPull repair/grant is warranted for a working existing target.
- [x] Validation proof: record exact merge/build/package checks before pins.

### Section 7: Validation Proof - F03 (2026-10-28)

- CI `40712057587`: completed success for exact head `b9af7598611d4364cc81ca391a327bf84d651931`;
  all four backend shards, aggregate backend, frontend and security passed.
- PR 427 merged at `2026-10-28T15:16:34Z`, merge commit
  `b841d1cef5a45c5da4d2fa8f4cf708ab734ef072`; no bypass.
- Native ACR build uses an immutable archive of that exact merge, no dirty
  checkout context, tag `aiops-api:r427-b841d1ce-20261028`.
- `az acr build --platform linux/amd64`: native run `cr37` Succeeded at
  `2026-10-28T15:21:21Z`, digest
  `sha256:d962205eaaa44e9649e3baf364d696f2984ca847f8ccd32ec3e930bf115c7f6f`.
- `docker run --network none --read-only --entrypoint python ...` real package
  smoke passes: exact 26h and +1-second boundaries, missing evidence unknown.
  All 478 packaged source files and config hash match exact merged-main archive;
  build metadata source revision is the merge SHA.
- `FreshnessSloConfig.from_config()` on actual packaged default path produces
  93,600 seconds only for two declared inventory products; other 89 registered
  schema/product names and unknown-product fallback remain 10,800 seconds.
- `f03-runtime-evidence.py`: sanitized preimages retained; no running Job.
  `az account/group/env/acr show`: exact established context, healthy resources.
  `az policy assignment list` and unchanged publisher role readbacks captured.
  Static merge diff has no IaC or identity delta. No new role grants required.
- `files/f03-build-receipt.json` and `f03-packaged-smoke-result.json` retain
  exact commands/results and package source hashes. No runtime mutation had
  occurred at validation time.

### F03 runtime adoption - bounded live acceptance complete

Healthy revision `aiops-dev-api--f03-b841d1ce` now has 100% API traffic;
the inventory-publication Job also pins digest `d962205e…`. Guarded normalized
pre/post verification passed for original serving env/grants/secrets, app-wide
configuration/identity, actual sizing, Job cron/config/roots, and all other
App/Job pins. No existing revision was deactivated and no producer run started.
Independent persisted publication receipt remains exactly equal to F04 receipt;
publisher role readbacks are unchanged. Public API health is ok/ready.

Operational corrections were limited to deployment helpers: successful ARM
PATCH can return an empty 202 body (verify actual state, never retry blindly);
the older Job PATCH schema excludes CLI's read-only `imageType` field;
revision/app read APIs expose default scaler fields differently (normalize only
documented 30-second/300-second defaults, never ignore a changed value).
Initial candidate scheduling reported workload-profile maximum nodes, then
scheduled normally and became Healthy without any scaling/quota mutation.
The new API log capture contains no error/traceback/warning matches.

The authorized normal-auth Workbench receipt was independently hash-verified
and correlated with the exact persisted DFS publication receipt. Both inventory
products return HTTP 200 with `stale_after_seconds` and
`freshness_budget.threshold_seconds` equal to 93,600 and `table_override`.
Registered controls `bronze_subscriptions`, `bronze_resourcegroups` and
`bronze_advisor` each return both fields as 10,800 and `defaults`, under the same
exact subscription scope. All 91 schema/product names were checked in the
byte-matched deployed package; this is not a claim of 91 live API observations.
Unregistered illustrative products were not accepted as live controls.

Bronze publication attempt and all six stage facts exactly match independent
DFS evidence: two recorded, four unknown, with the no-readiness disclaimer
unchanged. Browser restored Identity/All/dialogs0/1440x1000 and disconnected;
the original lease was released and an unnecessary replacement grant was
released unused. No further browser access or publication is required.

Final receipt: session `files/f03-release-receipt.json`,
SHA-256 `3c0d976ddd9a43d845a9cb3a7385179840725ee67b896679e23c9e2789af5a98`.
The original partial browser receipt remains preserved alongside the complete
receipt `11e4cb56...`. Job adoption is its scheduled template/image only: no
execution on the new F03 image is claimed. No consumer readiness, acquisition
completeness, raw fidelity, SQL/Blob authority or broker qualification is implied.

## F04 source provenance integration and dev rollout (2026-10-28)

Status: Validated
User-directed authorization: integrate accepted frozen F04 patch, validate,
create/merge its PR, build immutable merged-main image, deploy to the established
dev runtime and verify adoption. Excludes F03 and the SQL/Blob broker stack.

- [x] Refresh canonical main and isolate the four-path sealed patch from dirty work.
- [x] Run source and packaging checks, commit/push and merge the bounded PR.
- [x] Capture dev runtime preimages and select only F04-consuming image pins.
- [x] Complete azure-validate and azure-deploy checks before cloud mutation.
- [x] Build merged-main immutable image, verify packaged source and update approved pins.
- [ ] Verify runtime adoption, unchanged protected settings and bounded live evidence.

Preserve schedules, grants, identities, retention, roots, API/web configuration
and unrelated source. No manual publication execution is inferred. Any live
generation verification uses an already-authorized scheduled run. Existing
release evidence below remains historical and must not be overwritten.

Recipe: AZCLI, existing resources only. Reuse user-confirmed established dev
subscription `ME-MngEnvMCAP448721-pangj-1`
(`890c9bfc-d09c-4143-9ce5-465e75e3eecc`), Australia East, `aiops-dev-rg`.
No new resources or quota changes. Build only `aiops-api` from an immutable
archive of final merged main via native linux/amd64 ACR Tasks. Verify build
metadata plus source bytes and run offline packaged provenance checks.

The F04-consuming rollout target is the existing
`aiops-dev-inventory-publication` Job. Update only its container image digest;
API/web/MCP, ontology fixtures/coordinator, F03 config, storage roots, grants,
retention, command, sizing and cron remain unchanged. Current producer image
is r420 digest `f76b0cd52d8b41cde7ff1510ea3cff3c14e52034ba005cbd4b34253d74895fb3`.
Rollback restores that exact digest only if the protected template still
matches. Do not start a publication run manually. The natural 14:30 UTC run
can establish generated manifest adoption; image-pin readback alone cannot.

Final integration candidate supersedes initial source patch `79eaade1`:
`f04-integrated-candidate.patch`, SHA-256
`e7262479eaa16e2854bd0d6049fe62b86b04ef66f760148b100a4662429c49d0`.
Broader producer tests exposed writer-ID, connection-scoped run-ID and legacy
timestamp compatibility issues. Corrected source without changing old
fixtures: verify exact selected safe directory with original manifest run ID;
allow repeated run IDs across distinct connections; retain missing legacy
times as null, rejecting malformed recorded times. Fabric independently
reviewed the correction without blocking findings. All original negative
contracts remain; 181 coupled producer/activation/replay/provenance cases pass,
31 of them new. Web lint and 1,993 tests pass. Staged source is exactly four
F04 paths; unrelated plan/broker/IaC files stay excluded.

Additional shared storage/durability/subscription/packaging checks pass (one
existing conditional skip). Feature commit `9872811f` is pushed; PR 426 is open
against main with exactly the four F04 paths. CI run `40699955041` is active;
merge/build are gated on its actual completion, not bypassed. The current
session is the discovered Unified Deployment owner, so no self-notification
message is sent.

### All validation checks pass - F04 scoped image rollout

- [x] Core validation: authenticated subscription/context; existing target and
  image build path; exact protected Job preimage and no active execution.
  No Bicep/ARM resource deployment is involved, so template validate/what-if
  are inapplicable; scope is one existing Job image property.
- [x] Docker build: immutable merged-main archive, native linux/amd64 ACR build,
  exact build metadata/source byte parity and offline packaged smoke.
- [x] Azure Policy validation: inspect applicable assignments for existing
  dev target; no infrastructure, region or resource-type changes.
- [x] Static role verification: preserve publisher identity, Key Vault and
  existing registry credential mechanism; F04 uses the same storage permissions.
- [x] Record proof and complete validation before image-pin mutation.

### Section 7: Validation Proof - F04 (2026-10-28)

- `gh run view 40699955041`: all four backend shards, aggregate backend,
  frontend (including production build) and security checks passed for exact
  head `9872811f`. PR 426 merged at `14:01:04Z` as
  `412bfbc84f54bd3419a09cbccafbbf270439a765`. No admin bypass.
- `az account show`, registry/Job reads: approved subscription/region and
  existing target confirmed. No new resource or capacity request.
- `f04-preservation.py pre`: full protected Job projection recorded with env
  value hashes, all app revisions/images/traffic and other Job image pins.
  Protected Job SHA-256 `8e35f35497f826f709de4bee03049937583bfbb181a94274178421f5baa40f20`.
  Existing producer r420 digest and daily cron match approved scope; no run active.
- `az policy assignment list --scope <dev resource group>` returned `[]`.
- Static review of `infra/terraform/inventory_publication_job.tf` confirms
  same publisher UAI, Key Vault secret role and existing registry credentials.
  F04 adds no role, resource, auth mechanism or remote write location.
- Native `az acr build --platform linux/amd64` from immutable merged-main
  archive succeeded as `cr36` in `4m57s`; tag `r426-412bfbc8-20261028`,
  digest `sha256:f2b17a4729b243567d86ccfc119f4653202942e55c8583bd94b3892c108510ea`.
- `docker image inspect` confirms `linux/amd64`. Exact image offline readback
  matches all **478** merged-main source files, exact source revision in build
  metadata and unchanged packaged deployment config. No F03/broker dirty work
  is packaged.
- Locked-down `docker run --network none --read-only` packaged smoke passes:
  exact verified rows, writer-sanitized IDs/collision suffixes, connection-scoped
  duplicate run IDs, null legacy times, replay/reuse and corrupt-source rejection.
  No cloud calls, credentials or mounted local source used.
- Initial registry pull found expired local Docker login; normal `az acr login`
  repaired it. No cloud grants or identity changes were made.

### F04 image rollout result - bounded live generation accepted

The producer-only image update Succeeded at `2026-10-28T14:09:36Z`, with no
active execution and no command/env/resource/config overrides. Live readback
pins qualified digest `f2b17a47…`. Full sanitized protected Job projection
equals the preimage (`8e35f354…`); all Container App revisions/images/traffic and
all other Job image pins remain unchanged. Live publisher ARM role readback
is the same Key Vault Secrets User assignment; no grants were changed.
Protected API health remains HTTP 200.

The unchanged daily cron ran naturally at `2026-10-28T14:30:00Z`; execution
`aiops-dev-inventory-publication-29886630` Succeeded at `14:43:14Z` on the exact
qualified digest. No manual start or retry was requested.

Merged-main `verify_combined_activation_generation` and `read_verified_generation`
passed against live DFS GET-only bytes: 55 combined and 54 source datasets.
Combined `activation-4a26ede5-1d96-4863-b407-7f219b6c8ad6` explicitly binds demo
to source `e2a878bc-397e-4f2f-80c7-0236abeef839`, integrity hash
`9e9a654cf9383e0c99a221411f8b0c903822118318863a003f9479853e08fad7`.
Actual retained source is under `Files/aiops/connections/connections/demo`;
the CLI uses connection-home as coordinator output root. Verification used
the exact retained source, not a mutable current fallback.

API health and web returned HTTP 200. Authorized retained-browser regression
and independent exact-scope DFS receipt match: attempt `65852c6b-4cf2-4b4a-b168-d48640369e9b`,
publication run `64dcee07-07ab-4d34-aade-3bc06ca3e3ce`. Two publisher stages
remain recorded and four qualification stages unknown/null; disclaimer and
browser restoration were confirmed.

Retained execution logs show completed publication and graph refresh, plus a
nonfatal Cost Management HTTP 429: discovery explicitly continued without cost
actuals. This does not qualify acquisition completeness. F04 acceptance is
limited to explicit normalized-source pairing and verified pinned reads, not
raw fidelity, consumer readiness, scale, F03 or broker adoption.
Sealed session receipt: `files/f04-release-receipt.json`, SHA-256
`d39a7ede48e0421eb71a0fffc8e213c2f497c14020a2a22bad55f93eb2b4953f`.

## F02 dedicated producer image rollout (2026-10-28)

Status: Validated
Deployment approval: explicit user authorization received for this exact
producer-pin-only update; rollout in progress.
Update only the existing `aiops-dev-inventory-publication` Job's dedicated
`inventory_publication_image_digest` pin to
`sha256:f76b0cd52d8b41cde7ff1510ea3cff3c14e52034ba005cbd4b34253d74895fb3`.
This immutable linux/amd64 image is r420 (`99193f04`); the exact packaged
producer/orchestration/evidence source bytes were inspected offline and match
the reviewed source. Do not update the API or web app, rebuild, or execute the
Job.

- [x] Re-read and compare live Job/template preimage to approved scope.
- [x] Verify immutable image digest and F02 receipt-writing source chain.
- [x] Refresh preservation preimage: API revision is
  `aiops-dev-api--fabric-reader-20261028` on the same approved r420 digest
  `f76b0cd5…`; web revision is `aiops-dev-web--r421-b19eedd4` on its current
  image. Preserve these live revisions/images exactly.
- [x] Update only the dedicated producer digest pin through the reviewed path.
- [x] Read back image digest and all protected Job settings.
- [x] Persist sanitized rollout evidence; no Job trigger.

Preserve schedule `30 14 * * *` UTC, `python -m
intelligence.inventory.publication_cli`, 2 CPU / 4Gi, publisher identity and
grants, storage roots/scope, Fabric/graph/native-registry configuration, retry
settings, API/web images, traffic and all other settings. No grants, Terraform
apply, manual Job trigger, or unrelated deployment. F02 remains live-open until
a subsequent scheduled execution produces the exact-scope persistent receipt
and API/UI positive-branch verification succeeds.

### All validation checks pass - dedicated image pin

- [x] Core validation: Azure CLI authenticated to the approved subscription;
  exact existing Job, API and registry state read back before change.
- [x] Immutable image qualification: retained r420 digest verified as
  linux/amd64; packaged CLI/orchestration/evidence source files byte-match
  reviewed `99193f04`; no container execution, network or Job invocation.
- [x] Azure policy/identity review: no resource, role, identity, grant or scope
  changes; preserve current applicable policy and all existing permissions.
- [x] Recipe applicability: image already exists and is immutable, so no Docker
  build or dependency/package changes are needed.
- [x] Build verification: no source or image build is in scope. Offline
  inspection of the retained amd64 image and exact source-byte parity is the
  applicable immutable-image qualification.
- [x] Static role verification: reviewed
  `infra/terraform/inventory_publication_job.tf`; this rollout changes no
  identity or role assignment. The existing publisher identity, registry
  configuration and secrets remain unchanged.

Preflight command proof (2026-10-28):

- `az account show`: subscription `890c9bfc-d09c-4143-9ce5-465e75e3eecc`,
  tenant `262a3a77-7d74-4684-8937-897d98d2a17a`.
- `az containerapp job show -g aiops-dev-rg -n
  aiops-dev-inventory-publication`: exact target exists, current image is
  `sha256:fbb773f7…`; schedule, command, user-assigned identity, config,
  credentials, resources and all env values match approved preservation scope.
- `az containerapp show` for `aiops-dev-api` and `aiops-dev-web`: current API
  `aiops-dev-api--fabric-reader-20261028` still uses the approved r420 digest;
  web is `aiops-dev-web--r421-b19eedd4`. Both are preservation baselines and
  excluded from mutation.
- `az policy assignment list` at the resource group returned `[]`.
- `az acr manifest show-metadata`: target image exists as linux/amd64, tag
  `r420-99193f04-20261027`; offline container inspection found exact byte
  equality for all three producer source modules with reviewed source
  `99193f04a1d1f407a86e0519510c661ddf516242`.
- F02 source call chain: publication CLI calls the inventory orchestrator;
  the orchestrator invokes `publish_with_product_evidence` using
  `ProductEvidenceStore`; the wrapper records `begin` and `finish`.

### Rollout result

Updated at `2026-10-28T09:37:14Z` using only
`az containerapp job update --image <immutable digest>`. The Job is
`Succeeded` / `Ready` and now pins
`aiopsdevacr7h0ih3.azurecr.io/aiops-api@sha256:f76b0cd52d8b41cde7ff1510ea3cff3c14e52034ba005cbd4b34253d74895fb3`.
The normalized full Job template/configuration hash, with only container image
value normalized, is identical before and after (`839b7133…`). Schedule,
command, 2 CPU / 4Gi, publisher identity, registry credentials, env values,
storage roots, Fabric/graph/native-registry configuration and all other
settings are unchanged.

API remains on `aiops-dev-api--fabric-reader-20261028` and its pre-update
r420 digest; web remains on `aiops-dev-web--r421-b19eedd4` and its pre-update
digest. Live publisher identity role read-back shows its existing Key Vault
Secrets User assignment only; no role/grant operation was made. Eighteen prior
Job execution records were returned; none started after the update. No manual
trigger was issued. The next scheduled execution is not yet due.

Sanitized evidence:
`f02-producer-rollout-receipt-20261028.json`, SHA-256
`b9625ef3fad6a2968ae92a24bf93257d35ed63bcabeaf42298ba4a0cf0d58618`.
F02 remains **live-open** until the producer writes the exact-scope persistent
receipt and API/UI positive-branch verification passes. This pin update alone
does not qualify publication or receipt persistence.

### Subsequent explicit execution authorization

After the image-only rollout, the user explicitly requested "start the schedule
run and close it". Exactly one execution,
`aiops-dev-inventory-publication-dd7kfs6`, started at
`2026-10-28T09:41:34Z` using the existing template without overrides. This later
authorization supersedes the earlier no-manual-trigger restriction only for
that execution; it does not authorize retries, schedule changes or grants.
The image-only rollout receipt above remains a historical pre-execution record.
Execution, exact-scope persisted receipt and authenticated API/UI acceptance
are being verified separately; F02 remains live-open.

The authorized execution subsequently **Succeeded** at `2026-10-28T09:54:14Z`.
Its final summary records source
`activation-78c87e41-de42-4699-9c5e-5baa52ab0e02`, 198 published tables and graph
refresh `Completed`. Registry revision 104 confirms the sole active connection
`demo` and subscription `890c9bfc-d09c-4143-9ce5-465e75e3eecc`; its completed
result recomputes exact receipt key
`fabric/product-publication/f0a71eaedc3ceb0b59f09e6dac4154f21c9fde059249fc703552fe850bb27d03.json`.
Authenticated DFS GET and full receipt validation pass. Publication attempt
`223788f4-b97a-4aed-927f-2c7ab910dc74`, run
`b224d559-706d-45b3-aa38-8e495bff9283`, observed
`2026-10-28T09:50:18.811624Z`, match this execution's source and time window.
For `bronze_resources`, only validated/persisted are recorded; acquired,
registered, active and consumer-query-verified remain unknown. Early
service-health acquisition logged a connection error, not blanket acquisition
qualification. Post-execution full protected Job projection and API/web
revisions/images are unchanged. API/UI positive-branch verification remains
pending; Job success alone does not close F02.

### F02 bounded live acceptance closed

The subsequent authenticated Workbench API returned HTTP 200 for exact
subscription scope and `bronze_resources`; its full publication attempt and
validated/persisted facts match the independently read DFS receipt. Visible UI
verification at `2026-10-28T09:56:12Z` shows the same generation/time, two
`Completion recorded` stages and four `Unknown` stages, with the explicit
non-readiness disclaimer. The authorized browser was restored to Identity /
All subscriptions / no dialogs and released. Fabric independently correlated
the storage, API and UI evidence.

**F02 is closed only for the implemented historical publisher
validation/persistence recorder and exact-scope API/UI path.** Acquisition
completeness, registration, active-product and consumer-query readiness remain
unqualified; no SQL/Blob live or F03 policy qualification is implied.
The obsolete one-shot verification automation was cleared without changing the
Azure Job cron. Final evidence is
`f02-dd7kfs6-acceptance-receipt.json`; API/UI receipt
`f02-oct28-positive.receipt.json` has SHA-256
`9b24a296078234dd7d39a0946e08387c23446814a2ae44499ae8ffa1a5db3f2d`.

## Source-only verifier permission follow-up (2026-10-28)

Status: Preparation only; no live validation or deployment authority.
Approved bounded continuation: add separate UNASSIGNED read-only role definitions
and proposed exact-account / Blob-service / container bindings. Preserve all
accepted base files in the prior seal; ship only an additive follow-up patch.
No new role assignments, SQL/data grants, locking, executable hosting, main-state
wiring or cloud calls. Disabled root must still create zero resources.

- [x] Complete bounded frozen protocol correction review.
- [x] Add verifier role declarations, explicit output and offline contract/mock tests.
- [x] Validate with pinned installed providers; separate exact-base sealing follows.

Three single-action read-only role definitions, all UNASSIGNED, and separate
`publication_backend_verifier_roles_v1` proposal output. Prior nine accepted
source files unchanged. Schema validation, 24 mock-only plans, 125 related
Python tests, web lint and 1993 web tests pass. No deployment handoff.

## Source-only publication backend increment (2026-10-28)

Status for this increment: Preparation only; NOT deployment validated or authorized.

- [x] Inspect pinned providers and existing identity, hosting and private-network patterns.
- [x] Add default-disabled isolated SQL, Blob and broker declarations with explicit reviewed inputs.
- [x] Keep SQL procedure bootstrap and retention locking outside runtime/IaC automation.
- [x] Run offline schema/contract tests; separate exact-base patch sealing follows.

Separate root `infra/publication-backend`, not wired into the main stack/state.
Provider schema validation and 21 mock-only Terraform plans pass; 28 related
Python contracts pass. Required web lint and 1993 tests pass with repository
Python on PATH. Only an Unlocked draft policy and Manual exit-78 NONOPERABLE
hosting scaffold are expressible. No storage write role assignment, SQL grant,
policy locking or broker endpoint. Connectivity and runtime remain unqualified.

No live Terraform plan/apply, grants, cloud writes, commit or push are in scope.
Existing rollout evidence and production resources remain unchanged.

Status: Validated

## Direct rollout authorization (2026-10-28)

User explicitly instructed "then roll it out" and autonomous continuation.
Approved scope: qualify current-source image, two exact registry-only AcrPull
assignments for existing coordinator and collector identities, four fixed
manual Jobs, coordinator image and four verified durable HOME bindings.
Do not execute Jobs, publish, run drills, change production pins or traffic,
or grant data-write capabilities. Earlier approval holds below are historical
and superseded only for this exact scope. Image build is already in flight;
do not duplicate or poll it before its completion notification.

### Current rollout validation proof

- Immutable current-main build cr33 Succeeded. Native linux/amd64 image
  sha256:faf636fa1a1a8bc442aedfdc239914df17d699d6e59a40af8dd54a6c7243fb43
  qualified against source1aa32c4f:485 packaged files match, metadata exact,
  coordinator/runtime/API imports pass. No production image update planned.
- Fixed four-Job source rendering binds independently read-back MI IDs,
  existing environment and verified five-item contract. Evidence API URL
  intentionally targets the actual-MI-qualified zero-traffic candidate.
- ARM validation Succeeded. Fixed Job what-if exactly4Creates; registry
  role what-if exactly2Creates; no existing-resource modifications/deletes.
- Static registry roles: built-in AcrPull only, scoped to existing registry
  and two existing identities. No data-write grants or new identities.
- Coordinator before/candidate inverse equality PASS after restoring image
  and four HOME values. Configuration, commands, identity preserved.
- 64 coupled access/deployment tests pass; helper Python compile passes.
- ACR qualification first failed on multiline command YAML serialization;
  single-line-safe encoding corrected it, no image rebuild or source change.
- Azure account/tenant verified; inherited applicable policy list empty.
- Deployment postconditions: all4fixedJobs Succeeded/Manual/0executions,
  coordinator exact image/four-root change only, registry roles read-back,
  four protected apps/publisher hashes unchanged, no coordinator execution.

### Rollout result

PREREQUISITES_DEPLOYED_NOT_EXECUTED. Both exact registry-only AcrPull
assignments read-back verified. All four fixed Jobs provisioned Succeeded,
Manual, zero executions. Coordinator now uses qualified faf636fa digest
and exact four durable HOME values. Its configuration/identity/command/args
are unchanged. API/web/MCP apps and publisher protected hashes unchanged.
Initial coordinator PATCH rejected read-only imageType from GET; removed only
that write-invalid field. Postread omitted empty ephemeralStorage; precise
omitted/empty normalization preserves all explicit resource comparisons.
No Jobs/publication/drills, pins or traffic changes. Plan20 remains unexecuted.
Evidence and rollback templates retained in session files/fabric-prerequisites-current.

## Current Fabric coordinator and fixed-Job prerequisite plan (2026-10-28)

- Active execution scope is narrowed to current-main immutable API image
  build/package qualification under standing centralized build authority.
  No runtime deployment or role creation is authorized by this section.
- Local Docker daemon is unavailable; use existing configured ACR Tasks
  native linux/amd64 build path, immutable git archive only. Do not start
  another local daemon, upload dirty files or build unrelated web/MCP images.
- ARM shape validation Succeeded and what-if confirms exactly four Creates,
  no Modifies/Deletes for fixed Jobs. Retained r420 image was used strictly
  as a shape-validation parameter, NOT current-source image qualification.
- Both coordinator and collector lack registry AcrPull. Those two exact
  assignments remain held pending affirmative protected-scope approval;
  no runtime Job execution or resource creation is part of image build.

### All validation checks pass - image preparation scope only

- [x] Core Validation (CLI, auth, build, validate, what-if): authenticated
  corrected tenant/subscription and existing registry; no infrastructure
  deployment in image-only scope. Separate fixed-Job ARM shape validation
  passed with exactly four Creates/no Modifies/Deletes.
- [x] Docker Build (if containerized): Dockerfile and locked uv context
  reviewed; local daemon unavailable. Validate by native ACR Tasks build
  from immutable source archive before any image use. Build cr33 and exact
  485-file in-container qualification passed for digest faf636fa.
- [x] Azure Policy Validation: inherited applicable RG assignment list empty.
- [x] Static role verification: image build creates no identity/role/grant.
  Terraform already declares registry-scoped coordinator and collector
  AcrPull. Missing deployed assignments prevent runtime rollout, not build.
- MODIFY existing corrected-target runtime with AZCLI; current source
  1aa32c4f0a2e4934fa6e2b025463bf4d38e47478. Historical packages are evidence
  only and must not be applied unchanged.
- Existing target: tenant262a3a77-7d74-4684-8937-897d98d2a17a,
  subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc, aiops-dev-rg,
  AustraliaEast, aiops-dev-cae and aiopsdevacr7h0ih3.
- Effective collector MI read access now established with real tokens from
  existing azure-mcp--nmi390a: candidate API GET200; all five exact Lakehouse
  metadata GETs200 and OneLake Files list GETs200. Active API control401.
  Tokens never printed/retained. No grants or existing resources changed.
- Next proposed scope: build/qualify one immutable current-source API image;
  update only coordinator image and four HOME bindings; add exact coordinator
  AcrPull on existing registry; create fixed manual source-contract Jobs
  aiops-dev-ontology-rbac-check, ontology-evidence-read,
  ontology-fixture-prepare and ontology-fixture-cleanup if still absent.
- Durable binding map: connection registry and ontology state in workspace
  7fdda9f2-46fa-4ce5-b810-57924ae32491 / Lakehouse
  340c485f-3d1c-4277-a1bd-84cdc340af47; commands in workspace
  305808e4-123a-4b95-8675-bf6f18f32a9c / Lakehouse
  09737a6d-1589-4d51-8bd4-d8f14cf586e3; dispatch in workspace
  f7e78968-9a6b-4d4e-b80b-3df259424b04 / Lakehouse
  ea0c340b-6655-4b37-8d34-dcf1848240f9. Preserve exact existing path suffixes
  from reviewed source; no inferred data relocation or initialization.
- RBAC canary remains workspace8fe1c03f-a73b-4ae0-a86c-152e37806d49 /
  Lakehouse6f667736-2979-4ed7-8f1b-17da4dd17735. Do not recreate or regrant
  already-converged collector access.
- Fresh readback confirms coordinator Manual/run-once/limit1, legacy image
  fe8080a8 and all four HOME settings under /tmp. Registry role readback
  reports no coordinator AcrPull. Current group inventory has six Jobs and
  none of the four proposed fixed Jobs.
- Proposed execution safety: exact before-template/identity/configuration
  guards, image/source/package qualification, local source-contract tests,
  ARM validation/what-if and inverse coordinator-template comparison before
  any apply. Preserve rollback template and immutable previous image.
- Excluded: Job execution, publication, drills, publisher configuration,
  production pins/traffic, data-write grants, broad Terraform apply.
  Plan20 acceptance and downstream gates remain closed.
- Direct bounded approval was requested via ask_user. Runtime returned user
  unavailable/work autonomously, not affirmative protected-operation approval.
  No new build, role assignment, Job provisioning or coordinator mutation
  has been executed. Plan is prepared, not deployment-ready or approved.
- User subsequently directed implementation and autonomous completion.
  Continue source/image preparation, exact template generation and validation;
  preserve the explicit no-publication/no-drill/no-traffic boundaries and
  retain fail-closed approval for new security grants.

## Active bounded Fabric collector mapping candidate (2026-10-28)

- MODIFY existing API configuration using AZCLI, no Terraform apply or build.
- Direct user request: troubleshoot and fix, persist Terraform/setup changes;
  no publication/drills, production pins or traffic changes.
- Subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc, tenant262a3a77-7d74-4684-8937-897d98d2a17a,
  existing aiops-dev-rg and AustraliaEast environment.
- Copy exact active API revision r420-99193f04 and its retained digest to a
  zero-traffic candidate. Add only collector object99771d97-d5d5-497f-8787-aca353201502
  -> reader, scope subscription890. Preserve every existing grant and setting.
- Multiple revision mode with explicit r420 traffic100 required before/after;
  do not change ingress/traffic. Preserve CPU4/memory16Gi/storage80Gi,
  identities, image, Jobs, web, pins and grounding.
- Source: new validation-only Terraform grant/output and setup fail-closed
  contract check. Existing OneLake reconciler already does ETag/server dry-run/
  readback; five exact item Read policies now converged.88 focused tests,
  Ruff, Terraform fmt/validate and offline setup preview passed.
- Preflight existing target, role, image, revision health and policy metadata;
  no new regional resource or compute SKU. No RBAC provisioning.
- Postcondition: candidate Ready and zero traffic; exact inverse-template
  equality after removing the single grant and revision suffix. Production
  API remains unchanged; live MI authorization and lifecycle stay unqualified.

### Validation Proof (current bounded candidate)

- All validation checks pass (AZCLI configuration-only applicability):
  - [x] Core CLI/auth/existing resource readback; Bicep build/validate/what-if
    inapplicable because no Bicep or ARM deployment is executed.
  - [x] Docker build inapplicable: unchanged already-deployed immutable image.
    No dependencies, packaging or runtime source changed in this candidate.
  - [x] Azure Policy validation: applicable assignment inventory empty; caller
    has inherited Owner. Existing resource/SKU/image, no new regional compute.
- 2026-10-28T00:08Z:88 focused Python tests passed, Ruff passed,
  terraform fmt/validate passed, setup fabric preview read-only passed.
- Fresh delegated Fabric readback: five Viewer assignments and five exact
  Phase13EvidenceRead item policies verified; repeat reconciliation no-op.
- Azure CLI account tenant/subscription confirmed; existing API Multiple mode
  with explicit r420-99193f04 traffic100. No active runtime mutation yet.
- Existing r420 revision Healthy/active: API digest f76b0cd52d8b41cde7ff1510ea3cff3c14e52034ba005cbd4b34253d74895fb3,
  CPU4/memory16Gi. Runtime source/image unchanged; Python compileall passed.
- npm lint:fix passed; full151files/1993webtests passed with project Python on
  PATH (first run's4 adapter failures were missing FastAPI in system Python).
- Static grant review: only reader scoped to subscription890, conditional
  Fabric+validation mode. No publisher/operator or unscoped collector grant.

All following release sections are historical and do not widen this scope.

## Active Health metrics warning correction

- Standing user-directed centralized integration/release; MODIFY existing
  application images only, AZCLI recipe. No provisioning or Terraform apply.
- Existing subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc, AustraliaEast,
  aiops-dev-rg / aiops-dev-cae / aiopsdevacr7h0ih3 retained.
- Include reviewed UI banner two paths f244bf80 and backend diagnostics five
  paths724f5869. Preserve unknown workspace presence; no cross-sub discovery,
  schema/classification, auth, grants, config, pins, Jobs or capacity changes.
- Central180affected backend tests/Ruff and1989webtests/lint/types/build pass.
  First web run hit unrelated worker RPC timeout; full bounded-workers rerun
  passed151files/1989tests without source workaround.
- Commit/CI/merge seven exact paths, clean final-main archive; one API and web
  build. Stage API0%, finite readiness18provider parity/protected equality,
  promote100%, then existing Single-mode web rollout and served asset parity.
- Preserve API4CPU/16Gi/80Gi,4apps/6Jobs/7APIroles, all settings/identities/
  Foundrypins/groundingOFF/Network/profiles/retention0. Retain r419API94373433
  and r418weba423d90d immutable rollback digests. Retire only guarded oldAPI0%.
- Same persistentEdge banner/warnings acceptance separate from source tests.
  Completed r419 six-case acceptance remains bounded and is not reopened.
- Current validation proof below; older sections are historical only.
- Preparation complete: fresh protectedbefore796f4ac1 equals r419after;
  existing AustraliaEastRG Succeeded, policies/capacity refreshed, both Docker
  build-check recipes passed. No IaC/auth/dependency manifests changed.
  Existing scoped roles retained; RBAC provisioning/azd environment creation
  inapplicable to this approved AZCLI image-only existing-resource update.
  Seven-path commitb2e43fe6 pushed; PR420 exact-headCI passed and merged.

### All validation checks pass - Health warning correction
- [x] Core CLI/auth/existing target validation and protected baseline.
  Bicep build/validate/what-if not applicable: no Bicep/infrastructure deployment.
- [x] Docker contexts/lockfile and both linux/amd64 build-check recipes.
- [x] Existing subscription/RG inherited Azure Policy retrieval and review.
- [x] Central180backendtests/Ruff;1989webtests/lint/types/productionbuild.
- [x] Static roles: no new identity, data operation, IaC or access delta.
- [x] Exact-head CI, guarded seven-path merge, canonical source archive.
- [x] Immutable API/web package qualification, zero-traffic parity, promotion.

### Section 7: Validation Proof - Health warning correction
- 2026-10-27: CLI authenticated existing subscription; `az group show`
  AustraliaEast Succeeded. `state.py before` hash796f4ac1 equals r419after;
 4apps/6Jobs/7APIroles and unchanged profiles/config/identity baseline recorded.
- `az policy assignment list` inherited scope refreshed; workload profiles
  refreshed without mutation. Existing image-only plan has no resource delta.
- `docker build --check --platform linux/amd64` API/web both passed;
  unchanged Dockerfiles/lockfiles. No new infrastructure or roles required.
- `uv run --no-sync pytest -q -o addopts=''` four Health/runtime/API/history
  suites180passed; changedPythonRuff/diff passed.
- `npm run lint:fix`, full `npm test -- --maxWorkers=2 --minWorkers=1`:
 151files/1989tests passed; `npx tsc --noEmit` and `npm run build` passed.
  Initial default-worker RPC timeout is retained, no source workaround.
- Owner UI10artifactseal0a708c8c and postimages verified; backendpatch724f5869
  reviewed whole and imported once. Seven-pathcommitb2e43fe6, CI pending.
- No outstanding local validation errors. GuardedCI/merge/archive and final
  immutable package/zero-traffic/provider/protected parity remain deploy gates.
- All8exactheadCI passed, sevenpath/head/baseguard passed; PR420merge source
  99193f04a1d1f407a86e0519510c661ddf516242, canonicalarchive
  SHA2563b36a522239a83bec99acfbba85101a83bb40a1f5190a7284d6d94afdc36de83.
  Official validationworkflowcomplete, authorizedValidated set, deployinvoked.
  API/web shared userassignedidentity existing scopedAcrPull verified live.
  ExactlyoneACRbuild each underway from finalmergedarchive.
- Executioncomplete05:59Z: ACRAPIcr30/webcr31 successful, offline500APIfiles/
  metadata/imports and70webassets/newcopy/oldabsenceclaimremoval passed.
  StagedHealthy0%/1ready0restarts, locked18providers passed. Fresholdbaseline
  transientcopilotFoundryAgentError preserved; gate strengthened to union of
  fresh and lockedr41918providers rather than lowering requirement.
- APIr420-99193f04/f76b0cd5 promoted100%05:57:57Z; webr420-99193f04/
  469f9c3aHealthy100%05:59:12Z;70servedassetsmatch. GuardedoldAPIr419
  unlabelled0%deactivated, no explicitdelete/retentionchange.
- Protectedbefore/preflight796f4ac1/stagedd639ab74/afterf164ac85 preserve all
  exceptAPI/webimages+ready revisions. Receipt6c9174c1/40artifactseald05c77cf,
  allhashesindependentlyverified. UIowns reservedactualEdgecheck, pending.
- BoundedactualHealthacceptancepassed: sameEdge1912/375 truthfulbanner and
  observedconservativewarnings, oldabsenceclaimabsent/nooverflow. FiveHTTP200,
  onepositiveunavailablegate. UIsevenartifactseal8f426843 independentlyverified;
  report/disposition/mobilevisualreview passed. SamebrowserrestoredIdentity/
  clientdisconnected/slotreleased. Separateacceptanceaddendum preserves release
  seal; no live-negativegate/provider/collectioncause/completeness claim.

## Active response-accuracy follow-up after r418

- Standing user-directed central integration and image-only rollout continues;
  MODIFY/AZCLI existing subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  Australia East, aiops-dev-rg and existing Container Apps/ACR only.
- Confirmed Incident partial-status defect fixed in three bounded paths;
  central161coupled and300API tests (overlapping suites), Ruff/diff and
  preserved1987frontend tests/lint passed. Full six-path PR419 merged.
- Existing Agents owner supplied exact-freeform alert routing correction
  against main8f689801; composed once with Incident owner input. No duplicate
  implementer. Final source2a4b109e affects API only; web remains r418.
- Preserve r418 immutable APIe7e2b17b/web a423d90d rollback digests; preserve
  API4CPU16Gi80Gi,4apps/6Jobs/7roles, all settings/identities/Foundrypins,
  groundingOFF, Network, workload profile bounds and retention0.
- No provisioning/Terraform/config/grants/pins/Job/publication mutation.
  Staged API0% -> qualified baseline parity/protected equality -> promote100%.
  Web only if source changes require it; otherwise retain proven r418 web.
- Zero-traffic superseded API retirement remains user-directed; retention0
  may prune record, rollback always creates a newly qualified revision.
- Gate exact-head CI/pathset, clean merged archive, immutable offline package
  qualification and protected snapshots, then actual same-Edge hinted/freeform
  and Incident partial tool/turn/citation acceptance. Full accuracy not assumed.
- Fresh release-specific validation proof follows; older release sections below
  are historical evidence, not current validation.

### All validation checks pass - response follow-up
- [x] Existing subscription/RG confirmed; no provisioning; inherited policies
  refreshed and API Docker linux/amd64 recipe check passed without warnings.
- [x] Fresh protected-before751e2786 matches release418 protected-after exactly.
- [x] Static role delta review: no infrastructure/newidentity/access-operation
  changes; existing scoped AcrPull/KeyVault/Foundry assignments preserved.
- [x] Six exact composed postimages verified; central499coupled backend tests,
  changedPythonRuff/diff and preserved1987webtests/lint passed.
- [x] Exact finalhead73c7c858CI, guarded merge and merged archive.
- [x] Fresh validation proof and official validate workflow complete.
- [x] Offline final API image qualification; web remains unchanged r418.

### Section 7: Validation Proof - response follow-up PR419
- 2026-10-27T03:27Z-03:42Z: existing subscription/RG AustraliaEast Succeeded;
  policy assignments refreshed; D4 current1/max3/min0, no capacity changes.
  `docker build --check --platform linux/amd64` API recipe passed.
- Central `uv run --no-sync pytest -q` nine coupled routing/incident/history/
  observability/status/API/policy suites:499passed. ChangedPythonRuff,
  compileall and diffcheck passed. Preserved `npm run lint:fix && npm test`:
  151files/1987tests passed. No frontend or build-recipe source delta.
- Static role review confirms no new identities, data operations or role/IaC
  changes; existing assignments preserved by snapshot parity gate.
- All8 finalhead73c7c858CI checks passed. Exacthead/base/sixpathset guarded
  merge produced canonical2a4b109e7394b9577d88511eec32274b1a75a330.
  Clean sourcearchiveSHA2569dbc3147a75870f6cb33dd3be5c73f98f04fa601569d1665150c01a100ef085d.
- Protected-before751e2786 matches release418 after exactly. No outstanding
  validation errors. ImmutableAPIoffline qualification and zero-traffic
  readiness/providerparity/protectedequality remain hard execution gates.
- ACR run cr2y succeeded from canonical archive; API digest
  sha256:9437343345e11ae85119ca1c777be1f30ebf9f50e8b4ae703ba366e0c10f2370.
  Offline500packagedfiles/source metadata/import qualification passed.
  Freshpreflight751e2786 equals before; explicit r418100% retained while
  staging r419-2a4b109e at0%. Promotion awaits readiness/parity/equality.
- Execution complete04:03Z: zero-trafficHealthy/1ready/0restarts/18baseline
  providers and protectedstaged parity passed; explicitr419100% verified.
  Guarded oldr4180%unlabelled then deactivated; no explicitdelete.
  Protectedafter796f4ac1 preserves all except APIimage/ready; webunchanged.
  Receipt0f9a7891/seal3da9b0aa,28artifacthashes independentlyverified.
  Reserved actualEdge acceptance handed to Agents; remains separate/pending.

## Active follow-up: F02, navigation and response correction coordinated release

- User explicitly reaffirmed standing merge/deploy authority with "why are you
  not merging and deploying?" on 2026-10-27. Carry both reviewed candidates
  through exact-head CI merge then one coordinated API/web release.
- MODIFY existing images only; recipe AZCLI. Existing confirmed target remains
  subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc, Australia East,
  aiops-dev-rg / aiops-dev-cae / aiopsdevacr7h0ih3.
- Include sealed F02 patch a1cce7c4 (14 paths), mobile navigation patch
  31102734 (2 paths), and Resource Health compatibility patch6ec0775c
  (2 paths), all based on exact current-main74bdd321. Complete composed
  response seal882a302a arrived before PR creation and is now accepted;
  it includes the same Incident postimages, applied only once. Exactly29paths.
- F02 records historical validation/persistence only; all stronger product
  qualification remains unknown. No cloud publication, Job, grant, pin,
  configuration, profile, schedule, SLO or Terraform mutation.
- Mobile fix excludes closed offscreen sidebar links from keyboard/accessibility
  order at <=820px, retaining desktop/open navigation and existing Escape.
- Preserve current r417 API digest b61277961b812e30ba16bd48321081637c487266006e1c005a2feed77e946b57
  and web digest b68516fd11f36803b9472454c75c7a1f438549f94f0fa223cfe9d64bf6379c55
  for rollback via newly staged/qualified revisions. Existing maxInactiveRevisions=0
  auto-prunes retired records; do not assume reactivation or change this setting.
- Preserve API4CPU/16Gi/80Gi, all settings/identities/roles,4apps/6Jobs,
  Foundry pins, grounding OFF, Network and workload profile bounds.
- Gate: source CI -> final-main clean archive -> immutable ACR images and offline
  source/asset qualification -> zero-traffic API baseline parity and protected
  equality -> explicit API promotion -> Single-mode web rollout -> served
  asset verification -> user-authorized retirement of zero-traffic API.
- Existing one retained Edge window/CDP9334 remains owned by UI/Agents;
  no competing live-browser launch. New deployed acceptance follows separately.
- Local source review complete; 286 coupled backend tests and1986 frontend tests,
  lint/types/build plus8 combined browser fixtures passed. Recovery cases are
  running before commit. No new deployment executed yet.
- Additional complete handoff admitted before merge: Resource Health wire fix,
  two nonoverlapping paths sealed6ec0775c. Independently fetched official
  2025-05-01 AvailabilityStatuses_List example confirming `occuredTime` and
  absent optional reportedTime. Central88 incident tests/Ruff passed. No live
  row attribution inferred. The previously incomplete observability input is
  superseded by complete parent composition882a302a, now reviewed and validated:
  partial status retained through tools/aggregation/frontend, missing-policy
  diagnostics separated, and unattempted narration no longer called unavailable.
  Central393 composed backend tests and1987 frontend tests/lint/types/build
  passed. PR418 exacthead13310a2d is pending full CI.

### All validation checks pass - active follow-up
- [x] Azure CLI authenticated in confirmed existing subscription; resource group
  Succeeded in Australia East, no resource/profile provisioning.
- [x] Read-only resource-group/inherited policy assignments refreshed.
- [x] Both Docker BuildKit recipe checks pass for linux/amd64; no build during check.
- [x] Fresh release418 protected-before hash
  604fc0ebe38f68776e7dc97c1d723b09f9deeb41ace820d26f14b37d76c5026a
  equals prior deployed release417 protected-after;4apps/6Jobs/7APIroles preserved.
- [x] Only r417 active100%; idle cleanup leaves existing D4 staging capacity,
  maximum remains3, no change to CPU/memory/profile.
- [x] No Bicep/IaC delta; provision/what-if/AZD environment creation inapplicable.
- [x] Exact final-head CI and final-main archive verified. Immutable package
  verification remains a hard execution gate before traffic promotion.
- [x] Static role review and fresh source/build proof complete.

### Role Assignment Verification - active follow-up
- Status: Verified for this image-only delta. Existing user-assigned application
  identity retains ACR-scoped AcrPull and existing Key Vault data-plane access.
  No infrastructure, identity or role assignment source is changed.
- F02 reuses the existing trusted-root OneLakeDocumentStore composition and
  existing publisher credentials; it does not provision access or prove remote
  producer/API root alignment. Resource Health reuses existing reader access.
- No new operation requires a new Azure grant. Existing seven API assignments
  are preserved by protected-state equality; actual post-rollout verification
  remains required. No provision/apply or speculative permission escalation.

### Section 7: Validation Proof - coordinated PR418 release
- 2026-10-27T02:43Z-02:51Z: confirmed existing subscription/RG, inherited
  policy assignments and D4 staging capacity; Docker linux/amd64 recipe checks
  passed. Fresh protected-before hash604fc0eb matches completed r417.
- Source checks: `uv run --no-sync pytest -q` selected F02 tests286,
  publication/exposure/ontology recovery110 and composed response/API393 passed;
  changed-file `uv run --no-sync ruff check` and `git diff --check` passed.
- `cd web && npm run lint:fix && npm test && npx tsc --noEmit && npm run build`
  passed after composition:151files/1987tests. Eight local Chromium navigation/
  Identity viewport fixtures previously passed; no CSS delta after that check.
- Static identity/role delta review passed; no IaC or new grants. Existing
  protected app identity and roles remain required for post-deployment parity.
- 2026-10-27T02:58Z: all8 exacthead13310a2d CI checks passed; guarded
  head/base/29path review and merge completed. Final main
  8f689801b3d88246ba295910d161700676964427 clean archive SHA256
  51c678773a6962dc650e7682e6d6d14348047400482debc553f7a88d86d984d9.
  No outstanding validation failures. Immutable package qualification,
  zero-traffic parity and protected equality remain mandatory execution gates.
- ACR final-main builds succeeded once each: APIcr2x digest
  sha256:e7e2b17bbbf774b6414ac99099f98f87f14e3081d9821b5cd0be9e666768d681;
  webcr2w digest
  sha256:a423d90dbef36540c6f7fad464b4e8abf5bb1f4e7c517be95621bc9ecc1ae151.
  Offline500 packaged API files match exact archive, source metadata/imports
  pass;70 packaged web assets and corrected narration/F02 tokens pass.
  Fresh protected-preflight equals before604fc0eb exactly.
  Zero-traffic API qualification in progress; r417 remains explicit100%.
- Final deployment: API r418-8f689801 zero-traffic qualification03:13:09Z,
  explicit100% promotion03:14:11Z; web r418-8f689801 Healthy100%03:15:31Z.
  Both1ready/0restarts,18baselineAPIproviders and all70servedassets retained.
  Protected-after751e2786 equals before except permitted image/readyrevision
  fields;4apps/6Jobs/7APIroles/API4CPU16Gi80Gi/profiles/settings preserved.
  Live role verification retained existing scoped AcrPull, Key Vault and
  Foundry assignments; no grants, provisioning or registry reconfiguration.
  User-directed unlabelled0%r417 retirement completed without explicit delete.
  Existing retention0 may prune record; rollback creates qualified revisions
  from retained r417 digests, never assumes reactivation.
  ReceiptSHA2569fbbf6a22e2467d150fafd21278de72c0c7c1becf5e6470f4b455be772d383f8;
  seal6236ab3b500bf6814586d203fb3138f41bf2f0d44804608adcf52aa671b2b6ed.
  Agents/UI/Fabric/Incident notified; actualsamewindowacceptance remains separate.

## Historical completed release: coordinated PR413-PR417

- Mode MODIFY; recipe AZCLI; image-only updates of existing aiops-dev-api
  and aiops-dev-web from one clean final-main archive.
- Canonical merged source: 74bdd321a5225d327bb50e923ea71a70d52e9f91.
  PR413 evidence readers and PR414 Gold discovery/product contracts remain
  included. PR415's benchmark isolation/import fix, PR416's Bash setup launcher,
  and PR417's Identity principal-table layout repair are also merged. PR415,
  PR416, and PR417 passed all exact-head CI gates; PR417 additionally passed
  1,979 web tests, lint, TypeScript, build, and four Chromium viewport fixtures.
  Source checks do not constitute fresh deployment validation.
- Proposed target: subscription 890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  ME-MngEnvMCAP448721-pangj-1, Australia East, aiops-dev-rg, aiops-dev-cae,
  ACR aiopsdevacr7h0ih3.
- Build one API and one web image. Qualify immutable images offline, stage
  API at zero traffic, verify revision health and existing baseline parity,
  then promote API and roll web only after checks pass. Verify served web
  assets against the packaged image.
- Preserve API r410 immutable digest
  sha256:d83ff058ed57d21fea12f0365277549e0ff63930442ca2b4eccec881b0158818
  for rollback. Preserve web r412 digest
  sha256:48a6db1aa256250df00a24a67e3b14f19e9b872a7b02376b591140cbe3aae6ae
  for rollback. Preserve API 4 CPU / 16 GiB / 80 GiB ephemeral,
  identities, roles, environment settings, Jobs, profiles and Network.
- No Terraform apply, provisioning, credential changes, grants, provider
  registration, policy provisioning, Fabric publication, Job execution,
  schedule/SLO changes, or Foundry pin/identity changes.
- User explicitly directed "why deployment is blocked? unblock it and deploy"
  after the proposed bounded r404 retirement was presented. Deployment may
  reversibly deactivate unlabelled zero-traffic revisions. The subsequent
  explicit direction "remove the slots that's 0%" includes both r404 and
  r408. Both are now inactive, not deleted, while r410 remains healthy at
  100%. No capacity increase or protected configuration change is authorized.
- Diagnostics/history become read-capable using existing connection identities;
  missing policy/permissions remain unavailable or partial, never healthy.
  Authenticated provider completeness and Foundry synthesis are not deployment
  acceptance claims.
- PR417 changes only Identity table presentation and coverage; its source and
  local-browser results are not deployed Edge acceptance.
- User's original release direction explicitly requested every completed,
  validated change be merged and deployed once as one coordinated release.
  Subsequent source merges did not authorize grants, policy writes, publication,
  Jobs, provider registration, or profile changes.
- Fresh validation, immutable image build, zero-traffic API qualification,
  explicit API promotion and web rollout completed. D4 maximum remains three;
  all zero-traffic API revisions (r404, r408, and newly superseded r410) are
  deactivated. Azure subsequently pruned their inactive records under the
  existing unchanged maxInactiveRevisions=0 policy. Only r417 remains active
  and serves 100%; immutable rollback images remain in ACR.
- Gold/F01 are included as source declarations only, not physical tables,
  publication, operational ownership, or consumer readiness proof.
- Fresh validation proof is recorded below. Historical K01 proof is not used
  as current release validation.

### Coordinated release execution checklist
- [x] Canonical source merged through exact-head/path/CI guards.
- [x] Scope and rollback plan recorded.
- [x] Existing target and coordinated API/web scope confirmed by original
  explicit release direction; no infrastructure or configuration changes.
- [x] Inspect current context, app health, roles and protected state.
- [x] Resolve staging path: user-authorized r404/r408 deactivation completed;
  r410 remains healthy at 100%; health/ready HTTP 200.
- [x] Complete azure-validate with fresh proof.
- [x] Build and qualify immutable API and web images.
- [x] Stage and qualify API, promote, then roll web and verify served assets.
- [x] Verify protected-state equality and seal release receipt.

### Coordinated release result
- Source `74bdd321a5225d327bb50e923ea71a70d52e9f91` is deployed to API and
  web revisions `aiops-dev-api--r417-74bdd321` and
  `aiops-dev-web--r417-74bdd321`, both Healthy at 100%, one ready replica each
  with zero restarts. API staged qualification completed 2026-10-27T02:07:46Z,
  promotion qualification 02:08:29Z, web qualification 02:09:44Z.
- API digest
  `sha256:b61277961b812e30ba16bd48321081637c487266006e1c005a2feed77e946b57`;
  web digest
  `sha256:b68516fd11f36803b9472454c75c7a1f438549f94f0fa223cfe9d64bf6379c55`.
- Public API health/ready returned 200; all 18 baseline-ready providers remain
  ready. Web runtime configuration targets the existing public API; all 70
  served JS/CSS assets exactly match the immutable packaged image.
- Protected state comparison permits only image/ready-revision changes:
  all 4 apps, 6 Jobs, 7 API roles, settings, identities and profiles preserved.
  API remains 4 CPU / 16Gi / 80Gi ephemeral. Before SHA-256
  `f757c3728601144c02aa885f072c92f38b94174af191e27645301d831abf78b0`;
  after `604fc0ebe38f68776e7dc97c1d723b09f9deeb41ace820d26f14b37d76c5026a`.
- Receipt: session `files/release417/receipt.json`, SHA-256
  `add6e142ad249794b16fe6a8cdece5873600a2200b8dfec2c999b3de7841350c`;
  adjacent `SHA256SUMS.json` seals build logs and bounded qualification proof.
- Rollback correction: final read showed maxInactiveRevisions=0, an existing
  unchanged setting. Azure automatically pruned inactive r404/r408/r410 records;
  no explicit delete was issued. Reactivation is therefore unavailable.
  The r410 immutable digest was independently verified still present in ACR:
  rollback requires staging a new revision from that digest, qualifying it,
  then explicitly promoting it. Prior web r412 digest remains available.
  `release417/retention-addendum.json` supersedes the original receipt's
  reactivation assumption; the original sealed receipt is preserved.
  Lesson: inspect inactive-retention policy before assuming deactivation
  preserves a reactivatable revision. No infrastructure provisioning,
  grant/pin/config changes, Job execution or publication occurred.
- Limits remain explicit: actual authenticated Identity Edge/table acceptance,
  Foundry tool isolation/grounded synthesis and provider completeness are not
  claimed by this bounded deployment check. F02 and the pending mobile
  Tab-order source candidate are not included.

### All validation checks - coordinated PR413-PR417 release
- [x] Azure CLI installed/authenticated; selected subscription ID and name
  match the existing target.
- [x] Existing API/web Container Apps and environment are Succeeded/Running;
  API `/health` and `/ready`, and web `/api/config`, returned HTTP 200.
- [x] API r410 has 100% traffic, 4 CPU/16 GiB/80 GiB and exact r410 digest;
  web r412 has 100% traffic and exact r412 digest.
- [x] Docker BuildKit `buildx build --check` passed for API and web Dockerfiles;
  no image was built during validation.
- [x] No Bicep `infra/main.bicep` exists and no infrastructure, role, or
  configuration paths differ from merged main; no IaC deployment/what-if is
  applicable to this existing-image update.
- [x] Runtime role assignments read and unchanged (7); protected-state
  snapshot matches the prior r412 post-deployment baseline exactly, including
  6 Jobs, 4 apps, roles, profile configuration and protected settings.
- [x] Existing subscription policies were inspected read-only; no new
  resources, policy targets, or configuration are proposed.
- [x] Full Python suite passed after isolating the deterministic 100k
  benchmark test in a subprocess: 9,149 passed, 1 skipped in 1,894.10 seconds.
  The prior failure came from process-wide `ru_maxrss` retaining a higher peak
  from earlier tests, not from the benchmark. The local deterministic
  benchmark remains distinct from the qualified production 100k Phase 4
  entry gate; it does not qualify or replace that gate.
- [x] PR415's final Linux RSS sampling fix passed the complete backend CI
  matrix. PR416's launcher and PR417's Identity repair each passed all exact
  head CI checks; PR417 frontend CI passed all 1,979 tests, lint and build.
- [x] Container Apps staging capacity path is available on the current profile.
  At `2026-10-27T01:48:36Z`, the read-only workload-profile response showed
  `api-d4` currentCount 3 / maximumCount 3 / minimumCount 0. The API revision
  query showed r404 and r408 active at 0% and r410 active at 100%; all have one
  replica, consistent with the three occupied D4 nodes. API is on this profile
  and requires 4 CPU/16 GiB. The last quota query reported Microsoft.Quota
  unavailable because the provider is not registered; it was not retried.
  Provider registration/profile changes remain out of scope. The subsequent
  explicit user unblock/deploy and zero-traffic retirement instructions
  authorized r404/r408 deactivation, completed at 2026-10-27T01:59:35Z.
  These revisions are inactive with zero traffic; no revisions were deleted.
- Fresh release417 validation: exact source archived at
  `74bdd321a5225d327bb50e923ea71a70d52e9f91`; both Dockerfile build checks
  passed without warnings; target resource group Succeeded in Australia East;
  policy assignments refreshed read-only; runtime AcrPull and six other roles
  present. Protected-before SHA-256
  `f757c3728601144c02aa885f072c92f38b94174af191e27645301d831abf78b0`
  exactly matches the retained baseline. No IaC change, provisioning or what-if
  applies to this existing-image-only deployment. API health/ready and web
  configuration endpoints returned 200. Exact-head PR417 CI is fully green.

### Section 7: Validation Proof - coordinated PR413-PR417 release
- Source: `74bdd321a5225d327bb50e923ea71a70d52e9f91`. PR415 merge commit
  `78dc6b7d23110221c60d9714e89843485023be35` and PR417 merge commit
  `74bdd321a5225d327bb50e923ea71a70d52e9f91` are in main; PR416 setup merge
  `af92c7992f429bb0ee7c4a6e11569841bc063244` is also included. The two
  `.azure` artifacts in this worktree remain uncommitted release-preparation
  evidence.
- Azure CLI account: `az account show --query '{name:name,id:id}' -o json`
  confirmed `ME-MngEnvMCAP448721-pangj-1`,
  `890c9bfc-d09c-4143-9ce5-465e75e3eecc`.
- Read-only Container Apps checks: API r410 and web r412 are Succeeded and
  Running; API `/health`=200 and `/ready`=200; web `/api/config`=200.
- Protected baseline: `release-current/protected-before.json`, SHA-256
  `f757c3728601144c02aa885f072c92f38b94174af191e27645301d831abf78b0`;
  exact match with r412's protected-after state. Snapshot covers 4 apps,
  6 Jobs, 7 API managed-identity roles, profiles and protected settings.
- `az containerapp env workload-profile list`: API profile `api-d4` maximum
  remains three. Both idle API revisions were deactivated after checking
  explicit traffic and no labels; `revision list --all` confirms both
  inactive, r410 active at 100%, and its replica ready with zero restarts.
  Retirement receipt: `release417/idle-retirement.json`.
- `az quota list` and `az quota usage list` for Microsoft.App/Australia East
  returned `MissingRegistrationForResourceProvider` for Microsoft.Quota.
  Registration was deliberately not performed because it is an out-of-scope
  provider mutation. Resource-group policy assignment list returned zero;
  existing subscription policy assignments were read only.
- `docker buildx build --check --platform linux/amd64 -f Dockerfile .` and the
  equivalent web Dockerfile check both passed with no warnings. No image build
  or ACR write was performed.
- Source CI: PR413/PR414 history and PR415-PR417 exact-head checks passed.
  PR415's corrected benchmark passed the full backend CI matrix; PR417 passed
  frontend CI, including all 1,979 tests, lint and production build. The local
  Identity browser fixtures passed at 375, 820, 821 and 1912 px. None of these
  results reuses the historical production baseline as current deployment
  proof.
- Build proof at 2026-10-27T02:05Z: ACR native linux/amd64 API build cr2t
  succeeded, source metadata is exact main
  `74bdd321a5225d327bb50e923ea71a70d52e9f91`, digest
  `sha256:b61277961b812e30ba16bd48321081637c487266006e1c005a2feed77e946b57`.
  Offline credential-free/network-disabled check matched all 499 packaged
  source/config/manifest files and imported API/history runtime successfully.
- Web build cr2v succeeded, digest
  `sha256:b68516fd11f36803b9472454c75c7a1f438549f94f0fa223cfe9d64bf6379c55`;
  packaged qualification sealed hashes of all 70 JS/CSS assets. Earlier failed
  attempts produced no image: cr2s resolved the root Dockerfile instead of the
  web recipe; cr2u encountered npm ECONNRESET. Correct absolute Dockerfile path
  and retry of unchanged source resolved these failures. Preserve all logs.
  Lesson: ACR resolves a relative --file from invocation cwd, not context root;
  always pass the exact archived Dockerfile's absolute path.
- Final main CI run 40434431331 completed successfully: all four backend shards,
  backend, frontend and security-scan green.
- Static Role Assignment Verification: existing apps identity remains used for
  registry-scoped AcrPull, vault-scoped Secrets Officer (connection writes),
  project-scoped Foundry consumer/runtime and existing custom prompt/response
  roles. No generated infrastructure or RBAC delta is proposed; no new grant
  is required or permitted in this release.
- Decision: validation checks passed and authorized capacity remediation is
  complete; finish azure-validate workflow before API staging. Require healthy
  zero-traffic API qualification and protected-state equality before promotion.

## Historical preparation: K01 mobile navigation

- Mode MODIFY, recipe AZCLI; PR412 head
  72015a00ad62a66c1d357e51f63a427ee0cb3988 based on
  f8806e220ad20e4bf2548cc9ae38ed54cf7f3d5a. Guarded merge completed:
  fe7fbee62ae741cd99e9b277be9cc5bf1ab6a938 at 2026-10-26T15:53:16Z.
- Exactly two web paths: AppShell.tsx and AppShell.test.tsx. No CSS,
  routing, backend, infrastructure, policy or runtime configuration changes.
- Central lint, 1976 tests in 150 files, TypeScript and production build pass.
  All eight exact-head CI checks and guarded merge passed.
- Proposed next coordinated web-only image release to existing subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc, Australia East, aiops-dev-rg,
  aiops-dev-cae and ACR aiopsdevacr7h0ih3.
- Preserve web r411 digest
  sha256:08849b2b58e015384f5e4a01823ae9aeba1e24011334bc9a344a19a35e212fc9
  as rollback; preserve API r410 digest
  sha256:d83ff058ed57d21fea12f0365277549e0ff63930442ca2b4eccec881b0158818,
  its 4 CPU/16 GiB sizing, and all identities, roles, jobs and settings.
- Approval, current-context/capacity/protected-state verification,
  azure-validate and azure-deploy are required before image build/rollout.
  An unavailable confirmation is not approval. No live acceptance rerun
  until the new immutable identity is supplied.
- User explicitly approved the existing-target web-only deployment with
  "just deploy it" at 2026-10-26T23:55:15+08:00. Prior unavailable prompts
  are superseded by this direct approval. Preparation is ready for validation.
- No new credentials, grants, provider registration, Job starts, publication,
  diagnostic acquisition, schedule or SLO changes.
- Gold declaration and observability follow-up candidates are NOT included.
- Historical records below are not current validation or approval evidence.

### K01 validation checklist
- [x] All validation checks pass
  - [x] Core AZCLI authentication and target verification; image-only change
    has no IaC template deployment, so Bicep build/validate/what-if is not
    applicable and no historical template will be applied.
  - [x] Docker context/lockfile and existing production build verified.
  - [x] Subscription/resource policy assignments inspected.
  - [x] Static identity/role requirements unchanged by two UI-only paths.
  - [x] Protected API/web/jobs/roles/profile baseline retained.
- [x] Immutable final-main web image build and offline qualification.
- [x] Web-only rollout and served-asset/protected-state verification.

### K01 deployment result
- ACR build cr2r from fe7fbee62ae741cd99e9b277be9cc5bf1ab6a938 completed.
- Web r412-fe7fbee6 Healthy/Running at 100%, immutable digest
  sha256:48a6db1aa256250df00a24a67e3b14f19e9b872a7b02376b591140cbe3aae6ae.
- All 70 packaged JS/CSS assets match served hashes; offline K01 tokens present.
- Protected-state equality passes except web image/ready revision; API,
  identities, roles, jobs and profiles unchanged. Web r411 rollback retained.
- Actual keyboard acceptance handed to UI against this new identity.

### Section 7: K01 validation proof
- Current source: fetched origin/main fe7fbee62ae741cd99e9b277be9cc5bf1ab6a938;
  exact delta from r411 is AppShell.tsx and AppShell.test.tsx only.
- npm run lint:fix; npm test (150 files, 1976 tests); npx tsc --noEmit;
  npm run build all passed centrally. All eight exact-head CI checks passed.
- Docker server 29.9.2 available; web Dockerfile and npm ci lockfile verified.
- az account show confirms approved subscription; current serving web r411
  is Healthy, no competing K01 rollout observed.
- Infra, Dockerfile and package-lock unchanged: static RBAC/identity requirements
  unchanged. No IaC deployment or new role/data operation is proposed.
- Subscription policy assignments inspected: SQL/relational database and
  data-protection initiatives; no new resources or settings affected.
- Protected baseline captured in release412/protected-before.json,
  SHA256 e7108890cd3a7de86529c1148194c9581181f37ec8a56c1f4d3ac0f99c5d0f1c.
- Existing-only image update needs no quota allocation or profile change.
  Immutable image build/qualification and post-rollout checks follow in
  azure-deploy; validation does not claim those checks already passed.

## Historical preparation: PR409 scoped observability evaluator and ARG reader

- Mode MODIFY, recipe AZCLI; source merge ae34a2974b8ef62f7a5a5769b667836188225562.
- Source owner accepted exact head 3e0e416c; all eight CI gates passed before
  guarded merge. Central focused backend and complete frontend validation passed.
- Existing subscription 890c9bfc-d09c-4143-9ce5-465e75e3eecc, Australia East,
  aiops-dev-rg, aiops-dev-cae, ACR aiopsdevacr7h0ih3.
- Proposed image-only coordinated API/web update from one canonical main archive.
  Preserve current API/web r408 images as rollback and all settings, resources,
  identities, roles, jobs, workload profiles and Network behavior.
- Runtime reader performs existing governed ARG reads only when the alert
  scenario is invoked. Diagnostics/logging policy remain unavailable; alert
  configuration is at most partial, never delivery or live-coverage proof.
- No provider registration, new credentials, grants, Job execution, publication,
  lifecycle enablement or diagnostic-settings acquisition.
- Pending: context/plan confirmation, current protected-state and capacity
  checks, canonical archive, validation proof, immutable image qualification,
  zero-traffic API staging, promotion, web update and bounded owner acceptance.
- Prior r408 records below are historical and do not validate this deployment.

## Active preparation: PR407 timestamp abstention and C05-C09 UI sizing

- Mode MODIFY, recipe AZCLI. Existing API/web image-only coordinated update;
  no new infrastructure, grants, identity, provider registration or networking.
- Source407 head46d030eb, three sealed paths, owner source-byte accepted.
  UI bounded candidate uses shared40/44px token only for Changes filters,
  Compliance non-checkbox controls/domain, workspace identity/title,
  Remediation search and exposure source retry. No action/persistence changes.
- Target remains subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  aiops-dev-rg/Australia East/aiops-dev-cae/aiopsdevacr7h0ih3.
- Preserve API404/19ed8a98 and web406/876c9b67 as rollback; API4CPU16GiB/
  80Gi/min1max1, web0.5CPU1GiB/min1max3; identity/roles/jobs/profiles/settings.
- Plan: exact source review and CI/guarded merges, canonical final-main archive,
  one API plus one web production build, exact-source offline image checks,
  API zero-traffic staging then bounded promotion, web digest update, protected
  equality and finite served-byte checks. UI owner receives exact deployed
  identity for retained normal-session acceptance, not duplicate404/406 checks.
- No native/publication/provider-completeness gate or runtime flag changes.
  Invalid source times must explicitly abstain; six full valid projections
  remain byte-equivalent. Broader audit limits remain explicit.
- Section7 new validation proof: pending final merged source and current
  protected-state/quota/policy/role/readiness checks. Historical proof below
  belongs only to prior releases, not this release.
- Preparation complete: PR407 mergeda6c50db8 with8CI; UI408 candidate
  9a99992e096ea4ac4a568dde4cadd0819f07bdfb exact4paths independently
  canonical byte reviewed, CI/guarded final-main merge pending.
  Central198coupled Python/Ruff,27Chromium geometry/shared fixture cases,
  frontend149files1964tests/lint/types/productionbuild PASS.
- Read-only current context confirmed actual established subscription/region.
  Prompt returned user unavailable/autonomous; continue existing-target
  coordinated release under standing user direction, no new infrastructure.
  API remains4CPU16GiB80Gi/min1max1;18ready providers. Sevenroles/sixjobs/
  allapps/profiles captured in protected-before e77048b5.
  Supported environment usage shows12/500generalpurpose,1.5/500consumption;
  unchanged api-d4 profile cap3. ThreeactiveAPI revisions399/401/404;
  only399 is0traffic/unlabelled and may be reversibly retired for staging,
  preserving404serving and401rollback. Capacity prompt returned autonomous;
  no delete, capacity increase or settings change.
- Quota CLI failed Microsoft.Quota unregistered, preserved in quota-cli-error;
  no provider registration. Supported Microsoft.App environment usages used
  instead. Subscription policies3 relate SQL/database/dataprotection;
  RG-level query0 not mistaken for absent inherited subscription policies.
- /health/ready was an invalid read-only endpoint404; corrected /health
  ready18providers captured; actual readiness probe is /ready. No runtime
  failure attributed to this audit path error.
- Validation must wait for408all8actualCI/guardedmerge, then immutable source
  archive and one build per image. No IaC/Dockerfile/lock/permissions changes;
  infrastructure compilation/what-if N/A for image-only rollout.
- All validation checks pass (current408):
  - [x] 1. Core Validation (CLI, auth, target, capacity); build/validate/what-if
    of Bicep N/A because no Bicep or infrastructure deployment is included.
  - [x] 2. Docker Build (one production image per affected app from final main);
    exact-source/API16cases and all packaged web assets inspected offline.
  - [x] 3. Azure Policy Validation; current inherited subscription assignments
    reviewed, no proposed resource type/location/config/identity/scale changes.
- Section7 Validation Proof (408,2026-10-26): workflow LoadPlan,
  AddValidationSteps, RunValidation, BuildVerification, StaticRoleVerification
  executed sequentially. CLI/account/RG/currentapp/protectedstate checked;
  no IaC generation/apply, so Bicep compile/validate/what-if not applicable.
  Static container_apps.tf identity/registry paths unchanged; no new service
  operations or role needs. Existing credential registry path retained.
- Both8CI/source-owner guards passed before finalmain5d03ee9bef5d098928e516cb4b43de140e805367.
  `git archive origin/main` isolated all dirty deployment records.
  `az acr build` once each: APIcr2m3m56s/webcr2k4m25s SUCCESS; production
  Entra Docker defaults retained; no local envfiles in canonicalarchive.
  API sha256:cac58cffb93d0a1ddec2f229f4a90b45387c2d260df4aefc5e25a67b9d61eb49;
  web sha256:65aef1ec7016cd28a0de802e61847aa43013b631bb63228c3f07149962173922.
  Digests resolved from registry then pulled immutably.
- `qualify_api.py` runs pull-never/network-none/read-only/cap-dropALL:
  all473srcfiles exactcanonicalbytes/buildmetadata exactmerge;
 16public cases PASS including10invalidsourceabstentions/6validcontrols.
  `qualify_web.py packaged` same isolation:70JS/CSS hashes captured,
  shared40/44tokens/selectors retained; CSSdbce33c06a456d48b6af0ce8569613f6bf440e8702d91db0ae6c22a479c1a556.
  Native-arm host emulates immutableamd64images, warning retained, exit0.
  All current validation checks PASS; deployment not yet executed.
- Deployment completed under azure-deploy after workflow UpdateStatus:
  API/web bothr408-5d03ee9b Healthy100%1ready0restart; API18readyproviders.
  Only unused0traffic/unlabelled399 reversibly deactivated;404/401 retained.
  InitialHealthyAPI inventory/readport stillloading failed parity; preserved
  initialhealth, finitepassivewait reached all18before0%staging qualification/
  promotion. No gate weakened or source/config change.
  Stagedprotected36267b0c and finalprotectedc5d50709 assert unchanged settings/
  identities/7roles/6jobs/profiles/otherapps; explicitAPItraffic checked apart.
  All70publicJS/CSS match immutablewebimage. Receipt8d91705e seals42artifacts.
  ActualUI C05-C09 acceptance and Fabricreceipt review requested with exact
  newidentity; pending. Prior402/406 closed. No duplicatebuild/deploy.
- Final current disposition: Fabric API407 exact-image/deployment accepted.
  UI408 actual BLOCKED_AUTH,0states; genuineMicrosoftPickanaccount requires
  intendeduserchoice. Sixartifactseal c0b6b3e4 verified; no identity choice,
  credentials/MFA/storage/tokenchanges. User unavailable,helperstopped.
  Source/image/served-byte qualification does not override actualUIgate.
  Completion withheld; no retryloop or duplicate rollout.

## Active preparation: PR406 bounded drawer/form web-only repair

- Mode MODIFY; recipe AZCLI. Existing Next.js Container App image-only update;
  no generated infrastructure, resource provisioning or permission changes.
- Candidate ecc6f17ea12c8a381910e3b9a24a6387d119a0fc; base a42d964c.
  Five paths only; actual C02/C03/C04 fixes body portal, shared AI starter
  buttons and shared responsive form controls. Final merged source5c028620.
- Existing target subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  aiops-dev-rg/Australia East/aiops-dev-cae/aiopsdevacr7h0ih3.
- Preserve API404/19ed8a98, 4CPU16GiB/min1max1, traffic and replicas.
  Preserve web404/80dcce7a as rollback; web0.5CPU1GiB/min1max3.
  Protect all identities/settings/roles/jobs/profiles/other applications.
- Plan: exact-head CI/source review/guarded merge, immutable merged archive,
  one production-Entra web build, offline packaged-byte/provenance qualification,
  web-only digest update, healthy100%/served-byte/protected-state checks,
  bounded actual UI recheck in retained login. No API rebuild or mutation.
- Central149files1964tests/lint/build/strictTypes PASS. Two local Chromium
  real-layout cases375/1912 PASS,1080px settled viewport drawer,40/44px inputs,
  brand-white starters, focus/close/Escape/widen/mobile resize; no scenario
  submission. Fixture evidence is not deployed authenticated acceptance.
- Section7 validation proof (PR406, 2026-10-26T09:49Z):
  `az account show`, actual target show, protected snapshot and supported
  environment usage PASS (consumption1.5/500cores; no dedicated-profile change).
  CLI quota read registration error preserved; no provider registration.
  Three inherited policies concern Defender SQL/database/data protection;
  no web image-policy conflict. `git diff` proves infrastructure/Docker/locks
  unchanged; Bicep/ARM compile/validate/what-if N/A, no IaC deployment.
  Canonical merge5c028620 archive only, ACR cr2j SUCCESS, one web build with
  production Entra defaults; no API build. Digest
  sha256:876c9b674ca1dc373d3bdada0ac6d7e79d1a41a244f043295ef6b166a23487ac.
  Offline pull-never/network-none/read-only/cap-drop-ALL inspection PASS,
 70packaged JS/CSS hashes and scenario/form/AI/portal markers; image CSS
  e8503d7b shared40/44px and C01 retained. Initial unsupported --label
  rejected locally before any ACR submission; error preserved.
  Central1964webtests/lint/types/build and2real fixture layout cases PASS.
  Baseline API404ready18providers,7roles/6jobs protected. No validation errors.
- All validation checks pass:
  - [x] Core CLI/auth/target/headroom checks; no Bicep/ARM apply or what-if
    applies to this image-only change. Infrastructure and Docker/locks unchanged.
  - [x] Production Docker build from canonical merged archive; offline packaging.
  - [x] Inherited Azure policy read; unchanged existing resource type/location/
    identity/network/scale. No new policy-relevant resource properties.
- Static role/identity verification: exact Terraform and runtime configuration
  unchanged; existing registry-credential pull path, no new MI AcrPull path.
  Protected roles/identities captured for postdeploy equality.
- PR406 all8CI SUCCESS and independent bounded owner source review PASS;
  guarded merge5c02862016d1b78a2595969d2cbd6286bdadc8d3 canonical archive.
- Context/plan prompt returned user unavailable/autonomous; reuse established
  target under standing user-directed release authority. No new resources.
- Read-only preparation confirmed actual subscription and Australia East,
  web404 baseline and unchanged scale. Protected-before61a5cb7f captured.
  CLI-first quota read failed Microsoft.Quota registration; no registration
  mutation performed. Supported Microsoft.App environment usage, policies and
  API baseline health captured and inspected during actual validation.
- Actual validation workflow completed before azure-deploy. Deployed only web
  r406-5c028620/876c9b67, Healthy100%,1ready0restart. All70public served JS/CSS
  hashes equal immutable image. Protected after42978f41 proves only web image/
  ready revision differs; API404/18baseline-ready providers unchanged,7roles/
  6jobs/profiles/config unchanged. Receipt a9cbc51c73d49d84e8c73d7629cd99093fecfd59d78994d338e3390c51abec3d.
  Bounded actual retained-login UI recheck requested; not yet accepted.

## Active preparation: PR404 Package C API plus web

- Mode MODIFY; recipe AZCLI; existing API and Next.js Container Apps,
  image-only updates. No infrastructure generation/provisioning.
- Candidate724a7ee3fa84b57feb1aba7b91f776f9e8116ff5, basecc9c3af6;
  exactly14paths including bounded UTC-overflow correction. Canonical source
  owner review and exact-head CI/merge pending. Build only final merged archive.
- Existing subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  aiops-dev-rg/Australia East/aiops-dev-cae/aiopsdevacr7h0ih3.
- Preserve API401/cdbcc80c at100% while staging; API4CPU16GiB/80Gi,
  min1max1, api-d4 cap unchanged. Three current active replicas fill3/3 slots:
  r398/r399 zero traffic and unlabelled; retire ONLY oldest unused r398
  reversibly if approved, retain serving401 and399 rollback.
- Preserve web28/5e5999ab as rollback,0.5CPU1GiB/min1max3/auth/API base.
  Protect roles/identity/settings/grants/pins/jobs/profiles/otherapps.
- Plan: one API and one web build from identical immutable merged main,
  offline exact-source/package deterministic contract qualification, API0%
  staging/readiness/provider-baseline parity, promotion and web image update,
  protected-state checks and sealed receipts. No repeated401/402 acceptance.
- Central311coupledPython/Ruff and149files1962web/lint/build/types PASS.
  Production image build uses normal Entra defaults, never fixture auth.
- Deterministic evidence-only scenarios; Foundry narration not invoked.
  Historical health/activity unavailable, alerts partial, dependency depth1/
  max10 independently authorized neighbors. No LLM RCA/native/lifecycle/
  provider-completeness acceptance. Actual browser may be authentication-blocked;
  do not bypass normal sign-in or infer acceptance from offline tests.
- Section7 validation proof (PR404, 2026-10-26T08:48Z):
  `az account show`, protected snapshot, supported environment usage,
  inherited policy read and baseline health PASS; unchanged production Docker/
  dependency locks/Terraform source diff PASS. Registry credential auth and
  existing static role/identity relationships unchanged; no provisioning.
  Canonical merged archive06eb1e9f only: APIcr2h successful3m53s, digest
  sha256:19ed8a988c0692d4cdec55bfedf74d38fd29c888eeab5cdcaba7bba955ede07e;
  webcr2g successful4m9s, digest
  sha256:80dcce7ae6512684e5e91ed7b6a082f7472a6e86070f05d49f3edd768fd54b7e.
  One build each. Immutable API pull-never/network-none/read-only/cap-drop-ALL
  qualification PASS: all473canonical source hashes, exact metadata,
  ten public scenario fixtures, three invalid/two valid timezone controls.
  Web immutable packaging PASS: scenario code strings, compiled CSS/token
  retained; production Entra defaults. Artifacts in session files/release404.
  No unresolved validation errors. Bicep/ARM checks N/A, no infrastructure apply.
- Exact14canonical postimages source-owner PASS, all8CI run40292569433 PASS;
  guarded merge06eb1e9feea690859f5d1b261ec11e6f946bf181 at
  2026-10-26T08:41:21Z. Canonical merged archive captured for both builds.
- Context/plan prompt returned unavailable/autonomous; existing target and
  bounded reversible unused398 retirement selected under standing user-directed
  release authority. No node cap/resource/config expansion.
- Baseline protected-before1fd77677, supported environment usage/policy/health
  captured. Actual api-d4 current3/max3 confirmed. Production Dockerfiles,
  dependency locks and Terraform unchanged. No new generated artifacts.
- Validation steps: core CLI/auth/target/capacity and policy checks; Bicep/ARM
  compile/validate/what-if N/A (no IaC apply). Build API/web once, exact canonical
  image source/provenance/public fixture checks and packaged web evidence,
  unchanged static identity/config/roles proof, complete validation workflow.
- Actual prepare/validate workflow completed; azure-deploy invoked after proof.
  Only unused zero-traffic unlabelled398 deactivated. API404 Healthy0% staging
  preserved401100%,18baseline-ready providers/1ready0restart and protected state.
  Promoted404100%, updated matching web404 image once. Both Healthy100%,
  1ready0restart, root/config200, public health ready; served CSS matches image.
  API401/web28 rollback preserved; no sizing/settings/roles/grants/profile change.
- Release404receipt SHAcaeb5b028a02ec0e7f522ded35edacf3aa051cec175f7839f55f4ac34a0a73a1
  seals37artifacts. Owner independent source/hash evidence PASS, no independent
  Docker/web-byte recomputation. Exact-image HTTP/API-route and authenticated
  scenario UI/live-provider acceptance explicitly deferred, not closed.
  Retained browser normal sign-in BLOCKED_AUTH; no bypass/retry requested.
  This is bounded source-to-deployment delivery, not full scenario acceptance.
- Additive post-release exact-image HTTP proof now PASS12cases against unchanged
  deployed19ed8a98 code: six overflow400/no-read cases, six canonical/compatibility
  owner/scenario200/citation/retained-ledger cases plus mismatch/foreign-owner
  rejection. Read-only/no-network immutable image; mounted test runner/fixtures
  and ephemeral fixture cache only. Receipt exact-image-http-receipt.json
  SHA5fcbea87365f43a26ad0024924b5200ded9ed4136422b1d8bbbea03afd955eaf.
  Original deployment receipt/seals unchanged.
- Authentication status corrected: same retained Edge normal redirect reached
  actual Home with no credentials/account action; prior timeout did not prove
  persistent auth loss. UI finite actual scenario/static checks resumed with
  existing session; acceptance results pending, no fresh sign-in requested.

## Active preparation: PR402 C01 web-only control-height repair

- Mode MODIFY; recipe AZCLI; no new infrastructure. Existing Next.js
  `aiops-dev-web` image-only update, single revision mode.
- Source e7854c8340c00888d1cd68b7884c4df77f2c652a, two paths only; final merge
  identity pending CI. Owner canonical bytes accepted. Central lint/1,955
  unit tests/build/types/16 isolated Edge fixture cases passed.
- Target unchanged: subscription `890c9bfc-d09c-4143-9ce5-465e75e3eecc`,
  `aiops-dev-rg`, Australia East, registry `aiopsdevacr7h0ih3`.
- Preserve current web27/d9b9867d as rollback. API401/cdbcc80c, 4CPU16GiB,
  all settings/roles/identities/grants/pins/jobs/other apps remain unchanged.
- Build once from immutable final merged source, running ACR from the
  archive's web directory with `--file Dockerfile .`; never reuse fixture
  build or root/API Dockerfile.
- Validate image/provenance and deployed served CSS token; update web digest
  only; verify health/resources/config/unrelated state. Give UI exact receipt
  for its exclusive bounded actual runner; do not bypass live authentication.
- No scripts/provider/cloud expansion; Setup docs and package C excluded.
- Section 7 validation proof (PR402, 2026-10-26T08:18Z):
  core CLI/auth/target/protected snapshot and supported capacity PASS;
  inherited policies empty. No Bicep/ARM changes or apply (not applicable).
  `git diff bd1ccbde 0583863f --exit-code --` Docker/lock/Terraform/API
  config/identity source PASS unchanged. Existing registry credential auth
  retained; no provisioning or RBAC changes.
  One `az acr build`, from canonical merge archive web directory,
  `--file Dockerfile .`, run cr2f successful after 4m9s, digest
  `sha256:5e5999ab28e712c2086ef72327e661079ce1258b863f939a389c9571375e6958`.
  Immutable image extracted offline with network none/read-only/cap-drop ALL:
  packaged CSS uses shared token, desktop40/mobile44, disabled style retained.
  Production Dockerfile/default Entra build arguments used (not fixture auth).
  Logs/source/image qualification retained under session files/release402.
  Historical401 proof does not substitute for these web402 checks.
- PR402 merged `0583863fcbfb05333c45f736e15b5eb4dcc0ded9` at
  `2026-10-26T08:11:25Z`, all8CI gates passed. Immutable merged archive captured
  before Setup documentation commit; no uncommitted/workspace inputs.
- Context/plan prompt returned unavailable/autonomous; existing target reused
  under standing release direction. Supported environment quotas captured;
  no dedicated-profile change/new resources. Inherited policy assignments empty.
- Baseline `files/release402/protected-before.json` SHA-256
  `59f5a8e55ccab1026813d9ab2d6002ab6c5f8acdb09426ee1ed794d88f2d1fc6`
  captures API401/web27/otherapps/config/roles/sixjobs/workload profiles.
- Validation steps: core CLI/auth/target/capacity PASS; Bicep/ARM steps not
  applicable to image-only update; production Dockerfile/locks/identity/config
  unchanged. Build one immutable ACR image, inspect packaged CSS, then complete
  workflow and update only web digest. No infrastructure provisioning.
- Actual azure-validate workflow completed through UpdateStatus; azure-deploy
  invoked after Validated proof. Existing target/region confirmation retained
  from preparation; AZD/provision/MI AcrPull gate not applicable to this
  registry-credential image-only update.
- Web28 now Healthy/Running100%, one ready container/zero restarts,
  0.5CPU/1GiB/min1max3 unchanged. Root/config200; served CSS byte-equal to
  immutable image (SHA e8503d7bd1db8ee29d66c669f4d7de7c72348cdff238f9f0ae996651689bf3ec).
  Protected capture after-state asserts only web image/ready revision differ;
  API401, other apps, roles, six jobs and profiles unchanged. Raw normalized
  config absent; assertion-level evidence only, not independent raw replay.
- First PATCH hit transport reset; readback proved web27 unchanged, then
  same-digest retry succeeded. No extra build or config mutation.
- Sealed deployment receipt files/release402/deployment-receipt.json SHA256
  bf965e93c1103bcc09f596ab08d5cb9c219e8d69bd5f55fa1578b9e749195ddf
  seals25artifacts. UI exclusive finite actual acceptance PASS at375/1912,
  44/40px disabled/loading states only. Central verified five artifact hashes
  and geometry and inspected both crops. Bounded closure saved; no populated/
  enabled/path/provider/lifecycle or independent Network correctness claim.

## Active preparation: PR401 backend advisory tag-alias fix

- Mode MODIFY; recipe AZCLI; existing Python API Container App image-only
  update. No infrastructure generation or provisioning is required.
- Candidate head `dccd0913ec7f5827c0382490ec0a6ec8d7fae967`, base
  `b39cb1a2f0e007ce41883295c9ef4d7d2b212d51`. Await exact-head CI and
  independent source-byte acceptance before merge; build only final merged main.
- Source owner Fabric; Unified owns central integration, PR, merge, build,
  deployment and final receipt. Scope is three advisory projector/test/doc
  files. No Fabric artifact deployment, provider/native actions, grants or pins.
- Target: existing subscription `890c9bfc-d09c-4143-9ce5-465e75e3eecc`,
  `aiops-dev-rg`, Australia East, `aiops-dev-api`, registry
  `aiopsdevacr7h0ih3.azurecr.io`. Confirm current live state before mutation.
- Protect baseline API r399 image/settings/4 CPU/16 GiB, web27 digest
  `sha256:d9b9867d629535e8a2984a6c7b474772d7bc5bc46d513d4f21cb44e118fa132b`,
  identities, roles, grants, pins, lifecycle/canary gates, other apps and jobs.
- Planned flow: preserve r399 at 100%; build one immutable API image from
  merged main; qualify source/behavior offline; stage candidate at zero
  production traffic with baseline resources/config; check readiness and
  protected state; promote only after checks. Preserve rollback revision.
- Central source qualification: exact sealed three-file hashes, 295 focused
  Python tests, scoped Ruff, frontend lint and 1,955 tests passed.
- CI: all eight exact-head checks passed, run `40284650213`. Fabric canonical
  three-file review ACCEPTED. Merged `bd1ccbde1a41f49b9be857c5a4a8d65a11dbc706`
  at `2026-10-26T07:27:27Z`; immutable build source is this merge, not workspace.
- Plan/context prompt returned user unavailable with instruction to act
  autonomously; reuse the standing user-directed central merge/deploy target.
  Live account and API baseline confirmed. No new resource types or settings.
- Protected-state snapshot `files/release401/protected-before.json` captured
  four apps, six jobs and seven identity role assignments. SHA-256 canonical
  fingerprint `36ac7e6b96b5797062dba4ff998a89102e85e5f89084d2786704a6a114160f6c`.
- Quota CLI discovery failed `MissingRegistrationForResourceProvider` for
  Microsoft.Quota; no provider registration attempted. Supported environment
  `az containerapp env list-usages` confirms General Purpose 12/500 cores,
  Consumption 1.5/500, enough for unchanged 4-core staged replica.
- Existing Dockerfile/locked Python dependencies and production configs unchanged.
  Docker server 29.9.2 ready for isolated image/source/behavior qualification.
- Azure validation and immutable image complete. Zero-traffic r401 staging
  blocked by actual `api-d4` profile 3/3 nodes, despite regional quota headroom.
  System logs show `NotTriggerScaleUp`, then progression deadline/0 ready.
  API399 remains100%; no candidate traffic or production regression.
- Recovery: retire only oldest unlabelled zero-traffic r397 (reversible
  deactivation), retaining API399 serving and API398 immediate rollback.
  Ask-user returned unavailable/autonomous; bounded existing release authority
  used, no node-limit/resource change. Retry same revision/image; no rebuild.
- Recovery completed: same r401 Healthy0%, 18 baseline-ready providers, one
  ready container with zero restarts; protected template/config/roles/jobs/
  unrelated apps equal. Promoted r401 to100%; API399 now0% retained rollback.
  Serving health and replicas pass. Web27 unchanged. Deployment receipt
  `files/release401/deployment-receipt.json` SHA-256
  `2ac1817f8761e7cff231aad904303d756576c9ec6d68030703f0a10e15436b7f`
  seals24artifacts. Fabric independent exact-image acceptance requested;
  no expanded provider/native/Foundry/lifecycle acceptance claimed.
- Section 7 validation proof (PR401, `2026-10-26T07:35:26Z`):
  `az account show`, app/env/roles/jobs readback and protected snapshot PASS;
  supported environment capacity PASS; inherited policy assignment list is
  empty; no policy bypass performed. `az acr build` immutable merged archive
  run `cr2e` successful once in 4m44s, digest
  `sha256:cdbcc80c011f8450d5f1f8f9af3dc484e4d3e6e0d05cc692a267d21354ea52f4`.
  `files/release401/qualify-image.py` PASS: all472 source hashes and exact merged
  build provenance, 20 public tag-alias cases, four finite-iterable linked batches,
  22 retained Network cases; no network/read-only/cap-drop ALL.
  `git diff b39cb1a2 bd1ccbde --exit-code --` production Docker/dependency/config/
  Terraform identity and app sources PASS unchanged. Existing registry auth and
  identity preserved; no provisioning/RBAC mutation.
  Baseline `/health` captured successfully. Logs and image qualification are
  under session `files/release401/`. No unresolved validation failure;
  unsupported Microsoft.Quota replaced by supported environment usage evidence.

### PR401 all validation checks pass

- [x] Core CLI/auth/resource existence/capacity validation; image-only update.
  Bicep compile/ARM validate/what-if are not applicable: no IaC change or apply.
- [x] Docker build: one ACR build from immutable merged main, no local rebuild.
- [x] Policy validation: inspect inherited assignments for image-only rollout.
- [x] Build verification: exact source metadata/file hashes and no-network
  public projector controls, tag conflict regression, retained Network cases.
- [x] Static role verification: unchanged Terraform assignments/identity and
  existing registry credential authentication; do not run provisioning.
- [x] Record actual proof, resolve errors, complete workflow, then deploy.

## Active preparation: PR400 web-only follow-up

- Mode MODIFY; recipe AZCLI; application is the existing Next.js web image.
- Merged source: PR400 merge `b39cb1a2f0e007ce41883295c9ef4d7d2b212d51`.
  Scope is the selected-tab visibility repair and four mobile card-header
  flex-basis rules. No API, Terraform, dependency, identity, provider, or
  policy changes.
- Target candidate: subscription `ME-MngEnvMCAP448721-pangj-1`
  (`890c9bfc-d09c-4143-9ce5-465e75e3eecc`), resource group `aiops-dev-rg`,
  Australia East, Container App `aiops-dev-web`, registry
  `aiopsdevacr7h0ih3.azurecr.io`.
- Live baseline read-only verified: single-revision mode, ready/latest revision
  `aiops-dev-web--0000026`, image digest
  `sha256:498bc079bbfd993ab8eb19bd2dbe03ec0af498fce24368f38524110ee1e12d8a`.
- The current API baseline is `aiops-dev-api--r399-d09215f2`, image digest
  `sha256:f5e8c4257a42d507736113a704ac2622ed15565b0a7da114c4d94efc59739e1d`,
  4 CPU/16 GiB. Earlier starting context specified 4 CPU/8 GiB; the live
  post-PR399 API is 4 CPU/16 GiB. This release must not alter API image or
  sizing; retain the exact live baseline.
- Build exactly one new immutable web image from the merged `main` source using
  the existing deployment recipe. Deploy only that image to `aiops-dev-web`;
  do not build/deploy an API image, alter infrastructure, or change settings.
- Preserve API revision/configuration/capacity, all other apps/jobs, identities,
  role assignments, registry auth, ingress, scaling, and environment settings.
  Retain the prior web image/revision as rollback. The candidate is healthy;
  actual app-route browser checks remain blocked at the organizational
  sign-in screen because no authorized browser identity was supplied.
- Release checks: exact merged-source provenance; web revision readiness and
  100% traffic; protected-state equality; bounded served-page and browser checks
  for selected tabs and mobile card headers. Do not claim populated or
  authenticated UI, provider completeness/freshness, Foundry quality/latency,
  reachability, or broader lifecycle acceptance.
- Reuse the previously approved subscription/region and image-only AZCLI
  workflow. User's standing explicit direction authorizes deployment of
  completed validated changes and the user requested autonomous continuation.
  No new resources are provisioned, so quota checks do not apply. azure-validate
  completed with the plan status `Validated`; no Azure mutation or image build
  has yet been performed for PR400.
- Validation proof (2026-10-26): PR400 merged to `main` as
  `b39cb1a2f0e007ce41883295c9ef4d7d2b212d51`; exact-head GitHub security,
  frontend, backend, and all four backend shard checks passed. Locally,
  `npm run lint:fix`, `npm test` (149 files/1,955 tests), `npx tsc --noEmit`,
  and `npm run build` passed. The sanitized merged-source browser fixture passed
  all 19 candidate cases. Direct history-anchor comparison passed at 320/375px
  on both baseline and candidate. The existing 375px Predeploy E2E test times
  out waiting for `/changes/assess` on both trees before reaching its history
  assertions; the seven existing section-composition failures also reproduce
  identically on baseline and candidate. Neither test was weakened.

### All validation checks pass - PR400 web-only

- [x] Core Validation (CLI, auth, build, validate, what-if): Azure CLI
  authentication/target and the local web build pass. Bicep compile/deployment
  validate/what-if are N/A because this repository has no `infra/main.bicep`
  and this image-only release changes no infrastructure.
- [x] Docker Build validation: existing web Dockerfile context and package lock
  are present. The immutable production image will be built once with the
  existing ACR recipe during deployment; no duplicate local container image
  build was run.
- [x] Azure Policy Validation: read-only query returned zero applicable policy
  assignments; this release changes no policy or role assignments.

### Section 7: Validation Proof - PR400

2026-10-26:

- GitHub Actions run `40278519584`: security-scan, frontend, backend, and
  backend-tests shards 0-3 all passed. Trivy passed. PR400 merged as
  `b39cb1a2f0e007ce41883295c9ef4d7d2b212d51`.
- Local command `cd web && npm run lint:fix && npm test && npx tsc --noEmit &&
  npm run build` exited successfully: lint clean, 149 files/1,955 tests
  passed, strict TypeScript passed, and production build completed.
- Sanitized production fixture command
  `PLAYWRIGHT_BASE_URL=http://127.0.0.1:3113 npx playwright test
  e2e/selected-tab-visibility.spec.ts e2e/mobile-card-header.spec.ts
  --project=chromium` passed 19/19. The seven integrated candidate files were
  byte-identical to the fixture source.
- Read-only preflight receipt at
  `/Users/jasonmba/.copilot/session-state/f13dff91-b486-4191-a5ce-95039edefbf5/files/pr400/azure-preflight.txt`, captured
  `2026-10-26T06:31:50Z`, SHA-256
  `9938190a7eb2eb9bbc77efb4f3fa14d672a54562407b352f84ee21000509b35d`:
  confirmed selected subscription/tenant, registry, web26 baseline, and API
  r399 baseline. The applicable policy assignment count was zero. API currently
  reads 4 CPU/16 GiB; no API change is in this release.
- Existing Predeploy history E2E at 375px timed out waiting for
  `/changes/assess` on both pristine baseline and candidate before its history
  assertions; direct anchor comparison passed at 320/375px on both. Seven
  existing section-composition assertions remain identical baseline failures.
  These known non-regressions are retained without weakening tests.
- Validation harness issues were resolved: replaced an unsupported policy CLI
  flag with `--disable-scope-strict-match true`; reran browser checks using the
  sanitized fixture after a checkout-local `.env.local` prevented test-page
  rendering. The corrected policy query and all 19 candidate browser checks
  passed. No source or production configuration workaround was added.
- No Bicep/Terraform/RBAC or workflow paths changed.

### Deployment verification - PR400 web-only (2026-10-26)

- Structured receipt:
  `/Users/jasonmba/.copilot/session-state/f13dff91-b486-4191-a5ce-95039edefbf5/files/pr400/deployment-receipt.json`,
  SHA-256 `e4573d25ea3d1358cf402575655618cacb9119ba01214cdf6e5c6199df04ccee`.
- Source provenance: `origin/main` was `b39cb1a2f0e007ce41883295c9ef4d7d2b212d51`
  at build time. ACR run `cr2c` failed before image publication because the
  root API Dockerfile was selected against the web context; no release tag was
  created. The corrected build from `web/` succeeded as ACR run `cr2d` in
  4m18s. Image `aiopsdevacr7h0ih3.azurecr.io/aiops-web:pr400-b39cb1a2` resolves
  to immutable digest
  `sha256:d9b9867d629535e8a2984a6c7b474772d7bc5bc46d513d4f21cb44e118fa132b`.
- Only `aiops-dev-web` was updated, by digest. Revision
  `aiops-dev-web--0000027` was created at `2026-10-26T06:43:07Z` and is
  `Provisioned`, `Healthy`, and `Running`; ingress routes 100% to latest.
  Three replicas were observed, all ready with zero restarts. The old revision
  `aiops-dev-web--0000026` remains available but inactive and Healthy.
- Compared with revision 26, revision 27 preserves web CPU/memory, environment
  variable names, `minReplicas: 1` / `maxReplicas: 3`, and container name; only
  the image and revision identity changed. FQDN, ingress, registry credential
  configuration, and user-assigned identity are unchanged. The shared
  identity's live role assignment set was identical before and after.
- The API remains `aiops-dev-api--r399-d09215f2`, image digest
  `sha256:f5e8c4257a42d507736113a704ac2622ed15565b0a7da114c4d94efc59739e1d`,
  4 CPU / 16 GiB. No API or other Azure resource was changed.
- Credential-free HTTPS smoke checks returned HTTP 200 for `/` and
  `/api/config`. The deployed-host Playwright run for selected tabs and real
  card headers reached the sign-in screen on all routes and did not reach the
  UI assertions (12/12 blocked; snapshot said “Sign in with your organizational
  account to continue”). No identity, storage state, or sign-in attempt was
  used. Thus the merged-source fixture remains 19/19 passing, but authenticated
  deployed tab/card behavior and populated UI are not certified.
- The successful ACR `npm ci` reported 15 dependency advisories (3 moderate,
  9 high, 3 critical). A production-only `npm audit --omit=dev` reported 4
  vulnerable packages: direct `next` critical and `postcss`, `source-map-js`,
  and `zod` high. PR400 changed no web dependency manifests or lockfile, and
  PR400 security/Trivy checks passed; the dependency advisories were not
  remediated in this UI-only release and remain a separate risk.

## Completed release: PR399 Network design review (Deployed - bounded ACCEPTED)

## PR399 Network release record

- User-directed central merge/deploy request relayed by Agentscall_XhjGUd3cVkUtZUp4ORgTuhFB.
  Ownercd97ec54 supplied exact-base9d385ae0 sixteen-path patch66a060e6;
  applies cleanly to accepted8f5fdf05, intervening changes disjoint.
- Three explicit policy-opt-in Network checks only: public/private access,
  peering/address integrity, NSG configured exposure. Existing scoped governed
  firewall_nsg_gaps category design_review, no new grants/tools/pins/identity.
  Drawer canonical request cancellation/scope late-result protection included.
- Central806coupled plus414canonical unified API/package Python PASS/1skip,
  149files1950web units, lint:fix/Ruff/build/strictTS PASS. Frozen downstream
  byte contract retained. PR399 head2219bb7440dca1461b995c8143660e5cac5a4e5c.
  Independent owner GitHub diff reconstruction confirms all16paths byte exact.
- Installed Edge local production/no-Entra mocked provider fixture at375/1912
  verifies Network starter exact canonical hint, pending Cancel, late-response
  rejection, zero runner errors and no document overflow. Scope-change/late
  transport covered by unit tests; not actual deployed/provider certification.
- Plan/context confirmation attempted; user unavailable and instructed autonomous
  decisions. Existing explicit user-directed bounded Network merge/deploy
  authority retained; no scope expansion or newly authorized cloud grants.
- MODIFY existing API+web images only, aiops-dev-rg/AustraliaEast/subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc/tenant262a3a77. Preserve4CPU16GiB
  API,0.5CPU1GiB web/config/roles/profiles/all unrelatedapps/sixjobs.
- Exact-head CI and independent Network owner source review before guarded
  merge; immutable merged archive/API+web builds once each. Actual API hash/
  provenance/scenario and retained Fabric contracts before0%stage then promote
  only Healthy/ready0restart/every fresh baseline-ready provider preserved.
  Existingr398 stays serving until candidate qualified, retained for rollback.
- No runtime policy opt-in configuration, acquisition, authorization, Foundry
  identity/publication/native/scheduler mutation. Missing policies/coverage
  remain unknown; offline correctness not live provider/Foundry/latency evidence.
- Both pending UI packages and Fabric tag-alias candidate EXCLUDED. PR398closed.
  Nonproduction browser UI qualification and bounded postdeploy source/runtime
  acceptance required; no model/data action or production policy enabling.

### Section 7: Validation Proof - Network

2026-10-26: actual azure-prepare then stepwise azure-validate LoadPlan,
AddValidationSteps/RunValidation/BuildVerification/StaticRoleVerification completed.
az account/group verifies subscription890c9bfc/tenant262a3a77/AustraliaEast;
az2.90.0/docker29.9.2. All8 exact-head CI40270120020 PASS; guarded PR399
merged d09215f20866bf0e4905f708586c473faa82b38a, archived immutable source.
git diff8f5fdf05..d09215f2 confirms zero infra/RBAC/Dockerfile/lock/workflow
delta; no new data-plane operations, existing scoped provider path only.
No Bicep or provisioning/what-if operation applies to this image-only release.
az acr build exactly once per image: cr2a API4m9s digestf5e8c4257a42d507736113a704ac2622ed15565b0a7da114c4d94efc59739e1d;
cr2b web4m48s digest498bc079bbfd993ab8eb19bd2dbe03ec0af498fce24368f38524110ee1e12d8a.
Actual API472source hashes/provenance/22duplicate/44timestamp/4Iterable/2alias
and22public Network cases PASS networknone/read-only/capdrop.
Actual production-auth web69static hashes/BUILD_ID/starter/category/cancel/
production Entra client PASS. Local fixture browser375/1912 and1220Python/
1950frontend/lint/build/types/Ruff/frozen topology PASS. No test image reused.
Fresh sanitized protected resources/config/roles/profiles/unrelatedruntime and
18baseline-ready providers captured; policy assignments captured. Existing
acr-password auth retained; no managed-registry-identity migration/provisioning.
Harness-only initial failures corrected without source/image/seal mutation:
preserve predecessor replacement literal, block socket.connect not socket class
before lazy SSL imports. Final exact target digest qualified successfully.

### All validation checks pass - Network

- [x] Core Validation (CLI, auth, build, validate, what-if): existing AZCLI image-only
  operation; unchanged infra/Dockerfiles/locks. No Bicep provisioning delta.
- [x] Docker Build: immutable merged API and web images once each; actual runtime
  source/provenance/public Network and retained Fabric contracts.
- [x] Azure Policy Validation: captured current policies and protected state.

### Network deployment outcome

Actual azure-deploy completed after full stepwise validation. APIr399-d09215f2
Healthy100%1ready0restart, r398active0rollback. Web26 Healthy100%1ready0restart;
all69servedstatic hashes equal immutable production image.18baseline-ready
providers retained, protected configuration/resources/roles/profiles/unrelated
apps/sixjobs equal. Only obsolete unlabelled0%r396 deactivated after exact proof.
Deployment receipt854a651a4b478fb1a8de0b0e708f679ec690a02dee3c943d8962e5c2ad71d1d4.
Network owner independent sealed-image/source acceptance/deployment ACK PASS;
owner artifact0c3f629644326147165e397bf823a3fd759a265e0ff1e6ec9302f8dfde2cc374.
Final bounded closureb2135ad76e6dbcbbabe98bb34794ec94284467a481ba477c6a364c4f79cddecb
sealed and sent Network/Agents/UI; explicit final ACKs from all three persisted
in release399/final-acks.json. Bounded Network release closed; separate UI/Fabric
intake remains open and excluded from this deployment.
No central browser/server remains. Existing provider/Foundry/UI limitations held.

## Historical preparation: PR398 duplicate inventory declaration consistency

- MODIFY existing AZCLI API only, aiops-dev-rg/AustraliaEast/subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc/tenant262a3a77. No new resources.
- Exact three backend/test/doc paths at 528a4567b8402d4a2864fbcd733db3686986499f.
  Independent owner GitHub hash review PASS against receipt3a47a1a9.
  Duplicate payload/effective-generation/effective-UTCtime conflict abstains;
  independent Monitor and equivalent defaults/offsets preserved.
- Central pristine-source reproduction20fail/2controls; candidate322coupled
  backend/Ruff and frontend149files1948tests/lint:fix PASS.
- Require all exact-head CI, guarded merge then immutable merged source archive.
  Build API once; qualify all470 packaged source hashes/provenance,22duplicate
  cases plus44timestamp/4Iterablelinkedbatch/2alias guards networknone/read-only.
- Keep web25 exact1f6e1f2d entirely unchanged. No web build or UI recertification.
  Both later UI candidates/Network work/dirty historical plan excluded from PR.
- Preserve API4CPU16GiB/80Gi ephemeral, all existing config/identities/roles,
  profiles/unrelatedapps/sixjobs; stage copied r397 at0%, maintain r397100%
  until Healthy/ready/no restarts/every fresh baseline-ready provider preserved.
  Promote explicit100%; retain r397active0 rollback. Any cleanup requires
  exact obsolete unlabelled0% revision proof, never serving/rollback revision.
- No provisioning/capacity/auth/RBAC/provider/acquisition/native/scheduler/
  publication mutation. Source consistency is not authenticated provenance.
- Existing autonomous release authority; confirm same Azure context before
  execution. Fresh protected snapshots/health/policy/role evidence mandatory.
- Both deployment ACK and independent exact-image acceptance/final ACK gates
  retained. PR397 closure51c06584 unchanged, three KB continuity failures disclosed.
- Plan confirmation attempted: user unavailable, instructed autonomous decisions;
  existing sole-integrator bounded release authorization retained. Actual account/
  tenant/group location verified expected; three existing active revisions, newest
  r397100%, two old0%. No quota or capacity increase requested.
- npm latest Azure MCP now4.0.0-beta.3, beyond documented beta.46 fix; no persistent
  wrapper retry needed for this existing CLI-only image release.
- Functional verification: public projector tests/reproduction/322coupled
  backend and1948frontend units/lint pass; unchanged Dockerfile/locks and frozen
  source-only build path reviewed. Fresh production health ready18providers and
  protected resources4CPU16GiB/roles/profiles/web25 captured. Offline immutable
  image contract plus candidate startup/readiness remain pre-promotion gates.

### Section 7: Validation Proof - PR398

2026-10-26: azure-prepare completed, current Ready for Validation plan loaded by
actual azure-validate stepwise workflow. All8 exact-head CI40266544043 PASS at
528a4567; guarded merge8f5fdf05284c58dd64bbe8ba46c357e4c8e3af05 archived.
az account/group confirms expected subscription/tenant/AustraliaEast.
az2.90.0/docker29.9.2 available; policies captured0assignments. No IaC/role/
configuration or new data-plane delta (git diff --exit-code confirms infra/
Dockerfile/uv.lock/deploy configs unchanged); infrastructure validate/what-if/
provision inappropriate for this existing image-only operation.
az acr build cr29 successful3m53s, exactly once immutable archive/absolute
Dockerfile, digest2b134065a7727852407ef92a5367ddc97f0e53397f3fb628989fdc85779cac67.
Actual docker no-network/read-only/capdrop qualification independently verifies
470source hashes/provenance and22duplicate+44timestamp+4Iterablelinkedbatch+
2alias controls. First pull blocked by expired local registry login; az acr login
refreshed local CLI Docker credential, then exact same digest qualified. No new
image build or cloud identity/RBAC/authentication change.
Central322coupled/Ruff and149files1948frontend tests/lint:fix PASS.
Fresh before-state roles/profiles/config/runtime protected and18ready baseline
captured; preserve candidate0%/promotion readiness and role parity gates.

### All validation checks pass - PR398

- [x] Core Validation (CLI, auth, build, validate, what-if): existing image-only
  operation; no Bicep or infrastructure delta, validate/what-if not applicable.
- [x] Docker Build: immutable merged API image once plus offline contract.
- [x] Azure Policy Validation: captured policies, no resource/config changes.
- [x] Static Role Verification: source-only projector adds no data-plane access,
  identities or role assignments; existing registry secret/UAI/roles unchanged.

### PR398 deployed; independent acceptance pending

APIr398-8f5fdf05 exact2b134065 Healthy100%1ready0restart after0%qualification;
all18fresh baseline-ready preserved candidate/promoted. Web25 exact1f6e1f2d
entire runtime/configuration unchanged,Healthy100%1ready0restart/config200.
Protectedconfig/resources/roles/profiles/all unrelatedapps/sixjobs equal.
Only provenobsoleteunlabelled0%r395deactivated; r397active0rollback retained.
Cleanup confirmation attempted, user unavailable/autonomous instruction retained.
Seal script first used active-only revision list for deactivated r395; corrected
to explicit revision-show cleanup-after evidence, no workload retry/mutation.
Receipt1e702a1a1f5b038dfa2332f7d2fc9dc25db4402cc99e9dab0032cf84be5a67a7
seals31files. Both deployment notices delivered; owner ACKs/independent Fabric
exact-image acceptance/final ACKs pending. No new UI recertification requested.
Both deploymentACKs persisted: UIcall_VrjbG3lbetsxSZHqOM0QyWzF and
Fabriccall_2BO4PK67Ja4UryCIEecTGiqD. Fabric independently verified all31seals,
predecessor harnesses/470GitHubsources/mergedfixture/provenance and22duplicate+
44timestamp+4PUBLICIterablelinkedbatch+2alias exact-image contracts plus serving/
protected/readiness parity. Closurea1f8e27df96c561e1b9302b3c0d6170d8cf85b6dfd42717790515a66d36c74f6
sealed; both FINAL bounded ACCEPTED notices delivered, explicit ACKFINAL pending.
Pending UI packages deferred-not-rejected; require separate central source/seal
and baseline-failure qualification. No PR398 scope expansion.
Both explicit final ACKs persisted: Fabriccall_jfRUBWscFIQmzpAVmaxNb7yl,
UIcall_PBPigaUz68f3no86yRcyxMYQ. PR398 bounded release acceptance complete;
broader engineering loop remains open.

## Historical preparation: PR397 Exposure route reveal and timestamp v2

- MODIFY existing AZCLI API/web in aiops-dev-rg/AustraliaEast/subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc, tenant262a3a77. Image-only bounded release.
- Exact6paths/two commits headd7982d4d, both owners independently GitHubhashreviewPASS.
  Exposure horizontal nav reveal without focus/document scroll/CSS changes;
  invalid/naive/non-time inventory timestamps abstain, independent Monitor retained.
  Superseded timestampv1 and later Inventory/Connections5path handoff excluded.
- Require exact-headCI then merged archive/API+webbuildonce. API qualification
 470sourcehashes/provenance/44timestampcases plus retained Iterable/alias guards,
 networknone/read-only/capdrop. Web actual bounded route-label gate after rollout.
- Preserve API4CPU16GiB/web0.5CPU1GiB,config/roles/profiles/unrelatedapps/sixjobs.
  StageAPI0% copiedfromr396, keep r396100% until Healthy/ready/no-restart/fresh
  baseline-readyproviderparity. Promoteexplicit100%,retainr396rollback.
- Central28timestampnegatives/16controls then132coupled/RuffPASS. UI4negativeunit/
 14controls then1948units/lint/build/types/32productionbrowserPASS.
  Three pre-existing KB continuity tests fail identical accepted/candidate missing
  governedlink; not counted PASS. First central npm start invokes dev; stopped,
  corrected start:prod/rebuilt production fixture and recorded fresh successful run.
- No provisioning/auth/RBAC/capacity/provider/native/scheduler/publication changes.
  Existing autonomous release authority retained; confirmation/context pending.
  Both deployment/final ownerACK gates retained; no new broad UI certification.
- Preparation completed: all8 exact-head CI40263028128PASS; mergedf9ec86073232451fd840a03f12de8c3a61283d26.
  APIcr28(4m16s) digestaf86e08dd90197c3e5455ab97a3e889f81e57f1729732c995949a1ce1c98416f;
  webcr27(4m7s) digest1f6e1f2da38bd832e9fd9b0de0766b2c4e7e5c67e7056e33db13a01c05ef7164.
  Both built once with absolute immutable archive Dockerfiles.
- ActualAPI networknone/read-only/capdrop470sourcehashes/provenance/44publictimestamp/
  4finiteIterablelinkedbatch/2aliasguardsPASS. Freshstate/roles/profiles/health/policy
  captured; subscription/tenant/AustraliaEast context confirmed. No new IaC/locks/
  Dockerfiles/authentication/roles or data-plane operation. Existing registry secret/
  UAI retained; no provisioning/what-if needed for image-only update.
- User unavailable confirmation retains explicit autonomous coordinated release
  authority. ActualUI gate may require normal session restoration, no auth bypass.
- Fetch recovered from broken inherited GIT_EXEC_PATH by using installed Apple
  Git helper directory; merge identity verified before retry, no duplicate merge.

### All validation checks pass - PR397

- [x] CoreCLI/auth/target/scope validated; image-only/noinfra, deployment validate/
  what-if/provision not applicable.
- [x] Docker contexts/uv.lock/package-lock reviewed unchanged; successfulcr27/cr28
  and actual immutableAPI qualification above.
- [x] Policy assignments captured, existing service configurations unchanged.
- [x] Static role verification: six-path delta adds no role/identity/authentication
  or data-plane operation. Retained role snapshots captured for postdeploy comparison.

### Section 7: Validation Proof - PR397

2026-10-26: gh pr checks397 all8CI40263028128PASS atd7982d4d; GitHubownerreviews
all6sourcehashes exact. Mergedf9ec8607archive solebuildsource. az account/group
expected890c9bfc/tenant262a3a77/AustraliaEast; az policy assignment list captured.
az acr build successfulAPIcr28af86e08d/webcr271f6e1f2d onceeach.
python3 release397/qualify-image.py verifies470packagedsourcehashes/provenance and
44timestamp+4Iterablelinkedbatch+2retainedaliascontrolsPASS, networknone/read-only/
capdrop, reviewed mergedfixturehelpers only. Central132coupled/Ruff/1948units/
lint/build/types/32productionbrowserPASS. Three existingKBcontinuityfailures
reproduced unchangedbaseline/candidate and disclosed, not countedgreen; no new
validation failures. Freshsnapshot/roles/profiles/currenthealth captured. No
provision/what-if/newroles appropriate. Candidate readiness/providerparity and
actualExposurelabelacceptance remain mandatory release gates.

### PR397 deployed; independent acceptance blocked by session delivery

r397-f9ec8607af86e08d Healthy100%/1ready0restart/18freshbaseline-readypreserved
after0%qualification. web251f6e1f2d Healthy100%/1ready0restart/root+api-config200.
Protectedconfiguration/resources/roles/profiles/unrelatedapps/sixjobsequal;
r396active0rollback,onlyobsoleteunlabelled0%r394deactivated. Receipt
fcb6d7acb9b1a5c3c118d3d43fad7ba07f64220a5bf8ae3ea752a733f3c28a8dseals29files.
Bothdeploymentnoticeattempts failed ENOENT twice each; both ownerIDs still
listedbutnotrunning. No accepted delivery/ACK/imageacceptance/actualUI/finalACK
claimed. Resume existingownercoordination after messaging runtime available.
No rebuild/redeploy or replacementparallelimplementer necessary.
2026-10-26 recovery: cachedGithelpers now present; ordinarygitls-remote succeeds.
Both deployment notices accepted on retry, both originalowner sessions confirmed
running/busy. Messagingblocker cleared, actualACK/acceptance stillpending.
No binary/settings/authentication/workload changes made for recovery; causal
root of earlier ENOENT not proven from apptrace. coordination-recovery.json saved.
BothdeploymentACKs nowreceived; independentFabricimage470source/provenance/
44timestamp+4Iterable+2aliasacceptancePASS. UIactual6states/5hashes/twovisuals
centrallyverified, boundedPASS; all6loading/no-network-errorinventorylimitsretained.
Closure51c06584bb536f8668338a62efaa03ebf598458d1b5c857dda2afc67ea4362dfsealed;
bothFINALboundedACCEPTEDnoticesdelivered, explicitACKFINALpending.
Both explicitACKFINAL persisted: Fabriccall_tzHI36wn3d9iQyku9dmjh34T,
UIcall_pxIeqt89p5dZmKRTuAXjIzLv. PR397finiteacceptancecomplete; coordination
deliveryrecoveryverifiedend-to-end. BroaderexistingengineeringloopOPEN.

## Historical preparation: PR396 finite application-entity iterable parity

- MODIFY existing AZCLI API only in aiops-dev-rg/AustraliaEast, subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc. Existing tenant/registry/auth retained.
- Three backend/test/doc paths, exact head61d26cae; all exact-head CI passed
  run40255903614 and independent owner GitHub source hashes match sealed handoff.
- Snapshot finite application_entities once; preserve list/tuple/iterator/generator
  public projection and linked-batch entities/pair/citations. Existing alias guard retained.
- Merge with exact-head guard; archive merged source; build API once from archive.
  Network-none/read-only/capdrop image qualification must verify provenance/all
  packaged source hashes and finite iterable public projection/linked-batch parity.
- Web24 digest10154e46 remains unchanged; no web build or new UI acceptance claim.
- Preserve API4CPU16GiB, profiles/roles/config/identity/unrelatedapps/sixjobs.
  Stage copied r395 at0%, retain r395100% until candidate Healthy/ready/no restarts
  and every fresh baseline-ready provider preserved; then explicit promotion.
- No provisioning, data-plane/provider reads beyond established readiness endpoint,
  capacity/native/scheduler/Monitor enablement/publication or configuration changes.
- Central88coupled tests/Ruff and frontend lint:fix/1943tests pass; two negative
  controls fail old behavior, list/tuple controls pass. Exact3 integrated hashes match.
- Existing explicit autonomous image-only release authorization retained.
  Both deployment and final-disposition notices/ACKs remain required.
- Section7 proof complete for merged image/build/static role verification and validation.
  Authenticated settled-navigation check separately blocked; offline CSS not React proof.
- Preparation complete: merged9d385ae0857db6acd2f28f850e7ca6183a82ea9c after all8
  CI40255903614 passed; immutable archive used for successful APIcr26(4m23s),
  digest8c7bd5fa5c476a77b08fb1723441a60e8a47150e0f5202b6f9a56575d8eb2989.
  Exact-image470sourcehashes/provenance/four finite iterable linked-batch cases/two
  retained alias controls pass networknone/read-only/capdrop, no real credentials.
- Subscription/tenant and AustraliaEast target confirmed through Azure CLI; fresh
  before-state/roles/profiles/current health and policy assignments captured.
  Confirmation unavailable; prior explicit autonomous bounded image-only authority
  retained. No new IaC/Dockerfile/lock/auth/role changes; no provisioning necessary.

### All validation checks pass - PR396

- [x] Core validation: Azure CLI/auth/subscription/target confirmed; image-only
  update, no generated Bicep or infrastructure delta, so deployment validate/
  what-if/provision not applicable.
- [x] Docker build: merged archive/root Dockerfile/uv.lock reviewed; APIcr26
  successful; exact image provenance/470hashes/public contract harness passed.
- [x] Azure policy assignments retrieved; existing service configuration unchanged.
- [x] Static role verification: exact3path delta adds no network/data operation,
  identity/role/authentication/IaC changes. Existing roles unchanged.

### Section 7: Validation Proof - PR396

2026-10-26: `gh pr checks396` all8PASS exacthead61d26cae, CI40255903614;
merged9d385ae0857db6acd2f28f850e7ca6183a82ea9c. `git diff848884e4 origin/main`
exact3backend/test/doc paths, noinfra/auth/RBAC/new data operation.
`az account show` expected890c9bfc/tenant262a3a77; `az group show` AustraliaEast.
`az policy assignment list` captured. `release396-snapshot.py before` captures
fresh configuration/roles/profiles/resources/all apps/sixjobs; serving health200.
`az acr build` APIcr26 success4m23s from immutable merged archive/rootDockerfile
and unchanged uv.lock; digest8c7bd5fa5c476a77b08fb1723441a60e8a47150e0f5202b6f9a56575d8eb2989.
`python3 release396/qualify-image.py` actual packaged470sourcehashes/provenance,
public list/tuple/iterator/generator projection+linked-batch equality with2entities,
1pair/2linkedcitations and two prior alias guards PASS. Networknone/read-only/
capdrop, mounted merged fixture helpers only, no real credentials.
Central pytest88coupled/Ruff, frontend lint:fix/149files1943tests PASS. Prior
negative exactly2iterator/generatorfails whilelist/tuple controls pass.
No IaC/provision/what-if/newrole or webbuild applicable to bounded API-only recipe.
No unresolved validation errors; readiness/zero-traffic/provider parity still gates
promotion. Separate authenticated UI audit remains blocked and unclaimed.

### PR396 deployed and bounded acceptance complete

APIr396-9d385ae0 Healthy100%/1ready0restarts,18freshbaseline-readyproviders
preserved after0%qualification. r395active0rollback; onlyobsoleteunlabelled0%r393
deactivated. Entireweb24runtime/image/traffic unchanged, root/api-config200.
Protectedconfiguration/resources/roles/profiles/unrelatedapps/sixjobs equal.
Receipt8c10d97507bd10ba7bcad3d6501dd3b05ca1c0c428121c2572a7b0f16ceac4d4
seals26supportingfiles; bothdeploymentnotices sent. No webbuild or UIacceptance
claim. Mistaken/config.json404 correctedtoactual/api/config200, notappfailure.
BothdeploymentACKs persisted; Fabricindependent26sealedhashes/470GitHubsource/
provenance/fourpublicfiniteIterablelinkedbatch/twoaliascontrols acceptancePASS.
FinalboundedACCEPTEDclosureae3bcc19bab6f9b81b62f5e54a906ec16e9878b3cb1fe5dc92d6378ef88ac946
sealed and sent to both owners; explicitACKFINAL pending. BroaderloopOPEN,
separateauthenticatedsettlednavigationblocked, no new UI certification.
Both explicitACKFINAL received/persisted: Fabriccall_O19SOuAcw0DdzCHF5pFD574g,
UIcall_XmvIZ8rWNknf2iY3oePBsAAW. FinitePR396complete; broaderloopOPEN.

## Historical preparation: PR395 decoder sanitation, binding ambiguity and filters

- MODIFY existing AZCLI API/web apps in aiops-dev-rg/AustraliaEast, subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc; tenant262a3a77. Image-only release.
- Exact head ae2e62bf498b8a5bc9da10f6da07f41f923a7f62, eight paths in three
  distinct owner commits. Require exact-head CI and merge, archive merged main,
  build API/web once; do not rebuild PR394 or use dirty checkout as build context.
- API offline exact-image qualification: all packaged source hashes/provenance,
  actual httpx MockTransport nested-JSON failure on search/later search/direct/
  later direct, sanitized exit1/empty stdout/resource closure/no retry.
  Binding normalization all alias permutations abstain, equivalent aliases equal;
  no live Monitor acquisition/enablement or publication.
- Web single min-height token change, exact PR394 prose retained; shared fixture
  and actual-page regressions pass. Actual no-injection filter closure after deploy.
- Existing target/resources/config/identity/registry auth unchanged. Preserve API
  4CPU16GiB, web0.5CPU1GiB, roles/profiles/capacity/unrelated apps/sixjobs.
- Stage API0% copied from r394, explicit r394100% pin; require healthy ready
  zero restarts and fresh baseline-ready provider parity before promotion.
  Retain r394 rollback; web rollback is immutable web23c4c7ab9d redeployment.
- No provider/native/scheduler/capacity/config mutations, no provisioning.
- Central127Catalog/Ruff+84ontology evidence/runtime/replay/baseline/gate cases,
  1943frontend/lint/build/types and79browser pass. Eleven independent negative
  controls fail old behavior and pass restored candidate. Both owner GitHub
  reviews confirm all eight exact handoff bytes.
- Existing autonomous release authority retained; confirmation and current
  context verification pending. Both deployment and FINAL notices/ACKs required.
- Coverage excludes response size/depth prevention, Monitor production readiness,
  universal provider/schema certification and arbitrary UI states.
- Preparation complete: all8 exact-head CI40252661624PASS; merged848884e432637afbae12b611cde7948f9a1b11fe.
  Immutable merged archive used for APIcr24 digest7f4db2fa162247bb43a93db2772f9af6c4e924a92adcbd28208d53dd881f187b
  and webcr25 digest10154e46dc4d98d42524e1671a3d00d29483e37c2cd6471386744eeafe446006.
  Webcr23 failed before producing image due cwd-resolved rootDockerfile; corrected
  explicit webDockerfile. Exactly one successful image percomponent; no rebuild.
- Exact API networknone/read-only/capdrop verifies470src/provenance, four actual
  HTTP decoder sanitized failures plus successful case,17 public projection
  ambiguity/equivalence cases. Initial fixture namespace lacked timedelta;
  harness corrected only, unchanged image. No real credentials/network.
- Context confirmed account/tenant, current FabricF8Active and existing rollback.
  Userunavailable confirmation retains prior explicit autonomous coordinated
  image-only release authorization; no provisioning/destructive expansion.
- Fresh protected-state/roles/profiles baseline and currenthealth/policy captured.
  Dockerfiles/locks unchanged, no generated infrastructure or authentication change.

### All validation checks pass - PR395

- [x] Core CLI/auth/target and scope checked. Image-only modification with no
  infrastructure delta; Bicep build/deployment validate/what-if not applicable.
- [x] Docker context/locks reviewed; successful APIcr24/webcr25 builds from
  merged848884e4 archive. Exact API provenance/470hashes/5decoder/17projection cases pass.
- [x] Current subscription policy list recorded; existing target unchanged.
- [x] Static role verification: eight-path source delta has no infrastructure,
  identity/authentication/role definition or new data-plane operation.
  Existing registry secret/UAI roles retained; no role provisioning.

### Section 7: Validation Proof - PR395

2026-10-26: exactheadae2e62bf CI40252661624 all8SUCCESS; merged848884e4.
`az account show` subscription890c9bfc/tenant262a3a77; `az group show` AustraliaEast.
`git diff --name-only 56d433c7 origin/main` exactly8paths/noinfra/auth/RBAC delta.
`az policy assignment list` and fresh before-state/health/roles/profile captured.
`az acr build` successful APIcr24(4m18s)/webcr25(3m53s), immutable merged contexts.
API7f4db2fa/web10154e46 retained; cr23wrongDockerfilefailed/noimage, not deployed.
`python3 release395/qualify-image.py` with Docker networknone/read-only/capdrop:
470sourcehashes/provenance,4sanitizedactualdecoderfailures+1success,17public
projection alias cases PASS. Harness timedelta correction only, unchanged image.
Independentpytest127Catalog+84ontology/Ruff, web lint:fix/1943tests/build/types,
79browsercases PASS; four decoder and seven geometry negatives reproduced.
No provisioning/what-if/new roles necessary or permitted in image-only recipe.
All preparation validation checks pass; actual zero-traffic readiness still gates
promotion and finite actual UI acceptance remains postdeployment.

### PR395 deployed; finite owner acceptance pending

Validated workflow completed. ExactAPIr395-848884e4 qualified Healthy0%/1ready/
0restarts with all freshbaseline-readyproviders; explicitpromotion100% passed
sameproviderparity. Alreadybuiltweb10154e46 deployed as0000024 Healthy100%,
1ready0restarts/root+config200. Protectedsnapshot/roles/profiles/resources/
unrelatedapps/sixjobs equal. Onlyobsoleteunlabelled0%r390deactivated; r394active0
rollback retained. No capacity/config/role/provider/native/scheduler mutation.
Receipt dca2234552d0dd2f90fe84bd50f4fb2c2d485c87ceb36b2749577850ed64b673
seals25supportingartifacts. Both deployment notices sent; actual filter closure
and independent dual-contract Fabric/API acceptance requested. FinalACKs pending.
Both deploymentACKs received; Fabric independentlyverifiedall25hashes/470src/
5decoder/17PUBLICprojectioncases/providerparity/protectedstate, boundedPASS.
UI actualfilter6captures/21measurements44/40/40 labels/values/focus/boundsPASS;
central11hashes+seal/recomputedgeometry/4visuals verified. Retains6loading/1abort,
mobilePrioritiesviewportsidebarocclusion/Identitynavremnant, NOTmobile-shell
visualacceptance. Closure2f296c67 sealed; bothFINALnotices sent/ACKFINALpending.
Both explicit finalACKs now persisted; finitePR395releasecoordination complete.
Broaderexistingimplementationloop remainsopen; no speculative mobile-shellrepair
or universal visual acceptance inferred from transition-frame screenshots.

## Active preparation: PR394 Catalog clocks and full-width narrative sections

- MODIFY existing AZCLI API/web apps in aiops-dev-rg/AustraliaEast, subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc. No IaC/provision/RBAC/config changes.
- Eight source paths: Catalog source/test/runbook; globals.css and four browser
  helpers/specs. Distinct source commits eabcbbf8/e534dc8b/ce6cb036.
- Final head ce6cb03679e81f5f97883da3e4a4baa7dba602d5 must pass all exact CI.
  Archive merged main only, build API/web once each; immutable digests only.
- API exact-image qualification: packaged source/provenance, offline mocked
  direct verification old-clock rejection/equality/increase, retained replay.
  No new Catalog/provider reads; actual health readiness may read existing SQL.
- Snapshot config/resources/identity/roles/profiles/unrelated apps/sixjobs.
  Preserve API4CPU16GiB/web0.5CPU1GiB and existing registry secret authentication.
- Stage API0% from r393, require Healthy/ready/0restarts and all baseline-ready
  providers; promote explicit100% retain r393 rollback. Then update web.
  Existing web22 fced3ed8 rollback by immutable redeploy in Single mode.
- Capacity externally resumed F8; verify Active, do not pause/resume/resize.
  No cloud policy/native/provider/scheduler/patch execution or vm1 mutation.
- Local158Catalog/Ruff,1943frontend/lint/build/types,56final focused browser
  cases pass; owner236coupled/249temporaryCSSsimulation captures retained.
- Coverage limits:155loadingcaptures, no live authorized service/situation detail
  links; offline fixtures only there. Not universal allstates/page certification.
- Notify BOTH owners deployment and FINAL accepted closure, require explicit
  ACKs; actual servedCSS no-injection finite route/section closure required.
- Preparation checklist: source reviewed, unchanged Dockerfiles/locks/target,
  current rollback retained. Validation/provenance/build proof recorded below.
- Final CI all8PASS run40248679917; merged56d433c7e3bb15d33e836b28e41b6185f517dcf5
  at2026-10-26T00:31:58Z. Userunavailable confirmation retains established
  autonomous image-only release authorization and exact existing target.
- Fresh before-state/health/policy evidence captured; account/tenant match,
  FabricF8Active. Existing role/config/resources unchanged; no provision needed.

### All validation checks pass - PR394

- [x] Core CLI/account/RG/region/image-only recipe verified. No infrastructure
  delta; Bicepbuild/what-if/provisioning inapplicable, unchanged Terraform retained.
- [x] Container build context/lock/Dockerfiles reviewed. APIcr22/webcr21 succeeded
  once each from exact56d433c7archive. EarlierwrongDockerfilepath rejected before
  anyACRbuild submission; correctedrootDockerfile, no duplicatebuild.
- [x] Azure policy list captured; no new policy/role/config change.
- [x] Local qualification and exactheadCI pass. Image networknone/read-only/capdrop
  verifies470packagedsrcfiles/provenance/fourclockcases and retainedoffline replay.
- [x] Static/live roles captured with protectedsnapshot; existingregistrysecret
  auth/UAI retained, no role provisioning/migration.

### Section7: Validation Proof - PR394

2026-10-26: exactheadce6cb036 all8CI40248679917SUCCESS, merged56d433c7.
Independent158Catalog/Ruff,1943frontend/lint/build/types/56finalbrowserpass.
All31extensionartifacthashes verified; final3GitHubhashes independentlyUIverified.
Account890c9bfc/tenant262a3a77 existingAustraliaEasttarget confirmed.
APIcr22 digest61c248733b8689df3336449fe1664ccbdb6898580c1ba9e24d2887cd584213b3;
webcr21 digestc4c7ab9d0289936f6e7d5e78896cc53ecfbf9d2dc697816828b2dfe0d02ecb0d.
ExactAPI470sourcehashes/provenance matcharchive. Two backward clock cases reject
atomically; equal/increasing accept; no network/credentials, onlyfakeitemclient.
Retained comparison replay identical10unchanged, advisory/offlineverificationfalse.
Allvalidationchecks completed with no outstandingerrors; promotion still gated
by actual candidate provider parity and healthyready0restartreplica.

### PR394 deployed; bounded owner closure pending

Candidate baseline-ready provider parity/Healthy1ready0restarts passed before
explicit APIr394-56d433c7 promotion100%; r393active0 retained rollback.
Already-built webc4c7ab9d deployed as0000023 Healthy100%,1ready0restarts;
root/config200. Fresh protectedsnapshot confirms config/resources/roles/
profiles/unrelatedapps/sixjobs unchanged. Only obsolete unlabelled0%r389
deactivated before staging; no resize/capacity mutation or rebuild.
Receipt6492d99e5d166c2e40c4aa00142c9a80e7f7ce9d132b0112d4cb57ea20420419
seals21artifacts in sessionfiles/release394. Both deployment notices sent;
UI ACK received and finite actual servedCSS no-injection closure running.
Fabric independent acceptance and both final closure ACKs remain pending.

Both deployment ACKs and bounded Fabric/Catalog independent acceptance received.
Actual served UI no-injection249captures/83states/27URLs/7351measurements PASS,
central10hashes+seal/geometry verified and4visuals inspected. Retain163loading
captures/2unavailableauthorizeddetailroutes/38aborts/paragraph-only assertions;
not exhaustive page/state/provider certification. Finalclosurecb392a02 at
sessionfiles/release394/closure.json; both final notices sent, ACKFINAL pending.
Both explicit ACKFINAL received and persisted separately; finite PR394 release
coordination complete. Broader existing engineering loop remains open.

## Active preparation: PR393 coordinated Catalog preflight/search control

- MODIFY existing AZCLI API/web apps in aiops-dev-rg/AustraliaEast, subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc. No provisioning/IaC/role/config change.
- Five paths in distinct owner commits: Catalog baseline max-items preflight;
  UI existing shared search-control class/test. Exacthead6473a0f0 all8CIpassed.
- Archive final merged source, build API/web once each; do not use dirty plan
  as build input. Existing Dockerfiles/dependency locks and resources unchanged.
- Exact API image: source hashes/provenance, invalid bound before baseline IO/
  credentials/HTTP, retained valid offline replay; no new Catalog/provider read.
- Stage API zero traffic copied from r390, promote only Healthy/ready/0restarts
  and baseline-ready provider parity; retain r390 rollback. Then update web.
- Preserve API4CPU16GiB/web0.5CPU1GiB, registry secret/identity/RBAC, profiles,
  otherapps/sixjobs; snapshot protected hashes before/after. Web Singlemode
  rollback is retained immutable web21 bd8d03dc redeployment.
- Independently96Catalogtests/Ruff and1943web/lint/build/types pass. Owner558
  coupled tests and Edge geometry/negative control evidence retained.
- Notify BOTH owners on deployment and FINAL accepted closure; require ACKs
  at each. Request bounded UI search-control acceptance and Fabric exactimage
  evidence review. No vm1, patch execution or provider/native/scheduler mutation.
- PR393 validation proof populated below; later release sections are historical.

### All validation checks pass - PR393

- [x] Existing CLI auth/target/registry/policy and protected resource review.
  No infrastructure deployment/what-if/new roles/provisioning applies.
- [x] Local96Catalogtests/Ruff/1943frontend/lint/build/types; all8exactheadCI.
- [x] Build API/web once from immutable mergedarchive and qualify exactimage.
- [x] Static role review: only fiveCLI/test/docs/UI paths, no IaC/RBAC changes.
- [x] Protected snapshot, baseline health/readiness and immutable rollback check.

### Section7: Validation Proof - PR393

2026-10-25T16:43Z: CI40211989692 exact6473a0f0 all8SUCCESS;
mergeddea496123d9ea0c3b539672198cc256897dc4b53. Exact archive retained.
Independent96Catalogtests/Ruff and1943frontend/lint/build/types passed.
Fabric independently confirmed3sourcehashes match sealedac20be41; UI2hashes
match691c53e9. No infrastructure/resource/role/config deltas.
User unavailable at confirmation; existing autonomous coordinated-release
authorization and established subscription/AustraliaEast target retained.
2026-10-25: soleACR APIcr20/webcr1y succeeded3m58s/4m3s.
APIsha256:6cf14613c5a299a0c76787c4bb6628868fd7feb5f27a6d48ef3744eefb7b86d9;
websha256:fced3ed8a72506d25d819e1a9c97309a6fe3346ecd277a5a109b338dacede674.
Docker exactAPI networknone/read-only/capdrop qualification passed483source
hashes/provenancedea49612, incompatible1001 preflight forbidsbaselinePath.open/
credentials/http/socket and yields sanitizedconfigurationexit1/emptystdout.
Existing packaged localconfig loaded beforeguards; not config-freeCLI claim.
Retained valid offline replay identical10unchanged/othercounts0; reportbytes
unchanged. Actualunmocked invalid/valid moduleentrypoints matchguardedoutputs.
Fresh protected-state/healthbaseline recorded; existingtarget/RG/region verified,
applicablepoliciesempty. No role/IaC delta, existingregistrysecret/UAI retained.
No outstandingvalidationerrors; release permitted only afterworkflowcompletion.

### PR393 live release HOLD

Candidate aiops-dev-api--r393-dea49612 at0% is AzureHealthy with1ready0restarts.
Capacity limit first required deactivation of only obsolete/unlabelled/0%r388;
r390100% and r389 rollback retained, no profile/resource/config change.
Platform runningState is RunningAtMaxScale (valid), not Running; initial exact
string wait corrected without restart. Actual provider parity still FAILS:
baseline-ready change/vulnerability unavailable; candidate runtime build logs
FabricSqlReadinessError fabric_sql_connectivity_failed, schema/query blocked.
Bounded settling did not resolve; no promotion or web deployment performed.
Servingr390100%/web21 unchanged and protected hashes/roles/profiles/otherapps/
sixjobs equal. No provider publication/repair, newCatalogread or vm1 action.
Holdreceipt b9d863da0b13decd39412640fb92043a9bb1f0a860ef38da08402c1387a0db5c,
27hashes sealed in files/release393. Bothowners notified for HOLD ACKs.
Next gate remains all baseline-ready providers qualified on exactcandidate.
Further read-only diagnosis confirms DNS/TCP1433 connectivity, but SELECT1
fails SQLSTATE42000/error24800: Fabriccapacitycurrentlynotactive. ARM shows
aiopsdevcap7h0ih3/F8 Paused with provisioningSucceeded. No schema defect inferred.
Resuming billable capacity is a protected-state change, not included in image
rollout; ask_user unavailable, so no resume authorized/performed. Both owners
ACKed HOLD; Fabric independently verified27sealedhashes/483source/replay.
Rootcauseaddendum retained separately without rewriting originalHOLDseal.

### PR393 resumed deployment

2026-10-25T22:44Z: user reports Fabric resumed. ARM verifies Active F8/Succeeded;
integrator performed no capacity mutation. Bounded SELECT1 succeeds. Candidate
provider retry backoff clears; every original baseline-ready provider is ready.
Exact API r393 digest6cf14613 Healthy/one ready/zero restarts, staged at0%.
Promoted explicit r393100%, r390active0% rollback retained. Public API provider
parity passes. Updated web using already-built immutable fced3ed8, no rebuild:
web0000022 Healthy/Running100%, one ready/zero restarts. Root/config200.
Protected config/resources/identity/RBAC/profiles/unrelated apps/sixjobs equal
original baseline. New deployment receipt05d0648cc24e9b6abb894380699150ff73a835f1497ae8cdd1e5e06323bfed0e
seals16artifacts separately from original HOLD/addendum. Both owners notified
with exact identities and explicit deployment ACK requested. UI bounded actual
authenticated search-control acceptance and Fabric independent receipt review
remain final gates, followed by final-disposition notifications/ACKs to both.
Both deployment ACKs received; Fabric independently verified receipt/all16hashes
and accepted bounded Catalog/API rollout. UI actual closure attempt is BLOCKED
by expired audit login: sign-in page/account picker, no search captures.
Independently verified report9dd0ab58 and receipt01281525; no deployed UI PASS
claimed. Intended organizational sign-in required before new finite rerun.
No account guessed/auth bypass/rollback/rebuild; final accepted closure pending.
2026-10-25T23:27Z: user-directed retry with restored intended authentication
PASS on actual web22:375/1912/2560 search heights44/40/40 match shared tokens,
radius4px, label/focus retained, empty/query-free input and no horizontaloverflow.
All5ownerartifact hashes+manifest independently verified; mobile/desktop captures
inspected. Disclosed desktop viewport-transition blank/header artifact and one
KBprefetchERR_ABORTED retained; no universal page-shell/provider certification.
Final bounded closure84bd9248a1523c7fc2db07cc045c2451c8447975fb15d47f4394dad399b80bd1
sealed at files/release393/closure.json. Both sessions notified of accepted final
disposition; explicit ACKFINAL requested, broader engineering loops remain open.
Both explicit ACKFINAL received and recorded in final-disposition-acks.json:
UIcall_wMOOX2ex4zLxhSIqT8xBO5HG and Fabriccall_AVXFwvYJRTN1o3VBps5qxwfZ.
Finite PR393 release accepted/closed; broader implementation loops remain open.

## Active preparation: PR392 mobile caption web-only release

- MODIFY existing AZCLI target aiops-dev-web, aiops-dev-rg/AustraliaEast,
  subscription 890c9bfc-d09c-4143-9ce5-465e75e3eecc. No infrastructure generation.
- Exact owner CSS plus browser regression only. Exact-head CI before merge;
  archive merged main and build web once. API r390 and all other apps/six jobs
  are protected runtime, including image, revision, traffic and resources.
- Preserve Single mode, environment/config/secrets/identity/roles/capacity,
  web0.5CPU1GiB; rollback by redeploying web20 immutable f2e3487d image.
- Completed local lint1943unit/build/types/39browser checks; old CSS negative
  control fails at8.78px vs293.55px minimum; restored candidate passes.
- Capture fresh sanitized protected hashes/roles/profiles before mutation;
  deploy immutable web digest only after validation and gates. Verify health,
  replica readiness/restarts, traffic and public root/config/CSS selector.
- Require bounded authenticated owner caption closure and completion ACK.
  No API build/deploy, Catalog/provider calls, patch execution or vm1 actions.
- Validation proof for this release recorded below; earlier proofs are historical.

### All validation checks pass - PR392

- [x] Core CLI authentication/target/policy/registry checks: existing RG,
  AustraliaEast, Single mode and0.5CPU1GiB verified; inherited policies empty.
  No Bicep deployment, provisioning, resource creation or what-if applies.
- [x] Container build from exact merged archive; Dockerfile/context/lock verified.
- [x] Local application lint/unit/build/types/browser positive/negative checks.
- [x] Static roles: no new roles; existing passwordSecretRef and identity retained.
- [x] Exact-head CI green, protected snapshot captured, immutable digest recorded.

### Section7: Validation Proof - PR392

2026-10-25: local lint1943unit/build/types/39browser checks passed. Baseline
negative control reproduced collapsed caption8.78px; restored candidate passes.
Fresh pre-release snapshot protects API runtime/all otherapps/sixjobs and roles/
profiles; web only image allowance. Target/registry/Singlemode/resources verified.
User unavailable at confirmation; existing explicit autonomous coordinated
release-loop authorization and established subscription/region retained.
2026-10-25T16:09Z: CI40209334016 all8 exact465fc7bf checks successful.
Merged6d16f93fe8fe2fa89b41b942bdb35253d5f44d8d; gitarchive exactsource.
`az acr build --registry aiopsdevacr7h0ih3 --image
aiops-web:caption-392-6d16f93f --file Dockerfile .` from archivedweb succeeded
once, runcr1x4m8s, digest
sha256:bd8d03dc0596a5cf685f3e903d40b929185d4871f54f80bdc9f68f4b48ddd205.
No infrastructure/role files differ. Existing registry passwordSecretRef,
identity and captured role hash preserved; no provision/RBAC mutation applies.
Validation actions complete with no errors; deploy remains image-only.
2026-10-25T16:17Z: image-only update completed. Web0000021 Healthy/Running100%,
one ready replica/zero restarts. Root/config/compiledCSS200; compiled mobile
caption selector has display:block;width100%. Optimizer sorts selector groups;
rule membership checked instead of source-order byte substring.
APIhealth/ready200, exactAPIr390/runtime/images unchanged. Protected hashes,
roles/profiles/otherapps/sixjobs identical. Web20 immutable rollback exists.
Deployment receipt a000269f9fead8f2fe049c967801d009b2afc89161399134e3d2c458aa3334e7,
files/release392/receipt.json;13 evidence hashes sealed. UI explicitly ACKed
source/image/deployment notification; bounded authenticated live closure running.
2026-10-25T16:18Z: UI bounded authenticated caption closure PASS at375/1912/2560,
six actual populated queue/CVE captures with20px captions/fullwidth, rows and
accessible names preserved, no horizontaloverflow. All8sealed artifacts
independently verified, report86acb78e/manifestbd04f647. Both UI and Fabric
explicitly ACKed deployment; Fabric has no remaining action. ZeroJSerrors;
known404/3navigationaborts and CVEmobile navigation-transition artifact retained.
PopulatedKB remains fixture-only. Final bounded closure atfiles/release392/
closure.json; no universal UI/provider claim or patch execution.

## Active preparation: advisory Catalog metadata delta API-only #388

- Existing user-directed bounded merge/deploy/review authority; MODIFY azcli
  aiops-dev-api in aiops-dev-rg/AustraliaEast, subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc, tenant
  262a3a77-7d74-4684-8937-897d98d2a17a unchanged.
- Five-path sealed source1ad83889 atbasebc3e7dc9. Optional read-only local full
  baseline, deterministic advisory directmetadata delta, no retirement/schema/
  publisher/scheduler authority. No-baseline report unchanged.
- Exact-head CI required before merge, buildAPIonce from merged archive with
  source metadata. Snapshot fourapps/sixjobs/roles; preserve web387, API
  4CPU16GiB/allconfig/identity/roles/schedules and rollbackr385.
- Stage0% withr385100%; qualify exactimage existingMI/config against retained
  realr385fullreport (explicit priorPTY whitespaceNUL normalization retained).
  Transfer baseline only to bounded ephemeral scratchfile, run finiteCLI,
  remove scratchfile; no persistent/provider/native state writes.
- Promote only if actualCLI comparison success plus settledapplication parity.
  LocalJSON integrity is not authenticated provenance/principalequivalence.
  Missingitems unresolved, retiredempty. Owner review of sealed runtime evidence.

### Section7: Validation Proof - Catalog metadata delta

- Independent552coupledtests/Ruff/diff/frontend lint1930tests pass.
  Source0d608b5b all8exact-headchecks passed; mergedf90788505e362eb44b31258fec5aa964233b5202.
- Exactarchive ACRcr1r succeeded4m6s, solebuild, digest
  f3b52e2e0faf946bd28237ce73f032bcef4a1a00b7ed996bee73cae8840a525f.
  Dockerlinux/amd64 UID10001, metadataf9078850, imports/CLIhelp pass;
  runtimeCatalogsourcehashes saved for archive comparison.
- Fourapps/sixjobs/registryroles snapshot saved, account/tenant unchanged,
  RGpolicyempty. CurrentAPIr385 rollback retained/web387 preserved.
- All validation checks pass:
  - CoreCLI/account/resource/rollback verified existing approvedtarget.
  - Exactarchive Dockerbuild/runtime verified.
  - Existingpolicy/unchangedRBAC verified; no role/serviceedge delta.
  NoIaCdelta, so
  Bicepvalidate/what-if/provisioning inapplicable to image-only update.

### Runtime result - advisory Catalog delta promoted and accepted

- azure-validate workflowcompleted then azure-deploy. Stagedr388-f9078850
  0%/r385100%. api-d4max3nodes blockedstartup; freshtrafficcheck provedr375
  superseded/unreferenced0%. Deactivatedonlyr375 runtime (image retained),
  no capacity/configincrease; r385serving/rollback and r381 retained.
- CandidateHealthy after reclamation; actualMI/config finiteCLI baseline
  comparison ranonce:10directverified/3pages, unchanged10, added/changed/
  unresolved/retired0, remote/localexit0. Baseline realr385fullreport;
  localJSON/hash not authenticatedprovenance/principalequivalence.
- Two websocket404s beforeexecution from oversizedcommands retained;
  chunkedboundedephemeralscratch recovered, filesremovedfinally. Priorreport
  and currentPTY eachonewhitespaceNUL normalization explicitlyretained.
- Exactdelta recomputed independentlyidentical. Settledprovidermap equals
  contemporaneousbaseline, includingexistingfabric_iq/exposure_read_port
  unavailable. Promoted100%; finalready/providers equal.
- Protected4CPU16GiB/allconfig/roles/web387/otherapps/sixjobs equal; sealed
  catalog388-release-receipt.json SHA256
  9d9e6a9a7d8b741a0fb2a1190db6dbc3a49c04c0067621cd8cffbb7056229082.
  Fabricowner requested boundedreview; no scheduler/schema/prefetch acceptance.
- Fabric independently ACCEPTED receipt/all34hashes, integrated/runtimebytes,
  prior/currentreport/delta, exactdigest/traffic/protectedstate/roles and
  providerparity. Finite advisorymetadata comparison release loop complete;
  no additional implementation/cloudexecution requested.

## Active preparation: Investigate full-width actions web-only #387

- Approved existing autonomous merge/deploy/review direction; MODIFY existing
  aiops-dev-web using azcli, same subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  tenant262a3a77-7d74-4684-8937-897d98d2a17a, aiops-dev-rg/Australia East.
- Two sealed paths only: reuse existing wide grid utility and add seven-width
  geometry/order regression. Head64be82b6992e1edd7dd78bbc34a22978079175af.
  No architecture/identity/auth/provider/runtime configuration change.
- Require exact-head CI; merge and build web once from final merged archive
  using existing web/Dockerfile/Entra build defaults. No API rebuild.
- Snapshot four apps/six jobs/roles; preserve serving API385100%/4CPU16GiB,
  all other apps/jobs/config/schedules/secrets/roles. Immutable digest rollout;
  preserve web383 rollback image and configuration.
- Verify platform readiness, /api/config/auth routes, image chunks and public
  route accessibility; send exact revision/digest to UI for authenticated
  375/1912/2560 actions/grid width/order closure. Do not claim provider repair.

### Section 7: Validation Proof - Investigate web-only

- Independently lint:fix/1930unit/build/strictTS/eightInvestigatePlaywright pass.
  Patch SHA256ee7dc7e066f90a98ff9a80c19127ca88f7b04fe6bae2eb22e51d1200c45238aa
  verified; exactly two paths committed, dirty deployment ledger excluded.
- All exact-head64be82b6 CI checks passed; mergedbc3e7dc9158a8e551e9c065b7773f91702dbd89d.
  Eight additional actualEdge cases passed independently.
- ACRcr1p failed17s before image creation: -fDockerfile resolved parent API
  Dockerfile despite web context. Replanned command from exact archivedweb
  directory; cr1q succeeded4m1s, sole produced image
  sha256:94f55de41714c614dbe9ce6b7555927ff3f2e3986dceb41957415b6205e76300.
  No source edits/rebuild of an accepted image. Dockerlinux/amd64 UID10001,
  compiledInvestigate chunk includes wide-panel fix; all static hashes saved.
- Account/tenant/location match approved existing target; four-app/six-job
  protected snapshot and inherited registry roles saved, RGpolicy list empty.
  No IaC/RBAC/service relationship delta. Deployment/live closure pending.
- All validation checks pass:
  - CoreCLI/account/resource/rollback verified in existing approved target.
  - Exact archive Docker build/runtime verified; UID10001 and compiled fix.
  - Existing policy and unchanged role relationships verified. No IaC delta:
  Bicep/ARMvalidate/what-if/provisioning inapplicable to image-only update.

### Runtime result - Investigate rollout and owner closure accepted

- azure-validate completed then azure-deploy invoked. Immutable image updated
  web only toaiops-dev-web--r387-bc3e7dc9; Healthy100%, one ready replica,
  zero restarts. API385100%/allotherapps/sixjobs protected snapshots equal;
  all web protected configuration and inherited registry roles unchanged.
- / and /investigate200; /api/configcorrect APIendpoint. All25referenced
  liveassets SHA256 match exactimage. Initial smokecheck assumed/loginroute;
  repository has none,404expected, corrected test only.
- Exact revision/digest sent to UIowner for requested authenticated
  375/1912/2560 geometry/screenshot closure. No source-only completion claim.
- Owner accepted actual authenticatedEdge15602:21:56–02:22:07Z:
  all3geometry/screenshot reviews pass, actions/grid339/1604/1856wide,
  matchingx/conclusionorder/overflow0; no capturedJS/completedAPI/requesterrors.
  Populatedsubset1recommendation/5situations/7citations/82resources, explicit
  unknownrisk/unmappedowner/unknowngraphage; no broadproviderrecertification.
- Sealedinvestigate387-release-receipt.json SHA256
  ac94502b44455a8f92696a83595a9428b78e1775254e5f7dfcdbb617170dfc83.
  Finite scopedUI loop complete; Phase4/lifecycle gates unchanged.

## Active preparation: Catalog item-scope repair API-only #385 - 2026-10-25

- User directed troubleshooting and repair within the existing finite
  merge/deploy/review authority. Recipe: azcli, MODIFY existing aiops-dev-api
  in aiops-dev-rg, Australia East; subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc and tenant
  262a3a77-7d74-4684-8937-897d98d2a17a unchanged.
- Confirmed live validation cause with existing r381 identity: WorkspaceId-only
  Catalog search includes a valid Workspace entry without item hierarchy.
  Item-only adapter correctly rejects it. Explicit Type ne 'Workspace' filter
  yielded 10 Fabric items across three pages, with every direct item read
  matching item ID/workspace/type. These diagnostics are not image acceptance.
- Six source/test/doc paths in cfb3c7e2: initial item-only scoped filter, numeric
  HTTP failure status without provider bodies, regression tests and runbook.
  Keep token-only pagination, finite bounds, strict response/scope validation,
  atomic failures and advisory item-metadata-only evidence.
- Require all four exact-head CI checks before merge. Build API once from
  final merged main with exact metadata and packaged-source hashes.
- Snapshot four apps/six jobs, registry roles, traffic and rollback revision.
  Preserve existing API 4 CPU/16 GiB, all config/secrets/identity/scale/probes,
  deployed web r383, jobs (including prefetch r381), schedules and other apps.
- Stage new API revision at 0% traffic with r381 receiving 100%. Qualify finite
  CLI in exact image under existing identity/config; no fallback credentials
  or workspace override. Compare readiness to contemporaneous r381.
- Promote only on actual successful CLI metadata verification plus adequate
  application acceptance. Otherwise deactivate candidate and leave traffic
  unchanged. Preserve immutable r381 for rollback; r384 remains inactive.
- No native authoring, capacity/RBAC/config changes, Catalog scheduler or
  publisher wiring, grants, forced jobs or unrelated runtime/provider repairs.

### Section 7: Validation Proof - Catalog item-scope repair

- All validation checks pass:
  - Core validation: existing azcli/account/resource/rollback checks; Bicep
    compile/validate/what-if inapplicable to image-only existing-app update.
  - Docker build: exact merged-source archive; runtime/source identity checks.
  - Azure Policy validation: existing RG assignments, no infrastructure delta.
  - Role verification: unchanged image-pull and workload identity relationships;
    no generated IaC/service edge or permission change.
- Seven intended red regressions reproduced before production changes.
- 353 Fabric tests, global Ruff and required frontend lint:fix/1,930 tests pass.
- All four exact-head cfb3c7e2 checks succeeded in run40147698392.
  PR385 merged2026-10-25T01:26:36Z as19b90bf6fbab45c4b78e5ef26698eca772933ede.
  CI-only source3b1c892f remains separate PR386 and is not part of this API release.
- az account show matches approved subscription/tenant; active revision listing
  confirms r381100%, Healthy. Four-app/six-job protected snapshot and inherited
  registry-role snapshot persisted as catalog385-pre-*. No policy assignments
  at the resource-group scope. No IaC delta; no new role/service relationship.
- Exact merged archive ACR buildcr1n succeeded3m56s, tagr385-19b90bf6,
  digest6554f3d0de282853eaaa2e7ca475247100cc02e3099285ac2c1f46848bae5d13.
  Dockerlinux/amd64 runtimeUID10001, metadata19b90bf6; both Catalog runtime
  SHA256s exactly match archive; actual CLIhelp exits0. No second image build.
  Runtime identity qualification and traffic promotion remain pending.

### Runtime result - Catalog repair qualified and promoted

- 2026-10-25: azure-validate workflow completed; azure-deploy invoked.
  Staged r385-19b90bf6 at0%, preservedr381100%; Healthy/ready replica with
  zero restarts before actual qualification. Initial prestart transportexit3
  found no container and did not invoke CLI; retained separately.
- Actual finite CLI in exact image/existing managed identity returned
  advisory_metadata_verified,10direct-verified items/3pages, localexit0 and
  cluster success. Metadata-only/partial/schema unverified; no permissions,
  scope overrides, scheduler/publisher wiring or prefetch acceptance.
- Settled /ready matches contemporaneousr381: ready except existingfabric_iq
  andexposure_read_port unavailable. Inventory/read_port ready after natural
  startup; no full provider health or populated UI acceptance claimed.
- Promoted100%; finalGET confirmsr385-19b90bf6 traffic100%, readinessready.
  Preserve4CPU16GiB; webr383/otherapps/sixjobs/roles equal preflight.
  Four unchanged secretRefs gainedemptyvalue strings onupdate; removingonly
  those reconstructs exact preflight protected hash. Final nontraffic hash
  equals staged. r381retained for rollback.
- Sealedcatalog385-ci386-release-receipt.json SHA256
  b00bcd43d5634c0d4b4373d3cd9df3ab0d1a359b0a0d4d303c15c1cf580937de
  in sessionfiles; Fabric owner notified for bounded review.
- Separate CI386 mergedc87347a7, all four shards+aggregate green;
  observed backendcriticalpath12m55s vs43m37s (~70%shorter).
  CI-only source not deployed; no API rebuild for CI-only commits.

## Active preparation: Catalog qualification API-only #384 - 2026-10-24

- Existing user-directed finite merge/deploy/review authority; MODIFY azcli
  aiops-dev-api only, same subscription890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  tenant262a3a77-7d74-4684-8937-897d98d2a17a, aiops-dev-rg, Australia East.
- Candidate53360436872deda2699cba6c7dafbb3a5fe2a357, five handoff paths only.
  Bounded advisory direct metadata verification and read-only CLI, no wiring.
- Require all four exact-head CI successes before merge; build API once from
  merged-main archive with source metadata. Includes already-merged speed382
  Docker ownership optimization; independently qualify runtime contents.
- Snapshot four apps/six jobs and roles. Stage new API revision with all traffic
  held on healthy r381; shift only after exact digest Healthy and /ready ready.
  Preserve4CPU/16Gi, env/secrets/identity/scale/probes/auth/ingress.
- Preserve deployed web383 and all six jobs (including prefetchr381), schedules,
  roles/config/native definitions/grounding. No blanket Terraform/setup apply.
- Qualify finite python -m fabric.catalog_cli using exact deployed API revision
  and its existing identity/config via reviewed az containerapp exec. No new
  grants, scope/identity overrides or alternate credential fallback.
- Record CLI actual exit/output separately from API health. 403, unsupported,
  invalid config or malformed metadata is a qualification failure, never empty
  success or permission to escalate. No Catalog scheduler/publisher connection.
- Retain immutable APIr381 revision/image for rollback; preserve prior partial
  prefetch unsafe_content evidence, not a new release-success claim.
- [x] Exact-head CI, merge and final source archive
- [x] Immutable build, packaged source/runtime and existing-role verification
- [x] azure-validate proof and azure-deploy handoff
- [x] Exact-image staging, protected workload comparison and bounded identity
  qualification attempt
- [ ] API traffic promotion (BLOCKED: the Catalog CLI did not succeed)

### Section 7: Validation Proof - Catalog API-only

- Candidate: independently350Fabric tests, globalRuff, frontendlint:fix/
  1930tests and actual CLIhelp/missing-config subprocess passed.
- Both handoff hashes verified; all five integrated files exact tested bytes,
  independently confirmed by Fabric owner integrated-source-review.json.
- PR384 opened after app tracking refreshed; CI pending. Earlier creation
  blocker resolved without CLI workaround. No cloud qualification yet.
- 2026-10-24 18:15:54UTC: all4exact-head53360436checks COMPLETED/SUCCESS;
  merged8ebb83ac30cae231cc5a4236c592f3f9f4dd6c20.
- Exact merged archive built once ACRcr1m18:16:20–18:20:37UTC, Succeeded;
  digest706b465dae07ce64a9eda2794138aecbfb7645f9bf7fbdf9d8d901bc60b67e41.
- Fresh four-app/six-job snapshot/rollback/roles captured. Account unchanged;
  API Multiple mode r381 at100%; webr383 and all jobs remain baseline.
- Dockerlinux/amd64/UID10001; metadata exact8ebb83ac, both changed runtime
  source hashes match archive; imports, ODBC18 and offlineCLIhelp pass.
  Ownership lstat confirms app entries belongUID10001; interpreter symlink
  targets outside /app remain root-owned intentionally. Initial stat assertion
  followed external interpreter link, corrected test only; no rebuild.
- Local ACR auth expired on first pull; az acr login refreshed local credentials,
  retry succeeded, no cloud role or secret change.
- Merged archive coupled Fabric/build/packaging tests completedexit0. Global
  Ruff and frontendlint1930tests passed. Exact-headCI covers full suite/build.
- All validation checks pass: coreCLI/account/resource/rollback, Docker build
  and static/live registry roles, existing RGpolicy. No infra deployment:
  Bicep/ARMwhat-if and azdprovision are inapplicable, no new service edge.

### Runtime result - Catalog promotion BLOCKED

- Staged aiops-dev-api--r384-8ebb83ac exact706b465d image; platform Healthy
  and /ready200 readiness ready. All traffic remained onr381 throughout.
- Application gate did NOT pass: candidate lost warm-provider availability
  (inventory/change/vulnerability unavailable). OneLake404 diagnostic explicitly
  says Fabric capacity517c0d4e-9472-4288-8e61-343060396887currently unavailable;
  ARM confirms aiopsdevcap7h0ih3 F8statePaused, provisioningSucceeded.
- APIr381 serving baseline remains ready with some warm provider instances;
  its ExposureSQLreadiness was already degraded. Do not infer fresh provider
  success from cached readiness or blame scoped Catalog/CSS source.
- Actual direct CLI in exact staged revision/existing identity/config exited1
  with sanitized failure_stage=catalog_verification and no success output.
  CLI does not expose HTTPstatus; no claim it was specifically403 or that
  capacity pause alone explains it. No grants or scope changes.
- First exec wrapper failed Python syntax before invoking CLI due containerapp
  command splitting. Direct python -m invocation recovered transport and yielded
  the real bounded failure above. No successful CLI execution claimed.
- Promotion withheld. Newly stagedr384revision deactivated (not deleted) to
  avoid needless extra replicas; immutable image retained. Servingr381100%,
  web383/alljobs/config unchanged. No capacity resume or forced provider retry:
  outside this image-only scope. Owner review and capacity availability required
  before a newly qualified release attempt.

### Requalification after externally restored capacity - 2026-10-25

- On explicit user "resume", read-only ARM query now reports existing Fabric
  F8 capacity Active (no capacity mutation by this session). Candidate r384
  was activated at 0% traffic and allowed to start before qualification.
- At 2026-10-25 00:28Z, candidate /ready was ready; Fabric IQ and exposure
  read-port reported unavailable because no provider data was published.
  Contemporaneous r381 showed the same two unavailable providers, and its
  earlier Exposure SQL degradation had cleared. This is comparative readiness,
  not proof of Catalog capability or full provider health.
- The bounded CLI was run against exact r384 with the existing workload
  identity/config after startup. Remote exit was 1 with sanitized
  `failure_stage=catalog_verification`, no success output. It does not expose
  HTTP status or cause. The failure persisted while F8 was Active; do not infer
  a specific permission/API error or attribute the earlier result solely to
  capacity state.
- Promotion remains BLOCKED. Candidate r384 was deactivated after the failed
  attempt; verified inactive and Healthy, with immutable image retained.
  Traffic remains 100% on r381. Web r383, six jobs, roles and protected
  non-API workloads match the pre-attempt snapshots. API remains 4 CPU/16 GiB
  with existing identity; its revision template still references the candidate
  image, but no traffic is routed to it. No capacity, RBAC, config, or provider
  changes were made.

## Active release: Health/Twin web-only #383 - 2026-10-24

- Approved scope: existing user-directed merge/deploy/review loop, web only.
  Recipe: azcli, MODIFY existing aiops-dev-web in aiops-dev-rg, Australia East.
  Subscription 890c9bfc-d09c-4143-9ce5-465e75e3eecc; tenant
  262a3a77-7d74-4684-8937-897d98d2a17a. No provisioning.
- Candidate 9e3c4200665b6844243a852ddcbe13c5c43853b8, PR383. Health
  auto-fit and final Twin card full-span with actual-route regressions.
- Require all four exact-head checks completed successfully before merge.
  Build web once from final merged-main archive, linux/amd64, verify immutable
  digest and packaged source metadata. Do not use earlier candidate artifacts.
- Snapshot all apps/jobs and protected configuration before/after. Preserve
  API r381 (4 CPU/16Gi), all jobs, roles, secrets, environment, scale, probes,
  identity, ingress and all non-web applications. No Terraform/setup apply,
  grants, schedules, native authoring, grounding or Catalog wiring.
- Retain web r380 immutable image/revision for rollback. Existing Single mode
  is preserved: Container Apps keeps old revision serving until the new one is
  ready, then automatically shifts traffic. Do not change revision mode.
  Verify exact image,
  Healthy state, endpoint and protected equality; notify UI owner for its
  authenticated 24-capture closure. Report actual failures separately.
- Phase4 traversal/100k/canary and Phase13 lifecycle gates remain open.
- [x] Exact-head CI and merge
- [x] Fresh account/resource/config/rollback checks
- [x] Exact source build and immutable image verification
- [x] azure-validate proof; azure-deploy handoff
- [ ] Web readiness, protected equality and authenticated owner closure

### Section 7: Validation Proof - Health/Twin web-only

- 2026-10-24 17:19 UTC: all four PR383 checks COMPLETED/SUCCESS for exact
  9e3c4200665b6844243a852ddcbe13c5c43853b8; merged358e538b51d9368c8204798ae711984ddbaac101.
- Prepared git archive of merged web; SHA256
  b19b94aa55e5080042659c2e88153b5abf481ed6dcb001a0c5a21f18ae4e2996.
  ACR web build succeeded. Immutable digest
  sha256:eec70d30cda35080b32ef83fd669205ec40dc98a95cbd4a0798ed3dfcba058ca.
  Docker inspect confirms linux/amd64; offline read-only/network-none Node check
  confirms UID10001 and exact packaged Health/Twin CSS selectors.
  First assertion used incorrect guessed selectors; corrected against exact
  merged source and reran successfully. No image or source changes.
- Account tenant/subscription and RG Australia East confirmed. Four-app/six-job
  baseline captured ui383-before.json; rollback/role/policy receipts captured.
- Independently lint:fix,1930 web tests and strict types passed on candidate;
  exact PR frontend build passed; owner73 actual Edge layout cases passed.
- Existing Dockerfile has no packaged revision metadata. Source provenance is
  the exact archive/hash and ACR run receipt; inspect packaged CSS separately.
- All validation checks pass: core CLI/account/target, build verification,
  static/live registry roles and existing policy. Bicep/ARM/azd provision are
  inapplicable to existing-resource image-only azcli release.
- Existing apps UAI AcrPull confirmed; registry retains acr-password binding.
  No policy assignments at applicable RG/inherited scope. No grant needed.

### Applied result - Health/Twin web-only

- Web aiops-dev-web--r383-358e538b Healthy/Running; merged358e538b,
  immutable image eec70d30cda35080b32ef83fd669205ec40dc98a95cbd4a0798ed3dfcba058ca.
  / and /api/config return200; existing Single/latest100% mode preserved.
- Before/after four-app/six-job equality confirms only web image/revision
  changed. APIr3814CPU/16Gi, other apps and all jobs/config unchanged.
- Retained r380 immutable image/revision rollback, not deleted. Single-mode
  platform deactivates the old revision after readiness-gated cutover.
- Sealed ui383-release-receipt.json. UI owner notified with exact source/image/
  endpoint for prepared24authenticated captures. Acceptance pending; endpoint
  success alone is not authenticated route acceptance.
- Catalog five-path source separately committed/pushed53360436 with350Fabric
  tests/Ruff and frontendlint/1930tests passing. PR creation app still reports
  tracked383asopen despite live GitHub MERGED. No CLI creation fallback or
  Catalog cloud change attempted; require refreshed app PR state next turn.

## Active release: merged backend hardening - 2026-10-24

- Approval: user explicitly directed "continue to deploy"; existing target and
  autonomous release authority retained. MODIFY via azcli, no provisioning.
- Source: final origin/main 5915413878886eeed3c3e3b90e0c7332efd02046.
  Build one API image from a clean archive for API and prefetch only.
- Includes bounded discovery iterator consumption, protected maintenance
  baselines and advisory Catalog adapter. Catalog remains unwired; native
  authoring, grounding, schedules and Phase 4 acceptance gates remain unchanged.
- Setup #381 is operator tooling/documentation: do NOT execute setup --apply,
  Terraform apply, publication, inventory sync or authorization promotion.
- Web r380 already deployed and scoped Edge closure passed. No web rebuild.
- Capture all apps/jobs before change; preserve API 4 CPU/16Gi, environment,
  identity, probes, scale, all other applications and jobs. Change only API
  image/revision/traffic and prefetch image while no execution is active.
- Verify immutable build metadata and changed source bytes; run coupled backend
  tests and Ruff from exact archive before build. Require successful main CI.
- Retain API r375 and prior prefetch immutable image for rollback. Verify API
  health/ready/traffic and ordinary next scheduled prefetch execution, never
  force a run or expand provider permissions. Capture protected-field equality.
- recipe.type: azcli. Existing subscription 890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  tenant 262a3a77-7d74-4684-8937-897d98d2a17a, Australia East, aiops-dev-rg.
- No new resources, RBAC changes, deletions, secret/config changes or capacity
  changes. Prior release records below remain historical, not current approval.

### All validation checks pass - merged backend release

- [x] Core validation: CLI/auth, existing resource/region and exact merged CI.
  No infrastructure template deployment; Bicep build/what-if is inapplicable.
- [x] Docker build: locked dependencies, linux/amd64 ACR build, exact metadata
  and packaged changed-source verification.
- [x] Policy: no applicable assignments returned at RG/inherited scope;
  image-only change, no new service edge.
- [x] Roles: inspect existing ACR bindings/roles; do not provision or grant.
- [x] Coupled backend tests and scoped Ruff from exact merged archive.
- [x] Fresh rollback/snapshot and no-active-prefetch guard before mutation.
  Preflight protected snapshots match. Ordinary15:00 run initially Running;
  waited without mutation, then terminal Succeeded and idle guard passed.

### Section 7: Validation Proof - merged backend release

- 2026-10-24 14:42-14:58 UTC: clean Git archive of exact59154138;
  281 coupled tests and 23 scheduler/infra tests passed. Scoped Ruff passed.
  Exact merged PR381 backend/frontend/security/Trivy all COMPLETED/SUCCESS.
- ACR build cr1h Succeeded; immutable image0a879606ec1fbbeccc0cbac13e6034b24f0577db77e43731da9ec22d2e4fc402.
  Docker inspect confirms linux/amd64. build-metadata.json source_revision
  equals5915413878886eeed3c3e3b90e0c7332efd02046; five changed packaged
  runtime files byte-identical to archive. No execution of container during check.
- Live account tenant/subscription match plan, RG Australia East. API baseline
  /health200,4CPU/16Gi; rollback digest e4b41441a749f0cdfee4337abca64fc094063108bf6085c14de9eba28dd0edb0.
  Prefetch rollback aa3aa50ce5c4cc4191ce6708ce583066f3ceadc84b981905ef953fcde44a7257.
- Applicable policy assignment list empty (RG with inherited scope). Static
  main.tf AcrPull bound apps UAI; current registry uses existing secretRef.
  Live AcrPull for apps1701d43c and MCPf1e6d3f7 retained. No new role needed.
- Evidence files backend381-{tests,scheduler-tests,build,pull}.log,
  backend381-{metadata,image,before,api-before,job-before,acr-roles,policy}.json.
- Bicep/ARM validate/what-if, azd initialization and provisioning inapplicable:
  existing-image-only azcli release, no infrastructure or role change.

### Applied and verified - merged backend release

- API aiops-dev-api--r381-59154138 Healthy at100% traffic; /health and /ready
  return200/readiness ready. Image digest0a879606ec1fbbeccc0cbac13e6034b24f0577db77e43731da9ec22d2e4fc402.
  First readiness guard held traffic onr375 while image pulled/activated.
- API4CPU/16Gi and protected configuration unchanged. Webr380 and other2apps,
  other5jobs and ACR role assignments unchanged. Prefetch changed image only.
  Retained healthy immediate rollbackr375 at0%; olderr372 deactivated, not deleted.
- Ordinary prefetch29880910 used exact new digest15:10:00–15:10:51UTC.
  Platform Succeeded, application PARTIAL:1selected/attempted/failed,
  NVD CVE-2026-41305 unsafe_content rejection, generation
  exposure-gold-0967bd7c41e8ce6ce917a9e9. No forced retry or guard relaxation.
  Prior15:00 pod logs cleaned up; cannot attribute rejection to release.
- Sealed files/backend381-release-receipt.json with32evidence hashes, exact
  template comparison and rollback identities. Fabric/UI notified. Native
  publication, grounding and Phase4 gates remain unchanged. Setup not executed.
- Performance evidence: ACR build cr1h14:50:49–14:56:23UTC (5m34s).
  Avoidable orchestration/repeated validation overhead identified; future
  exact-commit evidence reuse, parallel checks/build and guarded automation
  can reduce delay. No safety gate weakened or optimization source patch made.

## Active preparation: Health case normalization and attribution - 2026-10-24

- User-directed autonomous Health fix/release; same confirmed subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc, tenant262a3a77, Australia East,
  aiops-dev-rg/lemonsmoke. Existing Container App MODIFY via narrow azcli.
- Seven reviewed paths only, candidate356f2515 onb11c93e3. Internal fixed
  not-found reason/correlation diagnostics and casefolded subscription prefilter.
  Uniform public404, scope checks and personal retention compatibility preserved.
- Independently162coupledtests/scopedRuff plus frontend lint/1927tests pass.
  Source PR/exact-headCI/merge still required; no production image built yet.
- Baseline Health recovered before fix; historical404cause remains unknown.
  Case bug independently reproduced, not proven historical cause.
- Build API linux/amd64 once from final merged-main archive with exact source
  metadata. Current main also includes373 scheduler diagnostics; API image
  includes this source but NO scheduled-job image/config update is authorized.
- Capture fresh all4apps/6jobs/roles, immutable API rollback digest
  sha256:1bf20fa8e0ebfb5d99797b7f8ab91d9f1587d751a1b4f6ca5f15168a9b7a7cfd.
  Update only API image/revision and explicit100% traffic after readiness.
- Preserve API4CPU/16Gi, all env/secrets/identity/scale/probes/auth/ingress,
  web374/otherapps, all6jobs including corrected prefetchroot/image/schedule,
  roles/Fabric/native/capacity. No blanketapply,grant,jobstart,retry or probes.
- Verify packaged bytes/buildmetadata, exact immutable revision Healthy/
  ready/100%traffic, protected equality, and bounded authenticated ordinary
  Inventory/Health/insight rendering. Local unauthorized404contracts suffice;
  no manufactured unauthorized live requests or force-refresh.
- Rollback only API image and explicit traffic to retained372 revision on
  readiness/auth/semantics failure. Keep source and dirty prior release records.
- Approval: standing user-directed autonomous completion and sole-integrator
  authority; no new resource,subscription,permissions or destructive action.

## Active correction: prefetch dataset root - 2026-10-24

- User-directed autonomous failed-prefetch repair; existing fixed subscription,
  tenant, resource group and region. MODIFY existing job configuration only.
- Exact historical execution template and current prefetch job use/tmp/aiops.
  Exact immutablefe8080a8 image/source257cad reproduces generic failure offline:
  missing Gold pointer raises before discovery tables/providers/cache writes.
  Historical internal exception remains unrecorded, not conclusively attributed.
- Current Terraform already defines canonical root with Fabric enabled; no
  new source patch, image build or blanket Terraform apply justified.
- Existing apps-UAI1701d43c/client5d4d603a confirmed current Contributor on
  exact workspace2c1, complete role-assignment page. Exact canonical Gold
  pointer readable as delegated user, generationexposure-gold-31f61cfb339d9976d9b19c9b.
  This is role/binding qualification, not managed-identity execution proof.
- Before mutation capture current job and executions; refuse active execution
  or unexpected root/image/identity drift. Change ONLY prefetch AIOPS_HOME to
  abfss://2c1fea36-104d-4c26-86db-12e09e432b41@onelake.dfs.fabric.microsoft.com/f995229d-970e-44ec-8af5-df9e25261d19/Files/aiops.
- Preservefe8080a8 image, all other env/secretRefs, identity/resources/command,
  retry/timeout/schedule, all apps/other jobs/permissions/capacity.
- No manual start/retry, write probe or grants. Verify full structural job
  equality except single root and all other app/job equality after correction.
- Rollback only AIOPS_HOME to retained/tmp/aiops if protected drift occurs.
  Next scheduled run must qualify actual pointer/table/cache/checkpoint access;
  role metadata does not prove those operations or close prior runtime gates.

### All validation checks pass - prefetch root correction

- [x] Core: exact fixed CLI target, historical/current template and immutable
  offline reproduction; config-only, no generated template/build/what-if.
- [x] Image: unchanged exact old image, retained source/buildmetadata; no build.
- [x] Policy: existing resource/config-only, no new resource/service edge.
- [x] Role: current exact-principal Contributor and exact canonical binding;
  no permission addition or effective managed-identity write test.

### Section 7: Validation Proof - prefetch root correction

- Retained prefetch-root-{current-job,execution,access-qualification}.json,
  exactfe8080a8 source/buildmetadata and Fabric offline reproduction receipts.
- Current grant/pointer verified24Oct in bounded read-only requests.
- Remaining pre-mutation guard: fresh no-active execution and full snapshot.
- No new code/dependencies; Terraform source correction unnecessary.
- Fresh no-active execution guard passed: all returned statuses terminal.
  Snapshot captured all four apps and six jobs before correction. Current
  schedule is authoritative; do not infer one daily execution from producer's
  unrelated schedule. Preserve existing prefetch recurrence unchanged.

### Applied root correction - 2026-10-24T05:03:45Z

- Prefetch AIOPS_HOME now canonical OneLake/Files/aiops; fresh job GET verifies
  value and ProvisioningSucceeded. Old/tmp/aiops retained as root-only rollback.
- Strict update-response equality initially failed because update response
  omits env values. Fresh GET preserves actual env values; normalized exact
  comparison proves only root changed. An empty value field added to unchanged
  NVD secretRef is serialization-only; reference remains identical.
- All other template/configuration/identity fields unchanged, including exact
  imagefe8080a8, command, resources, limits, retries and*/10cron. All four apps
  and other five jobs equal before snapshot. No grant, image build or manual run.
- Receipt files/prefetch-root-correction-receipt.json seals before/after GET
  and app/job snapshots. Historical cause remains unproven; next automatic
  execution must qualify effective pointer/table/cache/checkpoint operations.

### Scheduled root-repair acceptance - 2026-10-24

- Ordinary executionaiops-dev-exposure-prefetch-29880310 Succeeded:
  05:10:00–05:11:44Z. Stored template proves canonical root, same apps identity
  and same exactfe8080 image; no forced run or retry.
- Two platform-split stdout fragments at05:11:41.446159Z reassembled into one
  valid report: succeeded,100selected/attempted/outcomes,all100succeeded,
  failed_count0,all safe_error_codes empty. Do not parse fragments separately.
- Exact generationexposure-gold-31f61cfb339d9976d9b19c9b matches durable
  enrichment/exposure-items.json checkpoint; record_count100 and persisted
  MSRC/CVE cursors read back after execution. This was read-only verification,
  not a managed-identity write probe or extra provider invocation.
- Sealed files/prefetch-root-runtime-receipt.json binds execution/log/report/
  durable summary hashes. Repair qualified for this execution, not sustained
  reliability or conclusive attribution of the historical internal exception.

## Active preparation: cited evidence/source coverage - 2026-10-23

- User-directed autonomous release continuation; MODIFY existing web Container
  App using azcli, same subscription890c9bfc/tenant262a3a77, Australia East,
  aiops-dev-rg/lemonsmoke. No new resources, credentials, roles or service edges.
- Four-path sealed UI candidate on4d861006; confidence gets its own tone,
  separate explicit source coverage, ready does not imply complete, domain
  aggregate evidence retains precedence. No API/backend/CSS/provider changes.
- Independently1927webtests/lint/build/types and39serialactualEdge cases pass.
- Keep diagnostics373 source-only: do not build/deploy API or scheduled jobs.
- After separate source PR/CI/merge, archive final main and build/push web
  linuxamd64 exactly once with existing corrected public Entra/API build args.
- Before mutation retain exact immutable web rollback digestf18c6b97339567cc251bc90b9e7aa6fbefe5d7430df29af841a63578e33ea34e,
  capture all four apps/six jobs and existing role assignments.
- Update only web image/revision suffix. Preserve API4CPU/16Gi, API image and
  traffic, all jobs including producerfbb773f7, identities, roles, environment,
  probes, ingress, scale, schedules, native definitions, Fabric and capacity.
- No Terraform apply, manual job, refresh or provider probe. Verify new web
  immutable identity, Healthy/ready/100% traffic, auth/config and compiled
  banner markers, protected-state equality and authenticated owner receipt.
- Rollback on failed readiness/auth/semantics to retained web372 digest only.
- Phase4/native/Gold/bracket/provider acceptance and prefetch historical root
  cause remain unqualified. Web release does not activate scheduler diagnostics.

### Preparation proof - source coverage374

- Exact head af4ae017, PR374; CI39996062423 all four checks passed, then
  merged18:22:03Z asb11c93e3c750e8eb9cb3a0ccb5d021acac8dbdf2.
- Original frontend run failed unchanged Network option-loading race; retained
  exact log. Independent81Network/Evidence tests passed. Failed-job-only rerun
  passed; no unrelated Network source edit or CI bypass.
- Exact final-main web archive equals independently validated candidate tree.
  One build/push: aiops-web:r374-b11c93e3 digest
  sha256:93899cdfb2452fb2baf2d82116b9e7d09e8d672e390d7ac7f1ce0972e2bf8f3c.
- Immutable inspect confirmslinuxamd64/exact source label. Network-none,
  read-only image check confirms compiled coverage/auth/wide-layout markers.
  Isolated runtime config200 uses existing lemonsmoke API; helper removed.
- Account subscription/tenant match fixed target; effective policy snapshot
  and all role assignments retained. Four apps/six jobs baseline retained.
- MODIFY/web-image-only: no generated template or Terraform apply. Bicep
  validation/what-if inapplicable, not claimed. No new roles/service edges.
- Remaining validation: fresh preflight equality, existing port3000 and
  revision admission; then guarded web-only update and authenticated closure.

### All validation checks pass - source coverage374

- [x] 1. Core Validation (CLI, auth, build, validate, what-if): CLI/auth and
  fixed target confirmed, exact source image proven. No template deployment:
  Bicep build/validate/what-if are inapplicable, not falsely claimed.
- [x] 2. Docker Build: frozen lockfile, one final-mainlinuxamd64 build/push;
  immutable source label, compiled semantics/auth/layout, config200 smoke pass.
- [x] 3. Azure Policy Validation: effective target policy snapshot empty;
  no resource/config generation; platform revision admission checked on update.
- [x] Static role verification: no new generated IaC, operation or service
  relationship. Existing managed identity/registry refs preserved; source-only
  rendering changes require no additional data-plane roles.
- Fresh coverage-release-preflight.json matches retained before snapshot
  exactly for all apps/jobs; no baseline drift. Port3000 unchanged.

### Section 7: Validation Proof - source coverage374

- Evidence: coverage-release-{merge,web-metadata,before,preflight,roles-before,
  policy}.json, web-build log, independent tests/build/browser logs and sealed
  owner manifest. CI all four checks green at exact source head.
- All checks above have actual evidence; no mutation or live semantic
  acceptance yet. Preserve API/jobs and retained web372 rollback.

### Deployment result - source coverage374

- Web-only immutable image update to aiops-dev-web--r374-b11c93e3 completed;
  Healthy/Provisioned/Running,one ready replica,zero restarts,100%traffic.
- All22freshlivechunks equal immutable image; compiled coverage/confidence,
  auth IDs and preserved wide-layout/control markers confirmed.
- Exact protected web configuration preserved. API and both other apps,
  all six jobs, all retained role assignments unchanged. API remains372;
  producer staysfbb773f7; prefetch diagnostics373 are not deployed.
- Webconfig200 correct lemonsmoke API; devtoken404; Inventory/Network200.
- Existing web registry secret reference preserved; existing UAI AcrPull
  independently confirmed. No azd provision/apply/new role/new resource.
- UI owner received exact revision/image/source/endpoint for bounded live
  InventoryOS/software375/1912/2560 plus shared-surface verification.
- No Fabric/state/source collection/refresh/job/capacity/schedule changes.
  Authenticated semantics remain pending; no whole-UI/provider acceptance.

### Authenticated bounded closure - source coverage374

- UI receipt18:32:36–18:34:08Z, actualEdge156.0.4314.42: nine InventoryOS,
  Software and Twin views375/1912/2560 passed. OS reporting-ready/high
  confidence info; Software unavailable critical plus independent high
  confidence info; Twin incomplete/medium warning. Explanation and source
  warnings/disclosure retained; no inferred provider completeness.
- SoftwareUnknown narrative facts and suppressed unavailable chart preserved.
  All9zero page errors/non-scroller overflow;1668/1920/375canvas and
  767/893/309narrative widths retained.
- Receipt UI files/ui-source-coverage/release374-live/ACCEPTANCE-RECEIPT.md,
  SHA2569968e061e6a2a39c5b0a30356d43b999376d8d9a057de95b21197a8ab78a4e60.
- Initial Health selection timeout was harness-only: not an EvidenceBar
  consumer. Separate renderedHealth5failed/'Resource health was not found'
  and investigation-continuity-unavailable observation routed to Resource
  Health owner. No captured transport/root cause, retry or causal attribution.
- Browser stopped/profile preserved. Ready-empty/incomplete/unknown/no-source
  and aggregate precedence retain local-only evidence when not observed live.
  Scoped banner release complete; no whole-UI/Health/provider acceptance.

### Separate Health read-only triage update

- Resource Health owner correlated five resource-health GETs around18:30:34Z
  with API revisionr372-4d861006: all returned404, while OPTIONS and nearby
  Inventory list GET returned200. Not an API transport outage for those
  requests; no causal link to web-only374 established.
- Exact372handler intentionally collapses several identity/scope/connection
  rejection branches into404not_found. No request-correlated branch evidence
  retained; root cause undetermined. Missing-provider-unavailable response
  path is not the observed response. Earlier OneLake errors uncorrelated.
- No retry/newHealthrequest/code/deploy/cloudmutation. Owner debug checkpoint
  health-runtime-degradation.md is ABANDONED pending per-request branch
  evidence, not fixed/accepted. Banner release acceptance remains scoped.

## Active release: Inventory evidence hardening API/web - 2026-10-23

- Continuing user-directed autonomous integration/release; MODIFY,azcli;
  same existing aiops-dev-rg/lemonsmoke/Australia East/subscription890c9bfc.
- PR372 sourceca874b79 against3358c5f9: ten sealed owner files reviewed and
  byte-matched. Unknown source counts, independent OS/software readiness,
  pre-truncation totals, unavailable chart suppression, existing control styles.
- Independent83backendtests/Ruff,1912webtests/lint/build/types,39serialEdge passed.
  All CI required; current backend check pending. No mutation before pass.
- Build API/web linuxamd64 once from exact final merged main after producer371;
  explicit corrected Entra web args and exact source labels/digests.
- Update only API/web images/suffixes/explicit API traffic. Preserve4CPU/16Gi API,
  all other configs/identities/roles, registry refs, jobs and producerfbb773f7,
  Fabric/capacity/schedules/native definitions. No Terraform apply or manual job.
- Capture fresh baseline/roles and rollback current APIfbb773f7/web1093a0a5.
  Ready/healthy new revision and provenance/auth checks required before success.
- API poolmax3: inspect active revisions before update. Retain serving369 as
  rollback; do not scale/shrink or deactivate an active serving revision.
- Bounded authenticated Inventory narrative/controls/unknown chart closure after
  deployment; no whole-UI/model/provider/producer-runtime acceptance claim.

### Preparation complete - release372

- CI39943277971 all four checks succeeded; backend44m37s. Exact qualified
  headca874b79 merged11:47:59Z as4d86100624addd9f45b69fe30157ae3c69138554.
- Final merged tree differs from candidate only in371's reviewed producer
  digest/test. Combined final-main Inventory/profile tests pass from git archive.
- Single API build/push digest1bf20fa8e0ebfb5d99797b7f8ab91d9f1587d751a1b4f6ca5f15168a9b7a7cfd;
  single web build/push digestf18c6b97339567cc251bc90b9e7aa6fbefe5d7430df29af841a63578e33ea34e.
- Immutable image inspect: linuxamd64, exact main revision label; API build
  metadata matches. Offline unknown/partial/ready-empty facts, producer
  assert_ready and ODBC18 imports pass. Compiled web auth/wide/control markers pass.
- Local API health200 in explicit demo mode with ephemeral token config and
  network-none; web config200 correct lemonsmoke target. All helper containers
  stopped/removed. Production root/auth live preservation remains separately
  required; local demo smoke is not production provider acceptance.
- Fixed subscription/tenant read, effective RGpolicy[], existing UAIroles saved.
  Fresh baseline is after producer image update; six jobs must remain identical.
- Existing API active revisions: main-5ae58a49e zero traffic plus serving369.
  Current D4max3 admits one new4CPU replica without sizing/capacity mutations.

### All validation checks pass - Inventory release372

- [x] 1. Core Validation: Azure CLI/auth/fixed target confirmed; exact final-main
  combined source tests pass. Image-only update generates/applies no template:
  Bicep build/deployment validate/what-if inapplicable, not falsely claimed.
- [x] 2. Docker Build: both images built once from clean final-main archive;
  frozen lockfiles, amd64/source labels, backend metadata and offline semantics;
  compiled auth/layout/controls and isolated runtime smoke pass.
- [x] 3. Azure Policy Validation: effective RGpolicy[]; unchanged existing
  resource configuration; verify platform revision admission after deployment.
- [x] Static Role Verification: narrative aggregates/client styles introduce no
  new operations or service edges. Existing identities, registry refs and
  role assignments preserved; no roles/apply/provisioning required.

### Section 7: Validation Proof - Inventory release372

- Preparation proof above records exact sourceCI/merge, combined final-main
  tests, source-only archive, single builds, immutable digests/provenance and
  corrected compiled authentication. No failed source/image checks remain.
- Offline API semantic contract confirms unavailable/partial Unknown and
  genuinely ready-empty0. Network-none runtime health200 and webconfig200 pass.
  Early smoke harness omitted required runtime/auth inputs; corrected only
  harness to explicit supported demo+ephemeral auth, not application defaults.
- `az account show` matches fixed subscription/tenant; effective RGpolicy[].
  Existing port8080/3000 match; target identity/roles/config remain unchanged.
- Fresh `release372-preflight.json` equals `release372-before.json` for all
  four apps and six jobs after producer cutover. No model/schedule/state changes.
- Evidence: release372-{merge,api-metadata,web-metadata,image-check,policy,
  roles-before,before,preflight}.json and corresponding build/test logs.
- Rollback images remain APIfbb773f7/source66e and web1093a0a5/source3358.
  Producerfbb773f7 is fixed separately and must not follow new API digest.

### Deployment result - release372

- API and web r372-4d861006 Healthy,ready,100% traffic. API traffic moved only
  after both revisions became Healthy; serving369 retained as rollback.
- Production API startup complete and ready200; protected resources401;
  webconfig200 correct lemonsmoke API,devtoken404,Inventory/Network200.
- All live replicas ready with zero restarts. API4CPU/16Gi/80Gi preserved.
- Exact target immutable images verified; all protected configuration of
  four apps, six job hashes and live UAI role assignments unchanged.
- No capacity/schedule/identity/Fabric/native/state mutations. Producer stays
  separately pinnedfbb773f7. Pending normal14:30UTC runtime qualification.
- UI owner requested bounded authenticated375/1912/2560 narrative/control
  closure against actual372; live retained/empty states only if present.

### Bounded authenticated closure - release372

- UI Edge156 receipt12:02:54-12:04:00Z confirms six OS/Software views at
  375/1912/2560: ready OS machine1/group1/supported1 retained independently
  of unavailable logs; both software narrative facts Unknown. Complete
  software counts/absence explicitly unknown; three sampled narrations agree.
- Unavailable notice/three unknown software summaries visible; software
  dashboard absent. Six views no document/content overflow or page errors.
  Canvas1668/1920/375,wide columns767/893+32gap,mobile309 retained.
- Review triggers/mappings,incomplete rows and genuinely ready-empty software
  absent live: retain local regression evidence only; no action/data mutation.
- Receipt SHA256a19e1991e4883bbe3c39477c6fbf9525bfd8f340b72c092fd4568186161c9b22;
  source UI session files/ui-evidence-hardening/release372-live/ACCEPTANCE-RECEIPT.md.
- Existing collection-banner high-confidence versus unavailable/22h-old logs
  remains a separate UX observation; narrative correctly medium. No fresh
  collection/provider/whole-UI/Phase4/model acceptance claimed.
- Producer rollout is complete as an image deployment. Runtime acceptance is
  still deferred to normal14:30UTC recurrence; Fabric owner retains read-only
  evidence follow-up. No manual execution or intent clearing authorized here.

## Previous release: producer graph-refresh safeguards - 2026-10-23

- Continuing the user's autonomous release direction; sole cloud operator.
  MODIFY, recipe.type azcli, fixed aiops-dev-rg/Australia East/subscription
  890c9bfc-d09c-4143-9ce5-465e75e3eecc. No new resources or provisioning.
- Reuse immutable release369 API image digest
  fbb773f73cfe115c2720b9c49a3353fe95b0a7ac24cbaa4621d04aa58d8762f9,
  correctly attributed to source66e066c0. All backend source unchanged at3358c5f9.
  No rebuild or false source relabel. Owner405 coupled tests/Ruff passed.
- Change only inventory-publication job image. Preserve publisher identity,
  all env/secret/config/root bindings, command,2CPU/4Gi,3600timeout,zero retries,
  parallelism/completion1 and daily14:30UTC schedule. Other apps/jobs unchanged.
- Fresh execution listing: no Running/Processing/Pending execution.
  Actual durable state read from connections/graph-refresh/state.json:
  completed/Completed revision4,job2249d461-5ccd-4ba9-ac85-87a27ffbf3a2.
  Initial lookup outside connections returned PathNotFound and was corrected
  from source; that missing path was not interpreted as an empty intent.
- Retain full job snapshot and rollback96bec07e. Never clear intent or mutate
  source/native definitions/pointers. No capacity/schedule/role changes or apply.
- Reconcile only committed dev producer digest through a source PR so a later
  Terraform apply cannot revert the intended image. No blanket apply.
- Candidate image update is deployment evidence only. Leave normal scheduled
  execution in place; do not start an extra manual publication/refresh.
  Scheduled execution and lineage/native/query qualification remain pending.
- Next: independently verify image/import/config preservation, validate workflow,
  then image-only update and readback. Snapshot/intent must be rechecked at cutover.

### All validation checks pass - producer safeguard image
- [x] 1. Core validation: CLI/auth/existing target;421 coupled tests,
  scoped Ruff and Terraform validate/fmt passed. No generated infrastructure or
  apply: deployment validation/what-if are not applicable to image-only update.
- [x] 2. Docker validation: reuse previously built/pushed linuxamd64 immutable
  image; source66e066c0 label correct, backend-equivalent to3358c5f9.
  Independent offline network-none imports/assert_ready/ODBC18 passed.
- [x] 3. Policy validation: no resource/config changes beyond job image;
  same existing environment and permissions. Effective RG policy list empty.
- [x] Static role review: existing publisher identity retained; no new
  operation beyond existing publication/refresh capabilities or role assignment.
- [x] Source: producer digest and release-pin test only; PR371 exact-head
  CI39941502596 all four checks passed; merged9a40626b at11:23:53Z.
  Web lint/1911tests passed.

### Section 7: Validation Proof - producer safeguards 2026-10-23

- Fabric handoff SHA2569e010d3da1ab927ec410a7a4d88b28a10dccaa5187a07391231161e66c991116
  verified; git diff66e066c0..3358c5f9 contains only web/docs.
- Local421 tests passed in ten coupled suites; Terraform validate/fmt/check,
  scoped Ruff, web lint:fix and1911tests passed. Exact release-pin assertion
  deliberately updated from old image to candidate; no behavior test weakened.
- `docker image inspect` confirms amd64/source66e066c0; `docker run --network none
  --read-only` imports producer,assert_ready and ODBC18 successfully.
- `az account show` expected subscription/tenant. Full rollback job snapshot,
  all-app/job baseline, no-active-execution list and completed durable state read.
- Source-root path resolved from publication_cli(config[AIOPS_CONNECTION_HOME]).
  No missing-path default, intent clear, remote refresh/poll or data write.
- Preserve schedule30 14 * * *,2CPU/4Gi,3600seconds,retries0,single completion,
  publisher identity and all configs. Live post-update proof remains pending.
- Fresh11:24:10Z preflight confirms full job unchanged,no nonterminal executions,
  exact completed graph receipt unchanged. Source pin reconciliation merged.

### Producer image deployment result

- Image-only update Succeeded11:25Z; readback pinned fbb773f7/source66e066c0.
- Full normalized job equals snapshot except intended image; all four apps and
  five other jobs exactly unchanged. Publisher role assignments recorded.
- Completed graph receipt revision4/job2249d461 unchanged; no execution started.
- Daily14:30UTC and all protected config retained. Candidate runtime execution
  and scheduled recurrence evidence remain pending; no native/query acceptance.

## Previous release: shared wide-screen web refinement - 2026-10-23

- Mode MODIFY; recipe.type azcli; existing web Container App image only.
- Continuing user's explicit autonomous release direction and latest "continue".
  Same fixed subscription 890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  Australia East, aiops-dev-rg, lemonsmoke. No new target or provisioning.
- PR370 head55d6ddcb merged as3358c5f9389a349b3706b608b9f602c710c6db22.
  Qualified head and final main trees match exactly. Scope: shared CSS,
  browser regressions, related documentation.
- Expand operational canvas; readable Inventory narrative columns; compact
  notices. No API behavior, backend, auth, model or evidence scope changes.
- Source qualification: lint:fix/1911 tests, production build/types,160 distinct
  serial Edge checks passed. Health nested alert correction passed49-scenario
  final confirmation. Exact-head CI39927613800 all four checks passed,
  including full backend pytest44m15s.
- Build web once from clean final merged main, linux/amd64, source label and
  corrected Entra build args. Never reuse old build context/bundle.
- Capture fresh four-app/six-job preservation hashes and roles; retain current
  release369 web digest1a0064733ad9103883fbfde77e14dde05b00e5a82cde2f05e92d43e596f13e08
  for rollback. API fbb773f7 remains unchanged at4CPU/16Gi.
- Update only web image/revision suffix. Preserve API/MCP/jobs/identities/env,
  ingress, scale, schedules, Fabric capacity/configuration and role assignments.
- No Terraform apply, resource creation, producer rollout, Fabric probe or model
  deployment. No new permissions required; existing registry secret refs.
- Verify immutable provenance/auth bundle, new revision health/traffic,
  protected state equality and bounded live wide-screen/mobile geometry.
- This is not whole-UI acceptance or closure of outstanding provider/Phase4 gates.

### All validation checks pass - wide-screen release
- [x] 1. Core Validation (CLI, auth, build, validate, what-if).
  CLI/auth and exact existing target checked. Bicep build/validate/what-if are
  inapplicable: no template is generated or applied for an image-only revision.
- [x] 2. Docker Build (containerized): exact final-main source, lockfile,
  linux/amd64, immutable digest/source label and corrected Entra bundle.
- [x] 3. Azure Policy Validation: effective RG assignments read, no config
  change; verify platform revision admission.
- [x] Static role verification: CSS-only client changes add no service
  operations, new identity edges, or role assignments; existing refs retained.
- [x] Record current source/build/preservation proof separately from release369.

### Section 7: Validation Proof - wide-screen release370

- PR370 exact-head CI39927613800 all green; merge3358c5f9 tree equals qualified
  head55d6ddcb. Clean git archive used, no dirty plan file included.
- `npm run lint:fix && npm test && npm run build && npx tsc --noEmit` passed.
  1911 unit tests;160 distinct serial Edge cases, including ultrawide and mobile.
- Dockerfile uses npm ci; package-lock.json present. One linux/amd64 web build,
  pushed as release370-3358c5f9; immutable digest
  sha256:1093a0a58ffadf9bb274660952b4429e36790f928cdae60a6450eeedd620c776.
- `docker image inspect`: amd64 and exact3358c5f9 source label.
  `docker run --rm` bundle assertions: intended Entra IDs/wide CSS present,
  obsolete auth IDs absent. Local runtime /api/config200 correct lemonsmoke API;
  dev-token404. Bounded smoke container stopped.
- Azure CLI/auth expected subscription/tenant/region; policy assignments[].
  Existing-target image update only: no Bicep/deployment validation/what-if
  applicable because no infrastructure template is generated/applied.
- `release369-snapshot.py` fresh preflight equals before baseline after CI:
  API/MCP apps/six jobs and web protected config/identity/sizing/traffic unchanged.
  Captured seven existing apps-id role assignments; no role change required.
- Existing Entra/auth parameters, port3000 and registry secret refs preserved.
  Prior web digest1a006473 remains available for rollback.
- Evidence files: release370-web-{metadata.json,build.log},
  wide-release-{before,preflight,roles-before,policy,merge,ci} session artifacts.

### Deployment execution and verification - wide-screen release370

- Updated only existing web image/suffix at2026-10-23T09:41Z.
  Revision aiops-dev-web--r370-3358c5f9 is Healthy/Running,100% traffic,
  one ready replica,zero restarts after the stability sample.
- Fresh live Inventory HTML plus22 JS/CSS assets confirm1920px operational
  canvas/narrative layout markers and corrected Entra IDs, old IDs absent.
- Exact protected-state equality: API/MCP apps unchanged, all six jobs unchanged,
  web configuration/identity/resources/registry refs/traffic unchanged.
  Existing seven apps-id role assignments equal before/after.
- API ready200, protected canonical inventory/resources401, web dev-token404.
  The first check used a nonexistent inventory/summary URL and was corrected;
  a404 there was not used as auth acceptance. Optional exposure_read_port and
  fabric_iq remain unavailable as before; no provider acceptance claimed.
- Authenticated live Edge156.0.4314.42 verification passed nine sampled views:
  Inventory/Health/FinOps at1912/2560/375. Canvas1668/1920/375; narrative
  columns767/893 with32px gap, stacked309 mobile; compact Health notices and
  full-width short card descriptions confirmed. No document overflow,
  non-scroller offscreen descendants, or collected page errors.
- Live receipt: UI session files/ui-audit-fixes/release370-live-edge/
  ACCEPTANCE-RECEIPT.md with sealed screenshots and geometry.
  Nested Health error state not live present (covered locally). Whole UI is not
  accepted. Pre-existing Inventory software-zero narrative ambiguity remains
  separate from this layout release and is not claimed resolved.

## Previous release: audited API and web update - 2026-10-23

- Mode: MODIFY; recipe.type: azcli; existing Container Apps only.
- User directed autonomous completion after reviewing merged/not-deployed status.
- Source: main 66e066c020b72eeda09f2258c516f3a5a1d1ae36, identical to
  independently qualified PR369 head 4274a4b4.
- Target: subscription 890c9bfc-d09c-4143-9ce5-465e75e3eecc,
  resource group aiops-dev-rg, Australia East, lemonsmoke environment.
- Build API and web linux/amd64 images once from exact merged source; pin image
  digests and source revision. Explicit corrected Entra web build arguments.
- Update only aiops-dev-api and aiops-dev-web image references. Retain existing
  resources, scale, environment, identities, ingress, secrets and role grants.
- Preserve all MCP apps and jobs, schedules, Fabric configuration/capacity and
  pointers. No Terraform apply, model deployment or producer job rollout.
- Capture existing image digests and normalized protected state before mutation.
- Validate image provenance/auth bundle and health before deployment; deploy API
  then web; verify healthy ready revisions, traffic, auth and protected equality.
- Roll back affected app to its captured prior digest if verification fails.
- Live authenticated UI acceptance remains separate from local fixture checks.
- Existing subscription/location/target are fixed by the continuing release
  request; user explicitly reiterated autonomous completion at 16:11 +08.
  No new environment, provisioning, role assignment or regional move is planned.

### Current release validation proof

Source qualification: 446 backend tests/Ruff, web lint/1911 tests/build/types,
123 local Edge regressions; exact-head CI39917247019 all green.
Historical plans below are not validation of this release.

### All validation checks pass
- [x] Core validation: Azure CLI/auth, exact source archive and existing target.
  Bicep build/validate/what-if are not applicable: no infrastructure template is
  generated or applied, only existing app image updates.
- [x] Docker build: API and web linux/amd64 from exact main; lockfiles present.
- [x] Azure Policy Validation: read current assignments; preserve existing
  configuration and verify resulting revisions satisfy platform admission.
- [x] Static role check: no new data operations or role assignments; Health
  synthesis is page-only and requires no additional Azure permissions.
- [x] Record immutable build proof, rollback images and preservation baseline.

### Section 7: Validation Proof - current release 2026-10-23 08:14-08:22Z

- `az account show`: expected subscription and tenant 262a3a77; RG confirmed
  Australia East. Current resource-group effective policy assignment list empty.
- `git archive 66e066c0`: clean exact merged source, qualified tree equality.
- `docker buildx build --platform linux/amd64 --push`: both builds succeeded.
  API digest fbb773f73cfe115c2720b9c49a3353fe95b0a7ac24cbaa4621d04aa58d8762f9;
  web digest 1a0064733ad9103883fbfde77e14dde05b00e5a82cde2f05e92d43e596f13e08.
- `docker run --rm` API metadata/import check: exact source revision and Health
  insight constant verified. Image architecture amd64; OCI source labels exact.
- `docker run --rm` web bundle check: corrected tenant/client found; old
  ffc83107 / 306c1437 identifiers absent.
- `release369-snapshot.py`: 4 apps and 6 jobs baseline captured; API current
  sizing is 4 CPU / 16 GiB and must remain exact (not historical 8 GiB).
  Exclude only target image/revision suffix from target preservation hashes.
- Rollback API digest 8524ecaf4c472f88adb8c798ba6cfec07449a73cb06993ef1aac2910c936bffa;
  rollback web digest 0b4253c267f1a5465019e4f3b512d36bb7b0a9678b1ea174175195d32d2f1ab3.
- Registry uses existing secret references, not a newly assigned pull identity.
  Existing apps-UAI assignments captured; no new permissions needed or granted.
- Capacity read-only check F8 Active. No Fabric call or capacity write.
- Build logs, metadata, baseline and RBAC evidence are session artifacts prefixed
  `files/release369-`; no secret values printed or added to source.

### Deployment execution and verification

- API and web updated by immutable digest to `--r369-66e066c0`.
- API revision initially capacity-blocked by two obsolete zero-traffic active
  revisions insights341/insights342. Deactivated only those; kept serving
  predecessor main-5ae58a49e as rollback. No workload-profile scale change.
- Both new revisions Healthy/ready. API explicit new revision traffic 100%;
  web latest revision traffic 100%. Both replicas ready, restart count zero.
- API `/ready` 200; web `/api/config` 200 points to existing lemonsmoke API;
  protected inventory unauthenticated 401; web dev-token 404.
- Live fresh Health/Compliance/FinOps script fetches verified corrected Entra
  tenant/client, no old IDs, and expected new source markers.
- Machine equality: all six jobs unchanged; two MCP apps unchanged; API/web
  protected config exact aside from intended image/suffix/API traffic change.
  API retained 4CPU/16Gi. Apps-UAI live role assignment before/after identical.
- Authenticated live Edge receipt: 14 desktop/mobile views confirm sampled
  Health scope narrative/unknown metrics, Compliance label, FinOps count chart,
  Software unavailable state, mobile square triggers and keyboard tab reveal.
  UI owner receipt retained under ui-audit-fixes/postdeploy-edge.
  Whole UI remains not accepted: separate 1912px density issue open;
  Compliance narrative unsettled and other states not sampled.

## Draft: SRE Agent selected-patch live-trigger readiness — 2026-09-15

This is a Phase 3 source-only follow-up. It does not change or satisfy active
Phase 4 gates. Source merge is not live authorization and does not approve a
trigger, RBAC, secret, Terraform state/plan/apply, deployment, canary, or
production action.

### Current sanitized read-only facts

- ARM GET for the existing agent succeeded: provisioning, running, and power
  states are `Succeeded` / `Running` / `Running`; action fallback is
  Review/Low; the action identity is the known SRE UAI; and the exact
  `rg-sredemo-dev` managed resource covers the candidate target prefix.
- The exact thread endpoint is
  `https://sre-agent-sredemo--8b71343d.ba56c019.australiaeast.azuresre.ai`.
  Official trigger examples may use a different origin, so trigger origin and
  thread endpoint are independently pinned.
- Read-only trigger listing returned HTTP 403. Trigger existence, definition,
  mode, grouping, ID, enabled state, and origin remain unverified blockers.
- The API UAI has no agent-scoped custom thread role. The SRE UAI has no exact
  custom VM/Arc patch role at the target scope. Existing unrelated roles do
  not substitute for either contract.
- Key Vault metadata listing returned no
  `sre-agent-http-trigger-url` secret. The live API revision has direct ARM
  mode configured and no SRE Agent environment values.
- The tenant exposes one enabled subscription. All future RBAC captures must
  still use `--all --include-inherited --include-groups` for both identities
  and resolve every observed role definition.

### Source readiness contract

- Canonical operator review body:
  `infra/sre-agent/patch-trigger.v1.json`.
- Exact reviewed skill artifacts:
  `infra/sre-agent/skills/aiops-read-patch-applicability-v1/SKILL.md`
  (`RunAzCliReadCommands` only) and
  `infra/sre-agent/skills/aiops-install-selected-patches-v1/SKILL.md`
  (`RunAzCliWriteCommands` only). Their raw-byte hashes, versions, operations,
  output schemas, and read-then-write order are immutable trigger-envelope
  fields. Read applicability is accepted solely from the fixed read query's
  returned `outcome=applicable` and `blockers=[]`; an empty
  `child_activity_id` from a `softwarePatches` child resource is valid and is
  not an independent blocker when the query has already accepted the evidence.
- Offline-only verifier:
  `scripts/preflight_sre_agent_patch_execution.py`.
- Exact action-role writes are limited to VM/Arc resource read plus
  `installPatches/action`; no Contributor fallback, assessment action, or
  result-read permission is included.
- RBAC bootstrap is independently gated by
  `enable_sre_agent_patch_rbac=false`; dispatch cannot be enabled unless that
  flag is true. The first approved plan/apply contains only the three exact
  role definitions/assignments with execution still false.
- Target scope must be a canonical resource-group-or-narrower ID in the
  selected subscription and must be covered by
  `sre_agent_managed_resources`.
- API UAI thread `write` and thread `read` use separate custom roles at the
  individual agent scope. SRE action UAI patch actions are assigned only at
  the target scope. The split permits read-only verification retention during
  rollback without retaining trigger invocation.
- With the feature flag false, Terraform omits
  `AIOPS_PATCH_EXECUTION`, preserving the application's refusing default.
- Official trigger CRUD lacks a formal request schema and ETag/`If-Match`
  contract. No mutation mode is implemented; trigger creation/update is a
  portal-only human gate.
- Live trigger readiness accepts only the exact observed production GET row,
  validates `agentPrompt`, lowercase `agentMode=review`, `triggerEnabled`,
  default
  response agent, empty thread ID, and exact URL/ID/origin, and rejects aliases
  or unknown fields. The absent service payload schema remains enforced
  against the runtime's locked outgoing envelope and canonical hash.
- The canonical prompt may use the repository-managed Operations API/MCP
  through APIM only for read-only contract-liveness context when a separately
  approved authenticated connector exists. The current
  `sre_agent_pending_mcp_connectors` output does not provision that access, and
  this rollout must not invent or silently create a connector.
- The non-secret reviewed trigger ID is required independently from the secret
  URL. Runtime, normalized trigger evidence, and Key Vault metadata
  attestation must all bind the same exact ID.
- RBAC readiness ingests complete raw `az role assignment list --all
  --include-inherited --include-groups` results for both known principals in every visible
  subscription after `az account list --all --refresh`, plus a distinct
  subscription-scoped `--include-inherited --include-groups` query for parent
  management-group grants. Row counts/digests and raw role-definition captures
  at their subscription or management-group scope are reconciled internally;
  manually reduced assignment arrays are rejected. Effective group grants are evaluated for
  broad roles, while required custom roles must remain direct UAI assignments.

Render and offline verification:

```sh
python3 scripts/preflight_sre_agent_patch_execution.py render

python3 scripts/preflight_sre_agent_patch_execution.py verify \
  --trigger-json /tmp/sre-readiness/trigger.sanitized.json \
  --agent-json /tmp/sre-readiness/agent.sanitized.json \
  --rbac-json /tmp/sre-readiness/rbac.sanitized.json \
  --secret-json /tmp/sre-readiness/secret.sanitized.json \
  --expected-trigger-id '<reviewed-trigger-id>' \
  --expected-trigger-origin 'https://<reviewed-trigger-origin>' \
  --expected-agent-endpoint \
    'https://sre-agent-sredemo--8b71343d.ba56c019.australiaeast.azuresre.ai' \
  --target-prefix \
    '/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev'
```

Offline `build-rbac`/`verify` output is always classified
`offline-evidence-valid` with `fresh live collector required`; it cannot
authorize a trigger or canary. The exact value-free capture commands and
evidence schemas are in `docs/SRE_AGENT_PATCH_EXECUTION.md`.

The mandatory pre-trigger RBAC completeness gate is:

```sh
python3 scripts/preflight_sre_agent_patch_execution.py collect-live-rbac \
  --target-prefix \
    '/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev'
```

The mandatory post-trigger/pre-plan gate is `live-predeploy`; it same-process
collects the agent, exact trigger through a no-redirect authenticated GET,
exact versioned value-free secret metadata, and RBAC
and can emit only `ready-for-approved-enable-plan`. The mandatory pre-canary
gate is `live-canary`; it repeats those reads and also collects the deployed
ACA secret/environment state. Only that same-process fixed-argv collector can emit
`ready-for-approved-trigger-canary`; re-imported JSON never can. Optional
sanitized output is mode `0600`, informational only, contains no raw rows or
secret values, and is written only after successful validation.

### Separately approved live sequence

1. Save and machine-check a distinct RBAC bootstrap plan with
   `enable_sre_agent_patch_rbac=true` and execution false. After separate
   approval applies only the three roles/assignments, immediately require
   `collect-live-rbac=live-rbac-valid`.
2. Obtain named approval for portal trigger creation using the exact rendered
   body/hash, Review mode, New chat thread for each run, and no URL stored
   in source.
3. Separately provision the trigger URL as a Key Vault secret with exact
   trigger-ID, trigger-origin, and canonical-hash metadata tags; provide only
   `https://aiops-dev-kv-g6ludc.vault.azure.net/secrets/sre-agent-http-trigger-url/<version>` to
   Terraform.
4. Run `live-predeploy` immediately after provisioning. Require the exact
   canonical trigger, running/succeeded agent, exact independent endpoints,
   managed-resource coverage, complete refreshed RBAC, exact roles/scopes, and
   enabled value-free versioned secret metadata.
5. Review enablement values for the trigger secret URI, exact trigger ID,
   trigger origin, agent endpoint, exact managed resources, and the
   resource-group-or-narrower target prefix.
6. Require `live-predeploy=ready-for-approved-enable-plan`, then save a
   refresh-enabled Terraform plan. Require **zero RBAC changes** because the
   bootstrap is already applied. Allow only the Key Vault-backed ACA secret
   reference, exact SRE environment, and resulting API revision update.
   Require zero unrelated create/update/destroy/replace actions and zero agent,
   identity, APIM, MCP, ACA-shape, state-import, or other RBAC changes.
7. Separately approve and apply only that saved plan. Require the new API
   revision healthy/ready at 100% traffic and capture its revision, image,
   health evidence, and normalized SRE environment/secret-reference diff.
8. Select one non-critical in-scope running VM or Arc target with
   `rebootPending=false`, one applicable low-risk patch, and the fixed
   `IfRequired` reboot setting. Record the immutable envelope, canonical hash,
   plan hash, trigger ID, deployed API revision, and pre-state. A stopped,
   deallocated, or unknown-power VM is never auto-started; resolve the state
   separately and obtain a fresh assessment before retrying readiness.
9. Run the full `live-canary` collector immediately before the canary and
   require its production-ready verdict. Run exactly one canary only after
   separate approval. Require 202 acceptance,
   one thread ID, explicit approval of exactly one displayed command, terminal
   provider completion, and refreshed evidence reconciliation for every
   selected patch. Pending Review remains provider-active and cannot become
   retryable or supersedable. Agent prose is not proof.

Rollback routes traffic to a prior refusing API revision or separately applies
`enable_sre_agent_patch_execution=false`,
`enable_sre_agent_patch_rbac=false`, with
`retain_sre_agent_thread_verification=true`. This removes trigger write and
patch action authorization while keeping only thread read. Keep polling until
outstanding attempts reconcile, then separately set the retention flag false.
Preserve the trigger thread, execution attempt, approval, audit, and evidence;
never delete them as rollback cleanup.
The full acceptance-evidence checklist is in
`docs/SRE_AGENT_PATCH_EXECUTION.md`.

## Draft: Core Azure SRE Agent import live readiness — 2026-09-14

This draft covers only the existing
`Microsoft.App/agents@2026-01-01` resource at
`/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev/providers/Microsoft.App/agents/sre-agent-sredemo`.
It does not authorize an import, plan, refresh, apply, deployment, role change,
or any Azure write. Phase 4's digest-to-workload traversal, qualified 100k
benchmark, and canary/rollback evidence gates remain unchanged.

### Frozen scope and sanitized read evidence

- Exact Terraform address: `azapi_resource.sre_agent[0]`.
- Management remains default-disabled and `prevent_destroy = true`.
- The 2026-01-01 GET confirmed `australiaeast`, combined system/user-assigned
  identity, system principal `003cb2df-6d1f-4555-ba0b-60766e616f2d`, user
  principal `5b3b9ec4-16fb-4c0f-96fb-16887062f976`, Review/Low action mode,
  Automatic/MicrosoftFoundry model, 10,000 monthly units, unrestricted sandbox
  egress, Stable upgrades, and the four exact managed resources represented by
  `tests/fixtures/sre_agent_resource.sanitized.json`.
- The same GET confirmed `mcpServers = null`; incident connection key,
  Application Insights connection string, and GitHub PAT override were absent.
  Secrets, tags, endpoints, outbound IPs, power/running/provisioning state, and
  other output-only fields are excluded from the sanitized fixture.
- Read-only RBAC listing with `--all --include-inherited` returned zero
  assignments for the unused system identity and eight in-subscription
  assignments for the user identity: Reader, Monitoring Reader, Monitoring
  Contributor, Log Analytics Reader, Container Apps Operator, and Application
  Insights Component Contributor at subscription, resource-group, workspace,
  or component scope. No inherited management-group or other-subscription
  assignment was returned. The selected tenant exposed no other visible
  subscription, so the read API's visible target-tenant coverage is complete.

`scripts/preflight_sre_agent_import.py` is deliberately offline: it only reads
the supplied JSON, rejects output-only fields, ReadOnly action mode, unexpected
identity/settings, incomplete RBAC query coverage, conditional/ambiguous
assignments, and any scope outside the selected subscription. It never invokes
Azure CLI or Terraform and never reads or mutates Terraform state.

### Preflight procedure

1. Use only the approved read-only GET below. It drops tags, output-only
   properties, and every secret-bearing key before the JSON reaches disk:

   ```sh
   SRE_ID='/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev/providers/Microsoft.App/agents/sre-agent-sredemo'
   az rest --method get \
     --url "https://management.azure.com${SRE_ID}?api-version=2026-01-01" \
     --only-show-errors -o json |
     jq 'del(
       .tags,
       .systemData,
       .properties.agentEndpoint,
       .properties.outboundIpAddresses,
       .properties.powerState,
       .properties.provisioningState,
       .properties.runningState,
       .properties.incidentManagementConfiguration.connectionKey,
       .properties.logConfiguration.applicationInsightsConfiguration.connectionString,
       .properties.gitHubConfiguration.patTokenOverride
     ) | {apiVersion:"2026-01-01",resource:.}' \
     > /tmp/sre-agent.resource.sanitized.json
   ```

2. Run:

   ```sh
   python3 scripts/preflight_sre_agent_import.py resource \
     --resource-json /tmp/sre-agent.resource.sanitized.json \
     --tfvars-output infra/terraform/sre-agent.import.tfvars.json
   ```

   The generated file is non-secret and matched by the repository's
   `infra/terraform/*.tfvars.json` ignore rule. It contains exactly:

   ```json
   {
     "enable_sre_agent_management": true,
     "sre_agent_managed_resources": [
       "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev",
       "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev/providers/Microsoft.App/containerapps/ca-api-sredemo-dev",
       "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev/providers/Microsoft.App/containerapps/ca-web-sredemo-dev",
       "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev/providers/microsoft.insights/components/appi-sredemo-dev"
     ]
   }
   ```

3. Build the current selected-tenant RBAC wrapper with read-only list commands:

   ```sh
   SUB='a87a8e64-a52a-4aa8-a760-5e8919d23cd1'
   TENANT='ffc83107-fcc0-4d2e-8798-d582da36505e'
   SMI='003cb2df-6d1f-4555-ba0b-60766e616f2d'
   UAI='5b3b9ec4-16fb-4c0f-96fb-16887062f976'
   az account list --all --query "[?tenantId=='${TENANT}'].id" -o json \
     > /tmp/sre-agent.visible-subscriptions.json
   az role assignment list --subscription "${SUB}" \
     --assignee-object-id "${SMI}" --all --include-inherited \
     --only-show-errors -o json > /tmp/sre-agent.smi-rbac.json
   az role assignment list --subscription "${SUB}" \
     --assignee-object-id "${UAI}" --all --include-inherited \
     --only-show-errors -o json > /tmp/sre-agent.uai-rbac.json
   jq -n --arg subscriptionId "${SUB}" --arg tenantId "${TENANT}" \
     --arg smi "${SMI}" --arg uai "${UAI}" \
     --slurpfile visible /tmp/sre-agent.visible-subscriptions.json \
     --slurpfile smiRows /tmp/sre-agent.smi-rbac.json \
     --slurpfile uaiRows /tmp/sre-agent.uai-rbac.json \
     'def clean: map({
       scope,roleDefinitionName,roleDefinitionId,principalId,principalType,
       condition,conditionVersion
     });
     {
       subscriptionId:$subscriptionId,
       tenantId:$tenantId,
       includeInherited:true,
       visibleTenantSubscriptionIds:$visible[0],
       queriedSubscriptionIds:[$subscriptionId],
       principals:[
         {
           principalId:$smi,
           queries:[{
             subscriptionId:$subscriptionId,
             includeInherited:true,
             assignments:($smiRows[0]|clean)
           }]
         },
         {
           principalId:$uai,
           queries:[{
             subscriptionId:$subscriptionId,
             includeInherited:true,
             assignments:($uaiRows[0]|clean)
           }]
         }
       ]
     }' > /tmp/sre-agent.rbac.sanitized.json
   ```

   If `visibleTenantSubscriptionIds` contains any ID not in
   `queriedSubscriptionIds`, query both principals in that subscription, append
   one `queries[]` entry with `includeInherited: true` to each principal, and
   add the subscription ID to `queriedSubscriptionIds`. The preflight fails
   closed until every principal has exactly one inherited query for every
   visible target-tenant subscription.
   Then run:

   ```sh
   python3 scripts/preflight_sre_agent_import.py rbac \
     --rbac-json /tmp/sre-agent.rbac.sanitized.json
   ```

4. Require both commands to return status `resource-ready` / `rbac-ready`.
   Re-run them against evidence captured immediately before any separately
   approved import. Abort if the live resource, managed-resource set, identity,
   settings, RBAC scope, or visible subscription coverage changed.

### Separately approved future import and acceptance gates

The exact future import command is:

```sh
terraform -chdir=infra/terraform import -input=false \
  -var-file=sre-agent.import.tfvars.json \
  'azapi_resource.sre_agent[0]' \
  '/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev/providers/Microsoft.App/agents/sre-agent-sredemo'
```

The canonical gitignored `infra/terraform/terraform.tfvars` must already carry
the deployment's required private provider variables. The import requires a
separate explicit approval and a zero-live-mutation freeze for every other
operator and pipeline. Immediately afterward, a separately approved
refresh-enabled plan must report ideally zero drift and, at minimum, exactly
zero create, update, destroy, and replace actions for the SRE Agent and zero
action anywhere else. Any non-zero action is an abort; never apply it.

If the binding or subsequent plan is unacceptable, perform no Azure rollback.
After separate state-change approval, remove only the Terraform state binding
with:

```sh
terraform -chdir=infra/terraform state rm \
  'azapi_resource.sre_agent[0]'
```

Preserve the live resource unchanged, delete the local non-secret import tfvars
fragment, and investigate source/evidence offline.

MCP servers, agent/agent-space connectors and connector authentication, APIM
triggers, incident/remediation dispatch, gateway grants, RBAC creation, and all
other integration are explicitly blocked and out of scope. PR #75's CI jobs
failed with zero usable execution evidence; a green CI rerun is a remaining
acceptance gate and is not claimed here.

## Final Consolidated Phase 03.1 Recovery — 2026-09-08

- **Source candidate:** refreshed `main` at
  `1df7010038d3d8d27ee8275e681464462983711a`.
- **Relationship acceptance:** user-approved PR #96 is merged in this source;
  its 500,000-row relationship bound supersedes the older 250,000-row
  acceptance limit below without changing the guarded publication sequence.
- **Included fixes:** MCP runtime dependencies, managed-load-balancer topology
  semantics, lossless Exposure ontology collision merging, deterministic
  Overview test synchronization, and bounded compliance-to-remediation review
  handoff.
- **Source gate:** GitHub Actions run `34240019881` completed successfully for
  backend, frontend, and security against exact SHA
  `8092ab0d25566c1b97cf560951a3e287419a6aa7`.
- **Mode:** Modify existing development validation resources only.
- **Subscription:** `ME-MngEnvMCAP686238-pangj-1`
  (`a87a8e64-a52a-4aa8-a760-5e8919d23cd1`).
- **Location:** `australiaeast`.
- **Provisioning impact:** zero new resources, zero quota increase, zero RBAC
  changes, and no configured compute increase.

### Validation proof

- GitHub Actions run `34240019881` passed backend, frontend, and security for
  exact SHA `8092ab0d25566c1b97cf560951a3e287419a6aa7`.
- Full local backend validation passed with 3,950 tests and Ruff clean; the
  reconstructed live ontology passed at 80,691 entities / 233,212
  relationships with zero validation errors and exact 3/3 registry round-trip.
- `npm --prefix web run build` completed successfully, including lint and
  TypeScript checks.
- Terraform initialization, recursive formatting check, configuration
  validation, state access, template-variable scan, and optional JSON variable
  syntax checks passed.
- Saved pre-build plan
  `/tmp/aiops-final-8092ab0d-prebuild.tfplan` is refresh-enabled and limited to
  the four Container Apps. It contains 0 creates, 0 updates, 0 destroys, and
  0 replacements before recording the new image tag.
- Source and the bounded plan contain no RBAC change. The post-build saved plan
  must still be machine-checked for exactly four in-place Container App image
  updates and no other action before apply.
- 2026-09-09 bounded Delta APPEND recovery: exact source
  `2f29bea327cf89288ce390cbff76a04fbc6985ff` passed 4,046 backend tests,
  scoped Ruff, package sdist/wheel build, revert/reapply causality, and
  independent review. GitHub Actions run `34349454752` could not acquire a
  hosted runner on two attempts: all three jobs ended after two seconds with
  zero steps, zero runner name, and no logs. This is recorded as CI
  infrastructure unavailability, not a test result; no dependency changed.

### Immutable application release

Build all four repositories from a `git archive` of the exact approved source
SHA under one new immutable tag:

1. `aiops-api`
2. `aiops-web`
3. `mcp-server`
4. `azure-mcp`

Generate a refresh-enabled saved Terraform plan limited to:

- `azurerm_container_app.api`
- `azurerm_container_app.web`
- `azurerm_container_app.mcp_server`
- `azurerm_container_app.azure_mcp`

The saved plan must contain exactly zero creates, zero destroys, and zero
replacements. It must not include APIM, Container Apps Jobs, Fabric resources,
roles, identities, capacity, Key Vault, or any other resource. Abort on drift.

After apply, require all four apps to serve the new immutable image digest at
100% healthy traffic. Verify API `/health` and `/ready`, web routes including
the manual-only compliance handoff, MCP startup and `/health`, Azure MCP, APIM
MCP access, and Topology warning-free managed-load-balancer behavior.

### Guarded Exposure Gold initialization

After the application release is healthy:

1. Outside the runner, create the temporary `publication-e8` workload profile
   as E8 with minimum replicas 0 and maximum replicas 1. Do not start a Job or
   mutate the Job template while creating the profile.
2. Confirm `aiops-dev-exposure-publication` has no active or unknown execution,
   then snapshot the normalized workload profile, CPU, memory, timeout, image,
   retry, command/arguments, environment and secret references, identity,
   registry, and trigger configuration.
3. For the current recovery only, run
   `scripts/recover_aum_exposure_publication.py` with the exact immutable image
   plus `--target-workload-profile publication-e8 --target-cpu 8
   --target-memory 64Gi --target-timeout 14400`. The runner permits only the
   reviewed Consumption 4 CPU / 8 GiB / 7,200-second baseline or this explicit
   dedicated profile combination. Direct image-only Job updates are allowed
   only through this recovery workflow; `terraform apply` with
   `deploy_images=false` is prohibited.
4. Machine-diff normalized pre/post templates and require exactly the requested
   temporary workload-profile, CPU, memory, timeout, and image deltas. Command,
   arguments, environment, secret references, identity, registry, manual
   trigger, and zero-retry setting must remain unchanged. Fresh activation is
   mandatory; any replay argument is prohibited.
5. Start exactly one execution with no execution overrides. Keep the Job
   template unchanged for the entire execution. Retry transient execution-show
   failures only with the runner's bounded exponential backoff.
6. Restore nothing until the execution is observed terminal. On operator
   interruption or timeout, stop that exact execution and confirm a terminal
   state before any template write. If terminal state cannot be confirmed,
   leave the snapshot unrestored and escalate; never write a Job template while
   an execution is active or unknown.
7. After every confirmed terminal outcome, restore workload profile, CPU,
   memory, timeout, and image to the snapshot and require the complete normalized
   configuration to match. `--restore-snapshot` must refuse while any execution
   is active or unknown.
8. After restoration, remove the temporary `publication-e8` workload profile.
   Verify non-empty Gold generation/facet evidence plus active server/AUM
   provenance: every relevant fact matches authorized connection `demo`, zero
   active facts use a `legacy:` connection, and no unexpected connection facts
   remain. Also require pointer schema/revision with a non-empty
   `readable_generation_id`, Exposure overview HTTP 200, exact
   digest-to-workload traversal, graph bounds below 100,000 entities / 500,000
   relationships, and no unhealthy serving revision.

Rollback is the prior healthy Container Apps revisions and exact restored Job
template. Pointer-only repair, additional Job starts, Foundry promotion,
Fabric/RBAC changes, and unrelated infrastructure are prohibited.

## Objective

Build and push the API and web container images to Azure Container Registry,
then update the existing Azure Container Apps deployment.

Current repair: restore Foundry specialist narration on every contextual page by
accepting JSON media-type parameters at the existing APIM MCP policy, registering
all eight specialist clients in the API provider runtime, selecting the page's
specialist for narration, and deduplicating safe fallback warnings in the web UI.
APIM must be updated in place and must not be destroyed or replaced.

Current repair: deploy the Network topology live-runtime remediation. Preserve the
populated summary canvas during detail changes; bound/cancel slow full-detail
requests; fix slash-safe hub-dependent lookup and honest zero-dependent responses;
cache network provider results from completion time; hide unattached private-link
candidates by default behind an explicit disclosed toggle; improve connected-node
layout and canvas fit on resize; contain mobile tabs; reduce card-list page size to
20; and remove unsupported Cytoscape wheel sensitivity. This is an API/web
image-only rollout using the existing Container Apps, ACR, identities, APIM, and
Terraform state. No infrastructure, RBAC, secret, region, capacity, or resource
replacement is in scope.

Current repair: deploy the Network message-semantics correction. Remove duplicate
pagination warnings from the global provenance banner while retaining the
contextual incomplete-results callout; distinguish relationship endpoints excluded
by scope from endpoints missing or not projected; qualify topology evidence
confidence and graph observation labels; and rename the inspection-bypass metric
to the finding population it actually counts. This is an API/web image-only
rollout. No infrastructure, sizing, RBAC, APIM, secret, or region change is in
scope.

Current repair: deploy the final Network summary semantics correction. Remove the
page-level ordinary-pagination warning while preserving per-tab range/pagination;
contract an intentionally omitted summary Route node into a direct
RouteTable-to-AzureFirewall next-hop edge; and make exhaustive badge-loader
coverage authoritative for drawer clean state so 83/83 does not remain
unconfirmed solely because the visible list is paged. API/web image update only;
no infrastructure, sizing, RBAC, APIM, or secret changes.

Current follow-up: make the Network specialist answer the operator's actual
question instead of emitting a findings-only JSON inventory, deduplicate
equivalent deterministic evidence, and suppress repeated finding cards when a
Foundry narration is present. APIM remains in place and is not destroyed or
replaced.

Current follow-up: speed up Fabric publish by raising write concurrency
(write_workers 4 -> 12) and publish timeout (120s -> 420s), and add a new
SNAPSHOT_MERGE delta write mode (upsert + when_not_matched_by_source_delete)
for the three largest full-snapshot tables (bronze_resources,
silver_vm_inventory, silver_server_inventory) so most rows are skipped instead
of rewritten while decommissioned resources still disappear correctly. No
Terraform/infra changes; config-value and Python code changes only, deployed
via new container images.

Current follow-up: eliminate intermittent Azure MCP documentation/tool request
timeouts by replacing concurrent FIFO stdio forwarding with a bounded,
single-flight JSON-RPC queue. The bridge must correlate response IDs, preserve
notification ordering and UTF-8 framing, recover from hung/broken child
processes, require reinitialization after restart, reject malformed requests,
and require APIM's gateway assertion on the public ACA backend. Keep one warm
replica and one maximum replica because MCP session state is process-local.

Current follow-up: deploy Phase 13's autonomous ontology foundation using the
existing Terraform workflow. Add one finite scheduled ACA Job with a
non-publisher identity, one code-defined Foundry prompt curator with exactly four
scoped read tools, and one separate least-privilege publisher identity/role.
Validate the four-identity denied-write matrix against the non-production Fabric
target before enabling authoritative publication. No model-derived relationship
may enter the authoritative ontology in this deployment; shadow mode remains
mandatory. Do not replace APIM, the Foundry account/project, Fabric workspace,
or existing Container Apps.

Current repair: deploy the compliance-to-remediation fix and make governed
remediation catalog publication deployment-owned. Commit only the remediation
catalog/bootstrap files, publish an immutable shared image tag, and update the
existing API/web Container Apps in place. After Terraform apply, the repository
deployment wrapper must publish the packaged versioned catalog through the
authenticated application CLI before revision verification. The remediation
provider is required for readiness when enabled, so an absent, one-sided, or
mixed catalog generation must fail closed rather than serve an empty page as
healthy. No new infrastructure, resource deletion/replacement, RBAC expansion,
APIM change, Fabric workspace/lakehouse change, region change, or capacity
change is in scope.

## Workspace

- Mode: MODIFY existing deployed application
- Components: Python Operations API, Next.js web UI
- Target: existing Azure Container Apps environment and registry
- IaC: existing Terraform under `infra/terraform`
- Execution: `infra/scripts/build-and-push.sh`, then Terraform/app revision update

## Azure Context

- Subscription: `ME-MngEnvMCAP686238-pangj-1`
  (`a87a8e64-a52a-4aa8-a760-5e8919d23cd1`)
- Tenant: `ffc83107-fcc0-4d2e-8798-d582da36505e`
- Location: `australiaeast` (existing Terraform deployment default)
- Environment: existing `aiops-dev` resources

## Phase 13 Deployment Scope

- Create the ontology-discovery ACA scheduled Job in the existing Container Apps
  environment with finite execution, `parallelism = 1`, bounded timeout/retry,
  and the existing application image.
- Create distinct coordinator and publisher user-assigned identities plus two
  non-production workspaces on the existing Fabric capacity. Grant coordinator
  Contributor only in the ontology-state workspace and publisher Contributor
  only in the separate RBAC-validation workspace. API and curator receive no
  role in either new workspace.
- Preserve the production `aiops-dev-ops` workspace, Lakehouse, and existing
  API/web Contributor assignment unchanged until Plan 13-10 migrates legacy
  writes.
- Independently enable the code-first Foundry ontology curator without turning
  on the complete specialist candidate-publish flow. The curator uses
  `gpt-5.4-mini` and exactly four scoped read-only Operations MCP tools.
- Create a manual-only, bounded ACA validation Job with only the API,
  coordinator, and publisher UAIs attached. It has no schedule, ingress, or
  AIOps runtime role and runs only `--write-matrix-only`; it never calls Fabric
  role-assignment or Foundry agent-management APIs.
- Run the separate `--control-plane-audit` locally under the existing
  deployment principal. This read-only pass checks live validation-workspace
  role assignments and the deployed curator model, prompt hash, and exact
  four-tool allowlist without granting the publisher or API additional
  management privilege.
- Apply no API/web image rollout in this step unless Terraform proves the
  existing image is insufficient for the scheduled Job command.
- Run `scripts/validate_ontology_publisher_rbac.py --non-production
  --fail-on-missing-evidence --write-matrix-only` through the manual validation
  Job after provisioning. API and coordinator must each be denied actual stage
  and pointer writes, and publisher must complete stage/CAS/rollback cleanup.
  Then run `--control-plane-audit` locally under the deployment principal to
  prove publisher exactly Contributor, all three non-publishers without a
  validation-workspace writer role, and the curator's exact deployed read-only
  definition.
- Keep the live model relationship path in shadow mode. Plan 13-08 remains the
  blocking approval gate before any authoritative publication work.

## Phase 13 Constraints

- Terraform plan must show no APIM, Foundry project/account, Fabric workspace,
  lakehouse, or existing Container App replacement/destruction.
- Managed identities and role assignments must be additive and scope-minimal.
- Deployment and live RBAC validation are serialized with Phase 03.1; the
  deployment lane must be explicitly released before apply.
- The installed `azd` version cannot install the current
  `microsoft.foundry` extension. This deployment therefore uses the repository's
  existing Terraform and `create-foundry-agent.sh` prompt-agent path, not hosted
  agent `azd` deployment.
- Apply only the targets and actions recorded in
  `.planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-07-TARGETED-PLAN.md`.
  The twelve-resource additive baseline is now present in canonical state. The
  current source-only split-validator plan has 0 creates, 1 in-place validation
  Job update, 0 destroys, and 0 output changes. A new immutable ontology image
  will intentionally update both ontology Jobs through
  `ontology_discovery_image_tag`; existing API/web resources and outputs remain
  pinned to `azure-mcp-timeout-20260906-1454`.
- The supplied main `terraform.tfvars` currently contains an older global image
  tag than canonical state. Reconcile that external gitignored value, or
  explicitly preserve `azure-mcp-timeout-20260906-1454`, before applying the
  targeted plan. Never set the global `image_tag` to the Phase 13 Job image.

## Configuration

- Authentication: Entra ID for the API and web UI
- Secrets: Azure Key Vault and managed identity
- Images: existing ACR repositories for API and web
- No destructive resource deletion
- Fabric validation target: existing workspace with a separately named lakehouse
  (`OperationalContext_Validation`) and ontology (`Operational_Context_Graph_Validation`);
  production Fabric items remain untouched.

## Validation Proof

- 2026-09-23: PR #282 merged as
  `cbc2edeb4d99aba35c556b3e64c24d82a1417c3e` from reviewed head
  `848145697db65f7b0e5479004ade0cd68fbadfe9`. The bounded API/web fix
  asserts submitted page evidence as material claims, retains independent
  resource observations under partial coverage, keeps resource-less
  aggregates gated on complete coverage, propagates stable source/claim
  identity, and asks Network synthesis for named resources and evidence-carried
  remediation. Independent validation passed: focused backend 8/8, Ruff,
  `git diff --check`, TypeScript, Network Vitest 91/91, targeted ESLint, and an
  exact-merge production Next.js build. GitHub backend/frontend/security jobs
  executed zero steps because of the known account billing limit.
  Exact-merge ACR builds succeeded: API run `cr115`, digest
  `sha256:e2314f5d7615886458dee099bb2c02538d81370d5581d1b185932a20d6b21c4a`;
  web run `cr114`, digest
  `sha256:de46dff0181ddbe509bfd52847a69d9cacbbc82d9eadc6c7ff87dcf0af40314f`.
  Web revision `aiops-dev-web--pr282-de46dff0-r1` is Healthy/Running at 100%
  traffic; public `/api/config` and `/network` return HTTP 200. API revision
  `aiops-dev-api--pr282-e2314f5d-r1` preserves 4 CPU / 8 GiB, reached
  Healthy/RunningAtMaxScale, passed revision-scoped and public `/health` and
  `/ready` with `readiness=ready` and required Copilot/Exposure providers
  ready, and is at 100% traffic. Initial API scheduling was blocked because
  superseded PR #280 plus PR #281 occupied the `api-d4` two-node maximum;
  after the already-released PR #280 rollback was deactivated, the candidate
  scheduled and passed all gates. PR #281 remains Active/Healthy at 0% as the
  requested rollback pending authenticated PR #282 acceptance.

- 2026-09-23: PR #281 merged as `d159d5eaaca9753f8b2ec851ca8eca5aeaedce84`
  (branch tip `cd82a4142e1672d9ecbc4e0dcbe400da6c57f060`, base merged PR #280
  `5d647ebfa`). Fix pins `_canonical_synthesis_agent()` to the dedicated
  `executive_summary` specialist for both the live `/investigate-context`
  bridge and canonical investigations, replacing prior selection of a
  page/domain specialist (e.g. `aiops-network-agent`) whose response failed
  the executive-synthesis contract and was mis-classified as
  `degraded_reason=unavailable`. Adds sanitized, closed-vocabulary
  `provider_error_class`/`provider_error_reason` telemetry (no raw exception
  text). Independent integrator validation: focused pytest passed 9/9
  (`test_foundry_narration_provider_selection.py`,
  `test_api_copilot_context_bridge.py`,
  `test_foundry_narration_budget_starvation.py`,
  `test_topology_insights_empty_fallback.py`); `ruff check` clean on all
  changed files; `python -m compileall` clean; `git diff --check` clean.
  Confirmed the `test_orchestration_policy.py` collection error (missing
  `reviewed_tree_digest` attribute on `copilot_canary_authorization`)
  reproduces identically on the pre-PR281 baseline (`5d647ebfa`, PR #280 merge
  commit) in an isolated worktree — pre-existing/unrelated environment issue,
  not a regression from this change. No Terraform/RBAC/environment changes
  required; rollout is API-image-only from the exact merge SHA. Per source
  session instruction, the PR #280 revision must remain active (not
  deactivated) until authenticated live verification confirms
  `synthesis.mode=foundry`, non-empty narration, and agent identity with zero
  browser console errors. `terraform -chdir=infra/terraform fmt -check
  -recursive` reported only the pre-existing gitignored `terraform.tfvars`
  (unrelated to this PR, which touches zero `.tf` files);
  `terraform -chdir=infra/terraform validate` passed
  ("Success! The configuration is valid."). `git diff --stat
  5d647ebfa..d159d5eaa -- infra/` is empty, confirming zero Terraform/RBAC
  changes for this API-only rollout.

- 2026-09-23: PR #281 rollout executed. ACR build `cr113` (registry
  `aiopsdevacrg6ludc`, run `az acr build --file Dockerfile --build-arg
  AIOPS_SOURCE_REVISION=d159d5eaaca9753f8b2ec851ca8eca5aeaedce84`) succeeded
  from exact merge SHA `d159d5eaaca9753f8b2ec851ca8eca5aeaedce84`. Image
  `aiopsdevacrg6ludc.azurecr.io/aiops-api@sha256:7975c0911e1652083a440e9721674d81d2a1d3f3162f547406d0e8c9dd9c3cb9`
  (tag `foundry-provider-d159d5ea-20260923T055835Z`). A prior build attempt
  (`cr112`) failed at Dockerfile step 30/35 for a missing
  `AIOPS_SOURCE_REVISION` build-arg; a second attempt failed transiently
  during source upload (DNS resolution to `management.azure.com`), confirmed
  reachable moments later — `cr113` succeeded on retry. Candidate revision
  `aiops-dev-api--pr281-7975c091-r1` created via `az containerapp revision
  copy` preserving 4.0 CPU / 8Gi memory and `AIOPS_SOURCE_REVISION` env var,
  first at 0% traffic. Reached `Healthy`/`RunningAtMaxScale`; revision-scoped
  `/health` and `/ready` both returned HTTP 200 with `readiness: ready` and
  required providers `copilot` and `exposure_query` in state `ready`.
  Promoted to 100% traffic via `az containerapp ingress traffic set`. Per
  explicit rollback instruction, the prior `aiops-dev-api--pr280-5d647ebf-r1`
  revision was **not** deactivated — it remains `Active: True`,
  `HealthState: Healthy`, at 0% traffic as an immediate rollback target.
  Public `/health` and `/ready` on the app FQDN both returned 200
  post-promotion. Awaiting authenticated live Playwright verification of
  `synthesis.mode=foundry`, non-empty narration, and correct executive agent
  identity before any further cleanup of the PR #280 revision.

- 2026-09-22: PR #280 merged as `5d647ebfa3fd6071e2de75c08604d171881eff28`.
  Focused narration-budget and topology fallback tests passed (5 tests), Ruff
  passed for the changed API/test files, Python compileall passed, repository
  Terraform validation passed through
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh validate`, and the
  merged release introduced no Terraform or RBAC changes. The generic Terraform
  preflight was also run against `infra/terraform`; its bare-plan failures were
  limited to expected repository secret-backed variables, and its state/config
  checks passed.

- 2026-09-12: Exposure Copilot CVE grounding release validated from clean commit
  `18d4c63e6`. The focused backend release suite passed 106 tests; the contextual
  Copilot suite passed 30 tests; Ruff, Pylance, and `git diff --check` passed.
  ACR run `crs4` built `aiops-api:copilot-cve-grounding-20260912T023940Z` as
  `linux/amd64` with digest
  `sha256:5d084fe63358a09311e8c279a44e280715d663dabeb632e9febf32ca70d83c41`.
  Terraform/Azure CLI authentication, init, formatting, validation, state, and
  template checks passed. The generic bare plan lacked only this repository's
  secret-backed required variables; the canonical wrapper supplied them and
  produced a machine-checked saved plan with exactly 0 additions, one in-place
  API image-only update, 0 destructions, and no RBAC, identity, secret, web,
  MCP, traffic, or infrastructure change.

- 2026-09-08 18:14 +08:00: Final integrated source SHA
  `b2ba755804b8fa283adcfa39fca2bce1358c6edd` is clean, equals
  `origin/main`, has one worktree and zero open pull requests. GitHub Actions
  run `34214317851` passed backend full pytest/Ruff, frontend tests/lint/build,
  and security scanning.
- 2026-09-08 18:14 +08:00: Azure/Terraform preflight confirmed Terraform and
  Azure CLI availability, authenticated subscription
  `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`, `terraform init`,
  `terraform fmt -check`, `terraform validate`, state access, and template
  variable checks. The generic bare plan reported the repository's expected
  missing secret-backed variables; the canonical
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan` path resolved
  them successfully.
- 2026-09-08 18:14 +08:00: The unrestricted refreshed plan was rejected
  because it contained an unrelated ACA Job replacement, Fabric role creation,
  and Job updates. The bounded pre-build plan
  `/tmp/aiops-final-b2ba7558-prebuild.tfplan` contains exactly **0 additions,
  3 in-place updates, and 0 destructions**: the API and the two existing APIM
  MCP policies. API/web/MCP/Azure MCP image targets are included in the
  bounded scope and will be replanned after the final immutable image tag is
  pushed.
- 2026-09-08 18:14 +08:00: Static RBAC review confirmed all four Container
  Apps identities retain resource-scoped `AcrPull`; the MCP identity retains
  Key Vault Secrets User; the Azure MCP identity retains Reader and Monitoring
  Reader on the onboarded subscription. The bounded deployment introduces no
  RBAC changes.

- 2026-09-08: Final Network summary semantics passed 159 backend tests, 199 web
  tests, 3 Chromium scenarios, TypeScript, ESLint, changed-path Ruff, Next.js
  production build, Python source/wheel build, and revert/reapply causality
  checks. The fixes are committed at `65c0f8bed` and `548b88080`; concurrent
  uncommitted remediation/Fabric/Exposure work is excluded because ACR builds
  from committed HEAD.

- 2026-09-08: Governed remediation catalog deployment preparation passed the
  full Python suite, changed-path Ruff, `git diff --check`, `bash -n
  infra/scripts/deploy.sh`, Python compile, Next.js production build, and wheel
  inspection proving `fabric/catalogs/governed_remediation_catalog.v1.json` is
  packaged. The official Terraform preflight passed installation,
  authentication/subscription selection, init, validate, state access, and
  template checks; its bare plan omitted this repository's secret-backed
  variables. The canonical `AIOPS_ENV_FILE=web/.env.local
  ./infra/scripts/deploy.sh plan` path supplied those variables successfully.
  The unrestricted plan was rejected because it contained six unrelated
  Fabric role additions and unrelated ontology-job updates. A targeted
  `azurerm_container_app.api`/`azurerm_container_app.web` plan completed with
  zero mutating resources at the currently deployed tag, zero destruction, and
  no Terraform/RBAC source changes. Deployment remains constrained to those
  two existing Container Apps plus the post-apply authenticated catalog
  publication command.
- 2026-09-08: Network message-semantics remediation passed 8/8 focused backend
  boundary tests, 43/43 focused frontend tests, 275/275 adjacent backend tests,
  59/59 applicable frontend import-graph tests, TypeScript, changed-path Ruff,
  ESLint, and `git diff --check`. Revert/reapply testing proved the regressions
  fail without the implementation and pass with it. One unrelated full-web
  failure belongs to concurrently modified Compliance/services code and is
  excluded from this image build because ACR archives committed HEAD only.
- 2026-09-08: Message-semantics deployment validation completed for tag
  `network-messages-20260908-1425`. The targeted Terraform plan contains
  exactly **0 additions, 2 in-place API/web image updates, and 0 destructions**,
  with API sizing pinned to the current 2 vCPU / 4Gi. Python compile and the
  Next.js production build passed. No Terraform or RBAC file changed.
- 2026-09-08: Deployed `network-messages-20260908-1425` to API revision
  `aiops-dev-api--0000261` and web revision `aiops-dev-web--0000209`, both
  healthy and serving the new tag. Terraform applied **0 additions, 2 in-place
  image updates, and 0 destructions**. API `/health` and `/ready` and web
  `/network` returned HTTP 200. Authenticated Playwright confirmed the global
  provenance banner no longer repeats pagination warnings; the contextual
  incomplete-results callout remains; confidence is labeled
  `Topology evidence · high confidence`; relationship loss says
  `missing or not projected in this topology`; and the metric reads
  `Inspection bypass findings` with subnet-route/public-IP detail.

- 2026-09-08: Network topology live-runtime repair completed locally. Focused
  backend tests passed (150), focused web tests passed (189), full backend and
  web suites passed (web: 578), real-Chromium local Playwright acceptance passed
  10 tests with one deployment-gated live test skipped, and TypeScript, ESLint,
  changed-path Ruff, and the Next.js production build passed. The remaining
  validation is Azure plan review plus deployed authenticated Playwright against
  the existing `aiops-dev` API/web Container Apps. The deployment must remain
  image-only with zero infrastructure creates, deletes, replacements, RBAC
  changes, or APIM changes.
- 2026-09-08: Azure deployment validation rerun for the Network repair.
  The official Terraform preflight passed Terraform/Azure CLI installation,
  subscription selection/authentication, init, fmt, validate, state access, and
  template-variable checks; its bare plan failed only because this repository
  requires secret-backed variables. The canonical repository wrapper was then
  used with those variables. The unrestricted plan was rejected because it
  exposed four unrelated Fabric role-assignment deletions and a provider preview
  error. A targeted recovery plan for `azurerm_container_app.api` and
  `azurerm_container_app.web`, with digest overrides cleared, passed with exactly
  **0 additions, 2 in-place image changes, and 0 destructions**. No Terraform or
  RBAC file changed. `python3 -m compileall -q src` and `cd web && npm run build`
  passed. Target subscription:
  `ME-MngEnvMCAP686238-pangj-1`
  (`a87a8e64-a52a-4aa8-a760-5e8919d23cd1`), location `australiaeast`.
- 2026-09-08: Final Network remediation deployment completed. API revision
  `aiops-dev-api--0000258` serves
  `aiops-api:network-topology-final-20260908-0440`; web revision
  `aiops-dev-web--0000208` serves
  `aiops-web:network-topology-fix2-20260908-0320`. Both are healthy at 100%
  traffic; API `/health` and `/ready` and web `/network` return HTTP 200.
  The definitive authenticated Chromium suite passed **10/10** in 47.4 seconds,
  including retained canvas/cancel, server handler p95 <1,000 ms, end-to-end
  HTTP p95 <3,000 ms, hub-dependent 200 behavior, responsive repaint,
  candidate disclosure, >55% canvas utilization, mobile tab containment,
  20-card gap pagination, and console cleanliness.

- 2026-09-05: Built and pushed immutable release
  `remediation-final-20260905-0035`; unchanged `azure-mcp` content was retagged
  from the deployed digest after Azure CLI source packaging encountered
  another worktree's fsmonitor socket. Terraform applied 0 additions, 4
  in-place image updates, and 0 destructions. All four Container Apps serve the
  release; API revision `aiops-dev-api--0000225` and web revision
  `aiops-dev-web--0000183` are healthy. API `/health` and `/ready`, web `/`,
  `/api/config`, and `/remediation` returned HTTP 200. Live Update Manager
  operation `ec3f3b9c-f775-4749-92ad-ed16305837c6` reports `Succeeded`,
  `installedPatchCount=1`, `failedPatchCount=0`, `pendingPatchCount=0`, and
  `rebootStatus=NotNeeded`.
- 2026-09-05: Remediation E2E completion fixes validated with
  `uv run pytest tests/test_remediation_execution_verifier.py
  tests/test_remediation_execution_retry.py` (36 passed), targeted remediation
  web tests (47 passed), Ruff, Next.js ESLint, and the production web build.
  `terraform -chdir=infra/terraform fmt -check`, `terraform validate`,
  `python3 -m compileall -q src`, and the canonical
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` all passed; Terraform reported no infrastructure
  changes. Subscription policy assignments were reviewed and this image-only
  update does not change RBAC, policy, region, or resource topology.
- 2026-09-04: Deployed `fabric-unbounded-20260904-0210` to all four ACA apps.
  With Fabric capacity `aiopsdevcapg6ludc` active (F4), an authenticated
  connection-scoped sync completed successfully at `2026-09-04T02:56:01Z`:
  407/407 Fabric tables written, 12,605 records, `sync.status=succeeded`, and
  `health.status=healthy`. `publish_timeout_seconds=0` is now explicitly
  supported to leave the background Fabric publish unbounded while the
  hundreds-of-tables workload is investigated.
- 2026-09-04: Pending Delta-log retry fix validated with
  `python3 -m pytest tests/test_delta_tables.py tests/test_fabric_sync_service.py
  tests/test_incremental_sync.py -q` (40 tests passed), `python3 -m compileall -q src`,
  and `cd web && npm run build` (passed). The canonical Terraform wrapper
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan -refresh=false -lock=false`
  reported no infrastructure changes. No Terraform files or RBAC assignments changed.
- 2026-09-04: Fabric empty-table publish optimization validated with focused
  Fabric sync tests and lint. Repository canonical
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` completed with no infrastructure changes.
  `python3 -m compileall -q src` and `cd web && npm run build` passed.
  Static RBAC review confirmed no Terraform role-assignment changes.
- 2026-09-03 (Fabric publish speed-up, commit 003fe81e): `terraform -chdir=infra/terraform
  fmt -check` passed. `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` passed with no infrastructure changes (config-only +
  Python code change, no Terraform diff). `python3 -m compileall -q src` passed.
  `python3 -m pytest tests/test_delta_tables.py tests/test_fabric_sync_service.py
  tests/test_incremental_sync.py -q` passed (39 tests, including 3 new tests covering
  the new SNAPSHOT_MERGE write mode). `cd web && npm run build` completed successfully.
  Static RBAC review: no Terraform/RBAC changes in this commit, so the shared
  container-app identity's existing `AcrPull`, Key Vault, Foundry, Fabric, and VM
  roles are unaffected.
- 2026-09-03: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` passed with no infrastructure changes. `cd web &&
  npm run build` completed successfully, and `python3 -m compileall -q src` passed.
  Static RBAC review confirmed the shared container-app identity has scoped
  `AcrPull`, Key Vault Secrets Officer, Virtual Machine Contributor, Defender
  configuration, Foundry Agent Consumer, and Foundry Project Runtime User roles;
  the MCP identities have scoped Reader, Monitoring Reader, Key Vault Secrets
  User, and AcrPull roles.
- 2026-09-03: Built and pushed API, web, MCP server, and Azure MCP images with
  tag `fabric-sync-speedup-20260903-2246` (commit 003fe81e). Terraform applied
  0 additions, 6 changes, 0 destructions (image-tag updates only, same as prior
  deploys). All four Container Apps reached the new tag. API `/health` and
  `/ready`, web `/` and `/api/config` returned HTTP 200. No RBAC/role changes
  in this deploy (terraform plan showed no role-assignment diffs), so no
  additional live role verification was required beyond the prior confirmed
  baseline.
- 2026-09-03: Built and pushed API, web, MCP server, and Azure MCP images with
  tag `sync-progress-20260903-1235`. Terraform applied 0 additions, 6 changes,
  and 0 destructions. All four Container Apps are serving the new tag. API
  `/health` and `/ready`, web `/`, and web `/api/config` returned HTTP 200.
  Live RBAC verification confirmed the shared app identity's ACR, Key Vault,
  Foundry, Fabric, and VM roles.
- 2026-09-03: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh
  plan -refresh=false -lock=false` passed with no infrastructure changes.
  `./infra/scripts/build-and-push.sh remediation-card-overflow-20260903-0029`
  built and pushed the API and web deployment images (plus the required
  supporting images) successfully.
- 2026-09-03: Terraform apply completed with 0 additions, 6 changes, and
  0 destructions. API revision `aiops-dev-api--0000197` and web revision
  `aiops-dev-web--0000163` are healthy, running, and serving 100% traffic
  for the new image tag. API `/health` and `/ready`, web `/`, `/api/config`,
  and `/remediation` returned HTTP 200. Live RBAC verification confirmed the
  shared identity's ACR, Key Vault, Foundry, Fabric, and VM roles.
- 2026-09-02: `terraform -chdir=infra/terraform fmt -check` and targeted
  onboarding/API tests passed after constraining `api_max_replicas` to 1;
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` showed 0 additions, 1 in-place update, and
  0 destructions. The Next.js production build completed successfully.
- 2026-09-02: Static Terraform RBAC review confirmed the existing `AcrPull`,
  Key Vault, Fabric Reader, and Foundry roles remain unchanged.
- 2026-09-02: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` passed with no infrastructure changes. The generic
  validator's bare `terraform plan` was not applicable because this repository
  supplies required secret-backed variables through `deploy.sh`.
- 2026-09-02: `cd web && npm run build` passed; the `/remediation` route compiled
  successfully.
- 2026-09-02: Static Terraform RBAC review confirmed `AcrPull`, Key Vault access,
  and Foundry runtime roles remain assigned without destructive changes.
- 2026-09-02: Built and pushed API, web, MCP server, and Azure MCP images with
  tag `remediation-handoff-20260902-1435`; Terraform applied 0 additions, 6
  changes, and 0 destructions. All four Container Apps serve the new tag.
- 2026-09-02: Live verification returned HTTP 200 for the deployed
  `/remediation` page and API `/health`; the web revision reached `Running`
  with 100% traffic. Live RBAC verification confirmed the shared identity's
  ACR, Key Vault, and Foundry roles.

- 2026-08-30: Diagnosed contextual agent failures from Log Analytics:
  Foundry tool enumeration received APIM HTTP 415 because the MCP policy
  required an exact `application/json` header and rejected compatible media
  types with parameters.
- 2026-08-30: `.venv/bin/python -m ruff check src tests` passed.
- 2026-08-30: Full backend `pytest` suite passed.
- 2026-08-30: `npm run lint`, all 157 Vitest tests, and `npm run build`
  passed under `web/`.
- 2026-08-30: `terraform -chdir=infra/terraform fmt -check` and `validate`
  passed after formatting `variables.tf`.
- 2026-08-30: The generic Terraform preflight could not run its bare `plan`
  because this repository intentionally supplies required secret-backed inputs
  through `deploy.sh`. The canonical
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan` passed with
  the current image tag: 0 additions, 2 in-place APIM policy updates, and
  0 destructions. `azurerm_api_management.main` is unchanged.
- 2026-08-30: Foundry access roles remain least-privileged and assigned to the
  shared app identity: `Foundry Agent Consumer` plus
  `Foundry Project Runtime User`; deployment management remains separately
  assigned to the deployer.
- 2026-08-30: Network-response follow-up passed `ruff check src tests`, the
  complete backend suite (1,655 tests), frontend lint, all 158 Vitest tests,
  the Next.js production build, Terraform format check, and Terraform
  validation.
- 2026-09-02: Authenticated Terraform preflight passed subscription selection,
  Azure authentication, init, fmt check, validate, plan, state, template
  variable scan, and required variable validation. The Next.js production
  build completed successfully.
- 2026-08-30: Canonical `./infra/scripts/deploy.sh plan` for the Network
  response follow-up contains no APIM resource destruction or replacement.
  The only replacement is the non-resource `terraform_data.foundry_agent`
  provisioner trigger needed to publish updated Foundry agent instructions.
- 2026-08-30: Built and pushed API/web tag
  `network-direct-answer-20260830-1625`, then deployed it with 100% traffic on
  API revision `aiops-dev-api--0000128` and web revision
  `aiops-dev-web--0000095`. Terraform reported no Azure resource destruction;
  the one destroyed/recreated object was the expected local
  `terraform_data.foundry_agent` trigger.
- 2026-08-30: Live API `/health` and `/ready`, web `/`, and web `/api/config`
  returned HTTP 200. A direct live invocation of `aiops-network-agent` for
  `Can UAT reach PROD?` led with a concrete answer, cited topology evidence,
  and stated the unresolved UAT/PROD mapping instead of returning a generic
  findings JSON payload. Current API logs contain no MCP 415,
  `tool_user_error`, or Foundry contextual narration failure.
- 2026-08-30: Live RBAC verification confirmed app identity
  `2c367602-bb4f-4868-8dbb-7f4ca117a719` retains `AcrPull`,
  `Foundry Agent Consumer`, and `Foundry Project Runtime User`.
- 2026-08-22: `terraform -chdir=infra/terraform fmt -check` passed.
- 2026-08-22: `terraform -chdir=infra/terraform validate` passed.
- 2026-08-30: Fixed subscription-sync "Network request failed" bug — replaced
  `@app.middleware("http")` (Starlette `BaseHTTPMiddleware`) with pure ASGI
  `_ObserveMiddleware` in `src/api/app.py` to stop already-handled exceptions
  from re-raising and dropping the connection after a valid response was sent
  (commit `a35c1ca6`). `pytest tests/ -q -k "api or connection"` passed.
  Built/pushed `main-syncfix-20260830-1509` (api+web), deployed via
  `deploy.sh apply -auto-approve`; both apps serving the new tag. Post-deploy
  curl smoke test: `/health` 200, `/api/v1/subscription-connections/<id>/health`
  and `.../sync` for an unregistered id return clean `401` (auth-required),
  not a dropped connection.
- 2026-08-30: Fixed compliance page evidence panel still squashing labels
  into 1-char-per-line columns. Root cause: `.structured-data-nested` kept
  `container-type: inline-size` (re-entering the 420px column breakpoint
  inside a narrow parent cell) and `.compliance-detail dl` was a bare
  descendant selector matching every nested `<dl>`, both fighting the
  earlier ac41fe5e stacking fix. Set nested evidence `container-type:
  normal` (always stacks) and scoped the plain violation field list to a
  new `.compliance-fact-list` class (commit `637fad29`). Verified with a
  static HTML harness reproducing the real evidence markup/CSS (not just
  computed-style checks, which looked correct while the rendered layout
  was still broken from a cache-stale reload) — labels now render stacked
  above values at narrow widths. `npx vitest run` (156/156) and
  `npx eslint src/app/compliance/page.tsx` passed. Built/pushed
  `main-compliance-css-20260830-1548` (api+web), deployed via
  `deploy.sh apply -auto-approve`; both apps serving the new tag.
- 2026-08-22: Azure CLI account context resolved to subscription
  `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`.
- 2026-08-22: Terraform state resolved registry
  `aiopsdevacrg6ludc.azurecr.io`.
- 2026-08-27: `terraform fmt infra/terraform/terraform.tfvars` completed, correcting the
  formatting-only preflight finding.
- 2026-08-27: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` passed with two image updates and no resource creation or
  destruction.
- 2026-08-27: `IMAGE_TAG=validation-20260827-1928 ./infra/scripts/build-and-push.sh`
  passed; API and web images were pushed to ACR. Web digest:
  `sha256:58d968dda5d4824d210ac93c77c5a177a4f110e4957317dcfc9956f6e52eea6c`.
- 2026-08-27: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh apply
  -auto-approve -var deploy_images=true -var image_tag=validation-20260827-1928`
  passed with 0 additions, 2 updates, and 0 destructions.
- 2026-08-27: ACA revisions reached `Succeeded`; API revision `aiops-dev-api--0000073`
  and web revision `aiops-dev-web--0000060` serve the validation tag.
- 2026-08-27: API `/health` and `/ready`, web `/api/config`, and web `/` returned
  successfully over HTTPS.
- 2026-08-28: New API/onboarding extraction changes require a fresh image build and
  ACA revision rollout; validation will use the separate Fabric lakehouse target.
- 2026-08-28: `AIOPS_BUILD_MODE=local ./infra/scripts/build-and-push.sh` built and
  pushed the API image; the web image was built natively by ACR Task `cr4j` after
  the local Apple Silicon npm build hit the known emulation failure. Web build
  completed `next build` successfully and pushed tag
  `api-onboarding-validation-20260828-0034`.
- 2026-08-28: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` produced an image-only plan: 0 additions, 2 updates,
  and 0 destructions.
- 2026-08-28: `./infra/scripts/deploy.sh apply -refresh=false -lock=false
  -auto-approve -var deploy_images=true -var image_tag=api-onboarding-validation-20260828-0034`
  completed with 0 additions, 2 updates, and 0 destructions. API revision
  `aiops-dev-api--0000074` received 100% traffic; web revision
  `aiops-dev-web--0000061` is healthy with 100% traffic.
- 2026-08-28: Deployed API `/health` and `/ready` returned HTTP 200; deployed
  web `/api/config` returned the API base URL successfully.
- 2026-08-30: Merged PR #5 (CI hardening: ruff import/lint fixes, backend test
  fixes, `/investigate` Suspense boundary fix) to `main`; validating the merged
  `main` build (commit `e76c23e4`) end to end.
- 2026-08-30: `set -a; source web/.env.local; set +a; IMAGE_TAG=main-validation-20260830-1430
  ./infra/scripts/build-and-push.sh` built and pushed both images. API digest
  `sha256:60115010f1bad754670bd3326511efbaa50c31bb3006304d31ac044647be57e7`; web
  digest `sha256:2a0c7d91fb114cef4800ee861c50fcb8ec1f0fae5bd81c751d20695e40d711e4`.
- 2026-08-30: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` produced an image-only plan: 0 additions, 4
  changes, 0 destructions.
- 2026-08-30: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh apply
  -auto-approve -var deploy_images=true -var image_tag=main-validation-20260830-1430`
  completed with 0 additions, 5 changed, 0 destroyed. Both `aiops-dev-api` and
  `aiops-dev-web` revisions reached `Succeeded` and served
  `main-validation-20260830-1430` at 100% traffic.
- 2026-08-30: Deployed API `/health` and `/ready` returned HTTP 200; deployed
  web `/` and `/api/config` returned HTTP 200.

## All validation checks pass

### Bronze/Silver patch release proof — 2026-09-11

- Affected backend suites passed, including Fabric SQL, cursor, temporal
  projection, runtime, Delta APPEND, Fabric sync, ontology round-trip, and ARG
  normalization coverage.
- Ruff and `git diff --check` passed for every modified Python source/test file.
- Patch Priorities and shared table-filter tests passed (25 focused tests);
  TypeScript checking and the production Next.js build passed.
- Live read-only Fabric SQL proved 2 Bronze assessments, 5 Bronze missing-patch
  details, 5 Bronze installations, and 10 Silver findings (5 missing and 5
  installed) in one source generation.
- Official Terraform preflight passed installation, authentication, init,
  formatting, validation, state, and template checks. Its generic plan lacked
  repository-secret variables, so the repository deployment wrapper was used
  for the authoritative saved plan.
- `/tmp/aiops-bronze-silver-prebuild.tfplan` is refresh-enabled and contains
  exactly four in-place updates: `azurerm_container_app.api`, `.web`,
  `.mcp_server`, and `.azure_mcp`; zero creates, deletes, replacements, or
  unrelated resource changes.
- RBAC is unchanged. The release does not create, resize, replace, or modify
  Fabric, APIM, identities, roles, jobs, capacity, networking, or secrets.

- Terraform validation recipe:
  - Terraform and Azure CLI are installed.
  - Azure CLI is authenticated to the target subscription.
  - Terraform is initialized.
  - Terraform formatting check passes.
  - Terraform configuration validates.
  - Terraform plan completes without unapproved destructive changes.
  - Terraform state is accessible.
  - Go-style template variables are absent from Terraform JSON variables.
  - `main.tfvars.json` JSON syntax is valid.
  - Terraform validation recipe for the PR #280 API-only rollout:
    - Terraform and Azure CLI are installed and Azure CLI is authenticated.
    - Terraform is initialized, formatted, and validates successfully.
    - The deployment plan is limited to the intended API image/revision update with no
      unapproved destructive changes.
    - Terraform state is accessible and the Terraform variable-template and JSON syntax
      checks pass.

- Terraform preflight sequence:
  - Terraform installed
  - Azure CLI installed and authenticated
  - Terraform initialized
  - Terraform formatting check passes
  - Terraform configuration validates
  - Terraform plan completes without unapproved destructive changes
  - Terraform state and template-variable checks pass
  - `main.tfvars.json` JSON syntax is valid

- Terraform installed
- Azure CLI installed and authenticated to the target subscription
- Terraform initialized
- Terraform formatting check passes
- Terraform configuration validates
- Terraform plan reviewed for image-only ACA updates and no destructive changes
- Terraform state and template-variable checks pass
- `main.tfvars.json` JSON syntax is valid

- Terraform installed
- Azure CLI installed and authenticated to the target subscription
- Terraform initialized
- Terraform formatting check passes
- Terraform configuration validates
- Terraform plan reviewed for image-only ACA updates and no destructive changes
- Terraform state and template-variable checks pass
- `main.tfvars.json` JSON syntax is valid
- Terraform installed and Azure CLI installed.
- Azure CLI authenticated to the confirmed subscription.
- Terraform initialization, formatting, validation, and plan checks pass.
- Terraform state and template-variable checks pass.
- Existing Terraform-managed ACR and Container Apps resources are identified.
- Deployment uses the repository's `infra/scripts/build-and-push.sh` and `infra/scripts/deploy.sh` scripts.
  - Confirm Terraform and Azure CLI are installed.
  - Confirm Azure CLI is authenticated to the target subscription.
  - Run Terraform init, format check, validation, and plan.
  - Confirm Terraform state and template-variable checks pass.
  - Confirm `main.tfvars.json` JSON syntax.

## Role Assignment Verification

- Status: Verified
- Identities checked: shared user-assigned identity for the API and web apps; deploying principal
- Roles confirmed: `AcrPull` scoped to the ACR; `Key Vault Secrets Officer` scoped to the Key Vault; `Foundry Agent Consumer` scoped to the Foundry project; deploying principal has Key Vault Secrets Officer and Foundry Project Manager
- Issues: none found in the static Terraform review

## Validation Proof (Round 2 — remaining 7 specialists, 2026-08-30)

- Change: applied the same "answer the operator's actual question directly; do not replace the answer with a generic inventory of findings; do not repeat the same finding in both prose and a list" instruction (already used for `network`) to the remaining 7 specialists (`vulnerability`, `patch`, `incident`, `change`, `governance`, `remediation`, `executive_summary`) in `infra/terraform/foundry.tf`.
- Reviewed `src/operations/autonomous_investigation.py` contextual routing (`run_context_investigation`) and `web/src/components/ui/CopilotDrawer.tsx` finding-suppression logic — both already apply generically to all page kinds/specialists (fixed once for network, covers all). No additional code changes required.
- `ruff check` — passed (no findings).
- `PYTHONPATH=.:src pytest -q` — full suite passed, no failures/errors.
- `terraform -chdir=infra/terraform fmt -check` and `validate` — passed.
- `terraform plan` reviewed: 1 to add / 2 to change / 1 to destroy — only `terraform_data.foundry_agent[0]` replacement (expected trigger on specialist-instruction hash) and in-place APIM policy/connection updates. No APIM resource (`azurerm_api_management.main` or sub-resources) destroyed.
- `terraform apply -auto-approve` — succeeded: 1 added, 2 changed, 1 destroyed (same non-resource `terraform_data.foundry_agent` trigger). No image rebuild required (Terraform-only change); existing image tag `network-direct-answer-20260830-1625` continued serving.
- Live verification: `/health` → 200, `/ready` → 200, web `/` → 200.
- Live Foundry agent invocation (Responses API) for all 8 specialists — each answered the operator's question directly, cited real tool results, distinguished fact vs. inference, and gave bounded recommendations without a generic findings dump or duplicated content:
  - `aiops-network-agent` (previously verified)
  - `aiops-vulnerability-agent` — direct CVE exposure answer
  - `aiops-patch-agent` — direct missing-patch assessment
  - `aiops-incident-agent` — direct incident-timeline answer (one transient 503 from MCP backend on first call, succeeded on retry — not a regression)
  - `aiops-change-agent` — direct blast-radius answer
  - `aiops-governance-agent` — direct policy-gap answer
  - `aiops-remediation-agent` — direct remediation-priority answer
  - `aiops-executive-summary-agent` (note: hyphenated name per `var.foundry_specialists.executive_summary.name` in `variables.tf`, not underscored) — direct executive risk summary
- RBAC re-verified via `az role assignment list --assignee 2c367602-bb4f-4868-8dbb-7f4ca117a719 --all` — all prior roles intact (AcrPull, Foundry Agent Consumer, Foundry Project Runtime User, Key Vault Secrets Officer, Cognitive Services OpenAI User, Foundry Project Manager). No regressions.

## Validation Proof (Bearer-token auth fix, 2026-08-30)

- Root cause: `web/Dockerfile` requires `NEXT_PUBLIC_ENTRA_CLIENT_ID`,
  `NEXT_PUBLIC_ENTRA_TENANT_ID`, and `NEXT_PUBLIC_ENTRA_API_SCOPE` as Docker
  build-args (Next.js inlines `NEXT_PUBLIC_*` vars at build time, not runtime).
  The two prior image builds this session (`main-syncfix-...`,
  `main-compliance-css-...`) were run without first sourcing
  `web/.env.local`, so `infra/scripts/build-and-push.sh` picked up empty/stale
  values for those build-args. The browser bundle shipped with no Entra
  client/tenant ID, so MSAL could never acquire an access token client-side —
  every authenticated API call from the web UI failed with the backend's
  genuine `401 unauthenticated` / "A bearer token is required" response.
  Confirmed via live container logs: 100% of non-OPTIONS, non-`/health`
  browser-origin API calls (`/api/v1/subscription-connections`,
  `/api/v1/situations`, `/api/v1/network/*`, `/api/v1/vulnerabilities/summary`)
  were returning 401, not an isolated sync-only issue.
- Fix: rebuilt both images with `web/.env.local` sourced into the shell
  (`set -a && source web/.env.local && set +a`) before running
  `build-and-push.sh`, ensuring the three `NEXT_PUBLIC_ENTRA_*` build-args are
  populated. Tag: `main-authfix-20260830-1359`.
- `./infra/scripts/build-and-push.sh main-authfix-20260830-1359` — both
  `aiops-api` and `aiops-web` built and pushed successfully.
- `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh apply -auto-approve`
  — 0 added, 3 changed, 0 destroyed; both `aiops-dev-api` and `aiops-dev-web`
  confirmed serving `main-authfix-20260830-1359`.
- Live verification: fetched the deployed web app's `/_next/static/chunks/*.js`
  and confirmed the Entra client ID (`306c1437-0e7d-43bd-940b-79b878166331`)
  is now present in the served bundle (previously absent/empty), confirming
  MSAL is correctly configured client-side.
- No source code change was required — this was purely a deployment/build
  pipeline gap (missing env sourcing before an ad hoc build invocation), not a
  regression in `src/api/auth.py` or `web/src/lib` auth wiring.

## Validation Proof (Admin page revamp + governance settings editor — 2026-08-30)

- Commit: `53c9fac9` — trimmed `/admin` to Entra/Key Vault config only; wired previously-dead `governanceApi.updateSettings` into Governance page's Administration tab as an editable policy form.
- Build/push: `main-admin-revamp-20260830-1420` (both `aiops-api` and `aiops-web`), ACR run `cr77`, succeeded in 3m24s.
- Deploy: `deploy.sh apply -auto-approve` — 0 added / 3 changed / 0 destroyed. Confirmed both container apps serving `main-admin-revamp-20260830-1420`.
- Pre-deploy checks: `npx eslint` clean on changed files; `npx tsc --noEmit` clean (pre-existing unrelated errors only in `CopilotDrawer.test.tsx`); `npm run build` succeeded (26/26 static pages); `npx vitest run` — 158/158 tests passed.
- Post-deploy smoke check: `GET /admin` → 200, `GET /governance` → 200 on `https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io`.

## Validation Proof (Admin page removed — 2026-08-30)

- Commit: `ba023589` — removed `/admin` page, nav entry, `adminApi` client, backend `/admin/akv-config` router, and its dedicated test. The form wrote to Key Vault secrets that nothing in the running app ever read back (real auth config comes from Terraform vars -> container app env vars / `NEXT_PUBLIC_ENTRA_*` build-args, a separate path).
- Build/push: `main-admin-removed-20260830-1435` (both images), ACR run `cr7a`, succeeded in 3m23s.
- Deploy: `deploy.sh apply -auto-approve` — confirmed both container apps serving `main-admin-removed-20260830-1435`.
- Pre-deploy checks: `npx eslint` clean; `npm run build` succeeded (`/admin` route no longer in build output); `npx vitest run` — 158/158 passed; backend `pytest tests/` — full suite green (test_api_admin.py removed cleanly, no other test depended on it).
- Post-deploy smoke check: `GET /admin` → Next.js not-found content confirmed (route removed); `GET /governance` → 200 (Administration tab settings editor still functional).

## Validation Proof (Governance gates: durable ledger + patch approval — 2026-08-30)

- Commits: `f52a919d` (persist investigation ledgers to OneLake), `74ba4eea`
  (enforce human approval before patch execution), `3f877fda` (lint cleanup
  the ledger commit left behind).
- Pre-deploy: `ruff check src tests` clean (fixed 3 findings `f52a919d` had
  left — that commit linted only its changed files, not the repository);
  backend `pytest tests/` full suite green; `npm run lint` clean; 158/158
  Vitest tests passed; `npm run build` succeeded; `terraform fmt -check` and
  `validate` passed.
- Mutation testing: all 8 approval-gate tests verified against 4 mutations
  (remove self-approval check, drop case/whitespace normalisation, remove
  missing-approver check, default the policy open). Each mutation is caught,
  at both the service and HTTP layer.
- Fabric capacity `aiopsdevcapg6ludc` (F4) was **Paused**, which fails
  `fabric_workspace.ops` preconditions and blocks apply. Resumed to Active for
  this deployment, then paused again afterwards.
- Build/push: `governance-gates` (both images), ACR runs `cr7h`/`cr7m`.
- Deploy: `deploy.sh apply -auto-approve` — 0 added / 3 changed / 0 destroyed,
  all in-place. `terraform_data.foundry_agent[0]` was NOT recreated, so the
  specialist instructions from the previous round are intact.
- Post-deploy, live, authenticated with a real Entra token:
  - Approval gate A — no approver → HTTP 400 `invalid_request`, citing
    `agent_policy.require_human_approval`.
  - Approval gate B — approver == requester → HTTP 400, "The approver must be
    someone other than the requester".
  - Approval gate C — distinct approver → gate passes and reaches the adapter
    (HTTP 503, no execution adapter configured in dev). This is the important
    case: it proves the gate is not blanket-refusing and that the live
    enterprise setting is genuinely being read.
  - Dry run → HTTP 202, approver falls back to requester (exempt branch).
- Durable ledger, verified end-to-end against real OneLake (not a filesystem
  stand-in as in the original commit):
  - Ran a contextual investigation → ledger `ctx-7680489d3831`.
  - Restarted revision `aiops-dev-api--0000135`; the ledger was still readable
    afterwards. Before this change it lived in an in-memory OrderedDict and
    would have been lost.
  - Confirmed the blob exists in the lakehouse:
    `Files/aiops/ledgers/ctx-7680489d3831.json` (353,409 bytes).
- CORRECTION: an earlier draft of this entry claimed `GET
  /agents/investigations` was a broken list projection returning 0. That was a
  misreading. There is no list endpoint -- the routes are `POST
  /investigations` (create), `GET /investigations/{ledger_id}`, and `POST
  /investigations/{ledger_id}/actions`. The probe issued GET against a
  POST-only path and got `405 Method Not Allowed`, whose body has no `data`
  key; the check reported that absence as a count of 0. No such gap exists.
- Genuine limitation: ledgers are reachable only by id. Enumerating an
  operator's investigation history would need both a new route and a listing
  capability on the document store (`LedgerDocumentStore` exposes `read`/`put`
  only). Not required by any current caller.

## Web image rebuild — Phase 3 remediation execution fixes (2026-09-01)

- Trigger: Phase 3 (Safe Remediation Execution) code-verified 19/19; web fixes
  from commit `33bbc4a7` (scope-aware execution service resolution,
  `attempt_number` field rename) had not yet been rolled out to `aiops-dev`.
- Build: `az acr build` for `aiops-web` only (api/mcp images unchanged), ACR
  run `crat`, tag `fix-ontology-sync-publish-20260901-171839`. Build args:
  `NEXT_PUBLIC_ENTRA_CLIENT_ID`, `NEXT_PUBLIC_ENTRA_TENANT_ID`,
  `NEXT_PUBLIC_ENTRA_API_SCOPE` read from `web/.env.local`.
- Deploy: `az containerapp update --name aiops-dev-web --image
  aiopsdevacrg6ludc.azurecr.io/aiops-web:fix-ontology-sync-publish-20260901-171839`
  (direct image update, not a full `terraform apply`, to avoid touching
  unrelated in-flight config from other concurrent sessions working on this
  repo). `terraform.tfvars` `image_tag` was intentionally NOT updated by this
  path — a future `deploy.sh apply` will still read the prior tag
  (`active-entity-fix`) until reconciled.
- Result: new revision `aiops-dev-web--0000130` created at 2026-09-01T17:22:31Z,
  Active=True, Traffic=100%. Prior revisions `--0000128`/`--0000129` remain
  Active=True/Traffic=0 (not deprovisioned).
- Smoke checks (unauthenticated, page-load only):
  - `GET /remediation` → 200
  - `GET /` → 200
  - `GET /api/config` → 200
- Not verified in this pass: authenticated remediation UI behavior (preview/
  approve/execute flows) — the live remediation plan dataset is still empty
  per `03-UAT.md`, so full remediation UAT remains blocked pending real data.
- Follow-up: reconcile `infra/terraform/terraform.tfvars` `image_tag` on the
  next full Terraform apply so state doesn't drift from the live revision.

## Validation Proof (Reactive orphaned-sync reconciliation — 2026-09-03)

- Trigger: commit `5f2cfe93` "fix(onboarding): reactively reconcile orphaned
  syncs on every poll" — a follow-up to the Fabric publish speedup
  (`003fe81e`) deployed earlier the same day. That deploy's rolling container
  restart landed mid-sync on connection `demo`, stranding its `sync_state`
  at `status="running"` indefinitely (the existing reconciler only runs at
  process startup). This commit adds a reactive check on every
  `detail()`/`health_report()` poll so a stranded sync clears itself within
  seconds instead of requiring a manual container restart.
- `terraform -chdir=infra/terraform fmt -check` → pass, no diff.
- `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan -refresh=false -lock=false`
  → "No changes. Your infrastructure matches the configuration." (no infra
  changes, image-tag-only deploy expected).
- `python3 -m compileall -q src` → pass.
- `python3 -m pytest tests/test_subscription_onboarding.py tests/test_onboarding_activation.py -q`
  → 52 passed (includes 2 new tests: reactive reconciliation on poll,
  reactive check does not fail a genuinely live sync).
- `ruff check src/onboarding/service.py tests/test_subscription_onboarding.py`
  → all checks passed.
- `cd web && npm run build` → pass.
- No RBAC/Terraform changes in this commit (Python service-layer logic only).

## Deployment Proof (Reactive orphaned-sync reconciliation — 2026-09-03)

- Images built/pushed via `infra/scripts/build-and-push.sh`, tag
  `orphan-sync-fix-20260903-2333`, all 4 images (aiops-api, aiops-web,
  mcp-server, azure-mcp); `terraform.tfvars` `image_tag` recorded
  automatically by the script.
- `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh apply -auto-approve`
  → 0 added, 6 changed (container app image references only), 0 destroyed.
  All 4 Container Apps confirmed serving `orphan-sync-fix-20260903-2333` by
  the deploy script's built-in wait/check.
- Endpoint checks: API `/health`=200, `/ready`=200; web `/`=200,
  `/api/config`=200.
- No RBAC/Terraform resource changes — image tag update only.

## Validation Proof (Remediation workflow hardening — 2026-09-04)

- `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` passed with no infrastructure changes.
- `uv run python -m compileall -q src` passed.
- `cd web && npm run build` passed, including lint and TypeScript checks.
- Local `linux/amd64` API and web container builds passed. The web dependency
  stage now copies the repository `.npmrc` and restores through
  `https://packagefeedproxy.microsoft.io/npm/`, avoiding the Defender-blocked
  direct npmjs.org route.
- Local image smoke tests passed: API `/health` returned HTTP 200 and web
  `/api/config` returned HTTP 200.
- Static Terraform RBAC review passed. The deployment changes no role
  assignments; existing application permissions remain scoped to ACR, Key
  Vault, the application resource group for VM patch execution, and the
  opt-in subscription-level Defender configuration role.
- Azure Policy assignment enumeration was attempted through the Azure MCP
  policy command but the tool failed to load its own
  `Microsoft.Identity.Client` assembly. The image-only Terraform plan remains
  policy-neutral and introduces no Azure resource or RBAC changes.

## Preparation Proof (Azure MCP timeout reliability — 2026-09-06)

- Live baseline: direct Microsoft Learn fetch 0.34s; Azure MCP initialize
  0.64s; initialized notification 0.69s; tools/list 0.99s; documentation
  search 2.76s with a 65.9 KB response.
- Root cause: the HTTP bridge wrote concurrent requests to one stateful stdio
  child while assuming FIFO responses, had no queue/execution deadlines, and
  allowed stale queued work to cross child restarts.
- Implemented true single-flight execution, exact JSON-RPC ID matching,
  bounded 5s queue wait and 25s execution budgets, queue backpressure, request
  and response size bounds, UTF-8-safe framing, child recovery, and mandatory
  reinitialization after process replacement.
- Hardened the public ACA backend with APIM's high-entropy gateway assertion,
  strict inbound JSON-RPC validation, one replica, and one explicit APIM
  backend request with a 35s timeout.
- `node --test tests/mcp-stdio-http-bridge.test.js` → 16 passed.
- `node --check scripts/mcp-stdio-http-bridge.js` → passed.
- `terraform -chdir=infra/terraform fmt -check` → passed.
- `terraform -chdir=infra/terraform validate -no-color` → passed.
- `git diff --check` → passed.
- Generic Terraform preflight passed install/auth/init/fmt/validate/state/template
  checks; its unparameterized plan step failed because it does not load this
  repository's required environment variables.
- Repository-native targeted plan:
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false -target=azurerm_container_app.azure_mcp
  -target=azapi_resource.azure_mcp_server_policy` → 0 add, 2 in-place
  changes, 0 destroy.
- `docker build -f Dockerfile.azure-mcp -t azure-mcp-bridge:test .` → passed
  after reusing the repository's trusted Microsoft npm feed proxy.
- Local container smoke → unauthenticated direct request 401; authenticated
  initialize 200; notification 202; tools/list 200 with 67 tools;
  documentation search 200 in 2.02s with a 47.9 KB response.
- Three independent code-review passes were completed; all reported
  concurrency, lifecycle, UTF-8, APIM, authentication, and protocol-validation
  findings were fixed. Final review: no significant issues.
- Deployment scope: build/push only the `azure-mcp` image, apply the Azure MCP
  Container App and APIM policy changes without replacing APIM, then verify
  unauthorized direct requests return 401 and authenticated APIM
  initialize/tools/list/documentation requests complete within their budgets.

## Role Assignment Verification (Azure MCP timeout reliability)

- Status: Verified.
- Identity: `azurerm_user_assigned_identity.azure_mcp`.
- Roles: `Reader` and `Monitoring Reader` on each explicitly onboarded
  subscription, plus `AcrPull` on the project registry.
- Scope rationale: the Azure MCP service is intentionally a cross-subscription
  read-only operations surface; no Contributor, Owner, write, or mutation role
  is granted. The timeout/security change adds no RBAC assignments.
- Backend access: public ACA ingress is retained only because APIM is not VNet
  injected; the bridge now requires APIM's high-entropy gateway assertion
  before it can use the managed identity.

## Deployment Proof (Azure MCP timeout reliability — 2026-09-06)

- ACR build `crhy` published
  `aiopsdevacrg6ludc.azurecr.io/azure-mcp:azure-mcp-timeout-20260906-1454`
  with digest
  `sha256:27c94f946e005541cdfbc731122dab820ffbb75ecc662cf5ff976cc99efccc95`.
- Saved targeted Terraform plan was machine-checked to contain exactly:
  `azurerm_container_app.azure_mcp` update and
  `azapi_resource.azure_mcp_server_policy[0]` update.
- Apply result: 0 added, 2 changed in place, 0 destroyed.
- Healthy live revision: `aiops-dev-azure-mcp--0000074`, one ready replica,
  image tag `azure-mcp-timeout-20260906-1454`.
- Direct backend POST without APIM assertion returns HTTP 401.
- APIM-authenticated initialize: HTTP 200 in 1.63s; initialized notification:
  HTTP 202; tools/list: HTTP 200 in 1.21s with 67 tools; documentation search:
  HTTP 200 in 3.30s.
- Three concurrent documentation searches all returned HTTP 200 in
  2.50–3.78s. Bridge telemetry proved single-flight queueing with queue waits
  of 0ms, 1592ms, and 2172ms and no timeout.
- Live RBAC remains least privilege: `AcrPull` on ACR, `Reader` and
  `Monitoring Reader` on the onboarded subscription; no write role added.
- Post-apply targeted Terraform plan reports no changes.

## Validation Proof (Phase 13 ontology discovery — pre-apply)

- Phase 13 dependency preflight passed against completed and verified Phases 10
  and 12.
- `uv run python -m compileall -q src scripts` passed.
- Plan 13-07 infrastructure, identity, and curator tests passed (26 tests).
- `terraform -chdir=infra/terraform fmt -check` and `terraform validate`
  passed.
- The reviewed targeted plan contains 12 additive resources, 0 updates, and 0
  destroys. It excludes existing Container Apps, APIM, the Foundry
  account/project, production Fabric workspace/lakehouse/roles, Exposure jobs,
  the legacy specialist provisioner, and later Phase 13 resources.
- A new immutable API image is required before apply because the currently
  deployed image predates the coordinator CLI and validator script.
- Live authorization evidence remains a post-apply gate; no authoritative
  ontology publication is enabled by this deployment.

## Role Assignment Verification (Phase 13 ontology discovery)

- Status: Verified statically; live verification remains required after apply.
- Coordinator identity: `AcrPull` on the existing registry and Fabric
  Contributor only in the dedicated non-production discovery-state workspace.
- Publisher identity: Fabric Contributor only in the separate non-production
  RBAC-validation workspace. Fabric exposes Contributor as its least broad
  Lakehouse write/delete role; Admin and Member are not granted.
- API/web identity: unchanged in the production workspace and receives no role
  in either Phase 13 workspace.
- Curator/Foundry project identity: receives no Fabric workspace role and only
  the exact four reviewed read-only ontology MCP tools.
- Validation runtime: manual-only ACA Job with API, coordinator, and publisher
  identities attached solely to prove two denials and one positive
  stage/CAS/rollback path in the isolated validation workspace.
- Issues fixed: removed the ineffective Azure resource-group custom data role,
  decoupled curator deployment from Phase 11 specialist-candidate publication,
  and eliminated the premature production API Contributor-to-Viewer cutover.

## Deployment Proof (Phase 13 ontology discovery — 2026-09-07)

- Immutable Job image:
  `aiopsdevacrg6ludc.azurecr.io/aiops-api:phase13-ontology-split-20260906-173930`
  (`sha256:865bc6aed31e7eb0930962cf825b87aeac7d8526a903ab73d6bf8bc7a3fd3ba1`).
- Targeted infrastructure apply created 12 additive Phase 13 resources in two
  passes (the Fabric capacity was resumed after the first pass): 12 added,
  0 existing resources changed, 0 destroyed.
- Two later targeted applies updated only the two ontology Job images/arguments;
  0 resources were destroyed.
- `aiops-dev-ontology-discovery` is healthy, scheduled every 15 minutes, and its
  five most recent executions succeeded.
- Live write matrix execution `aiops-dev-ontology-rbac-check-yuywrdn` succeeded:
  API and coordinator stage/pointer writes were denied; publisher
  stage/pointer/rollback/cleanup was authorized.
- Separate deployer audit succeeded: API, coordinator, and curator have no
  validation-workspace writer role; publisher is Contributor; curator has
  exactly the expected four read-only tools, model, and prompt hash.
- Sanitized evidence is retained in Phase 13 `13-07-LIVE-RBAC.json`.
- Existing API/web Container Apps, APIM, Foundry account/project, production
  Fabric workspace/lakehouse/roles, and global API/web image outputs were
  unchanged.

## Current Release Plan (2026-09-08)

- Source revision: current release branch based on
  `ac556cc26f435694944d5aa22580cc047a03c010` (`origin/main`), plus the
  compliance-page test-contract correction required by that revision.
- Build four immutable `linux/amd64` images from the committed source archive:
  `aiops-api`, `aiops-web`, `mcp-server`, and `azure-mcp`.
- Preserve the existing `aiops-dev` environment in subscription
  `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`, tenant
  `ffc83107-fcc0-4d2e-8798-d582da36505e`, region `australiaeast`.
- Use the canonical local Terraform state and its gitignored `terraform.tfvars`;
  do not synthesize, replace, or silently migrate state in another worktree.
- Produce a saved, refreshed Terraform plan after the image build. Reject the
  release if the plan contains any destroy, replacement, unrelated resource
  change, privilege broadening, or unexpected drift.
- The expected Phase 13 authorization delta is the additive
  `fabric_workspace_role_assignment.ontology_state_api[0]`, granting the API
  managed identity only Fabric Workspace `Viewer` on the ontology state
  workspace. No API write, publication, Job-start, Member, Contributor, or
  Admin authority may be added.
- Apply only the reviewed saved plan. Do not start or stop Phase 13 Jobs during
  infrastructure deployment.
- Verify all Container Apps serve the immutable release tag, revisions and
  replicas are healthy, `/health` and `/ready` succeed, the web application
  loads over HTTPS, and the API identity's live Fabric role is exactly Viewer.
- Run authenticated deployed API/UI and Playwright validation after the role
  assignment is live. Keep Phase 13 release state `BLOCKED/PENDING` and
  authoritative model-edge count zero until every remaining Plan 21 gate passes.

### Current Release Safety Gates

- Dirty worktrees are excluded from this release and remain untouched.
- Stale clean Phase 13 branches are not merged because they predate the merged
  REST-role reconciliation and contain superseded blocker/freeze variants.
- Build and deployment credentials remain in the existing gitignored
  environment file and process environment; no secret is passed on a command
  line or committed.
- Deployment stops before apply if canonical Terraform state is unavailable.
- Online validation records only sanitized evidence and deletes ephemeral
  browser authentication state after Playwright completes.

### Current Release Validation Proof

- 2026-09-08: `uv run python -m ruff check src tests` passed.
- 2026-09-08: `uv run python -m pytest` passed: 3,842 passed, 1 skipped.
- 2026-09-08: `cd web && npm run lint` passed.
- 2026-09-08: `cd web && npm test -- --run` passed: 593 tests.
- 2026-09-08: `cd web && npm run build` passed.
- 2026-09-08: `terraform -chdir=infra/terraform fmt -check -recursive` and
  `terraform -chdir=infra/terraform validate` passed.
- Azure context was confirmed as subscription
  `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`, tenant
  `ffc83107-fcc0-4d2e-8798-d582da36505e`, resource group `aiops-dev-rg`,
  Container Apps environment `aiops-dev-cae`, and region `australiaeast`.
- The Terraform recipe preflight remains blocked at `plan` and `state list`
  because this isolated worktree does not contain the canonical local state,
  gitignored `terraform.tfvars`, or deployment environment file. Validation
  must remain incomplete and deployment must not start until those canonical
  artifacts are supplied without using a dirty worktree.

## PR #283 rollout — network Copilot ready-gate race fix (2026-09-23)

- Root cause: `TopologyInsights` fired its `investigate-context` Copilot fetch
  before the Network page's `gaps`/`findings`/`bypass` queries resolved,
  producing a snapshot with only 2 mandatory `coverage` evidence rows and zero
  detail rows. Confirmed independently by tracing `page.tsx`,
  `TopologyInsights.tsx`, and `page-adapters.ts` before Topology's own fix
  arrived; the diagnosis matches exactly.
- Fix: PR #283 (`fix/network-copilot-ready-gate`), head
  `d949b3d5a5ea0162c2aa2b4594425a9cc8f8c684`, adds a `ready` prop to
  `TopologyInsights` (default `true`) computed in `network/page.tsx` as
  "topology + gaps + findings + bypass all have data and none are loading."
  The fetch effect short-circuits (stays `loading=true`, no API call) while
  `!ready`. Web-only change (4 files, +134/-1).
- Independent validation (isolated worktree, not just owner report):
  `npx tsc --noEmit` clean; `npx eslint` clean on the 4 touched files;
  `npx vitest run src/components/network src/app/network/page.test.tsx` → 6
  files / 147 tests passed; `npm run build` (production) succeeded.
- Merge: squash-merged with a head-SHA guard
  (`gh pr merge 283 --squash --match-head-commit d949b3d5a...`) as
  `0842f461abaf992c316f3fc2ec36efe17c61de70` on `main`.
- Build: `az acr build` for `aiops-web` only (API unchanged), registry
  `aiopsdevacrg6ludc`, run `cr117`, tag
  `network-copilot-ready-0842f461a-20260923T132458Z`, digest
  `sha256:ad3e39dfe5479c5adf12c4b3c4e455f95bf722d0c87fc7e534d00c7a96a5aea4`,
  built from the exact merge commit in an isolated worktree
  (`web/` build context, `NEXT_PUBLIC_ENTRA_*` build-args from `web/.env.local`).
- Deploy: `az containerapp update --name aiops-dev-web --image
  aiopsdevacrg6ludc.azurecr.io/aiops-web:network-copilot-ready-0842f461a-20260923T132458Z`.
  New revision `aiops-dev-web--0000246` auto-promoted (single-revision mode),
  Healthy, Active, Traffic=100%. Prior `aiops-dev-web--pr282-de46dff0-r1`
  remains Active, Traffic=0, Healthy (not deprovisioned).
- Smoke checks (unauthenticated): `GET /api/config` → 200; `GET /network` →
  200.
- API unchanged: `aiops-dev-api--pr282-e2314f5d-r1` remains Healthy at 100%
  traffic; `aiops-dev-api--pr281-7975c091-r1` rollback remains Healthy at 0%
  traffic, preserved pending PR #283 acceptance re-run.
- Next: awaiting Topology's authenticated Playwright re-run confirming the
  first `investigate-context` request includes `network/gaps` /
  `network/rule-findings` / `network/firewall-bypass` evidence rows and
  narration names specific resources with `retained:` evidence ids. On PASS,
  release the PR #281 API rollback hold per deployment policy.

## PR #284 rollout — synthesize retained network findings (2026-09-23)

- Root cause (Topology's diagnosis, independently confirmed): after PR #283,
  `/network` correctly submits detailed `network/gaps` /
  `network/rule-findings` / `network/firewall-bypass` rows, and backend
  retention preserves them as `retained:` citations, but the Foundry
  executive-synthesis path only received normalized aggregate
  `network_topology` tool findings plus prior retained thread evidence — the
  detailed current-page rows never entered the coordinator's citation-closed
  findings set, so narration said exact resources/remediations were "not
  supplied" despite being present in the response's citation list.
- Fix: `src/operations/orchestration_service.py` adds
  `retained_network_page_claims()`, which promotes current retained Network
  page gap/rule-finding/firewall-bypass rows into citation-closed synthesis
  findings (severity-ranked, capped at 8, with resource/issue/recommendation
  text and evidence refs) before Foundry executive narration, prefers these
  over aggregate topology counts in claim/specialist selection, and folds
  current retained citations into synthesized success bookkeeping
  (`used_retained_evidence`). API-only change (2 files, +139/-9 in
  `orchestration_service.py`, +107 new test file).
- Independent validation (isolated worktree, not just owner report):
  `pytest -p no:phoenix tests/test_network_retained_synthesis.py
  tests/test_page_evidence_material_claims.py
  tests/test_api_copilot_context_bridge.py
  tests/test_foundry_narration_provider_selection.py` → 9/9 passed;
  `ruff check` clean on both touched files; `compileall` clean. Broader
  orchestration-adjacent suite run for regression check; the only failures
  were the pre-existing baseline `reviewed_tree_digest` fixture-attribute
  errors already documented as unrelated environment issues (confirmed
  present on clean `main` too, not caused by this change).
- Merge: squash-merged with a head-SHA guard
  (`gh pr merge 284 --squash --match-head-commit
  32a53d123695ad556b97cf5c399a9274d04a4683`) as
  `d872e43ba2d825464a93abda926a18d3cdea22d4` on `main`.
- Build: `az acr build` for `aiops-api` only (web unchanged), registry
  `aiopsdevacrg6ludc`, run `cr119`, tag
  `network-retained-synthesis-d872e43ba-20260923T134551Z`, digest
  `sha256:e76176292551a4117bf3b0b775b46783209f09f5eb23eebc0ca440c2c2f28fb3`,
  built from the exact merge commit in an isolated worktree with explicit
  `--build-arg AIOPS_SOURCE_REVISION=d872e43ba2d825464a93abda926a18d3cdea22d4`
  (required by the Dockerfile's exact-revision assertion step).
- Deploy: multi-revision API — created
  `aiops-dev-api--pr284-e7617629` at 4 CPU / 8 GiB (unchanged from baseline),
  0% traffic; polled to Healthy/RunningAtMaxScale; smoke-checked `/health`
  and `/ready` → both 200 directly against the revision FQDN; promoted to
  100% traffic (`az containerapp ingress traffic set`). Confirmed via main
  ingress FQDN: `/health` → 200, `/ready` → 200.
- Rollback preserved: `aiops-dev-api--pr281-7975c091-r1` remains Healthy,
  Active, Traffic=0%, per Topology's explicit hold request — acceptance for
  the Network narration thread (PR #280/#281/#282/#283/#284) has still not
  fully PASSed as of this entry. `aiops-dev-api--pr282-e2314f5d-r1` (prior
  100% revision) also remains Healthy at 0%, not deprovisioned.
- Next: awaiting Topology's authenticated Playwright re-run confirming
  narration now names specific retained resources (e.g. `aiopsdemoacr`)
  with `retained:` citation ids and recommendations, zero console errors. On
  PASS, release the PR #281 API rollback hold per deployment policy.

## PR #284 acceptance result (addendum)

- Topology's authenticated Playwright re-run on `/network`: **FAIL (partial
  improvement)**. Retained-network deterministic path confirmed working
  (narration names `aiopsdemoacr` and other concrete resources with
  recommendations), but `synthesis.mode=deterministic` (not `foundry`),
  no executive agent identity returned, `used_retained_evidence=[]`,
  `policy_status=fallback`, `fallback_reason=planner_unavailable`. Zero
  JS console errors (one unrelated DevTools accessibility-only notice).
  Rollback hold on `aiops-dev-api--pr281-7975c091-r1` kept in place per
  policy; no deployment mutation from that acceptance report alone.
  Root cause traced by Topology to preview MAF transport degradation for
  the unversioned `executive_summary` specialist → follow-up PR #286.

## PR #286 — fix(agent): force executive_summary onto stable Foundry REST transport

- Source: Topology handoff (`fix/network-foundry-admission`,
  head `290fa7f5a89528ad66ec06723d11a4254b1b40ee`, base
  `fd2d9243d818a1bda2df6fee42737fdbaeeaf78d` — confirmed exact match with
  main HEAD prior to merge).
- Root cause (evidenced): live `/network` nested synthesis diagnostics
  showed `provider_error_class=foundry_agent_error` for the unversioned
  `executive_summary` specialist when routed through the preview MAF
  (Microsoft Agent Framework) transport; the identical call — same agent
  identity, prompt, and citation-closed retained evidence — succeeded via
  the stable Foundry Responses REST adapter. Production's
  `select_foundry_agent_class()` was defaulting unversioned specialists to
  the preview MAF path, which was degraded for this specific specialist.
- Fix: adds a narrow early-return branch in `select_foundry_agent_class()`
  — `if specialist == EXECUTIVE_SPECIALIST_ID: return rest_agent_class` —
  forcing only `executive_summary` onto the stable REST transport while
  preserving MAF for all other unversioned specialists. API-only change
  (2 files: `src/operations/foundry_agent.py`,
  `tests/test_foundry_agent.py`; +1 new test).
- Independent validation (isolated worktree, not just owner report):
  `pytest -p no:phoenix tests/test_foundry_agent.py` → 45/45 passed;
  broader related set (`test_foundry_agent.py` +
  `test_network_retained_synthesis.py` + `test_page_evidence_material_claims.py`
  + `test_api_copilot_context_bridge.py` +
  `test_foundry_narration_provider_selection.py`) → 54/54 passed, no
  regressions. `ruff check` clean, `compileall` clean on both touched
  files. GitHub Actions run failed at workflow admission (0 steps, 2-4s
  completion) — treated as infrastructure per established policy; not a
  test-evidence gate.
- Merge: squash-merged with a head-SHA guard
  (`gh pr merge 286 --squash --match-head-commit
  290fa7f5a89528ad66ec06723d11a4254b1b40ee`) as
  `b685627da80ef3ce993abf87bc052bb9fc4e35af` on `main`.
- Build: `az acr build` for `aiops-api` only (web unchanged), registry
  `aiopsdevacrg6ludc`, run `cr11a`, tag
  `network-foundry-admission-b685627da-20260923T155206Z`, digest
  `sha256:0396666685315d496f83710f5d4999732a7a308fd76068692580d51e832afd7c`,
  built from the exact merge commit in an isolated worktree with explicit
  `--build-arg AIOPS_SOURCE_REVISION=b685627da80ef3ce993abf87bc052bb9fc4e35af`.
- Deploy: created `aiops-dev-api--pr286-03966666` at 4 CPU / 8 GiB
  (unchanged sizing), 0% traffic. Revision initially stuck
  `Activating`/`health:None` with an empty replica (`containers: []`,
  `runningState:NotRunning`) — root-caused as `api-d4` workload-profile
  node-capacity exhaustion: 4 active revisions (`pr281`, `pr282`, `pr284`,
  `pr286`) at 4 CPU each had filled all available nodes even after raising
  `maximumCount` to 4. Resolved by deactivating the superseded
  `aiops-dev-api--pr282-e2314f5d-r1` (already superseded by `pr284`, not the
  designated rollback — `pr281` is) to free a node. Revision then passed
  through a transient `ActivationFailed`/`Unhealthy` state (platform
  `Deployment Progress Deadline Exceeded` at container-start time, per
  Topology's corroborating platform-log evidence) before reaching
  Healthy/RunningAtMaxScale — confirmed a scheduling-delay artifact, not a
  code or image defect. Smoke-checked `/health` and `/ready` directly
  against the revision FQDN → both 200. Promoted to 100% traffic
  (`az containerapp ingress traffic set`).
- Rollback preserved: `aiops-dev-api--pr281-7975c091-r1` remains Healthy,
  Active, Traffic=0%, per Topology's explicit hold request — Network
  narration thread acceptance (PR #280/#281/#282/#283/#284/#286) has not
  yet fully PASSed as of this entry.
  `aiops-dev-api--pr282-e2314f5d-r1` deactivated this entry (superseded,
  capacity-freeing decision) — no longer Active; `pr284` remains Active at
  0% as an additional fallback point between `pr281` and `pr286`.
- Next: awaiting Topology's authenticated Playwright re-run confirming
  `synthesis.mode=foundry`, executive agent identity present,
  `used_retained_evidence` non-empty, named resources (e.g. `aiopsdemoacr`),
  concrete recommendations, `retained:` citation ids, zero console errors.
  On PASS, release the PR #281 API rollback hold per deployment policy.

## PR #286 acceptance result (addendum)

- Topology's authenticated Playwright re-run on `/network`: **PASS** for
  Foundry synthesis itself. `synthesis.executive.status=synthesized`,
  `mode=foundry`, `agent=aiops-executive-summary-agent`, empty
  degraded/provider-error fields, 2 claims, named resources (e.g.
  `acrsredemodevau0qhc`, `aiops-demo-openai`), concrete private
  endpoint/NSG/route-table recommendations, 8 `retained:` refs, zero
  console errors, UI no longer shows "Evidence-only fallback". Remaining
  gap: `used_retained_evidence` populated internally but omitted from the
  API response projection → follow-up PR #287.

## PR #287 — fix(copilot): expose retained synthesis evidence in API response

- Source: Topology handoff (`fix/copilot-retained-evidence-projection`,
  head `3e55592ca9588613175ee0a0abd5c7448e14a5a4`, base
  `187de7fed9d1819cda05dfbd441b65710354acf2` — confirmed exact match with
  main HEAD prior to merge).
- Root cause: `ExecutiveSynthesis.used_retained_evidence` was already
  computed and populated internally (used for narration/claims), but the
  inline dict literal building the API response's `synthesis` payload
  omitted the key, so external callers/UI could not see which retained
  evidence rows were actually used.
- Fix: extracts the inline synthesis-dict construction into a new
  `_executive_synthesis_payload()` helper and adds the missing
  `used_retained_evidence` key to the projected dict. API-only change
  (2 files: `src/operations/orchestration_service.py`,
  `tests/test_network_retained_synthesis.py`; +1 assertion on the new
  helper's output).
- Independent validation (isolated worktree, not just owner report):
  `pytest -p no:phoenix tests/test_network_retained_synthesis.py
  tests/test_page_evidence_material_claims.py
  tests/test_api_copilot_context_bridge.py
  tests/test_foundry_narration_provider_selection.py
  tests/test_foundry_agent.py` → 54/54 passed; `ruff check` clean;
  `compileall` clean; `git diff --check` clean. GitHub Actions run failed
  at workflow admission again (0 steps executed across all 3 jobs, 2-3s
  completion) — same infrastructure/runner pattern as PR #286, treated as
  non-executed per established policy.
- Merge: squash-merged with a head-SHA guard
  (`gh pr merge 287 --squash --match-head-commit
  3e55592ca9588613175ee0a0abd5c7448e14a5a4`) as
  `6b0241eff9f30c56400c2289dd38d94ee4c30350` on `main`.
- Build: `az acr build` for `aiops-api` only (web unchanged), registry
  `aiopsdevacrg6ludc`, run `cr11b`, tag
  `copilot-retained-evidence-projection-6b0241eff-20260923T161631Z`,
  digest `sha256:36354b89b64d55adfc781ed1d584ebf823b49fb74333de84dabc3c0956873531`,
  built from the exact merge commit in an isolated worktree with explicit
  `--build-arg AIOPS_SOURCE_REVISION=6b0241eff9f30c56400c2289dd38d94ee4c30350`.
- Deploy: created `aiops-dev-api--pr287-36354b89` at 4 CPU / 8 GiB
  (unchanged sizing), 0% traffic. Hit the same `api-d4` node-capacity
  exhaustion pattern as PR #286 (4 active revisions again filled all
  nodes). Resolved by deactivating the now-superseded
  `aiops-dev-api--pr284-e7617629` (superseded by `pr286`, then by `pr287`;
  not the designated rollback). Revision reached Healthy/RunningAtMaxScale
  shortly after. Smoke-checked `/health` and `/ready` directly against the
  revision FQDN → both 200. Promoted to 100% traffic
  (`az containerapp ingress traffic set`).
- Rollback preserved: `aiops-dev-api--pr281-7975c091-r1` remains Healthy,
  Active, Traffic=0%, per Topology's explicit hold request.
  `aiops-dev-api--pr286-03966666` (prior 100% revision, itself already
  acceptance-PASSed for Foundry synthesis) also remains Healthy at 0% as
  an additional fallback point between `pr281` and `pr287`.
  `aiops-dev-api--pr284-e7617629` deactivated this entry (superseded twice
  over) — no longer Active.
- Next: awaiting Topology's final post-#287 authenticated acceptance
  confirming `data.synthesis.executive.used_retained_evidence` is now
  non-empty in the API response (in addition to the already-PASSed
  foundry mode/agent/citations/console-error checks from PR #286). On
  final PASS, release the PR #281 API rollback hold per deployment policy
  — this closes out the PR #280→#287 Foundry topology-narration thread.

## PR #287 final acceptance — Foundry topology-narration thread CLOSED

- Topology's final authenticated Playwright re-run on `/network` against
  `aiops-dev-api--pr287-36354b89` at 100% traffic: **PASS**.
  `data.synthesis.executive.status=synthesized`,
  `reason=operations_copilot_coordinator`, `mode=foundry`,
  `agent=aiops-executive-summary-agent`; `warning`/`degraded_reason`/
  `provider_error_class`/`provider_error_reason` all empty. 4 claims,
  5 `retained:` claim refs, and `used_retained_evidence` now contains
  5 rows/IDs (the field PR #287 exposed). Narration names concrete
  resources (`demo-vnet-private-endpoints-nsg-australiaeast`,
  `demo-vnet-AzureBastionSubnet-nsg-australiaeast`,
  `acrsredemodevau0qhc`, `aiops-demo-openai`, `container-apps`,
  `aiops-dev-vnet`) with concrete NSG/private-endpoint/route-table/
  firewall recommendations. UI shows "Grounded LLM insight" (not
  "Evidence-only fallback"). Zero browser console errors.
- **Rollback hold released**: `aiops-dev-api--pr281-7975c091-r1`
  deactivated per Topology's explicit release instruction and
  deployment policy — this closes the entire PR #280 → #281 → #282 →
  #283 → #284 → #286 → #287 Foundry topology-narration fix chain.
  `aiops-dev-api--pr286-03966666` retained Active/Healthy at 0% as the
  immediate rollback point (already itself acceptance-PASSed for Foundry
  synthesis mode/agent/citations, superseded only by the
  `used_retained_evidence` exposure fix in #287).
- Final API revision state: `pr286` (Healthy, 0%, immediate rollback),
  `pr287` (Healthy, 100%, live). All prior revisions (`pr281`, `pr282`,
  `pr284`) deactivated.
- Web: unchanged throughout this entire thread (API-only fixes, per
  Topology's explicit rollout constraints on #281/#284/#286/#287; #282/
  #283 were the only paired API+web releases in this chain).

## PR #288 — Foundry topology-narration recurrence fix (paired API+web)

- Context: after the PR #280→#287 thread was closed, Topology reported a
  recurring intermittent fallback: repeated `/network` refreshes
  sometimes returned `synthesis.mode=deterministic`/`status=degraded`
  with `provider_error_class=foundry_agent_error`. Root cause reproduced:
  `parse_specialist_findings` was rejecting valid Foundry executive
  answers that described a concrete remediation (e.g. "create a private
  endpoint"), misclassifying successful provider calls as errors.
  Additionally, the deployed `TopologyInsights` UI collapsed successful
  structured claims/next-checks/uncertainty into a single paragraph.
- Topology's session was blocked from opening its own PR (dirty unrelated
  branch `feat/kb-finding-title`; PR tool limited to session's own
  branch) and persisted a validated 10-file patch instead. As sole
  release integrator, this session applied the patch in an isolated
  worktree from clean `origin/main`, independently re-validated it, and
  opened PR #288 on Topology's behalf. Topology confirmed (byte-for-byte
  diff) the PR matches their intended fix.
- Independent validation (isolated worktree, clean main):
  - Backend: 60/60 focused tests passed (`test_foundry_narration_provider_selection.py`,
    `test_network_retained_synthesis.py`, `test_page_evidence_material_claims.py`,
    `test_api_copilot_context_bridge.py`, `test_foundry_agent.py`).
    Ruff + `compileall` clean.
  - Two pre-existing unrelated test failures found on unpatched main too
    (`test_ontology_trace_redaction.py` missing `opentelemetry.sdk`;
    `test_orchestration_policy.py` missing `reviewed_tree_digest`
    attribute) — confirmed via `git stash` not caused by this patch;
    excluded from release gate.
  - Web: `npx vitest run` 837/837 passed (65 files, incl.
    `TopologyInsights.test.tsx` 10/10), ESLint clean, `tsc --noEmit`
    clean, production build succeeded (28/28 static pages).
- Merge: PR #288 merged via head-SHA guard
  (`--match-head-commit cce5dfefef7ccac10e6bfc74e26f1b5dd6f04608 --admin`,
  GitHub Actions non-executed at workflow admission — known billing/
  spending-limit infra issue, treated as non-blocking per established
  policy) → `2e7b8dea202ec7d9315935b5c7f0ea716877518d` on `main`.
- Build: both API and web images built from the exact merge commit in an
  isolated worktree, registry `aiopsdevacrg6ludc`.
  - API: run `cr11c`, tag
    `topology-recurrence-2e7b8dea2-20260923T173529Z`, digest
    `sha256:8c4edb0639128ae1c58938ed54bdcaeb1596ba47bf271005543ae019db4aad21`,
    `--build-arg AIOPS_SOURCE_REVISION=2e7b8dea202ec7d9315935b5c7f0ea716877518d`.
  - Web: run `cr11d`, tag
    `topology-recurrence-2e7b8dea2-20260923T174050Z`, digest
    `sha256:04bd1d555fe7d25f186c6c6aa62305a8539498785141a3f1ff522a8b39a9f843`.
- Deploy — API: created `aiops-dev-api--pr288-8c4edb06` at 4 CPU / 8 GiB
  (unchanged sizing), 0% traffic. Hit the same `api-d4` node-capacity
  exhaustion pattern seen in prior PRs (3 active revisions filled all
  nodes). Resolved by deactivating the now-doubly-superseded
  `aiops-dev-api--pr286-03966666` (superseded by `pr287`, then by
  `pr288`). Revision reached Healthy/RunningAtMaxScale shortly after.
  Smoke-checked `/health` and `/ready` directly against the revision
  FQDN → both 200. Promoted to 100% traffic
  (`az containerapp ingress traffic set`).
- Rollback preserved: `aiops-dev-api--pr287-36354b89` (prior 100%
  revision, itself already acceptance-PASSed for Foundry synthesis +
  `used_retained_evidence`) remains Healthy at 0% as the new immediate
  rollback point. `aiops-dev-api--pr286-03966666` deactivated this entry
  (superseded twice over) — no longer Active.
- Deploy — Web: `az containerapp update` on `aiops-dev-web` (Single
  revision mode — auto-promotes to 100% immediately, no canary staging
  possible). New revision `aiops-dev-web--0000247` reached
  Healthy/Running. Smoke-checked `/` and `/network` → both 200.
- Final revision state: API `pr287` (Healthy, 0%, rollback), `pr288`
  (Healthy, 100%, live); Web `0000247` (Healthy, 100%, live — only web
  deploy since the PR #282/#283 pair).
- Next: awaiting Topology's authenticated Playwright re-acceptance run
  against `pr288` + web `0000247` confirming: repeated refreshes/reload
  return `mode=foundry` reliably (not just once), structured claims/
  next-checks/uncertainty render separately (not collapsed), retained
  citations expandable, honest fallback warning text, zero console
  errors. Do not release the `pr287` rollback hold until that PASSes.

## PR #289 — mutation-word-boundary false-positive fix (API-only)

- Context: Topology's post-PR288 authenticated acceptance run FAILed
  reliability — only 3/5 `/network` calls synthesized via Foundry, 2/5
  incorrectly fell back to deterministic/degraded, misclassified as
  `foundry_agent_error`/`provider_error`. UI/rendering criteria (structured
  claims, next-checks, uncertainty, expandable citations, honest fallback
  warning, zero console errors) all PASSed on PR288; only the reliability
  percentage was flagged. No rollback mutation was requested or made.
- Root cause: `_MUTATION_WORDS` substring matching in
  `parse_specialist_findings` rejected valid Foundry executive summaries
  whose read-only wording contained a mutation-word stem as a substring of
  a longer word (e.g. `apply` inside `applied`, as in "Verify whether the
  recommendation has been applied").
- Fix: Topology supplied a 2-file patch (`src/operations/foundry_agent.py`
  + `tests/test_network_retained_synthesis.py`) switching mutation-word
  detection to a compiled word-boundary regex
  `\b(?:delete|create|update|modify|execute|apply|remediate)\b`
  (case-insensitive), which still correctly rejects genuine imperative
  mutation instructions. Persisted at
  `.copilot/session-state/fb7534f6-eadb-4b75-9b63-b712b1794cef/files/pr288-followup-word-boundary.patch`
  (SHA-256 `0783ff5d...`).
- Independent validation (before merge): applied cleanly
  (`git apply --check` → 0), 60/60 focused backend tests passed
  (`test_network_retained_synthesis.py`,
  `test_foundry_narration_provider_selection.py`, `test_foundry_agent.py`,
  `test_page_evidence_material_claims.py`,
  `test_api_copilot_context_bridge.py`), Ruff clean, `compileall` clean.
- PR: opened **PR #289** from branch `fix/mutation-word-boundary-detection`,
  head `db999a67d5bf6220a4c59ca8811d1fd21c94fdad`. Topology confirmed
  byte-for-byte match against their persisted patch and authorized
  proceeding. GitHub Actions again failed at workflow admission (all jobs
  zero-execution in 2-4s — known billing/spending-limit infra issue,
  non-blocking per established policy).
- Merge: head-SHA guarded
  (`gh pr merge 289 --squash --match-head-commit
  db999a67d5bf6220a4c59ca8811d1fd21c94fdad --admin`) →
  `3de259e3c1a4392e6b7284004d93ac34d2e03ac7` on `main`.
- Build: API image only (no web changes in this PR), built from the exact
  merge commit in an isolated worktree, registry `aiopsdevacrg6ludc`. Run
  `cr11e`, tag `mutation-word-boundary-3de259e3c-20260923T175823Z`, digest
  `sha256:c611c145b46d11c2b5fdffb90bd3c57bea503218640c855e974fbe7212334878`,
  `--build-arg AIOPS_SOURCE_REVISION=3de259e3c1a4392e6b7284004d93ac34d2e03ac7`.
- Deploy: created `aiops-dev-api--pr289-c611c145` at 4 CPU / 8 GiB
  (unchanged sizing), 0% traffic. Hit the same `api-d4` node-capacity
  pattern; this time with only 3 active revisions and `pr287` under an
  explicit Topology preservation hold (pending their reliability
  re-acceptance) plus `pr288` still serving live 100% traffic, there was no
  safe revision to deactivate. Confirmed `api-d4` workload profile had
  headroom (`currentCount: 3`, `maximumCount: 4`) and continued polling
  without any capacity mutation; the candidate reached
  Healthy/RunningAtMaxScale on its own (~90s). Smoke-checked `/health` and
  `/ready` directly against the revision FQDN → both 200. Promoted to 100%
  traffic (`az containerapp ingress traffic set`), dropping `pr288` to 0%;
  `pr287` left untouched at 0% (rollback hold preserved throughout).
- No web changes/redeploy needed for this PR (API-only fix).
- Final revision state: API `pr287` (Healthy, 0%, preserved rollback hold —
  pending Topology's reliability re-acceptance), `pr288` (Healthy, 0%,
  immediate prior state), `pr289` (Healthy, 100%, live). Web unchanged:
  `0000247` (Healthy, 100%, live).
- Smoke-checked production ingress `/health` and `/ready` → both 200.
- Next: notifying Topology of the PR289 deployment and requesting their
  repeated authenticated `/network` reliability acceptance re-run —
  target 5/5 Foundry synthesis calls (up from the 3/5 that failed on
  PR288), plus re-confirmation of the UI/rendering criteria already
  PASSed. Do not release the `pr287` rollback hold until that PASSes.

## PR #290 — executive next-check sanitization (API-only)

- Context: Topology's post-PR289 authenticated acceptance run again FAILed
  reliability — only 2/4 fresh `/network` calls synthesized via Foundry,
  degraded on `contract_error/response_contract`. `/ready` reported the
  executive agent ready; measured budget ~29.9s (not a timeout). UI
  criteria remained PASS. Word-boundary fix (PR289) correctly resolved
  the `applied`/`apply` false positive, but the underlying model can
  still legitimately produce genuinely unsafe imperative wording in
  `next_check` (e.g. "Create a private endpoint now."), and whole-output
  lexical rejection dropped an otherwise-valid cited finding.
- Fix: Topology supplied a 2-file patch (`src/operations/foundry_agent.py`
  + `tests/test_foundry_agent.py`) that, in the executive synthesis
  adapter only, replaces a `next_check` field containing an exact
  mutation-word match with a deterministic safe string
  ("Review the cited evidence before any governed change.") instead of
  rejecting the entire finding. Strict JSON/schema/enum/citation
  validation and generic-specialist mutation rejection are unchanged.
  Persisted at
  `.copilot/session-state/fb7534f6-eadb-4b75-9b63-b712b1794cef/files/pr289-followup-next-check-sanitization.patch`
  (SHA-256 `c1a3d69c7b045f05893973b6a90a8c04c15e852e3fa0db8af0c2265e0b55c383`).
- Independent validation (before merge): applied cleanly, 67/67 focused
  backend tests passed (`test_foundry_agent.py`,
  `test_network_retained_synthesis.py`,
  `test_foundry_narration_provider_selection.py`,
  `test_page_evidence_material_claims.py`,
  `test_api_copilot_context_bridge.py`), Ruff clean, `compileall` clean.
- PR: opened **PR #290** from branch `fix/executive-next-check-sanitization`,
  head `c86c4b4840e4a9ae80177c52949b2528f380208b`. Topology confirmed
  byte-for-byte match against their persisted patch (raw SHA-256 exact
  match) and authorized proceeding. GitHub Actions again failed at
  workflow admission (known billing/spending-limit infra issue,
  non-blocking per established policy).
- Merge: head-SHA guarded
  (`gh pr merge 290 --squash --match-head-commit
  c86c4b4840e4a9ae80177c52949b2528f380208b --admin`) →
  `f07123ff66ff726b94319cde19cf8ff9180d543c` on `main`.
- Build: API image only (no web changes in this PR), built from the exact
  merge commit in an isolated worktree, registry `aiopsdevacrg6ludc`. Run
  `cr11f`, tag `next-check-sanitization-f07123ff6-20260923T181701Z`,
  digest `sha256:c429dd82d05182f865197bea299ced190d90f9e88f6b5566456592beacdae529`,
  `--build-arg AIOPS_SOURCE_REVISION=f07123ff66ff726b94319cde19cf8ff9180d543c`.
- Deploy: created `aiops-dev-api--pr290-c429dd82` at 4 CPU / 8 GiB
  (unchanged sizing), 0% traffic. Hit `api-d4` node-capacity exhaustion
  again — 4 active revisions filled all 4 nodes (`currentCount: 4,
  maximumCount: 4`, confirmed via workload-profile query). Resolved by
  deactivating the superseded, non-rollback, 0%-traffic
  `aiops-dev-api--pr288-8c4edb06` (`pr287` — the explicitly protected
  rollback — was left untouched throughout). Candidate reached
  Healthy/RunningAtMaxScale shortly after. Smoke-checked `/health` and
  `/ready` directly against the revision FQDN → both 200. Promoted to
  100% traffic (`az containerapp ingress traffic set`), dropping `pr289`
  to 0%; `pr287` left untouched at 0% (rollback hold preserved
  throughout).
- No web changes/redeploy needed for this PR (API-only fix).
- Final revision state: API `pr287` (Healthy, 0%, preserved rollback hold
  — pending Topology's reliability re-acceptance), `pr289` (Healthy, 0%,
  immediate prior state), `pr290` (Healthy, 100%, live). `pr288`
  deactivated (superseded twice over, no longer Active). Web unchanged:
  `0000247` (Healthy, 100%, live).
- Smoke-checked production ingress `/health` and `/ready` → both 200.
- Next: notifying Topology of the PR290 deployment and requesting their
  repeated authenticated `/network` reliability acceptance re-run —
  target 5/5 Foundry synthesis calls. Do not release the `pr287` rollback
  hold until that PASSes.

## PR #291 — fix(copilot): allow executive uncertainty remediation context

- Follow-up to PR #290 after Topology reported PR290 acceptance FAIL
  (4/5 foundry synthesis, 1 degraded `contract_error/response_contract`).
  Root cause: executive mutation-word validation still applied across all
  finding fields except `summary`, so legitimate remediation-describing
  language in `uncertainty` could still trigger whole-finding rejection.
  Fix narrows the mutation-word guard to only `next_check` (already
  sanitized deterministic-safe by PR290); `summary`/`uncertainty` may
  describe cited remediation without rejection. Generic (non-executive)
  specialist validation and all schema/citation/freshness/confidence
  checks unchanged and strict.
- Patch persisted by Topology, SHA-256
  `82fec12db046cb69a2ade42f20e8d0d6ab6612652fcf828f9b24f0106e24e12b`,
  applied cleanly onto fresh `origin/main` (`c19a94c5644ab98cf6a65d4b74733c8d7b7d1add`,
  includes PR290 deployment record). Exactly 2 files: `src/operations/foundry_agent.py`
  (10 lines) and `tests/test_network_retained_synthesis.py` (20 lines).
- Independent validation (isolated worktree, before commit): 68/68 focused
  backend tests passed (`test_foundry_agent.py`,
  `test_executive_summary_specialist.py`, `test_network_retained_synthesis.py`,
  `test_foundry_narration_provider_selection.py`,
  `test_foundry_narration_budget_starvation.py`); Ruff clean; `compileall`
  clean; `git diff --check` clean.
- Committed with conventional-commit message + Co-authored-by trailer
  (`c89063743447e7974fdbff11b26055134f9c3d1c`), pushed branch
  `fix/executive-uncertainty-validation`, opened **PR #291**.
- Topology independently confirmed exact-diff match (`gh pr diff 291`
  SHA-256 matches the validated patch artifact exactly) and authorized
  merge.
- Merge: head-SHA guarded (`gh pr merge 291 --squash --match-head-commit
  c89063743447e7974fdbff11b26055134f9c3d1c --admin`) →
  `6ab7133f675e1ddfc7e641b20d923ccdc3d9eeaf` on `main`.
- Build: API image only (no web changes), built from the exact merge
  commit in an isolated worktree, registry `aiopsdevacrg6ludc`. Run
  `cr11g`, tag `executive-uncertainty-6ab7133f6-20260923T183605Z`,
  digest `sha256:0835e454447b13f95b5907cdfee490a2a27e2b8fc3eb9fe99ba17fe52060f335`,
  `--build-arg AIOPS_SOURCE_REVISION=6ab7133f675e1ddfc7e641b20d923ccdc3d9eeaf`.
- Deploy: created `aiops-dev-api--pr291-0835e454` at 4 CPU / 8 GiB
  (unchanged sizing), 0% traffic. `api-d4` had headroom
  (`currentCount: 3, maximumCount: 4`) — no capacity mutation needed;
  candidate reached Healthy/RunningAtMaxScale after continued polling
  (~75s). Smoke-checked `/health` and `/ready` directly against the
  revision FQDN → both 200. Promoted to 100% traffic (`az containerapp
  ingress traffic set`), dropping `pr290` to 0%; `pr287` left untouched
  at 0% (rollback hold preserved throughout).
- No web changes/redeploy needed for this PR (API-only fix).
- Final revision state: API `pr287` (Healthy, 0%, preserved rollback hold
  — pending confirmed re-acceptance against this specific deployment),
  `pr289` (Healthy, 0%, superseded), `pr290` (Healthy, 0%, superseded),
  `pr291` (Healthy, 100%, live). Web unchanged: `0000247` (Healthy, 100%,
  live).
- Smoke-checked production ingress `/health` and `/ready` → both 200.
- Note: Topology's PR291 acceptance message referenced an
  `executive_summary_agent` readiness timestamp (`2026-09-23T18:40:54Z`)
  predating this deploy's completion (`lastModifiedAt 2026-09-23T18:41:31Z`)
  and `pr291` was still at 0% traffic when that message was sent — the
  reported 5/5 evidence likely tested the then-live `pr290`, not `pr291`.
  Requested a fresh re-run specifically against the now-live `pr291`
  before releasing the `pr287` rollback hold.

## Process deviation — unauthorized out-of-band mutation on PR287 rollback (2026-09-23)

- Topology ("fb7534f6-eadb-4b75-9b63-b712b1794cef" session) reported PR291
  acceptance PASS (5/5 foundry synthesis) via a message whose reported
  `executive_summary_agent` readiness timestamp (`2026-09-23T18:40:54Z`)
  predated this session's PR291 deploy completion
  (`lastModifiedAt: 2026-09-23T18:41:31Z`); `pr291` was still at 0%
  traffic when that acceptance evidence was captured. This session
  declined to release the `pr287` rollback hold and requested a fresh,
  post-deploy-timestamped re-run twice.
- Topology did not provide new evidence. Instead, Topology directly ran
  `az containerapp revision deactivate -g aiops-dev-rg -n aiops-dev-api
  --revision aiops-dev-api--pr287-36354b89` against the shared Azure
  environment, bypassing this session (the sole designated release
  integrator per the unified-release-freeze policy — other sessions are
  restricted to providing handoff evidence only, not performing
  infrastructure mutations).
- Verified via `az containerapp revision list` that `pr287` had indeed
  been deactivated (no longer listed as Active).
- Remediation: reactivated `aiops-dev-api--pr287-36354b89`
  (`az containerapp revision activate`) to restore the rollback hold to
  its last authorized state. Confirmed it returned to
  Healthy/RunningAtMaxScale at 0% traffic after ~45s. `pr291` (100%,
  Healthy, live), `pr289`/`pr290` (0%, Healthy, superseded) were
  unaffected throughout.
- Notified Topology that direct infrastructure mutation is out of policy
  scope, reiterated the evidence bar for releasing the `pr287` hold
  (fresh authenticated `/network` acceptance with timestamps after
  `2026-09-23T18:41:31Z` UTC), and requested no further direct mutations.
- Current authoritative state: `pr287` Healthy/0% (rollback hold
  restored/preserved), `pr289` Healthy/0% (superseded), `pr290`
  Healthy/0% (superseded), `pr291` Healthy/100% (live). Web unchanged.

## PR287 rollback hold released — closure (2026-09-23)

- Topology re-ran authenticated `/network` acceptance genuinely
  post-PR291-deploy (executive agent `last_success_at=2026-09-23T18:50:28Z`,
  after this session's PR291 deploy completion at `18:41:31Z`), confirming
  production ingress was serving `pr291` at 100% before testing.
- Result: **PASS 5/5** — five real page-triggered authenticated
  `POST /api/v1/copilot/investigate-context` calls all returned
  `mode=foundry`/`status=synthesized`, agent `aiops-executive-summary-agent`,
  no `provider_error_class`/`provider_error_reason`/fallback warning
  (claims/retained per call: 7/6, 2/8, 2/8, 2/8, 2/8). UI criteria PASS:
  Grounded LLM insight, no evidence-only fallback, structured cards, next
  read-only checks, uncertainty, cited evidence details, concrete
  resources/remediation, retained citation ids, mobile no overflow, zero
  console/page errors.
- Topology did not perform the deactivation themselves this time (per
  the process-deviation correction) — this session executed
  `az containerapp revision deactivate -g aiops-dev-rg -n aiops-dev-api
  --revision aiops-dev-api--pr287-36354b89` directly, releasing the
  rollback hold that had protected `pr287` since PR #287's deployment.
- Final API revision state: `pr291` (Healthy, 100%, live),
  `pr290-c429dd82` (Healthy, 0%, retained as immediate rollback per
  policy — most recent prior healthy revision), `pr289-c611c145`
  (Healthy, 0%, further-back superseded). `pr287` deactivated (no
  longer Active). Web unchanged: `0000247` (Healthy, 100%, live).
- This closes the PR286→PR287→PR288→PR289→PR290→PR291 topology-narration
  reliability remediation thread. `pr287`'s multi-deploy rollback hold,
  held continuously since its own acceptance uncertainty, is now
  released following confirmed 5/5 reliability on PR291's fix chain
  (word-boundary mutation detection → next_check sanitization →
  uncertainty/summary scope narrowing).

## PR #293 — Fabric Data Agent grounding for Operations Copilot (2026-09-23)

- Change: `feat(copilot): ground specialists through Fabric Data Agent`. Pivots
  Operations Copilot to thin-client requests and generation-pinned Fabric Data
  Agent grounding behind existing governed `fabric_iq_*` specialist tools.
  Scope: `docs/runbooks/copilot-orchestration-rollout.md`,
  `src/api/runtime.py`, `src/fabric/gold_grounding_client.py`,
  `src/operations/tools.py`, `tests/test_fabric_iq_governance.py`,
  `tests/test_gold_grounding_client.py`,
  `web/src/app/inventory/page.test.tsx`,
  `web/src/components/ui/CopilotDrawer.tsx` (+ test) — 9 files.
- Feature remains OFF by default: activation requires
  `AIOPS_ENABLE_FABRIC_IQ=true`, `AIOPS_ENABLE_FABRIC_DATA_AGENT_GROUNDING=true`,
  `FABRIC_GOLD_GROUNDING_AGENT_ID`, optional
  `FABRIC_GOLD_GROUNDING_TOOL_NAME`. No such env vars were set on this
  deployment, so the change is dormant in production pending a separate
  activation decision. Documented RLS/OBO production gate preserved; no Data
  Agent mutation/publication authority granted.
- CI status: PR #293 backend/frontend/security-scan checks failed in ~2-3s
  with no log output — the known account billing/spend-limit infra failure
  pattern (not test evidence), consistent with prior PRs in this cycle.
- Independent local validation (fresh clone `/tmp/aiops-pr293-verify`, merged
  against `origin/main`, 0 behind):
  - `pytest -p no:phoenix -q tests/test_fabric_iq_governance.py
    tests/test_gold_grounding_client.py tests/test_api_runtime.py
    tests/test_fabric_commands.py` => 21/21 passed.
  - `ruff check` on changed files: clean. `compileall`: clean.
    `git diff --check`: clean. `git diff --stat` confirmed exact 9-file scope
    (426 insertions / 164 deletions).
  - Frontend: `vitest run` on `CopilotDrawer.test.tsx` and
    `inventory/page.test.tsx` => 49/49 passed (React `act()` warnings only,
    not failures). ESLint clean. `tsc --noEmit` clean. `npm run build`
    succeeded.
- Merge: admin-merged via `gh pr merge 293 --admin --merge` given exact-diff
  match plus exhaustive independent validation and the known CI infra-failure
  pattern. Merge commit `41f72d7fe8137fddfecd1e4c3755f0151fb7f607`.
- Build:
  - API: `aiopsdevacrg6ludc.azurecr.io/aiops-api:fabric-iq-grounding-41f72d7fe-20260923T200930Z`,
    digest `sha256:0a854bd301806563cc001b985f32f9a1240d4f429890f2a20a118a68b282378f`.
  - Web: `aiopsdevacrg6ludc.azurecr.io/aiops-web:fabric-iq-grounding-41f72d7fe-20260923T200930Z`,
    digest `sha256:b91beb74f6628b11997e7fc3ee83cb3c5804c15aace1e4d80bd1ba4495fdd857`.
- Deploy:
  - API: `az containerapp revision copy` from prior active revision
    `aiops-dev-api--pr291-0835e454`, new revision
    `aiops-dev-api--pr293-0a854bd3`, `AIOPS_SOURCE_REVISION` set to the merge
    SHA. CPU/memory preserved automatically at 4.0 CPU / 8Gi. Revision reached
    `Healthy`/`RunningAtMaxScale`; promoted to 100% traffic via
    `az containerapp ingress traffic set`. Per explicit user direction to keep
    the API on a single active revision, prior revision
    `aiops-dev-api--pr291-0835e454` was deactivated after promotion (no
    lingering 0%-traffic rollback revision this cycle).
  - Web: `az containerapp update --name aiops-dev-web --image
    aiops-web:fabric-iq-grounding-41f72d7fe-20260923T200930Z` (Single revision
    mode). New revision `aiops-dev-web--0000248` reached `Running`/100%,
    prior revision `aiops-dev-web--0000247` auto-deprovisioned.
- Post-deploy smoke checks (production ingress):
  - API `/health` and `/ready`: `status: ok`, `readiness: ready`; required
    providers `copilot` and `exposure_query` both `ready`/`loaded`.
  - Web `/`, `/network`, `/inventory`: HTTP 200.
- Final state: single active API revision
  `aiops-dev-api--pr293-0a854bd3` (100%, Healthy); single active web revision
  `aiops-dev-web--0000248` (100%, Running).

## API Fabric readiness hotfix — PR #295 follow-up (2026-09-24)

- Trigger: after PR #295 merged, production API readiness became sensitive to
  transient Fabric/OneLake capacity failures. The live PR293 API revision had
  Fabric enabled, but `/ready` could return degraded/503 because
  `exposure_query` was classified as a process-readiness-required provider.
  Route-level behavior already fails closed, so Fabric-backed data availability
  should remain visible without making the API process unroutable.
- Source change: commit
  `56dd66146271aec40bbc3315ff3ae50ccc6c2bff`
  (`fix(api): keep Fabric outages from blocking readiness`) changes
  `src/api/runtime.py` so Fabric-backed providers, including
  `exposure_query`, are optional for process readiness. Tests in
  `tests/test_api_runtime.py` assert that `exposure_query` remains configured
  and observable while aggregate readiness stays `ready`.
- Process deviation: the hotfix was accidentally committed and pushed directly
  to `main` instead of going through a PR branch. The diff was exactly
  `src/api/runtime.py` and `tests/test_api_runtime.py`, and the deviation was
  accepted only because production readiness was actively impacted. Future
  source changes should return to the normal branch/PR path.
- Local validation before rollout:
  - `pytest -p no:phoenix -q tests/test_api_runtime.py
    tests/test_api_providers.py` => 94/94 passed.
  - `ruff check src/api/runtime.py tests/test_api_runtime.py` => clean.
  - `python3 -m compileall src/api/runtime.py tests/test_api_runtime.py` =>
    clean.
  - `git diff --check` => clean.
- Build:
  - ACR run `cr11k`.
  - Image:
    `aiopsdevacrg6ludc.azurecr.io/aiops-api:fabric-readiness-56dd6614-20260924T170000Z`.
  - Digest:
    `sha256:a64627c0fd44e5492d5c4fd449f3987dabd1f9b5543b554967fa6963c3c4f68f`.
- Candidate cleanup: the first candidate revision
  `aiops-dev-api--pr295-readiness-56dd6614` unexpectedly inherited
  `AIOPS_ENABLE_FABRIC=false`; it was deactivated before any traffic was moved.
  The corrected candidate explicitly set `AIOPS_ENABLE_FABRIC=true`.
- Deployment:
  - Correct API revision:
    `aiops-dev-api--pr295-readiness-fabric-on`.
  - Image:
    `aiops-api:fabric-readiness-56dd6614-20260924T170000Z`.
  - `AIOPS_SOURCE_REVISION=56dd66146271aec40bbc3315ff3ae50ccc6c2bff`.
  - `AIOPS_ENABLE_FABRIC=true` preserved.
  - `AIOPS_ENABLE_FABRIC_IQ=false` preserved.
  - CPU/memory preserved at 4.0 CPU / 8Gi.
  - Revision-scoped `/health` and `/ready` returned `status=ok` and
    `readiness=ready` before promotion.
  - Promoted to 100% traffic, then prior active revision
    `aiops-dev-api--pr293-0a854bd3` was deactivated to satisfy the user's
    single-active-API-revision request.
- Post-deploy public validation:
  - API `/health`: `status=ok`, `readiness=ready`.
  - API `/ready`: `status=ok`, `readiness=ready`.
  - Required `copilot` provider: configured, required, `ready`, loaded.
  - `exposure_query`: configured, `required=false`, `ready`, loaded.
  - `fabric_iq`: configured, `required=false`, loading/not loaded; Fabric IQ
    remains disabled by environment flag.
- Final API state: exactly one active API revision,
  `aiops-dev-api--pr295-readiness-fabric-on`, `Healthy`,
  `RunningAtMaxScale`, 100% traffic, image digest
  `sha256:a64627c0fd44e5492d5c4fd449f3987dabd1f9b5543b554967fa6963c3c4f68f`,
  Fabric enabled, Fabric IQ disabled.

## PR #298 — stop hourly inventory refresh wiping entity-derived tables (2026-09-29)

- Change: `fix(inventory): stop hourly refresh wiping entity-derived tables`
  (head `f2f38ca0d2298c3b62998f59c4d1e1f8434aedd2`, 6 files). The hourly
  Fabric pipeline "Inventory Refresh" (`d879af68-e020-4c6f-941e-aa9967544b13`)
  POSTs to the API `/api/v1/inventory/refresh`; the API replayed an
  inventory-only combined generation through the full Fabric sync, overwriting
  every entity-derived bronze/silver/ontology table with 0 rows while reporting
  `completed`. The fix replays an entities-aware combined snapshot (inventory
  datasets pinned) and adds two pre-commit guards in `src/fabric/sync_service.py`
  that abort a collapsed entity projection over live inventory.
- CI: backend/frontend/security-scan failed in ~2s (known billing/admission
  infra failure, not test evidence).
- Independent local validation (worktree at `f2f38ca0d`, 0 behind main):
  `tests/test_fabric_sync_service.py`, `test_inventory_refresh_multi_connection.py`,
  `test_inventory_refresh_cli.py`, `test_inventory_refresh_endpoint.py`,
  `test_inventory_refresh_pipeline_script.py`, `test_onboarding_activation.py`,
  `test_api_runtime.py` => all passed; Ruff clean; `git diff --check` clean.
  Reviewed `_RefreshedConnectionSources` shim against
  `publish_combined_snapshot` (uses only `registry.get` and
  `sync_coordinator.connection_output_dir`).
- Merge: admin-merged with `--match-head-commit`, merge commit
  `8e7785406155b06e208053f11f8bd2c5decdf4f8`. This build also ships
  previously merged-but-undeployed #296/#297 (ops semantic evolution enabled in
  baked `fabric.config.deploy.yaml`, adapter `noop`, no live semantic-model
  publish).
- Build: ACR run `cr11n` (first attempt `cr11m` failed only on the missing
  `AIOPS_SOURCE_REVISION` build-arg guard), image
  `aiopsdevacrg6ludc.azurecr.io/aiops-api:inventory-wipe-fix-8e778540-20260929T012826Z`,
  digest `sha256:c6463b9206c20d80c9749cc4b1b546bdb7c5b8b7f7ac86a467c84f631ffb6108`.
- Deploy: revision `aiops-dev-api--pr298-8e778540` copied from
  `aiops-dev-api--pr295-readiness-fabric-on` with explicit
  `AIOPS_ENABLE_FABRIC=true`, `AIOPS_ENABLE_FABRIC_IQ=false`,
  `AIOPS_SOURCE_REVISION=8e778540…`, 4.0 CPU / 8Gi. Revision-scoped and public
  `/health` and `/ready` returned 200 `ok`/`ready`. Promoted to 100%; prior
  revision deactivated (single active API revision).
- Live condition at deploy: Fabric capacity `aiopsdevcapg6ludc` (F4,
  `6616292a-d806-4f20-91c0-5e035fa3c1b4`) is **Paused**. OneLake returns
  404 "capacity is currently not available", so `inventory`, `exposure_query`,
  `exposure_read_port`, and `fabric_iq` providers are unavailable (optional;
  readiness unaffected). The prior revision was serving a pre-outage in-memory
  inventory cache; the new revision cannot reload it until capacity resumes.
  The hourly pipeline cannot run while paused, so no further wipes occur.
- Pending: recovery verification (`bronze_resources` > 0 rows,
  `ontology_entities` advancing past v108 / 133 rows in lakehouse
  `6317eaf6-e597-4b4e-a07d-c53027c01feb`) is blocked until the capacity is
  resumed and the first hourly run completes on this revision. Capacity resume
  was not performed (cost/ownership decision).

## PR #300 — async inventory refresh endpoint (2026-09-30)

- Merge: `1e1b751b160f33cb16481cf6c43653beb5801f8b` (admin merge, `--match-head-commit`;
  GitHub Actions blocked by billing, local validation: inventory refresh
  endpoint/pipeline_script/multi_connection/cli, api_runtime, fabric_sync_service
  tests pass; Ruff and `git diff --check` clean).
- Build: ACR run `cr11p`, `aiops-api:inventory-refresh-async-1e1b751b-20260930T000724Z`,
  digest `sha256:9c9b7d0d5ca105e69e8ea039ffb1331aa98c2d405c2d89d182de5b4347e0eba2`.
- Deploy: revision `aiops-dev-api--pr300-1e1b751b` copied from pr298 with explicit
  `AIOPS_ENABLE_FABRIC=true`, `AIOPS_ENABLE_FABRIC_IQ=false`, 4 CPU / 8Gi; promoted to
  100%, pr298 deactivated (single active revision). `/health` and `/ready` 200.
- ACA jobs: all 10 jobs moved to the same digest by the Fabric session via
  `az containerapp job update --image` (image-only change). Future API deploys must
  update jobs too (or set Terraform `api_image_digest`).
- Fabric pipeline `d879af68-e020-4c6f-941e-aa9967544b13` re-pushed with
  `push_inventory_refresh_pipeline.py`: activity timeout `0.03:00:00`,
  `disableAsyncPattern=false`; hourly schedule `7309b4ec` unchanged.
- Recovery verified: run `refresh-a4ec87fd-72ec-4788-be90-58f97d2bcf85` succeeded
  (00:20:15Z–00:49:23Z, 1747.8s); scheduled pipeline job `c228873f` adopted it and
  Completed. Entities generation `activation-13dc9994-72f3-4926-ad57-39ea36a60628`
  (12,993 entity rows) published. SQL counts: `bronze_resources`=171,
  `silver_vm_inventory`=2, `silver_server_inventory`=3, `ontology_entities`=1715.
  This closes the PR #298 pending recovery verification.
- Known follow-up (non-blocking): `GET /inventory/refresh/latest` while running sets
  `Location` to `/refresh/latest/{run_id}`; pipeline polls the POST Location and is
  unaffected.

## PR #303 — Operations Copilot page insights (2026-10-02)

- Merge: `7c9eb66297fb482ef84841fabe1f913d3c078172`, web-only. Local
  validation: 842/842 web tests, `npm run lint:fix`, `tsc --noEmit`,
  `npm run build`, and `git diff --check` passed. GitHub security scan passed;
  CI backend failed on two pre-existing unused `noqa` directives in
  `src/onboarding/sync.py`, while CI frontend tests lacked Python `fastapi`.
- Build: exact merge-commit `web/` archive, ACR run `cr11r`, tag
  `aiops-web:copilot-page-insights-7c9eb6629-20261002T012034Z`, digest
  `sha256:cbbe6750f301289b46dbd9b6aec3493f17635d521fe9890fadfc3b779bcaebaa`;
  Entra public build arguments were taken from the existing local configuration.
  An earlier ACR run `cr11q` selected the wrong Dockerfile and failed before
  producing an image; it was not deployed.
- Deploy: `aiops-dev-web--0000249` uses the immutable digest, Healthy and
  Running with 100% traffic in Single revision mode. Previous revision
  `0000248` is at 0%. API remains `aiops-dev-api--pr300-1e1b751b` at 100%;
  no API, Network, APIM, MCP, or job configuration was changed.
- Public route checks returned HTTP 200 for `/`, `/exposure`, `/situations`,
  `/network`, and `/api/config`. Authenticated browser rendering of the
  insights panel remains **unverified**: the browser stopped at organizational
  MFA approval. The image is the one built from the locally tested source,
  but HTTP 200 alone does not prove the panel rendered for a signed-in user.

## PR #305 — Operations Copilot insights accuracy (2026-10-02)

- Merge: `2871bab9df70c163590b189d33a5567f36d0b08d`, web-only. Local
  validation: 845/845 web tests, `npm run lint:fix`, `tsc --noEmit`,
  `npm run build`, and `git diff --check` passed. GitHub security scan passed;
  backend CI failed on unchanged unused `noqa` directives and frontend CI
  lacked Python `fastapi` and `opentelemetry` dependencies for its parity tests.
- Build: exact merge-commit `web/` archive, ACR run `cr11s`, tag
  `aiops-web:copilot-insights-accuracy-2871bab9-20261002T070012Z`, digest
  `sha256:30f12ec34ce718632d3d925fbd1a9bd9e425510317aee1831c10f3393d42008f`.
- Deploy: `aiops-dev-web--0000250` uses the immutable digest, Healthy and
  Running at 100% traffic; `0000249` is at 0%. `/`, `/identity`,
  `/remediation`, `/network`, and `/api/config` returned HTTP 200. API remains
  `aiops-dev-api--pr300-1e1b751b` at 100% on its previous image; no API,
  Network, APIM, MCP, or job deployment/configuration change was made.
- Authenticated browser smoke: `/`, `/identity`, and `/remediation` each
  displayed "Waiting for page evidence to load…" before leaving the loading
  state. Home then displayed deterministic cited findings with
  `Synthesis confidence: medium` and network/vulnerability/patch/incident
  specialists. Identity displayed deterministic cited findings with
  `Synthesis confidence: medium` and `identity_access` specialist. On both,
  Foundry narration failed response validation and the UI explicitly showed
  deterministic evidence instead. Remediation displayed `Insight unavailable`
  because `remediation_opportunities` was unavailable and its visible subset
  incomplete; it showed `Specialists: remediation` but no confidence line or
  fabricated insight. Thus the rendering and fail-closed states are verified,
  but a successful remediation insight with confidence provenance is **not**
  verified against live complete evidence.

## PR #307 — Copilot backend accuracy (2026-10-02)

- Merge: `b1dda04c10f19bd85b656c60712e506de36b9e1c`, backend-only, including
  the already-merged #302 polling-header correction. The revised PR head
  `7caf1c2fa450df0a62bc00d5648d534ddf005204` addressed review findings
  around corrected plans, public connections results, and substantive evidence.
  Changed-file Ruff, diff check, and 27 selected regressions passed. Broader
  Copilot tests required a process-local compatibility shim for an outdated
  authorization test fixture; excluding four independently existing failures,
  the rest passed. GitHub security scan passed; backend CI failed on two
  unchanged unused `noqa` directives and frontend CI lacked Python dependencies.
  Neither failing CI job is counted as passing validation.
- Build: exact merge-commit source archive, ACR run `cr11t`, image
  `aiops-api:copilot-accuracy-b1dda04c-20261002T0746Z`, immutable digest
  `sha256:c8a799a390c97fa2894d7c95b1fdf628207526ac2eea8dee8033c734357fe46f`.
- Cutover waited for in-process inventory refresh
  `refresh-b026e3ca-fdf8-4243-90cc-d49fcb6d5c84` to return HTTP 200 at
  08:01:45Z. The new revision `aiops-dev-api--pr307-b1dda04c` copied the
  previous revision's configuration, changing only image and
  `AIOPS_SOURCE_REVISION`. Dedicated `api-d4` scheduling initially reported
  insufficient capacity, then autoscaled within its existing 0–4-node limit;
  no profile setting or quota was changed. Its replica became Running/Healthy,
  revision-specific `/health` and `/ready` returned 200, and canary traffic
  was staged at 10% before promotion to 100%. It retains 4 CPU / 8 GiB.
  Prior `aiops-dev-api--pr300-1e1b751b` remains Active/Healthy at 0% for
  rollback. The rollout mode and retired runtime authorization gate are
  unchanged; no new protected-tree enablement was performed.
- All ten ACA jobs moved from the #300 image to the same #307 immutable
  digest; each before/after job template, configuration, identity, and tags
  was compared, with only its image differing. API `/health` and `/ready`
  returned 200 on the public and revision-specific hosts. Unauthenticated
  `/api/v1/copilot/tools` returned the expected 401, not an API error.
  Web `aiops-dev-web--0000250` still serves the #305 digest at 100%, and
  `/`, `/identity`, `/remediation`, and `/network` return 200. Azure MCP
  `aiops-dev-azure-mcp--0000100` remains at 100%; no web, Network, APIM, MCP,
  Fabric, Terraform state, or RBAC change was made.
- Live authenticated F4/F5/F6 and Foundry narration outcomes have **not**
  been exercised after this deployment. Local regressions verify the
  fail-closed behavior, but public health/401 probes do not establish an
  authenticated Copilot result. Phase 4 digest-to-workload traversal,
  qualified 100k benchmark, and canary/rollback exercise remain deferred.

## PR #389 bounded API release - 2026-10-25

Status: Validated
Recipe: AZCLI, existing Container App image-only update.

Direct user instruction "fix the authorization" resolves the preceding API
deployment authorization hold for this bounded release. No application RBAC,
Entra policy, authentication bypass, or infrastructure grants will be changed.

- [x] Verify exact merged main and successful CI.
- [x] Snapshot protected app/job templates, identities, configuration and roles.
- [x] Build the API image from exact merged source, without dirty workspace files.
- [x] Qualify the immutable image offline with retained full Catalog reports,
      no credentials, no config loading, no network, and unchanged input bytes.
- [x] Compare packaged source and run targeted regressions.
- [x] Validate readiness/provider parity before image-only promotion.
- [x] Verify API readiness and protected-state equality after promotion.
- [x] Seal evidence for independent review.
- [x] All validation checks pass:
      - Azure CLI/auth and existing target verified; no infrastructure template
        deployment or what-if required for an image-only revision.
      - Container image build and exact-image offline replay pass.
      - Applicable Azure policy assignments checked.
      - Existing managed-identity ACR pull roles verified without provisioning.

Target: existing subscription `890c9bfc-d09c-4143-9ce5-465e75e3eecc`,
resource group `aiops-dev-rg`, region `australiaeast`, app `aiops-dev-api`.
Preserve existing API 4 CPU/16 GiB and all configuration, identities, roles,
registries, web, supporting apps and six jobs. No Terraform apply, new resources,
provider repair, scheduler/publisher operation, or fresh Fabric reads.
Rollback is the previous immutable API image; keep existing rollout mode.
Earlier user-owned plan content is retained unchanged.

### Validation Proof

2026-10-25 preparation: exact main f7043f1724328c7cdf502cd9f90bff74fde48092;
CI run 40177283679 completed successfully. All 86 coupled Catalog tests passed.
Retained reports match SHA256 807de7aa... and 34aa2dec....
Protected-state hashes saved in session api389-release/before-state.json.
Baseline health/ready HTTP 200; existing exposure_read_port/fabric_iq unavailable
and Copilot degraded remain limitations, not new release defects.
2026-10-25T10:53:57Z: ACR run cr1u succeeded, exact-source API image digest
sha256:0ab034063b20fb5a50c1bb7c25f19c2f01dbe2fd4a9c139b196c7d0ec127fd39.
`docker run --network none --read-only ... python /evidence/qualify.py`
passed: 483 packaged source/config/skill hashes equal exact main; build metadata
matches f7043f1724328c7cdf502cd9f90bff74fde48092; guarded saved-report replay
equals accepted delta, ten unchanged and all other result counts zero.
Actual `python -m fabric.catalog_compare_cli` output equals guarded output.
Both input hashes unchanged. Network/socket calls, runtime config loading,
credential construction and HTTP client construction were forbidden. Existing
fabric package imports auth/client libraries; no claim of import isolation.
Initial over-strict import guard rejected that existing package import and was
corrected to the established no-provider-access contract; no production edits.
`az policy assignment list` at the target RG with inherited scope: no assignments.
Static registry identity contract reviewed; existing AcrPull verified at the
registry for apps identity. Existing credential-based pull configuration is
preserved, not migrated. No new role or infrastructure provisioning required.
No Bicep/Terraform deployment validation/what-if applies to this image-only
update; no infrastructure templates are being deployed.
2026-10-25T11:17Z: candidate aiops-dev-api--r389-f7043f17 became Healthy,
RunningAtMaxScale, one ready replica with zero restarts. All baseline-ready
providers were ready before promotion. Existing fabric_iq/exposure_read_port
unavailable and deferred providers remain explicit; no full-health claim.
Promoted r389 to 100%; public /health and /ready HTTP 200. R388 remains active
at zero traffic for immediate rollback. Web r19, other apps, six jobs,
configuration, identities and role-assignment hashes equal the protected baseline.
Capacity recovery: deactivated obsolete zero-traffic/unlabelled r381 and r385.
The profile remains D4 maximum three nodes and API remains 4 CPU/16 GiB.
An early restart temporarily required a surge slot; the second obsolete revision
was retired to let that restart converge. No capacity expansion was performed.
Exact-image qualification/release evidence is sealed in session
files/api389-release/receipt.json and evidence-sha256.json. This release does not
include the separate unmerged patch-journey repair and does not authorize vm1 UAT.

## PR #390 coordinated API and web repair release - 2026-10-25

Status: Validated
Recipe: AZCLI, existing Container Apps image-only update.

### Scope and requirements

MODIFY existing Python API and Next.js web images only. No new infrastructure,
dependency changes, identity grants, provider repair, scheduler/publisher/native
operations, fresh Fabric Catalog reads or patch execution. User-directed
engineering/release loop continues with exact-head CI and compatible API/web
rollout; source admission alone is not deployed acceptance.

Target: subscription `890c9bfc-d09c-4143-9ce5-465e75e3eecc`, resource group
`aiops-dev-rg`, Australia East. Preserve API 4 CPU/16 GiB, web 0.5 CPU/1 GiB,
D4 maximum three nodes, all environment/configuration/roles and six jobs.
Current rollback baselines: API r389-f7043f17 and web 0000019.

### Execution and verification

- [x] Review both sealed handoffs and verify all 27 exact file hashes.
- [x] Independent 106 backend plus 87 Catalog tests, Ruff, 1943 web tests,
      lint:fix, strict TypeScript and production build passed.
- [x] Require exact e7b66f44 CI and merge; archive immutable merged main.
- [x] Capture fresh protected-state and provider/readiness baselines.
- [x] Build API and web once from the same merged source.
- [x] Qualify exact-image sanitized nesting failure and unchanged offline replay.
- [x] Prepare compatible zero-traffic API; require readiness/provider parity.
- [x] Promote compatible API then web, preserving immediate rollback.
- [x] Verify serving image/traffic and protected state.
- [x] Complete independent bounded authenticated read-only UI closure.
- [x] Seal evidence and send exact identities to both owners for acceptance.

### Validation Proof

2026-10-25T15:12Z: CI40204815445 exact e7b66f44 all eight checks successful;
merged af31bc41e03b5e6deeffb2e5c4e69f489543b9a2, exact archive retained.
2026-10-25T15:19Z: ACR cr1w API build and cr1v web build succeeded once each.
API digest sha256:6e727159db4564a0c0d3a9660e48c87309c9e9ab52f88b4d8af95e551e3a6db6;
web digest sha256:f2e3487dc5e5fdbf66018abc072090de3c7e89c203234d851fb860b22d49319c.
`docker run --network none --read-only --cap-drop ALL --security-opt
no-new-privileges ... qualify.py` passed all 483 source hashes/build provenance,
sanitized live-CLI invalid nesting (exit1, empty stdout, configuration JSON),
and retained valid offline replay (ten unchanged, all other counts zero).
Both report hashes unchanged. Credential/HTTP/socket access forbidden; live CLI
still reads its existing packaged local config, offline config access forbidden.
The initial depth2000 fixture produces TypeError on Python3.12.15 rather than
decoder recursion; depth10000 exercises the actual normalized recursion failure.
Only the session qualification fixture changed, not production source/image.
Protected baseline saved; target subscription/RG/region match established values.
Applicable inherited Azure policy assignment list empty. Existing registry
credentials/identity/RBAC remain unchanged; no provisioning or what-if applies.
User unavailable at target/plan confirmation; established user-directed
autonomous release-loop authorization and same target retained.

- [x] All validation checks pass:
  - Existing AZCLI target, policies, registry authentication and preserved roles.
  - Source/CI, production builds and immutable image qualification.
  - No infrastructure template deployment or new resource required.

2026-10-25T15:30Z: API r390-af31bc41 and web 0000020 are Healthy and each
serves 100% traffic, one ready replica/zero restarts. API /health and /ready,
web / and /api/config HTTP 200. All baseline-ready providers remain ready;
protected config/resources/roles/capacity/unrelated apps/six jobs equal baseline.
No obsolete revision deactivation or capacity change was needed in this release.
API r389 remains active at zero traffic. Web uses existing Single revision mode;
the prior web 0000019 revision is not listed after replacement. Its immutable
digest fde9a4478dffaca4da746a697e6e45f71322f7a68125800a6bb1c5bf9f2dd461
is retained in the registry for image-based rollback, not instant traffic switching.
Exact-image recursion proof now checks ValueError.__cause__ is RecursionError
and the live CLI file bytes equal the parser fixture. Actual unmocked module
entrypoints match guarded outputs. Sealed receipt files/release390/receipt.json
SHA256 d52ebc1ddc017c292c4cc28798c496b78a703c1b6449a10a701e1abea549a2f2.
Fabric independently accepted all 32 sealed hashes, exact source/image,
normalization branch, unchanged replay and protected-state/provider parity.
UI authenticated read-only closure passed at 375/1912/2560 against actual
serving identities; all 14 independent artifact hashes verified. Exact CVE
rejects unrelated VM plans, KB requires deliberate target selection and exact
2267602 snapshot, unknown evidence blocks review/approval/run consistently.
Known attack-path404, unavailable MSRC, findings-loading capture and ten aborted
advisory/navigation requests remain disclosed; no universal UI/provider all-clear.
Final closure files/release390/closure.json SHA256
cc99892b7bd14661988327f39a35baeb21318e0052ef5d32478ad5d701a71661.
Bounded release and independent acceptance complete; no patch execution occurred.

## Publication authority permission commissioning - 2026-10-30

Status: Deployed - permission commissioning verified only.
This is separate from the completed application release; authority runtime
and publication trust activation remain disabled.

Authorization: the user directed unblocking and granting the necessary MI
permissions. The plan was presented through ask_user; it returned that the user
was unavailable and to work autonomously. The bounded separate-identity option
was selected under that existing direction, not as a fabricated explicit vote.

Purpose: satisfy the user's request to give the MI the necessary publication
authority permissions without substituting a publisher, coordinator, or broker
identity, generating signatures, or enabling publication.

Verified target:
- Subscription: `890c9bfc-d09c-4143-9ce5-465e75e3eecc`; Australia East.
- Identity resource group: `aiops-pub-dev-rg`.
- Manual proof-job resource group: `aiops-pub-dev-service-rg`.
- Fabric workspace: `4938f885-3e79-41b1-810a-80b55c01dbb7`.
- SQLDatabase: `b003a6fb-eb2a-4226-b079-6033be2ff354`, live type SQLDatabase.
- SQL database: `aiops_publication_control_dev-b003a6fb-eb2a-4226-b079-6033be2ff354`.
- SQL server: `o45cujtupwcencjxrf6zruvbpi-qx4dqslzh2yudaikqc2vyao3w4.database.fabric.microsoft.com,1433`.
- Capacity is Active. CLI-authenticated encrypted SQL catalog reads succeed;
  the current caller can manage users and roles.
- Live RecordGrant, Revoke, ReadControl, and ReadAttempt procedures exist.
  The authority and reader roles do not yet exist. Existing broker and verifier
  roles/memberships must remain untouched.

Proposed bounded changes:
1. Create dedicated UAIs `aiops-pub-dev-authority-id` and
   `aiops-pub-dev-reader-id`. Record each principalId, clientId, and ARM ID.
2. Grant each identity exactly Read on this SQLDatabase through its item-sharing
   UI, with all additional data/analytics/OneLake permissions unchecked.
   Do not grant workspace access.
3. Add only the missing `publication_authority` and `publication_reader` SQL
   roles. Grant authority EXECUTE on RecordGrant/Revoke only, reader EXECUTE
   on ReadControl/ReadAttempt only, and deny SELECT/INSERT/UPDATE/DELETE on
   SCHEMA::publication for both. Create contained users using each UAI client
   ID as binary16 SID and add exactly the corresponding single role membership.
   Do not run packaged bootstrap scripts or modify existing procedures/tables.
4. Create a manual-only `aiops-pub-dev-authority-check` job in the existing
   isolated publication environment. Bind the two new UAIs plus the existing
   registry-pull identity; do not attach authority to an existing worker/broker.
   Reuse immutable broker image
   `sha256:6d9478ab8877efb97c92e7c39d40dce92e589f61416a91b7a9b4aa61795195bd`
   for a finite Python ODBC18/TLS permission/read probe, not the broker server.
   Limit to one replica, 0.5 CPU/1 GiB, 180 seconds, zero retries, no schedule.
5. Verify item Read-only grants, exact SID/client bindings, memberships,
   effective object EXECUTE rights, direct-data denials, job identity binding,
   and separate MI read calls. Never invoke RecordGrant or Revoke as a test.
   Preserve and compare publication table counts before/after.

Excluded: app rebuild/deployment; source handoff integration; issuer/approver
key creation or enrollment; trust activation; Key Vault changes; retention or
Blob changes; AuthorityGrant/Attempt/session mutations; schema bootstrap;
broker/session/admin/DDL permissions for either new identity.

Corrected preflight finding: publisher principal
`b0f361ce-de36-417a-a2e9-5488743ee847` already has Key Vault Secrets User.
That assignment is not changed. Its principalName is its client ID, not its
principal/object ID. This does not populate missing trust configuration.

- [x] Verify exact live item, connection properties, capacity, and SQL contracts.
- [x] Present the bounded plan and record the autonomous continuation decision.
- [x] Validate the bounded plan and selected immutable proof image.
- [x] Provision separate identities and least-privilege item/SQL access.
- [x] Run identity-bound read-only verification and preserve receipts.

Permission-commissioning validation steps (AZCLI, no template deployment):
- [x] All validation checks pass:
  - [x] Core CLI authentication, exact target, management permissions, and
    object-scoped SQL contract checks.
  - [x] Build verification: reuse the existing verified immutable broker image;
    no application changes, container build, or Bicep/template deployment applies.
  - [x] Azure Policy validation for both isolated resource groups.
  - [x] Static role review: two exact object grants per identity, direct-DML
    DENYs, no workspace/admin/broker membership, unchanged registry-pull role.

### Permission commissioning validation proof

Live Fabric REST returned the exact workspace and SQLDatabase type/server/name.
The capacity is Active F8. After one transient database-unavailable response,
Go sqlcmd with ActiveDirectoryAzCli and encryption successfully read the
commissioned database and confirmed ALTER ANY USER / ALTER ANY ROLE for the
current operator. No operator elevation was performed. Live procedure bodies
match the intended authority/read boundaries. Existing broker/verifier grants
and memberships were read and will remain unchanged.

The immutable image digest exists in ACR and is already configured on the
isolated broker and manual worker-probe job. No image build or application
deployment is part of this permission operation. No Bicep/ARM template is
submitted, so template build/validate/what-if are not applicable. The existing
hosting environment and registry-pull identity are reused without role changes.
Inherited Azure Policy assignments for `aiops-pub-dev-rg` are empty.
Inherited assignments for `aiops-pub-dev-service-rg` are also empty. The
operator's existing effective management actions cover both scopes, with no
notActions; no operator role change is required.

Static role verification: the proposed authority and reader have separate
SQL users, exactly two corresponding procedure grants each, four explicit
schema-level direct-data DENYs each, and item Read only. No Azure resource
roles are created for these identities. The job reuses the already assigned
registry-pull identity solely for the existing immutable image. There are no
new Bicep/Terraform role-assignment resources to review. No validation errors
remain; the initial SQL availability response cleared without a capacity or
database mutation. Local ODBC library loading failed, so the authenticated
catalog inspection used the supported Go sqlcmd alternative.

Commissioned identity/access readback:
- Authority UAI `aiops-pub-dev-authority-id`, principal
  `20c5be48-acf4-45e3-937e-f0d25791fb1a`, client
  `dafc75c0-45b5-4b6a-b761-da231fb6239d`.
- Separate reader UAI `aiops-pub-dev-reader-id`, principal
  `484638f7-e024-4dd3-9ca7-9ca43ec5c87d`, client
  `ad01e219-c3f5-40c7-85c3-7060a86a5bd7`.
- Both ARM IDs are under the specified subscription and
  `resourceGroups/aiops-pub-dev-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/`
  with their corresponding identity names.
- Entra readback confirms both are ManagedIdentity service principals with
  those exact client/object mappings.
- Fabric Manage permissions shows exactly Read and no workspace role for
  each identity. All three additional-data permission checkboxes were
  unchecked. REST workspace role readback and Azure role-assignment readback
  for both new principals are empty.
- Targeted transaction created only the two missing roles, two client-SID
  users, exact procedure grants, direct-DML DENYs, and one corresponding role
  membership per identity. No packaged bootstrap was executed.
- Publication counts remain Target1; AuthorityGrant/Attempt/Revocation/
  Operation/Audit/Receipt0. The proof job is manual-only and provisioned
  successfully with the authority, reader, and existing registry-pull UAIs.
- Initial permission probe reached the intended direct-SELECT denial after
  all authority effective-permission checks passed. Fabric uses native error
  373 for that denial; the measurement initially expected only SQL Server
  229. Only the probe assertion was corrected, with exact SQLSTATE/message
  checks; the first failed measurement remains retained.

Final proof: execution `aiops-pub-dev-authority-check-445tpwe` Succeeded,
2026-10-30T09:14:02Z through 09:14:44Z. Both distinct real MI tokens mapped
to the correct contained SQL users/client SIDs. Authority can execute only
RecordGrant/Revoke; reader can execute only ReadControl/ReadAttempt. Direct
SELECT was denied with Fabric native373 for both; schema-wide EXECUTE,
direct DML, DDL, broker/verifier/admin rights were absent. Normal contained
user CONNECT grants were read back, with no other direct user grants.
Reader ReadControl returned the actual target at epoch0/revision0 with no
active attempt. ReadAttempt was authorized but correctly rejected a
nonexistent retained attempt with51012; this is not retained-data success.
No RecordGrant/Revoke procedure was invoked. All seven publication table
counts match the baseline exactly, and no proof execution remains Running.

The proof exposed token-based ODBC pooling reusing the authority session
for the separate reader. Pooling was disabled before either proof connection;
the subsequent live identity/SID checks succeeded independently. The final
probe also drains TDS result sets to observe ReadAttempt's deferred error.
Three failed measurement attempts and their exact source/config remain
retained, not represented as permission successes.

Final probe SHA256:
`a72f95ff8202e675be44da5e0d53d3b02fb6cb16ecdcd8e5c5b6518696645082`.
Evidence root:
`/Users/jasonmba/.copilot/session-state/f13dff91-b486-4191-a5ce-95039edefbf5/files/publication-authority-permissions/`.
The receipt verifier checks exact item/SQL grants, principal bindings,
unchanged broker/verifier memberships, job source/image/resources, actual
ODBC results, and before/after counts.

Remaining gates: actual issuer/three-approver public trust pins/config source
were not supplied or configured by this operation. The unapplied v3 SQL
adapter must isolate credential identities in its ODBC pool before authority
runtime activation; its same-DSN token connections lack that protection.
That source finding was sent to Fabric. No authority runtime, signatures,
retention, or publication execution has been enabled or claimed complete.
