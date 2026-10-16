# Operations API

The Operations API is the HTTP surface that makes AIOps the backend for the
Azure AI Operations Workbench UI.

**The API owns no business logic.** Every route composes an existing service —
`SubscriptionOnboardingService`, `SemanticEngine`, `IncidentEngine`,
`RemediationPlanner` — and every read is served through the Semantic Knowledge
Layer. No handler reads Fabric, ontology tables, or Azure Resource Graph
directly.

## Running

```bash
pip install -e ".[api]"
uvicorn --factory api.app:create_app --port 8080
```

When no context is supplied, one is assembled from the environment:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AIOPS_HOME` | `~/.aiops` | Connection registry and dataset root. |
| `AIOPS_CONNECTION_HOME` | `AIOPS_HOME` in local validation | Explicit durable connection registry and per-connection generation root. Required as a distinct OneLake URI in production. Governance reads this boundary, not the general state root, without resolving connection secrets. |
| `AIOPS_API_AUTH` | `token` | `token` or `gateway` (upstream-asserted identity). |
| `AIOPS_API_TOKENS` | — | Required when `AIOPS_API_AUTH=token`. JSON: `{"<token>": {"subject": "...", "grants": [{"role": "admin"}]}}`. |
| `AIOPS_API_GATEWAY_GRANTS` | — | Required when `AIOPS_API_AUTH=gateway`. JSON: `{"user@contoso.com": [{"role": "reader", "scope": {"subscription": ["..."]}}]}`. |
| `AIOPS_API_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated browser origins allowed to call the API. |
| `AIOPS_CONNECTION_KEY_VAULT` | — | Key Vault name used to store one-time client secrets submitted by the workbench before AIOps persists the returned `keyvault://...` reference. |

Misconfiguration fails at **startup**, not as a 500 on the first request: token
mode with no tokens, malformed token JSON, and an unknown auth mode all refuse
to boot. The default context (`api.runtime.build_context`) wires a
`semantic_provider` that rebuilds a knowledge snapshot from every registered
connection's synced `current/` dataset on each call (via
`InventoryDatasetMapper`), so search/context routes reflect real ingested data
once a connection has synced successfully. If no connection has synced any
data yet, the provider returns `None` and routes report `upstream_unavailable`
rather than implying an empty estate.

The request-time operational twin and live VM/server search resolve an
unrestricted authorized scope through active onboarded connections, just as
the Network page does. They do not require selecting a subscription first.
Semantic-only searches still report deferred semantic providers explicitly;
this does not enable full semantic hydration or optional Data Agent grounding.

For local browser testing, run the API and web app separately. The API must be
running on port 8080 and the web app's `AIOPS_DEV_TOKEN` must
match one of the keys in `AIOPS_API_TOKENS`; otherwise requests will be
rejected with `401`. CORS preflight requests from the default Next.js origins
are enabled by default.

For local testing, start the web app and API from `web/` in separate terminals:

```bash
npm run start
npm run start:api
```

`npm run start` starts the web app. `npm run start:api` reads `web/.env.local`.
When local SPN values are configured (`AZURE_SUBSCRIPTION_ID`,
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`), startup injects a
subscription connection backed by `env://AZURE_CLIENT_SECRET` so the workbench
can run real discovery/sync without persisting the secret. Startup removes any
previous fixture-only demo connection and runs initial sync for the SPN
connection; set `AIOPS_LOCAL_AUTO_SYNC=0` to skip that sync. Without SPN
values, startup falls back to a fixture-backed `.aiops-local` snapshot.

Set `AIOPS_LOCAL_SEED=0` for the existing live Azure-backed local development
mode, which uses the OneLake-backed registry. Live subscription onboarding and
sync still use `build_connection_ingestion()` and the Azure Resource Graph
client path.

The subscription onboarding route accepts either a pre-existing `secret_ref` or
a one-time `credential.client_secret`. When `client_secret` is supplied,
`AIOPS_CONNECTION_KEY_VAULT` must name the vault where the API runtime identity
can write secrets. The response and registry contain only the returned
`keyvault://<vault>/secrets/<name>/<version>` reference.

Interactive docs are at `/docs`; the machine-readable contract is at
`/openapi.json`.

The factory takes an `ApiContext`, which is the composition root:

```python
from api import ApiContext, create_app
from api.auth import StaticTokenAuthenticator
from api.rbac import Authorizer
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

context = ApiContext(
    onboarding=SubscriptionOnboardingService("~/.aiops"),
    authenticator=StaticTokenAuthenticator(principals),
    authorizer=Authorizer(),
    telemetry=ApiTelemetry(),
    semantic_provider=lambda: load_semantic_engine(),
    network_provider=lambda: build_service(ontology_rows()),
)
app = create_app(context)
```

`semantic_provider`, `incident_provider`, `remediation_provider`, and
`network_provider` are **callables**, not instances. The knowledge snapshot is refreshed out of band by
ingestion, so resolving the engine per request means a refreshed snapshot is
served without restarting the process.

## Response envelope

Every successful response is an envelope:

```json
{
  "data": { "...": "..." },
  "evidence": [
    {
      "source_engine": "semantic.SemanticEngine",
      "source_table": "ontology_entities",
      "timestamp": "2026-01-01T00:00:00Z",
      "subscription_connection": "prod-core",
      "resource_id": "Payments",
      "confidence": "high",
      "freshness": "fresh"
    }
  ],
  "scope": { "subscription": ["1111..."] },
  "knowledge_version": "v1"
}
```

`scope` echoes the **effective** scope the data was read under — after RBAC
narrowing — so the UI can render "you are seeing 2 of 7 subscriptions" honestly.

### Confidence

| Value | Meaning |
| --- | --- |
| `high` | Read from a system of record (e.g. the connection registry). |
| `medium` | Derived, correlated, or ranked (risk scores, incidents, search, graph traversal). |
| `low` | Heuristic or partial. |
| `unknown` | Not classified. |

### Freshness

Banded from the evidence timestamp: `fresh` (≤6h), `aging` (≤24h), `stale`
(>24h), `unknown`. A **future** timestamp is reported as `unknown`, not `fresh` —
a clock skew is a fault, not evidence of freshness.

## Authentication

Two authenticators ship:

- `StaticTokenAuthenticator` — bearer tokens compared with `hmac.compare_digest`
  (constant time); tokens shorter than 16 characters are rejected. For local
  development and tests.
- `HeaderPrincipalAuthenticator` — consumes an identity asserted by an upstream
  gateway (App Service Easy Auth, APIM). Gateway identity **does not grant
  authorization by itself**: `AIOPS_API_GATEWAY_GRANTS` maps a subject to
  explicit grants and must be configured before the process starts.

Direct JWKS/Entra token validation is **not implemented**. `Authenticator` is a
Protocol, so it is a drop-in addition when required. Do not expose the API
without a gateway in front of it until then.

## Authorization

Roles, least to most privileged:

| Role | `read` | `operate` | `write` |
| --- | --- | --- | --- |
| `reader` | ✅ | ❌ | ❌ |
| `operator` | ✅ | ✅ | ❌ |
| `admin` | ✅ | ✅ | ✅ |

- `operate` = run a sync, validate a connection (state-changing, not registry-mutating).
- `write` = create, update, disable, or map metadata on a connection.

A principal holds **grants**, each pairing a role with a scope. Grants may only
be scoped by `subscription` and `business_service`.

There are **two enforcement points, and both are mandatory**:

1. `Authorizer.require(principal, action)` — the coarse action gate.
2. `Authorizer.effective_scope(principal, action, requested)` — narrows the
   requested scope to the union of qualifying grant scopes.

The gate alone would let a reader of subscription A read subscription B. The
scope narrowing alone would let a reader mutate the registry. A request for a
scope entirely outside the caller's grants is `403`; an individual out-of-scope
resource is reported as `404`, because confirming its existence is itself a
disclosure.

## Scope model

Scope is expressed as repeated query parameters:

```
GET /api/v1/subscription-connections?subscription=1111-...&environment=prod
```

Dimensions: `business_service`, `application`, `environment`, `subscription`,
`subscription_connection`, `owner`, `support_team`, `region`, `criticality`.
Matching is case-insensitive. An omitted dimension is unconstrained.

Rows carrying **no** scope attributes are retained by filtering: an unlabelled
row is not evidence of belonging to someone else's scope.

## Errors

```json
{ "error": { "code": "not_found", "message": "...", "details": { } } }
```

| Code | Status |
| --- | --- |
| `invalid_request` | 400 |
| `unauthenticated` | 401 |
| `forbidden` | 403 |
| `not_found` | 404 |
| `conflict`, `already_exists`, `ambiguous_subject` | 409 |
| `not_implemented` | 501 |
| `upstream_unavailable` | 502 |
| `secret_unavailable` | 503 |
| `internal_error` | 500 |

Domain exceptions are translated centrally (`api/errors.translate`). Messages
pass through a secret scrubber, and the text of an **unrecognised** exception is
suppressed entirely — a 500 never echoes an upstream message that might contain
a connection string. Validation failures report which field failed and why, but
never echo the submitted value.

Every response includes `X-Correlation-ID`. Supply a valid
`X-Correlation-ID` request header to retain an existing trace identifier;
otherwise AIOps generates one. API logs include only the correlation ID,
templated route, method, status, and duration — never request payloads,
headers, principals, or scopes.

## Pagination and truncation

Collection routes accept `offset` (default `0`) and `limit` (default `100`,
maximum `500`). A successful paged response carries:

```json
{ "pagination": { "offset": 0, "limit": 100, "total": 238, "next_offset": 100 } }
```

Bounded semantic traversals can emit a `warnings` array containing a truncation
notice. The UI must display it rather than treating the result as complete.

## Endpoints

### Subscription connections

| Method | Path | Action |
| --- | --- | --- |
| GET | `/api/v1/subscription-connections` | read |
| POST | `/api/v1/subscription-connections` | write |
| GET | `/api/v1/subscription-connections/{id}` | read |
| PATCH | `/api/v1/subscription-connections/{id}` | write |
| PUT | `/api/v1/subscription-connections/{id}/metadata` | write |
| POST | `/api/v1/subscription-connections/{id}/disable` | write |
| POST | `/api/v1/subscription-connections/{id}/enable` | write |
| POST | `/api/v1/subscription-connections/{id}/validate` | operate |
| POST | `/api/v1/subscription-connections/{id}/sync` | operate |
| GET | `/api/v1/subscription-connections/{id}/health` | read |

Request bodies use `extra="forbid"`, so a stray top-level `client_secret` field
is rejected with `400` rather than silently ignored. `CredentialReferenceModel`
accepts either `secret_ref` or one-time `client_secret`; no secret material is
returned, and AIOps persists only the Key Vault reference.

### Context (Semantic Knowledge Layer)

| Path | Returns |
| --- | --- |
| `/api/v1/search?q=` | Intent-driven operational search |
| `/api/v1/business-services/{name}` | Business service context |
| `/api/v1/applications/{name}` | Application context |
| `/api/v1/environments/{name}` | Environment context |
| `/api/v1/subscriptions/{name}` | Subscription context |
| `/api/v1/subscription-connections/{name}/context` | Connection context with lineage |
| `/api/v1/resources/{resource_id}` | Resource context |
| `/api/v1/risk/{subject}` | Aggregated risk |
| `/api/v1/impact/{subject}` | Blast radius |
| `/api/v1/graph/dependencies/{application}` | Dependency graph (`direction=upstream\|downstream\|both`) |

`search` is **intent-driven, not free text**. Supported phrases: `production
applications`, `applications owned by <owner>`, `servers with failed patches`,
`resources missing ownership`, `applications missing ownership`, `resources
related to business service <name>`, `critical infrastructure`. An unsupported
phrase returns `400` listing what is supported — deliberately not an empty
result set, which the UI would render as "nothing found".

### Operations

| Path | Returns |
| --- | --- |
| `/api/v1/incidents` | Correlated incidents |
| `/api/v1/incidents/{id}` | Incident detail and timeline |
| `/api/v1/remediation-plans` | Remediation plans |
| `/api/v1/remediation-opportunities` | Remediation opportunities |

If no engine provider is registered these return `502 upstream_unavailable` with
the capability name. They do **not** return an empty list, which would be
indistinguishable from a healthy, incident-free estate.

## Network intelligence

Served by `NetworkIntelligenceService` over the ontology snapshot.

| Path | Purpose |
| --- | --- |
| `/api/v1/network/topology` | Stitched hub-spoke topology and summary |
| `/api/v1/network/topology/hubs/{vnet_id}/dependents` | What depends on the hub |
| `/api/v1/network/firewall-bypass` | Which spokes bypass the hub firewall |
| `/api/v1/network/traffic-flow` | Can source reach destination, and which rules decide |
| `/api/v1/network/gaps` | Intended-design and structural gaps |
| `/api/v1/network/rule-findings` | Firewall and NSG tightening analysis |
| `/api/v1/network/summary` | Dashboard card payload |

Three properties are load-bearing:

- **`indeterminate` is a real verdict.** `/traffic-flow` returns it when an
  endpoint or a higher-priority rule could not be resolved. It means no claim is
  made in either direction and must never be rendered as "allowed".
- **Scope filters the snapshot, not just the classifications.** Counts,
  connection IDs and derived summaries are narrowed with the resources, so a
  scoped caller cannot infer the size of the estate beyond their grant.
- **`intended_design_declared: false` is reported, not silently passed.** With
  no design policy only structural gaps can be found, never conformance gaps.

Tightening findings are `medium` confidence because no flow logs are ingested:
"unused" and "shadowed" are inferred structurally, and each finding states that
in its own `basis`.

## Not implemented

These paths are published as **contracts only** and return `501
not_implemented` with `details.capability` and `details.roadmap`. The underlying
engines do not exist in the codebase.

| Path | Capability | Roadmap |
| --- | --- | --- |
| `/api/v1/kbs` | `vulnerability.kb` | Prompt 17 |
| `/api/v1/cves` | `vulnerability.cve` | Prompt 17 |

There is no CVE, CVSS, or KB article model anywhere in the repository. Publishing the paths now lets the UI
bind to stable routes; returning `501` rather than an empty payload keeps
"not built yet" distinguishable from "found nothing" — a distinction that
matters most on security-facing views.

## Telemetry

Emitted through the OpenTelemetry metrics API already used by the intelligence
engines:

- `aiops.api.requests` (counter) — by route, method, status **class**
- `aiops.api.request.duration` (histogram, ms)
- `aiops.api.authorization.denied` (counter)

Route labels are **templated paths**, not concrete URLs, and status is recorded
as `2xx`/`4xx` rather than per-status. No payloads, headers, principals, or
scope values are recorded, so telemetry can never become a secret sink.

## Health

`GET /health` is unauthenticated and reports liveness plus
`semantic_snapshot_loaded`, which distinguishes "the process is up" from "the
process can answer questions".
