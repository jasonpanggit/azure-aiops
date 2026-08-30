# Predictive Operations Runbook

## Preconditions

- Fabric and Semantic snapshots are healthy.
- Patch, Lifecycle, Incident, and Change intelligence are enabled or explicitly unavailable.
- Predictive history uses canonical resource IDs and ISO timestamps.
- Application, business-service, ownership, environment, and criticality relationships are governed.

## Verify

```bash
uv run --extra test pytest tests/test_predictive_*.py -q
uv run --extra test ruff check src tests
aiops plugins doctor --ci .
```

Smoke checks:

1. Compare predictive inventory count to governed Bronze resources.
2. Confirm duplicate/future history fails closed.
3. Run `What Is Likely To Fail Next` for `Enterprise` / `PredictivePortfolio`.
4. Run `Predict Operational Risk`, `Service Stability Forecast`, `Show Operational Debt`, and `Show Risk Drivers` for the same portfolio.
5. Run `Is Application At Risk?` with a governed `Application` subject.
6. Inspect feature contributions, estimated probability kind, observed patterns, debt categories, and trend evidence.
7. Confirm confidence is below 1 and probability language is explicitly uncalibrated.
8. Confirm no action result, remediation, or infrastructure command exists.

## Interpretation

Critical does not mean a failure will occur. It means the combined governed evidence and observed trend place the workload in the highest configured predictive-risk band. Validate source telemetry and operational context before intervention.

## Monitoring

Alert on stale freshness, history bounds, loss of peer-intelligence inputs, sudden confidence collapse, rapid growth in critical 90-day forecasts, latency regressions, and a previously nonempty history feed becoming empty.

## Troubleshooting

### Confidence is low

Increase governed observation history and repair missing ownership, application, service, patch, lifecycle, incident, or drift evidence. Do not inflate confidence manually.

### Forecast is unexpectedly high

Inspect feature contributions and debt growth. Correct source evidence or relationships rather than overriding the forecast.

### No forecast appears

Confirm the resource exists in the governed inventory and can resolve through public Semantic APIs.

## Rollback

Restore the prior application package or last completed Fabric generation. No workload rollback is required because the feature is read-only.
