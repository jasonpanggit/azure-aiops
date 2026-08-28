# Patch Intelligence Operational Runbook

## Preconditions

- ARG ingestion identity has read-only access to the configured scopes.
- `PatchAssessmentResources`, `PatchInstallationResources`, and Advisor rows are present in the normalized generation.
- Fabric synchronization completed and Ontology relationship quality checks passed.
- The Operations Agent receives only governed semantic projections; it receives no Azure client or mutation tool.

## Deploy

```bash
uv sync --extra test
uv run pytest tests/test_patch_*.py -q
uv run aiops-inventory sample --fixture tests/fixtures/mock_arg_responses.json --output-dir sample-data
uv run aiops-inventory fabric "Sync Azure inventory to OneLake" --config fabric.config.yaml
```

Set `AIOPS_FABRIC_CONFIG` to the operator-managed Fabric configuration before starting AIOps. Do not expose configuration paths or credentials in the tool schema.

## Smoke tests

1. Verify the latest ARG manifest contains `patch_assessments` and `patch_installations`.
2. Verify OneLake tables `bronze_patchassessment`, `bronze_patchinstallation`, `silver_compliance`, `silver_patch_installations`, merge-retained `silver_patch_history`, and governed `silver_patch_policies` have expected row counts.
3. Verify every active patch assessment/installation target exists in the same graph generation.
4. Invoke `Analyze Patch Compliance` and confirm `read_only=true`.
5. Invoke `Show Priority Remediation Candidates` and confirm every recommendation has evidence, rationale, confidence, affected resources, and `advisory_only=true`.
6. Compare the response freshness with the completed Fabric watermark.
7. Verify collection metadata reports full qualifying counts before truncation and the serialized response remains within the configured ceiling.
8. Probe literal, percent-encoded, Base64, hex, and Unicode-escaped identifiers and confirm the public response redacts them.

## Monitoring

Alert on:

- increasing `patch.intelligence.freshness` beyond the approved data SLA;
- sustained increases in analysis, risk, trend, or business-correlation latency;
- zero assessment/installation rows after a previously nonzero generation;
- dangling patch-to-resource relationships;
- unexpected growth beyond the configured resource bound;
- output truncation or serialized-size rejection rates above the approved baseline;
- failed OneLake/Fabric publication or Ontology synchronization.

## Failure handling

### Stale intelligence

Check ARG sync status, OneLake publication state, and Fabric synchronization. Continue serving the last completed immutable generation with its original freshness. Never label stale evidence as current.

### Missing patch installations

Confirm the `PatchInstallationResources` query is authorized and that software-patch child rows are returned. An empty collection means no governed installation rows are present; it is not proof of successful patching.

### Unknown business context

Repair resource-to-application, application-to-business-service, owner, or support-team relationships in the authoritative tagging/stewardship process. The engine reports `Unknown` and lowers confidence; it does not invent relationships.

### Score disagreement

Inspect the returned `risk_factors`, compliance deductions, policy evidence, patch age, and source freshness. Scores are deterministic. Correct source data or approved model configuration; do not manually overwrite a finding.

### Performance degradation

Check resource count, history volume, and report frequency. Keep snapshots bounded. Pre-aggregate long-term history in Fabric rather than adding direct Azure reads or unbounded in-process traversal.

## Recovery and rollback

Rollback uses the existing immutable OneLake generation/current-pointer mechanism. Repoint to the last valid completed generation, rebuild semantic indexes, and restart the Operations Agent cache. Do not partially roll back Ontology definitions while leaving incompatible Delta tables active.

## Security and read-only guarantee

- No engine API accepts credentials, subscription scopes, filesystem roots, shell commands, callbacks, or remediation payloads.
- Recommendations are data only.
- Patch deployment, reboot, update installation, change-ticket creation, and policy mutation remain out of scope.
- Agent command routing is closed; unsupported commands fail.
- Malformed Semantic sections, non-mapping rows, Boolean numeric fields, duplicate installation evidence, and non-canonical identity collisions fail closed.

## Verification commands

```bash
uv run pytest tests/test_patch_*.py -q
uv run pytest -q
uv run ruff check src tests
uv build
```

A live tenant verification must separately prove read-only ARG access and Fabric table/ontology publication. Automated mock tests do not establish live-cloud readiness.
