# Operations API

The Operations API is the HTTP surface that makes AIOps the backend for the
Azure AI Operations Workbench UI.

**The API owns no business logic.** Every route composes an existing service —
`SubscriptionOnboardingService`, `SemanticEngine`, `IncidentEngine`,
`RemediationPlanner` — and every read is served through the Semantic Knowledge
Layer. No handler reads Fabric, ontology tables, or Azure Resource Graph
directly.

## Portal scoped bookmarks

The shared shell restores all nine repeated scope dimensions from each page URL
before mounting page data providers or contextual Copilot. The bookmark may
narrow an unconstrained dimension or select a subset of the current global
operating context. It cannot replace a selected value with an outside value,
clear an existing constraint through omission, or treat blank/control-bearing
values as an unscoped request. Invalid bookmarks withhold the page and expose
a recovery link preserving non-scope query fields and the global selection.
Bookmarks are not authorization; every backend read retains its own access and
provider-capability checks.

The global selector remains memory-only and unchanged by page bookmarks.
A page-level notice distinguishes the effective bookmarked scope from that
selector. Effective-scope changes remount page contents immediately, discarding
loaded data and local drafts; ordinary non-scope filters do not remount the
whole page. Copilot continuity observes this effective scope and retains its
existing server-revalidation requirement on scope changes. No conversation or
new authority is restored from a URL.
Global selector/account controls and continuity sign-out handling remain active
while an invalid bookmark withholds page data.

## Retained Resource Health observations

`GET /api/v1/resource-health/resource/history?resource_id=...` reads personal
receipts for the exact principal, effective scope and case-insensitive resource
address. Current Inventory membership and supported compute type are checked
before storage access. Reads do not need Monitor to be available, but cannot
recover a resource outside current Inventory authorization.

`POST` to the same route accepts only `{"expected_revision": 0}`, using the
reviewed revision. After a revision precheck, the server acquires the existing
authorized **per-resource** live detail/cache projection, never a subscription
bulk snapshot or browser measurements. Exactly one matching resource must have
no provider-reported error. Membership is checked again before CAS append.
Conflicts return 409; failed/invalid collections do not advance the revision.
Personal capture requires read authority, not permission to execute changes.

The existing `AIOPS_HOME` local/OneLake document root stores
`state/resource-health-history/<sha256([principal,effective_scope,resource_address])>.json`.
Latest 30 captures and a 256 KiB complete-document bound apply; capture 31
replaces the oldest. Strict schema, identity, duplicate, aware-time, chronology
and revision checks reject corruption instead of substituting empty history.
Retention is explicit, with no schedule, time-based purge or historical backfill.

Only eight finite nonnegative metric values/nulls, reported CPU classification,
collection/request/capture times, cache flag/TTL and diagnostic counts are
retained. Raw provider errors, warning text, credentials, arbitrary properties
and CPU series are not stored. Absent metrics stay null, not zero/healthy.
Collection time is not original metric sample time; aggregation windows, rate
semantics and threshold configuration are unreported. Cached receipts are not
independent telemetry samples. Comparisons are arithmetic only, not continuous
trends, availability, SLOs, verified improvement or causation. A deleted/recreated
resource at the same address is not proven to be the same incarnation.

The portal opens history on demand for a selected Inventory resource, independently
of live cards. The existing six-request **card** scheduler is unchanged; explicit
retention capture performs one separate server acquisition. This is not a
cross-tab/server-wide Monitor concurrency limit. Scope/resource changes discard
the prior panel and ignore late responses. A failed/unconfirmed capture withholds
the revision until explicit reload; aborting/closing cannot undo a capture
already received by the server. History is not mixed into current-health Copilot.

## Overview interpretation

The Overview reads Situations and Connections at offset 0 / limit 100,
plus the existing Network and vulnerability summaries. Its v1 posture
heuristic is `max(0, 100 - 18*loaded_P1 - 7*internet_exposed_count - 4*gap_count)`.
The explanation shows each count/weight, the unclamped deduction, saturation,
classification thresholds, and links preserving all selected scope dimensions.
An unavailable/invalid input withholds the score instead of counting as zero.
This formula is not an SLA, compliance result, complete-estate measure, or
learned probability. Reads are not atomic; findings can overlap across sources.
Situation rows can include closed lifecycle states; no active-only claim is
made for an unfiltered page. Vulnerability `internet_exposed_count` and the
legacy `reachable_server_count` are counts of findings in the current service,
**not distinct CVEs or servers**. The UI labels those units accordingly.

Source coverage shows loaded/reported page counts, partial-page indicators,
reported evidence freshness, warnings, and a scoped next-check link for each
source, including failed reads. Missing totals/evidence remain unreported.
Connection reviews prioritize explicit non-healthy, disabled, incomplete-sync,
missing successful-sync timestamp, and unmapped service/owner/environment rows.
Only explicit healthy, active, succeeded, timestamped, mapped registry rows
are ready in this local readiness view. This does not establish publication
freshness, resource health, or estate completeness. Review links select only
active connections; disabled rows link to the registry without an invalid
readiness bookmark. A scope change remounts the workspace immediately so old
observations are not scored or passed to Copilot under a new scope.
### Retained Overview observations

`GET /api/v1/overview/history` recovers only the current principal's exact
effective-scope history. `POST` to the same route accepts only
`{"expected_revision": 0}` (using the revision returned by the prior read);
it performs fresh server-side Situation (first 100 priority-ranked rows),
Network summary, and vulnerability summary reads through the same authorized
composers used by the current cards. It never accepts submitted counts.
Every source must succeed and validate before an atomic append. This is
sequential collection, **not an atomic cross-source or generation-pinned
snapshot**. Capture receipt time and each collection's start/end are separate
from the underlying reported source observation times. Missing source times
and knowledge versions remain unreported, not inferred.

Storage uses the existing `AIOPS_HOME` local/OneLake root at
`state/overview-history/<sha256([principal,effective_scope])>.json`.
The strict versioned document retains the latest **30** explicit observations,
at most **256 KiB including serialization**. Appending observation 31 removes
observation 1; there is no time-based expiry, scheduled capture, historical
backfill, or continuous monitoring guarantee. Only the three aggregate
formula inputs and bounded provenance/extents/warning counts are retained,
not raw resources, credentials, or customer-entered claims. Revision/ETag
conflicts return 409 without overwriting another capture. Reads reauthorize
but do not require the live providers; failed acquisitions leave the stored
history unchanged. Missing durable composition returns 503 and corrupt
retained state fails explicitly rather than returning an empty history.
The caller must retain permission to exactly the same scope to read it;
broader/narrower scope selections do not implicitly include other histories.

The portal requires two chronologically ordered retained observations for
arithmetic count/heuristic-score comparisons and exposes both source extents,
collection/source times, query versions, and provenance. It does not label a
delta as new/resolved resources, cause, verified improvement, complete-estate
growth, or same-population comparison. A captured observation and the live
cards are separate reads; capture does not silently replace the current cards.
Scope changes immediately discard the prior comparison and late responses.
No raw history is cached in browser storage.

## Independent change observations

`GET /api/v1/changes/observations` reads the existing governed ChangeIntelligence
projection independently of incidents. Missing providers return 503, not empty
success. Scope authorization/resource membership precedes facets, counts,
filtering and paging. Selected connection membership must be authorized before
provider resolution; a missing/inaccessible selection returns 404. Connection
selection narrows subscriptions, **not event connection provenance**. Missing
resource context cannot satisfy a constrained dimension. The route does not
invoke the incident API/provider or start collection, mutation or deployment.
Existing change-provider composition can read related snapshot tables/semantic
context and can itself be unavailable; source independence is not a claim of
zero underlying provider dependencies.

Optional `q` searches change identity/summary, resource, application and service.
`category` and `source` match exact projected labels; `since`/`until` are inclusive,
timezone-explicit ISO instants; reversed/naive/invalid ranges fail with 400.
`order=newest|oldest` uses time, normalized identity and source position for
deterministic ties. Standard offset pagination allows at most **100 rows**;
the portal requests 25. `pagination.total` counts matching authorized projection
rows, `authorized_count` counts all authorized rows before filters. Neither is
an estate or distinct-change count. Facets precede query filters and expose
first **100 labels** plus exact returned/total/truncation metadata; an exact
typed source beyond the suggestion cap still filters the full projection.
Serialized response data is bounded at **1 MiB**; oversized pages fail
explicitly instead of dropping rows. The source engine already bounds input
acquisition. Offset pages are separate reads, not generation-pinned history.

Observation IDs hash the resource join key, normalized source identity, time
and original position in the loaded projection. This avoids normalized/redacted
ID collisions and remains stable across filters/pages of that ordered
projection; it is **not** a globally durable Azure change identity. Internal
resource keys/IDs and raw states are not returned. Configuration comparison
exposes only `publicNetworkAccess`, `encryption`, `minimumTlsVersion`,
`httpsOnly`, `allowBlobPublicAccess`, `enableSoftDelete`, `sku`, and `vmSize`.
The finite allowlist also admits their exact `properties.` paths, except VM
size uses `properties.hardwareProfile.vmSize` and SKU uses `sku.name`.
Different paths remain separate, never silently merged. Values must match
finite named enums, booleans, or bounded conventional Azure
VM-size syntax; other values are withheld. Arbitrary/nested property paths and
values are withheld, with only a count of other names. Before/after absence
means **unreported**, not null, zero, addition or deletion. Arithmetic equality
is reported only when both typed values are known; this compares change
states, not expected baseline versus current configuration.

The portal restores scoped `change_q`, `change_category`, `change_source`,
`change_since`, `change_until`, `change_order` and `change_page` URL bookmarks
and browser Back/Forward. Invalid/duplicate continuations fail explicitly;
applying filters resets paging. All nine bookmarked scope dimensions are
restored before either provider is read, retaining/narrowing the in-memory
operating context. An invalid/broader bookmark fails with a recovery link,
never an unscoped fallback. The effective route scope is explicitly displayed;
this route-local behavior does not silently replace the global selector.
Scope/query changes discard prior observations
and late responses immediately. Explicit reload permits recovery without
changing filters. The read-only observation Copilot includes only loaded safe
fields/comparisons and reported freshness, never execution authority. Long
summary/resource/service/source text is excerpted with an explicit truncation
marker to preserve the contextual row byte bound; full projected text remains
visible in the portal.

Legacy incident timeline associations remain a separate independently failing
source: first 100 report rows, at most 50 rendered change-type events, reported
extents, and their own scoped review links/Copilot. They are not the durable
Situation queue and do not filter the independent feed. No HTTP success alone
establishes freshness, complete estate history, causal contribution, resolved
incident, confirmed outcome, baseline compliance or operational approval.

## Service catalog and detail interpretation

The catalog joins the complete accessible connection registry with the existing
incident report, **not** the durable Situation queue. Its mapping denominator is
loaded authorized connection rows, including disabled connections; it is not
an inventory/resource denominator or authoritative service registry. A row
requires service, owner, support team and environment to count as mapped in
this view. Missing mappings link to Connections; an unmapped label is not
treated as a real service detail identity. Incident associations can overlap
between services. Failed/loading incident reads withhold counts, chart and
clean-state claims in both the UI and contextual Copilot. Even an available
empty report means no associations in that report, never healthy availability.

Service detail projects known subject ownership, criticality, environment and
source-defined heuristic risk facts. Missing/ambiguous fields stay unreported;
risk is not SLO attainment. Object-based applications/infrastructure/dependencies
and top-level impact arrays retain relation, type and identity. Explicit
resource IDs navigate to the authorized asset explorer; supported named domain
references navigate to reauthorized lookups, and unsupported/untyped names
remain unlinked. Filters work across all loaded relationship observations,
with a visible 50-row render cap and loaded counts, not an asserted complete
dependency graph. Original source payloads remain behind disclosures.

Operational review prerequisites distinguish missing ownership/escalation,
unavailable/partial/stale/fresh source evidence and corresponding scoped
review links. HTTP success is not freshness: missing evidence stays partial,
explicit stale evidence stays stale. A reported owner is not tested on-call
coverage; no execution, rollback, failover or production-readiness approval is
inferred. These source contracts do not supply service availability, latency,
SLO windows/targets or error budgets. Those remain unreported rather than
being synthesized from incident counts. Scope changes remount both workspaces
immediately; all generated review and dependency links preserve selected scope.
Sourced reliability telemetry remains separate pending work; an interpretation
layer or a retained mapping count does not supply availability measurements.

### Retained service portfolios

`GET/POST /api/v1/service-portfolio/history` reauthorizes the exact principal and
effective scope on every read/capture. The POST body is only
`{"expected_revision": 0}`; service metrics cannot be submitted. The server
composes existing authorized Connections (up to 10,000, including disabled)
and incident report (first 100 rows, reported total retained) handlers. A
partial connection registry, failed provider, invalid aggregate, changed
revision/ETag or exceeded bound leaves the previous history unchanged.
Collection is sequential, not an atomic or generation-pinned estate snapshot.

Only up to **250 service labels** and their mapping/incident-association counts,
plus bounded source extents, collection/source times, query versions, reported
freshness and warning counts are retained. An incident counts once per distinct
trimmed service label in that report row; associations can overlap between
services. No raw connection/resource identities, owner names or credentials
are stored. Unmapped labels have a separate identity from a real service named
"Unmapped service". Counts refer to loaded source observations, not unique
resources, service requests or resolved incidents.

Storage uses existing `AIOPS_HOME` local/OneLake documents at
`state/service-portfolio/<sha256([principal,effective_scope])>.json`, with CAS
and a strict versioned, identity/chronology/count-validated schema. Retain latest
**20 explicit observations**, **2 MiB including serialization**; observation 21
evicts the oldest. Limits are conjunctive: 250 labels does not waive the byte
bound. No automatic cadence, timed expiry/physical purge or historical backfill
is claimed. Reads need no current provider, but retained access still requires
authorization to the identical scope. Missing storage is explicit 503;
corruption is explicit failure, never an empty-history fallback.

The portal selects two chronologically ordered receipts, filters their loaded
label union and renders at most 50 comparisons. Arithmetic is shown only for
labels represented in both collections. Absence is not zero, newly
created/deleted service, new/resolved incident, verified improvement or cause.
Reported source extents/freshness remain inspectable; capture receipt time
does not assert fresh source data. Scope changes immediately discard prior
comparisons and late responses. Capturing does not overwrite the live catalog.

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

Fabric capacity health probes the configured platform subscription even when
the page filters customer inventory to another subscription. Managed-identity
deployments use the Terraform-configured Fabric identity for this read-only
ARM request; the identity's capacity-scoped Reader assignment remains required.
When global Terraform role management is disabled, explicitly set
`enable_fabric_capacity_health_reader = true` to provision only this read-only
capacity-scoped assignment. This does not enable other role assignments or
change Container Apps registry authentication. Without this permission, the
capacity health remains unknown rather than reporting a healthy capacity.

### Portal assessment and readiness controls

The Connections readiness journey reads inventory, medallion layers, ontology
pointer state, and consumer capabilities independently for the selected connection.
Discovery records, inventory resources, and healthy dataset counts are different
units. Inventory's `query_version` is a query contract version, not proof of a
publication generation. Missing/stale stages remain explicit; sync success does
not establish Fabric publication or portal-wide readiness.

`POST /api/v1/subscription-connections/preflight` accepts the proposed create
payload with a one-time SPN secret and authorizes registry-write access over
its complete proposed subscription/business scope before probing anything.
It runs the seven incumbent fixed read-only access checks with a request-local
credential resolver. It does not write Key Vault, registry or health documents,
grant permissions, create a connection, start a sync or publish data. Stored
secret references and non-SPN credential kinds are not accepted on this path.
Missing runtime wiring returns 503, not an optimistic readiness result.

The response marks `advisory_only=true`, `persisted=false` and
`sync_started=false`; required failures and optional degradation stay distinct.
Failed probe details never echo SDK exception text or submitted credentials.
Preview is explicitly advisory in the onboarding form, is discarded on edits
or scope changes, and does not replace the fresh validation performed by
**Add subscription**. Closing the form clears the entered secret.

`GET /api/v1/inventory/resources` supports optional `q` (name, identity or type),
`family`, `resource_type`, and `resource_group` filters. Scope is enforced before
facets, filtering, totals and pagination. Type/group/query matching is
case-insensitive; family is an exact canonical value. Facets and
`represented_count` describe the entire authorized published resource
projection before these filters, not the current page or complete estate.
`family_availability.row_count` uses that same authorized observation grain,
not installed-software counts. Source state remains acquisition metadata.
Internal resource reads no longer silently stop at 10,000 rows.

`GET /api/v1/inventory/asset?resource_id=...` resolves an exact case-insensitive
identity within the effective scope. Missing and invisible identities return
the same 404. Only normalized fields and observed containment are returned;
raw provider properties, tags and inferred management-group ancestry are not
exposed. The resource-list API uses the same field allowlist, while trusted
internal adapters retain their lossless payloads. `generation_id` is the
reported publication generation (empty means unreported); `query_version`
remains a query contract. These are published observations, not live health.

The Inventory **Explore assets** view (`/inventory/assets`) restores validated
filters, page and exact resource bookmarks from its URL. Navigation preserves
current scope but never grants access; asset reads reauthorize independently.
Scope/query transitions immediately discard old facts. Resolved Situation
Resource links use this same destination. Historical asset snapshots and
queued export workers remain separate work; the retained export capture
below supplies bounded resume/cancellation without pretending to be a worker.
This navigation drilldown is explicitly excluded from model-bound Copilot
snapshots until a selected-asset evidence/tool contract is reviewed; the
existing governed Inventory Copilot is unchanged on `/inventory`. It never
substitutes a group snapshot for the selected asset.

The grouped `GET /api/v1/inventory/os`, `/inventory/software` and
`/inventory/paas` endpoints now apply `q` and exact case-insensitive group
filters before selecting the requested page. OS supports `os_name`,
`os_version`, `source_type` and `lifecycle` (`expired`, `expiring`,
`supported`, `review`). Software supports `software_name`, `publisher`
and `source_type`. Azure supports the raw provider namespace, `resource_type`
and the displayed `sku_tier` pair. Source/publisher filters select groups
containing that value; they do not repartition installations or machines.

`facets` count complete authorized groups before query filters, not
distinct assets. `represented_group_count` and matched `pagination.total`
remain distinct. `summary` covers all matching groups before pagination
and preserves machine, installation and Azure-resource grains separately.
An empty page retains those facets and totals. Source status counts remain
scope-limited acquisition observations, independent of table filters.
Internal full-group readers no longer silently stop at 10,000 groups.

The grouped portal queries these contracts rather than filtering only the
visible page. **Save view in URL** explicitly records all three tabs'
filters and page settings for bookmarks/history; invalid bookmarks are
reported, never silently converted to an unrelated view. Scope transitions
discard previous rows and in-flight detail responses. Charts and detail CSV
exports are explicitly visible-page evidence; source group memberships can
overlap and are not installation counts. The scope narrative remains
independent of table filters, and missing aggregate metadata is not presented
as complete-estate coverage.

**Retained resource exports** replace the old multi-request live scan.
`POST /api/v1/inventory/exports` accepts `expected_generation_id`, which must
match the real publication generation on one resolved InventoryService
instance. An empty or changed generation returns 409; a query contract is
never substituted for the pin. The server captures all authorized normalized
OS/platform observations from that instance exactly once, independently of
table filters. Only nine string columns are retained: family, resource_name,
resource_type, resource_id, subscription_id, resource_group, environment,
location, observed_at. Raw properties, tags and credentials are excluded.
This is published-observation evidence, not complete-estate or live-health
certification. No capture truncates silently: 1–50,000 rows and 16 MiB maximum
complete serialized document size; over-limit/empty requests return 400.

`GET /api/v1/inventory/exports/current` recovers the exact principal/effective
scope's manifest (or `null`). Each principal/scope has at most one ready
capture; replacement requires cancellation or expiry and otherwise returns
409. `GET /api/v1/inventory/exports/{export_id}/batches?offset=0` reads up to
500 retained rows. Offsets must be existing multiples of 500. The response
includes immutable manifest, offset, next_offset, and resources. Reloading,
retrying, or changing the active provider cannot mix capture generations.
Each request reauthenticates and reauthorizes current read scope; an ID is
not a bearer capability. Other authorized identities/scopes and replaced
IDs return 404; requests outside the caller's grants remain forbidden.
Recovery/batches/cancellation do not need the active inventory provider.

`POST /api/v1/inventory/exports/{export_id}/cancel` requires the manifest's
`expected_revision`. ETag compare-and-swap clears retained rows and revokes
future reads; conflicts return 409 and require review. It cannot revoke an
in-flight response or a downloaded file. Access expires at 24 hours, including
the exact expiry instant; the next access/create lazily clears the row body.
There is **no scheduled physical-purge guarantee** for idle documents.
Manifest metadata remains. Documents live in the existing
`AIOPS_HOME/state/inventory-exports/` store, keyed by hashed actor/exact scope.
Unreadable/corrupt storage fails explicitly, never resets to empty;
unconfigured storage returns 503.

The portal offers explicit separately downloaded CSV batches, a batch selector,
current-capture recovery, and a validated identity/offset resume URL.
It carries no resource payload in URLs or browser storage. The SHA-256 covers
the generation ID and complete sorted allowlisted rows, not a query version.
The client compares manifest identity, revision, scope and whole-capture
checksum, and checks row shape, count and offsets before emitting a batch;
it does not independently recompute the whole-capture digest per batch.
It neutralizes spreadsheet
formulas. An offered browser download is not a saved-file receipt. Pending
old-scope/unmounted/cancelled callbacks cannot emit a later download.

`GET /api/v1/compliance/design-policy` returns a revisioned architecture
assessment policy, exception decisions, and audit for the **exact effective
scope**. There is no inheritance between scope combinations. A missing document
returns revision-zero defaults; a missing store or unreadable document is an
error, not a reset. The runtime stores these documents under
`AIOPS_HOME/state/compliance/` using OneLake ETag compare-and-swap (atomic local
documents in local development). No new infrastructure or identity is required.

`PUT /api/v1/compliance/design-policy` accepts `expected_revision`, a complete
`policy`, and a nonblank `reason`. It requires write authorization over the
entire scope. `POST /api/v1/compliance/design-policy/exceptions` accepts
`expected_revision`, `action` (`accept` or `revoke`), `violationId`, `owner`,
`reason`, and `expiresAt` (future ISO timestamp with timezone for acceptance).
Exception decisions require both write and approve authorization. The server
records the authenticated principal, not the owner text, as the approver.
Conflicting revisions return HTTP 409; reload and review before retrying.
Expired, revoked, or prior-policy exceptions do not reduce the assessment score.
New policy saves record exact `policy_diff` field/before/after values,
`previous_policy_revision`, and the IDs of currently active exceptions
invalidated by that save. Metadata-only changes also invalidate exceptions.
Old audit entries are not backfilled with invented differences or counts.
The first explicit default-policy application may have an empty diff;
subsequent no-op replacements return 400 without incrementing revisions,
invalidating decisions, or appending an audit entry.
These are operator-declared architecture-assessment findings, not provider-side
policy exemptions or remediation approvals. Browser-local policy/exception
preferences are deliberately not imported as governed decisions. The audit is
append-only through this API and stops further writes at 10,000 entries until
administratively archived; no history is silently discarded.

The Compliance policy editor explains each draft field's actual evaluator
boundary and previews added/removed/reclassified findings against the **same
loaded observations**. It does not infer a historical cause or pretend to
compare retained evidence generations. Declared hub-routing/environment
intents have no connected local evaluator; server Network design gaps remain
independent. The projected heuristic score invalidates prior exceptions just
as a save would, but is neither an approval nor benchmark coverage.
Late reloads cannot replace a newer saved policy/decision revision.

The framework view pins its advisory catalog to
[Microsoft cloud security benchmark v1](https://learn.microsoft.com/en-us/security/benchmark/azure/overview-mcsb-v1),
not the separately published v2 preview. Known local finding types associate
with broad NS/AM/LT domains; exact provider `DOMAIN-number` control-ID formats
are candidate domain associations only. Ambiguous/custom/CIS/ISO labels
remain explicitly unmapped; no cross-framework equivalence is guessed.
All 12 v1 domains remain visible. No mapped evidence means **not assessed**,
never passed. Counts are distinct loaded observations (including pagination
limits), not evaluated-control denominators or complete-estate totals.
Risk acceptance remains evidence, never successful compliance coverage.
Mapped rows link to local findings or provider references and the official
domain guidance; missing/loading/error sources withhold conformance claims.
Unavailable governed/drift sources no longer render healthy empty states.

Public-access findings require an explicitly enabled observed
`public_network_access`/`publicNetworkAccess` setting; the word "public" in
serialized metadata, disabled/missing settings, or contradictory values do
not establish exposure. This setting does not itself prove reachability.
Unjoined CVE observations are labeled scope-level context, not resource links.

Agent finding accept/reject actions require an explicit finding in the current
ledger and a reason (1–1000 characters). Twin traversal and scenario analysis
require an explicitly selected observed resource; no first resource is chosen
automatically. Resource Health distinguishes still-loading, failed, and unknown
coverage from healthy observations, retaining the six-request hydration bound.

For local browser testing, run the API and web app separately. The API must be
running on port 8080 and the web app's `AIOPS_DEV_TOKEN` must
match one of the keys in `AIOPS_API_TOKENS`; otherwise requests will be
rejected with `401`. CORS preflight requests from the default Next.js origins
are enabled by default.

### Predeploy artifact intake

`POST /api/v1/changes/assess` retains its existing admin write authorization and
authorized read scope. Intake now rejects malformed present source arrays,
more than 500 entries per source change/file array, more than 24 nested levels
(root level 0), more than 50,000 JSON values, object keys over 256 Unicode scalar
characters, invalid Unicode, nonfinite numbers, and non-JavaScript-safe integers.
Submitted JSON values serialized as compact UTF-8 must not exceed 2 MiB. The
wire envelope is separately limited to 2 MiB + 16 KiB before JSON/model parsing;
deeply nested and duplicate-key JSON is rejected before model validation.
Missing
source arrays and unfamiliar action/resource fragments still produce defensive
ingestion unknowns; acceptance is not source-schema certification.

Known credential-like keys, named environment values and Terraform
`before_sensitive`/`after_sensitive` masks block assessment while detected
values are present. The portal supports bounded local UTF-8 JSON file intake or
paste, explicit local redaction to `[REDACTED]`, and a separate review checkbox.
Editing the artifact, changing its source, starting a file read or changing
scope invalidates that review. Late file reads cannot replace newer input.
No inspection or redaction operation makes a network write. Detection is
heuristic, not comprehensive DLP: users must remove secrets embedded in prose,
patches or arbitrary values themselves. Nothing is automatically submitted.

The server independently revalidates intake before acquiring source evidence.
An `artifact` receipt on the assessment contains source, compact UTF-8 size,
withheld-value count and SHA-256 of ASCII JSON with sorted keys, no whitespace
and envelope `{"schema_version":1,"source":SOURCE,"payload":PAYLOAD}`.
Its `canonicalization` is `python-json-ascii-sorted-v1`; this identifies the
submitted JSON values and source, not original file bytes, source authenticity,
or a release approval. Raw artifacts/before/after values are not retained in
assessment history. Withheld values become declared unknowns, suppress
confidence to low/unknown, and require advisory human review even when two
redacted markers compare equal. History remains bounded process-local state;
durable revision comparisons and CI review contracts are not established by
this intake receipt.

### Search exploration and durable queue bookmarks

`GET /api/v1/search/capabilities` requires the normal read authorization and
reports configured live, semantic, and exact-identity search prerequisites.
It inspects provider health without loading deferred semantic providers.
Configuration readiness is not a successful upstream probe.

`GET /api/v1/search` retains its unpaged shape when no exploration options are
supplied. Optional `offset` (0-100000), `limit` (1-100), `entity_type` (128
characters), and `source` (256 characters) enable exploration; a filter or
offset without a limit uses 25. Authorization precedes facets, filtering,
counts, and paging. `represented_count` and `aggregate_basis` describe the
authorized results represented by that provider response, **not estate-wide
totals**. Source truncation remains explicit; paging cannot recover omitted
provider results. Search URLs retain query, facets, offset, and current scope
as navigation context, never as an authorization grant.

`GET /api/v1/saved-views` and `PUT` to the same route retain **personal
navigation preferences**, not Search results or Situation evidence. Normal
read authorization is required on both operations; preferences are keyed by
the authenticated subject and exact effective nine-dimension scope, on the
existing local/OneLake root at `state/saved-views/`. Neither operation acquires
Search, Situation, inventory, or Azure providers. Missing/corrupt/unavailable
storage fails explicitly rather than returning an empty collection.

PUT requires `expected_revision` and the complete `views` list. Create-only
and ETag CAS prevent concurrent/stale replacement; conflicts return409.
An empty list explicitly removes all views in this personal scope.
Up to20 views combined and64KiB serialized state are supported. Each view
has a distinct lowercase slug `view_id` (max64), nonblank `name` (max80),
and a discriminating `kind`. Search views use `kind: "search"`, nonblank
`query` (max512), `entity_type` (max128), and `source` (max256).
Situation views use `kind: "situations"`, optional `query` (max256),
`priority` (`all`/`P1`/`P2`/`P3`), `assigned_owner` (max256),
`lifecycle_state` (max64), integer `older_than_hours` (24/168/720 or null),
and `sort` (`default`/`oldest`/`newest`). Unknown fields, arbitrary URLs,
submitted actors/scopes, results, handoff selections and execution fields
are rejected. The server issues revision and aware update time.

Both pages expose an on-demand named-view panel with explicit save,
replace-current-filters, delete and reload. It preserves other view kinds
when replacing the reviewed collection. Restoring constructs only an
allowlisted first-page URL with every current scope dimension, then reacquires
current authorized evidence. Source/permission changes may yield different
results or unavailability. Restoring an already-current first-page view
explicitly reacquires evidence even when no URL change occurs; restoring from
a later page navigates back to the first. Queue reload also invalidates reviewed
handoff selections. Scope changes remount the panel; aborted/late
responses cannot restore the old collection. An uncertain update invalidates
the collection and requires explicit reload/retry; it is never automatically
replayed. Preferences provide no access grant, schedule, evidence retention,
SLA, approval or execution authority. Do not place secrets in query text.
Search result navigation also preserves every selected scope dimension,
including repeated subscriptions, alongside its existing detail selector.

`GET /api/v1/situations` additionally accepts `assigned_owner` and
`lifecycle_state` (case-insensitive exact matches), `older_than_hours`
(0-87600), and `sort` (`default`, `oldest`, or `newest`). These operate on
the complete authorized Situation collection before pagination. Default
ordering is priority, then newest observed start; unknown or timezone-less
starts sort last and do not satisfy an age filter. `assigned_owner` is
deliberately distinct from the global `owner` scope dimension. Observed
age is not overdue status: no SLA deadline is inferred.

`POST /api/v1/situations/handoff` is a **read-only** authenticated export,
not approval, execution, or a durable export job. Supply `selections`, one
to 25 unique `{situation_id, run_id}` objects from the reviewed queue.
Every Situation is reauthorized and its run must still match: invisible
or missing selections fail the entire request with 404; changed runs
return 409. Unknown fields, duplicate IDs, missing runs, more than 25
selections, or a canonical artifact larger than 2 MiB are rejected.
The response contains the selected brief fields, only visible linked
evidence IDs, effective scope, export time, and a SHA-256 integrity digest.
The digest covers the artifact serialized as Python
`json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`
then UTF-8 encoded; `canonicalization` states that contract. It is an
integrity checksum, not a signed attestation or complete evidence bundle.

Situation triage URLs restore search, priority, `assigned_owner`, lifecycle
state, supported observed-age presets, sort, and page; history navigation
reruns the authorized read. Filter, page, or scope changes clear selected
handoff rows and invalidate in-flight downloads.

Connections URLs restore `tab` and `connection` without starting another
sync. A bookmarked connection is usable only after it is present in the
current authorized active list; unavailable selections do not silently
fall back to a different connection. Existing server sync-run recovery
continues independently of URL navigation.

The legacy `/vulnerabilities` route translates historical parameter names
through the shared Exposure allowlist; canonical names win regardless
of input order. Cursors, unrecognized keys, external origins, and invalid
values do not cross the redirect. Migration logs contain only a count,
allowlisted translated parameter names, and the number of discarded keys,
never query values, connection IDs, or unknown raw parameter names.

### Situation handover annotations and observed comparisons

`GET /api/v1/situations/{situation_id}/notes` reauthorizes the live Situation
and reads the exact effective-scope annotation history. Different scope
combinations do not inherit notes. The response includes `can_append` only
when the caller has operate rights over that **entire** scope.

`POST` to the same route requires operator authorization and accepts
`expected_revision`, `evidence_run_id`, and `text` (1-2000 nonblank
characters). The run must match the current authorized Situation at
request-time validation. The service records the authenticated actor,
UTC timestamp, unique note ID, and next revision. Client-supplied actors,
execution fields, and other unknown keys are rejected. Changed source runs
or history revisions return 409, with no automatic replay. Reload and review
the history before explicitly retrying; the UI retains unsent drafts.

Histories use the existing local/OneLake document store under
`AIOPS_HOME/state/situation-notes/`, with a SHA-256 name derived from the exact
Situation identity and effective scope. Create-only/ETag replacement prevents
lost concurrent appends. Missing storage and corrupt documents fail explicitly;
only a genuinely absent document starts at revision zero. Histories are
append-only through this API and capped at 200 notes; additional writes require
administrative archival, not silent deletion. These annotations are not
provider facts, source audit events, remediation approval, or execution
authority. Do not enter secrets.

Situation detail preserves unresolved link quality and enables navigation
only for resolved identities with supported destinations. Links carry current
scope as context; the destination still enforces authorization. Timeline source,
quality, and observed-time filters operate only on returned authorized evidence.
Two explicitly selected observations can be compared by assertion, trust facts,
and resource-reference differences. References appearing in only one observation
do **not** prove resources were created or deleted. Unknown/timezone-less times
cannot establish chronology; equal instants are explicitly coincident. Sequence
does not establish causation. Scope, Situation, or source-run changes reset
local timeline state and handover drafts.

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
| `/api/v1/network/intents` | GET personal saved connectivity expectations/receipts; PUT replace reviewed declarations |
| `/api/v1/network/intents/run` | POST explicitly analyze the saved reviewed suite against current scoped configuration |
| `/api/v1/network/topology/history` | GET personal exact-scope retained projections; POST explicitly capture reviewed history revision |
| `/api/v1/network/topology/history/compare` | GET paginated fixed-field differences between two retained captures |
| `/api/v1/network/review` | GET reauthorized exact gap/rule evidence for a separate advisory proposed-change review |

**Saved connectivity tests** are personal reader state, not global design policy,
deployment approvals or infrastructure execution. The server keys documents by
exact authenticated principal and effective nine-dimension scope, on the existing
local/OneLake root at `state/network-intents/`. GET and PUT do not acquire Network
providers. PUT requires `expected_revision` and the complete `tests` list (empty
explicitly removes declarations). Each test requires stable lowercase slug
`test_id` (max64), name (max80), source/destination (max512 each), port1–65535,
`Tcp`/`Udp`, and an `allowed`/`denied` expectation. Up to20 tests are supported.
Declarations are not proof of endpoint membership.

POST accepts **only** `expected_revision`, resolves one currently authorized
Network service, and batch-evaluates only the saved declarations. Any unresolved
verdict, unknown or missing enforcement point yields `indeterminate`, never
`match`; otherwise a configuration verdict either matches or mismatches the
declared expectation. There are no packet probes, traffic observations,
schedules, auto-fixes or execution grants. Foreign or unresolved endpoints cannot
recover configuration outside the current scope. Receipts retain exact tested
declarations, reviewed revision, aware acquisition times, reported snapshot
observation time (empty means unreported), verdicts and evidence-gap counts;
raw rules, provider errors and arbitrary property bags are not retained.

Every successful save/run advances the revision under create-only/ETag CAS;
stale/concurrent writes return409. Empty suites cannot run. Failed acquisitions
or invalid provider results never append a success receipt. Corrupt/unavailable
storage fails explicitly, not as empty history. The latest10 run receipts remain
under a512KiB serialized-document bound. Editing/removing declarations does not
rewrite receipts. Source generation and complete topology coverage are unreported;
repeated snapshot observation times do not prove independent acquisitions.
No time-based expiry, historical backfill, continuous coverage, compliance or
observed-reachability claim is made. Personal suite contents are not added to
the current Network Copilot snapshot.

**Topology history** retains the latest five explicit server-acquired summary
projections on the existing document root at `state/network-history/`, keyed by
exact principal and effective nine-dimension scope. GET does not acquire current
Network data. POST accepts only `expected_revision`, resolves one currently
authorized Network service and captures its untruncated summary. Truncation,
invalid projection, provider or storage failures do not append. Concurrent/stale
writes return409 under create-only/ETag CAS. Each capture has aware acquisition
start/finish times and reported source observation time (empty means unreported).
Schema one retains fixed node metadata, directed typed relationships and peering
configuration flags. It excludes raw rules, tags, arbitrary properties and
boundary peering identities; withheld boundary peerings and source-dropped
relationships have explicit counts. The bounds are1500 nodes/6000 edges per
capture and2MiB for the serialized five-capture document. Exceeding a bound fails
explicitly without truncation; narrow the scope instead.

Comparison requires two distinct retained `baseline_id`/`target_id` UUIDs in
capture order. It reads no new provider, compares exact fixed fields, and uses
standard `offset`/`limit` pagination with overall added/no-longer-observed/changed
counts. Expired, foreign-principal or different-scope IDs return404; same/reversed
captures return400. "No longer observed" means absent from a later projection,
not deletion. Source generation, complete estate coverage, lifecycle and causation
are unreported. Repeated source timestamps do not prove independent observations;
zero differences do not establish unchanged infrastructure. No background
collection, historical backfill, time expiry, packet probing, execution approval
or infrastructure mutation occurs. Personal retained contents are not added to
the Network Copilot context.

**Finding-to-predeploy handoff** adds `reviewed_digest` to current gap and rule
rows. The digest binds the full source finding, current policy digest, reported
source observation time, safe fixed context and exact effective scope. Network
links carry only kind (`gap`/`rule`), finding identity, digest and repeated scope
query parameters; raw evidence, rules and finding text are not carried in URLs.
GET `/network/review` requires `kind`, `finding_id` and `reviewed_digest`. It
acquires one currently scoped Network service, finds that exact current result
and rejects missing/foreign results404 or evidence drift409. Provider failure
remains503. Safe context is bounded to64KiB; full source properties are hash-bound
only, not forwarded. Repeated source times and missing generations do not prove
independent source refreshes.

The predeploy page requires explicit attachment to a separately entered artifact.
Malformed/incomplete references or failed evidence reads block linked submission;
removing context is a separate visible action. POST `/changes/assess` accepts
optional `network_review: {kind, finding_id, reviewed_digest}` only, reauthorizes
the current requested `ReadScope` (including all nine dimensions) and rechecks
the digest before assessment. Existing admin-level `WritePrincipal` authorization
is preserved, not broadened to readers/operators. Stored assessment context is
server-acquired and attributed to the submitting subject. Linked list/detail/
explain reads require that same subject and exact effective scope; they cannot
leak through a broader/narrower query or a direct ID. The assessment list wire
data remains an array, now consumed as such by the portal.

Assessment storage still follows the existing bounded **process-local** service;
this handoff does not claim a durable cross-replica audit trail. A separately
prepared artifact is never auto-generated from a finding. Neither attachment,
simulation nor CAB recommendation verifies that the artifact addresses the
finding, certifies a fix, approves deployment or grants execution. Failed/
unconfirmed submissions require explicit evidence reload/reattachment; there
is no automatic assessment retry or infrastructure mutation.

Three properties are load-bearing:

- **`indeterminate` is a real verdict.** `/traffic-flow` returns it when an
  endpoint or a higher-priority rule could not be resolved. It means no claim is
  made in either direction and must never be rendered as "allowed".
- **Scope filters the snapshot, not just the classifications.** Counts,
  connection IDs and derived summaries are narrowed with the resources, so a
  scoped caller cannot infer the size of the estate beyond their grant.
  Network REST reads, agent tools, Twin network projections and Governance
  network packs share the same nine-dimension projection: connection,
  subscription, environment, business service, application, owner, support
  team, region and criticality. Missing metadata does not match a selected
  dimension. Canonical `region` takes precedence over the native `location`
  fallback without overwriting that location; support-team and criticality
  metadata accept their canonical columns and tag aliases. Derived shared
  services retain these attributes. Filtering is configuration analysis, not
  a packet probe or a claim of observed reachability.
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
