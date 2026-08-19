# Operational Context Graph runbook

## Schedule

Run the existing ARG and Fabric synchronization on the required cadence. `Sync operational ontology` performs inventory-to-OneLake synchronization and Ontology publication as one leased operation.

```bash
uv run hermes-arg fabric "Sync operational ontology" --config /secure/fabric.config.yaml
```

## Health checks

```bash
uv run hermes-arg fabric "Show ontology health" --config /secure/fabric.config.yaml
uv run hermes-arg fabric "Show ingestion status" --config /secure/fabric.config.yaml
uv run hermes-arg fabric "Validate inventory data" --config /secure/fabric.config.yaml
```

Monitor OpenTelemetry instruments:

- `fabric.ontology.entities`
- `fabric.ontology.relationships`
- `fabric.ontology.orphan_resources`
- `fabric.ontology.missing_ownership`
- `fabric.ontology.missing_tags`
- `fabric.ontology.sync.duration`
- `fabric.ontology.sync.errors`

Alert on synchronization errors, sustained orphan growth, missing-ownership growth, or unexpected entity-count collapse.

## Query examples

```bash
uv run hermes-arg ontology "What applications are affected by patch failures?" --config /secure/fabric.config.yaml
uv run hermes-arg ontology "Who owns this VM?" --entity vm-prod-01 --config /secure/fabric.config.yaml
uv run hermes-arg ontology "What resources belong to Service X?" --entity Payments --config /secure/fabric.config.yaml
uv run hermes-arg ontology "What is impacted if this server fails?" --entity arc-prod-01 --config /secure/fabric.config.yaml
uv run hermes-arg ontology "Show dependencies of Application X" --entity Checkout --config /secure/fabric.config.yaml
uv run hermes-arg ontology "Show compliance by application" --config /secure/fabric.config.yaml
```

Agents use `operations_analysis`, which consumes the Semantic Layer internally; `hermes-arg ontology` is retained only for operator diagnostics.

For broad ownership coverage, agents use `command="Find Resources With Missing Ownership"` with `subject="Enterprise"`; the response remains bounded, sanitized, and read-only.

## Failure handling

1. Inspect the latest failed record in `metadata_ingestion_state`.
2. If data quality failed, inspect `metadata_quality_reports` and `ontology_quality_report`.
3. Correct source tags or mappings; do not manually edit Ontology instances.
4. Rerun the same source generation with `--replay-source-run-id` if deterministic replay is needed.
5. If a pre-publication rollback is reported incomplete, stop scheduled writes and restore the listed Delta tables to their recorded pre-run versions before resuming.
6. If Ontology publication or shortcut creation fails after the publication boundary, graph tables remain committed by design. Verify Fabric permissions and retry; stable request IDs plus definition read-back reconcile ambiguous API outcomes, and unchanged definitions are skipped.

## Retirement recovery

A missing source entity becomes `retired`, not hard-deleted. To reactivate it, restore it in the authoritative ARG source and run synchronization. Its deterministic ID is reused and lifecycle state returns to active.

## Tag remediation

Do not invent default environments, owners, teams, applications, or services. Missing values stay missing and appear in ontology health/queries. Correct Azure resource tags at the source, then resynchronize.

## Security

- Prefer managed identity.
- Keep service-principal secrets in the configured environment variable or managed secret provider.
- Use read-only query tools.
- Restrict Fabric item and OneLake permissions to the target workspace/Lakehouse.
- Do not expose `payload_json` or lineage records to users without operational inventory authorization. The bundled `operations_analysis` tool reasons over validated semantic projections and never returns resource/tenant/subscription IDs, raw payloads, lineage, or semantic metadata; direct Lakehouse access remains separately governed.
