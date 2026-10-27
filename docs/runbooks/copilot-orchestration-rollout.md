# Operations Copilot Orchestration Rollout Runbook

**Plan:** 11-12 · **Owner:** Operations Copilot on-call · **Scope:** introducing the
canonical `OrchestrationService` behind a staged, reversible rollout.

This runbook is the operator procedure for moving the Operations Copilot from the
degraded Phase 10 baseline onto the governed canonical orchestrator **without a
big-bang break or a destructive thread/ledger migration**. Every stage is gated
by the predetermined absolute thresholds in
`tests/fixtures/copilot_release_thresholds.v1.json` and measured by
`scripts/evaluate_agents.py` against `tests/fixtures/copilot_evaluation_cases.v1.json`.

The rollout is controlled by two Terraform inputs on the API container app
(`infra/terraform/container_apps.tf`):

| Input | Meaning |
|---|---|
| `copilot_rollout_mode` | `compatibility` → `shadow` → bounded `canary` → `default` |
| `copilot_canary_percentage` | reviewed canonical traffic share from 1 through 10 in `canary`; effective value is 100 in `default` |

These project to the running revision as `AIOPS_COPILOT_ROLLOUT_MODE`,
`AIOPS_COPILOT_CANARY_PERCENTAGE`, and the retained rollback target
`AIOPS_COPILOT_ROLLBACK_MODE` (always `compatibility`). The runtime orchestrator
selection (`agent_orchestration_mode`: `maf` / `deterministic` / `canonical`) is
orthogonal and unchanged; the **legacy `deterministic` page-anchored planners are
retained for rollback throughout Phase 11 and are not deleted by this plan.**

Runtime request selection is fail closed:

- missing or invalid rollout mode serves `compatibility`;
- `shadow` keeps the compatibility response path selected;
- `canary` uses a stable principal-derived bucket;
- a missing stable key or a percentage outside 1 through 10 is an error, never
  a compatibility-shaped success;
- `default` requires an effective percentage of 100;
- an invalid `AIOPS_COPILOT_ROLLBACK_MODE` also serves `compatibility`.

## Code-bound rollout authorization retired

The packaged canary/default authorization manifests and reviewed-tree runtime gate
have been retired. Unified Deployment is now the sole writer lane for merge,
build, and deployment coordination, and it is responsible for preventing image,
source, traffic, and provider drift before changing live traffic.

Runtime behavior still fails closed for malformed rollout settings:

1. `compatibility` and `shadow` serve no canonical default traffic.
2. `canary` requires a stable principal key and an effective percentage from 1
   through 10. The canary bucket remains deterministic per principal.
3. `default` requires an effective percentage of 100 and enables canonical
   execution for every principal.
4. `AIOPS_COPILOT_ROLLBACK_MODE` must remain `compatibility`; any other value
   selects compatibility.

Builds still bake `AIOPS_SOURCE_REVISION` into `/app/build-metadata.json`, API
images are still recorded by immutable `sha256:` digest, and `deploy.sh` still
verifies that the active healthy API revision is running the expected digest,
rollout mode, and effective percentage. The removed pieces are the manifest
SHA-256 environment variables, reviewed-tree recomputation, manifest-bound
provider identity checks, and the separate `--default-promotion` image path.
Use `build-and-push.sh --api-authorization-release --deploy` when updating only
the API image; default traffic promotion is now a normal unified deployment
traffic change after the unified session has completed its source review,
validation, and canary evidence review.

## Page Insights provenance during compatibility rollout

The canonical endpoint can return a successful Foundry answer while retaining
`policy_status: fallback` and `fallback_reason: compatibility_rollout`. This is
a rollout-path label, not proof that model narration failed. Page Insights reads
`synthesis.compatibility_answer` when `synthesis.status` is `compatibility`.
It labels the narration as LLM only when the server reports nonempty text,
agent name, pinned agent version, a non-deterministic model, and `grounded: true`;
the panel also displays that provenance. Canonical synthesized narration requires
`synthesis.mode: foundry`.
The follow-up drawer and dedicated investigation surfaces use the same retained
answer validation, so opening a follow-up does not discard a successful answer
or claim its narrator is unavailable merely because rollout stays compatible.

Empty or unavailable governed tools can instead produce a deterministic
status-only answer (`model: deterministic`). Such answers remain visibly
deterministic, not LLM successes. Repairing the display does not restore missing
provider data, qualify Exposure traversal, or authorize a rollout-mode change.

Incident and observability scenario summaries are deliberately deterministic:
the retained investigation path builds their summaries before selecting a
Foundry narrator. A deterministic answer alone therefore does not establish
that a narration provider failed or was unavailable. Inspect response details
for an actual failure; keep source coverage and narration provenance separate.
Partial governed results retain `partial` turn status, including when another
source is empty, denied or unavailable; their per-source statuses and warnings
remain intact rather than turning a partial turn into an access denial.

On Resource Health, deterministic freeform routing recognizes diagnostic
settings/workload logging policy and alert rules/Action Group references/alert
delivery coverage as the corresponding reviewed observability scenarios.
Typing those scenario questions therefore uses the same governed tool arguments
as the starter buttons, rather than silently retrieving generic incidents.
This does not extend page grants, establish complete coverage, or qualify Foundry
execution; generic incident and utilization questions retain their existing route.

Network uses the contextual endpoint and reports `synthesis.mode` in current
responses; older responses can report `synthesis_mode` at the top level.
Topology Insights accepts either Foundry marker, but any explicit deterministic
mode, including a rejected executive synthesis, prevents an LLM label.
For a live audit, inspect the actual authenticated browser response and rendered
panel together. HTTP 200 alone, a specialist name, or replayed test fixtures
does not establish a successful live LLM answer.

CVE detail Insights must also preserve subject identity: a generic executive
question without a hint is bound to the already-validated `cve:*` page ID using
the existing `cve_detail` read. Never substitute a global exposure list or a
different CVE for missing enrichment. Live acceptance checks identifiers in the
actual narration, not only HTTP status and model provenance.
All page-bound drawers retain the canonical snapshot, scope, reviewed hints and
exact thread revision for starter and typed follow-ups. A question-only legacy
request is used only when there is no page snapshot. Missing or deferred sources
remain explicit; retaining page context does not expand any tool or intent grant.
Inventory snapshots remain untrusted selectors: the server re-queries authorized
inventory, and browser resource types are not promoted into explicit tool arguments.

### Native Governance, Identity and FinOps Insights

These three page mappings use `governance_summary`, `identity_summary` and
`finops_summary`, respectively. Each accepts no caller-supplied arguments and
uses `ApiContext.governance_snapshot(effective_scope, require_generation=True)`,
the same scoped, generation-pinned connection evidence used by the REST pages.
The engine projections are shared with REST, rather than importing router
handlers or interpreting a page title/question as a business-service identifier.

The manifest grants these native reads to the corresponding specialists.
Other Governance pages retain their existing reviewed semantic grants; the
legacy MCP consumer's allowlist and twelve-specialist portfolio are unchanged.
Explicitly selected entities retain their existing subject-specific tools;
an estate summary is not a substitute for a selected resource's risk or owner.
Direct visible observations on these three estate pages are not implicit
operator selections. Their page-scoped follow-up drawers use the same canonical
snapshot/request path as Insights, including exact server thread revisions.
An unnamed standalone ownership question still requires a subject.
New specialist MCP grants and the Terraform registry are projected from the
same reviewed manifest. Source/package parity does not establish that an older
deployed Foundry specialist version has been republished: verify the actual
consumer's grants before claiming remote MCP parity.

Provider or missing-generation failures return `unavailable`, without fallback
to a broader semantic snapshot. A successful read with no relevant synced rows
returns `empty`. Missing role assignments never become a zero-privilege claim;
missing Cost Management data and mixed currencies retain the FinOps engine's
explicit limitations. Governance summarises observed identity, cost and
onboarding credentials, not policy compliance, approval or completed reviews.
Bounded principal-risk, Advisor and waste projections provide affected identifiers;
raw role assignments, credential records and secret references are not sent
to the model. Payload list bounds disclose any truncation while summary counts
continue to cover the full authorized snapshot.

### Live incident and remediation scope parity

Incident and remediation tools use the existing live adapters for an explicit
subscription, an active selected connection, or an unrestricted selection over
active onboarded subscriptions, just like their REST pages. Combined subscription
and connection selections intersect; disabled/unmatched connections never trigger
a broader managed-snapshot fallback. The complete effective scope still filters
returned rows before narration. A metadata-only scope without subscription or
connection selectors retains the existing snapshot path rather than querying all
live subscriptions.

Registry and live-provider construction failures are `unavailable`, not evidence
that no records exist. This routing repair does not enable deferred semantic
hydration, change the reviewed tool portfolio or Foundry versions, publish
remediation catalogs, or manufacture incidents. A successful live read can still
be empty and must remain an explicitly deterministic status in that case.

## Source the non-secret provider environment

Terraform output `copilot_provider_environment` is the authority for the
Foundry endpoint, existing Operations MCP endpoint/audience/connection
contract, candidate mapping path, AI Search connection, rollout settings,
source revision, candidate artifact/binding digests, and observable API image
digest. Generate a local source file without copying values by hand:

```sh
python3 scripts/export_copilot_provider_env.py \
  --terraform-dir infra/terraform \
  --output /secure/path/copilot-provider.env
. /secure/path/copilot-provider.env
```

The exporter reads local Terraform state only, emits an allowlisted set of
non-secret values, writes mode `0600`, and never emits tenant/client
credentials or bearer tokens. Missing outputs or an absent candidate artifact
return `BLOCKED`; malformed endpoints, rollout settings, candidate identities,
or connection IDs fail. Credentials must still come from the approved secret
mechanism. This output no longer carries canary/default authorization manifest
SHA-256 values because the code-bound rollout authorization gate is retired.

## Fabric IQ grounding through Fabric Data Agent

The browser is a thin client for Copilot investigations. It sends the question,
authorized scope, opaque thread/session continuity, and optional selected
identifiers as untrusted hints. It does **not** send resource inventories,
findings, topology, or ontology snapshots as operational truth. Operations
Copilot resolves current context on the server through its governed tools.

Fabric IQ remains the semantic authority for ontology, relationships, business
meaning, and immutable generation lineage. The Fabric Data Agent is the
read-only natural-language grounding provider over that governed semantic
model; it does not replace Operations Copilot or the specialist agents.
Specialists continue to use the shared `fabric_iq_relationships`,
`fabric_iq_topology`, and `fabric_iq_policy_context` contracts. The provider
binding can be enabled with:

| Environment variable | Purpose |
|---|---|
| `AIOPS_ENABLE_FABRIC_IQ=true` | Enables the governed Fabric IQ tool adapter. |
| `AIOPS_ENABLE_FABRIC_DATA_AGENT_GROUNDING=true` | Binds Fabric IQ tool reads to the Fabric Data Agent. |
| `FABRIC_GOLD_GROUNDING_AGENT_ID` | Required Fabric Data Agent item ID. |
| `FABRIC_GOLD_GROUNDING_TOOL_NAME` | Optional MCP tool name; defaults to `DataAgent_AI_Ops_Data_Agent`. |

Each request includes the server-resolved authorized scope and immutable
ontology generation. Structured findings must cite governed Gold rows, pass
scope validation, and return truthful `fabric-data-agent` provenance. Missing
generation, degraded findings, scope-invalid findings, transport errors, and
malformed responses fail closed; the transport permits one bounded 20-second
attempt.

The current token is acquired from the runtime credential. That is a service
identity, not evidence of end-user delegation. Production activation therefore
requires application-side scope filtering and should use Fabric RLS/OBO when
supported. The Data Agent has no authority to mutate resources, approve
remediation, accept ontology proposals, publish generations, or perform
rollback. Those remain deterministic, audited application workflows.

The candidate artifact binds all twelve specialist agent names and immutable
provider version IDs to the existing full `operations-mcp` Foundry
project-connection resource ID. Live parity lists the project's actual
connections read-only and checks that every pinned agent version uses that
exact ID. A connection display name is not accepted as an ID. This gate does
not authorize, build, validate, or deploy either the `mcp-server` or
`azure-mcp` container image.

## Candidate catalog transport and semantic authorization boundary

The raw `foundry_specialist_candidate_catalog_artifact_sha256` remains a
transport/file-integrity check only. It proves the runtime parsed the exact
bytes supplied by Terraform, but the semantic binding does **not** include
that raw digest: those bytes contain `source_revision`, `generated_at`, and
per-agent/coordinator validation timestamps, so binding the raw digest creates
an impossible source → artifact → source cycle.

The release process instead records
`sha256-canonical-json-candidate-v1`. Compute both values offline with:

```sh
PYTHONPATH=src python -m operations.foundry_candidate_catalog \
  --artifact /secure/path/foundry-specialist-candidates.v1.json
```

The semantic projection first applies the existing strict Pydantic candidate
contract, rejects missing/extra agents, undeclared fields, duplicate grants,
duplicate provider identities, mutation authority, non-passing validation, and
invalid coordinator state, then excludes only:

- top-level `source_revision`;
- top-level `generated_at`;
- each `agents.<id>.validation.validated_at`;
- `coordinator.validation.validated_at`.

Every other parsed field remains bound, including release/contract/manifest
identity, project resource ID and endpoint host, all twelve agent identities
and provider/candidate versions, model deployments and contract models, prompt
digests, Operations MCP grants, AI Search connection/index policy, read-only
and mutation policy, scope/citation/timeout/fallback contracts, publication and
non-timestamp validation results, and coordinator identity/status. Mapping keys
are canonical JSON key order. Operations MCP grant lists alone are sorted
because the existing validator defines those grants as an unordered set; no
other list is reordered.

The digest input is UTF-8 JSON with sorted mapping keys, no insignificant
whitespace, and the exact envelope
`{"algorithm":"sha256-canonical-json-candidate-v1","candidate":<projection>}`.
Strings and non-grant lists retain the strict parser's values and order.

Set `foundry_specialist_candidate_binding_sha256` to the reported semantic
digest. Terraform separately verifies the raw artifact SHA and projects both
values. Runtime re-verifies the raw bytes, parses the strict artifact,
independently compares its `source_revision` with the baked image revision,
recomputes the semantic digest, and compares it with the Terraform-projected
binding.

The raw digest still does not identify who produced the bytes.
Candidate-catalog authenticity depends on the compensating deployment boundary:
Azure Container Apps deployment RBAC plus sole-writer release control must
ensure that only the reviewed release path can set the artifact and both
digests together.

Broad promotion requires that compensating control to remain enforced and
auditable. If deployment ownership cannot remain sole-writer, promotion must
stay blocked until the catalog uses an identity-bound signature or HMAC whose
verification key is controlled independently from the artifact writer.

### Current external onboarding blocker

The reported live inventory contains only one governed connection named
`demo`. That is not evidence for either required connection and must not be
copied into both slots. Provider promotion therefore remains **BLOCKED** until
an authorized operator supplies all of the following evidence from one target
Foundry project:

1. Full resource ID and read-only connection payload for the Terraform-created
   `operations-mcp` project connection, with target equal to the exact exported
   `OPERATIONS_MCP_SERVER_URL` and audience equal to exported
   `MCP_APIM_AUDIENCE`.
2. A candidate artifact created by `create-foundry-agent.sh` containing the
   exact Operations MCP connection ID plus all twelve agent identities and the shared
   coordinator's service-returned immutable provider version IDs.
3. A read-only `validate_specialist_parity.py --live` result proving that
   connection exists and every pinned version binds to the expected connection
   ID and exact read-only grants.

Do not invent a second connection, rewrite `demo`, synthesize provider IDs, or
mark the live gate passed from Terraform declarations alone.

## Order of operations (create → validate → switch → observe → promote)

Each promotion is an additive revision deploy. The previous revision is retained
so a rollback is a revision/mode switch, never a rebuild.

### Stage 0 — Preconditions

1. Offline parity must pass: `.venv/bin/python scripts/validate_specialist_parity.py --offline`.
2. Source the Terraform-owned non-secret provider environment as shown above.
3. Live parity must pass (read-only) before any Foundry promotion:
   `bash infra/scripts/validate-runtime-e2e.sh` (a `blocked` live gate holds, it never counts as a pass).
4. The full corpus must be runnable against the candidate build.

### Stage 1 — `compatibility`

- **Deploy:** `terraform apply -var 'copilot_rollout_mode=compatibility'` (default).
- **Behaviour:** serve the legacy projections to clients while recording canonical
  decisions for comparison. No client sees canonical output yet.
- **Validate:** offline + live parity pass; v1 and v2 reads both succeed.
- **Rollback:** none required — this is the safe baseline.

### Stage 2 — `shadow`

- **Deploy:** `terraform apply -var 'copilot_rollout_mode=shadow'`.
- **Behaviour:** for each turn, compute the canonical decision alongside the
  fallback and record the comparison. **Shadow reuses the already-collected
  deterministic inputs and never double-runs external tools or models, and never
  exposes a mutation** (per D-02, D-09, D-10). Each response reports
  `data.rollout.canonical_preview_external_io.tool_calls` and
  `data.rollout.canonical_preview_external_io.model_or_narration_calls`; both
  must be exactly `0`.
- **Validate:** run the corpus; confirm zero deterministic safety/citation-integrity
  violations and that shadow adds no external tool/model calls.
- **Rollback:** `terraform apply -var 'copilot_rollout_mode=compatibility'`.

### Stage 3 — `canary`

- **Deploy:** record the requested `copilot_rollout_mode=canary` and
  `copilot_canary_percentage` (1–10) in the normal Terraform inputs, then run
  `AIOPS_API_AUTHORIZATION_RELEASE=1 ./infra/scripts/deploy.sh apply
  -target=azurerm_container_app.api`. Do not run a full apply or add another
  target; the wrapper rejects both.
- **Behaviour:** the canonical orchestrator becomes the default for the bounded
  traffic share only. The rollout logic permits no value above 10.
- **Immutable release inputs:** set the exact reviewed specialist release and
  source revision, supply the reviewed candidate/promotion artifacts, set the
  raw candidate transport SHA-256 and independently reviewed semantic binding
  SHA-256, and set `api_image_digest` to the pushed immutable digest. A mutable
  tag, absent digest, wrong release, unpinned identity, or mismatched build
  revision fails unified deployment validation or runtime rollout checks. Use
  `build-and-push.sh <tag> --api-authorization-release --deploy`; this path
  builds, verifies, records, and deploys only the API image. It never builds,
  pushes, verifies, or changes `mcp-server`, `azure-mcp`, or web image
  references. The script resolves `aiops-api:<tag>` back to its ACR manifest,
  verifies the returned repository, tag, and lowercase `sha256:` digest, then
  atomically records only `api_image_digest` and
  `deployment_source_revision` in `terraform.tfvars` before Terraform apply.
  The wrapper performs two API-only applies: first the digest-pinned candidate
  in compatibility mode with zero canonical canary, then—only after the active
  healthy revision reports the exact digest/mode/percentage—the originally
  requested canary. It validates the final active revision too. Any failure
  automatically restores and verifies compatibility/0 before returning
  failure.
- **Automatic hold:** if any applicable predetermined threshold fails
  (`scripts/evaluate_agents.py … evaluate_gates`), the canary **holds
  automatically** — a deterministic safety or citation-integrity failure HOLDs the
  whole build; a model-quality, provider-parity, latency, reliability, or spend
  failure HOLDs OR DISABLES only the affected optional mode while the governed
  deterministic fallback stays available.
- **Claim support:** narrated groundedness is measured only from the controlled
  `evaluation.claim_support` result produced by a deterministic response path or
  proxy evaluator. The object must use version `1`, identify its method as
  `deterministic_response` or `proxy_evaluator`, and provide one ordered
  `{claim_index, supported}` boolean record for every material claim. Missing or
  malformed support evidence holds narrated-answer promotion. Citation validity
  and material-claim citation coverage remain separate gates; attaching a valid
  citation does not establish that the cited evidence entails a claim.
- **Validate:** completed-turn rate ≥ 0.98, timeout rate ≤ 0.01, latency and spend
  ceilings met for the served share.
- **Evaluate the immutable revision once:**

  ```sh
  AZURE_SUBSCRIPTION_ID="<subscription-id>"
  API_APP="<api-container-app-name>"
  AZURE_RESOURCE_GROUP="<resource-group-name>"
  CANDIDATE_REVISION="$(az containerapp revision list \
    --name "$API_APP" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query 'sort_by([?properties.active], &properties.createdTime)[-1].name' \
    --output tsv)"
  CANDIDATE_FQDN="$(az containerapp revision show \
    --name "$API_APP" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --revision "$CANDIDATE_REVISION" \
    --query properties.fqdn \
    --output tsv)"
  API_URL="https://$CANDIDATE_FQDN"
  RUNTIME_E2E_RESULT="$(mktemp)"
  trap 'rm -f "$RUNTIME_E2E_RESULT"' EXIT
  VALIDATION_EVIDENCE_JSON="/secure/path/copilot-validation-evidence.json"
  COPILOT_DEPLOYED_REVISION="$CANDIDATE_REVISION" \
  COPILOT_ROLLOUT_MODE=canary \
  AZURE_SUBSCRIPTION_ID="$AZURE_SUBSCRIPTION_ID" \
  AZURE_RESOURCE_GROUP="$AZURE_RESOURCE_GROUP" \
  API_APP="$API_APP" \
  API_URL="$API_URL" \
    bash infra/scripts/validate-runtime-e2e.sh >"$RUNTIME_E2E_RESULT"

  BASELINE_TMP="/secure/path/copilot-orchestration-baseline.json"
  python3 scripts/evaluate_agents.py \
    --api "$API_URL" \
    --resource "$AIOPS_ENTRA_API_AUDIENCE" \
    --dataset tests/fixtures/copilot_evaluation_cases.v1.json \
    --thresholds tests/fixtures/copilot_release_thresholds.v1.json \
    --revision "$CANDIDATE_REVISION" \
    --provider foundry=available \
    --provider operations_mcp=available \
    --provider azure_mcp=available \
    --runtime-e2e-result "$RUNTIME_E2E_RESULT" \
    --validation-evidence-out "$VALIDATION_EVIDENCE_JSON" \
    --out "$BASELINE_TMP"
  python3 scripts/evaluate_agents.py \
    --validate-artifact "$BASELINE_TMP" \
    --dataset tests/fixtures/copilot_evaluation_cases.v1.json \
    --thresholds tests/fixtures/copilot_release_thresholds.v1.json
  ```

  This is one corpus run: the evaluator derives every deterministic gate from
  that run's controlled per-case evidence. The runtime result contributes only
  the exact revision, scoped-topology check, runtime readiness, and offline/live
  parity facts it actually measured. Parity cannot turn an unrelated mutation,
  snapshot, citation, scope, tool, or route gate true. The evaluator rejects
  missing/extra/non-boolean runtime checks and revision mismatches, then
  atomically replaces `VALIDATION_EVIDENCE_JSON` only after deriving the full
  gate set. Do not hand-author that file. A missing or unproven case field
  records a false gate and HOLD; a failed or incomplete runtime result produces
  no replacement evidence file. `validate-runtime-e2e.sh` also rejects shared
  ingress: `API_URL` must be the revision-specific FQDN returned for
  `CANDIDATE_REVISION`, so traffic cannot be served by the prior active revision.
  Exit `0` is `PROMOTE`; exit `3` is `HOLD` or
  `HOLD_OR_DISABLE_MODE`. Copy the temporary artifact into
  `.planning/eval/copilot-orchestration-baseline.json` only after the deployed
  revision and artifact have both been reviewed.
- **Rollback:** `terraform apply -var 'copilot_rollout_mode=shadow'` (or
  `compatibility`) — the prior revision and threads are untouched.

### Stage 4 — `default`

Default rollout is a unified deployment promotion after the unified session has
reviewed the source, validated the candidate image, checked canary evidence, and
confirmed rollback readiness. It no longer requires a separate packaged default
authorization manifest or a `--default-promotion` image. Deploy by setting
`copilot_rollout_mode=default` with the exact immutable API image digest and
`deployment_source_revision` selected by the unified release. Runtime then serves
canonical default for all principals and still reports malformed percentage or
rollback-mode settings as hard rollout errors before canonical execution.

## Rollback (any stage)

```sh
# Reverse one stage at a time; each is additive and non-destructive.
terraform apply -var 'copilot_rollout_mode=<previous-stage>'
# Or restore the retained previous revision:
az containerapp revision list -n <api-app> -g <rg> -o table
az containerapp ingress traffic set -n <api-app> -g <rg> --revision-weight <prior-revision>=100
```

Rollback restores the prior revision/mode and the retained `compatibility`
fallback. Threads and ledgers are **never** rewritten; v1 and v2 reads both keep
working.

## Legacy retirement (separately reviewed, out of scope for this plan)

The legacy page-anchored planners and v1 reads are **retained through Phase 11**.
Deletion is a **separate, separately reviewed post-promotion change** that may only
proceed after **zero v1 requests for 30 consecutive days**. This plan does not
delete any legacy planner and does not schedule that retirement.
## Replacement-subscription infrastructure checks

After recreating the subscription, model deployment alone does not restore
the Agents page. Preserve its validated candidate/promotion contract:

- Set `enable_apim` in the environment's Terraform inputs and review a saved
  plan for the gateway, native Operations/Azure MCP routes and Entra policies.
- Set `enable_foundry_role_assignments` when an Owner deployer must restore
  project-scoped runtime and knowledge-search grants without enabling
  unrelated subscription-wide execution permissions.
  Named prompt-agent calls also require agent-definition reads and OpenAI
  Responses access. Terraform's `apps_foundry_prompt_runtime` custom role
  grants only project metadata `accounts/projects/read`,
  `AIServices/agents/read`, `AIServices/deployments/read` and
  `OpenAI/responses/read`/`write`,
  assigned to the API identity at the project. It does not grant agent
  mutation, model deployment, key access or role management. Verify a real
  pinned call from that identity; built-in runtime-role presence alone is
  not sufficient.
  The separate `apps_foundry_response_runtime` custom role grants only
  account metadata `accounts/read` and `OpenAI/responses/read`/`write` on the
  Foundry account, because account-level
  OpenAI authorization does not inherit a project assignment. It grants no
  agent-definition read or mutation, response deletion or management writes.
  Exact account, project and deployment metadata reads cover the documented account
  Reader/project-access prerequisites without a wildcard Reader grant.
  Its Responses access covers the account, not just one project. Review this
  boundary before enabling the scoped restoration gate; require actual API
  identity invocation before activating candidates or promoting traffic.
- Set `enable_mcp_role_assignments` for the MCP identities' read-only Azure
  and vault grants. Terraform adds the Foundry project identity to API gateway
  grants as a subscription-scoped reader; existing browser grants are retained.
- Restore governed knowledge search before specialist candidate publication.
  For runtimes supporting dedicated consumer endpoints, opt in through
  `foundry_use_agent_endpoints` (`FOUNDRY_USE_AGENT_ENDPOINTS=true`).
  Requests use `/agents/{name}/endpoint/protocols/openai/responses` with API
  version `2025-11-15-preview` and still send the exact immutable
  `agent_reference.version`. Missing versions and `@latest` fail closed; there is no
  direct-model or project-route fallback. The flag defaults off to preserve
  existing deployments. Verify both a real pinned invocation and rejection
  of a nonexistent version from the actual API identity before activation.
  This consumer route uses the existing endpoint-interaction grant instead
  of adding agent-management permissions for the legacy project proxy.
  See [the Foundry endpoint model](https://learn.microsoft.com/azure/foundry/agents/how-to/migrate-agent-applications).
  Empty rejected-version history in a restored project is compared by its
  JSON value, not Terraform's inferred empty-list type. An absent, malformed
  or different history still fails the coordinator activation gate.
  Before API traffic cutover, `operations_mcp_api_revision_suffix` can point
  the protected Operations MCP relay at an accepted zero-traffic revision of
  the same API app. Empty restores the main API URL. Only a revision suffix
  is accepted, never an arbitrary host or URL. Preserve JWT validation,
  gateway assertions and claim stripping; validate protected initialize,
  tools/list and a real read before specialist parity. APIM resolves validated
  user principals in the same preferred_username/upn/oid order as direct API
  authentication; managed identities continue to use oid.
  Coordinator publication and its live validator both support
  `FOUNDRY_AUTH_MODE=azure_cli` without storing client credentials.
  `foundry_coordinator_rejected_versions` preserves the historical default
  `["1", "2", "3", "4"]`; set it explicitly to `[]` only for a newly created
  project with no unusable coordinator history. The live validator rejects
  listed versions before provider I/O, and its digest-bound validation
  payload must carry the same reviewed list before Terraform can activate it.
  Publish candidates with the existing Terraform provisioner, validate actual
  provider version IDs, then use a separate reviewed activation plan.
- With an Azure CLI deployer, leave Terraform `client_id` and `client_secret`
  empty. All Foundry/index provisioners select `azure_cli` authentication and
  use the current CLI identity; their scoped deployer grants must name that
  identity. Configured service principals retain `client_credentials` mode.

Keep deterministic execution and the existing Network default until the
candidate tools and agent invocation pass live checks. Legacy agent-name
environment variables are not proof of a deployed or activated agent. A
Foundry permission denial must be resolved and checked on the data plane;
an ARM role assignment appearing in a list is not sufficient evidence.

## Terraform API revision staging

Before changing an existing API image or durable-storage configuration, set
`api_traffic_revision` to the full, healthy revision name currently serving
traffic. Review the saved plan: that revision must retain 100% traffic while
the new template creates a zero-traffic candidate. Preserve existing secrets,
browser grants, CPU/memory and unrelated workloads. Verify the candidate
through its revision-specific endpoint, including authenticated inventory
reads. Only after acceptance, generate and review a separate Terraform plan
setting `api_traffic_revision = ""` to promote latest. Roll back by pinning the
previous healthy revision through Terraform; do not assume the old revision
remains valid after incompatible storage changes.

For an existing Contributor-bootstrap deployment, import both live cursor keys
into their `random_password.exposure_cursor` state addresses before applying.
Never print the import values or commit them. Imported length/special metadata
is retained to prevent an incidental credential rotation during restoration;
new keys still use 64 characters without special characters. Intentional
rotation requires an explicitly reviewed `-replace` plan and matching key IDs.
