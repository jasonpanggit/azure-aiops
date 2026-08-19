# Predictive Operations Intelligence

## Purpose and boundary

This layer produces evidence-backed forecasts for operational failure, application instability, business-service risk, incident likelihood, and operational-debt growth. It is prediction only: no remediation, infrastructure modification, deployment, or automated action exists.

## Architecture and workflow

```text
Patch + Lifecycle + Incident + Change/Drift posture
  -> governed canonical resource feature snapshot
  -> public Semantic application/service/ownership context
  -> 30/60/90-day historical growth features
  -> explainable weighted risk contributions
  -> bounded resource forecasts
  -> application and business-service aggregation
  -> operational debt and executive reports
  -> read-only Operations Agent
```

The engine consumes OneLake/Fabric projections and peer intelligence outputs. It never queries Azure directly.

## Prediction engine design

The requested framework is implemented as explicit, testable modules:

- `predictive_engine` — facade and predictive knowledge projection.
- `risk_forecasting` — transparent 30/60/90 scenario-risk scoring.
- `failure_prediction` — resource/VM/Arc failure estimates and consequences.
- `service_health_forecaster` — application and business-service horizon aggregation.
- `incident_probability_engine` — named evidence-weighted probability estimate.
- `trend_detector` — improving, stable, and degrading patterns.
- `operational_debt_engine` — patch, lifecycle, ownership, configuration, and security debt.
- `prediction_context_builder` — canonical governed context and privacy-safe portfolio aliases.
- `prediction_summary` — operational and executive forecast summaries.

The implementation also preserves the original module APIs for compatibility.

## Feature model

The deterministic feature contributions total 0–100:

- Incident recurrence: up to 20
- Patch risk and debt: up to 20
- Lifecycle exposure: up to 10
- Configuration drift: up to 15
- Change volatility: up to 10
- Security exposure: up to 10
- Advisor recommendation exposure: up to 5
- Ownership gap: up to 10
- Business criticality: up to 10

Forecast scores are current evidence plus bounded observed growth. Levels: Low 0–24, Moderate 25–49, High 50–74, Critical 75–100.

The sum is capped at 100. No learned or opaque model is used.

## Risk prediction models

Each resource exposes infrastructure risk and the applicable VM-failure or Arc-server-degradation model. It also includes patch-compliance degradation, service instability, ownership-failure risk, and business-service disruption risk. Portfolio aggregation produces privacy-safe subscription, resource-group, and environment risk views. Application rows identify critical application exposure and potential consequences.

## Horizons and explainability

Every workload receives 30, 60, and 90-day forecasts, predicted failure modes, feature contributions, growth trends, evidence, confidence, operational-debt score, and an advisory-only review action. Confidence is capped at 0.95 and depends on evidence coverage and historical observations. Forecasts are not guaranteed outcomes.

Each horizon separately projects incident-likelihood risk, an estimated incident band (`0`, `1`, `2-3`, or `4+`), patch-debt risk, lifecycle exposure, drift accumulation, compliance degradation, ownership risk, and overall operational risk. These are deterministic scenario-risk projections—not calibrated probabilities or promised incident counts.

Failure predictions also include an `estimated_probability_percent` capped at 95. It is explicitly labeled an evidence-weighted estimate rather than a calibrated probability. Contributors are recent incidents, patch exposure, lifecycle exposure, configuration drift, change volatility, Advisor exposure, and observed growth. If every contributor is unavailable, the estimate is `null` with `evidence_status=Unknown`, never zero.

Confidence means evidence sufficiency, not predictive probability. It uses source-field coverage, observation count, and elapsed historical span; same-resource observations at the same instant are rejected.

Zero or one observation produces Unknown optional trends rather than Stable zero. A metric delta is calculated only when that metric exists in both endpoint observations; sparse mixed-metric history cannot manufacture growth or improvement.

## Operational debt

Operational debt contains five independently visible categories:

- Patch debt: available debt count × 5, capped at 100.
- Lifecycle debt: governed lifecycle-risk score.
- Ownership debt: 100 only for an evidence-backed ownership gap; otherwise 0 or Unknown.
- Configuration debt: active drift count × 20, capped at 100.
- Security debt: governed security finding count × 20, capped at 100.

The total is the average of known categories. Trends include patch/lifecycle/configuration/security debt growth and ownership-coverage improvement or degradation. Reduction opportunities remain preventive and advisory-only.

## Questions and commands

- Analyze Predictive Risk
- What Is Likely To Fail Next
- Show Unstable Applications
- Show Services Accumulating Debt
- Forecast Incidents
- Show Workloads Requiring Intervention
- Generate Predictive Operations Report
- Generate Executive Predictive Brief

The requested command surface is also available:

- Predict Operational Risk
- Show High Risk Applications
- Service Stability Forecast
- Show Compliance Trends
- Show Operational Debt
- Show High Risk Resources
- Show Risk Drivers
- Predictive Risk Report
- Executive Forecast
- Is Application At Risk? (requires an `Application` subject)

Portfolio commands require `Enterprise` / `PredictivePortfolio`; `Is Application At Risk?` requires the named governed `Application` subject.

## Reports

- Predictive Operations Summary
- Failure Risk Forecast
- Application Stability Report
- Business Service Risk Forecast
- Operational Debt Forecast
- Executive Predictive Brief

## Telemetry

- `predictive.analysis.duration`
- `predictive.feature.duration`
- `predictive.forecast.duration`
- `predictive.trend.duration`
- `predictive.aggregation.duration`
- `predictive.report.duration`
- `predictive.intelligence.freshness`
- `predictive.prediction.latency`
- `predictive.risk.scoring.duration`
- `predictive.forecast.accuracy`
- `predictive.trend.generation.duration`
- `predictive.context.assembly.duration`
- `predictive.recommendation.generation.duration`

Accuracy is recorded only when a binary observed outcome is supplied to `record_forecast_accuracy`; the engine does not fabricate an accuracy value without outcome labels.

## Predictive knowledge model

The ontology projection adds `Prediction`, `Forecast`, `Trend`, `OperationalDebt`, and `RiskDriver`, connected through `hasForecast`, `hasTrend`, `accumulatesDebt`, and `drivenBy`. Projection identifiers are deterministic hashes of canonical identities and do not expose ARM or subscription identifiers. Rows conform to the existing ontology `resource_id`/`predicate` contracts, remain referentially valid, and disclose count/returned/truncated metadata.

## Executive report sample

```json
{
  "headline": "3 workloads forecast; 2 elevated in 30 days",
  "top_risk": "vm-payments",
  "application": "Payments",
  "business_service": "Retail Checkout",
  "estimated_probability_percent": 78,
  "confidence_kind": "Evidence sufficiency, not calibrated probability",
  "preventive_action": "Review the named evidence through approved operational processes",
  "read_only": true
}
```

## Safety and bounds

Canonical identities, ISO timestamps, duplicate history identities, future evidence, history limits, output counts, public identifiers, and 1 MB serialized response bounds fail closed. Public outputs do not include ARM, tenant, subscription, or ingestion-run identifiers.

Unknown ownership does not become a confirmed ownership gap. Peer posture keys pass through the same deep-decoding, case, and trailing-slash canonicalization as inventory keys. Truncated outputs preserve total, returned, and truncated metadata, and executive headlines use portfolio totals.

## Testing

Tests cover ranking, horizons, monotonic forecasts, degrading debt, duplicate history, application/service aggregation, ownership risk, queries, reports, telemetry, Semantic integration, Fabric snapshots, Operations Agent commands, identifier safety, and read-only behavior. Fixture: `tests/fixtures/sample_predictive_operations.json`.
