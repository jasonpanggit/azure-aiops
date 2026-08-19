# Operational risk scoring methodology

`RiskScorer` produces an explainable score from 0 through 100. It does not use an AI model. Every point is attributable to an operational fact in the Semantic Layer.

## Factors

| Factor | Condition | Points |
|---|---|---:|
| Missing owner | Resource has no active `owned_by` relationship | 25 |
| Patch noncompliance | Latest assessment is not compliant/succeeded/completed | 25 |
| Advisor recommendation | One or more active recommendations affect the resource | 15 maximum |
| Security finding | One or more current security findings affect the resource | 20 maximum |
| Resource criticality | `Critical` 10; `High` 8; `Medium` 5; `Low` 2 | 0–10 |
| Environment classification | `Production`, `Prod`, or `Live` | 5 |

The score is the bounded sum of factor points. Application and service risk use the maximum risk of their supporting resources so a critical dependency cannot be hidden by averaging.

## Levels

| Score | Level |
|---:|---|
| 0–24 | Low |
| 25–49 | Moderate |
| 50–74 | High |
| 75–100 | Critical |

## Missing and unknown data

- Missing ownership is an explicit risk.
- Missing/unknown patch status is reported as `unknown` and adds no noncompliance points; only confirmed failed/noncompliant states add patch risk.
- Missing Advisor or security findings do not add points; absence is not represented as proof of safety.
- Environment and criticality values are discovered from current semantic/inventory facts. No environment names are hardcoded beyond the documented production aliases used for scoring/search.

## Example

A production critical VM with a failed assessment, one Advisor recommendation, and one security finding scores:

```text
patch noncompliance       25
advisor recommendation   15
security finding          20
criticality               10
production environment     5
                          --
total                     75 (Critical)
```

If ownership is also missing, the bounded result is 100.

Risk output includes the complete factor map so callers can explain the result without accessing raw resources.
