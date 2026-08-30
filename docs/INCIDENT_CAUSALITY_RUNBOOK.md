# Incident Causality Operational Runbook

## Preconditions

- Fabric sync is healthy and the latest completed snapshot is available.
- Incident/alert projections, when configured, use canonical resource IDs.
- Semantic resource and impact contexts are healthy.
- Patch and Lifecycle Intelligence snapshots are available or explicitly absent.

## Verification

```bash
uv run --extra test pytest tests/test_incident_*.py tests/test_causality_engine.py -q
uv run --extra test ruff check src tests
aiops plugins doctor --ci .
```

Smoke checks:

1. Compare incident and alert table counts to their governed sources.
2. Confirm no future timestamps or duplicate incident IDs.
3. Confirm every incident resource resolves through public Semantic APIs.
4. Run `Analyze Incident Causality` for `Enterprise` / `IncidentPortfolio`.
5. Confirm causes include factors, evidence, confidence, and probabilistic wording.
6. Confirm business service, owner, support team, and blast radius are present or explicitly Unknown.
7. Confirm all actions are advisory-only.
8. Confirm post-incident evidence and lifecycle posture never appear as probable causes.
9. Confirm duplicate evidence/history identities and canonical resource aliases fail closed.
10. Run `Analyze Incident` for a governed `Incident` ID and inspect related events, reasoning chain, confidence, dependency tree, and business impact.
11. Run `Show Operational Timeline` and verify deterministic chronological ordering.
12. Run `Show Repeated Operational Risks` and confirm patterns require repeated evidence.
13. Validate the incident ontology projection has no dangling relationship endpoints.

## Interpreting results

A “Probable cause” is a ranked hypothesis supported by target, time, severity, and evidence-type signals. It is not a confirmed root cause. Operators must validate telemetry and source-system evidence before deciding on change or remediation.

## Monitoring

Alert on:

- stale incident intelligence freshness;
- zero incidents after a previously nonzero governed feed;
- sudden growth in unresolved resource identities;
- evidence bounds exceeded;
- correlation, causality, pattern, or report latency regression;
- timeline, blast-radius, root-cause, knowledge-retrieval, or expanded pattern latency regression;
- missing incident/alert Delta tables when feeds are expected.

## Troubleshooting

### No probable causes

Check canonical resource identity, correlation lookback, evidence timestamps, and source freshness. Do not lower thresholds until evidence quality is validated.

### Missing business impact

Repair authoritative resource-to-application and application-to-business-service relationships. The engine reports Unknown rather than inventing mappings.

### Excessive recurring patterns

Validate incident deduplication and source incident identity. Patterns require distinct incident IDs.

## Rollback

Restore the prior application package and the last completed governed Fabric generation. No workload rollback is required because this feature performs no infrastructure writes.

## Security boundary

Never expose tenant, subscription, ARM resource, ingestion-run, raw payload, lineage, or action-result fields through Operations Agent responses. Incident IDs are operational case references, not Azure resource identifiers.
