# Data Governance

## Provenance

Every fact the platform serves carries an `evidence[]` entry in the API
envelope (`{data, evidence[], scope{}, knowledge_version?, warnings?,
pagination?}`) identifying its authoritative source, observation timestamp,
and a deep link/API locator back to that source
(`DATA_SOURCES.md` §1 "Source strategy"). Nothing is served as fact without
a traceable origin: ARG for resource identity/topology, Azure Monitor/LAW for
telemetry, Sentinel/ITSM for incidents, Defender for Cloud for findings,
Update Manager for patch state, Entra/Microsoft Graph for identity,
ServiceNow for CMDB/ITSM references, Azure DevOps for engineering context.

Hermes/the semantic layer does not become a second copy of authoritative
data — it retains identity, relationship evidence, and observation
timestamps, and queries the source live for current values
(`DATA_SOURCES.md` §1, `docs/semantic-architecture.md`).

## Retention

| Data | Retention | Where |
| --- | --- | --- |
| Log Analytics platform logs (Container Apps, request telemetry) | 30 days (`retention_in_days = 30`) | `infra/terraform/main.tf::azurerm_log_analytics_workspace.main` |
| Semantic graph / ontology generations | Governed by Fabric OneLake retention policy; superseded generations are retained per `docs/ONTOLOGY_RUNBOOK.md`'s Delta-version history | Fabric Lakehouse |
| Cached CVE enrichment | Bounded cache with its own TTL (`intelligence/vulnerability/enrichment_cache.py`) | OneLake |
| Multi-agent investigation ledgers | In-memory only, bounded to the most recent 1,000 entries (`MAX_LEDGER_ENTRIES`); **not durably retained** | Process memory — known gap, see below |
| Saved investigations / remediation plans / compliance exceptions | Browser `localStorage`, no server-side retention | Client browser — known gap, see below |
| Key Vault secrets (soft-deleted) | 7 days (`soft_delete_retention_days`) | Key Vault |

## Residency

All durable platform data resides in the Fabric workspace/OneLake region
selected at provisioning (`infra/terraform/fabric.tf`), and Azure resources
in the region set by `var.location`/`azurerm_resource_group.main.location`.
No data leaves the deployed Azure region except:

- Discovery reads against the customer's own Azure Resource Graph endpoint
  (regionless ARM control-plane API, standard Azure behavior).
- Foundry model calls to the configured Foundry project endpoint — pin
  `FOUNDRY_PROJECT_ENDPOINT` to a project in an approved region for the
  pilot customer's residency requirements.

## Access control

Covered in depth in `SECURITY.md`; the governance-relevant summary is that
every read is scope-narrowed to the calling principal's grants
(`Authorizer.effective_scope`) across subscription, business service,
application, environment, and owner dimensions — a pilot tenant's data is
never visible to a principal outside that tenant's grants, and a
business-unit-scoped reader cannot see another business unit's data even
within the same tenant.

## Audit

- Every unhandled API error is logged with a `correlation_id` and error code
  (`src/api/app.py`'s exception handler), enabling after-the-fact
  correlation between a user-visible error and server-side logs.
- Authorization denials are recorded via `ApiTelemetry.record_denied`
  (route + reason, no principal/payload detail) for aggregate monitoring;
  **per-request audit logging of who accessed what** is a gap — today only
  denial counts are recorded, not an allow-side access log. This is the
  single most important gap to close before an enterprise pilot handling
  regulated data: track as a pilot go-live conditional, not a hard blocker
  for a design-partner/internal pilot.
- Remediation plan approvals, CAB evidence, and incident collaboration notes
  are currently `localStorage`-based (see `RELIABILITY.md`), so there is no
  server-side audit trail for governance actions yet. This must be disclosed
  to any pilot customer relying on remediation approval as a compliance
  control.

## Deletion

- A `SubscriptionConnection` can be disabled/removed via the connections
  API; its discovered entities become `retired` (soft-deleted, not
  hard-deleted) per `docs/ONTOLOGY_RUNBOOK.md`, so historical evidence
  referencing them remains coherent rather than dangling.
- Key Vault secret deletion honors the 7-day soft-delete window before
  purge (purge protection is currently off in non-production — see
  `SECURITY.md` action item for pilot go-live).
- **Right-to-be-forgotten / full tenant offboarding** is not yet a
  single documented procedure — it is currently "disable the connection(s),
  let entities retire, and separately purge the OneLake generation." A
  single offboarding runbook step should be authored before a pilot customer
  requests full data deletion; tracked in `SUPPORT_MODEL.md`'s known
  limitations.

## Freshness

Every provider surfaces a `freshness` field and `ontology_version` via
`/health`; the UI is expected to render a stale-data indicator when
freshness exceeds `HERMES_PROVIDER_STALE_HOURS`. This is the mechanism that
keeps the platform honest about "real-time vs stale" — the entire premise
of the live/near-real-time pivot this session's history documents.

## Customer isolation

- Each `SubscriptionConnection` uses its own discovery SPN, isolated per
  connection — no shared credential across pilot customers/tenants.
- Scope enforcement (above) is the runtime isolation boundary within a
  single deployed environment.
- **Recommended pilot topology**: one deployed environment (Fabric
  workspace + Container Apps + Key Vault) per pilot customer, not a shared
  multi-tenant deployment, until row-level audit logging (above) and a
  documented offboarding procedure exist. This is the safest interpretation
  of "customer isolation" available today and should be stated explicitly
  in `ONBOARDING_GUIDE.md`.
