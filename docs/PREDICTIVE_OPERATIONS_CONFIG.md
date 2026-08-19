# Predictive Operations Configuration

```yaml
fabric:
  predictive:
    enabled: true
    max_history_rows: 50000
    max_output_items: 100
```

`max_history_rows` bounds governed feature observations. `max_output_items` bounds public workload, application, and business-service results. Values must be positive.

## Inputs

Current features are assembled from:

- Patch Intelligence resource posture and patch debt
- Lifecycle Intelligence risk posture
- Incident Correlation recurrence counts
- Change Intelligence risk and drift posture
- Semantic security findings
- Semantic ownership, environment, criticality, application, and business service
- `silver_predictive_history` for observed debt and risk growth

No synthetic metrics are substituted when a peer intelligence layer has no evidence. Missing evidence lowers forecast confidence.

`predictive: false` explicitly disables runtime construction. The mapping and `enabled` value are type-checked, and explicit zero bounds fail validation.

## History schema

Each observation requires canonical `target_resource_id`, `observed_at`, patch debt, lifecycle risk, 30-day incident count, drift count, and risk score. Optional `resource_id` supplies a deterministic observation identity.

Optional `ownership_coverage_score` and `security_debt_score` fields enable ownership-improvement and security-debt trend detection. Missing optional fields remain unknown and do not create a trend.

Advisor recommendations are consumed through governed Semantic sections and contribute a bounded, named risk driver; the predictor does not query Advisor or Azure directly.
