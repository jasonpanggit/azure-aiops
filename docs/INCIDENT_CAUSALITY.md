# Incident Correlation and Operational Causality

## Scope and safety boundary

This layer is read-only. It ranks evidence-backed probable causes and business impact; it never confirms causation, executes remediation, changes infrastructure, or calls Azure directly. Inputs are governed OneLake/Fabric projections and public Semantic Knowledge Layer APIs.

## Architecture

1. Governed incident and alert facts, ARG resource changes, Patch Intelligence posture, and Lifecycle Intelligence posture enter through Fabric snapshots.
2. Canonical lowercase resource identity joins evidence to inventory.
3. Public `SemanticEngine` resource and impact APIs enrich each resource with applications, services, business services, owners, support teams, dependencies, and blast radius.
4. `IncidentCorrelator` applies bounded temporal and target correlation.
5. `CausalityEngine` ranks evidence using explainable factors.
6. `IncidentPatternEngine` identifies recurring evidence patterns.
7. `IncidentSummaryEngine` produces operational and executive views.
8. `OperationsAgent` exposes a closed, read-only command set.

See `docs/incident-causality-architecture.html` for the rendered diagram.

## Workflow

```text
Incident/Alert
  -> canonical resource match
  -> bounded time-window evidence
  -> resource change / patch / lifecycle correlation
  -> semantic dependency and ownership enrichment
  -> causal scoring and confidence
  -> probable cause ranking
  -> blast radius and business impact
  -> recurring-pattern detection
  -> advisory report
```

## Causality model

The deterministic 0–100 causal score is evidence strength, not proof:

| Factor | Maximum |
|---|---:|
| Canonical target match | 35 |
| Temporal proximity before incident | 25 |
| Signal severity | 20 |
| Causal relevance by evidence type | 20 |

Classification:

- 60–100: Probable cause
- 35–59: Contributing factor
- 0–34: Contextual evidence

Confidence is capped at 0.95. Evidence after incident start receives no temporal or causal-relevance points. Missing or malformed evidence is not converted into a conclusion.

Only preceding alerts, resource changes, and explicit failed/noncompliant patch events are causally eligible. Lifecycle posture is correlated as contextual risk and is capped below the causal threshold. Evidence after incident start is retained only as contextual evidence and never appears under probable causes.

## Operational context and business impact

Every incident finding includes the public resource, application, business service, owner, support team, environment, criticality, ranked causes, impacted applications/services/business services, blast-radius counts, freshness, and an advisory-only validation action.

## Pattern analytics

Recurring patterns require at least two distinct incidents with the same resource and probable evidence type. Pattern output includes occurrence count, incident IDs, business service, confidence, and evidence. Results are bounded.

Governed incident history is timestamp-validated, deduplicated, bounded, and contributes distinct historical incidents to pattern analysis. Canonical resource identity removes case and trailing-slash aliases. Nested impact collections are capped at 50 by default and disclose truncation.

Public strings are capped at 512 characters, public incident lists are capped at 50 by default, and each serialized intelligence response is limited to 1 MB. Oversized responses fail closed. Literal, percent-encoded, and double-encoded ARM paths plus labeled tenant/subscription/run identifiers are redacted or replaced with opaque hashes before output.

## Reports

- Incident Correlation Summary
- Operational Causality Report
- Business Impact Report
- Recurring Pattern Report
- Executive Incident Brief

Example executive headline:

```text
2 incidents analyzed; 2 have ranked probable causes; 1 business service exposed.
```

## Agent commands

- Analyze Incident Causality
- Show Probable Root Causes
- Show Incident Blast Radius
- Show Correlated Incidents
- Show Recurring Incident Patterns
- Generate Incident Correlation Report
- Generate Incident Executive Brief

Commands require `Enterprise` / `IncidentPortfolio`. Unsupported and action-oriented requests fail closed.

## Telemetry

- `incident.analysis.duration`
- `incident.correlation.latency`
- `incident.causality.latency`
- `incident.business_impact.latency`
- `incident.pattern.latency`
- `incident.report.duration`
- `incident.intelligence.freshness`

Metric attributes contain no resource or incident identifiers.

## Testing strategy

Tests cover causal scoring, future evidence, correlation, business impact, recurring patterns, reports, telemetry, public Semantic API integration, Fabric snapshot integration, command bounds, identifier safety, and read-only behavior. Sample data is in `tests/fixtures/sample_incident_causality.json`.

## Expanded operational reasoning framework

The requested framework is implemented under `src/intelligence/incidents/` while the hardened `src/intelligence/incident/` package remains the correlation foundation:

- `incident_engine`: enriched incident reasoning and knowledge projection.
- `incident_correlator`: bounded target/time correlation compatibility surface.
- `root_cause_engine`: probable causes, confidence, evidence, and reasoning chain.
- `blast_radius_engine`: applications, services, functions, owners, teams, and dependency tree.
- `event_timeline`: normalized chronological event chains.
- `operational_patterns`: recurring patch, lifecycle, ownership, configuration, and chronic-risk patterns.
- `incident_summary`: engineer, manager, director, and CIO summaries.
- `causality_graph`: incident ontology projection.

### Normalized operational events and timeline

The event model covers patch failure, patch success, Advisor alert, resource created, resource deleted, resource modified, OS EOL threshold crossed, ownership change, configuration change, service degradation, and incident. Each normalized event contains an event identity, type, timestamp, source, summary, and evidence.

Events are ordered by timestamp and identity. Named chains describe failure, VM reboot, missed patch, exposure increase, application-at-risk, and business-service-impact sequences. A chain is an evidence sequence, not proof of causation.

### Root-cause reasoning model

The root-cause result carries ranked probable causes, contributing factors, confidence capped at 0.95, evidence, timeline, impacted systems, and a reasoning chain. Canonical target match, preceding temporal proximity, signal severity, and explicit causal relevance determine ranking. `confirmed_cause` is always false because this read-only layer cannot prove causality.

### Blast-radius and business-impact model

The expanded blast radius includes impacted applications, operational services, business services, business functions, owners, support teams, upstream dependencies, downstream dependents, and a bounded dependency tree. Business impact exposes contextual risk, patch, and lifecycle scores only when governed evidence exists; missing evidence remains Unknown.

### Incident knowledge model

First-class ontology entities are `Incident`, `OperationalEvent`, `RootCause`, `RiskPattern`, `BlastRadius`, `DependencyChain`, and `OperationalFinding`. Relationships connect incidents to findings, events, probable causes, blast radius, and dependency chains. Projection endpoints are referentially validated and count/truncation metadata is emitted.

### Expanded agent commands

- Analyze Incident
- Explain Root Cause
- Show Blast Radius
- Show Dependency Chain
- Show Operational Timeline
- Show Recent Causes
- Show Repeated Operational Risks
- Generate Incident Report

Incident-specific commands require a governed incident ID with `subject_type=Incident`. Portfolio commands require `Enterprise` with `subject_type=IncidentPortfolio`.

### Expanded telemetry

- `incident.timeline.generation.duration`
- `incident.blast_radius.generation.duration`
- `incident.root_cause.analysis.duration`
- `incident.knowledge.retrieval.latency`
- `incident.pattern.detection.duration`

### Sample CIO summary

```json
{
  "summary": "Operational causality remains probabilistic; prioritize chronic contributors and critical service exposure.",
  "business_services": ["Retail Checkout"],
  "confirmed_cause": false,
  "read_only": true
}
```
