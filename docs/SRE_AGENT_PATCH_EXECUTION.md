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
| `AIOPS_SRE_AGENT_TRIGGER_ID` | Exact reviewed non-secret trigger ID. The adapter requires the secret URL path to contain this exact ID. |
| `AIOPS_SRE_AGENT_TRIGGER_ORIGIN` | Independently reviewed, non-secret HTTPS origin copied from the trigger URL. It pins the secret URL without assuming the trigger and thread endpoints share a domain. |
| `AIOPS_SRE_AGENT_ENDPOINT` | Independently configured, non-secret HTTPS agent data-plane origin used to poll threads. Localhost, IP literals, userinfo, explicit ports, paths, queries, and fragments are rejected. |
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

Create the HTTP trigger separately through the Azure SRE Agent portal. The
documented data-plane routes do not publish a formal create/update schema,
ETag/`If-Match` contract, or redirect semantics. This repository therefore
does not create, update, or delete the trigger. The checked-in operator review
body is `infra/sre-agent/patch-trigger.v1.json`; it is not asserted to be the
undocumented service wire format.

Configure the demo trigger as **Review**. AIOps approval and its immutable
execution snapshot remain the upstream authorization boundary. Review mode
must display exactly one bounded install command and wait for explicit
approval; it may not reconstruct or widen the approved action.

Use the exact prompt, description, Review mode, NewThreadPerRun grouping,
and payload contract from the versioned artifact. Render its deterministic
review body and SHA-256 hash with:

```sh
python3 scripts/preflight_sre_agent_patch_execution.py render
```

The prompt and skills are not security boundaries. Before enabling the mode:

- Import exactly the two repository-reviewed Skill Builder artifacts:
  `infra/sre-agent/skills/aiops-read-patch-applicability-v1/SKILL.md` with
  only `RunAzCliReadCommands`, and
  `infra/sre-agent/skills/aiops-install-selected-patches-v1/SKILL.md` with
  only `RunAzCliWriteCommands`. Do not select `GetAzCliHelp`. Their names,
  versions, raw-byte SHA-256 hashes, tool sets, operations, output schemas,
  and read-then-write ordering are bound into both the trigger artifact and
  runtime envelope.
- The authenticated remediation API and its recorded approval snapshot remain
  the authorization boundary. SRE Agent may use read-only tools and knowledge
  skill's fixed Azure Resource Graph query to evaluate every and only selected
  KB. Azure Resource Graph is not a built-in Azure SRE Agent skill, so the
  reviewed custom read skill is required. Do not paste or accept
  caller-supplied KQL.
- Read evidence is capped at 257 rows, must be within PT24H, and must retain
  one exact target and assessment parent/activity/generation. Immediately
  before Review handoff it must also prove an Azure VM is
  `PowerState/running` and the assessment has `rebootPending=false`. A stopped,
  deallocated, or unknown-power VM is never auto-started; a pending or unknown
  reboot state blocks until separately resolved and freshly reassessed. A
  missing selected-patch child row is an honest not-applicable result, never
  fabricated applicability. The write is allowed only when direct same-run
  evidence is at most PT5M old and exactly matches every write input. Missing,
  stale, ambiguous, partial, or extra evidence stops without action.
- The write skill presents exactly one command, waits for Review approval,
  and then invokes it once. Empty filters, classifications, discovery,
  alternate targets/patches, shell use, second commands, fallback, and retry
  are forbidden.

- Restrict the SRE Agent `managedResources` to the approved subscription and
  target resource set.
- Grant the SRE Agent action identity only the VM/Arc patch actions required
  within those managed resources.
- Grant the API UAI only `Microsoft.App/agents/threads/write` for trigger
  invocation and `Microsoft.App/agents/threads/read` for verification at the
  individual SRE Agent resource. Terraform defines separate custom roles so
  rollback can remove write while temporarily retaining read.
- Store the trigger URL in an existing Key Vault secret and supply only its
  URI through `sre_agent_http_trigger_secret_id`. Terraform state never
  receives the trigger URL value.
- Grant the SRE action UAI only the custom role defined in
  `infra/terraform/sre_agent.tf` for VM/Arc resource reads and
  `installPatches/action`, assigned at `sre_agent_patch_target_prefix`.
  Assessment actions and patch-result reads are not required to submit the
  documented install operation and are deliberately excluded.

The adapter sends only `schema_version`, `run_id`, `subscription_id`,
`target_id`, `target_kind`, `patch_ids`, `approval`, `skill_chain`, `reboot_setting`,
`maximum_duration=PT2H`, `requested_by`, `approved_by`, and `operation`. The
approval is the exact current durable decision and hash-bound snapshot. The
skill chain contains exact raw-byte hashes and cannot be replaced at runtime.
The duration is the same bounded constant used by the direct ARM adapter,
and reboot mode is fixed to `IfRequired`. It supports Azure VM and Arc
`install_patches` runs only; AKS node-image upgrades, empty patch selections,
cross-subscription targets, and targets outside the configured prefix fail
before submission.

## Verification and recovery

An HTTP `202` with `success=true` and a non-empty `threadId` means accepted,
not patched. The verifier polls the documented
`GET {agentEndpoint}/api/v1/threads/{threadId}` endpoint:

- `In Progress` remains running.
- scalar `Pending User Input`, or a composite thread with a critical or
  warning action, records `Pending Review` and remains provider-active;
- composite incident `Failed`/`Error` and `Cancelled` are typed terminal
  failures without reading message prose; and
- scalar `Complete` or composite `lastMessage.isComplete=true` without an
  exact typed `provider_operation` fails closed as
  `submission_ambiguous`, so retry and supersession remain refused;
- completion advances only when `provider_operation` has exactly schema
  `1.0`, a nonempty provider operation ID, a submitted/running/succeeded/
  completed status, the bound write skill name/version,
  `operation=install_patches`, and target/ordered patch IDs exactly equal to
  the immutable snapshot; and
- terminal `failed_without_action` is an explicit no-write failure, never
  provider success.

A provider-active Pending Review remains running even beyond the local
verification deadline, so retry and supersede stay refused while the original
thread remains approvable.

Provider completion is never clean patch proof. The existing refreshed target
evidence reconciliation must still clear every immutable selected patch ID;
only `evidence_reconciliation.status=reconciled_clean` completes the workflow.
For SRE Agent only, the refreshed `assessed_at` must strictly postdate both
the persisted provider-handle transition and the first terminal thread
transition. Older, missing, malformed, or timezone-naive evidence remains
pending/ambiguous under the existing deadline and recovery rules. Direct ARM
behavior is unchanged. Free-form SRE Agent messages are never parsed as
evidence.

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
enable_sre_agent_patch_rbac      = true
retain_sre_agent_thread_verification = false
sre_agent_http_trigger_secret_id = "https://aiops-dev-kv-g6ludc.vault.azure.net/secrets/sre-agent-http-trigger-url/<version>"
sre_agent_trigger_id             = "<reviewed-trigger-id>"
sre_agent_trigger_origin         = "https://<reviewed-trigger-origin>"
sre_agent_endpoint               = "https://<agent-endpoint>"
sre_agent_patch_target_prefix    = "/subscriptions/<id>/resourceGroups/<approved-rg>"
sre_agent_managed_resources      = [
  "/subscriptions/<id>/resourceGroups/<approved-rg>"
]
```

Do not enable the flag until the pre-created Review trigger,
`managedResources`, action-identity patch permissions, Key Vault secret, and
agent-scoped caller role have all been reviewed. Enabling or applying this
configuration is an Azure write and is outside this source-only change.

When the flag is false, Terraform omits `AIOPS_PATCH_EXECUTION`; it no longer
forces direct ARM mode. The application therefore retains its refusing
default. `AIOPS_SRE_AGENT_ENDPOINT` may remain configured during rollback so
already-persisted SRE attempts can continue read-only thread verification.

## Draft: live-trigger readiness

This section is an operator runbook, not authorization. Source merge alone
does not authorize trigger creation, RBAC changes, secret provisioning,
Terraform planning/apply, a canary, or a production rollout.

### Sanitized read-only capture

Use a private temporary directory and never write access tokens or raw trigger
responses into the repository:

```sh
umask 077
READ_DIR="$(mktemp -d)"
SUB='a87a8e64-a52a-4aa8-a760-5e8919d23cd1'
TENANT='ffc83107-fcc0-4d2e-8798-d582da36505e'
SRE_ID="/subscriptions/${SUB}/resourceGroups/rg-sredemo-dev/providers/Microsoft.App/agents/sre-agent-sredemo"
API_UAI='2c367602-bb4f-4868-8dbb-7f4ca117a719'
SRE_UAI='5b3b9ec4-16fb-4c0f-96fb-16887062f976'
TARGET_PREFIX="/subscriptions/${SUB}/resourceGroups/rg-sredemo-dev"
TRIGGER_ID='<reviewed-trigger-id>'
TRIGGER_ORIGIN='https://<reviewed-trigger-origin>'
CANONICAL_HASH="$(
  python3 scripts/preflight_sre_agent_patch_execution.py render |
  jq -r '.canonicalHash'
)"
```

Capture only the required agent fields:

```sh
az rest --method get \
  --url "https://management.azure.com${SRE_ID}?api-version=2026-01-01" \
  --only-show-errors -o json |
jq '{
  apiVersion:"2026-01-01",
  resource:{
    id,name,type,
    properties:{
      provisioningState:.properties.provisioningState,
      runningState:.properties.runningState,
      powerState:.properties.powerState,
      agentEndpoint:.properties.agentEndpoint,
      actionConfiguration:.properties.actionConfiguration,
      knowledgeGraphConfiguration:{
        managedResources:.properties.knowledgeGraphConfiguration.managedResources
      }
    }
  }
}' > "${READ_DIR}/agent.sanitized.json"
```

Capture the visible subscription set and the complete raw inherited assignment
list for both identities in every visible subscription. Do not use `--query`
on assignment results and do not manually construct a reduced assignment
array. Resolve every referenced role definition from its raw CLI response.

```sh
az account list --all --refresh \
  --query "[?tenantId=='${TENANT}'].id" -o json \
  > "${READ_DIR}/visible-subscriptions.json"

RBAC_ARGS=()
while IFS= read -r visible_sub; do
  api_file="${READ_DIR}/api-uai.${visible_sub}.assignments.raw.json"
  sre_file="${READ_DIR}/sre-uai.${visible_sub}.assignments.raw.json"
  for principal_spec in "api:${API_UAI}:${api_file}" "sre:${SRE_UAI}:${sre_file}"; do
    principal_id="$(printf '%s' "${principal_spec}" | cut -d: -f2)"
    merged_file="$(printf '%s' "${principal_spec}" | cut -d: -f3)"
    az role assignment list --subscription "${visible_sub}" \
      --assignee-object-id "${principal_id}" --all --include-inherited \
      --include-groups --only-show-errors -o json \
      > "${merged_file}.descendants"
    az role assignment list --subscription "${visible_sub}" \
      --assignee-object-id "${principal_id}" \
      --scope "/subscriptions/${visible_sub}" --include-inherited \
      --include-groups --only-show-errors -o json \
      > "${merged_file}.parents"
    jq -s 'add | unique_by(.id)' \
      "${merged_file}.descendants" "${merged_file}.parents" > "${merged_file}"
  done
  RBAC_ARGS+=(
    --api-inherited-assignment-json "${visible_sub}=${api_file}"
    --sre-inherited-assignment-json "${visible_sub}=${sre_file}"
  )
done < <(jq -r '.[]' "${READ_DIR}/visible-subscriptions.json")

jq -r '.[].roleDefinitionId' \
  "${READ_DIR}"/*.assignments.raw.json |
  sort -fu > "${READ_DIR}/role-definition-ids.txt"

while IFS= read -r role_id; do
  role_scope="${role_id%/providers/Microsoft.Authorization/roleDefinitions/*}"
  role_scope="${role_scope:-/subscriptions/${SUB}}"
  az role definition list --name "${role_id##*/}" \
    --scope "${role_scope}" --only-show-errors -o json |
    jq 'if length == 1 then .[0] else error("role definition not unique") end'
done < "${READ_DIR}/role-definition-ids.txt" |
jq -s '.' > "${READ_DIR}/role-definitions.raw.json"

python3 scripts/preflight_sre_agent_patch_execution.py build-rbac \
  --visible-subscriptions-json "${READ_DIR}/visible-subscriptions.json" \
  "${RBAC_ARGS[@]}" \
  --role-definitions-json "${READ_DIR}/role-definitions.raw.json" \
  --target-prefix "${TARGET_PREFIX}" \
  > "${READ_DIR}/rbac.sanitized.json"
```

`build-rbac` embeds every raw row, its raw row count, a deterministic SHA-256,
the principal/subscription provenance, and `includeInherited:true`; it does not
accept a manually normalized assignment array. Verification recomputes every
count and digest, requires one capture per known principal per visible
subscription, internally normalizes the raw rows, resolves every referenced
raw role definition one-for-one, and rejects omitted/extra/misattributed rows,
unknown roles, outside/inherited scopes, and Owner/Contributor/custom wildcard
fallbacks that cover guarded writes.

Trigger list/read uses the SRE data-plane audience. The collector accepts only
the exact observed production row keys: `agent`, `agentMode`, `agentPrompt`,
`createdAt`, `createdBy`, `description`, `executionCount`, `id`,
`lastExecutionTime`, `modelTier`, `name`, `threadId`, `triggerEnabled`,
`triggerLastCalledAt`, and `triggerUrl`. It requires the default response agent
(`agent: null`), lowercase `review`, enabled state, empty/null `threadId`,
exact canonical name/prompt, and exact trigger URL/ID/origin with no query,
fragment, alias, or extra path. Missing or additional fields preserve HOLD.

The portal has no payload-schema field. The local `payloadSchema` is validated
against the runtime adapter's exact outgoing envelope contract and remains
bound to the canonical artifact hash; it is never fabricated from the live
trigger row.

```sh
AGENT_ENDPOINT="$(
  jq -r '.resource.properties.agentEndpoint' \
    "${READ_DIR}/agent.sanitized.json"
)"
az account get-access-token --resource 'https://azuresre.dev' \
  --query accessToken -o tsv > "${READ_DIR}/sre-token"
chmod 600 "${READ_DIR}/sre-token"
{
  printf 'Authorization: Bearer '
  cat "${READ_DIR}/sre-token"
  printf '\nAccept: application/json\n'
} > "${READ_DIR}/sre-headers"
curl --silent --show-error --fail-with-body --max-redirs 0 \
  --connect-timeout 10 --max-time 30 \
  -H @"${READ_DIR}/sre-headers" \
  "${AGENT_ENDPOINT%/}/api/v1/httptriggers" \
  > "${READ_DIR}/triggers.raw.json"
rm -f "${READ_DIR}/sre-token" "${READ_DIR}/sre-headers"
```

Capture secret metadata without requesting a secret value, and capture the
Container Apps reference separately:

```sh
VAULT='aiops-dev-kv-g6ludc'
az keyvault secret list --subscription "${SUB}" --vault-name "${VAULT}" \
  --query "[?name=='sre-agent-http-trigger-url'].{
    id:id,name:name,enabled:attributes.enabled,tags:tags
  } | [0]" --only-show-errors -o json \
  > "${READ_DIR}/secret-metadata.json"

az containerapp show --subscription "${SUB}" \
  --resource-group aiops-dev-rg --name aiops-dev-api \
  --query "{
    secrets:properties.configuration.secrets[
      ?name=='sre-agent-http-trigger-url'
    ].{name:name,keyVaultUrl:keyVaultUrl},
    env:properties.template.containers[0].env[
      ?name=='AIOPS_SRE_AGENT_TRIGGER_URL'
    ].{name:name,secretRef:secretRef}
  }" --only-show-errors -o json \
  > "${READ_DIR}/containerapp-secret-reference.json"
```

The secret must carry these value-free attestation tags:
`aiops-trigger-id=<reviewed-trigger-id>`,
`aiops-trigger-origin=https://<reviewed-trigger-origin>`, and
`aiops-trigger-definition-sha256=<canonical-hash>`. Normalize the two capture
files into the exact value-free
`tests/fixtures/sre_agent_patch_secret.sanitized.json` shape. Any `value`,
token, disabled/missing metadata, tag mismatch, mismatched URI, or missing ACA
reference is a blocker. The preflight never reads the secret value.

After separate write approval, provision the value and attestations together:

```sh
az keyvault secret set --subscription "${SUB}" --vault-name "${VAULT}" \
  --name sre-agent-http-trigger-url --value "${SRE_TRIGGER_URL}" \
  --tags \
    "aiops-trigger-id=${TRIGGER_ID}" \
    "aiops-trigger-origin=${TRIGGER_ORIGIN}" \
    "aiops-trigger-definition-sha256=${CANONICAL_HASH}"
```

### Offline evidence validation

Offline fixtures and externally supplied JSON are useful for deterministic
review and tests, but they cannot prove that a live assignment row was not
omitted. `build-rbac` and `verify` therefore report
`offline-evidence-valid` plus the blocker `fresh live collector required`;
they can never emit `ready-for-approved-trigger-canary`.

```sh
python3 scripts/preflight_sre_agent_patch_execution.py verify \
  --trigger-json "${READ_DIR}/trigger.sanitized.json" \
  --agent-json "${READ_DIR}/agent.sanitized.json" \
  --rbac-json "${READ_DIR}/rbac.sanitized.json" \
  --secret-json "${READ_DIR}/secret.sanitized.json" \
  --expected-trigger-id '<reviewed-trigger-id>' \
  --expected-trigger-origin 'https://<reviewed-trigger-origin>' \
  --expected-agent-endpoint "${AGENT_ENDPOINT}" \
  --target-prefix "${TARGET_PREFIX}"
```

The `render`, `build-rbac`, and `verify` modes never invoke Azure CLI, `curl`,
Terraform, or a write API. There is no `--apply` mode. Their JSON inputs are
explicitly replayable test/review evidence and never authorize either live
stage.

### Mandatory same-process live collector

RBAC bootstrap is a distinct, separately approved stage. First save and review
a Terraform plan with `enable_sre_agent_patch_rbac=true` and
`enable_sre_agent_patch_execution=false`. It must contain only the three
reviewed role definitions and assignments and zero unrelated changes. After a
separate approval applies that bootstrap plan, run:

```sh
python3 scripts/preflight_sre_agent_patch_execution.py collect-live-rbac \
  --target-prefix "${TARGET_PREFIX}" \
  --evidence-output "${READ_DIR}/live-rbac.informational.json"
```

This mode itself executes only these fixed argv families with `shell=False`:
`az account list --all --refresh`, `az role assignment list --all
--include-inherited --include-groups` for both known principals in every visible target-tenant
subscription, a second explicit `--scope /subscriptions/<id>
--include-inherited --include-groups` query that captures parent
management-group grants, and `az role definition list` at each referenced
definition's subscription or management-group scope. It
rejects non-zero exits, any stderr, malformed/non-list JSON, incomplete query
coverage, missing or extra role definitions, and every RBAC contract failure.
It records exact argv, exit code, raw stdout byte count/SHA-256, and parsed row
count before internal normalization. Its status is only `live-rbac-valid`; it
never claims canary readiness.

`--include-groups` is mandatory: group-principal rows returned for the queried
UAI are treated as effective grants for that UAI and broad Owner, Contributor,
thread wildcard, or patch wildcard access blocks readiness. Query-principal
provenance remains separate from each row's `principalId`. The three required
least-privilege assignments must still be direct `ServicePrincipal`
assignments to the expected UAI; a group assignment cannot satisfy them.

After the trigger and versioned secret exist, run the mandatory pre-deploy
collector before authorizing an enablement plan:

```sh
python3 scripts/preflight_sre_agent_patch_execution.py live-predeploy \
  --expected-trigger-id "${TRIGGER_ID}" \
  --expected-trigger-origin "${TRIGGER_ORIGIN}" \
  --expected-agent-endpoint "${AGENT_ENDPOINT}" \
  --secret-version '<version>' \
  --target-prefix "${TARGET_PREFIX}" \
  --evidence-output "${READ_DIR}/live-predeploy.informational.json"
```

The collector derives the vault host and secret name from the checked-in
`keyVault` contract in `patch-trigger.v1.json`; callers supply only the
version. It same-process collects the exact ARM agent GET, obtains a scoped SRE
data-plane token through fixed Azure CLI argv, performs an internal
no-redirect authenticated trigger GET selecting the exact ID, reads exact
versioned Key Vault metadata with a fixed value-excluding query, and refreshes
RBAC. Tokens, trigger URLs, raw response bodies, and secret values are excluded
from output and exception text. Only it can emit
`ready-for-approved-enable-plan`.

Immediately before the separately approved canary, run:

```sh
python3 scripts/preflight_sre_agent_patch_execution.py live-canary \
  --expected-trigger-id "${TRIGGER_ID}" \
  --expected-trigger-origin "${TRIGGER_ORIGIN}" \
  --expected-agent-endpoint "${AGENT_ENDPOINT}" \
  --secret-version '<version>' \
  --target-prefix "${TARGET_PREFIX}" \
  --evidence-output "${READ_DIR}/live-canary.informational.json"
```

This repeats every live pre-deploy read and additionally fixed-command
collects the deployed API Container App's SRE environment and Key Vault secret
reference. Only this path can emit
`ready-for-approved-trigger-canary`. Optional evidence is written atomically
with mode `0600` only after validation succeeds, contains no raw assignment
rows or secret values, is labeled informational/non-authorizing, and cannot be
re-imported to reproduce a live verdict.
Azure CLI may render the unused `value` beside a valid `secretRef` as either
`null` or an empty string; the collector normalizes only those two
representations and still requires the exact secret reference.

### Approval, plan, and canary gates

1. Save, machine-check, and separately approve the RBAC-only bootstrap plan:
   `enable_sre_agent_patch_rbac=true`,
   `enable_sre_agent_patch_execution=false`. Apply only the three exact
   roles/assignments.
2. Immediately require `collect-live-rbac=live-rbac-valid`, then a named
   approver creates or updates the trigger after reviewing the canonical
   SHA-256, exact prompt, payload
   schema, Review mode, and New chat thread for each run in the portal
   before saving the trigger. Do not use undocumented trigger PUT/POST
   automation.
3. Separately approve secret provisioning. Put the copied trigger URL into
   `sre-agent-http-trigger-url` with the exact trigger-ID, trigger-origin, and
   canonical-hash attestation tags; pass only its exact versioned Key Vault URI
   to Terraform.
4. Review all enablement values above, including the separately observed
   trigger ID, trigger origin, exact agent endpoint, exact managed resources,
   and a resource-group-or-narrower target prefix.
5. Require `live-predeploy=ready-for-approved-enable-plan`, then generate a
   refresh-enabled saved Terraform plan. The bootstrap already owns the three
   roles/assignments, so require **zero RBAC changes**. The enablement plan may
   contain only the Key Vault-backed ACA secret reference, exact SRE
   environment values, and resulting API revision update, with zero unrelated
   create, update, destroy, replace, identity, agent, APIM, ACA-shape, MCP, or
   state changes. Any unexplained action is an abort.
6. Separately approve and apply only that exact saved plan. Require the new API
   revision healthy and ready at 100% traffic, verify its image and health
   endpoints, and capture the deployed revision name plus normalized SRE
   environment/secret-reference diff before continuing.
7. Select one non-critical VM or Arc machine already inside the exact target
   prefix and one currently applicable low-risk patch ID. Record the immutable
   `run_id`, target ID, patch ID, reboot setting, pre-state, approver, saved-plan
   hash, deployed revision, canonical trigger hash, trigger ID, and expected
   thread origin before the separately approved canary.
8. Run `live-canary` immediately before the canary and require
   `ready-for-approved-trigger-canary`. Then accept only HTTP 202 plus
   `success=true` and one thread ID, terminal `Complete` with the exact typed
   `provider_operation`, and post-terminal refreshed evidence that reconciles
   every selected patch as clean. Prompt prose is never acceptance evidence.

Rollback switches API traffic to a prior revision where
`AIOPS_PATCH_EXECUTION` is absent/refusing, or applies a separately approved
configuration with `enable_sre_agent_patch_execution=false` and
`enable_sre_agent_patch_rbac=false` and
`retain_sre_agent_thread_verification=true`. This removes trigger write and
patch action authorization while preserving only agent-scoped thread read.
Keep the agent endpoint available until persisted threads reach a terminal
reconciliation, then separately set
`retain_sre_agent_thread_verification=false`.
Do not delete or rewrite the trigger thread, execution attempt, approval,
audit record, or evidence. Trigger disablement is a separate human action only
if containment requires it.

Acceptance evidence is the approved canonical hash, sanitized trigger/agent/
RBAC/secret captures, zero-unrelated-change saved-plan JSON, API revision and
environment diff, exact canary envelope, 202 response metadata without the
secret URL, thread ID/status history, refreshed patch reconciliation, and
rollback proof. Until all evidence exists, the repository is source-ready but
not live-authorized.

## Official references

- [Azure SRE Agent HTTP triggers](https://learn.microsoft.com/azure/sre-agent/http-triggers)
- [Create an HTTP trigger](https://learn.microsoft.com/azure/sre-agent/create-http-trigger)
- [Azure SRE Agent API reference](https://learn.microsoft.com/azure/sre-agent/api-reference)
- [Azure SRE Agent run modes](https://learn.microsoft.com/azure/sre-agent/run-modes)
- [Azure VM installPatches](https://learn.microsoft.com/rest/api/compute/virtual-machines/install-patches?view=rest-compute-2024-07-01)
- [Arc machine installPatches](https://learn.microsoft.com/rest/api/hybridcompute/machines/install-patches?view=rest-hybridcompute-2024-07-10)
- [Microsoft.App RBAC permissions](https://learn.microsoft.com/azure/role-based-access-control/permissions/compute#microsoftapp)
- [Container Apps Key Vault secret references](https://learn.microsoft.com/azure/container-apps/manage-secrets#reference-secret-from-key-vault)
