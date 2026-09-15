# Azure SRE Agent Patch Execution

This is a source-only, default-off Phase 3 Safe Remediation Execution
follow-up. It does not change Phase 4 scope, entry gates, or acceptance
evidence.

## Runtime mode

Set `AIOPS_PATCH_EXECUTION=sre-agent` only after every prerequisite below is
met. When the value is absent or unrecognized, the existing refusing adapter
remains active. Existing `azure`, `arm`, and `azure-arm` modes continue to use
the direct ARM adapter.

Required runtime values:

| Variable | Contract |
| --- | --- |
| `AIOPS_SRE_AGENT_TRIGGER_URL` | Secret-backed HTTPS URL for one pre-created HTTP trigger. Never log or hard-code it. |
| `AIOPS_SRE_AGENT_ENDPOINT` | Independently configured, non-secret HTTPS agent origin used to pin the secret trigger URL and poll threads. Localhost, IP literals, userinfo, explicit ports, paths, queries, and fragments are rejected. |
| `AIOPS_SRE_AGENT_SUBSCRIPTION_ID` | The single subscription accepted by the adapter. |
| `AIOPS_SRE_AGENT_TARGET_PREFIX` | The exact ARM prefix beneath which VM/Arc targets are allowed. |
| `AIOPS_SRE_AGENT_TRIGGER_SCOPE` | Trigger token scope; defaults to `59f0a04a-b322-4310-adc9-39ac41e9631e/.default`. |
| `AIOPS_SRE_AGENT_THREAD_SCOPE` | Thread polling token scope; defaults to `https://azuresre.dev/.default`. |
| `AZURE_CLIENT_ID` | Existing API user-assigned managed identity client ID. |

The API acquires a fresh managed-identity token for each trigger submission
and thread poll. It never forwards the authenticated operator token.
Redirects are disabled for both requests.

ARM and SRE read-only verifiers are wired independently of the current write
mode and route by the provider persisted on each execution attempt. Switching
the configured write adapter therefore does not strand an already-submitted
operation. An ordinary retry cannot change providers; use a new explicitly
superseding execution when the provider must change.

## Trigger contract

Create the HTTP trigger separately through the Azure SRE Agent data plane.
There is no documented typed ARM/Terraform HTTP-trigger resource, so this
repository intentionally does not create or manage the trigger.

Configure the trigger as **Autonomous**. AIOps approval and its immutable
execution snapshot are the upstream authorization boundary; an autonomous
trigger must not introduce another interactive approval state.

Use this prompt contract:

> Execute only the `install_patches` operation in the supplied versioned JSON
> envelope. Install every and only the exact `patch_ids` on the exact
> `target_id` inside the supplied `subscription_id`, using the supplied
> `reboot_setting`. Do not discover, infer, broaden, substitute, or fall back
> to all available patches. Do not change any other subscription, resource,
> node, node pool, or configuration. If any requested patch cannot be
> installed exactly as supplied, stop and report the bounded failure. Echo the
> supplied `run_id` in the thread outcome.

The prompt is not a security boundary. Before enabling the mode:

- Restrict the SRE Agent `managedResources` to the approved subscription and
  target resource set.
- Grant the SRE Agent action identity only the VM/Arc patch actions required
  within those managed resources.
- Grant the API UAI only `Microsoft.App/agents/threads/read` and
  `Microsoft.App/agents/threads/write` at the individual SRE Agent resource.
  Terraform defines this role and assignment only behind
  `enable_sre_agent_patch_execution = false` by default.
- Store the trigger URL in an existing Key Vault secret and supply only its
  URI through `sre_agent_http_trigger_secret_id`. Terraform state never
  receives the trigger URL value.

The adapter sends only `schema_version`, `run_id`, `subscription_id`,
`target_id`, `target_kind`, `patch_ids`, `reboot_setting`, `requested_by`,
`approved_by`, and `operation`. It supports Azure VM and Arc
`install_patches` runs only; AKS node-image upgrades, empty patch selections,
cross-subscription targets, and targets outside the configured prefix fail
before submission.

## Verification and recovery

An HTTP `202` with `success=true` and a non-empty `threadId` means accepted,
not patched. The verifier polls the documented
`GET {agentEndpoint}/api/v1/threads/{threadId}` endpoint:

- `In Progress` remains running.
- `Pending User Input` fails because it violates the Autonomous trigger
  contract.
- `Complete` records provider completion.

Provider completion is never clean patch proof. The existing refreshed target
evidence reconciliation must still clear every immutable selected patch ID;
only `evidence_reconciliation.status=reconciled_clean` completes the workflow.
Free-form SRE Agent messages are never parsed as evidence.

The HTTP trigger has no documented idempotency guarantee. The durable
pre-submit execution claim and immutable `run_id` remain authoritative.
Transport failure or a 5xx response after POST is `submission_ambiguous`.
Ordinary retry stays refused. Authoritative refreshed target evidence may
prove the exact selection clean; otherwise an SRE ambiguity remains
non-retryable after its deadline and requires recovered thread identity or an
explicit superseding/manual resolution. Direct ARM timeout behavior is
unchanged.

## Terraform enablement

Terraform preserves the existing imported SRE Agent resource and import
preflight. A future separately approved deployment may set:

```hcl
enable_sre_agent_patch_execution = true
sre_agent_http_trigger_secret_id = "https://<vault>.vault.azure.net/secrets/<name>"
sre_agent_endpoint               = "https://<agent-endpoint>"
sre_agent_patch_target_prefix    = "/subscriptions/<id>/resourceGroups/<approved-rg>"
```

Do not enable the flag until the pre-created Autonomous trigger,
`managedResources`, action-identity patch permissions, Key Vault secret, and
agent-scoped caller role have all been reviewed. Enabling or applying this
configuration is an Azure write and is outside this source-only change.
