# Remediation Planning Configuration

## Runtime

```yaml
fabric:
  remediation:
    enabled: true
    max_resources: 5000
    max_plans: 1000
    max_output_items: 100
    max_dependencies: 100
```

The section may be explicitly `false`. `enabled` must be Boolean. Bounds must be positive, exact non-Boolean integers.

## Governed Fabric inputs

### `silver_remediation_action_catalog`

Required columns:

- `action_id`, `title`, `opportunity_type`
- `trigger_json`
- `execution_steps_json`
- `preconditions_json`
- `rollback_actions_json`
- `success_criteria_json`
- `failure_criteria_json`
- `deployment_stages_json`
- `effectiveness_json`

Example logical record:

```json
{
  "action_id": "supported-platform-modernization",
  "title": "Modernize to a supported platform release",
  "opportunity_type": "Lifecycle and modernization debt",
  "trigger": {
    "any": [
      {"field": "eol", "equals": true},
      {"field": "lifecycle_risk_score", "gte": 75}
    ]
  },
  "execution_steps": [
    "Confirm the supported target from the governed lifecycle catalog",
    "Assess application and dependency compatibility",
    "Validate Development, Test, and UAT evidence",
    "Present a phased production cutover for approval"
  ],
  "deployment_stages": ["Development", "Test", "UAT", "Production"],
  "effectiveness": {
    "risk_reduction_percent": 68,
    "compliance_improvement_percent": 35,
    "lifecycle_exposure_reduction_percent": 100,
    "operational_debt_reduction_percent": 70
  }
}
```

This catalog is the only remediation workflow source. Empty catalog means no generated plans.

### `silver_remediation_approval_policies`

Required columns:

- `policy_id`
- `conditions_json`
- `roles_json`

Example:

```json
{
  "policy_id": "mission-critical",
  "conditions": {"criticality_in": ["Mission Critical", "Critical"]},
  "roles": ["Business Service Owner", "Operations Risk Owner"]
}
```

Malformed JSON, unknown policy conditions, duplicate identities, invalid thresholds, incomplete rollback metadata, or invalid effectiveness percentages fail closed.

## Sources

Resource posture is assembled internally using canonical IDs from:

- Patch Intelligence
- Lifecycle Intelligence
- Incident Correlation
- Change and Configuration Intelligence
- Predictive Operations Intelligence

Business and dependency context comes from public Semantic projections over Fabric Ontology. Public plans remove canonical IDs.
