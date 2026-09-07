---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 14
subsystem: evaluation-observability
tags: [promptfoo, phoenix, opentelemetry, synthetic-evaluation, redaction, supply-chain]

requires:
  - phase: 13-04
    provides: bounded proposal-only curator, pinned prompt, and read-only evidence boundary
  - phase: 13-09
    provides: deterministic publication tracer, exact caps, shadow exclusion, and rollback
  - phase: 13-11
    provides: content-addressed EvaluationSnapshot contract and durable CAS store
provides:
  - locked opt-in Python evaluation environment using trusted-proxy Phoenix 20.4.0 and OpenTelemetry SDK 1.44.0
  - exact Promptfoo 0.122.2 synthetic-only no-cache prompt regression gate
  - repository evaluator with durable BLOCKED/PENDING EvaluationSnapshot evidence
  - finite loopback Phoenix lifecycle with explicit trace allowlist and forbidden-content inspection
affects: [13-15, release-evidence, ontology-observability, dependency-policy]

actuals:
  tokens: 540241
  tasks: 3
  commits: 5

tech-stack:
  added: [arize-phoenix 20.4.0, opentelemetry-sdk 1.44.0, promptfoo 0.122.2]
  patterns:
    - mutually exclusive uv api/eval extras preserve production dependency isolation
    - recorded local Promptfoo provider keyed only by allowlisted synthetic fixture IDs
    - content-free OpenTelemetry attributes with opaque correlation hashes
    - finite child-process launch, readiness, query, inspection, and termination

key-files:
  created:
    - evals/ontology-discovery/package.json
    - evals/ontology-discovery/package-lock.json
    - evals/ontology-discovery/promptfooconfig.yaml
    - scripts/evaluate_ontology_discovery.py
    - scripts/inspect_ontology_traces.py
    - tests/test_ontology_discovery_evals.py
    - tests/test_ontology_trace_redaction.py
  modified:
    - pyproject.toml
    - uv.lock
    - docs/FABRIC_ONTOLOGY_DEPLOYMENT.md
    - .planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-AI-SPEC.md
    - .planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-RESEARCH.md
    - .planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-14-PLAN.md
    - .planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-VALIDATION.md

key-decisions:
  - "Use Phoenix 20.4.0 as the newest release available from the trusted Microsoft proxy; canonical 20.7.0 remains legitimate but is not downloadable in this environment."
  - "Declare api and eval as conflicting uv extras so Phoenix's evaluation-only OpenAI line cannot alter a production API installation."
  - "Keep Promptfoo synthetic-only, local, telemetry-disabled, sharing-disabled, and backed by a trusted fixture-key provider."
  - "Persist evaluation evidence with release_eligible=false and report pair status only as BLOCKED/PENDING."
  - "Export only opaque hashes, bounded counts, and closed status values to loopback Phoenix."

patterns-established:
  - "Evaluation dependency gate: explicit trusted proxy plus committed uv/npm locks."
  - "Trace privacy gate: allowlist first, then forbidden-content/canary scan over queried Phoenix records."
  - "Local observer lifecycle: bind loopback, strip inherited credentials, disable telemetry/server bash, inspect, and terminate."

requirements-completed: [AUTO-ONT-03, AUTO-ONT-04, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: Pinned Promptfoo and Phoenix toolchains reproduce without entering the production API environment.
    requirement: AUTO-ONT-07
    verification:
      - kind: integration
        ref: "trusted-proxy uv sync --extra eval --locked; npm ci; promptfoo validate"
        status: pass
      - kind: integration
        ref: "uv sync --extra api --locked plus Python absence/version assertions"
        status: pass
    human_judgment: false
  - id: D2
    description: Synthetic Promptfoo regression and repository metrics pass while durable release evidence remains BLOCKED/PENDING.
    requirement: AUTO-ONT-04
    verification:
      - kind: e2e
        ref: "promptfoo eval -c evals/ontology-discovery/promptfooconfig.yaml --no-cache"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_discovery_evals.py and evaluate_ontology_discovery.py --fail-on-threshold"
        status: pass
    human_judgment: false
  - id: D3
    description: Self-hosted loopback Phoenix contains the seven correlated ontology lifecycle spans and no forbidden content.
    requirement: AUTO-ONT-07
    verification:
      - kind: integration
        ref: "tests/test_ontology_trace_redaction.py"
        status: pass
      - kind: e2e
        ref: "inspect_ontology_traces.py --launch-local --fail-on-redaction"
        status: pass
    human_judgment: false

duration: 35min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 14: Synthetic Evaluation and Sanitized Phoenix Summary

**Exact Promptfoo regression, durable repository metrics, and seven-stage sanitized OpenTelemetry traces now run entirely on checked-in synthetic data against a finite loopback Phoenix server.**

## Performance

- **Duration:** 35 min
- **Started:** 2026-09-07T02:48:34Z
- **Completed:** 2026-09-07T03:23:41Z
- **Tasks:** 3
- **Files modified:** 15

## Accomplishments

- Reconciled Phoenix to the newest trusted proxy-resolvable release, committed both package-manager locks, and isolated the evaluation stack from production API installation.
- Added an exact Promptfoo `--no-cache` gate over eight representative synthetic cases with local-only provider/data references and pinned fixture, prompt, schema, model, agent, and policy hashes.
- Added a complementary repository evaluator that checks quality, safety, recovery, audit, token, latency, and 50/200/40 bounds before durably writing a content-addressed, never-release-eligible `EvaluationSnapshot`.
- Added a finite Phoenix harness that launches on loopback with local temporary storage, strips credentials, disables telemetry and server-side bash, exports seven correlated lifecycle spans, queries them back, applies an explicit attribute allowlist and forbidden-content scan, and terminates the child.

## Task Commits

1. **Task 1: Lock and validate Promptfoo and Phoenix** - `a96ab90d` (chore)
2. **Task 2 RED: Synthetic evaluation contracts** - `c0172670` (test)
3. **Task 2 GREEN: Promptfoo provider and durable evaluator** - `b6607c07` (feat)
4. **Task 3 RED: Trace redaction contracts** - `a7412268` (test)
5. **Task 3 GREEN: Sanitized Phoenix lifecycle inspection** - `93098df8` (feat)

## Files Created/Modified

- `pyproject.toml` / `uv.lock` - Opt-in Phoenix/OpenTelemetry evaluation extra with explicit api/eval conflict and trusted-proxy lock.
- `evals/ontology-discovery/package.json` / `package-lock.json` - Exact private Promptfoo 0.122.2 toolchain.
- `evals/ontology-discovery/promptfooconfig.yaml` - Synthetic-only local provider, pinned hashes, and executable contract assertions.
- `scripts/evaluate_ontology_discovery.py` - Recorded provider, deterministic metric gate, durable snapshot writer, and sanitized span emitter.
- `scripts/inspect_ontology_traces.py` - Loopback Phoenix launcher, query client, allowlist scanner, and finite teardown.
- `tests/test_ontology_discovery_evals.py` - Config, provider, threshold, persistence, and admission tests.
- `tests/test_ontology_trace_redaction.py` - Lifecycle, correlation, endpoint, credential, and redaction tests.
- `13-AI-SPEC.md`, `13-RESEARCH.md`, `13-14-PLAN.md`, `13-VALIDATION.md`, and `docs/FABRIC_ONTOLOGY_DEPLOYMENT.md` - Version reconciliation, package evidence, proxy commands, and deployment guidance.

## Decisions Made

- Phoenix 20.4.0 is the newest trusted resolvable direct pin because canonical PyPI's 20.7.0 artifacts are unreachable while the approved Microsoft proxy mirrors through 20.4.0.
- The production `api` and local `eval` extras are mutually exclusive. An API sync installs Agent Framework 1.15.0/OpenTelemetry SDK 1.43.0 and no Phoenix; an eval sync installs Phoenix 20.4.0/OpenTelemetry SDK 1.44.0.
- Promptfoo remains exact-pinned at 0.122.2 and runs only the local Python provider against checked-in synthetic fixtures with telemetry, sharing, hosted evaluators, live data, and production endpoints disabled.
- Every evaluator output remains non-authoritative: durable `release_eligible` is false, model-derived authoritative edge count is zero, and status is BLOCKED/PENDING.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Isolated incompatible API and evaluation dependency lines**
- **Found during:** Task 1 lock generation
- **Issue:** Phoenix's pydantic-ai/OpenAI dependency line cannot coexist with the production Agent Framework OpenAI line in one selected environment.
- **Fix:** Declared `api` and `eval` as conflicting uv extras, preserving both in one universal lock while making accidental combined selection fail explicitly.
- **Files modified:** `pyproject.toml`, `uv.lock`, AI-SPEC/research/plan/deployment notes
- **Verification:** Both `uv sync --extra eval --locked` and `uv sync --extra api --locked` pass; API selection excludes Phoenix and preserves Agent Framework 1.15.0.
- **Committed in:** `a96ab90d`

**2. [Rule 1 - Bug] Avoided Promptfoo's Python 3.14 dynamic-loader dataclass failure**
- **Found during:** Task 2 exact no-cache Promptfoo gate
- **Issue:** Promptfoo 0.122.2 loads provider modules without first registering them in `sys.modules`; Python 3.14 dataclass processing then dereferenced a missing module.
- **Fix:** Used immutable-shape named tuples for internal result records, leaving the provider contract and evaluation behavior unchanged.
- **Files modified:** `scripts/evaluate_ontology_discovery.py`
- **Verification:** Exact Promptfoo no-cache gate passes 8/8 cases.
- **Committed in:** `b6607c07`

**3. [Rule 1 - Bug] Prevented verbose migration output from blocking Phoenix startup**
- **Found during:** Task 3 launch-local inspection
- **Issue:** Capturing Phoenix's verbose first-run migration output in an unread pipe filled the pipe and prevented readiness.
- **Fix:** Routed child output to the null device; readiness and exit status remain explicit and the child is always terminated.
- **Files modified:** `scripts/inspect_ontology_traces.py`
- **Verification:** Launch-local inspection returned seven expected spans and zero violations.
- **Committed in:** `93098df8`

---

**Total deviations:** 3 auto-fixed (1 blocking dependency issue, 2 runtime bugs).
**Impact on plan:** The fixes preserve the selected tools, exact pins, production dependency boundary, loopback-only topology, and redaction contract.

## Issues Encountered

- Context7 CLI was unavailable, so version-specific behavior was verified from the installed pinned package source, CLI help, and executed integrations.
- The exact Promptfoo development tree reports nine transitive npm advisories (eight high, one moderate). `npm audit --omit=dev` reports zero production vulnerabilities; the synthetic-only, credential-free, non-production boundary and exact approved pin were retained.
- Repository-wide Ruff still reports the 27 unrelated legacy-script findings already recorded in `deferred-items.md`; targeted Ruff for all Plan 13-14 Python files passes.

## Verification

- Phase 13 dependency preflight — passed.
- Trusted-proxy `uv lock --check` and `uv sync --extra eval --locked` — passed.
- `npm ci --prefix evals/ontology-discovery` and `npm audit --omit=dev` — passed.
- Promptfoo config validation — passed.
- Exact `promptfoo eval -c evals/ontology-discovery/promptfooconfig.yaml --no-cache` — 8 passed, 0 failed, 0 errors.
- `tests/test_ontology_discovery_evals.py` — 5 passed.
- Combined evaluator/redaction suite — 12 passed.
- Repository evaluator — passed, durable snapshot written, release status BLOCKED/PENDING.
- Phoenix `--launch-local` inspection — 7 lifecycle spans found, 0 violations.
- Evaluation snapshot and ontology E2E regressions — 13 passed.
- Targeted Ruff — passed.
- Full repository Ruff — attempted; stopped on 27 pre-existing findings already listed in the phase deferred-items ledger.

## Known Stubs

None.

## Threat Flags

None. The local OTLP/HTTP surface, package registry boundary, and synthetic fixture boundary are all explicitly covered by the plan threat model.

## TDD Gate Compliance

- Task 2 RED `c0172670` precedes GREEN `b6607c07`.
- Task 3 RED `a7412268` precedes GREEN `93098df8`.

## User Setup Required

None. The automated harness owns local Phoenix startup and teardown; the optional interactive command is documented for inspection.

## Next Phase Readiness

Plan 13-15 may consume the durable EvaluationSnapshot and sanitized Phoenix evidence. Model-derived admission remains BLOCKED/PENDING, and no deployment, push, merge, or Plan 13-15 work occurred.

## Self-Check: PASSED

- All nine required implementation, lock, configuration, test, and summary artifacts exist.
- All five task commits are present in git history.
- Root STATE remains on active Phase 03.1; only completed-plan accounting changed.
- The loopback Phoenix child was terminated after inspection.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
