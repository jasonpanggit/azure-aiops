---
name: aiops-install-selected-patches-v1
description: Install only an exact app-approved Windows patch selection on one Azure VM or Arc-enabled server.
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
- After validation, invoke `RunAzCliWriteCommands` exactly once with the exact
  command. Autonomous trigger mode may submit it only because the dispatching
  API has already bound explicit human approval to this immutable payload.
- Do not present the command only in prose, create a `userQuestion`, ask for a
  chat response, call `SubmitMessage`, or create another approval layer.
- On refusal or any validation failure, return `blocked_no_action` without a
  write-tool call.

## Immutable approval and evidence checks

Require schema version `1.1`, operation `install_patches`, `IfRequired`, and
`PT2H`. The dispatching API has authoritatively checked the approval decision
and timestamps immediately before creating this immutable payload. Treat its
`approval.decision=approved` as current; do not independently infer the
current time or reject from a self-calculated expiry. Still require a nonempty
decision ID and approver, valid snapshot hash, and exact equality among every
top-level, approved-snapshot, read-skill, and write-skill target and patch
field.

The approved snapshot may additionally contain exactly one `rollout` object:
`rollout_id` (`RMO-` plus 32 lowercase hex digits), `terms_hash` (64 lowercase
hex digits), and integer `wave` (1 through 5). Include that complete object in
the canonical snapshot hash when present; never drop, replace or infer it.
The dispatching API enforces immutable maintenance terms, explicit wave
admission and stop conditions immediately before submission. This metadata
adds no command argument or provider-side scheduler. Do not advance a wave,
extend a window, cancel in-flight work, or infer successful target verification.

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
`vm_power_state=PowerState/running` immediately before write handoff. A
deallocated, stopped, or unknown-power VM is blocked and never auto-started.
A pending or unknown reboot state and a missing selected-patch child row are
blocked until separately resolved and freshly reassessed. Stored,
reconstructed, model-authored, stale, partial, extra, or mismatched evidence
is forbidden.

## Fixed command

For `target_kind=Azure VM`, pass exactly:

```text
az vm install-patches --ids <target_id> --kb-numbers-to-include <exact IDs> --maximum-duration PT2H --reboot-setting IfRequired --no-wait
```

For `target_kind=Arc-enabled server`, serialize every and only approved patch
ID as a compact JSON string array and pass exactly:

```text
az connectedmachine install-patches --ids <target_id> --windows-parameters '{"kbNumbersToInclude":[...]}' --maximum-duration PT2H --reboot-setting IfRequired --no-wait true
```

An empty include filter, classification filter, exclusion, Linux parameter,
alternate target or patch, additional argument, changed command, fallback,
retry, or second command is forbidden. Never submit before explicit Review
approval recorded in the immutable app payload.

## Closed outcome

After a write-tool acceptance, return one `provider_operation` object with
exactly schema `1.0`, a nonempty provider `operation_id`, status `submitted`,
`running`, `succeeded`, or `completed`, this exact skill name/version,
operation `install_patches`, the immutable `target_id`, and the exact ordered
`patch_ids`. No additional field is allowed. On refusal or validation failure,
return terminal `failed_without_action` and never fabricate
`provider_operation`. If a successful `--no-wait` write command returns empty
output and no typed provider operation, return `submission_ambiguous` without
retry; the dispatching runtime may recover provider proof only from its own
read-only evidence chain: Azure Activity Log may establish accepted submission
context for the exact immutable target, exact installPatches operation type,
write-attempt time window, and exactly one accepted/succeeded correlation ID,
but the durable provider operation/result ID must come from one unambiguous
Azure Resource Graph `patchinstallationresources` parent
`patchInstallationResults/<id>` row whose start time is after the write
attempt, whose status/counts indicate success, and whose child
`softwarePatches` rows prove every and only selected KB is Installed. Missing,
multiple, failed, wrong-target, wrong-operation, out-of-window, or
wrong-selected-KB evidence remains `submission_ambiguous`. Tool acceptance,
thread completion, Activity Log recovery, and model prose never prove patch
success. Provider completion never substitutes for refreshed selected-KB
reconciliation.
