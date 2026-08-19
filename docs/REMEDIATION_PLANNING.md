# Autonomous Remediation Planning Engine

## Purpose and phase boundary

The engine turns governed operational evidence into approval-ready remediation plans. It never executes a change, modifies infrastructure, submits an approval, deploys a package, performs rollback, or calls a resource control plane.

Every output is:

- evidence-backed and explainable;
- generated from the Operational Context Graph, Fabric Ontology, Semantic Layer, and existing intelligence outputs;
- approval-driven and explicitly unauthorized;
- reversible through a mandatory rollback contract;
- bounded, sanitized, auditable, and read-only.

## Architecture

```text
Patch · Lifecycle · Incident · Change · Predictive posture
                         +
       Fabric inventory · Semantic graph context
                         +
  governed action catalog · configurable approval policy
                         |
               Opportunity Engine
                         |
  Dependency -> Risk -> Rollback -> Simulation -> Approval
                         |
                 Plan Generator
                         |
              Priority 1–4 scoring
                         |
  Draft repository + remediation ontology projection
                         |
   bounded Operations Agent commands and reports
```

The action catalog is the workflow source. With an empty catalog, the engine generates no plan. There is no built-in action workflow and no direct Azure query path.

## Planning workflow

1. Read a governed Fabric resource snapshot and peer-intelligence posture.
2. Resolve application, service, owner, support, upstream, and downstream relationships through public Semantic context.
3. Match evidence to declarative catalog triggers.
4. Build bounded dependency context.
5. assess execution, operational, business, and service-impact risk.
6. Generate mandatory preconditions, rollback actions, validation, success criteria, and failure criteria.
7. Simulate bounded risk/debt reduction from governed action effectiveness metadata.
8. Evaluate configurable approval policies and action stage gates.
9. Score Priority 1–4.
10. Publish a draft plan projection and ontology entities; do not execute it.

## Opportunity model

Catalog triggers support declarative `equals` and nonnegative integer `gte` clauses. Catalogs can represent:

- failed update and patch debt;
- critical vulnerability exposure;
- EOL and modernization candidates;
- configuration drift and policy violations;
- predictive high-risk workloads;
- patch, lifecycle, configuration, ownership, and security debt.

Missing evidence does not match a trigger. Malformed triggers fail closed.

## Plan model

Every `RemediationPlan` contains:

- stable plan identity, title, objective, draft status, and Priority 1–4;
- resource alias, application, and business service—never raw ARM identifiers;
- evidence, risk drivers, confidence semantics, and business impact;
- ordered non-executed `ExecutionStep` records;
- `RiskAssessment`, `ApprovalRequirement`, `RollbackPlan`, and `SimulationResult`;
- explicit `execution_authorized=false`, `execution_performed=false`, and `read_only=true`.

Ontology entities:

- `RemediationPlan`
- `ApprovalRequirement`
- `RollbackPlan`
- `ExecutionStep`
- `RiskAssessment`
- `SimulationResult`

Relationships include:

- `Application requiresPlan RemediationPlan`
- `RemediationPlan mitigatesRisk RiskAssessment`
- `RemediationPlan protectsService BusinessService`
- `RemediationPlan requiresApproval ApprovalRequirement`
- `RemediationPlan hasStep ExecutionStep`
- `RemediationPlan hasRollbackPlan RollbackPlan`
- `RemediationPlan hasSimulation SimulationResult`

The draft repository projection is referentially complete and externally read-only.

## Approval model

Every deployment stage creates a Stage Gate Approver requirement. Additional roles are selected by governed policies:

```yaml
policy_id: production-change
conditions:
  environment_in: [Production]
roles: [Change Manager, Application Owner, Service Owner, Support Team]
```

Supported conditions:

- `environment_in`
- `criticality_in`
- `minimum_execution_risk`

Typical policy roles include application owners, service owners, change managers, support teams, business service owners, operations risk owners, and a change advisory board. Development, Test, UAT, and Production stage gates come from each governed action definition. All approvals begin `Required - Not Approved`; the engine cannot approve them.

## Risk assessment model

Four independently explainable dimensions use a 0–100 score and Low/Moderate/High/Critical level:

- Execution risk: stage count, dependency count, production scope, and criticality.
- Operational risk: patch, lifecycle, predictive, and configuration posture.
- Business risk: governed business criticality.
- Service-impact risk: environment and dependency blast radius.

Levels:

- Low: 0–24
- Moderate: 25–49
- High: 50–74
- Critical: 75–100

When a dimension has no governed evidence, it returns `score=null`, `level=Unknown`, and `evidence_status=Unknown`; it is not converted into a Low score. Partial operational or dependency evidence is labeled `Partial`.

Overall planning risk is the maximum dimension, preserving the strongest known concern rather than averaging it away.

## Rollback framework

No plan can be generated unless its catalog action provides:

- preconditions;
- rollback actions;
- success criteria;
- failure criteria.

The planner adds application-health, dependency-transaction, and governed-posture validation. Rollback remains manual and approval-controlled: `reversible=true`, `automatic_rollback=false`, `execution_status=Not Executed`.

## Simulation model

The engine reads integer 0–100 effectiveness estimates from the governed action catalog:

- risk reduction;
- compliance improvement;
- lifecycle-exposure reduction;
- operational-debt reduction.

It calculates residual debt and combines service-impact evidence into a business-impact level. Results are scenario estimates, not guaranteed outcomes.

Example:

```json
{
  "title": "Modernize to a supported platform release",
  "resource": {"name": "arc-payroll", "entity_type": "ArcServer"},
  "priority": "Priority 1",
  "simulation_result": {
    "risk_reduction_percent": 68,
    "lifecycle_exposure_reduction_percent": 100,
    "operational_debt_reduction_percent": 70,
    "simulation_only": true,
    "changes_executed": false
  },
  "status": "Draft - Approval Required",
  "execution_authorized": false
}
```

## Prioritization methodology

Priority score is bounded to 100:

- Expected risk reduction: up to 35 points.
- Service criticality: up to 20.
- Dependency count: up to 15.
- Lifecycle risk: up to 15.
- Patch risk: up to 15.
- Incident history: up to 10.

Bands:

- Priority 1: 75–100
- Priority 2: 50–74
- Priority 3: 25–49
- Priority 4: 0–24

A recommendation means the draft is suitable for human approval review; it never means authorization to execute.

## Operational debt planning

Catalog actions can separately target patch, lifecycle, ownership, configuration, and security debt. Portfolio reports sort plans by expected reduction, criticality, dependencies, and recurrence while retaining per-plan evidence and rollback readiness.

## Agent commands

All commands require `Enterprise` / `RemediationPortfolio`:

1. Generate Remediation Plan
2. Show High Priority Plans
3. Simulate Remediation
4. Show Risk Reduction
5. Show Required Approvals
6. Show Rollback Plan
7. Generate Modernization Roadmap
8. Generate Operational Debt Reduction Plan
9. Generate Executive Remediation Report
10. Should This Plan Be Recommended?

## Executive reports

- Modernization Roadmap
- Patch Remediation Plan
- Compliance Recovery Plan
- High-Risk Service Remediation Plan
- Technology Debt Reduction Plan
- Executive Risk Reduction Strategy

## Telemetry

- `remediation.plan.generation.latency`
- `remediation.simulation.duration`
- `remediation.dependency.traversal.latency`
- `remediation.risk.analysis.duration`
- `remediation.approval.generation.time`
- `remediation.rollback.generation.time`

## Safety controls

- No direct Azure/resource API queries or modifications.
- No execution client, command runner, deployment adapter, approval writer, or rollback executor.
- Fixed-point identifier decoding and recursive output sanitization.
- Canonical resource identity and duplicate rejection.
- Strict catalog, policy, percentage, and bound validation.
- Bounded resources, plans, dependencies, nested collections, strings, and serialized output.
- Missing evidence remains unknown and cannot match a trigger.
- Every action and approval comes from governed data, not hardcoded workflow logic.
