# Lifecycle Intelligence Operational Runbook

## Deployment prerequisites

- Read-only ARG/Arc inventory synchronization is healthy.
- Fabric sync and Ontology publication are operational.
- Semantic resource context returns application, business service, ownership, environment, and criticality.
- Patch Intelligence is available or semantic patch posture can provide a conservative fallback.
- The lifecycle catalog has approved vendor sources and a reviewed update date.

## Deploy and verify

```bash
uv sync --extra test
uv run --extra test pytest tests/test_lifecycle_*.py tests/test_risk_engine.py \
  tests/test_modernization_engine.py tests/test_business_impact.py \
  tests/test_executive_reporting.py -q
uv run aiops-inventory fabric "Sync Azure inventory to OneLake" --config fabric.config.yaml
aiops plugins doctor --ci .
```

## Smoke checks

1. Confirm `metadata_lifecycle_catalog` has the expected catalog row count.
2. Confirm active `LifecycleProduct` rows exist in `ontology_entities` and the typed Ontology table.
3. Confirm `silver_lifecycle_history` receives one bounded observation per analyzed resource per sync. Correlation uses canonical resource ID, never display name. `resource_key` and `ingestion_run_id` are mandatory. Observation identity includes the ingestion run so two valid syncs started in the same second remain distinct; exact duplicate or identity-less observations fail closed when loaded for analysis.
4. Run `Show EOL Systems` for `Enterprise` / `LifecyclePortfolio`.
5. Verify all recommendations contain evidence, confidence, risk drivers, business impact, and `advisory_only=true`.
6. Compare catalog freshness and semantic freshness against their SLAs.
7. Confirm `lifecycle_classification=Expired` corresponds to the compatibility value `lifecycle_status=EOL` for assets past support.
8. Confirm malformed Boolean, score, catalog-row, and snapshot-bound inputs fail before Semantic enrichment.

For UUID subscriptions, verify history retains the governed internal subscription identifier while Operations Agent reports use a deterministic public alias. A successful sync with zero lifecycle-history rows is an alert condition, not a healthy empty result.

## Catalog update procedure

1. Obtain dates from the product vendor's official lifecycle source.
2. Update a staged JSON catalog; retain the source URL and update date.
3. Run catalog and full tests.
4. Review changed classifications and priority movements in a non-production Lakehouse.
5. Deploy the catalog through `fabric.lifecycle.catalog_path` and run Fabric sync.
6. Verify Metadata Lakehouse and Ontology row parity.

Catalog updates change analysis only. They do not execute upgrades.

## Monitoring

Alert on:

- catalog freshness over the approved SLA;
- malformed or future semantic/history timestamps;
- sudden growth in Unknown classifications;
- missing lifecycle metadata or typed Ontology tables;
- analysis/risk/business-correlation/report latency increases;
- unexpected drops to zero EOL observations after a nonzero generation;
- dangling inventory-to-operational-context relationships.

## Troubleshooting

### High Unknown count

Validate canonical OS/product/version fields and exact catalog aliases. Add a governed catalog entry or explicit inventory stewardship field; do not introduce fuzzy title matching.

### Unexpected EOL classification

Check support channel. Each catalog entry declares its governed default. A resource-level `support_channel` overrides it; paid Ubuntu ESM and RHEL ELS dates must not be selected without authoritative entitlement evidence.

### Missing business impact

Repair resource-to-application and application-to-business-service relationships or ownership/support tags in authoritative sources. The engine reports Unknown instead of inventing context.

### Stale reports

Check source sync, Lakehouse state, catalog update date, Ontology synchronization, and Semantic cache version. Continue serving only the last completed immutable generation with its original freshness.

## Rollback

Use the existing immutable OneLake generation and Ontology publication rollback procedures. Restore the last approved catalog file, rerun Fabric sync, and verify catalog/typed-table parity. No workload rollback or operating-system change is performed by this platform.

## Testing strategy

- Catalog validation and threshold boundaries
- Unknown and exact-match behavior
- Deterministic risk factors and bounds
- Modernization recommendation evidence and no-invention checks
- Semantic/graph business-impact integration
- 30/90/180-day event trends
- Executive report and telemetry contracts
- Agent scope/read-only validation
- Metadata Lakehouse and Ontology catalog persistence
- Full regression, pinned Ruff, build, security scan, Plugin Doctor, and independent review

Live Azure/Fabric verification must be reported separately from deterministic mock tests.
