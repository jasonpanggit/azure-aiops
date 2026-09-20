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
| `copilot_rollout_mode` | `compatibility` → `shadow` → `canary` → `default` |
| `copilot_canary_percentage` | bounded canonical-default traffic share while in `canary` |

These project to the running revision as `AIOPS_COPILOT_ROLLOUT_MODE`,
`AIOPS_COPILOT_CANARY_PERCENTAGE`, and the retained rollback target
`AIOPS_COPILOT_ROLLBACK_MODE` (always `compatibility`). The runtime orchestrator
selection (`agent_orchestration_mode`: `maf` / `deterministic` / `canonical`) is
orthogonal and unchanged; the **legacy `deterministic` page-anchored planners are
retained for rollback throughout Phase 11 and are not deleted by this plan.**

Runtime request selection is fail closed:

- missing or invalid rollout mode serves `compatibility`;
- `shadow` keeps the compatibility response path selected;
- `canary` uses a stable principal-derived bucket and refuses canonical routing
  when the percentage or stable key is missing or invalid;
- `default` selects the canonical service unless the explicit
  `AIOPS_AGENT_ORCHESTRATION_MODE=deterministic` emergency rollback is active;
- an invalid `AIOPS_COPILOT_ROLLBACK_MODE` also serves `compatibility`.

## Source the non-secret provider environment

Terraform output `copilot_provider_environment` is the authority for the
Foundry endpoint, both exact APIM MCP URLs, APIM audience, candidate mapping
path, both Foundry project-connection resource IDs, and all three rollout
settings. Generate a local source file without copying values by hand:

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
provider version IDs to two **distinct full Foundry project-connection resource
IDs** (`operations-mcp` and `azure-mcp`). Live parity lists the project's actual
connections read-only, requires both IDs to exist, and checks that every pinned
agent version uses those exact IDs. A connection display name is not accepted
as an ID.

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
2. Full, distinct resource ID and read-only connection payload for the
   Terraform-created `azure-mcp` project connection, with target equal to the
   exact exported `AZURE_MCP_SERVER_URL` and the same governed audience.
3. A candidate artifact created by `create-foundry-agent.sh` containing the
   exact two connection IDs plus all twelve agent identities and the shared
   coordinator's service-returned immutable provider version IDs.
4. A read-only `validate_specialist_parity.py --live` result proving those
   connections exist and every pinned version binds to the expected connection
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

- **Deploy:** `terraform apply -var 'copilot_rollout_mode=canary' -var 'copilot_canary_percentage=10'`.
- **Behaviour:** the canonical orchestrator becomes the default for the bounded
  traffic share only. Raise the percentage in reviewed increments (e.g. 10 → 25 → 50).
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

- **Deploy:** `terraform apply -var 'copilot_rollout_mode=default'`.
- **Behaviour:** canonical default for all traffic; the deterministic fallback
  remains wired behind the rollback seam.
- **Promote Foundry versions only when live parity is green** and every applicable
  threshold row passes (`PROMOTE`). Any model threshold miss is recorded as a
  `HOLD` in `.planning/eval/copilot-orchestration-baseline.json`, never a fabricated pass.
- **Rollback:** `terraform apply -var 'copilot_rollout_mode=canary'` /
  `shadow` / `compatibility`, or redeploy the retained previous revision. No thread
  or ledger is rewritten.

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
