# Phase 09-10: Microsoft Agent Framework Orchestrator Pivot

**Status:** In progress  
**Decision:** Adopt Microsoft Agent Framework as the forward multi-agent orchestration model.  
**Goal:** Make Operations Copilot the orchestrator for every user turn so operators can ask arbitrary cross-domain questions from any page without switching to a specific specialist page.

## Scope

- Keep the current deterministic orchestration path as an explicit rollback baseline.
- Make MAF the default orchestration boundary; use `AIOPS_AGENT_ORCHESTRATION_MODE=deterministic` only for rollback.
- In MAF mode, select specialists from the operator's question first, not the current page.
- Preserve governed tool access, scope filtering, audit ledgers, fallback behavior, and quality metrics.
- Expose the orchestration decision in the contextual ledger for evaluation.

## Tasks

- [x] Add feature-flagged MAF-compatible orchestration boundary.
- [x] Route contextual drawer turns by question intent first in MAF mode.
- [x] Preserve page-anchored routing when MAF mode is disabled.
- [x] Expose `selected_agents` and `orchestration` metadata in contextual ledgers.
- [x] Add backend regression tests for cross-domain questions from the Network drawer.
- [x] Align frontend API types with the contextual ledger contract.
- [x] Add production MAF SDK dependency and lock compatible Foundry runtime packages.
- [x] Add hosted-agent runtime wiring beyond the current MAF-compatible selection boundary.
- [x] Extend evaluation harness to compare deterministic vs MAF mode.
- [x] Add default-off deployment flag wiring and rollout instructions.
- [x] Deploy behind the feature flag and run live API/evaluation validation.
- [x] Run browser-level validation from the Network drawer.
- [x] Mitigate MAF timeout volatility and rerun full evaluation cleanly.
- [x] Cut over MAF as the default after explicit parity review approval.

## Blockers / Gates

- MAF is the default orchestration mode.
- Deterministic routing remains available only as an explicit rollback path with `AIOPS_AGENT_ORCHESTRATION_MODE=deterministic`.
- Future regression requires either rollback or another parity review before expanding the agent catalog.

## Live Validation

- Deployed API/web image tag `maf-pivot-20260830-234852` behind
  `AIOPS_AGENT_ORCHESTRATION_MODE=maf`.
- Terraform apply updated only the API and web Container Apps in place:
  `0 added, 2 changed, 0 destroyed`.
- Active revisions:
  - API: `aiops-dev-api--0000140`
  - Web: `aiops-dev-web--0000107`
- Live endpoints passed:
  - `https://aiops-dev-api.greenpond-732382e3.australiaeast.azurecontainerapps.io/health`
  - `https://aiops-dev-api.greenpond-732382e3.australiaeast.azurecontainerapps.io/ready`
  - `https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/api/config`
- Evaluation artifact `.planning/eval/maf-full-20260831.json`:
  - `routing_rate`: 1.0
  - `narration_rate`: 1.0
  - `tool_correctness_mean`: 1.0
  - `orchestration_runtimes`: `{"microsoft-agent-framework": 10}`
  - Two cases hit the wall-clock budget during the full pass; rerun artifact
    `.planning/eval/maf-timeout-rerun-20260831.json` passed both without
    timeout.
- Browser validation on
  `https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/network`
  passed for the Network drawer suggested question `What depends on demo-vnet?`.
  The visible answer was a direct dependency answer, not a duplicated findings
  dump, and the response metadata recorded:
  - `runtime`: `microsoft-agent-framework`
  - `strategy`: `question_first`
  - `selected_ids`: `["network"]`
  - `synthesis.mode`: `foundry`
  - `synthesis.warning`: empty

## Parity Review

**Decision at this point:** Continue the guarded MAF rollout in the validation
environment, but do not make MAF the default yet.

MAF meets the quality bar against the saved deterministic baseline:

| Metric | Deterministic baseline | MAF validation |
| --- | ---: | ---: |
| Routing rate | 1.0 | 1.0 |
| Narration rate | 1.0 | 1.0 |
| Tool correctness mean | 1.0 | 1.0 |
| Median latency | 25639.7 ms | 16594.5 ms |

Cutover remains gated because the full MAF pass had two wall-clock timeouts
versus one in the deterministic baseline. Both timed-out MAF cases passed on
focused rerun, so this is runtime volatility rather than routing failure, but
the default cutover should wait for a clean full pass or explicit timeout-budget
mitigation.

### Timeout Mitigation Follow-up

**Decision:** MAF now meets the technical parity bar for default cutover, pending
explicit operator approval to remove the default-off guardrail.

Mitigation:

- Moved optional Fabric IQ enrichment after all selected specialists complete
  their required delegation pass, so enrichment cannot consume the bounded
  context budget before a question-selected specialist runs.
- Stopped marking an otherwise completed contextual run as `wall_clock_timeout`
  after all selected specialists and narration have already completed.
- Added regression coverage proving a Network-page CVE question runs the
  Vulnerability specialist before optional Network enrichment.

Validation after mitigation:

- Deployed API/web image tag `maf-timeoutfix-20260831-002339` with
  `AIOPS_AGENT_ORCHESTRATION_MODE=maf`.
- Active revisions:
  - API: `aiops-dev-api--0000141`
  - Web: `aiops-dev-web--0000108`
- Evaluation artifact `.planning/eval/maf-timeoutfix-full-20260831.json`:
  - `cases`: 10
  - `errors`: 0
  - `timeouts`: 0
  - `routing_rate`: 1.0
  - `narration_rate`: 1.0
  - `tool_correctness_mean`: 1.0
  - `latency_ms_median`: 11933.1
  - `orchestration_runtimes`: `{"microsoft-agent-framework": 10}`

## Default Cutover

**Decision:** MAF is now the default orchestration mode after explicit operator
approval.

- `maf_mode_enabled()` returns true unless
  `AIOPS_AGENT_ORCHESTRATION_MODE=deterministic` is set.
- Terraform defaults `agent_orchestration_mode` to `maf`.
- `deploy.sh` passes `agent_orchestration_mode=maf` when no override is present,
  so subsequent deployments preserve the cutover.
- Rollback path: run
  `AIOPS_AGENT_ORCHESTRATION_MODE=deterministic ./infra/scripts/deploy.sh apply`
  and rerun the deterministic evaluation baseline.

## Success Criteria

- Users can ask ownership, change, patch, vulnerability, remediation, incident, or network questions from any drawer and have Operations Copilot delegate to the right specialists.
- The ledger records which orchestration strategy and runtime selected the specialists.
- Existing deterministic behavior remains available as a rollback baseline.
- No specialist can bypass governed MCP/tool scope checks.
