# Change Intelligence Runbook

## Preconditions

- ARG/Fabric synchronization is healthy.
- Canonical resource IDs are present.
- Optional policy, security, identity, network, and IaC feeds are governed.
- Expected configuration baselines have an authoritative owner.
- Semantic application, business-service, owner, team, environment, and criticality relationships are available.

## Verify

```bash
uv run --extra test pytest tests/test_change_*.py tests/test_configuration_drift.py -q
uv run --extra test ruff check src tests
hermes plugins doctor --ci .
```

Smoke checks:

1. Compare ResourceChanges counts and watermark to ARG ingestion state.
2. Confirm timestamps and canonical resource identities.
3. Confirm actor is evidence-backed or Unknown.
4. Run `Analyze Change Risk` for `Enterprise` / `ChangePortfolio`.
5. Validate drift fields against the governed baseline.
6. Confirm incident correlation is temporal, probabilistic, and never confirmed.
7. Confirm recommendations are advisory-only.
8. Run `Show Change Timeline` and confirm 24-hour, 7-day, 30-day, and 90-day counts.
9. Run `Show Unapproved Changes`; verify missing authorization remains Unknown rather than Unapproved.
10. Run `Explain Incident Changes`; verify `confirmed_cause=false`.

## Change intelligence workflow

1. Consume immutable Fabric projections for ResourceChanges, Policy, Advisor, network, identity, IaC, inventory, and incidents.
2. Canonicalize resource identity and validate event identity and time.
3. Classify the event and retain authorization, actor, source, prior state, and current state.
4. Resolve Operational Context Graph business and dependency context.
5. Compare expected and observed state and name the drift type.
6. Correlate active policy/security deviations and subsequent incidents.
7. Calculate factor-attributed risk and compliance.
8. Aggregate application, service, subscription, team, and timeline views.
9. Publish bounded ontology, command, and report projections without execution.

## Monitoring

Alert on stale freshness, evidence bounds, missing expected baselines, unexplained growth in Unknown actors, sudden compliance-score changes, correlation latency, and a previously nonempty feed becoming empty.

## Troubleshooting

### Actor is Unknown

Validate that the source ResourceChanges, deployment, network, or identity feed includes an authorized actor field. Do not infer an actor from ownership.

### Configuration status is Unknown

Publish an approved expected configuration. Absence of a baseline is not compliance.

### Incident contribution missing

Check canonical identity and timestamps. The change must precede the incident and fall within 24 hours.

## Rollback

Restore the prior application package or last completed Fabric generation. No workload rollback is needed because this feature performs no infrastructure writes.

## Safety

No remediation, policy assignment, deployment, infrastructure modification, or automated rollback capability is registered with the Operations Agent.

## Testing strategy

- Unit: collection, classification, baseline validation, named drift, risk factors, incident correlation, timeline windows, and compliance aggregation.
- Integration: Fabric source projection, Semantic context, ontology entities/relationships, agent commands, and plugin schema.
- IaC: Terraform/Bicep/ARM/pipeline metadata and declared-vs-observed drift.
- Adversarial: duplicate IDs, malformed timestamps/types, sparse evidence, inactive deviations, encoded identifiers, collection amplification, unknown authorization, and post-incident changes.
- Release: full pytest, Ruff, Bandit, dependency audit, package build, Plugin Doctor, and independent fail-closed review.
