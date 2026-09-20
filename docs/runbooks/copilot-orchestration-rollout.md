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
| `copilot_rollout_mode` | `compatibility` → `shadow` → bounded `canary`; `default` is denied |
| `copilot_canary_percentage` | reviewed canonical traffic share from 1 through 10 while in `canary` |

These project to the running revision as `AIOPS_COPILOT_ROLLOUT_MODE`,
`AIOPS_COPILOT_CANARY_PERCENTAGE`, and the retained rollback target
`AIOPS_COPILOT_ROLLBACK_MODE` (always `compatibility`). The runtime orchestrator
selection (`agent_orchestration_mode`: `maf` / `deterministic` / `canonical`) is
orthogonal and unchanged; the **legacy `deterministic` page-anchored planners are
retained for rollback throughout Phase 11 and are not deleted by this plan.**

Runtime request selection is fail closed:

- missing or invalid rollout mode serves `compatibility`;
- `shadow` keeps the compatibility response path selected;
- `canary` uses a stable principal-derived bucket only after the packaged
  authorization, build metadata, target, evidence, and provider pins validate;
- a missing stable key or a percentage outside 1 through 10 is an error, never
  a compatibility-shaped success;
- `default` is hard-denied regardless of environment flags or manifest content;
- an invalid `AIOPS_COPILOT_ROLLBACK_MODE` also serves `compatibility`.

## Code-bound pre-canary authorization

`src/operations/copilot_canary_authorization.v1.json` is the reviewed,
strict-schema authorization record. It rejects undeclared fields and binds the
one allowed canary window to the exact Azure/Foundry target, twelve unordered
specialist identities, coordinator version, candidate/proof digests, and
passing shadow evidence. Its current UTC validity window ends at
`2026-10-04T19:00:00Z`; extending or replacing it requires a separately
reviewed code change.

The manifest's `reviewed_tree` object is the code authorization boundary. Its
fixed `include_roots` cover `.dockerignore`, `Dockerfile`, dependency locks,
both production deploy configuration YAMLs, all packaged files under `src/`
and `skills/`, every separately copied runtime script, the build/deploy
scripts, and the Terraform API-image inputs. The same
roots are pinned in `operations.reviewed_tree.REVIEWED_TREE_ROOTS`; changing
either side fails closed. The exact file set is every regular file recursively
found under those roots, sorted by repository-relative POSIX path.
`__pycache__` entries and `*.pyc` are explicitly excluded as transient compiler
output. The authorization manifest itself
(`src/operations/copilot_canary_authorization.v1.json`) is the sole
`exclude_paths` entry and is always excluded so the digest has no
self-reference. Files outside the fixed roots are not build/runtime inputs and
do not participate.

The `sha256-path-length-content-v1` algorithm starts an empty SHA-256 and, for
each path in lexicographic order, appends exactly
`UTF8(path) + NUL + ASCII(byte_length) + NUL + file_bytes`. Symlinks, missing
files, absolute paths, `..`, duplicates, unsorted paths, a changed fixed set,
or a manifest path in the set are rejected. No newline normalization,
whitespace normalization, filesystem metadata, or environment/build argument
participates in the hash.

`build-and-push.sh` rejects an existing API tag before building or recording a
release, then verifies that digest against the immutable build context
before invoking Docker. Docker independently recomputes it from the packaged
files rather than accepting a digest build argument, and writes both the
recomputed reviewed-tree digest and authorization-manifest SHA-256 to
`/app/build-metadata.json`. Runtime recomputes the packaged tree again and
requires all three tree values (manifest, build metadata, runtime computation)
to match. It additionally requires all of the following before loading Foundry
providers, reporting ready, or permitting canonical external I/O:

1. packaged authorization bytes match the baked SHA-256 and Terraform-projected
   SHA-256;
2. the packaged reviewed tree matches the manifest and baked reviewed-tree
   SHA-256;
3. `AIOPS_SOURCE_REVISION` exactly matches the independently baked source
   revision (a revision value alone cannot authorize different bytes);
4. rollout mode is exactly `canary`, percentage is 1–10, orchestration is
   `maf`, activation source is `validated_promotion`, and rollback remains
   `compatibility`;
5. target, project, candidate/proof/shadow digests, all twelve provider
   identities, and coordinator identity exactly match the reviewed record.

Terraform and `build-and-push.sh --api-authorization-release` still require and
deploy the API by an immutable `sha256:` digest. Authorization releases must use
`AIOPS_API_AUTHORIZATION_RELEASE=1 ./infra/scripts/deploy.sh apply
-target=azurerm_container_app.api`; the wrapper rejects a missing target,
duplicate target, full apply, or any extra/different target. No dependency
target is required. The projected
`AIOPS_API_IMAGE_DIGEST` is observability for deployment and external
validation only: a container environment variable is self-attested and is
therefore never a runtime authorization predicate or proof of the image that
platform is actually running. Before canary traffic, the deployment wrapper
first applies only the API target with rollout mode forced to `compatibility`,
which projects a zero canonical percentage, and validates the active healthy
revision's platform-reported registry digest, mode, and percentage. Only then
does a second explicit API-only apply restore the requested canary values. The
external platform digest is the image root of trust.

The existing Terraform resource uses Container Apps `Single` revision mode, so
this is a compatibility-mode stage rather than a retained zero-traffic
revision: the candidate digest may serve legacy-compatible API traffic while
validation runs, but it cannot serve canonical canary traffic. Terraform inputs
and `terraform.tfvars` are not rewritten; the second apply reuses the operator's
exact requested values. A staging, admission, second-apply, or activation
failure triggers an explicit compatibility apply and verifies mode
`compatibility` with percentage `0`. If Azure prevents that verification, the
script exits nonzero with promotion held and requires immediate operator
intervention; it never reports promotion success.

Raw environment flags cannot create route authority. Any missing, malformed,
expired, premature, inactive, mutable, or mismatched value makes `/ready`
return 503 and causes canonical requests to fail before provider/tool/model
I/O. Compatibility and shadow remain unchanged when their projected canary
percentage is zero. Manifest timestamps must be exact
`YYYY-MM-DDTHH:MM:SSZ` strings; Unix numbers, offsets, fractional seconds,
lowercase separators, and surrounding whitespace are rejected before datetime
parsing.

At the execution boundary, `OrchestrationService.execute` and `execute_turn`
invoke a server-held authorizer with the exact request, selection snapshots,
principal, and principal-derived stable key. Production revalidates the
packaged immutable `ValidatedCanaryAuthorization` and recomputes canary
selection immediately before resolving a provider or invoking a tool.
The production constructor exposes no authorizer injection point; callers
cannot replace the module-held revalidator with a no-op. Caller-constructed
decisions or proof objects are not accepted, preventing direct-call, replay,
and routing-to-execution TOCTOU bypasses. Tests install an explicitly test-only
module fixture rather than importing a production token or passing authority
through the production constructor.

## Source the non-secret provider environment

Terraform output `copilot_provider_environment` is the authority for the
Foundry endpoint, existing Operations MCP endpoint/audience/connection
contract, candidate mapping path, AI Search connection, all three rollout
settings, source revision, authorization-manifest digest, and observable API
image digest. Generate a local source file without copying values by hand:

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
mechanism.

The candidate artifact binds all twelve specialist agent names and immutable
provider version IDs to the existing full `operations-mcp` Foundry
project-connection resource ID. Live parity lists the project's actual
connections read-only and checks that every pinned agent version uses that
exact ID. A connection display name is not accepted as an ID. This gate does
not authorize, build, validate, or deploy either the `mcp-server` or
`azure-mcp` container image.

### Candidate catalog integrity and authenticity boundary

The configured raw-artifact SHA-256 is an integrity and corruption check only:
it proves that the deployed bytes match the separately reviewed digest, but it
does not identify who produced either value. Candidate-catalog authenticity
currently depends on the compensating deployment boundary: Azure Container Apps
deployment RBAC plus sole-writer release control must ensure that only the
reviewed release path can set the artifact and its expected digest together.

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
  traffic share only. This authorization permits no value above 10.
- **Immutable release inputs:** set the exact reviewed specialist release and
  source revision, supply the reviewed candidate/promotion artifacts, and set
  `api_image_digest` to the pushed immutable digest. A mutable tag, absent
  digest, wrong release, unpinned identity, or mismatched build revision fails
  the Terraform precondition or code-bound runtime gate. Use
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

### Stage 4 — `default` (not authorized)

This code-bound prerequisite does not authorize default rollout. Terraform and
runtime both reject `copilot_rollout_mode=default`. A future default rollout
requires separate reviewed authorization and is not implied by a passing
canary.

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
