# Change and Configuration Intelligence

## Purpose and boundary

This read-only layer explains what changed, who changed it, when it changed, its operational risk, configuration compliance, and whether it probably contributed to an incident. It performs no remediation, infrastructure modification, rollback, deployment, or policy mutation.

## Architecture and workflow

```text
ARG ResourceChanges + governed policy/security/network/identity/IaC evidence
  -> canonical resource identity and timestamp validation
  -> public Semantic resource context
  -> expected vs observed configuration comparison
  -> policy/security deviation correlation
  -> deterministic 0–100 change risk
  -> temporal incident contribution analysis
  -> compliance, trends, operational and executive reports
  -> bounded read-only Operations Agent commands
```

The intelligence package never queries Azure directly. OneLake and Fabric remain the governed evidence boundary; Fabric Ontology and public Semantic APIs supply application, service, ownership, team, environment, and criticality context.

## Framework modules

- `change_intelligence` — orchestration, timelines, compliance scopes, queries, reports, and ontology projection.
- `change_collector` — governed-source collection without direct Azure access.
- `change_classifier` — Security, Network, Identity, Compute, Storage, Governance, Platform, or Application classification.
- `change_risk_engine` — deterministic factor-attributed risk.
- `configuration_drift` — named configuration, ownership, tag, network, identity, and policy drift.
- `baseline_engine` — auditable required-state and compliance-rule baselines.
- `change_correlator` — incident timing, resource alignment, and recurring patterns.
- `change_summary` — operational, governance, risk, and executive reports.

Original module names remain available for compatibility.

## Risk model

| Factor | Points |
|---|---:|
| Change severity | 0–20 |
| Sensitive network/identity/security scope | 0–15 |
| Production environment | 0–10 |
| Business criticality | 0–15 |
| Configuration drift | 0–15 |
| Policy deviation | 0–10 |
| Security baseline deviation | 0–10 |
| Incident proximity | 0–15 |
| Workload scope | 0–5 |
| Dependency count | 0–15 |
| Historical incident correlation | 0–10 |

Scores are clamped to 0–100: Low 0–24, Moderate 25–49, High 50–74, Critical 75–100.

## Configuration compliance

Expected configuration is compared exactly against governed observed configuration. Missing expected configuration is Unknown, never Compliant. A known drift deducts 30 points; policy and security deviations each deduct 15 per finding up to 30 per category.

Compliance is aggregated by application, business service, and privacy-safe subscription alias. Each aggregate includes resource count, compliance score or Unknown, drift count, violations, and critical deviations.

## Baseline framework

Baselines contain identity, resource type, required state, expected configuration, compliance rules, and ownership metadata. Supported resource types include VMs, Arc Servers, NSGs, VNets, subnets, Azure Firewall, route tables, Application Gateway, Key Vault, Storage Accounts, SQL Databases, AKS, and Azure Local.

## Drift detection model

Named drift includes configuration, policy, security, ownership, tag, network, and identity drift, including required-tag removal, NSG rule addition, firewall opening, owner removal, managed-identity removal, Private Endpoint removal, and policy exemption. Every result retains previous state, current state, changed fields, evidence, and evidence status.

## Incident contribution

A change can be a Probable contributor only when it targets the same canonical resource and precedes an incident by no more than 24 hours. Confidence is capped at 0.95 and `confirmed_cause=false` is always returned. Changes after incident start are not contributors.

Temporal proximity alone is insufficient: the change must affect a configured sensitive network, identity, security, IaC, SKU, or access-control scope. Incident identity is mandatory.

## Evidence domains

- ARG resource changes
- Configuration drift
- Azure Policy or equivalent governed deviations
- Security baseline deviations
- Network changes
- Identity and role-assignment changes
- Terraform/Bicep/ARM or other governed IaC changes
- Incident correlations
- Operational Context Graph relationships
- Azure Advisor evidence through governed Semantic projections

Network intelligence covers routes, Azure Firewall, NSGs, UDRs, DNS, Private Endpoints, load balancers, and Application Gateway. Identity intelligence covers role assignments, privileged access, managed identities, and service principals. IaC evidence supports Terraform, Bicep, ARM templates, GitHub Actions, and Azure DevOps metadata when available.

## Change event and ontology model

First-class ontology entities include `ChangeEvent`, `ConfigurationBaseline`, `ConfigurationDrift`, `PolicyDeviation`, `SecurityDeviation`, `AuthorizedChange`, and `UnapprovedChange`. Relationships classify authorization, link events to baselines, and link events to resulting drift. Unknown authorization remains unknown and is not converted to Unapproved.

## Reports

- Change Intelligence Summary
- Configuration Compliance Report
- Change Risk Report
- Incident Contribution Report
- Executive Change Brief
- Executive Governance Report

## Commands

- Analyze Change Risk
- Show Recent Changes
- Show Configuration Drift
- Show Policy Deviations
- Show Security Baseline Deviations
- Show Incident Contributing Changes
- Generate Change Intelligence Report
- Generate Executive Change Brief

Requested enterprise commands:

- Analyze Changes
- Show Resource Changes
- Show Configuration Drift
- Show Policy Violations
- Show High Risk Changes
- Show Unapproved Changes
- Generate Change Report
- Show Change Timeline
- Explain Incident Changes
- Generate Risk Report

All commands require `Enterprise` / `ChangePortfolio`.

Public outputs canonicalize percent-encoded resource aliases, redact literal/percent/base64/hex-encoded ARM identifiers and standalone GUIDs, bound nested deviation collections, cap strings and output items, and enforce a 1 MB serialized response limit. Duplicate changes, incidents, and deviations fail closed; resolved deviations do not affect posture.

Filtering and recency sorting occur before public truncation. Drift fields and nested deviations share the configured output bound. Equivalent evidence permutations produce deterministic trends and deviation results. Whitespace-only actors remain Unknown and do not create actor evidence.

## Telemetry

- `change.analysis.duration`
- `change.drift.duration`
- `change.risk.duration`
- `change.incident.correlation.duration`
- `change.report.duration`
- `change.intelligence.freshness`
- `change.processing.duration`
- `change.drift.detection.duration`
- `change.risk.calculation.duration`
- `change.baseline.comparison.duration`
- `change.timeline.generation.duration`

## Timelines and executive sample

The platform produces 24-hour, 7-day, 30-day, and 90-day timelines. Counts are calculated before truncation.

```json
{
  "change_id": "CHG-100",
  "category": "Network",
  "authorized": true,
  "approval_reference": "CAB-2026-100",
  "risk_level": "Critical",
  "business_service": "Retail Checkout",
  "related_incidents": ["INC-100"],
  "confirmed_cause": false,
  "read_only": true
}
```

## Testing

Tests cover analysis, attribution, risk, drift, unknown baselines, compliance, incident contribution, post-incident exclusion, trends, reports, Semantic integration, Fabric snapshots, agent bounds, and read-only behavior. Sample evidence: `tests/fixtures/sample_change_intelligence.json`.
