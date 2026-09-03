---
phase: 11
slug: cross-page-operations-copilot-orchestration-and-specialist-p
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-03
---

# Phase 11 — Validation Strategy

> Per-phase Nyquist contract for task, wave, release, and live-promotion feedback.

---

## Test Infrastructure

| Property | Value |
|---|---|
| **Backend framework** | pytest 9.x |
| **Backend config** | `pyproject.toml` |
| **Web framework** | Vitest 2.1.9 + Testing Library |
| **Web config** | `web/package.json` |
| **Infrastructure** | Terraform 1.14.8 and shell syntax checks |
| **Quick backend command** | `.venv/bin/python -m pytest tests/test_orchestration_policy.py tests/test_page_context_v2.py -q` |
| **Quick web command** | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts` |
| **Quick parity command** | `.venv/bin/python -m pytest tests/test_orchestration_parity.py -q && cd web && npm test -- --run src/lib/copilot/page-adapters.manifest-parity.test.ts` |
| **Full backend command** | `.venv/bin/python -m pytest -q` |
| **Full web command** | `cd web && npm test` |
| **Infrastructure command** | `cd infra/terraform && terraform validate -no-color` |
| **Max focused feedback latency** | 60 seconds; split a focused command if it exceeds this |

---

## Sampling Rate

- **After every task commit:** Run the task's exact `<automated>` command below.
- **After every wave:** Run the focused backend Copilot suite, all web Copilot tests touched through that wave, and Terraform validation when infrastructure has changed.
- **Before `/gsd-verify-work`:** Run full backend and web suites, exact backend/frontend parity, route inventory, Terraform/package gates, and validate the saved deployed evaluation artifact.
- **Release sampling floor:** At least five routing cases per specialist; at least one normal and one stale/partial/unavailable case per integrated page kind; all required two-navigation, scope-narrowing, executive, and rollback scenarios.
- **No watch mode:** Every command terminates and returns a meaningful exit code.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | Wave 0 Dependency | Status |
|---|---:|---:|---|---|---|---|---|---|---|
| 11-01-01 | 01 | 1 | COP-01/03/04/05 | T-11-01..04 | Rejected candidates make zero tool calls; fallback/citations/thread remain bounded | service integration | `.venv/bin/python -m pytest tests/test_orchestration_policy.py tests/test_api_copilot_unified.py -q` | Create both test files before production code | ⬜ pending |
| 11-01-02 | 01 | 1 | COP-01/03 | T-11-01/03 | Inventory grant is exact, scoped, reviewed, and read-only | unit + MCP | `.venv/bin/python -m pytest tests/test_orchestration_policy.py tests/test_api_copilot_unified.py tests/test_mcp_tools.py -q` | `tests/test_orchestration_policy.py`, `tests/test_api_copilot_unified.py` | ⬜ pending |
| 11-04-01 | 04 | 2 | COP-03 | T-11-13/14 | Twelve-specialist manifest rejects cycles, unknowns, credentials, and mutation grants | unit | `.venv/bin/python -m pytest tests/test_orchestration_parity.py -q` | Create `tests/test_orchestration_parity.py` | ⬜ pending |
| 11-04-02 | 04 | 2 | COP-03 | T-11-13..15 | Runtime, prompts, MCP, catalog, and mappings exactly equal manifest | unit + integration | `.venv/bin/python -m pytest tests/test_orchestration_parity.py tests/test_mcp_tools.py tests/test_foundry_agent.py tests/test_context_specialist_routing.py -q` | `tests/test_orchestration_parity.py` | ⬜ pending |
| 11-13-01 | 13 | 2 | COP-01..05 | T-11-42..44 | Canonical API reauthorizes typed inventory observations | API + component | `.venv/bin/python -m pytest tests/test_api_copilot_unified.py -q && cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/app/inventory/page.test.tsx` | Create unified API and adapter tests | ⬜ pending |
| 11-13-02 | 13 | 2 | COP-02/04/05 | T-11-42..44 | Cited fallback and opaque-thread remount work without mutation authority | API + component | `.venv/bin/python -m pytest tests/test_api_copilot_unified.py -q && cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/app/inventory/page.test.tsx src/components/ui/CopilotDrawer.test.tsx` | Unified API and adapter tests | ⬜ pending |
| 11-02-01 | 02 | 3 | COP-04 | T-11-05..08 | Identity, dedup, conflict, scope, coverage, and citation closure fail closed | unit + API | `.venv/bin/python -m pytest tests/test_page_context_v2.py tests/test_api_copilot_snapshot_v2.py -q` | Create both snapshot v2 test files | ⬜ pending |
| 11-02-02 | 02 | 3 | COP-02/04 | T-11-05..08 | Browser emits deterministic bounded v2 observations, not authority | unit + typecheck | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts && npx tsc --noEmit` | `web/src/lib/copilot/page-adapters.test.ts` | ⬜ pending |
| 11-05-01 | 05 | 3 | COP-03 | T-11-16..18 | Terraform/package projections derive from credential-free manifest | Terraform + build | `cd infra/terraform && terraform fmt -check && terraform validate -no-color && cd ../.. && .venv/bin/python -m build --wheel` | Existing infrastructure; no new test scaffold | ⬜ pending |
| 11-05-02 | 05 | 3 | COP-03/05 | T-11-16..18 | Offline/live exact parity blocks broad or missing grants | unit + script | `.venv/bin/python -m pytest tests/test_specialist_manifest_packaging.py tests/test_orchestration_parity.py -q && .venv/bin/python scripts/validate_specialist_parity.py --offline && bash -n infra/scripts/create-foundry-agent.sh infra/scripts/validate-runtime-e2e.sh` | Create packaging and parity tests | ⬜ pending |
| 11-03-01 | 03 | 4 | COP-01 | T-11-09 | Model proposal cannot authorize, widen, mutate, or execute before policy | unit | `.venv/bin/python -m pytest tests/test_orchestration_policy.py tests/test_context_specialist_routing.py -q` | `tests/test_orchestration_policy.py` | ⬜ pending |
| 11-03-02 | 03 | 4 | COP-01/05 | T-11-10..12 | All routes converge canonically while legacy planners/readers remain rollback-safe | API integration | `.venv/bin/python -m pytest tests/test_api_copilot_unified.py tests/test_api_copilot_investigation.py tests/test_api_copilot_snapshot.py tests/test_api_multi_agent.py -q` | `tests/test_api_copilot_unified.py` | ⬜ pending |
| 11-06-01 | 06 | 5 | COP-01/05 | T-11-19 | 12-turn/1h-idle/24h-absolute thread is principal/scope bound | store integration | `.venv/bin/python -m pytest tests/test_investigation_thread_store.py tests/test_api_copilot_unified.py -q` | Create `tests/test_investigation_thread_store.py` | ⬜ pending |
| 11-06-02 | 06 | 5 | COP-05 | T-11-20..22 | Executive synthesis is conditional, citation-closed, and privacy-safe | unit + integration | `.venv/bin/python -m pytest tests/test_copilot_evaluation_v2.py tests/test_foundry_agent.py -q` | Create `tests/test_copilot_evaluation_v2.py` | ⬜ pending |
| 11-14-01 | 14 | 6 | COP-05 | T-11-45 | Browser stores only same-tab opaque ID/revision | component | `cd web && npm test -- --run src/lib/copilot/thread-context.test.tsx` | Create `web/src/lib/copilot/thread-context.test.tsx` | ⬜ pending |
| 11-14-02 | 14 | 6 | COP-05 | T-11-45/46 | Historical/revalidated states and reset semantics are visible | component | `cd web && npm test -- --run src/lib/copilot/thread-context.test.tsx src/components/ui/CopilotDrawer.test.tsx` | Thread-context test | ⬜ pending |
| 11-07-01 | 07 | 7 | COP-02/04/05 | T-11-23/25 | Overview/network/compliance adapters preserve scope, coverage, and freshness | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/components/ui/CopilotPageIntegrations.test.tsx src/app/compliance/page.test.tsx` | Adapter test | ⬜ pending |
| 11-07-02 | 07 | 7 | COP-02/04/05 | T-11-23/25 | Exposure/CVE/situations identities and provider states remain explicit | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/components/ui/CopilotPageIntegrations.test.tsx src/app/exposure/page.test.tsx src/app/situations/page.test.tsx` | Adapter test | ⬜ pending |
| 11-15-01 | 15 | 8 | COP-02/04/05 | T-11-47/48 | Current remediation eligibility overrides historical context | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/app/remediation/page.test.tsx` | Adapter test | ⬜ pending |
| 11-15-02 | 15 | 8 | COP-02/05 | T-11-47 | Copilot cannot approve or execute remediation | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/app/remediation/page.test.tsx` | Adapter test | ⬜ pending |
| 11-08-01 | 08 | 9 | COP-02/04 | T-11-26..28 | Defender/KB/patch pages remain coverage-honest and mutation-safe | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/components/ui/CopilotPageIntegrations.test.tsx` | Adapter test | ⬜ pending |
| 11-08-02 | 08 | 9 | COP-02/04 | T-11-26..28 | Change/predeploy uncertainty and handoff are cited and read-only | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/components/ui/CopilotPageIntegrations.test.tsx src/app/remediation/page.test.tsx` | Adapter test | ⬜ pending |
| 11-09-01 | 09 | 10 | COP-02/03/04 | T-11-30/31 | Data-health/governance provider states remain distinct | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/app/connections/page.test.tsx src/app/connections/fabric/page.test.tsx` | Adapter test | ⬜ pending |
| 11-09-02 | 09 | 10 | COP-02/03/04 | T-11-29..31 | Identity/cost/health context is scoped, redacted, and coverage-honest | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/components/ui/CopilotPageIntegrations.test.tsx` | Adapter test | ⬜ pending |
| 11-10-01 | 10 | 11 | COP-02/04/05 | T-11-32/33 | Situation/service navigation ages prior evidence and retains current context | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts 'src/app/situations/[id]/page.test.tsx' src/components/ui/CopilotPageIntegrations.test.tsx` | Adapter test | ⬜ pending |
| 11-10-02 | 10 | 11 | COP-02/04 | T-11-32 | Twin relations retain provenance, bounds, and uncertainty | component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/app/twin/page.test.tsx` | Adapter test | ⬜ pending |
| 11-16-01 | 16 | 12 | COP-02 | T-11-50 | Filesystem and registry contain exactly 28 reviewed dispositions | component + filesystem | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts src/components/ui/CopilotPageIntegrations.test.tsx` | Adapter test | ⬜ pending |
| 11-16-02 | 16 | 12 | COP-03 | T-11-49 | Manifest, API, routes, and every adapter hint match exactly | backend + cross-language | `.venv/bin/python -m pytest tests/test_orchestration_parity.py -q && cd web && npm test -- --run src/lib/copilot/page-adapters.manifest-parity.test.ts src/lib/copilot/page-adapters.test.ts` | Create manifest parity Vitest file | ⬜ pending |
| 11-11-01 | 11 | 13 | COP-01/02/05 | T-11-35 | Standalone/workspace share canonical policy/evidence/thread semantics | component + typecheck | `cd web && npm test -- --run src/app/investigate/page.test.tsx src/components/ui/CopilotDrawer.test.tsx && npx tsc --noEmit` | Existing tests cover scaffold | ⬜ pending |
| 11-11-02 | 11 | 13 | COP-01/02/05 | T-11-35..37 | Ledger UI is a principal-scoped canonical projection with API catalog | API + component | `.venv/bin/python -m pytest tests/test_api_copilot_unified.py tests/test_api_multi_agent.py -q && cd web && npm test -- --run src/app/agents/page.test.tsx` | Unified API test | ⬜ pending |
| 11-12-01 | 12 | 14 | COP-01..05 | T-11-38 | Versioned corpus enforces all deterministic and absolute quality thresholds | evaluation unit | `.venv/bin/python -m pytest tests/test_copilot_evaluation_v2.py tests/test_copilot_evaluation.py tests/test_context_evaluation_metrics.py -q` | Create evaluation test + dataset + thresholds | ⬜ pending |
| 11-12-02 | 12 | 14 | COP-01/03/05 | T-11-39/41 | Staged controls hold/disable/rollback mechanically; legacy remains available | Terraform + scripts | `cd infra/terraform && terraform validate -no-color && cd ../.. && bash -n infra/scripts/validate-runtime-e2e.sh && .venv/bin/python scripts/validate_specialist_parity.py --offline` | Existing infra plus parity script from Plan 05 | ⬜ pending |
| 11-12-03 | 12 | 14 | COP-01..05 | T-11-38..41 | Deployed artifact records honest PROMOTE/HOLD/disabled-mode decision | live evaluation | `.venv/bin/python scripts/evaluate_agents.py --validate-artifact .planning/eval/copilot-orchestration-baseline.json --dataset tests/fixtures/copilot_evaluation_cases.v1.json --thresholds tests/fixtures/copilot_release_thresholds.v1.json` | Dataset/thresholds from Task 11-12-01 and live credentials | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 means each listed test/data artifact is created with failing characterization or contract cases before the associated production implementation begins. Existing pytest, Vitest, Terraform, and build infrastructure require no package installation.

- [ ] `tests/test_orchestration_policy.py` — pre-I/O denial, zero tool calls, budgets, DAGs, grants, mutation fence, fallback.
- [ ] `tests/test_api_copilot_unified.py` — canonical contract plus endpoint/tracer equivalence.
- [ ] `tests/test_page_context_v2.py` — identity, dedup, priority, conflict, freshness, coverage, insufficiency, citations.
- [ ] `tests/test_api_copilot_snapshot_v2.py` — API authorization and unsupported-version behavior.
- [ ] `tests/test_orchestration_parity.py` — exact manifest/runtime/MCP/Terraform/API/page mapping sets.
- [ ] `tests/test_specialist_manifest_packaging.py` — wheel/container manifest inclusion.
- [ ] `tests/test_investigation_thread_store.py` — durability, principal binding, scope narrowing, 12-turn/1h/24h expiry, evidence aging.
- [ ] `tests/test_copilot_evaluation_v2.py` — synthesis, telemetry privacy, thresholds, and release dispositions.
- [ ] `web/src/lib/copilot/page-adapters.test.ts` — adapter output and 28-route dispositions.
- [ ] `web/src/lib/copilot/thread-context.test.tsx` — same-tab continuity and storage boundary.
- [ ] `web/src/lib/copilot/page-adapters.manifest-parity.test.ts` — exact manifest/API/UI route and hint parity.
- [ ] `tests/fixtures/copilot_evaluation_cases.v1.json` — versioned representative corpus.
- [ ] `tests/fixtures/copilot_release_thresholds.v1.json` — predetermined resolved thresholds.

---

## Release Threshold Contract

| Gate | Pass threshold | Failure disposition |
|---|---:|---|
| Scope isolation, cross-principal denial, production-mutation denial, unknown specialist/tool denial | 100%; zero violations | Hold all promotion |
| Route disposition, manifest/API/UI projection, grants, snapshot schema, retained references | 100%; exact equality where applicable | Hold affected build |
| Deterministic tool correctness | 100% | Hold promotion |
| Specialist routing | Exact-set accuracy >= 0.90 overall; recall >= 0.80 per specialist | Hold model routing; fallback may ship only if independently green |
| Groundedness | Mean >= 0.75; p10 >= 0.50; zero unsupported high-severity, causal, or action-scope claims | Hold narration |
| Citation quality | 100% valid references; material-claim coverage >= 0.95 | Invalid reference holds all; coverage miss holds narration/synthesis |
| Single-domain latency | p95 <= 8,000 ms | Hold model-planned single-domain mode |
| Cross-domain/executive latency | p95 <= 15,000 ms | Disable/hold executive synthesis |
| Provider/runtime reliability | Completed-turn rate >= 0.98; timeout rate <= 0.01 | Hold affected provider mode |
| Per-turn model spend | Every single-domain turn <= USD 0.15; every cross-domain/executive turn <= USD 0.40 | Hold affected mode |

`PROMOTE` requires every applicable row. A deterministic safety or citation-integrity failure holds the whole build. An optional model/provider mode may be disabled only when all deterministic gates pass and the unavailable state remains explicit.

---

## Manual and Environment Gates

| Behavior | Requirement | Why Manual/Environment-Gated | Test Instructions |
|---|---|---|---|
| Live Foundry/Operations MCP/Azure MCP exact parity | COP-03 | Local shell lacks Foundry project endpoint | Run the read-only post-deploy parity job; require exact manifest equality and zero mutation-capable grants. |
| Deployed compatibility → shadow → canary observation | COP-01/COP-05 | Requires target Container Apps revision and live traffic boundary | Execute `infra/scripts/validate-runtime-e2e.sh`, record revision/mode, and require all applicable thresholds. |
| Cross-page operator UAT | COP-02/COP-04/COP-05 | Visual/interactive confirmation at end of phase | From `/inventory`, continue the same thread through CVE → service → remediation; verify citations, historical labels, current scope, and no Copilot approval/execution control. |
| Gold grounding unavailable behavior | COP-05 | Credentials may intentionally remain absent | Confirm the deployed result marks Gold grounding unavailable while deterministic evidence and the page remain usable. |

---

## Validation Sign-Off

- [ ] Every task has an automated command.
- [ ] No three consecutive tasks lack automated feedback.
- [ ] All Wave 0 test/data dependencies exist before their production behavior is implemented.
- [ ] No watch-mode flags are present.
- [ ] Focused commands complete within 60 seconds or are split.
- [ ] Exact manifest/API/UI parity passes.
- [ ] All deterministic gates and applicable absolute thresholds pass, or affected optional modes are explicitly disabled as permitted.
- [ ] `wave_0_complete: true` and `nyquist_compliant: true` are set after reconciliation.

**Approval:** pending
