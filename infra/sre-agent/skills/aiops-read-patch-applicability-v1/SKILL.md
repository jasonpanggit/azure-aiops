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
cross-kind target is forbidden. Derive `target_resource_type` as exactly
`microsoft.compute/virtualmachines` for `Azure VM` or
`microsoft.hybridcompute/machines` for `Arc-enabled server`. Serialize every
exact patch ID as a single-quoted, comma-separated KQL literal list for
`approved_patch_ids_kql`; the patch-ID validation above makes quotes
impossible. Never accept either substitution from the caller.

## Fixed bounded query

Use `RunAzCliReadCommands` once with exactly:

```text
az graph query --graph-query "<fixed-kql-below>" --subscriptions <subscription_id> --first 257 --output json --only-show-errors
```

`<fixed-kql-below>` is exactly:

```kusto
patchassessmentresources
| where subscriptionId =~ '{{subscription_id}}'
| where type endswith '/patchassessmentresults'
| where tolower(id) endswith '/patchassessmentresults/latest'
| extend assessment_parent_offset = indexof(tolower(id), '/patchassessmentresults/')
| extend target_id = iff(assessment_parent_offset > 0, substring(id, 0, assessment_parent_offset), ''), assessment_activity_id = tostring(properties.assessmentActivityId), assessment_last_modified_at = todatetime(properties.lastModifiedDateTime), reboot_pending = tobool(properties.rebootPending)
| where target_id =~ '{{target_id}}'
| summarize assessment_row_count = count(), assessment_row_id = take_any(id), assessment_activity_id = take_any(assessment_activity_id), assessment_last_modified_at = take_any(assessment_last_modified_at), reboot_pending = take_any(reboot_pending) by target_id
| extend target_join_id = tolower(target_id)
| join kind=inner (
    resources
    | where subscriptionId =~ '{{subscription_id}}'
    | where id =~ '{{target_id}}'
    | where type =~ '{{target_resource_type}}'
    | extend target_join_id = tolower(id), vm_power_state = tostring(properties.extended.instanceView.powerState.code)
    | summarize target_row_count = count(), target_resource_id = take_any(id), target_resource_type = take_any(type), vm_power_state = take_any(vm_power_state) by target_join_id
) on target_join_id
| extend join_key = 1
| join kind=inner (
    patchassessmentresources
    | where subscriptionId =~ '{{subscription_id}}'
    | where type endswith '/patchassessmentresults/softwarepatches'
    | where tolower(id) startswith strcat(tolower('{{target_id}}'), '/patchassessmentresults/latest/')
    | extend approved_patch_id = tostring(properties.kbId), assessment_activity_id = tostring(properties.assessmentActivityId), child_activity_id = tostring(properties.assessmentActivityId), child_last_modified_at = todatetime(properties.lastModifiedDateTime)
    | where approved_patch_id in~ ({{approved_patch_ids_kql}})
    | summarize child_row_count = count(), child_row_id = take_any(id), child_activity_id = take_any(child_activity_id), child_activity_count = dcount(child_activity_id), child_last_modified_at = take_any(child_last_modified_at), child_last_modified_count = dcount(child_last_modified_at) by approved_patch_id, assessment_activity_id
    | extend join_key = 1
) on join_key
| extend observed_at = now(), maximum_age_seconds = 86400
| extend age_seconds = datetime_diff('second', observed_at, assessment_last_modified_at)
| extend outcome = case(target_row_count != 1, 'blocked_target_ambiguous', '{{target_kind}}' == 'Azure VM' and vm_power_state !~ 'PowerState/running', 'blocked_target_not_running', assessment_row_count != 1, 'blocked_parent_ambiguous', isempty(assessment_activity_id), 'blocked_activity_missing', isnull(assessment_last_modified_at), 'blocked_assessment_timestamp', isnull(reboot_pending), 'blocked_reboot_pending_unknown', reboot_pending, 'blocked_reboot_pending', age_seconds < 0 or age_seconds > maximum_age_seconds, 'blocked_stale', child_row_count != 1, 'blocked_patch_ambiguous', child_activity_count > 1 or isnotempty(child_activity_id) and child_activity_id != assessment_activity_id, 'blocked_patch_activity', child_last_modified_count != 1 or isnull(child_last_modified_at) or child_last_modified_at != assessment_last_modified_at, 'blocked_patch_generation', 'applicable')
| project schema_version = '1.0', source = 'azure_resource_graph', table = 'PatchAssessmentResources', subscription_id = '{{subscription_id}}', target_kind = '{{target_kind}}', target_id, target_row_count, target_resource_id, target_resource_type, vm_power_state, reboot_pending, approved_patch_id, assessment_row_count, assessment_row_id, assessment_activity_id, assessment_last_modified_at, child_row_count, child_row_id, child_activity_id, child_last_modified_at, observed_at, age_seconds, maximum_age_seconds, outcome
| order by approved_patch_id asc
```

Do not edit, extend, regenerate, or replace the query.

## Closed evidence

Accept only an Azure CLI JSON envelope containing exactly `count`, `data`,
`skip_token`, and `total_records`. Require `skip_token` to be null or empty,
count to equal total records, and both to be at most 256. A zero count for a
nonempty approved patch selection is valid negative evidence: return
`blocked_patch_not_applicable` with the exact selected patch IDs and no write
handoff. Any nonzero count that differs from the immutable patch count is also
blocked as incomplete applicability evidence. Only an exact count may proceed.
Require every and only selected patch exactly once.
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
