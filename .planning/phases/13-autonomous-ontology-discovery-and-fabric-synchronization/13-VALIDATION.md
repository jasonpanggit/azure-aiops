---
phase: 13
slug: autonomous-ontology-discovery-and-fabric-synchronization
status: in_progress
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-04
updated: 2026-09-07
---

# Phase 13 — Validation Strategy

## Test Infrastructure

| Property | Value |
|---|---|
| Backend | pytest 9.1.1 via `uv run pytest -q` |
| Web | Vitest 2.x via `cd web && npm test -- --run ...` |
| Infrastructure | Terraform 1.14.8 `fmt -check` + `validate` plus pytest HCL assertions |
| Prompt regression | Promptfoo 0.122.2 via `npm ci --prefix evals/ontology-discovery`; config validation plus exact no-cache eval |
| Trace inspection | Arize Phoenix 20.4.0 + OpenTelemetry SDK 1.44.0 via locked opt-in `eval` extra and trusted Microsoft package proxy; loopback/self-hosted synthetic spans only |
| Quick local target | One task-specific test file, normally under 60 seconds |
| Full gate | Backend, ruff, web tests/typecheck/build, Terraform, synthetic evaluator, credentialed live validator |
| Watch mode | Forbidden; every command is finite |

## Sampling Rate

- **Before all production work:** execute `uv run python .planning/scripts/preflight_phase_13.py`; abort until Phase 10 and every Phase 12 plan/requirement are complete and verified.
- **After every task:** run its exact finite command below plus ruff/typecheck where applicable.
- **After every wave:** run all completed Phase 13 targeted tests and dependency regressions.
- **Before verification:** run the evaluation gate in Plan 13-14 and the full shadow deployment gate in Plan 13-15, then inspect sanitized Phoenix/live evidence.
- **Feedback latency:** local unit/contract loops target under 60 seconds. Terraform and credentialed live/deployment drills are explicit release gates and are not misclassified as quick loops.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command / Gate | Wave 0 | Status |
|---|---:|---:|---|---|---|---|---|
| 13-01-01 | 01 | 1 | AUTO-ONT-01..07 | preflight/tracer | `uv run pytest -q tests/test_phase_13_preflight.py tests/test_ontology_discovery_contracts.py -x && uv run python .planning/scripts/preflight_phase_13.py` | creates | passed |
| 13-01-02 | 01 | 1 | AUTO-ONT-02..07 | fixture/contract | `uv run pytest -q tests/test_ontology_discovery_contracts.py -x` | creates | passed |
| 13-02-01 | 02 | 2 | AUTO-ONT-01,06 | unit/concurrency | `uv run pytest -q tests/test_ontology_discovery_store.py tests/test_ontology_discovery_coordinator.py -x` | consumes | passed |
| 13-02-02 | 02 | 2 | AUTO-ONT-01,06 | integration | `uv run pytest -q tests/test_ontology_discovery_coordinator.py tests/test_subscription_onboarding.py -k 'sync or restart or timeout' -x` | consumes | passed |
| 13-03-01 | 03 | 3 | AUTO-ONT-02,07 | property/replay | `uv run pytest -q tests/test_ontology_discovery_incremental.py -x` | consumes | passed |
| 13-03-02 | 03 | 3 | AUTO-ONT-02,06 | restart/replay | `uv run pytest -q tests/test_pending_relationships.py tests/test_ontology_discovery_incremental.py -x` | consumes | passed |
| 13-04-01 | 04 | 4 | AUTO-ONT-03,07 | contract/fault | `uv run pytest -q tests/test_ontology_curator_agent.py -x` | consumes | pending |
| 13-04-02 | 04 | 4 | AUTO-ONT-03 | MCP/security | `uv run pytest -q tests/test_ontology_curator_agent.py tests/test_foundry_tool_registry_matches_implementation.py tests/test_mcp_protocol.py -x` | consumes | pending |
| 13-05-01 | 05 | 5 | AUTO-ONT-04,07 | policy/security | `uv run pytest -q tests/test_ontology_proposal_policy.py tests/test_relationship_vocabulary_consistency.py -x` | consumes | pending |
| 13-05-02 | 05 | 5 | AUTO-ONT-04,06 | lifecycle/property | `uv run pytest -q tests/test_ontology_proposal_policy.py -x` | consumes | pending |
| 13-06-01 | 06 | 2 | AUTO-ONT-05,06 | inventory/contract | `uv run pytest -q tests/test_ontology_generation_consumers.py -k 'inventory or resolver' -x` | consumes | pending |
| 13-06-02 | 06 | 2 | AUTO-ONT-05,07 | integration/rollback | `uv run pytest -q tests/test_ontology_generation_consumers.py -k 'api or fabric or agent or operations or alias' -x` | consumes | pending |
| 13-06-03 | 06 | 2 | AUTO-ONT-05,07 | export/semantic rollback | `uv run pytest -q tests/test_ontology_generation_consumers.py -k 'twin or semantic or inventory or rollback' -x` | consumes | pending |
| 13-07-01 | 07 | 5 | AUTO-ONT-01 | Terraform/contract | `uv run pytest -q tests/test_ontology_discovery_job_infra.py && terraform -chdir=infra/terraform fmt -check && terraform -chdir=infra/terraform validate` | consumes | pending |
| 13-07-02 | 07 | 5 | AUTO-ONT-03,05 | Terraform/security | `uv run pytest -q tests/test_ontology_publisher_identity.py tests/test_ontology_curator_infra.py && terraform -chdir=infra/terraform fmt -check && terraform -chdir=infra/terraform validate` | consumes | pending |
| 13-07-03 | 07 | 5 | AUTO-ONT-05,07 | live authorization | `uv run pytest -q tests/test_ontology_publisher_identity.py && uv run python scripts/validate_ontology_publisher_rbac.py --non-production --fail-on-missing-evidence` | consumes | pending |
| 13-08-01 | 08 | 6 | AUTO-ONT-05 | decision | Blocking pointer-cutover evidence decision; no implementation | N/A | pending |
| 13-08-02 | 08 | 6 | AUTO-ONT-05 | decision | Blocking publisher-RBAC evidence decision; no implementation | N/A | pending |
| 13-08-03 | 08 | 6 | AUTO-ONT-03 | decision | Blocking prompt-vs-hosted evidence decision; no implementation | N/A | pending |
| 13-09-01 | 09 | 7 | AUTO-ONT-05 | storage/concurrency | `uv run pytest -q tests/test_onelake_documents.py tests/test_run_lock.py -x` | consumes | pending |
| 13-09-02 | 09 | 7 | AUTO-ONT-05,06 | publication/fault | `uv run pytest -q tests/test_ontology_generation_publication.py -x` | consumes | pending |
| 13-09-03 | 09 | 7 | AUTO-ONT-05,07 | E2E/rollback | `uv run pytest -q tests/test_ontology_discovery_e2e.py tests/test_ontology_generation_publication.py -x` | consumes | pending |
| 13-10-01 | 10 | 8 | AUTO-ONT-01,05 | integration/security | `uv run pytest -q tests/test_ontology_discovery_coordinator.py tests/test_subscription_onboarding.py tests/test_fabric_sync_service.py -k 'publisher or manual or scheduled or generation' -x` | consumes | pending |
| 13-10-02 | 10 | 8 | AUTO-ONT-01,06 | compatibility/restart | `uv run pytest -q tests/test_subscription_onboarding.py -k 'sync or health or restart' -x` | consumes | pending |
| 13-11-01 | 11 | 2 | AUTO-ONT-06,07 | contract/CAS | `uv run pytest -q tests/test_ontology_evaluation_snapshot.py -k 'contract or write or cas' -x` | consumes | passed |
| 13-11-02 | 11 | 2 | AUTO-ONT-06,07 | restart/freshness | `uv run pytest -q tests/test_ontology_evaluation_snapshot.py -x` | consumes | passed |
| 13-12-01 | 12 | 9 | AUTO-ONT-04..07 | API/security | `uv run pytest -q tests/test_api_ontology_discovery.py tests/test_api_ontology_evaluation.py -x` | consumes | pending |
| 13-12-02 | 12 | 9 | AUTO-ONT-01,06 | app wiring | `uv run pytest -q tests/test_api_ontology_discovery.py tests/test_api_ontology_evaluation.py -x` | consumes | pending |
| 13-13-01 | 13 | 10 | AUTO-ONT-06,07 | web contract | `cd web && npm test -- --run src/app/connections/page.test.tsx && npx tsc --noEmit` | consumes | pending |
| 13-13-02 | 13 | 10 | AUTO-ONT-01,04,05,06 | web/accessibility | `cd web && npm test -- --run src/app/connections/page.test.tsx && npx tsc --noEmit` | consumes | pending |
| 13-14-01 | 14 | 11 | AUTO-ONT-03,07 | config/dependency | `UV_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple uv sync --extra eval --locked && npm ci --prefix evals/ontology-discovery && export PATH="$PWD/evals/ontology-discovery/node_modules/.bin:$PATH" PROMPTFOO_DISABLE_TELEMETRY=1 && promptfoo validate -c evals/ontology-discovery/promptfooconfig.yaml` | consumes | passed |
| 13-14-02 | 14 | 11 | AUTO-ONT-03,04,06,07 | Promptfoo/snapshot | `uv run pytest -q tests/test_ontology_discovery_evals.py -x && export PATH="$PWD/evals/ontology-discovery/node_modules/.bin:$PATH" PROMPTFOO_DISABLE_TELEMETRY=1 && promptfoo validate -c evals/ontology-discovery/promptfooconfig.yaml && promptfoo eval -c evals/ontology-discovery/promptfooconfig.yaml --no-cache && uv run python scripts/evaluate_ontology_discovery.py --synthetic-only --dataset tests/fixtures/ontology_discovery/reference.jsonl --fail-on-threshold` | consumes | passed |
| 13-14-03 | 14 | 11 | AUTO-ONT-06,07 | Phoenix/security | `UV_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple uv run --extra eval --extra test pytest -q tests/test_ontology_trace_redaction.py tests/test_ontology_discovery_evals.py -x && UV_INDEX_URL=https://packagefeedproxy.microsoft.io/pypi/simple uv run --extra eval python scripts/inspect_ontology_traces.py --launch-local --dataset tests/fixtures/ontology_discovery/reference.jsonl --fail-on-redaction` | consumes | passed |
| 13-15-01 | 15 | 12 | AUTO-ONT-01,07 | alert/Terraform | `uv run pytest -q tests/test_ontology_discovery_alerts.py && terraform -chdir=infra/terraform fmt -check && terraform -chdir=infra/terraform validate && uv run python scripts/validate_ontology_discovery_live.py --alert-smoke --synthetic-only --fail-on-missing-evidence` | consumes | pending |
| 13-15-02 | 15 | 12 | AUTO-ONT-01..07 | deployed shadow E2E | `uv run pytest -q tests/test_ontology_discovery_evals.py tests/test_ontology_discovery_alerts.py && uv run python scripts/validate_ontology_discovery_live.py --shadow --assert-authoritative-model-edge-count-zero --assert-release-status blocked-or-pending --fail-on-threshold --fail-on-missing-evidence` | consumes | pending |
| 13-16-01 | 16 | 13 | AUTO-ONT-01,02,03,04,06,07 | production tracer/CAS | `uv run pytest -q tests/test_ontology_discovery_runtime.py tests/test_ontology_discovery_store.py tests/test_ontology_discovery_incremental.py tests/test_ontology_curator_agent.py tests/test_ontology_proposal_policy.py -x` | consumes | pending |
| 13-16-02 | 16 | 13 | AUTO-ONT-01,06,07 | CLI/config/restart | `uv run pytest -q tests/test_ontology_discovery_runtime.py tests/test_ontology_discovery_coordinator.py tests/test_subscription_onboarding.py -k 'ontology or sync or restart or duplicate or fail_closed' -x` | consumes | pending |
| 13-17-01 | 17 | 14 | AUTO-ONT-05,06,07 | publisher E2E/restart | `uv run pytest -q tests/test_ontology_publisher_runtime.py tests/test_ontology_generation_publication.py tests/test_fabric_sync_service.py tests/test_ontology_generation_consumers.py -x` | consumes | pending |
| 13-17-02 | 17 | 14 | AUTO-ONT-05,06,07 | rollback/identity/fault | `uv run pytest -q tests/test_ontology_publisher_runtime.py tests/test_ontology_generation_publication.py -k 'rollback or identity or restart or duplicate or stale' -x` | consumes | pending |
| 13-18-01 | 18 | 15 | AUTO-ONT-01,05,06 | API rollback tracer | `uv run pytest -q tests/test_api_ontology_discovery.py tests/test_api_ontology_evaluation.py tests/test_ontology_publisher_runtime.py -x` | consumes | pending |
| 13-18-02 | 18 | 15 | AUTO-ONT-01,04,05,06,07 | OpenAPI/UI/restart | `uv run pytest -q tests/test_api_ontology_discovery.py tests/test_api_ontology_evaluation.py tests/test_subscription_onboarding.py -k 'ontology or sync or openapi or restart or rollback' -x && cd web && npm test -- --run src/app/connections/page.test.tsx && npx tsc --noEmit` | consumes | pending |
| 13-19-01 | 19 | 16 | AUTO-ONT-01,03,05,06,07 | Terraform/identity tracer | `uv run pytest -q tests/test_ontology_discovery_job_infra.py tests/test_ontology_publisher_identity.py tests/test_ontology_curator_infra.py -x && terraform -chdir=infra/terraform fmt -check && terraform -chdir=infra/terraform validate` | consumes | pending |
| 13-19-02 | 19 | 16 | AUTO-ONT-01,05,06,07 | targeted deployment | `uv run pytest -q tests/test_ontology_deployment_plan.py tests/test_ontology_discovery_job_infra.py tests/test_ontology_publisher_identity.py -x && uv run python scripts/validate_ontology_deployment_plan.py --evidence .planning/eval/ontology-gap-deployment.json --require-applied --fail-on-unexpected-change` | consumes | pending |
| 13-20-01 | 20 | 17 | AUTO-ONT-01,02,03,04,06,07 | deployed schedule/checkpoints | `uv run pytest -q tests/test_ontology_discovery_live_evidence.py tests/test_ontology_discovery_evals.py -x && uv run python scripts/validate_ontology_discovery_live.py --shadow --collect-deployed-lifecycle --output .planning/eval/ontology-deployed-lifecycle.json --fail-on-local-substitution --fail-on-missing-evidence` | consumes | pending |
| 13-20-02 | 20 | 17 | AUTO-ONT-04,05,06,07 | deployed generation/rollback | `uv run pytest -q tests/test_ontology_discovery_live_evidence.py -k 'edges or promotion or consumer or stale or rollback or provenance' -x && uv run python scripts/validate_ontology_discovery_live.py --shadow --evidence .planning/eval/ontology-deployed-lifecycle.json --assert-authoritative-model-edge-count-zero --assert-deployed-old-new-old --assert-five-live-consumers --fail-on-local-substitution --fail-on-missing-evidence` | consumes | pending |
| 13-21-01 | 21 | 18 | AUTO-ONT-01,04,05,06,07 | deployed API/UI | `uv run pytest -q tests/test_ontology_discovery_live_evidence.py -k 'openapi or api or ui or playwright or provenance' -x && cd web && npx playwright test e2e/ontology-automation-live.spec.ts` | consumes | pending |
| 13-21-02 | 21 | 18 | AUTO-ONT-01..07 | deployed-only closeout | `uv run pytest -q tests/test_ontology_publisher_identity.py tests/test_ontology_discovery_live_evidence.py tests/test_ontology_discovery_evals.py -x && uv run python scripts/validate_ontology_publisher_rbac.py --non-production --fail-on-missing-evidence && uv run python scripts/validate_ontology_discovery_live.py --shadow --evidence .planning/eval/ontology-deployed-lifecycle.json --assert-authoritative-model-edge-count-zero --assert-release-status blocked-or-pending --assert-deployed-old-new-old --assert-five-live-consumers --fail-on-local-substitution --fail-on-threshold --fail-on-missing-evidence` | consumes | pending |

## Wave 0 Requirements

- [x] `.planning/scripts/preflight_phase_13.py` and `tests/test_phase_13_preflight.py`
- [x] `tests/ontology_discovery_contract_harness.py`
- [x] `tests/fixtures/ontology_discovery/reference.jsonl`
- [x] `tests/test_ontology_discovery_contracts.py`
- [ ] `tests/test_ontology_discovery_store.py`
- [ ] `tests/test_ontology_discovery_coordinator.py`
- [ ] `tests/test_ontology_discovery_incremental.py`
- [ ] `tests/test_ontology_curator_agent.py`
- [ ] `tests/test_ontology_proposal_policy.py`
- [ ] `tests/test_ontology_generation_consumers.py`
- [ ] `tests/test_ontology_publisher_identity.py`
- [ ] `tests/test_ontology_generation_publication.py`
- [ ] `tests/test_ontology_discovery_e2e.py`
- [ ] `tests/test_ontology_evaluation_snapshot.py`
- [ ] `tests/test_api_ontology_discovery.py`
- [ ] `tests/test_api_ontology_evaluation.py`
- [x] `tests/test_ontology_discovery_evals.py`
- [x] `evals/ontology-discovery/promptfooconfig.yaml`
- [x] `tests/test_ontology_trace_redaction.py`
- [ ] `tests/test_ontology_discovery_alerts.py`
- [ ] `tests/test_ontology_discovery_runtime.py`
- [ ] `tests/test_ontology_publisher_runtime.py`
- [ ] `tests/test_ontology_deployment_plan.py`
- [ ] `tests/test_ontology_discovery_live_evidence.py`
- [ ] `web/e2e/ontology-automation-live.spec.ts`

## Manual / Deployment Verification

| Behavior | Requirement | Automated precursor | Human evidence |
|---|---|---|---|
| Pointer consumer cutover | AUTO-ONT-05 | Three-state consumer suite | Plan 13-08 one-way-door decision |
| Publisher least privilege | AUTO-ONT-03,05 | Terraform matrix + live denied writes | Plan 13-08 RBAC decision |
| Prompt versus hosted runtime | AUTO-ONT-03 | Executed proposal generation | Plan 13-08 prompt selection continues; hosted exception records evidence and halts for `/gsd-plan-phase 13 --reviews` |
| Prompt regression and trace privacy | AUTO-ONT-03,07 | Promptfoo exact gate + Phoenix redaction assertions | Plan 13-14 local Phoenix inspection |
| Deployed schedule, shadow exclusion, deterministic rollback, alerts | AUTO-ONT-01..07 | Live shadow validator | End-of-phase sanitized report/UI review with BLOCKED/PENDING release status |

## Validation Sign-Off

- [x] One row exists for every actual and planned task (47/47).
- [x] Every code-producing task has a finite `<automated>` gate or consumes Wave 0.
- [x] Checkpoint-only tasks are backed by completed automated evidence and contain no implementation.
- [x] No watch-mode flags are present.
- [x] Quick local feedback target is under 60 seconds; Terraform/live deployment gates are explicitly separated.
- [x] Wave 0 references are preserved and expanded.
- [x] Promptfoo config validation and exact `promptfoo eval -c evals/ontology-discovery/promptfooconfig.yaml --no-cache` are independently mapped.
- [x] Self-hosted Phoenix setup, run, trace inspection, and forbidden-content assertions are independently mapped.
- [x] Hosted-agent exception halts before Plan 13-09 and requires explicit replanning.
- [x] Deployed model edges remain shadow-only; live release/canary activation is absent and eligibility is BLOCKED/PENDING.
- [x] `nyquist_compliant: true` is reconciled with the task map.
- [x] `wave_0_complete` is true after Plan 13-01 passed the integrated Phase 10/12 preflight and Wave 0 contract gates.

**Approval:** Plan 13-01 foundation complete; later Phase 13 plans remain gated by `.planning/scripts/preflight_phase_13.py`.
