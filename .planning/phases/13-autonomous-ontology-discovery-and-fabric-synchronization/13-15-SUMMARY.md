---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 15
subsystem: evaluation-observability
tags: [azure-container-apps, fabric, foundry, onelake, terraform, shadow-validation]

requires:
  - phase: 13-07
    provides: scheduled coordinator Job, isolated state/RBAC workspaces, prompt curator, and live identity evidence
  - phase: 13-09
    provides: deterministic publication, five-consumer cutover, stale-writer rejection, and rollback contracts
  - phase: 13-14
    provides: Promptfoo, Phoenix redaction, repository evaluation, and durable BLOCKED/PENDING snapshots
provides:
  - exact Terraform alert coverage with sanitized emission smoke
  - credentialed non-production shadow validator spanning Azure, Fabric, Foundry, RBAC, evaluation, consumers, and UI/API contracts
  - durable Phase 13 EvaluationSnapshot and per-pair BLOCKED/PENDING readiness records
  - operator procedures for evidence retention, emergency disable, deterministic rollback, and later admission review
affects: [ontology-operations, release-review, fabric-state, alerting]

actuals:
  tokens: 91203
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - explicit Phase 13 state targets override and never fall back to production Fabric workspace IDs
    - credentialed evidence is reduced to statuses, counts, timestamps, hashes, and closed reason codes
    - OneLake initial documents use guarded DFS create/append/flush while updates retain ETag CAS
    - a passing shadow gate deliberately retains BLOCKED/PENDING pair release status

key-files:
  created:
    - docs/ontology-discovery-operations.md
    - .planning/eval/ontology-discovery-shadow-2026-09-07.json
  modified:
    - src/ontology_discovery/telemetry.py
    - infra/terraform/alerting.tf
    - scripts/validate_ontology_discovery_live.py
    - src/storage/onelake_documents.py
    - tests/test_ontology_discovery_alerts.py
    - tests/test_ontology_discovery_evals.py
    - tests/test_onelake_documents.py

key-decisions:
  - "Resolve Phase 13 state and RBAC workspaces only from explicit CLI/environment values or canonical Terraform outputs; ordinary deployment config supplies connection metadata but never state workspace defaults."
  - "Treat BLOCKED/PENDING for every predicate/type pair as the successful Phase 13 release result because no pair has 30 consecutive shadow days or 200 expert-adjudicated eligible proposals."
  - "Use executable Plan 13 publication/consumer/API/UI contracts together with scoped live control-plane evidence; do not label an unavailable live fact as passed."
  - "Persist EvaluationSnapshot and per-pair readiness records in the isolated Phase 13 OneLake state workspace while keeping production model admission structurally unavailable."

patterns-established:
  - "Live shadow closeout: scoped cloud reads and bounded Job starts -> executable safety contracts -> durable evidence -> sanitized report."
  - "Release report semantics: validator PASS and pair BLOCKED/PENDING are compatible and expected; ELIGIBLE is a validation failure in Phase 13."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-02, AUTO-ONT-03, AUTO-ONT-04, AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: Every AI-SPEC ontology alert has exact Terraform semantics and a sanitized observed emission path.
    requirement: AUTO-ONT-07
    verification:
      - kind: integration
        ref: "tests/test_ontology_discovery_alerts.py and validate_ontology_discovery_live.py --alert-smoke"
        status: pass
      - kind: other
        ref: "terraform fmt -check and terraform validate"
        status: pass
    human_judgment: false
  - id: D2
    description: The credentialed shadow gate proves deployed scheduling, explicit non-production scope, Foundry configuration, identity separation, exact bounds, injection resistance, zero model-edge authority, deterministic rollback, and every consumer category.
    requirement: AUTO-ONT-05
    verification:
      - kind: e2e
        ref: ".planning/eval/ontology-discovery-shadow-2026-09-07.json"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_discovery_evals.py and tests/test_ontology_discovery_e2e.py"
        status: pass
    human_judgment: false
  - id: D3
    description: Durable evaluation and per-pair metrics remain explicitly BLOCKED/PENDING with missing 30-day and 200-label predicates and no activation interface.
    requirement: AUTO-ONT-04
    verification:
      - kind: e2e
        ref: "credentialed shadow report plus reconstructed OneLake EvaluationSnapshot/pair-readiness records"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_evaluation_snapshot.py and tests/test_ontology_proposal_policy.py"
        status: pass
    human_judgment: false

duration: 38min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 15: Credentialed Shadow Closeout Summary

**Exact Azure Monitor alerts and a credentialed Azure/Fabric/Foundry shadow gate now prove deterministic-only authority while durably retaining every model pair as BLOCKED/PENDING.**

## Performance

- **Duration:** 38 min
- **Started:** 2026-09-07T03:34:43Z
- **Completed:** 2026-09-07T04:13:01Z
- **Tasks:** 2
- **Files modified:** 17

## Accomplishments

- Defined and structurally tested all 28 exact alert rules, severities,
  thresholds, windows, action-group links, low-cardinality metrics, and
  sanitized synthetic emissions.
- Replaced the alert-only validator with a credentialed `--shadow` path that
  resolves explicit Phase 13 targets rather than the production workspace in
  `fabric.config.deploy.yaml`.
- Proved two successful no-click runs plus two successful bounded manual
  executions, restart/idempotency contracts, exact 50/200/40 and
  8,000/1,200/60 bounds, deployed prompt-agent configuration, injection/scope
  defenses, and the Plan 13-07 identity matrix.
- Re-executed deterministic generation publication, stale-writer rejection,
  API/Fabric/agent/export/semantic old/new/old rollback, API audit, UI audit,
  Promptfoo no-cache evaluation, Phoenix redaction inspection, and alert smoke.
- Persisted and reconstructed fresh/stale EvaluationSnapshot evidence plus 253
  allowed-pair readiness rows in the isolated Phase 13 OneLake state
  lakehouse. Every pair explicitly lacks 30 consecutive days and 200 expert
  labels, remains `BLOCKED/PENDING`, and has no activation interface.
- Added an operations runbook for evidence collection, report interpretation,
  emergency disable, deterministic rollback, retention, and the required
  future reviewed-plan boundary.

## Task Commits

Each TDD task was committed with a RED contract before its implementation:

1. **Task 1 RED: exact alert contracts** - `4a6505ce` (test)
2. **Task 1 GREEN: ontology alert telemetry and Terraform rules** - `ab652d3f` (feat)
3. **Task 2 RED: credentialed shadow validation contracts** - `11e154fc` (test)
4. **Task 2 GREEN: live shadow gate, durable evidence, and runbook** - `f50e3366` (feat)

## Files Created/Modified

- `src/ontology_discovery/telemetry.py` - Low-cardinality metrics and 28
  sanitized alert-smoke signals.
- `infra/terraform/alerting.tf` - Exact immediate, schedule/freshness,
  one-hour, and weekly ontology alerts.
- `scripts/validate_ontology_discovery_live.py` - Alert smoke plus full
  credentialed shadow validation and sanitized dated report generation.
- `tests/test_ontology_discovery_alerts.py` - Terraform and telemetry alert
  contracts.
- `tests/test_ontology_discovery_evals.py` - Explicit target resolution,
  complete evidence, release blocking, no-activation, and sanitization tests.
- `src/storage/onelake_documents.py` and `tests/test_onelake_documents.py` -
  live-proven OneLake initial DFS write behavior and regression contract.
- `docs/ontology-discovery-operations.md` - Operator procedures and future
  release-review boundary.
- `.planning/eval/ontology-discovery-shadow-2026-09-07.json` - Sanitized
  credentialed report; status PASS, authoritative model edge count zero,
  release status BLOCKED/PENDING.
- `.planning/eval/ontology-discovery-shadow-2026-09-07/` - Reproducible local
  repository-evaluation report and immutable snapshot history.

## Decisions Made

- Explicit Phase 13 state/RBAC target IDs or canonical Terraform values are
  mandatory. The production Fabric workspace in connection configuration is
  never an implicit shadow-state target.
- Real cloud evidence and executable contracts are identified separately in
  the report. The validator fails on a missing source rather than substituting
  a fixture or inference.
- The successful closeout state is `PASS` for shadow safety and
  `BLOCKED/PENDING` for pair release. A pair reported `ELIGIBLE` fails the
  Phase 13 validator.
- Model admission remains unavailable in CLI, UI, configuration, and runtime
  defaults. A future reviewed plan and blocking checkpoint are prerequisites
  to any activation work.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Repaired initial OneLake DFS document writes**
- **Found during:** Task 2 credentialed durable EvaluationSnapshot write
- **Issue:** The SDK's `upload_data(overwrite=False)` created a remote path but
  its append step returned `PathNotFound` on OneLake, preventing the first
  durable snapshot from being recorded.
- **Fix:** Initial remote documents now use explicit guarded
  `create_file(if_none_match="*")`, `append_data`, and `flush_data`, with
  incomplete-file cleanup; ETag-conditional replacement remains unchanged.
- **Files modified:** `src/storage/onelake_documents.py`,
  `tests/test_onelake_documents.py`
- **Verification:** Regression suite passed and three credentialed snapshots
  plus latest/history and pair-readiness records were reconstructed from
  OneLake.
- **Committed in:** `f50e3366`

**2. [Rule 1 - Bug] Corrected credentialed evidence invocation details**
- **Found during:** Task 2 live validator execution
- **Issue:** The initial Foundry request passed a redacted placeholder instead
  of the in-memory bearer token, and the Phoenix command omitted its required
  dataset argument.
- **Fix:** Credentials remain in-memory and excluded from output while the
  request uses the real token; Phoenix receives the checked-in reference
  dataset path.
- **Files modified:** `scripts/validate_ontology_discovery_live.py`
- **Verification:** Final exact Task 2 command exited zero; Foundry and Phoenix
  both report PASS and the report contains no target IDs or bearer material.
- **Committed in:** `f50e3366`

---

**Total deviations:** 2 auto-fixed bugs.
**Impact on plan:** Both fixes were required to produce genuine durable and
credentialed evidence. No production API/web deployment or model admission
was performed.

## Issues Encountered

- The checked-in deployment config points at the production operational
  workspace. The validator correctly refused to use those IDs and consumed
  explicit Phase 13 state/RBAC targets.
- The first two credentialed attempts failed closed on Foundry authorization
  wiring and initial OneLake write behavior. Their failures were not converted
  into passes; the final dated report was regenerated only after both defects
  were fixed and all evidence succeeded.
- Repository-wide Ruff has known unrelated legacy findings in the phase
  deferred-items ledger. Plan 13-15 targeted Ruff is clean.

## Verification

- `uv run pytest -q tests/test_ontology_discovery_evals.py tests/test_ontology_discovery_alerts.py tests/test_onelake_documents.py` — 31 passed.
- Targeted Ruff over every Plan 13-15 Python file — passed.
- `terraform -chdir=infra/terraform fmt -check` — passed.
- `terraform -chdir=infra/terraform validate` — passed.
- `uv run python .planning/scripts/preflight_phase_13.py` — passed.
- Exact alert-smoke command — 28/28 rules, queries, and action groups passed.
- Exact credentialed Task 2 `--shadow` command — passed.
- Promptfoo exact no-cache evaluation — passed from the shadow gate.
- Phoenix loopback redaction inspection — seven expected spans and zero
  violations, passed from the shadow gate.
- `/connections` Ontology automation test file — passed from the shadow gate.
- Final report sanitization scan — passed.

## Known Stubs

None. Per-pair observed quality values are intentionally `null` until real
expert-adjudicated labels exist; this is explicit missing evidence and keeps
release blocked rather than simulating metrics.

## User Setup Required

None outstanding. Required credentialed values were supplied for this run and
the reusable environment contract is documented in
`docs/ontology-discovery-operations.md`.

## Next Phase Readiness

- Phase 13 is complete for shadow-only operation, deterministic publication,
  rollback, durable evaluation, and operational observability.
- Production model admission remains disabled. Every pair requires at least 30
  consecutive shadow days and 200 expert-adjudicated eligible proposals before
  a new reviewed plan may even consider an activation interface.
- Root Phase 03.1 remains the active workstream; only Phase 13 completion
  accounting changes.

## Self-Check: PASSED

- Required telemetry, Terraform, validator, runbook, and dated report artifacts
  exist.
- All four TDD task commits are present in repository history.
- The final report parses as PASS with no missing evidence, zero authoritative
  model edges, and BLOCKED/PENDING release status.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
