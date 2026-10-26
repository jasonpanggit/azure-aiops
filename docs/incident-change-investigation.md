# Bounded incident/change investigation (Package C)

Source-only extension of the existing Incident, Change and Resource Health &
Observability specialists. No new agents, provider authority, deployment,
Foundry identity, native ontology maintenance or lifecycle/canary gates.

## Entry and contract

On **Changes**, select one exact resource ARM id and an explicit timezone-qualified
time window, then open the shared Copilot. Resource Health cards offer the same
entry with the resource already selected. Choose:

- `recent_change`: selected-resource changes with timestamped alert/incident
  evidence, ranked low-confidence hypotheses, supporting/counterevidence and
  validation checks.
- `incident_impact`: the same collected evidence plus direct known dependency
  observations, separating observed symptoms from inferred possible impact.

Both use the existing governed `incidents` tool, with `scenario`, `resource_id`,
`since` and `until`. The server authorizes inventory identity before evidence
access and binds the hint to exactly one selected entity and the snapshot's
window filters. Windows are inclusive, chronological and at most seven days.
Invalid explicit scenario hints fail closed, not into a wider incident query.
Legacy incident-id and ordinary incident-list callers are unchanged.

The Changes surface uses the existing Change/Incident owners. Resource Health
uses its existing Resource Health & Observability owner and the same tool grant.
One invocation acquires each existing Change and Incident provider once and
shares the resulting bundle; no specialist independently reacquires it. Canonical
thread/evidence retention and the shared drawer's cancellation, scope-generation
and stale-response fences remain in use. Cancellation stops display/admission
of late results; it does not claim to interrupt an in-flight provider read.

## Evidence and limitations

The Change adapter reads normalized independent `ChangeIntelligence.changes`.
The Incident adapter accepts normalized `IncidentEngine` snapshots or the existing
`LiveIncidentEngine` Azure Monitor alert projection. The latter requires an
actual target resource and source event timestamp: it never substitutes the
alert id or query observation time.

The optional `incident_history_read_port_provider` reads historical control-plane
Activity Log operations and Resource Health availability transitions through the
existing registered connection identity. Inventory authorization and parameter
validation precede acquisition; ambiguous, missing, disabled or out-of-scope
connections fail closed, without credential fallback. No new inventory pipeline,
credential, permission grant or configuration is introduced.

Historical metrics remain **unavailable**. Current alert projections are not
complete alert lifecycle history, and the native history adapter does not widen
that coverage.
Projection acquisition does not prove complete logs, provider read permission,
freshness across the requested window or successful deployed execution. Every
family reports coverage explicitly; missing projections produce unavailable
coverage, not a healthy/authoritative-empty result. Observation times are retained
separately from event times. Zero observed changes never establishes no change.

Only existing direct downstream dependency identities are considered: maximum
depth one, at most ten neighbor identity checks, independently authorized through
the inventory read port. Friendly names and denied neighbors are withheld.
Truncation is disclosed. No arbitrary graph discovery, recursive provider reads
or ontology maintenance is initiated. A known dependency is a projection
observation, not proof of actual outage or authoritative current topology.

The returned timeline is capped at fifty chronologically ordered events and
ten ranked hypotheses. Stable local evidence references join hypotheses and
impact rows back to their supplied observations; governed tool citations retain
source-family receipts in the canonical thread. Ranking considers same-resource
ordering and explicitly retains earlier symptoms and recovery counterevidence.
It never upgrades temporal ordering to a mechanism or causal root cause.
Conflicting supplied symptoms remain visible; pre-existing specialist causal
scores are not imported as facts.

All arbitrary configuration property names, before/after values, provider titles
and summaries are withheld by the scenario adapter. Only bounded structural
facts, safe closed statuses, authorized identities and timestamps reach the
drawer/ledger. This intentionally conservative projection avoids leaking secrets
through free text as well as configuration values.

### Native history source contract

The adapter uses read-only HTTPS ARM GET operations documented by Microsoft:

- [Activity Logs List, 2015-04-01](https://learn.microsoft.com/en-us/rest/api/monitor/activity-logs/list?view=rest-monitor-2015-04-01):
  subscription management events with an exact `resourceUri` and inclusive
  `eventTimestamp` bounds. `$select` omits callers, claims, free text and
  configuration. Only successful `write`/`delete` operations become change
  candidates; failed/started/action operations remain activity observations.
- [Availability Statuses List, 2025-05-01](https://learn.microsoft.com/en-us/rest/api/resourcehealth/availability-statuses/list?view=rest-resourcehealth-2025-05-01):
  single-resource historical availability transitions. The documented operation
  does not specify supported time-filter syntax, so no invented filter is sent;
  returned transitions are locally restricted to the requested window. Only
  `occurredTime` is an event time; `reportedTime` remains separate provenance.
  Missing/invalid timestamps and foreign identities are excluded, not replaced
  with query time. `Unknown` is not a symptom or proof of health.

Each family attempts at most three pages and inspects at most 200 raw rows,
with at most one retry per page for 429/500/502/503/504, a fixed one-second
backoff and ten-second request timeout. Redirects are not followed. Continuations
must retain the same HTTPS ARM host and exact resource endpoint; original
query bindings are preserved and conflicting filters/versions are rejected.
There is no history cache or last-known-good fallback. UI cancellation still
fences late admission rather than promising interruption of synchronous reads.

The adapter conservatively declines windows outside
[Activity Log's 90-day retention](https://learn.microsoft.com/en-us/azure/azure-monitor/fundamentals/activity-log)
or Resource Health's documented
[30-day health-history horizon](https://learn.microsoft.com/en-us/azure/service-health/resource-health-overview#history-information).
The latter is an application query bound, not a guarantee that the REST
endpoint returns every portal history event. Neither source is an archival
backfill service. Future windows are not queried.
Boundaries use UTC normalization, including minimum/maximum year overflow
rejection before any provider acquisition.

Receipts distinguish source/API version, requested window, collection time,
provider-reported time, pagination exhaustion, inspected/invalid/excluded rows,
truncation, stale collection and sanitized failure codes. Permission denial,
unsupported resources, throttling, malformed data and transport errors are never
reported as healthy-empty. Activity ingestion may lag by 3-20 minutes; exhausted
pagination still does not establish full control-plane history. Every family
remains partial at best, including an empty successful response.

Activity Log and health receipts stay separate from snapshot changes and alerts.
Health availability observations can support or oppose low-confidence hypotheses,
but neither recovery nor temporal proximity establishes a cause or full-window
health. Only the selected resource gets historical reads. Dependency impact still
uses existing authorized direct projections; missing live dependency projection
remains unavailable, not an inferred complete topology.

**Operator prerequisites, not performed:** the existing connection identity needs
`Microsoft.Insights/eventtypes/values/read` and
`Microsoft.ResourceHealth/availabilityStatuses/read` at the selected resource's
applicable scopes (the Activity Log endpoint is subscription-scoped). Resource
Health must support the resource type and provide usable event timestamps.
No roles, credentials, pins or policies are changed here. Actual permissions,
live ARM schemas/completeness and authenticated deployed acceptance must be
qualified separately by the operator. Offline source tests are not live proof.

Scenario answers are deterministic and evidence-preserving even without Foundry;
they do not claim successful agent narration. Detailed timeline, hypotheses,
counterevidence, impact, unknowns and next checks remain visible alongside the
summary. Existing opt-in canonical rollout and authorization gates still apply;
this source work does not enable a rollout.

## Offline regression receipt

`tests/test_incident_scenarios.py` exercises exact relevant/unrelated and
out-of-window events, no observed changes, missing projections, incomplete live
alert identity/times, conflicting symptoms/recovery, redaction, unauthorized
resources, bounded/cyclic dependencies, and canonical API owner/citation/thread
wiring. `CopilotDrawer.test.tsx` covers exact scenario hints, detailed evidence
with synthesis, invalid windows and cancellation/stale completion after resource,
time-window and scope changes. These are offline fixtures, not live acceptance.
`tests/test_incident_history_reader.py` adds positive native ARM response fixtures,
exact resource/window and connection binding, retention and UTC-boundary controls,
bounded retries/pagination, denied/malformed/stale/truncated coverage, redaction,
source-specific partial failures, and governed tool/API integration.
