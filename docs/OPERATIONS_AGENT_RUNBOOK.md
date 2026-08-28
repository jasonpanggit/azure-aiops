# Operations Agent Runbook

## Purpose

Operate and validate the read-only Operations Agent over synchronized Microsoft Fabric operational knowledge. This runbook does not authorize remediation or autonomous execution.

## Prerequisites

1. A successfully completed Fabric/Ontology synchronization.
2. A trusted Fabric runtime configuration readable by the AIOps process.
3. `AIOPS_FABRIC_CONFIG` set to that configuration path for plugin use.
4. Project dependencies installed in the same Python environment as AIOps.
5. Fabric/OneLake permissions configured through managed identity in production where possible.

The Operations Agent can continue reading the latest synchronized knowledge while Azure is disconnected. Freshness fields must be checked before relying on the result.

## Agent tool

AIOps registers exactly one operational agent tool:

- `operations_analysis`

Required fields are `command` and `subject`; `subject_type` is required for generic health/executive requests and recommended for impact/incident requests.

Example input:

```json
{
  "command": "Analyze VM",
  "subject": "vm-payments",
  "subject_type": "VirtualMachine"
}
```

The tool intentionally does not expose `semantic_knowledge_query`, raw Azure queries, Delta tables, Ontology traversal, Fabric synchronization, or mutation commands to agents.

## Operator CLI smoke tests

```bash
uv run aiops-inventory operations \
  "Analyze VM" vm-payments \
  --subject-type VirtualMachine \
  --config fabric.config.yaml

uv run aiops-inventory operations \
  "Executive Summary" Payments \
  --subject-type Application \
  --config fabric.config.yaml

uv run aiops-inventory operations \
  "Generate Incident Context" vm-payments \
  --subject-type VirtualMachine \
  --config fabric.config.yaml
```

## Operational checks

1. Confirm `knowledge_version` is an opaque `semantic-*` fingerprint.
2. Confirm `freshness` is inside the organization’s operational tolerance.
3. Confirm conclusions include evidence, data sources, reasoning, and risk factors.
4. Confirm recommendations include priority, impact, confidence, rationale, suggested action, and `advisory_only=true`.
5. Confirm unknown data is reported as unknown and does not become a negative conclusion.
6. Confirm no response contains Azure resource IDs, tenant/subscription IDs, raw payloads, lineage, or ingestion metadata.
7. Confirm no action result, mutation status, remediation execution, or Azure command is present.
8. Confirm encoded ARM/GUID values are redacted and truncated collections retain count/returned/truncated metadata.

## Telemetry

The agent records OpenTelemetry histograms:

- `operations.analysis.duration`
- `operations.recommendation.latency`
- `operations.knowledge.retrieval.latency`
- `operations.summary.generation.latency`
- `operations.impact.analysis.duration`
- `operations.context.generation.latency`

Alert on sustained latency regressions, failed plugin health checks, stale knowledge, or repeated invalid/ambiguous requests. Telemetry contains command/context categories only, never caller subjects or resource IDs.

## Runtime bounds

```yaml
fabric:
  operations_agent:
    max_output_items: 100
    max_serialized_bytes: 1000000
```

Bounds must be exact positive integers; the serialized ceiling must be at least 1024 bytes. Invalid values fail closed. Increase bounds only after representative Fabric-volume latency and memory testing.

## Troubleshooting

### Operational subject was not found

- Verify the exact semantic name and expected domain.
- Confirm the latest Fabric synchronization completed.
- Use operator-only semantic/Ontology diagnostics if authorized.
- Do not bypass the Operations Agent with a direct Azure query from an agent.

### Request is invalid or ambiguous

- Supply one of the documented commands exactly.
- Add `subject_type` when names collide or when using generic health/executive commands.
- Correct source tags or Ontology relationships through the governed ingestion process.

### Stale analysis

- Compare `freshness` and Ontology synchronization telemetry.
- Have an operator run the approved Fabric synchronization CLI/API workflow.
- Treat recommendations as stale until synchronization succeeds.

### Missing evidence

- The correct response is `unknown` or an empty evidence-backed collection.
- Correct the authoritative source or discovered Ontology relationship.
- Never invent ownership, impact, health, cost savings, affected users, or remediation success.

## Verification

```bash
uv run --extra test pytest \
  tests/test_operations_agent.py \
  tests/test_recommendations.py \
  tests/test_incident_analysis.py \
  tests/test_health_scoring.py \
  tests/test_context_generation.py \
  tests/test_explainability.py \
  tests/test_operational_summaries.py

uvx ruff check . --exclude .venv --exclude live-data --exclude mock-fabric-lakehouse
uvx bandit -r src -q
uv run python -m compileall -q src aiops_plugin.py __init__.py
aiops plugins doctor --ci .
uv build
```

Live Fabric publication, authorization, and production telemetry-export behavior require credentialed tenant validation and must remain separate from local/mock verification.
