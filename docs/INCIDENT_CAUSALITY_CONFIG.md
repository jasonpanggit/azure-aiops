# Incident Causality Configuration

```yaml
fabric:
  incident_causality:
    enabled: true
    lookback_hours: 168
    max_incidents: 10000
    max_evidence_rows: 50000
```

`lookback_hours` controls how far before incident start governed evidence may be considered. Evidence up to one hour after incident start may be correlated as context but cannot receive preceding-cause points.

`max_incidents` and `max_evidence_rows` are fail-closed snapshot bounds. Values must be positive.

Public output additionally enforces bounded strings, nested collections, item counts, and serialized response size. These code-level safety limits prevent a governed but malformed source value from creating an unbounded agent response.

## Governed input tables

Optional operator-managed tables:

- `silver_incidents`
- `silver_alerts`
- `silver_incident_history`

Existing platform tables consumed automatically:

- `bronze_resources`
- `bronze_resource_changes`
- Patch Intelligence resource posture
- Lifecycle Intelligence resource posture
- Fabric Ontology and Semantic Knowledge Layer context

The platform does not query Azure Monitor, ServiceNow, or Azure resources from the intelligence layer. Those systems may populate governed Fabric projections through separately authorized ingestion pipelines.

## Required incident fields

- `incident_id`
- `title`
- `status`
- `severity`
- `started_at`
- canonical `target_resource_id`

## Required alert fields

- `alert_id`
- `title`
- `severity`
- `fired_at`
- canonical `target_resource_id`
- `signal`

All timestamps are ISO-8601. Future evidence and duplicate incident identities fail closed.

## Expanded event inputs

Governed rows may additionally carry `source`, `status`, `risk_score`, `change_type`, and bounded `changed_fields`. These fields classify Advisor, patch-success, create/delete/modify, ownership, and configuration events. Unknown or absent fields remain Unknown and do not become causal evidence.

The Semantic Knowledge Layer may contribute governed Advisor findings and dependency/business mappings. The incident layer never queries Azure Advisor or Azure resources directly.

## Strict bounds

All configured bounds must be positive integers; Booleans, fractions, zero, and negative values are invalid. Public strings, nested collections, incident findings, events, patterns, ontology rows, and serialized output are bounded. The public serialized ceiling remains 1 MB.
