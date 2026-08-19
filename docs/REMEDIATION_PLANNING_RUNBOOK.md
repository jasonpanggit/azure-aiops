# Remediation Planning Operational Runbook

## Boundary

This runbook operates a planning feature only. Never interpret a generated plan, simulation, approval requirement, rollback action, or recommendation as permission to change a system.

## Preconditions

1. Fabric and Semantic snapshots are current.
2. Peer intelligence layers are healthy or explicitly unavailable.
3. Action catalog entries have approved owners, evidence provenance, rollback metadata, and integer effectiveness estimates.
4. Approval policies reflect current organizational governance.
5. Application, service, ownership, support, and dependency relationships are governed.

## Verification

```bash
uv run --extra test pytest tests/test_remediation_*.py -q
uv run --extra test ruff check src tests
uvx bandit -q -r src
hermes plugins doctor --ci .
```

Functional smoke checks:

1. Run `Generate Remediation Plan` for `Enterprise` / `RemediationPortfolio`.
2. Confirm every plan is `Draft - Approval Required`.
3. Confirm `execution_authorized=false`, `execution_performed=false`, and `read_only=true`.
4. Confirm every plan has evidence, dependencies, four risk dimensions, approvals, rollback, simulation, confidence, and priority.
5. Confirm a resource with unknown posture matches no action.
6. Confirm an empty action catalog generates zero plans.
7. Confirm the ontology projection has no dangling endpoints.
8. Confirm public output contains no ARM, tenant, subscription, or ingestion identifiers.

## Catalog promotion

Treat catalog and policy updates as governed data changes:

1. Validate JSON and unique IDs.
2. Review trigger semantics and required evidence.
3. Review each non-executable planning step.
4. Validate all rollback fields and stage gates.
5. Review effectiveness assumptions and provenance.
6. Test in a non-production Fabric generation.
7. Obtain catalog/policy governance approval.
8. Promote through the normal Fabric publication process.

The engine itself does not approve catalog changes.

## Monitoring

Monitor:

- catalog/policy ingestion failures;
- stale Semantic or intelligence freshness;
- unexpected plan-count changes;
- Priority 1 growth;
- plans without owners or service context;
- dependency-bound or serialized-output failures;
- telemetry latency regressions;
- zero-plan output after a previously nonempty catalog.

## Troubleshooting

### No plan generated

Confirm a governed action exists and at least one trigger has known matching evidence. Do not add fallback workflow logic.

### Approval list is incomplete

Inspect stage gates and approval policy conditions. Correct governed policy data rather than inserting roles in code.

### Risk reduction appears overstated

Review catalog effectiveness provenance. Simulation is declarative and must not infer unsupported outcomes.

### Dependency scope is incomplete

Repair Ontology/Semantic relationships. Do not query Azure directly from the planner.

### Plan is too large

Reduce configured output size or narrow catalog scope. Do not disable public output bounds.

## Rollback and recovery

Application rollback means restoring the previous package or Fabric generation. No workload rollback is necessary because the planning engine performs no infrastructure changes. Generated draft plans are deterministic projections and can be regenerated from the prior governed snapshot.

## Testing strategy

- Unit: opportunity matching, risk, dependencies, approvals, rollback, simulation, impact, priority, repository.
- Contract: ten agent commands, six reports, ontology entities/relationships, telemetry.
- Integration: Fabric schemas/snapshot, Semantic enrichment, peer-posture joining, runtime injection.
- Adversarial: nested identifier encoding, malformed catalogs/policies, duplicate identities, unknown evidence, invalid bounds/percentages, dependency amplification, response-size ceilings, and no-action checks.
- Release: full pytest, Ruff, Bandit, dependency audit, package build, Plugin Doctor, and independent fail-closed review.

Live Azure/Fabric validation must be reported separately from deterministic fixture and mock verification.
