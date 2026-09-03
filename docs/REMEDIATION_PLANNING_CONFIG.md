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

## Governed catalog and seeding

The governed remediation catalog and approval policies live at
`tests/fixtures/governed_remediation_catalog.json` in this repository. That
file is the single source of truth for what actions the planner can propose;
`remediation_planning_snapshot()` in `src/fabric/sync_service.py` reads only
`silver/remediation_action_catalog` and `silver/remediation_approval_policies`
from the lakehouse, so nothing is proposed anywhere until this content is
seeded.

Seed it into a lakehouse with:

```bash
.venv/bin/python scripts/seed_remediation_catalog.py --target <lakehouse-root-or-table-uri>
```

`--target` is required; the seeder refuses to run without an explicit target
so it can never write to a default or production location by accident. Add
`--dry-run` to see a summary of what would be written without writing
anything, and `--catalog <path>` to seed from a different governed catalog
file. The seeder validates the catalog through the real
`RemediationOpportunityEngine` and `ApprovalEngine` before writing anything,
and exits non-zero without writing if the content is invalid. It writes both
tables in overwrite mode keyed on `action_id`/`policy_id`, so running it
repeatedly against the same target converges on the same rows rather than
accumulating duplicates.

**Seeding a catalog action grants it no execution authority.** The seeder
only writes declarative, human-reviewed description text into governed
configuration tables; it performs no cloud calls, spawns no process, and
nothing in this repository reads a seeded action as permission to run
anything. Execution remains gated behind the existing approval workflow.

### What evidence triggers each seeded action, and what approval it requires

| Action | Triggering evidence | Approval roles required |
| --- | --- | --- |
| `critical-alert-containment` | `defender_active_critical_alert_count` >= 1 | Security Response Owner, plus production/mission-critical/high-execution-risk roles when those conditions match |
| `attack-path-segmentation-review` | `defender_attack_path_membership_count` >= 1 | Security Response Owner, plus production/mission-critical/high-execution-risk roles when those conditions match |
| `secure-score-control-remediation` | `defender_unhealthy_control_count` >= 1 or `defender_secure_score_gap` >= 10 | Security Response Owner, plus production/mission-critical/high-execution-risk roles when those conditions match |
| `exploitable-finding-remediation` | `defender_exploitable_finding_count` >= 1 | Security Response Owner, plus production/mission-critical/high-execution-risk roles when those conditions match |
| `controlled-patch-recovery` | `failed_update`, `patch_risk_score` >= 75, or `critical_vulnerability_count` >= 1 | Production change and mission-critical/high-execution-risk roles when those conditions match |
| `configuration-baseline-recovery` | `configuration_drift_count` >= 1 or `policy_violation_count` >= 1 | Production change and mission-critical/high-execution-risk roles when those conditions match |

Every action additionally requires a Stage Gate Approver for each of its
declared `deployment_stages`. Each action's metadata marks whether it is a
candidate for the Phase 3 low-risk allowlist; that marker is documentation
only in this phase and enables no behavior.

### Direct Defender configuration boundary

Direct Defender configuration is limited to two code-authored action types:

- `defender-enable-servers-plan-p1` enables resource-level Defender for
  Servers Plan 1 for one Azure VM, VM scale set, or Arc-enabled server.
- `defender-enable-storage-plan-v2` enables Defender for Storage V2 only when
  the recommendation target is the subscription itself.

Both use the pinned Microsoft.Security pricing API, require an exact
server-generated preview hash and current approval, re-read the current
configuration immediately before submission, and persist the pre-action state
properties/hash/ETag. The caller cannot provide an ARM method, URL, body, plan name, or
target override. Other Defender configuration recommendation titles produce
`defender-manual-review` plans and cannot execute. Rollback remains manual
guidance; terminal success is reported only after a follow-up Defender read
matches the approved desired properties.

Terraform keeps this capability off by default. Set
`enable_defender_configuration_execution = true` only after reviewing the
generated subscription-scoped custom role assignment.

### Operator workflow

The remediation center uses one scoped workflow read model:

1. **Select fix** — choose a generated governed plan.
2. **Review impact** — inspect business impact, evidence, rollback guidance,
   and the exact server-owned provider operation.
3. **Approve** — bind a human decision to the current action version and
   preview hash.
4. **Run** — submit the immutable approved snapshot once.
5. **Verify** — poll the owning provider and retain decisions, attempts,
   transitions, failures, and rollback guidance in the audit record.

The governed family catalog recognizes patch, Defender, Azure Policy, and
configuration actions. Only action IDs with a bounded provider handler are
executable. Recognized families without a handler, and unknown action IDs,
remain manual-review items and never receive an arbitrary ARM request path or
body.

## Sources

Resource posture is assembled internally using canonical IDs from:

- Patch Intelligence
- Lifecycle Intelligence
- Incident Correlation
- Change and Configuration Intelligence
- Predictive Operations Intelligence

Business and dependency context comes from public Semantic projections over Fabric Ontology. Public plans remove canonical IDs.
