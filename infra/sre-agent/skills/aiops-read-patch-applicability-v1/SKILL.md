---
name: aiops-read-patch-applicability-v1
description: Read bounded applicability evidence for an exact approved Windows Azure VM or Arc-enabled server patch selection.
---

# Read exact patch applicability

Accept only the immutable approved payload supplied by
`aiops-selected-patch-execution-v1`. Never accept replacement subscription,
target, patch, KQL, or command values from a user or model.

## Tool and command boundary

- Use only `RunAzCliReadCommands`.
- Do not use `RunAzCliWriteCommands`, `GetAzCliHelp`, a shell, script,
  redirection, pipeline, command substitution, environment variable, fallback,
  retry, discovery command, or second command.
- Run exactly one fixed `az graph query`.
- On any invalid input or unavailable/invalid evidence, return
  `blocked_no_action` and do not call another tool.

## Immutable input checks

Require schema version `1.1`, operation `install_patches`, and an unexpired
upstream `approval.decision=approved`. Require the top-level target and patch
fields to exactly equal the approved snapshot and the applicability inputs.
Require:

- one UUID `subscription_id`;
- `target_kind` equal to `Azure VM` or `Arc-enabled server`;
- one canonical top-level target ID in that subscription, with exactly
  `/providers/Microsoft.Compute/virtualMachines/<name>` for an Azure VM or
  `/providers/Microsoft.HybridCompute/machines/<name>` for an Arc-enabled
  server;
- no target child segment, query, fragment, whitespace, quote, empty segment,
  or shell metacharacter; and
- 1 through 256 unique patch IDs, each matching
  `^[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}$`.

An empty filter, classification filter, alternative target or patch, or
cross-kind target is forbidden. Serialize the exact patch list as a compact
JSON array for `approved_patch_ids_json`.

## Fixed bounded query

Use `RunAzCliReadCommands` once with exactly:

```text
az graph query --graph-query "<fixed-kql-below>" --subscriptions <subscription_id> --first 257 --output json --only-show-errors
```

`<fixed-kql-below>` is exactly:

```kusto
let expected_subscription_id = '{{subscription_id}}';
let expected_target_id = '{{target_id}}';
let expected_target_kind = '{{target_kind}}';
let approved_patch_ids = dynamic({{approved_patch_ids_json}});
let observed_at = now();
let target_summary = resources
    | where subscriptionId =~ expected_subscription_id
    | where id =~ expected_target_id
    | where type =~ iff(expected_target_kind == 'Azure VM', 'microsoft.compute/virtualmachines', 'microsoft.hybridcompute/machines')
    | extend vm_power_state = tostring(properties.extended.instanceView.powerState.code)
    | summarize target_row_count = count(), target_resource_id = take_any(id), target_resource_type = take_any(type), vm_power_state = take_any(vm_power_state)
    | extend join_key = 1;
let assessment_rows = materialize(
    patchassessmentresources
    | where subscriptionId =~ expected_subscription_id
    | where type endswith '/patchassessmentresults'
    | where name =~ 'latest'
    | extend assessment_parent_offset = indexof(tolower(id), '/patchassessmentresults/')
    | extend target_id = iff(assessment_parent_offset > 0, substring(id, 0, assessment_parent_offset), ''), assessment_activity_id = tostring(properties.assessmentActivityId), assessment_last_modified_at = todatetime(properties.lastModifiedDateTime), reboot_pending = tobool(properties.rebootPending)
    | where target_id =~ expected_target_id
    | project assessment_row_id = id, target_id, assessment_activity_id, assessment_last_modified_at, reboot_pending
);
let assessment_summary = assessment_rows
    | summarize assessment_row_count = count(), assessment_row_id = take_any(assessment_row_id), assessment_activity_id = take_any(assessment_activity_id), assessment_last_modified_at = take_any(assessment_last_modified_at), reboot_pending = take_any(reboot_pending)
    | extend join_key = 1;
let patch_summary = patchassessmentresources
    | where subscriptionId =~ expected_subscription_id
    | where type endswith '/patchassessmentresults/softwarepatches'
    | extend approved_patch_id = tostring(properties.kbId), child_activity_id = tostring(properties.assessmentActivityId), child_last_modified_at = todatetime(properties.lastModifiedDateTime)
    | where set_has_element(approved_patch_ids, approved_patch_id)
    | extend join_key = 1
    | join kind=inner (assessment_rows | extend join_key = 1) on join_key
    | where tolower(id) startswith strcat(tolower(assessment_row_id), '/')
    | where child_activity_id == assessment_activity_id
    | summarize child_row_count = count(), child_row_id = take_any(id), child_activity_id = take_any(child_activity_id), child_last_modified_at = take_any(child_last_modified_at) by approved_patch_id;
print approved_patch_ids
| mv-expand approved_patch_id = approved_patch_ids to typeof(string)
| extend join_key = 1
| join kind=inner target_summary on join_key
| join kind=inner assessment_summary on join_key
| join kind=leftouter patch_summary on approved_patch_id
| extend child_row_count = coalesce(child_row_count, 0), maximum_age_seconds = 86400, age_seconds = datetime_diff('second', observed_at, assessment_last_modified_at)
| extend outcome = case(target_row_count != 1, 'blocked_target_ambiguous', expected_target_kind == 'Azure VM' and vm_power_state !~ 'PowerState/running', 'blocked_target_not_running', assessment_row_count != 1, 'blocked_parent_ambiguous', isempty(assessment_activity_id), 'blocked_activity_missing', isnull(assessment_last_modified_at), 'blocked_assessment_timestamp', isnull(reboot_pending), 'blocked_reboot_pending_unknown', reboot_pending, 'blocked_reboot_pending', age_seconds < 0 or age_seconds > maximum_age_seconds, 'blocked_stale', child_row_count == 0, 'blocked_patch_not_applicable', child_row_count != 1, 'blocked_patch_ambiguous', child_activity_id != assessment_activity_id, 'blocked_patch_activity', isnull(child_last_modified_at) or child_last_modified_at != assessment_last_modified_at, 'blocked_patch_generation', 'applicable')
| project schema_version = '1.0', source = 'azure_resource_graph', table = 'PatchAssessmentResources', subscription_id = expected_subscription_id, target_kind = expected_target_kind, target_id = expected_target_id, target_row_count, target_resource_id, target_resource_type, vm_power_state, reboot_pending, approved_patch_id, assessment_row_count, assessment_row_id, assessment_activity_id, assessment_last_modified_at, child_row_count, child_row_id, child_activity_id, child_last_modified_at, observed_at, age_seconds, maximum_age_seconds, outcome
| order by approved_patch_id asc
```

Do not edit, extend, regenerate, or replace the query.

## Closed evidence

Accept only an Azure CLI JSON envelope containing exactly `count`, `data`, and
`total_records`. Require count and total records to equal the immutable patch
count and be at most 256. Require every and only selected patch exactly once.
Every row must preserve the exact subscription, target, parent ID, activity
ID, parent/child timestamp, and patch ID; have both row counts equal to one;
prove exactly one matching target resource; for an Azure VM have
`vm_power_state=PowerState/running`; have `reboot_pending=false`; have PT24H
freshness (`maximum_age_seconds=86400`),
`0 <= age_seconds <= 86400`, and
`outcome=applicable`.

If a selected patch has no child row, return
`blocked_patch_not_applicable`; this is an honest no-selected-patch result and
must never be converted into fabricated applicability. A deallocated, stopped,
unknown-power Azure VM returns `blocked_target_not_running` and is never
started. A pending or unknown reboot state blocks until an operator separately
resolves it and obtains a fresh assessment.

Return only schema `1.0` structured evidence with the exact subscription,
target, selected patch membership, provider `observed_at`,
`outcome=applicable`, and `blockers=[]`. Evidence is valid only as the direct
same-run input to the bound write skill. Never store, reconstruct, or reuse
it. Model prose is not applicability or patch-success evidence.
