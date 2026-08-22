# Subscription Onboarding

Onboard a single Azure subscription using a dedicated service principal (SPN),
validate its access, map business context, run connection-scoped ingestion, and
monitor health — all without tenant-wide permissions.

Every operation is scoped to a `SubscriptionConnection`. Nothing in this
workflow requires tenant-level roles, Management Group access, or a shared
platform identity.

## 1. Create the SPN

Create one SPN per subscription. Do not reuse an SPN across subscriptions —
connection isolation is the security boundary.

```bash
az ad sp create-for-rbac \
  --name "hermes-conn-prod-core" \
  --role Reader \
  --scopes /subscriptions/<subscription-id>
```

Record the `appId` (client id), `tenant`, and the generated secret. The secret
is stored in a secret provider, never in this repository or its config files.

### Required roles

| Capability | Role | Scope |
| --- | --- | --- |
| SPN authentication | none (Entra ID app) | tenant |
| Subscription reachability | `Reader` | `/subscriptions/<id>` |
| ARG read | `Reader` | `/subscriptions/<id>` |
| Network resource read | `Reader` | `/subscriptions/<id>` |
| Patch/update read | `Reader` | `/subscriptions/<id>` |
| Advisor read | `Reader` | `/subscriptions/<id>` |
| ResourceChanges read | `Reader` | `/subscriptions/<id>` |

`Reader` at subscription scope satisfies every check. No `Owner`,
`Contributor`, `User Access Administrator`, or Management Group role is needed.

Only `spn_authentication`, `subscription_reachability`, and `arg_read` are
**required**. The remaining checks are optional: a connection missing them is
reported as `degraded` and still onboards, with reduced capability.

## 2. Store the secret

The secret is referenced by pointer, never by value. Two reference schemes are
supported.

The Workbench UI can accept the client secret directly during onboarding. In
that flow the Operations API stores the submitted value in the Key Vault named by
`HERMES_CONNECTION_KEY_VAULT`, then passes only the returned
`keyvault://<vault>/secrets/<name>/<version>` reference to Hermes.

### Key Vault (production)

```
keyvault://<vault-name>/secrets/<secret-name>
keyvault://<vault-name>/secrets/<secret-name>/<version>
```

```bash
az keyvault secret set \
  --vault-name kv-hermes-prod \
  --name hermes-conn-prod-core \
  --value "<spn-secret>"
```

Grant the Hermes runtime identity `Key Vault Secrets User` on the vault. If the
Workbench stores submitted secrets, grant the Operations API runtime identity
`Key Vault Secrets Officer` or an equivalent custom role with `set` permission on
that vault. The runtime resolves the secret at use time and discards it; it is
never written to the registry, logs, telemetry, or CLI output.

### Environment variable (local development only)

```
env://VARNAME
```

```bash
export HERMES_CONN_PROD_CORE_SECRET='<spn-secret>'
```

Use this only for local development. See [Local development](#5-local-development).

## 3. Onboard the subscription

```bash
hermes-arg subscriptions add prod-core \
  --name "Production Core" \
  --tenant-id <tenant-id> \
  --subscription-id <subscription-id> \
  --client-id <spn-app-id> \
  --secret-ref keyvault://kv-hermes-prod/secrets/hermes-conn-prod-core \
  --business-service Payments \
  --application checkout-api \
  --environment production \
  --project-owner alice@example.com \
  --support-team payments-sre \
  --criticality critical \
  --region eastus \
  --cost-center CC-1001
```

Business metadata is optional at creation and can be assigned later with
`subscriptions map`.

## 4. Command reference

All commands accept `--config` (default `config.yaml`).

| Command | Purpose |
| --- | --- |
| `subscriptions add <id>` | Register a connection with an SPN credential reference |
| `subscriptions list [--active-only]` | List registered connections |
| `subscriptions detail <id>` | Full connection record including metadata and freshness |
| `subscriptions update <id>` | Change name or rotate the credential reference |
| `subscriptions validate <id> [--check NAME]` | Run the access check suite |
| `subscriptions sync <id> [--mode MODE]` | Run connection-scoped ingestion |
| `subscriptions health [<id>]` | Health, sync state, and data freshness |
| `subscriptions map <id>` | Assign or merge business metadata |
| `subscriptions disable <id>` | Disable a connection (blocks sync) |
| `subscriptions enable <id>` | Re-enable a disabled connection |

### Validate

```bash
hermes-arg subscriptions validate prod-core
```

Runs all seven checks and returns a per-capability report with remediation
guidance. Exits non-zero when a required check fails. If authentication fails,
downstream checks are reported as `skipped` rather than as separate failures.

Run a subset with repeated `--check` flags:

```bash
hermes-arg subscriptions validate prod-core --check spn_authentication --check arg_read
```

Statuses: `healthy` (all passed), `degraded` (optional checks failed),
`failed` (a required check failed).

### Sync

```bash
hermes-arg subscriptions sync prod-core --mode initial
```

Modes are `initial`, `scheduled`, and `manual`. Each run produces an ingestion
run id and writes to a connection-isolated dataset root:

```
<output_dir>/connections/<connection-id>/
```

Sync state per connection tracks `status`, `last_synced_at`,
`last_successful_sync_at`, `last_failed_at`, `run_id`, `record_count`, and
`attempts`. A failed sync never overwrites `last_successful_sync_at`, so
freshness stays accurate through outages. Disabled connections refuse to sync.

### Health

```bash
hermes-arg subscriptions health
hermes-arg subscriptions health prod-core
```

Overall status is one of `healthy`, `stale`, `unhealthy`, `unknown`
(never validated), or `disabled`. Data older than 24 hours is reported as
`stale`.

### Map business metadata

```bash
hermes-arg subscriptions map prod-core \
  --business-service Payments \
  --environment production \
  --criticality critical
```

Fields merge: values you omit keep their previous value. Assigning
`--business-service` creates a business service linkage, and `--environment`
creates an environment mapping on the connection. `criticality` must be one of
`critical`, `high`, `medium`, `low`.

### Rotate a credential

```bash
hermes-arg subscriptions update prod-core \
  --secret-ref keyvault://kv-hermes-prod/secrets/hermes-conn-prod-core/<new-version>
hermes-arg subscriptions validate prod-core
```

## 5. Local development

```bash
uv sync --extra test
export SPN_SECRET='<dev-secret>'

hermes-arg subscriptions add dev-sandbox \
  --tenant-id <tenant-id> \
  --subscription-id <subscription-id> \
  --client-id <spn-app-id> \
  --secret-ref env://SPN_SECRET \
  --environment dev

hermes-arg subscriptions validate dev-sandbox
```

The registry is stored at `<output_dir>/state/subscription_connections.json`,
written atomically with `0600` permissions.

## 6. Secret handling guarantees

- Only `secret_ref` pointers are persisted; secret values never reach disk.
- Secrets are resolved on demand and passed straight to the credential factory.
- CLI output, connection details, and health reports are redacted before
  emission; keys matching `secret`, `password`, `token`, `api_key`, and
  `connection_string` are masked.
- A credential marked `active: false` refuses to resolve.

## 7. Connection lineage and concurrency

Every connection-scoped sync stamps connection identity and business metadata
onto each ingested row, so the ontology emits `SubscriptionConnection` and
`ConnectionHealth` entities from real ingestion — not just synthetic data. The
metadata supplied via `--environment` and `--business-service` drives the
`mapped_to` (Environment) and `supports` (Business Service) lineage edges,
completing Business Service → Application → Environment → SubscriptionConnection.

Because connection metadata is authoritative business context, the named
Environment and Business Service entities are created even when no resource tag
declares them.

The registry uses optimistic concurrency. Each write bumps a `revision` counter,
and a write based on a stale revision raises `RegistryConflictError` rather than
silently overwriting a concurrent update. Callers that read-modify-write should
pass `expected_revision` and retry after reloading on conflict.

`SemanticEngine.get_subscription_connection_context()` and
`SemanticIndexes.health_for_connection()` accept either the connection's
display name or its raw `connection_id`, and always resolve the linked
`Subscription` entity via its canonical `/subscriptions/{id}` key. Health
lookups are isolated per connection by graph edge (`has_health`) or exact
identity match — never by name prefix — so a connection id that is a prefix
of another (e.g. `prod` vs `prod-core`) cannot leak the wrong connection's
health status.

## 8. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Environment variable X ... is not set` | `env://` reference unresolved | Export the variable in the runtime environment |
| `No Key Vault client is configured` | Key Vault provider missing a client factory | Configure Key Vault access for the runtime identity |
| `spn_authentication` fails with authority error | Wrong `tenant_id` | Verify the tenant GUID matches the SPN's directory |
| `spn_authentication` fails with invalid client secret | Secret rotated or expired | Update Key Vault, then `subscriptions update --secret-ref` |
| `subscription_reachability` fails | SPN lacks `Reader` | Assign `Reader` at `/subscriptions/<id>` |
| `arg_read` fails | Missing ARG permission | Assign `Reader`; ARG inherits subscription RBAC |
| `patch_update_read` fails | Update Manager not enabled | Enable Azure Update Manager, or accept `degraded` |
| `advisor_read` fails | No Advisor data or permission | Assign `Reader`; new subscriptions may have no recommendations |
| `Subscription ... is already onboarded as '<id>'` | Duplicate active connection | Reuse or disable the existing connection |
| `connection_id must be 2-63 characters ...` | Invalid identifier | Use lowercase letters, digits, hyphen, underscore |
| Health shows `stale` | No successful sync in 24h | Run `subscriptions sync`, then check the failure `message` |
| Health shows `unknown` | Never validated | Run `subscriptions validate` |
| Sync raises `connection is disabled` | Connection disabled | Run `subscriptions enable` |
| `Registry revision N does not match expected M` | Concurrent registry write | Reload the connection and retry the update |
