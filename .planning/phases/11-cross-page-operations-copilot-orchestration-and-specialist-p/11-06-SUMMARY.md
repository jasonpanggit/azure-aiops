---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 06
subsystem: operations-copilot-continuity
tags: [threads, durability, scope, synthesis, citations, telemetry]
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 03
    provides: Canonical routing, history, scope, hints, and ledger behavior
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 05
    provides: Manifest-derived specialist and Foundry runtime contracts
provides:
  - Durable principal- and scope-bound investigation threads across restart and replicas
  - Fixed 12-turn, 1-hour idle, and 24-hour absolute continuity bounds with evidence aging
  - Conditional citation-closed executive synthesis over normalized transmitted evidence
  - Privacy-safe low-cardinality orchestration telemetry
  - Controlled continuity-unavailable and optimistic-conflict production responses
affects: [11-14, 11-15, 11-16]
actuals:
  tasks: 2
  commits: 18
tech-stack:
  added: []
  patterns:
    - Logical thread revisions are separate from document-store CAS revisions
    - Configured durable continuity fails closed; only intentionally unconfigured local mode may be memory-only
    - Principal and effective scope are revalidated from durable state on every operation
    - Scope narrowing is persisted before history or turn success and can never widen back
    - Executive validation uses only evidence IDs present in the exact bounded provider payload
    - Production continuity prefers strict document reads that distinguish absent data from unavailable or malformed data
    - Telemetry records controlled status and timing dimensions without prompts, identities, resource IDs, or evidence payloads
key-files:
  created:
    - .planning/phases/11-cross-page-operations-copilot-orchestration-and-specialist-p/11-06-SUMMARY.md
  modified:
    - src/operations/investigation_thread_store.py
    - src/operations/orchestration_service.py
    - src/operations/foundry_agent.py
    - src/operations/autonomous_investigation.py
    - src/operations/orchestration_contract.py
    - src/api/telemetry.py
    - src/api/routers/copilot.py
    - src/api/routers/multi_agent.py
    - tests/test_investigation_thread_store.py
    - tests/test_copilot_evaluation_v2.py
    - tests/test_api_copilot_unified.py
key-decisions:
  - "Thread state uses OneLakeDocumentStore.write(expected_revision=...) rather than last-writer-wins put(), with distinct thread_revision and storage revision fields."
  - "A configured durable store never returns a successful memory-only turn after read, write, or CAS failure; local memory-only behavior exists only when no durable adapter is configured."
  - "Every durable operation reloads current authority, rechecks principal and scope, and permanently persists any narrower effective scope before returning success."
  - "History and authorization retry one optimistic conflict after reloading and reapplying narrowing; a second conflict fails closed as ThreadRevisionConflict."
  - "Retained evidence is filtered by each turn's stored scope and marked historical until rechecked."
  - "Executive synthesis runs zero times for ordinary single-domain turns and at most once for explicit executive intent or two material cited domains."
  - "The synthesis allowlist is derived from the exact bounded normalized payload sent to the provider, preventing citations to retained entries truncated after the first 50."
  - "Validated synthesis is stored on the canonical result and projected through Copilot and multi-agent production responses as an optional backward-compatible field."
  - "Continuity storage outages project as HTTP 503 and unresolved optimistic conflicts as HTTP 409."
requirements-completed: [COP-01, COP-05]
coverage:
  - id: 11-06-01
    description: "Authorized continuity survives restart and replicas while enforcing ownership, permanent scope narrowing, retention bounds, and evidence aging."
    requirement: COP-05
    verification:
      - kind: unit
        ref: "tests/test_investigation_thread_store.py"
        status: pass
      - kind: api
        ref: "tests/test_api_copilot_unified.py"
        status: pass
    human_judgment: false
  - id: 11-06-02
    description: "Executive synthesis is conditional, bounded, citation-closed, degradable, persisted, and exposed by production routes."
    requirement: COP-01
    verification:
      - kind: unit
        ref: "tests/test_copilot_evaluation_v2.py tests/test_foundry_agent.py"
        status: pass
      - kind: api
        ref: "tests/test_api_copilot_unified.py tests/test_api_multi_agent.py"
        status: pass
    human_judgment: false
  - id: 11-06-03
    description: "Orchestration telemetry exposes controlled operational outcomes without high-cardinality or sensitive request content."
    requirement: COP-05
    verification:
      - kind: unit
        ref: "tests/test_copilot_evaluation_v2.py"
        status: pass
    human_judgment: false
completed: 2026-09-07
status: complete
---

# Phase 11 Plan 06: Durable Continuity, Conditional Synthesis, and Safe Telemetry Summary

**Operations Copilot now carries an authorized investigation thread safely across navigation, replicas, and restart, while optional executive synthesis remains conditional and citation-closed and orchestration telemetry remains low-cardinality and privacy-safe.**

## Accomplishments

- Replaced process-local continuity authority with revisioned durable thread documents that bind an opaque thread ID to a principal, effective scope, scope fingerprint, creation time, last-seen time, logical revision, storage revision, and retained turns.
- Enforced exactly 12 retained turns, a 1-hour idle timeout, a 24-hour absolute timeout, bounded cleanup, corrupt-record rejection, and immutable read-only projection of legacy investigation ledgers.
- Added replica-safe optimistic persistence through document-store CAS. Logical turn revisions remain stable across authorization/history touches while storage revisions advance independently.
- Made durability behavior explicit: unconfigured local execution can be `memory_only`, but a configured store must persist successfully before any turn, history touch, scope narrowing, or legacy binding is reported as successful.
- Added strict continuity reads that prefer `OneLakeDocumentStore.read_or_raise()` when available. Genuine missing documents remain absent; malformed, transport, and configured read failures become `ThreadStoreUnavailable`.
- Revalidated principal and current effective scope from durable storage on every read and mutation. Scope narrowing is permanent and wider historical turns are redacted before provider context or API projection.
- Made authorization and history scope narrowing safe under contention: one conflict reloads, reapplies narrowing and evidence aging, and retries CAS; a second conflict raises `ThreadRevisionConflict` instead of returning success while durable scope remains broad.
- Marked carried evidence historical until rechecked and applied each retained turn's stored scope before its evidence IDs or sources may enter executive synthesis.
- Added a deterministic synthesis gate: ordinary single-domain work returns specialist findings directly; explicit executive intent or at least two material cited domains admits one aggregation call.
- Sent only normalized findings and retained evidence to the executive provider. The payload is bounded before citation validation, and claims may cite only current or retained evidence IDs actually transmitted.
- Degraded invalid, unavailable, or citation-open synthesis to direct specialist findings plus a warning without discarding grounded evidence.
- Added an optional synthesis field to the canonical orchestration result, persisted exactly the validated synthesis, and exposed it through production Copilot/context and multi-agent projections without breaking legacy clients.
- Added controlled 503 projection for continuity-store unavailability and 409 projection for unresolved thread or legacy-binding contention, including the canonical history route.
- Added orchestration telemetry for controlled stage, specialist, status, fallback, evidence, duration, and budget outcomes. Privacy tests prove no question text, prompts, arguments, principal/thread/resource IDs, evidence payloads, tokens, or model rationale are recorded.
- Preserved Plan 11-03 canonical routing, history, scope, hint, and ledger behavior and retained ontology manifest parity from the merged canonical baseline without duplicating its implementation.

## Task and Review Commits

1. **Task 1 RED:** `aabfe91c` — `test(11-06): pin durable principal-bound thread lifecycle`
2. **Task 1 GREEN:** `08490d2e` — `feat(11-06): make investigation continuity durable and scope-bound`
3. **Task 2 RED:** `8ea590d3` — `test(11-06): pin conditional synthesis and telemetry privacy`
4. **Task 2 GREEN:** `315d43e2` — `feat(11-06): gate executive synthesis and telemetry`
5. **Replica-safe persistence review:** `761c5d2b` — `fix(11-06): enforce replica-safe durable orchestration`
6. **Contention and legacy recovery review:** `d6200f5b` — `fix(11-06): bound contention and legacy recovery`
7. **Fail-closed synthesis exposure review:** `a6ae8ee3` — `fix(11-06): fail closed and expose validated synthesis`
8. **Continuity outage RED:** `cc71a764` — `test(11-06): pin fail-closed continuity outages`
9. **Continuity outage GREEN:** `b8fb21a2` — `fix(11-06): fail closed on continuity outages`
10. **Strict-read/bounded-synthesis RED:** `aa032ed1` — `test(11-06): pin strict reads and bounded synthesis`
11. **Strict-read/bounded-synthesis GREEN:** `d604cca3` — `fix(11-06): harden strict continuity and synthesis bounds`
12. **Release lint:** `f390f875` — `style(11-06): normalize strict read test imports`
13. **History narrowing contention RED:** `81a552e8` — `test(11-06): pin history narrowing contention`
14. **History narrowing contention GREEN:** `6c3d5fbb` — `fix(11-06): persist history scope narrowing under contention`

Canonical merge commits:

- `5af7761d` — merged Plan 11-03 base `f3a4eb21`
- `46d46505` — merged final canonical base `ee1d650e`
- `e38dadd0` — merged manifest parity baseline `4446e098`
- `2a24f602` — merged latest `origin/main` baseline `be8162eb`

## Verification

| Gate | Command / scope | Result |
|---|---|---|
| Focused latest regressions | strict OneLake reads, bounded retained citation, history conflict projection, history narrowing CAS | pass |
| Plan 11-06 focused suites | `test_investigation_thread_store.py`, `test_copilot_evaluation_v2.py`, `test_api_copilot_unified.py` | pass |
| Final combined regression matrix | thread, synthesis, canonical Copilot, Foundry, orchestration parity/policy, multi-agent, ledger, legacy Copilot, MCP registry, and OneLake suites | **290 passed**, 1 pre-existing Starlette/httpx deprecation warning |
| Lint | Ruff on all Plan 11-06 source and focused test files | pass |
| Bytecode | `compileall` on `src` and focused tests | pass |
| Whitespace | `git diff --check` | clean |
| Independent comprehensive review | final branch through `6c3d5fbb` | pass; no remaining blockers |

## Review Hardening

The final behavior includes all review-mandated fixes:

1. Storage-level CAS replaced process-local optimistic checks and last-writer-wins persistence.
2. Production runtime wiring shares the durable ledger/thread adapter and preserves Foundry, telemetry, and legacy-binding seams.
3. Configured storage read/write/CAS failures fail closed and discard or reload uncommitted authority.
4. Retained evidence is filtered against each turn's stored scope before executive context construction.
5. Executive citation validation accepts authorized retained evidence but rejects evidence omitted by the 50-entry provider bound.
6. Validated synthesis persists and appears in production Copilot and multi-agent responses through an optional compatible contract field.
7. Production OneLake strict reads distinguish missing continuity from malformed or unavailable storage.
8. Thread and legacy-binding conflicts project as controlled 409 responses; unavailable continuity projects as 503.
9. History scope narrowing cannot return 200 until the narrowed durable scope is persisted, including one-retry/two-conflict behavior.

## Deviations from Plan

**1. [Review fix] Extended the file surface to production contracts and routers**

- **Issue:** The original declared files could compute synthesis and continuity errors but could not expose them through the production result schema and routes.
- **Fix:** Added a backward-compatible optional synthesis field in `orchestration_contract.py` and updated only the Copilot and multi-agent projections required to persist/expose validated synthesis and map controlled 503/409 outcomes.

**2. [Review fix] Replaced the planned outage fallback with fail-closed configured durability**

- **Issue:** A configured durable adapter that failed could otherwise return a successful `memory_only` turn, violating restart/replica guarantees.
- **Fix:** Reserved memory-only behavior for intentionally unconfigured local execution and made configured read, write, malformed-data, and CAS failures controlled failures.

**3. [Review fix] Added replica-safe retries for narrowing touches**

- **Issue:** Returning history after a CAS conflict could expose a narrowed projection while durable authority remained broad.
- **Fix:** Authorization and history reload and retry narrowing once; sustained contention fails closed with a controlled conflict.

## Baseline and Delivery Status

- Final implementation HEAD before this summary: `6c3d5fbb0578a7762cdcff26f76f113ae4f68ef4`
- Latest fetched and merged `origin/main`: `be8162eb3c8cb29a03c842da91bb17e4402dad25`
- Merge-base with `origin/main`: `be8162eb3c8cb29a03c842da91bb17e4402dad25`
- Concurrent Exposure work remained disjoint; no web, exposure, vulnerability, remediation, network, or Terraform implementation was changed by Plan 11-06 commits.
- No shared planning state or roadmap file was edited by Plan 11-06; upstream planning changes entered only through the requested canonical merges.
- Nothing was pushed or deployed.
