# Resource Health observability coverage scenarios

The Resource Health Copilot drawer exposes two read-only actions through its
existing `resource_health_observability` specialist and governed `incidents`
tool:

- `diagnostic_settings_coverage` compares Diagnostic Settings with an explicit
  workload logging policy.
- `alert_delivery_coverage` checks disabled alert rules and Action Group
  references when those configuration sources are available.

The optional `observability_read_port` is a provider-neutral injection
contract, not a collector. It accepts only typed, effective-scope-bound policy,
Diagnostic Settings, alert-rule, and Action Group evidence. When such evidence
is injected, deterministic evaluators compare required categories/destinations,
apply unexpired resource-specific policy exceptions, and count disabled rules
and missing/invalid action-group references. Without a configured reader,
actions return `unavailable`, not `empty`, `healthy`, or `compliant`.

The governed `InventoryReadPort` supplies the existing scoped inventory
snapshot; no second inventory acquisition path was added. The evaluator reports
supported and excluded resource types, plus unreadable and unknown resource
counts when present in typed evidence. Even an exact, scope-qualified published
snapshot does not qualify live-estate completeness or freshness: the current
inventory contract exposes an observation timestamp but no freshness
qualification. Therefore injected-fixture evaluations are `partial`, and do
not claim a complete authorized live-resource denominator or compliance. An
empty inventory, stale/incomplete configuration collection, foreign scope
binding, pagination mismatch, or unqualified scope cannot produce a healthy
result. The current inventory contract does not qualify workload ownership,
so findings are not attributed to an owner.

Alert evaluations distinguish direct resource rules from log-query rules.
Missing direct resource rules are reported as direct-only gaps and do not prove
that broader log-query coverage is absent. Configured settings or action
references alone do not prove telemetry or notification delivery.

The runtime wires an ARG-backed reader through the existing connection-scoped
live resource provider; it adds no credentials, policy writer, grant, deployment
pin, or mutation path. Alert rules and Action Groups are queried only for
enforceable subscription scopes. Unsupported scope dimensions, incomplete or
stale collections, and unknown enabled states cannot produce evaluated findings.
Missing groups are classified invalid only in a complete, fresh authorized
collection. Scheduled-query rules are never treated as direct-resource coverage.

Diagnostic Settings use the existing authorized inventory result as their
resource denominator and read settings from ARM through each resource's existing
subscription connection. Resource reads are bounded and paginated; missing,
denied, malformed, or over-limit pages are unknown/incomplete, not an empty
configuration. Destination references are compared as opaque configured
identifiers and are never dereferenced, so a central logging destination does
not expand the caller's resource scope. Required categories must be configured
at each required destination; a category routed only elsewhere does not satisfy
that destination. Enabled `categoryGroup` entries abstain as unknown until a
qualified group-to-category expansion is available, rather than becoming false
missing-category findings. Noncanonical ARM paths are rejected before credential
acquisition. The connection principal needs the
read-only `Microsoft.Insights/diagnosticSettings/read` operation; no role is
granted by this feature.

The workload logging policy has no defaults. An operator-reviewed document must
be present at `state/workload_logging_policy.json` in the existing document
store. It requires schema version, explicit revision and policy version,
approval status/identity/time, validity end, exact subscription scope,
supported resource types, required log categories and canonical destination
references (`log_analytics:`, `storage:`, `event_hub:`, or `marketplace:`).
Resource exceptions require an in-scope resource ID, an approver, reason, and
expiry. Missing, invalid, unapproved, or scope-mismatched policy is unavailable;
an expired policy is stale. The API does not create or modify this document.

Diagnostic and alert results remain at most `partial` while inventory freshness
and live-estate completeness are unqualified; observed configuration does not
prove telemetry or notification delivery. Live ARM/ARG schema and connection
behavior have not been qualified by the offline tests. Tests include
expected-output fixtures for evaluated positive/negative supplied evidence and
default-unavailable behavior; they are not deployed/live acceptance evidence.
