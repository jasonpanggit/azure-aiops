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

## Order of operations (create → validate → switch → observe → promote)

Each promotion is an additive revision deploy. The previous revision is retained
so a rollback is a revision/mode switch, never a rebuild.

### Stage 0 — Preconditions

1. Offline parity must pass: `.venv/bin/python scripts/validate_specialist_parity.py --offline`.
2. Live parity must pass (read-only) before any Foundry promotion:
   `bash infra/scripts/validate-runtime-e2e.sh` (a `blocked` live gate holds, it never counts as a pass).
3. The full corpus must be runnable against the candidate build.

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
  exposes a mutation** (per D-02, D-09, D-10).
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
- **Validate:** completed-turn rate ≥ 0.98, timeout rate ≤ 0.01, latency and spend
  ceilings met for the served share.
- **Evaluate the immutable revision once:**

  ```sh
  API_APP="<api-container-app-name>"
  AZURE_RESOURCE_GROUP="<resource-group-name>"
  CANDIDATE_REVISION="$(az containerapp revision list \
    --name "$API_APP" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query '[?properties.active].name | [0]' \
    --output tsv)"
  RUNTIME_E2E_RESULT="$(mktemp)"
  trap 'rm -f "$RUNTIME_E2E_RESULT"' EXIT
  VALIDATION_EVIDENCE_JSON="/secure/path/copilot-validation-evidence.json"
  COPILOT_DEPLOYED_REVISION="$CANDIDATE_REVISION" \
  COPILOT_ROLLOUT_MODE=canary \
    bash infra/scripts/validate-runtime-e2e.sh >"$RUNTIME_E2E_RESULT"
  python3 scripts/evaluate_agents.py \
    --revision "$CANDIDATE_REVISION" \
    --runtime-e2e-result "$RUNTIME_E2E_RESULT" \
    --validation-evidence-out "$VALIDATION_EVIDENCE_JSON" \
    --thresholds tests/fixtures/copilot_release_thresholds.v1.json

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
    --validation-evidence "$VALIDATION_EVIDENCE_JSON" \
    --out "$BASELINE_TMP"
  python3 scripts/evaluate_agents.py \
    --validate-artifact "$BASELINE_TMP" \
    --dataset tests/fixtures/copilot_evaluation_cases.v1.json \
    --thresholds tests/fixtures/copilot_release_thresholds.v1.json
  ```

  The translator performs no live calls, rejects missing/extra/non-boolean
  gates and revision mismatches, and atomically replaces its output only after
  validation. `COPILOT_DEPLOYED_REVISION` is mandatory, so a missing revision
  or malformed threshold file stops the runtime gate before any provider call.
  Do not hand-author `VALIDATION_EVIDENCE_JSON`. A blocked live parity result
  writes false gate evidence and exits with the evaluator's hold status; a
  failed or incomplete runtime result produces no replacement evidence file.
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
