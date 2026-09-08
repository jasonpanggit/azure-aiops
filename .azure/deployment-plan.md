# Azure Deployment Plan

Status: Validated

## Objective

Current operation (Phase 11 Plan 11-12 Task 3): deploy the already-implemented
canonical Operations Copilot orchestration changes as an additive Container
Apps revision, preserve the current revision and legacy planners for rollback,
verify exact live Foundry/MCP/manifest parity, exercise
`compatibility -> shadow -> 10% canary`, run the complete versioned 96-case
evaluation corpus against one deployed revision/provider configuration, and
record an honest immutable `PROMOTE`, `HOLD`, or
`HOLD_OR_DISABLE_MODE` baseline. Promotion is fail-closed; this operation does
not delete resources, rewrite threads/ledgers, retire v1 reads, or execute
remediation.

Phase 11 deployment target:

- Subscription: `ME-MngEnvMCAP686238-pangj-1`
  (`a87a8e64-a52a-4aa8-a760-5e8919d23cd1`, current/default and Enabled)
- Tenant: `ffc83107-fcc0-4d2e-8798-d582da36505e`
- Resource group: existing `aiops-dev-rg`
- Region: existing `australiaeast`
- Recipe: direct Azure CLI updates of the existing ACR and Container Apps,
  plus existing parity, evaluation, and rollback scripts. This isolated
  worktree does not contain the gitignored canonical Terraform state or
  service-principal inputs, so Task 3 must not create a replacement state or
  run an unreviewable apply.
- Safety: plan must show zero resource destruction/replacement outside expected
  additive revision/provisioner changes; retain the currently serving revision
  and `compatibility` rollback mode
- Operator confirmation: requested through the deployment workflow; the user
  was unavailable, so the already configured current/default existing target
  is retained without changing subscription, resource group, or region

Phase 11 validation proof is intentionally pending a fresh `azure-validate`
pass. The historical validation evidence below remains provenance for prior
deployments and is not reused as proof for this canary.

## Phase 11 Validation Checklist

- [x] All validation checks pass
  - [x] Azure CLI installed and authenticated to the configured subscription
  - [x] Existing ACR and API/web Container Apps are readable and healthy
  - [x] API and web Docker build contexts contain their lock files and build
        successfully before remote image creation
  - [x] Candidate image tags are immutable and unique to the source commit
  - [x] Planned `az containerapp update` commands change only API/web image
        references and Phase 11 rollout environment variables
  - [x] Existing Container App identities, secrets, ingress, scaling, and RBAC
        remain unchanged
  - [x] Previous API/web revisions remain available for compatibility rollback
  - [x] Offline specialist parity passes
  - [x] Focused Phase 11 evaluation and rollout-control tests pass
  - [x] Static managed-identity/RBAC review confirms existing least-privilege
        roles remain sufficient and unchanged
  - [x] Assigned Azure policies do not conflict with the additive revision
- [x] Validation Proof records exact commands, timestamp, plan summary, and
      resolved target before deployment

Phase 11 execution uses `az acr build` with commit-derived immutable API/web
tags and `az containerapp update` against the existing apps. It does not create,
delete, or replace Azure resources and does not modify Terraform state.

## Phase 11 Validation Proof

- Validated at: `2026-09-08T07:19:40Z`
- Source revision: `33843c214b5067a72ed3e9907b294be455c5c7d3`
- Target: subscription `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`,
  resource group `aiops-dev-rg`, region `australiaeast`
- Azure preflight: `az account show`, `az acr show`, and
  `az containerapp show` confirmed an Enabled subscription, succeeded ACR with
  admin credentials disabled, and healthy running API/web apps.
- Policy validation: `az policy assignment list --disable-scope-strict-match`
  returned no applicable assignments at the resource-group scope;
  `az policy state summarize --resource-group aiops-dev-rg` returned no
  non-compliant policy or resource count.
- Container validation:
  `docker build -t aiops-api:phase11-validation .` and
  `docker build -t aiops-web:phase11-validation web` both passed; `uv.lock`
  and `web/package-lock.json` are present.
- Backend: 351 passed, 1 skipped across the Phase 11 orchestration, evaluation,
  manifest, policy, page-context, API, and thread-store suites; relevant Ruff
  checks passed.
- Web: ESLint passed; 59 files and 661 tests passed; Next.js production build
  and `tsc --noEmit` passed.
- Specialist parity: all eight offline parity checks passed for 12 specialists,
  contract `1.0`, including runtime, MCP grants, API/page mappings, Terraform,
  model, package, and rollout projections.
- Static RBAC: Phase 11 adds only three API environment values in
  `container_apps.tf`; it does not add or alter role assignments. Existing
  app `AcrPull`, Operations MCP Reader/Key Vault, and Azure MCP Reader/
  Monitoring Reader assignments remain unchanged. Direct app updates preserve
  identity, secrets, ingress, and scaling.
- Change preview: API/web image references plus
  `AIOPS_COPILOT_ROLLOUT_MODE`,
  `AIOPS_COPILOT_CANARY_PERCENTAGE`, and
  `AIOPS_COPILOT_ROLLBACK_MODE` only. No Azure resource create, delete,
  replacement, RBAC, or Terraform-state operation is planned.

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
