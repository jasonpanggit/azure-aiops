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
result.

Alert evaluations distinguish direct resource rules from log-query rules.
Missing direct resource rules are reported as direct-only gaps and do not prove
that broader log-query coverage is absent. Configured settings or action
references alone do not prove telemetry or notification delivery.

This source-only implementation deliberately adds no Azure provider, policy
store, grant, deployment pin, or mutation path. The current runtime configures
no `observability_read_port`, so production calls remain `unavailable`. Enabling
one requires a separately reviewed, read-only implementation of the typed
contract with qualified workload policy/categories/destinations,
Diagnostic Settings, alert rules, and Action Group references. Tests include
expected-output fixtures for evaluated positive/negative supplied evidence and
default-unavailable behavior; they are not deployed/live acceptance evidence.
