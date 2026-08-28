# Patch Intelligence Configuration Guide

Patch intelligence consumes governed semantic snapshots; it does not accept Azure connection configuration and never queries resources directly.

## ARG ingestion

`config.example.yaml` controls the existing read-only ingestion process. Six independent queries are now issued, so production worker capacity should be sized to the source/API limits. A value of 6 allows one worker per current query; a lower value is safe and queues work.

```yaml
azure:
  max_query_workers: 6
  page_size: 1000
  max_pages: 1000
  command_timeout_seconds: 60
```

## Runtime construction

```python
PatchIntelligence.from_semantic_engine(
    semantic_engine,
    inventory=governed_inventory_projection,
    assessments=patch_assessment_projection,
    installations=patch_installation_projection,
    history=patch_history_projection,
    policies=policy_projection,
    max_resources=5000,
    max_evidence_rows=50000,
    max_output_items=100,
    max_serialized_bytes=1000000,
)
```

`from_semantic_engine` resolves resource-to-application, business-service, owner, support-team, Advisor, and security context through public Semantic Engine APIs. IDs are used internally to join governed OneLake rows but are not emitted to agents.

## Governed policy projection

```yaml
policies:
  - name: Production baseline
    environment: Production
    max_patch_age_days: 30
    minimum_compliance_score: 90
  - name: Development baseline
    environment: Development
    max_patch_age_days: 60
    minimum_compliance_score: 80
```

Policy rows are evidence/configuration, not an execution instruction. `PatchWindow` and `PatchBaseline` models are descriptive in this read-only phase.

## Resource bound

`max_resources` defaults to 5000. Exceeding the bound fails closed so an agent request cannot trigger an unbounded analysis. Increase only after latency and memory validation with representative Fabric data.

`max_evidence_rows` defaults to 50000 and is enforced independently for assessments, installations, history, security findings, and Advisor recommendations. Evidence is indexed once by canonical resource identity. Duplicate display names require canonical identity and never fall back to an ambiguous name join.

## Fabric runtime controls

```yaml
fabric:
  patch_intelligence:
    enabled: true
    max_resources: 5000
    max_evidence_rows: 50000
    max_output_items: 100
    max_serialized_bytes: 1000000
```

All values are exact positive integers; Booleans, fractional values, zero, and negative values fail closed. `max_serialized_bytes` must be at least 1024. Resource and evidence bounds are enforced before Semantic enrichment. `max_output_items` applies recursively to public collections, and `max_serialized_bytes` enforces the final response ceiling.

## Freshness

Supply the timestamp of the last completed Fabric generation. Do not use request time or agent execution time. Monitor `patch.intelligence.freshness` against the enterprise SLA.

## Scoring governance

The implemented weights and thresholds are documented in `docs/PATCH_INTELLIGENCE.md`. Changing them is a model-governance change: update tests, methodology documentation, sample reports, and approval records together.

## AIOps tool exposure

Expose only `operations_analysis` from toolset `azure_operational_context`. Patch commands are enum-bounded in the same tool schema; `Show Security Exposure` and `Executive Brief` are canonical user-facing forms, while the earlier `Analyze Security Exposure` and `Generate Executive Brief` aliases remain compatible. Do not register raw Delta, ARG, or Ontology traversal tools for agents.

Caller authentication and authorization remain the AIOps gateway/toolset boundary. Grant `azure_operational_context` only to principals permitted to view the configured enterprise portfolio. The plugin then enforces the fixed `Enterprise` / `PatchPortfolio` contract and will not interpret caller-supplied subscription or application labels as authorization scopes.
