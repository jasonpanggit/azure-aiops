# Production Runtime Activation

The deployed API treats the latest published Fabric Ontology and OneLake tables
as the authoritative operational snapshot. `SubscriptionConnection` credentials
remain isolated per connection and are used only for connection-scoped Azure
Resource Graph discovery. Production mode never loads fixture or mock data.

## Required deployment configuration

| Setting | Purpose |
| --- | --- |
| `HERMES_RUNTIME_MODE=production` | Disables direct fixture/local snapshot providers. |
| `HERMES_LOCAL_SEED=0` | Prevents local fixture seeding. |
| `HERMES_HOME` | ADLS root for connection registry state and isolated discovery generations. |
| `HERMES_DATABASE_URL` | PostgreSQL connection registry store. |
| `HERMES_API_AUTH=entra` | Validates browser access tokens directly against Entra JWKS. |
| `HERMES_ENTRA_TENANT_ID` | Entra tenant allowed to issue API tokens. |
| `HERMES_ENTRA_AUDIENCE` | Exact API audience expected in the token `aud` claim. |
| `HERMES_API_GATEWAY_GRANTS` | Explicit subject-to-role/scope authorization map. |
| `HERMES_CONNECTION_KEY_VAULT` | Key Vault used for submitted SPN secrets. |
| `HERMES_ENABLE_FABRIC=true` | Enables Fabric-backed runtime providers. |
| `FABRIC_WORKSPACE_ID` | Immutable Fabric workspace ID. |
| `FABRIC_LAKEHOUSE_ID` | Immutable operational-context Lakehouse ID. |
| `FABRIC_ONTOLOGY_NAME` | Published ontology item name. |
| `AZURE_CLIENT_ID` | User-assigned managed identity selected by Azure Identity. |
| `FOUNDRY_PROJECT_ENDPOINT` | Operations Copilot Foundry project endpoint. |
| `FOUNDRY_AGENT_NAME` | Existing governed prompt-agent name. |
| `HERMES_PROVIDER_REFRESH_SECONDS` | Safe provider refresh interval; default `30`. |
| `HERMES_PROVIDER_STALE_HOURS` | Freshness threshold; default `24`. |
| `HERMES_AKV_BOOTSTRAP_ENABLED` | Enables the startup sync of explicitly mapped container secrets into Key Vault. |
| `HERMES_AKV_BOOTSTRAP_SECRETS` | JSON map of Key Vault names to secret-backed environment variables. |

The Container App identity requires:

- `Storage Blob Data Contributor` on the ADLS account.
- Key Vault secret read/write access for connection credential references.
- `Contributor` on the Fabric workspace and access to its capacity/Lakehouse.
- `Azure AI User`/Foundry Agent Consumer access to the Foundry project.
- Network reachability to private ADLS, Key Vault, PostgreSQL, Fabric, and
  Foundry endpoints.

### Startup secret synchronization

The API image runs `api.akv_bootstrap` before Uvicorn starts. When enabled, it
uses the API Container App's user-assigned managed identity (`AZURE_CLIENT_ID`)
and writes only the allowlisted `HERMES_AKV_BOOTSTRAP_SECRETS` mappings. The
default deployment mapping is:

```json
{"hermes-database-url":"HERMES_DATABASE_URL"}
```

Values are read from Container Apps secret-backed environment variables, are
never logged, and are not rewritten when unchanged. A missing secret is
created; other Key Vault read/write failures fail container startup rather than
leaving a misleadingly healthy deployment. The app identity therefore needs
Key Vault Secrets Officer access and private-endpoint network reachability.

The production web image must be built with
`NEXT_PUBLIC_ENTRA_CLIENT_ID`, `NEXT_PUBLIC_ENTRA_TENANT_ID`, and
`NEXT_PUBLIC_ENTRA_API_SCOPE`. `infra/scripts/build-and-push.sh` requires and
passes all three values. The deployed web app never receives or serves a static
admin token; `/api/dev-token` is available only outside `NODE_ENV=production`.

Container Apps liveness uses `/health`; readiness uses `/ready`. A process stays
alive when an upstream refresh fails, but `/ready` returns `503` until every
required configured provider has a safe snapshot.

## Onboard, discover, publish, and activate

Create protected connector and Fabric configuration files from
`config.example.yaml` and `fabric.config.example.yaml`. Use Key Vault references,
not inline SPN secrets.

```bash
uv run hermes-arg subscriptions add hub-prod \
  --config /secure/config.yaml \
  --tenant-id "$HUB_TENANT_ID" \
  --subscription-id "$HUB_SUBSCRIPTION_ID" \
  --client-id "$HUB_CLIENT_ID" \
  --secret-ref "keyvault://ops-kv/secrets/hub-discovery-spn" \
  --business-service "Shared Platform" \
  --application "Hub Network" \
  --environment prod \
  --project-owner "Platform Operations"

uv run hermes-arg subscriptions add spoke-prod \
  --config /secure/config.yaml \
  --tenant-id "$SPOKE_TENANT_ID" \
  --subscription-id "$SPOKE_SUBSCRIPTION_ID" \
  --client-id "$SPOKE_CLIENT_ID" \
  --secret-ref "keyvault://ops-kv/secrets/spoke-discovery-spn" \
  --business-service Payments \
  --application "Payments API" \
  --environment prod \
  --project-owner "Payments Operations"

uv run hermes-arg activate \
  --config /secure/config.yaml \
  --fabric-config /secure/fabric.config.yaml \
  --connection-id hub-prod \
  --connection-id spoke-prod
```

`activate` performs the supported production sequence:

1. Validate SPN authentication, subscription reachability, ARG, network,
   patch/update, Advisor, and resource-change access for each connection.
2. Run discovery in each connection's isolated dataset root.
3. Build a deduplicated combined snapshot while retaining connection,
   subscription, business-service, application, environment, and owner lineage.
4. Publish Bronze/Silver/ontology Delta tables to OneLake and publish the Fabric
   Ontology definition.
5. Construct the semantic engine and return the activated ontology version.

The API checks the Fabric semantic version every refresh interval. To activate
immediately:

```bash
curl -fsS -X POST \
  -H "Authorization: Bearer $API_TOKEN" \
  "$API_URL/api/v1/runtime/refresh"
```

Refresh is atomic. A failed refresh retains the last good provider and reports
`degraded`; it never replaces current data with an empty snapshot.

## Health and failure states

`GET /health` and `GET /ready` report:

- provider configured/loaded state;
- `ontology_version`;
- last successful discovery and ontology publication timestamps;
- provider and aggregate freshness;
- degraded reason;
- retry attempts and next retry time.

States are:

- `ready`: current provider loaded.
- `partial`: provider loaded with an explicitly incomplete optional projection.
- `stale`: loaded snapshot exceeds the freshness threshold.
- `degraded`: last good provider retained after refresh/runtime failure.
- `unavailable`: no safe provider has ever loaded.
- `disabled`: optional provider is not configured.

Provider failures return `503 provider_unavailable`; routes never turn a provider
failure into a successful empty payload. The Copilot can return governed
retrieval without narration when Foundry is degraded, and records that degraded
state in provider health.

### Entra app registration prerequisites

`EntraJwtAuthenticator` validates access tokens against the Entra **v2.0**
issuer (`https://login.microsoftonline.com/{tenant}/v2.0`). The app
registration used as the API audience must request v2.0 access tokens, or
Entra issues v1.0 tokens (`https://sts.windows.net/{tenant}/` issuer) that
this validator rejects with `Entra access token is invalid` even though the
token itself is otherwise valid. Set this explicitly — it is not the app
registration default:

```bash
OBJECT_ID="$(az ad app show --id "$ENTRA_WEB_CLIENT_ID" --query id -o tsv)"
az rest --method PATCH \
  --url "https://graph.microsoft.com/v1.0/applications/${OBJECT_ID}" \
  --headers "Content-Type=application/json" \
  --body '{"api":{"requestedAccessTokenVersion":2}}'
```

Verify with `az ad app show --id "$ENTRA_WEB_CLIENT_ID" --query api.requestedAccessTokenVersion`
(expect `2`). Also confirm `identifierUris` includes the exact
`HERMES_ENTRA_AUDIENCE` value and `api.oauth2PermissionScopes` has an enabled
delegated scope (e.g. `access_as_user`) matching `NEXT_PUBLIC_ENTRA_API_SCOPE`.
After changing `requestedAccessTokenVersion`, users must sign out/in again —
already-cached v1.0 tokens remain invalid until MSAL acquires a fresh token.

#### App roles (required for grants to resolve)

`EntraJwtAuthenticator` reads the token's `roles` claim and intersects it with
each subject's roles from `HERMES_API_GATEWAY_GRANTS`
(`src/api/runtime.py:_gateway_grants`). Entra only ever populates a `roles`
claim when **both** of the following are true:

1. The app registration defines `appRoles` (by default this list is empty).
2. The signed-in user (or SPN) has been assigned one of those app roles on the
   app's service principal.

If either is missing, every token carries an empty `roles` claim and every
principal is rejected with `Entra principal has no configured Hermes grants`,
even though `HERMES_API_GATEWAY_GRANTS` correctly lists the subject. This is a
one-time, admin-only setup step — run
[`infra/scripts/configure-entra-app-roles.sh`](../infra/scripts/configure-entra-app-roles.sh)
as a tenant/app admin (requires `Application.ReadWrite.All` or app ownership;
the deployment SPN itself typically cannot grant this to itself):

```bash
ENTRA_WEB_CLIENT_ID="306c1437-0e7d-43bd-940b-79b878166331" \
HERMES_API_GATEWAY_GRANTS='{"admin@contoso.com":[{"role":"admin"}]}' \
./infra/scripts/configure-entra-app-roles.sh
```

The script defines `admin`/`operator`/`reader` app roles on the app
registration (idempotent) and assigns each subject in
`HERMES_API_GATEWAY_GRANTS` the app role matching their highest configured
role. Affected users must sign out and back in (or otherwise force MSAL to
acquire a fresh token) before the new `roles` claim takes effect.

### Administrator Entra configuration

Administrators can save the deployment's Entra values from `/admin`. The form
calls `POST /api/v1/admin/akv-config`; the API requires the `admin` role, accepts
only the fixed configuration fields, and writes fixed secret names using the
Container App managed identity. It never returns secret values or accepts
arbitrary Key Vault names. Saving these values does not mutate an existing
Container App revision; apply them through the normal deployment/revision
workflow before expecting build-time web settings or API authentication settings
to change.

## Hub/spoke end-to-end validation

```bash
API_URL="$(terraform -chdir=infra/terraform output -raw api_url)" \
WEB_URL="$(terraform -chdir=infra/terraform output -raw web_url)" \
API_TOKEN="$(az account get-access-token \
  --resource "$HERMES_ENTRA_API_AUDIENCE" \
  --query accessToken -o tsv)" \
HERMES_ARG_CONFIG=/secure/config.yaml \
HERMES_FABRIC_CONFIG=/secure/fabric.config.yaml \
HUB_CONNECTION_ID=hub-prod \
SPOKE_CONNECTION_ID=spoke-prod \
infra/scripts/validate-runtime-e2e.sh
```

The check activates both subscriptions, refreshes the API, verifies all required
providers are loaded, asserts a real hub and spoke are present, verifies scoped
hub/spoke API reads, exercises vulnerability/incident/remediation APIs, and
checks that the deployed web application is reachable.
