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
alert id or query observation time. No new Azure activity-log read is wired.

Historical resource-health events/metrics are **unavailable** through these
adapters. Current alert projections are not complete alert lifecycle history.
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
