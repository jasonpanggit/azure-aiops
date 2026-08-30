# Security

## Authentication

- **Production auth mode**: `AIOPS_API_AUTH=entra`. The API validates
  browser-supplied access tokens directly against Entra JWKS
  (`src/api/auth.py::EntraJwtAuthenticator`) — no bespoke token issuance.
- **Tenant/audience pinning**: `AIOPS_ENTRA_TENANT_ID` and
  `AIOPS_ENTRA_AUDIENCE` are required in production; a token from another
  tenant or issued for a different audience is rejected.
- **Static-token mode** (`AIOPS_API_AUTH=token`) and **gateway mode**
  (`AIOPS_API_AUTH=gateway`) exist for local development and platforms that
  terminate auth upstream, respectively. Neither is used in the pilot
  production deployment (`infra/terraform/container_apps.tf` hardcodes
  `AIOPS_API_AUTH=entra` for the API Container App).
- **Dev token endpoint**: `/api/dev-token` exists only outside
  `NODE_ENV=production` in the web app; the production web image never
  serves it (`docs/PRODUCTION_RUNTIME_ACTIVATION.md`).

## Authorization (RBAC)

`src/api/rbac.py` enforces two independent axes, both required:

1. **Action gate** (`Authorizer.require`) — read/operate/write, gated by role
   (`reader`/`operator`/`admin`).
2. **Scope narrowing** (`Authorizer.effective_scope`) — narrows a request's
   requested scope to the intersection with the principal's actual grants,
   across `subscription`, `subscription_connection`, `business_service`,
   `application`, `environment`, and `owner` dimensions
   (`src/api/scope.py::GRANTABLE_DIMENSIONS`).

Verification for the pilot: a reader granted only `business_service=Retail`
must never see rows scoped to another business service, even when the read
action itself is permitted. This is exercised in
`tests/test_api_copilot.py` (`grounded` context assertion:
`"wealth" not in grounded`) and equivalent scope tests across the graph,
network, vulnerability, and twin routers.

- **Subscription scope**: enforced identically to business-service scope —
  a connection-scoped grant restricts every read/operate action to that
  `SubscriptionConnection`'s discovered resources.
- **Gateway grants**: `AIOPS_API_GATEWAY_GRANTS` is an explicit
  subject-to-role/scope JSON map, reviewed as part of onboarding a pilot
  tenant (who gets `admin`, who gets scoped `reader`).

## SPN (Service Principal) governance

Each `SubscriptionConnection` carries its own discovery SPN, isolated per
connection (`docs/PRODUCTION_RUNTIME_ACTIVATION.md`):

- Client secrets are never inlined in configuration; they are Key Vault
  references (`keyvault://<vault>/secrets/<name>`) resolved at connection
  time (`onboarding/credentials.py::KeyVaultSecretWriter`).
- A connection's SPN is scoped to read-only Azure Resource Graph access for
  its own subscription(s) — no cross-subscription credential reuse.
- Connection health (`GET /api/v1/connections/{id}/health`) surfaces SPN
  auth failures without ever returning the secret value itself.

## Key Vault

- RBAC authorization (not access-policy model) so grants in Terraform are the
  single source of truth for data-plane access
  (`infra/terraform/main.tf::azurerm_key_vault.main`).
- `public_network_access_enabled = false` with a `Deny`-default network ACL;
  reached only via the private endpoint on the `private-endpoints` subnet
  (`infra/terraform/persistence.tf`).
- `soft_delete_retention_days = 7`. **Action item for pilot go-live**:
  `purge_protection_enabled` is currently `false` (chosen for non-production
  teardown/rebuild convenience) and must be set to `true` before any real
  pilot customer secret is stored — tracked in `READINESS_REVIEW.md` and
  `RELIABILITY.md`.
- **Startup secret bootstrap** (`src/api/akv_bootstrap.py`) only ever writes
  an explicit allowlisted `secret_name -> environment_variable` mapping
  (`AIOPS_AKV_BOOTSTRAP_SECRETS`, default `{}`); it never scans or persists
  arbitrary environment variables, and a Key Vault write failure fails
  container startup rather than serving from a partially-synced vault.

## Secret rotation

| Secret | Rotation mechanism | Cadence |
| --- | --- | --- |
| Discovery SPN client secrets | Customer/tenant-owned rotation in Entra; AIOps reads the current Key Vault version at connection time (no caching beyond the request lifecycle) | Per customer's Entra secret expiry policy (recommend ≤ 180 days) |
| API bearer token (Key Vault, static-token mode only) | Manual rotation via Key Vault; not used in Entra-mode production | Dev/test only |
| Managed identity | No secret material — Azure-managed, token-based | N/A |
| Foundry data-plane token | Cached in-process with a 300s renewal margin before expiry (`src/operations/foundry_agent.py::_TokenProvider`); re-acquired transparently | Automatic, per-token TTL |

Rotating a discovery SPN secret in Key Vault requires no AIOps redeploy —
the next connection use resolves the current version.

## Network isolation

- API and web Container Apps run inside the `container-apps` delegated
  subnet of a dedicated VNet (`infra/terraform/persistence.tf`).
- Key Vault is reachable only over a private endpoint on the
  `private-endpoints` subnet with a private DNS zone
  (`privatelink.vaultcore.azure.net`).
- OneLake/Fabric and Foundry reachability is via the Container App's
  user-assigned managed identity; no inbound public exposure to those
  services is required from the API.
- The browser calls the API cross-origin from the web app's own domain;
  `AIOPS_API_CORS_ORIGINS` is pinned to the web app's FQDN, not `*`.

## Pilot security validation checklist

See `READINESS_REVIEW.md` for the full checklist; the security-specific
items are:

- [ ] `purge_protection_enabled = true` on the pilot Key Vault.
- [ ] `alert_email_addresses` configured so authorization-denial and
      provider-health alerts reach the on-call rotation.
- [ ] Entra tenant/audience values reviewed against the pilot customer's
      actual tenant (not a dev/test tenant).
- [ ] `AIOPS_API_GATEWAY_GRANTS` reviewed line-by-line for the pilot
      tenant's actual users/roles before go-live.
- [ ] Discovery SPNs confirmed read-only (no write/contributor role) against
      their target subscriptions.
