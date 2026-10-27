# Platform setup with service principals

## Quick start: run platform setup

Use a pre-created **deployment SPN with Owner on the target subscription**.
You do not need to run Terraform, configure individual Azure services or
assign the platform's resource-level roles yourself.

On a machine with Git, Azure CLI, Terraform and `uv` installed, open a current
platform checkout, prepare dependencies once, then run setup:

```bash
uv sync --locked --extra api --extra test
bash infra/scripts/setup-platform.sh --apply --env-file /secure/platform-setup.env
```

The Bash entry point invokes the existing Terraform-backed setup workflow;
Python helpers remain internal dependencies. All setup options pass through
unchanged. The launcher does not install dependencies or change your login,
and omitting `--apply` retains the offline, read-only preview.

`/secure/platform-setup.env` is the protected setup file supplied by your
platform administrator, containing the SPN credentials and approved platform
settings. Keep it outside source control. The administrator prepares the
deployment settings and tenant prerequisites using the reference below.
The script handles SPN login, infrastructure provisioning, configured Fabric
resources, supported permission assignments and application image deployment.
This includes creating and attaching all configured user-assigned and
system-assigned managed identities, and assigning their Terraform-managed
Azure RBAC and Fabric workspace access. You do not create these identities
or copy the deployment SPN's credentials into runtime containers.
Running with `--apply` creates billable resources.

To preview the sequence without making changes, omit `--apply`. A preview
does not validate cloud permissions. If setup reports a missing permission
or tenant prerequisite, have the relevant administrator resolve it before
rerunning; do not treat partial provisioning as a completed platform.

**Current limitation:** the script still requires the administrator-supplied
configuration and Entra/Fabric tenant approvals. Subscription Owner and SPN
credentials alone cannot grant these approvals.

## Administrator reference

The remaining sections are for administrators preparing the setup package,
resolving prerequisite failures or onboarding additional subscriptions.

This guide separates **automated provisioning** from **manual administrator
gates**. Azure RBAC, Entra application permissions, Fabric tenant settings,
Fabric workspace roles and OneLake permissions are different authorization
systems: subscription Owner does not grant all of them.

Use a privileged **deployment SPN** for setup and a separate, read-only
**connection SPN for each onboarded subscription**. Production containers use
managed identities, not the deployment SPN's secret.

**Operator access assumption:** you cannot create SPNs, manage Entra
applications/groups, assign Entra app roles or grant tenant consent. You can
assign Azure RBAC permissions on the subscriptions you administer. All SPNs
must therefore be **pre-created and supplied by the identity team**. Sections
3, 4 and the directory changes in section 7 are requests to the relevant
administrators, not steps you are expected to execute yourself.

Subscription RBAC cannot replace these tenant prerequisites. If they are not
provided, stop at the affected gate; a supplied deployment SPN plus subscription
Owner does not by itself enable full platform setup and user sign-in.

## 1. Setup sequence and automation

| Order | Task | Automated? |
| --- | --- | --- |
| 1 | Approve subscription RBAC, Fabric/AI region and quota, network access, tenant settings | **Manual administrator gate** (sections 2-3) |
| 2 | Receive pre-created deployment/connection SPNs and administrator-configured SPA/API registration, scopes, roles and assignments | **External identity-team prerequisite** (sections 2, 4 and 8) |
| 3 | Install dependencies and prepare protected credentials/non-secret Terraform settings | **Manual operator input** (section 5) |
| 4 | SPN login, Terraform init/validate/apply, Fabric config, catalog and supported OneLake roles | **Automated** (section 6) |
| 5 | Build and verify four images; deploy the same image tag | **Automated** (section 6) |
| 6 | Add final SPA redirect URL; approve new managed identities in Fabric's allowed group | **Manual administrator gate** (section 7) |
| 7 | Onboard connections and ingest approved real data | Existing CLI/UI; explicit optional setup sync (sections 8-9) |
| 8 | Optional BI Direct Lake model bootstrap/rebinding | **Manual BI owner gate** (section 9) |
| 9 | Optional advisory Data Agent provisioning/publication | **Automated opt-in**; query acceptance remains manual (section 9) |
| 10 | Runtime readiness, live authorization and phase rollout acceptance | **Separate operator verification** (section 10) |

`infra/scripts/setup-platform.py` orchestrates the existing deployment tools.
It does nothing to Azure, credentials or files unless **`--apply`** is passed.
An offline preview is not a Terraform plan or proof of effective permissions.
Running setup never approves native unattended ontology maintenance or clears
the deferred evidence gates recorded in `.planning/STATE.md`.

## 2. Pre-created deployment SPN and subscription RBAC (operator)

Request an existing deployment SPN from the identity team. Obtain these values
through the approved secure handoff, without querying the directory yourself:

| Supplied value | Purpose |
| --- | --- |
| Tenant ID | Directory issuing the SPN's tokens |
| Application/client ID | SPN login and Terraform authentication |
| Service principal object ID in that tenant | Azure role assignments and Fabric capacity administration |
| Valid client secret, expiry and rotation contact | Current setup scripts use client-secret authentication |

The object ID must be the **enterprise application's service principal object
ID**, not the app-registration object ID or application/client ID. The identity
team owns creation, credential issuance and rotation; this guide does not ask
the operator to run `az ad sp create-for-rbac` or perform directory lookups.

Sign in using your existing operator identity and assign the supplied SPN
Azure RBAC. You need role-assignment authority at the subscription (for example
Owner or an appropriately authorized User Access Administrator). Use
`--assignee-object-id` and `--assignee-principal-type` to avoid a Microsoft
Graph lookup:

```bash
az login --tenant <tenant-id>
az account set --subscription <platform-subscription-id>
az role assignment create \
  --assignee-object-id <supplied-deployment-SPN-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role Owner \
  --scope /subscriptions/<platform-subscription-id>
```

Store the supplied secret in your approved secret store. Set
`AIOPS_DEPLOYER_OBJECT_ID` to the supplied service principal object ID in the
setup environment file; the setup runner exports it to `deploy.sh`, bypassing
that script's optional `az ad sp show` lookup. When invoking `deploy.sh`
directly, export `AIOPS_DEPLOYER_OBJECT_ID` explicitly as well: it does not read
that value from the environment file itself. Do not paste secrets into logs,
tickets or source control.

### RBAC assignment checklist by pre-created SPN

This is the operator's assignment checklist. Use each SPN's supplied
**service principal object ID** as the assignee, not its client ID. The
deployment and connection SPNs must remain separate.

| Pre-created SPN | Azure RBAC role | Exact scope | When / who assigns |
| --- | --- | --- | --- |
| Deployment SPN | `Owner` **or** both `Contributor` and `User Access Administrator` | `/subscriptions/<platform-subscription-id>` | Required before provisioning. The subscription RBAC operator assigns one of these alternatives, not all three roles. |
| Deployment SPN | `Reader` **and** `User Access Administrator` | `/subscriptions/<additional-onboarded-subscription-id>` | Only where Terraform must grant the MCP identities access outside the platform subscription. That subscription's RBAC operator assigns both. Existing Owner is sufficient instead; do not add redundant roles. |
| Deployment SPN | `Key Vault Secrets Officer` | Platform Key Vault resource ID | Terraform assigns after creating the vault. Do not grant at the entire subscription just to bootstrap. |
| Deployment SPN | `Search Index Data Contributor` and `Search Service Contributor` | Platform Search service resource ID | Terraform assigns when knowledge search is enabled. |
| Deployment SPN | `Cognitive Services OpenAI User` and `Cognitive Services User` | Corresponding platform Foundry/Cognitive Services account resource ID | Terraform assigns for the configured deployment data-plane operations. |
| Deployment SPN | `Foundry Project Manager` | Platform Foundry project resource ID | Terraform assigns for agent provisioning. |
| Connection SPN, **one per subscription** | `Reader` | `/subscriptions/<that-connection-subscription-id>` | Required before onboarding; target subscription RBAC operator assigns. No platform-subscription assignment is needed unless it is that connection's target. |
| Connection SPN | `Cost Management Reader` | `/subscriptions/<that-connection-subscription-id>` | Optional explicit cost-read grant, only if required by the enabled billing integration/offer; Reader may already cover it. |
| Connection SPN | No additional Azure RBAC on Key Vault, ACR, Foundry or Fabric capacity | None | The connection SPN reads target inventory; the runtime identity, not the connection SPN, resolves its secret reference. |
| Workbench SPA/API application service principal | No Azure resource RBAC for browser sign-in | None | Identity team configures Entra scopes, consent and user app roles separately. Do not grant Azure Contributor/Owner to enable sign-in. |

The deployment role alternative must permit role-assignment creation/deletion
and, when enabled, custom-role management. Conditions, deny assignments or
restricted delegation can prevent this even if the role name appears correct.
If your organization disallows granting the deployment SPN those permissions,
the RBAC operator must arrange a separately reviewed pre-provisioning workflow;
the current full Terraform setup cannot manage its assignments with
Contributor alone.

To use the two-role alternative on the platform subscription, run instead of
the Owner assignment above:

```bash
az role assignment create \
  --assignee-object-id <supplied-deployment-SPN-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role Contributor --scope /subscriptions/<platform-subscription-id>
az role assignment create \
  --assignee-object-id <supplied-deployment-SPN-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role "User Access Administrator" --scope /subscriptions/<platform-subscription-id>
```

For each **additional** subscription listed in `onboarded_subscriptions`,
assign the deployment SPN these roles only if it will manage that
subscription's MCP grants:

```bash
az role assignment create \
  --assignee-object-id <supplied-deployment-SPN-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role Reader --scope /subscriptions/<additional-onboarded-subscription-id>
az role assignment create \
  --assignee-object-id <supplied-deployment-SPN-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role "User Access Administrator" --scope /subscriptions/<additional-onboarded-subscription-id>
```

Verify assignments without resolving principals through Microsoft Graph:

```bash
az role assignment list \
  --scope /subscriptions/<subscription-id> --include-inherited \
  --fill-principal-name false \
  --query "[?principalId=='<supplied-SPN-object-id>'].{role:roleDefinitionName,scope:scope}" \
  --output table
```

Repeat for the deployment SPN and every connection SPN at their respective
subscription scopes. Resource-level grants can be inspected using their
resource ID as `--scope` after Terraform creates them. Role propagation may
take time; assignment visibility is not proof that an actual data-plane call
is already authorized.

### Deployment permissions and provisioning details

| Deployment SPN permission | Scope | Reason / provisioning |
| --- | --- | --- |
| `Owner`, or `Contributor` plus `User Access Administrator` | Platform subscription | Creates resource groups/resources and Azure role assignments. Contributor alone cannot assign roles. Equivalent custom/conditioned RBAC must allow all required assignments. |
| `Microsoft.Authorization/roleDefinitions/write` and role-assignment management, if Defender configuration execution is enabled | Platform subscription | Creates and assigns the custom Defender pricing read/write role. Ensure any constrained RBAC admin alternative permits this. |
| Role-assignment management, plus access needed to read the scope | Each subscription explicitly in `onboarded_subscriptions` | Assigns Reader to the MCP managed identity and Reader/Monitoring Reader to the Azure MCP identity. This list is not the connection SPN registry. |
| `Key Vault Secrets Officer` | Platform Key Vault | Terraform grants this to the deployer for secret data-plane operations. Owner alone does not give RBAC-mode secret access. |
| `Search Index Data Contributor`, `Search Service Contributor` | Platform Search service, when enabled | Terraform grants these for knowledge-index provisioning. |
| `Cognitive Services OpenAI User`, `Cognitive Services User`, `Foundry Project Manager` | Corresponding Foundry resources/project | Terraform grants these for model/agent data-plane setup. Agent/index helpers are already Terraform `local-exec` steps, not mandatory additional commands. |
| ACR build/push capability | Platform registry | Inherited through the provisioning role. `az acr build` needs task/run management, not just `AcrPush`; local Docker push can use `AcrPush`. |

Provider registration and deployment can be blocked by subscription policy,
quota, unavailable SKUs, resource locks or private networking even with Owner.
For a reported provider error, an administrator checks and registers that
specific provider, for example:

```bash
az provider show --namespace Microsoft.Fabric --query registrationState -o tsv
az provider register --namespace Microsoft.Fabric --wait
```

The deployment includes Container Apps, ACR, Key Vault, managed identities,
Log Analytics/Application Insights, Foundry/model deployments, optional Search,
APIM and Fabric capacity. Approve the selected regions/model quota in advance.
The machine running Terraform and the Fabric scripts must reach the required
Azure, Fabric and OneLake endpoints, including any approved private endpoints.

## 3. Fabric tenant permissions (manual Fabric administrator)

**External prerequisite:** send this checklist to the Fabric/identity teams.
The subscription operator cannot perform these tenant/group changes.

In **Fabric portal > Settings > Admin portal > Tenant settings**, search for
the following settings (labels and preview availability can vary by tenant):

1. Enable **Service principals can use Fabric APIs** for an approved Entra
   security group containing the deployment SPN.
2. If workspace creation is restricted, allow that group in **Service
   principals can create workspaces, connections, and deployment pipelines**
   (or the tenant's applicable workspace-creation control).
3. Approve the required item-creation, Ontology/Fabric IQ and Data Agent preview
   settings for the features you intend to use. An unsupported item API or SKU
   is not fixed by granting broader Azure roles.
4. For AI features, inspect the tenant's Copilot/Azure OpenAI enablement and
   data-processing geography controls. If the capacity region needs cross-region
   processing, obtain compliance approval before enabling the corresponding
   **Data sent to Azure OpenAI can be processed outside your capacity's
   geographic region, compliance boundary, or national cloud instance** setting.
   Do not enable cross-region processing/storage or organization-wide access
   merely to bypass a 403.
5. Apply the settings and allow propagation. After Terraform creates runtime
   managed identities, add their service principal object IDs to the same
   approved groups as applicable (section 7).

The identity team can add an approved principal without giving the deployment
SPN Graph rights. The following command is **administrator-only**, not an
operator setup command:

```bash
az ad group member add --group <allowed-security-group-id> \
  --member-id <service-principal-object-id>
```

Terraform adds the deployer to the new capacity's administrators using its
object ID. **Capacity admin is not workspace admin**: the creator of a new
workspace obtains workspace administration; an existing/adopted workspace must
explicitly grant the deployment principal suitable workspace access. Configuring
OneLake data-access roles requires workspace **Admin**. Do not replace a
missing tenant setting with a blanket workspace/tenant administrator grant.

Fabric tenant API authorization is not provided by Azure Owner or Microsoft
Graph permissions. The runtime's Contributor workspace grants and capacity
Reader grants are Terraform-managed. Role scopes and separation are defined in
`infra/terraform/fabric.tf` and `ontology_discovery_identity.tf`; the setup
script does not broaden them.

## 4. Entra sign-in configuration (manual application administrator)

**External prerequisite:** ask the identity/application team to configure and
hand over the following. The subscription operator does not run these steps
or the Graph-based helper. Neither the deployment nor connection SPN needs
directory-write permissions for the operator workflow.

1. In **Entra admin center > App registrations > New registration**, create a
   single-tenant app for the Workbench/API, and record its client ID.
2. Under **Authentication > Add a platform > Single-page application**, add
   `http://localhost:3000` if local development is needed. Add the deployed web
   origin after provisioning (section 7); match scheme/host/path exactly.
3. Under **Expose an API**, set an Application ID URI such as
   `api://<web-api-client-id>` and create/enable the delegated
   `access_as_user` scope. Consent/preauthorize the SPA for that scope under
   your tenant's consent policy. For separate SPA and API registrations, expose
   the scope/roles on the API registration and configure the SPA accordingly.
4. In the API registration's manifest set
   `api.requestedAccessTokenVersion` to **2**. The runtime rejects v1 issuers.
   For v2 access tokens the API `aud` is normally the **API client-ID GUID**;
   configure the exact expected audience, not the scope string.
5. Define and assign the `admin`, `operator` and `reader` user app roles, and
   configure the matching `AIOPS_ENTRA_GRANTS_JSON` authorization map. In the
   single-registration layout the existing helper can do the role work:

   ```bash
   ENTRA_WEB_CLIENT_ID=<web-api-client-id> \
   AIOPS_API_GATEWAY_GRANTS='{"admin@example.com":[{"role":"admin"}]}' \
     bash infra/scripts/configure-entra-app-roles.sh
   ```

   Review the helper first: it sets the app's role definitions, resolves the
   configured subjects, and assigns user roles. Verify every assignment in
   **Enterprise applications > your application > Users and groups**; do not
   treat its final `Done` message as proof that every subject resolved. Its
   roles currently allow `User`, not application principals. Application/MCP
   authorization must follow the separate runtime contract.
6. Sign out/in after scope, token-version or role changes to replace cached
   tokens. Validate both the token's `roles` claim and the runtime grant map.

Human Entra administrative roles and Microsoft Graph OAuth permissions are
different. If automating Graph work separately, application creation/update
and app-role assignments need the appropriate consented permissions (for
example `Application.ReadWrite.All`, `AppRoleAssignment.ReadWrite.All`, and
directory reads required to resolve users), in addition to any required
directory role. App ownership alone does not authorize all assignments.
This setup deliberately leaves those privileges off the deployment SPN.
Set `AIOPS_DEPLOYER_OBJECT_ID` below to avoid its optional Graph object-ID lookup.

The handoff must include the SPA/API client IDs, tenant ID, exact API audience,
delegated scope, authorized operator app-role assignments and a contact for
the final redirect-URI update. Without this preconfiguration the operator can
provision some Azure resources but cannot complete authenticated platform access.

## 5. Local dependencies and configuration (manual operator)

Install Python 3.11+, `uv`, Terraform `>= 1.9, < 2.0`, Azure CLI and Git.
Builds use ACR tasks by default; Docker/buildx is needed only when explicitly
using `AIOPS_BUILD_MODE=local`. Node.js is needed for local frontend development.

```bash
uv sync --locked --extra api --extra test
```

Do not combine the `api` and `eval` extras. Terraform initializes the pinned
AzureRM, AzAPI, Fabric and random providers from `providers.tf`.

Create a mode-0600 `web/.env.local` (gitignored), or select a protected path with
`--env-file`. Values are literal single-line `KEY=value` settings; do not use
shell commands, interpolation or trailing inline comments:

```dotenv
AZURE_SUBSCRIPTION_ID=<platform-subscription-id>
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<deployment-SPN-client-id>
AZURE_CLIENT_SECRET=<deployment-SPN-secret>
AIOPS_DEPLOYER_OBJECT_ID=<deployment-SPN-object-id>
NEXT_PUBLIC_ENTRA_CLIENT_ID=<SPA-client-id>
NEXT_PUBLIC_ENTRA_TENANT_ID=<tenant-id>
NEXT_PUBLIC_ENTRA_API_SCOPE=api://<API-client-id>/access_as_user
AIOPS_ENTRA_API_AUDIENCE=<API-client-id>
AIOPS_ENTRA_GRANTS_JSON='{"admin@example.com":[{"role":"admin"}]}'
```

Optional settings include `NVD_API_KEY`, `AIOPS_APIM_PUBLISHER_EMAIL`,
`AIOPS_APIM_NAME`, `AIOPS_FOUNDRY_MODEL_CAPACITY` and
`AIOPS_AGENT_ORCHESTRATION_MODE=maf`. Never prefix a secret with `NEXT_PUBLIC_`.

Review `infra/terraform/variables.tf`, then create non-secret
`infra/terraform/terraform.tfvars`, for example:

```hcl
name_prefix = "aiops"
environment = "dev"
location    = "eastus"
enable_fabric = true
fabric_capacity_sku = "F2"
enable_fabric_ontology_item = false
enable_fabric_publisher_ontology_item = false
deploy_images = false
onboarded_subscriptions = []
```

Choose capacity size/region for the actual workloads; an F2 workspace is not
proof that every preview AI feature is supported. Current `main` does not
declare the old pilot-bound `fabric_semantic_model.aiops` resource; do not add
or import it just to run setup. Native Ontology item publication stays disabled
until source tables and the actual definition are verified. The generated
setup config also sets `fabric.ontology.enabled=false` for a fresh install.
Existing configs retain their reviewed setting. Keep runtime and dedicated
publisher item-publication flags independently approved.

Do not add `image_tag` until an image exists. The build script records it after
all four pushes are verified. Configure/review a secure Terraform backend
before provisioning in a shared/production environment; this repository does
not automatically create one. State and saved plans may contain secrets, even
when CLI output marks a value sensitive.

## 6. Automated setup (explicit operator invocation)

From the repository root:

```bash
# Offline, no login, writes or cloud requests:
uv run --no-sync python infra/scripts/setup-platform.py

# After completing the manual prerequisites, provision and release:
uv run --no-sync python infra/scripts/setup-platform.py --apply \
  --env-file web/.env.local --image-tag initial-20261024
```

`--apply` explicitly authorizes the selected infrastructure/Fabric/image writes
and passes `-auto-approve` to Terraform. Inspect the variables and manual gates
first. For interactive Terraform review, use the individual commands below
instead. The script does **not** register providers, modify tenant settings,
change Entra applications, grant itself RBAC, resume capacities or promote
ontology/agent rollout flags.

Use this whole-platform runner for compatibility/shadow setup. Environments
already in `canary`/`default` must use the current API-authorization release
workflow for any authorization promotion: `deploy.sh` retains its exact-target,
immutable-digest and authorization checks and will reject an unqualified broad
apply. Setup does not downgrade the configured rollout mode to make it pass.

The automated sequence is:

1. Read literal credentials without sourcing/executing the environment file.
   Log in with the supplied SPN using a temporary mode-0700 `AZURE_CONFIG_DIR`;
   select the platform subscription. Your ambient `az login` is not changed.
   The temporary token cache is deleted on normal exit or failure.
2. Run Terraform init, validate, plan and infrastructure apply. Inspect the
   saved plan to block accidental creation/replacement of the pilot-bound
   semantic model; apply that exact plan. Catalog publication
   and final image-tag verification are explicitly deferred for this apply.
   The sensitive plan is held in a private temporary directory and removed
   after use. All four Container Apps use placeholders when `deploy_images=false`,
   avoiding pulls from an empty registry.
3. Read Terraform outputs without printing sensitive output values. Generate
   or merge the SPN Fabric YAML using the actual workspace/Lakehouse/ontology
   name, keeping secrets in environment variables, never YAML. Preserve
   unrelated configuration, default native item publication off, and refuse
   to overwrite another deployment's IDs,
   an existing managed-identity config or a symlink. Use `--fabric-config` to
   select a separate setup config when the runtime config uses managed identity.
4. Publish the governed remediation catalog. If Fabric is disabled, explicitly
   skip Fabric configuration/publication. If the validation-only
   `ontology_evidence_role_contract` output is present, run the existing OneLake
   role reconciler in preview then apply/verify mode. This works around Fabric
   provider 1.13's ManagedIdentity role round-trip bug; no broad workspace
   role is substituted for the managed-identity evidence grant. A null contract
   means no validation-role writes, not missing production authorization.
5. Build and verify `aiops-api`, `aiops-web`, `mcp-server` and `azure-mcp` using
   `build-and-push.sh`. Run the final apply with **both**
   `deploy_images=true` and the verified image tag. Preserve the existing
   immutable API digest/source revision, default/canary authorization and
   revision verification contracts in the build/deploy helpers; setup does
   not authorize a mode change or use the special API-authorization release.

Stage-specific retries use the same protected inputs:

```bash
# Infrastructure + Fabric baseline, but no image build/release:
uv run --no-sync python infra/scripts/setup-platform.py --stage infrastructure --apply

# Existing infrastructure: config, catalog and applicable OneLake roles only:
uv run --no-sync python infra/scripts/setup-platform.py --stage fabric --apply

# Build/release only, after Fabric config exists:
uv run --no-sync python infra/scripts/setup-platform.py --stage release --apply \
  --image-tag release-20261025
```

Stages stop on a failed command. Terraform resources already applied remain in
place: correct the reported prerequisite and rerun the appropriate stage.
No destroy, automatic import, `state rm`, or scope-widening retry is performed.
The Fabric role evidence is saved under the private `.azure/setup/` directory
(gitignored); use `--artifact-dir` for an approved alternate location.

For an individually reviewed Terraform apply:

```bash
# First authenticate az as the same deployment SPN in a protected CLI context.
# deploy.sh reads credentials for Terraform, but does not perform az login.
export AZURE_CONFIG_DIR="$(mktemp -d)"
chmod 0700 "$AZURE_CONFIG_DIR"
# DEPLOY_SECRET must already be obtained from your approved secret store.
az login --service-principal --username <deployment-SPN-client-id> \
  --password "$DEPLOY_SECRET" --tenant <tenant-id> --output none
az account set --subscription <platform-subscription-id>
export AIOPS_DEPLOYER_OBJECT_ID=<supplied-deployment-SPN-object-id>
bash infra/scripts/deploy.sh plan
AIOPS_DEFER_CATALOG_PUBLICATION=true bash infra/scripts/deploy.sh apply
uv run --no-sync python infra/scripts/setup-platform.py --stage fabric --apply
bash infra/scripts/build-and-push.sh initial-20261024
bash infra/scripts/deploy.sh apply \
  -var=deploy_images=true -var=image_tag=initial-20261024
```

The explicit deferral is for the first apply only: catalog failure on a normal
Fabric-enabled release is still an error. Foundry agent and knowledge-index
provisioning are already wired by Terraform; do not rerun those helpers blindly
or bypass their candidate/publication/activation checks. The manual CLI context
contains a token cache: remove that specific temporary directory when finished
and unset `AZURE_CONFIG_DIR` and `DEPLOY_SECRET`; the setup orchestrator handles
its own temporary directory automatically.

## 7. Finish sign-in and managed identity access (manual administrator)

### Managed identities included in platform setup

The setup script applies Terraform's identity resources and attaches them to
their applications, jobs and services. The deployment SPN is used only for
provisioning; runtime workloads use the identities below. No separate
managed-identity creation commands are required.

This inventory describes the current-main deployment. Optional resources and
grants follow the selected feature flags; keep role-assignment management
enabled for a fresh Owner-SPN setup. Disabling it requires administrator-
provisioned equivalent grants, not a successful but unauthorized runtime.

| Managed identity | Created and attached automatically | Permissions managed by setup |
| --- | --- | --- |
| Application runtime (`apps`, user-assigned) | Platform Container Apps and configured jobs | `AcrPull` on the platform registry; `Key Vault Secrets Officer` on the platform vault; Foundry `Foundry Agent Consumer` and `Foundry Project Runtime User`, plus configured custom prompt/response runtime roles at project/account scopes; Fabric capacity `Reader` and operational workspace `Contributor`. Ontology command access is Contributor; state/publication access is Viewer. VM execution uses `Virtual Machine Contributor` only on the platform resource group; the optional custom Defender pricing role is subscription-scoped. |
| Operations MCP relay (`mcp_server`, user-assigned) | Operations MCP Container App | `AcrPull` on the registry, `Key Vault Secrets User` on the platform vault, and `Reader` on explicitly configured subscriptions. |
| Azure MCP (`azure_mcp`, user-assigned) | Azure MCP Container App and configured evidence job | `AcrPull` on the registry; `Reader` and `Monitoring Reader` on explicitly configured subscriptions. Applicable OneLake evidence-read roles are reconciled from the deployment contract, not inferred from subscription Reader. |
| Ontology coordinator (`ontology_coordinator`, user-assigned) | Discovery coordinator and configured preparation/cleanup jobs | `AcrPull` on the registry and `Key Vault Secrets User` on the vault; Contributor on configured operational, state, command and dispatch workspaces. Validation-mode subscription `Reader`/`Monitoring Reader` grants are conditional; this identity is not the authoritative publisher. |
| Ontology publisher (`ontology_publisher`, user-assigned) | Publisher job | `AcrPull` on the registry; Contributor on configured operational, command, dispatch, publication and RBAC-validation workspaces. Identity provisioning does not approve publication or enable deferred native-authoring capabilities. |
| Foundry account (system-assigned) | Foundry account creation | `Search Index Data Contributor` and `Search Service Contributor` on the optional knowledge Search service. |
| Foundry project (system-assigned) | Foundry project creation | The same scoped Search roles when knowledge search is enabled. Application-level APIM/MCP caller authorization is a separate grant-map step below, not Azure RBAC. |
| Knowledge Search (system-assigned, optional) | Knowledge Search service creation | `Cognitive Services OpenAI User` on the Foundry account for configured model calls. |

Azure subscription Owner authorizes Azure identity/resource creation and role
assignment. It does **not** authorize adding the resulting identities to
Entra security groups or changing Fabric tenant allowlists. Those external
approvals remain administrator tasks below; Fabric workspace roles and
OneLake access also require the applicable Fabric permissions.

### External administrator completion

**External post-provisioning gate:** the operator supplies the resulting URLs
and managed-identity object IDs to the identity/Fabric administrators. They
perform the redirect-URI and allowed-group updates below. Azure RBAC assignment
rights alone do not authorize either change.

Get `web_url`, `api_url`, `fabric_workspace_id` and `fabric_lakehouse_id`
from Terraform outputs. Add `web_url` as an SPA redirect URI in the app
registration from section 4, and confirm the API's allowed web origin matches.
Add newly created runtime service principals to the approved Fabric tenant
groups from section 3. List managed identity object IDs for the resource group:

```bash
az identity list --resource-group <platform-resource-group> \
  --query '[].{name:name,objectId:principalId,clientId:clientId}' -o table
```

Terraform handles Azure resource RBAC and Fabric workspace roles. The app
identity receives Key Vault Secrets Officer for Workbench onboarding, ACR pull,
Fabric workspace Contributor and the configured Foundry roles. The MCP and
Azure MCP identities get their distinct read-only scopes. Patch/Defender
execution grants are separate from subscription inventory access; the setup
does not extend them to arbitrary external subscriptions.

For Foundry-to-APIM/MCP authorization, follow the
`foundry_project_principal_id` output instructions: add that object ID with
the reviewed reader/scope grants to the grant map and reapply. Do not insert
an unrestricted admin grant or confuse this with a browser user app role.

If Fabric calls fail, check **capacity state** in Azure portal > Fabric
capacity > Overview and resume it there if approved. Also check workspace
assignment, tenant allowlists, networking and item-specific errors. A 403
alone is not evidence that a capacity is paused.

## 8. Onboard subscriptions with isolated read-only SPNs

### Permissions and who grants them

Request one **pre-created connection SPN per subscription** from the identity
team in the target tenant. Obtain its tenant ID, client ID, service principal
object ID, valid secret and rotation contact through a secure channel. Do not
reuse the privileged deployment SPN. Using only your subscription RBAC
authority, assign the supplied connection SPN Reader:

```bash
az role assignment create \
  --assignee-object-id <supplied-connection-SPN-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role Reader --scope /subscriptions/<target-subscription-id>
```

This uses the supplied object ID and does not require an Entra directory
lookup. For a target subscription you do not administer, ask its RBAC owner
to perform the assignment; directory access is not a substitute for that
subscription permission. Credential renewal remains the identity team's task.

| Principal / capability | Required permission and scope |
| --- | --- |
| Connection SPN: authentication | Valid app/secret in the specified tenant. No directory admin or Graph permissions. |
| Connection SPN: reachability and ARG | `Reader` at `/subscriptions/<target-id>`. These are required onboarding checks. |
| Connection SPN: network, patch/update inventory, Advisor and ResourceChanges | Subscription `Reader` covers the read checks. Unavailable optional providers/data can still yield `degraded`. This does not authorize patch installation or Defender changes. |
| Optional billed-spend queries | Confirm Cost Management access under the subscription's billing offer. Reader commonly includes cost reads; `Cost Management Reader` is an explicit cost-read grant where needed, not a universally required extra onboarding role. EA/MCA billing policies may impose additional restrictions. |
| Optional management-group discovery | `Reader` on each explicitly queried management group. Not required for connection-scoped subscription onboarding. |
| Operator storing a connection secret | `Key Vault Secrets Officer` (or narrowly equivalent secret-set permission) on the selected vault. |
| Runtime resolving a secret reference | At least `Key Vault Secrets User` on that vault and network reachability. The API identity uses Officer because the UI also stores submitted secrets. |
| Workbench onboarding user | Assigned `admin`/`operator` app role and matching authorized runtime grants; this is separate from the Azure connection SPN. |

No Owner, Contributor, User Access Administrator, Fabric role or tenant-wide
Graph permission is required by the **connection SPN**.

If explicitly required for billed-spend access, the target subscription RBAC
operator can add the optional role to that same connection SPN:

```bash
az role assignment create \
  --assignee-object-id <supplied-connection-SPN-object-id> \
  --assignee-principal-type ServicePrincipal \
  --role "Cost Management Reader" --scope /subscriptions/<target-subscription-id>
```

Management-group permissions are outside the assumed subscription-only
operator authority. Leave management-group discovery unconfigured unless the
management-group owner supplies the required Reader access.

### Store the credential and register the connection

Use Workbench subscription onboarding to submit the secret to
`AIOPS_CONNECTION_KEY_VAULT`; the registry keeps only its versioned reference.
Alternatively, a vault-authorized operator stores a protected secret file:

```bash
az keyvault secret set --vault-name <vault> --name aiops-conn-prod-core \
  --file /secure/connection-secret.txt --output none

uv run --no-sync aiops-inventory subscriptions add prod-core \
  --config /secure/config.yaml \
  --tenant-id <target-tenant-id> --subscription-id <target-subscription-id> \
  --client-id <connection-SPN-client-id> \
  --secret-ref keyvault://<vault>/secrets/aiops-conn-prod-core \
  --business-service Payments --environment production --criticality high
uv run --no-sync aiops-inventory subscriptions validate prod-core --config /secure/config.yaml
uv run --no-sync aiops-inventory subscriptions sync prod-core --config /secure/config.yaml --mode initial
uv run --no-sync aiops-inventory subscriptions health prod-core --config /secure/config.yaml
```

Keep the file mode 0600, retrieve it from the approved secret store, and remove
that temporary file after upload. For local-only testing use `env://NAME`;
never put raw secrets in YAML or CLI connection metadata. The CLI process
resolving Key Vault references needs its own authorized Azure credential.

Configure the CLI's `storage.output_dir` for the intended environment: a
local `./data` registry is **not automatically the deployed OneLake registry**.
Prefer the deployed Workbench/API for production onboarding. See
[Subscription onboarding](docs/SUBSCRIPTION_ONBOARDING.md) for command details.

Adding a connection does not grant generic MCP managed identities access.
If you also want their Azure MCP tools on a same-tenant subscription, an
administrator can add it to `onboarded_subscriptions` and reapply with the
deployer authorized to grant Reader/Monitoring Reader there. This is **not**
a prerequisite for the connection-isolated SPN's ARG ingestion, and is not an
automatic cross-tenant managed-identity grant.

## 9. Complete Fabric data and optional items

### Automated data/ontology sync (explicit opt-in)

Catalog publication alone does not ingest inventory or make the runtime ready.
After actual connection discovery, provide the approved normalized generation
directory (not fixtures or an empty directory) to the Fabric sync:

```bash
uv run --no-sync python infra/scripts/setup-platform.py --stage fabric --apply \
  --source-data-root /secure/normalized-generation --sync-inventory
```

This sets `fabric.source_data_root`, runs the existing **Sync operational
ontology** CLI operation and reads ontology health. It is deliberately not
the default because it writes data. Native Ontology item creation/update
additionally requires the config's separately reviewed
`fabric.ontology.enabled=true`; new setup configs leave it false. Keep any
migrated/native-authoritative target out of this legacy sync
unless the relevant phase gate explicitly authorizes it. Setup does not claim
native unattended authoring support.

For a newly created Ontology, inspect health/the portal item URL and pin its
immutable `fabric.ontology.ontology_id` in the config. Verify Lakehouse bindings,
entity/relationship counts and known traversals. Data quality failures, item
authorization failures and unsupported schema formats remain blocking.
See [Fabric persistence](docs/FABRIC_RUNBOOK.md) and
[Ontology deployment](docs/FABRIC_ONTOLOGY_DEPLOYMENT.md).

### OneLake role limitation (automated where the contract exists)

The setup script invokes
`scripts/reconcile_onelake_data_access_roles.py` rather than recreating
Terraform's broken `ManagedIdentity` role round-trip. The reconciler preserves
unrelated roles, uses ETags, retries bounded conflicts and verifies the result.
It needs the deployer's workspace administration and the isolated CLI token
context, not an unqualified default user login.

The contract is emitted only for the configured validation environment.
Successful reconciliation does not clear live publisher-RBAC or production
isolation gates. For **old states only**, the explicit reviewed `state rm`
migration is in
[OneLake role migration](docs/onelake-data-access-role-migration.md).
Fresh installs must not run those state-removal commands.

### Direct Lake semantic model (optional manual BI surface)

Terraform can create semantic models in general, but current `main` no longer
declares the old adopted `aiops_semantic_model`. There is no setup count flag or
Terraform import step for it. If a separate BI model is required, its owner must
build and qualify it against this installation's actual Lakehouse.

1. Ingest and register the real Lakehouse tables first.
2. In Fabric portal, open the target Lakehouse and use **New semantic model**
   (or the tenant's equivalent SQL analytics endpoint action). Select the
   intended tables, save it as `aiops_semantic_model` in the target workspace,
   and verify it uses this Lakehouse, not the pilot workspace.
3. Have the BI/model owner review relationships, measures, visibility and
   required table coverage against the approved model contract and current
   [Lakehouse table inventory](docs/LAKEHOUSE_TABLE_INVENTORY.md).
   A minimal auto-generated model is not equivalent to the full governed model.
   Configure any prompted source credentials/connection and test a real query
   as the intended consumer. Check Direct Lake capacity/licensing requirements.
4. Record workspace/model IDs and the qualified source binding for its
   consumers. Do not reintroduce the pilot model definition or claim that a
   minimal auto-generated model reproduces the full governed BI contract.
   If your environment still tracks an older model in Terraform state,
   coordinate that state migration with its owner; setup does not remove it.

### AI Ops Data Agent (Terraform item, manually reviewed definition)

Current `main` already creates `fabric_data_agent.ai_ops` with
`definition_update_enabled=false`. The item lifecycle is Terraform-owned;
staging and publication use the separately invoked
`scripts/configure-gold-grounding-agent.py`, not the relationship-suggestion
helper below. After real Gold/ontology tables exist, record the verified item
ID from the portal under `fabric.gold_grounding_agent.item_id`, review the
script's instructions/table selection and run:

```bash
uv run --no-sync python scripts/configure-gold-grounding-agent.py \
  --fabric-config fabric.config.yaml
# Review the staged definition first, then explicitly publish:
uv run --no-sync python scripts/configure-gold-grounding-agent.py \
  --fabric-config fabric.config.yaml --publish
```

Publication is not query acceptance or runtime grounding enablement. Follow
the current environment's grounding gates; do not inherit historical item IDs.

### Advisory Data Agent (optional automated preview item)

After real `ontology_entities` and `ontology_relationships` tables exist and
tenant support has been approved:

```bash
uv run --no-sync python infra/scripts/setup-platform.py --stage fabric --apply \
  --publish-data-agent
```

This calls `deploy-relationship-suggestion-agent.py` with **`--publish`**;
without that flag the existing helper only creates/stages the item. It uses the
DataAgent-specific staging publish API, not the generic item publish route.
The config can pin `fabric.relationship_suggestion_agent.item_id` after creation.

**Manual acceptance:** open `relationship_suggestion_agent` in the target
workspace, inspect its selected Lakehouse tables/instructions and ask a
bounded read-only question. Record an actual answer, not just successful item
creation or MCP `tools/list`. The repository records a server-side query
failure despite successful publish; SDK namespace collision is a separate
known limitation. Portal diagnostics may help, but portal success is not
guaranteed. See
[Data Agent limitations](docs/fabric-data-agent-relationship-suggestions.md).
Suggestions remain advisory/human-reviewed, never authoritative graph writes.

## 10. Verification and failure handling

Check `/health` for process liveness and `/ready` for required providers. A
completed Terraform apply or four correct image tags does not prove usable
inventory, valid Entra sign-in, native ontology authoring, semantic queries or
live authorization isolation. In an empty installation `/ready` may remain 503
until onboarding/data/ontology activation is complete.

Use the deployed Workbench to confirm sign-in, connection validation/sync,
freshness and scoped data. Follow
[Production activation](docs/PRODUCTION_RUNTIME_ACTIVATION.md) for atomic
runtime activation. `validate-runtime-e2e.sh` is a separate **live gate**, not an
unconditional setup smoke test: it requires API/web URLs, an authorized token,
distinct hub/spoke connection IDs and connector/Fabric configuration, and can
hold promotion when parity is blocked. Configure/read that script before use.

| Failure | Action |
| --- | --- |
| Azure `AuthorizationFailed` creating assignments | Have a subscription administrator grant the deployer the required RBAC scope; do not upgrade the connection SPN. |
| Fabric tenant/item authorization error | Verify scoped tenant settings, workspace administration/item support and MI group membership. Azure Owner alone is insufficient. |
| Fabric unavailable/paused | Inspect capacity state and approved region/SKU/networking; resume manually if authorized. |
| Existing Fabric config belongs to another deployment/non-SPN identity | Use a separate `--fabric-config`; do not overwrite runtime bindings to force setup through. |
| Catalog fails after infrastructure apply | Resources remain. Fix config/data-plane access and rerun `--stage fabric --apply`; do not silently skip publication on normal releases. |
| Missing/incorrect images | Rebuild the same reviewed release, verify all four repositories and pass `deploy_images=true` on rollout. |
| Entra token denied | Verify v2 issuer/audience, scope consent, user app-role assignment and matching grant-map subject; sign in again. |
| Model creation/import blocked | Complete the manual data/model gate; never remove `prevent_destroy` or apply a pilot-bound definition as a shortcut. |

Keep SPN secrets, environment files, Terraform state/plans and temporary token
caches private. Use short-lived credentials and rotate connection references,
then revalidate. CI federation requires a separately reviewed credential path:
the current providers/deployment scripts explicitly use client-secret inputs,
so it is not a drop-in replacement. Do not automatically downgrade deployment
RBAC after setup; later applies still manage role assignments and data-plane
resources.
