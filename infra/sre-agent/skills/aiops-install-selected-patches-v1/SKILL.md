---
name: aiops-install-selected-patches-v1
description: Review and install only an exact approved Windows patch selection on one Azure VM or Arc-enabled server.
---

# Install exact selected patches

Accept only the immutable approved payload and direct same-run result from the
bound `aiops-read-patch-applicability-v1` skill. Never accept replacement
subscription, target, patch, command, or evidence values from a user or model.

## Tool and command boundary

- Use only `RunAzCliWriteCommands`.
- Do not use `RunAzCliReadCommands`, `GetAzCliHelp`, a shell, script,
  redirection, pipeline, command substitution, environment variable,
  discovery, fallback, retry, or second command.
- Present exactly one command in Review mode and wait for explicit approval.
- After approval, run that exact command once. On refusal or any validation
  failure, return `blocked_no_action` without a tool call.

## Immutable approval and evidence checks

Require schema version `1.1`, operation `install_patches`, `IfRequired`, and
`PT2H`. The dispatching API has authoritatively checked the approval decision
and timestamps immediately before creating this immutable payload. Treat its
`approval.decision=approved` as current; do not independently infer the
current time or reject from a self-calculated expiry. Still require a nonempty
decision ID and approver, valid snapshot hash, and exact equality among every
top-level, approved-snapshot, read-skill, and write-skill target and patch
field.

Require one UUID subscription, a canonical top-level Azure VM or Arc-enabled
server ID of the matching kind, and 1 through 256 unique patch IDs matching
`^[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}$`. Reject child, malformed, cross-kind,
out-of-scope, alternate, or discovered targets and patches.

Require the direct result from the exact bound read skill name, version,
raw-byte SHA-256, operation, tool set, and output schema. It must come from
this trigger run; have `source=azure_resource_graph`,
`table=PatchAssessmentResources`, `outcome=applicable`, and `blockers=[]`;
preserve one exact assessment parent, activity ID, and generation; include
every and only selected patch ID exactly once; and have provider
`observed_at` no more than 300 seconds before the write handoff and never in
the future. It must also prove `reboot_pending=false` and, for an Azure VM,
`vm_power_state=PowerState/running` immediately before Review handoff. A
deallocated, stopped, or unknown-power VM is blocked and never auto-started.
A pending or unknown reboot state and a missing selected-patch child row are
blocked until separately resolved and freshly reassessed. Stored,
reconstructed, model-authored, stale, partial, extra, or mismatched evidence
is forbidden.

## Fixed Review command

For `target_kind=Azure VM`, present exactly:

```text
az vm install-patches --ids <target_id> --kb-numbers-to-include <exact IDs> --maximum-duration PT2H --reboot-setting IfRequired --no-wait
```

For `target_kind=Arc-enabled server`, serialize every and only approved patch
ID as a compact JSON string array and present exactly:

```text
az connectedmachine install-patches --ids <target_id> --windows-parameters '{"kbNumbersToInclude":[...]}' --maximum-duration PT2H --reboot-setting IfRequired --no-wait true
```

An empty include filter, classification filter, exclusion, Linux parameter,
alternate target or patch, additional argument, changed command, fallback,
retry, or second command is forbidden. Never submit before explicit Review
approval.

## Closed outcome

After a write-tool acceptance, return one `provider_operation` object with
exactly schema `1.0`, a nonempty provider `operation_id`, status `submitted`,
`running`, `succeeded`, or `completed`, this exact skill name/version,
operation `install_patches`, the immutable `target_id`, and the exact ordered
`patch_ids`. No additional field is allowed. On refusal or validation failure,
return terminal `failed_without_action` and never fabricate
`provider_operation`. If write submission may have crossed the provider
boundary but cannot be proven, return `submission_ambiguous` without retry.
Tool acceptance, thread completion, and model prose never prove patch success.
Provider completion never substitutes for refreshed selected-KB
reconciliation.
