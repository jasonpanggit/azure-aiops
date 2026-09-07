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
  - Bounded durable namespace cleanup with revision-conditional deletion
  - Fixed 12-turn, 1-hour idle, and 24-hour absolute continuity bounds with evidence aging
  - Conditional citation-closed executive synthesis over normalized transmitted evidence
  - Canonical wall-clock enforcement across executive admission and provider I/O
  - Collision-free current and retained citations across turns
  - Privacy-safe low-cardinality orchestration telemetry
  - Controlled continuity-unavailable and optimistic-conflict production responses
affects: [11-14, 11-15, 11-16]
actuals:
  tasks: 2
  commits: 26
tech-stack:
  added: []
  patterns:
    - Logical thread revisions are separate from document-store CAS revisions
    - Configured durable continuity fails closed; only intentionally unconfigured local mode may be memory-only
    - Principal and effective scope are revalidated from durable state on every operation
    - Scope narrowing is persisted before history or turn success and can never widen back
    - Executive validation uses only evidence IDs present in the exact bounded provider payload
    - Foundry JSON is structurally bounded before serialization and never character-sliced
    - Durable cleanup pages the thread namespace and conditionally deletes the exact revision inspected
    - Retained citations use deterministic thread/turn-qualified aliases while preserving source identity
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
    - src/storage/onelake_documents.py
    - src/operations/orchestration_contract.py
    - src/api/telemetry.py
    - src/api/routers/copilot.py
    - src/api/routers/multi_agent.py
    - tests/test_investigation_thread_store.py
    - tests/test_copilot_evaluation_v2.py
    - tests/test_api_copilot_unified.py
    - tests/test_foundry_agent.py
    - tests/test_onelake_documents.py
key-decisions:
  - "Thread state uses OneLakeDocumentStore.write(expected_revision=...) rather than last-writer-wins put(), with distinct thread_revision and storage revision fields."
  - "A configured durable store never returns a successful memory-only turn after read, write, or CAS failure; local memory-only behavior exists only when no durable adapter is configured."
  - "Every durable operation reloads current authority, rechecks principal and scope, and permanently persists any narrower effective scope before returning success."
  - "History and authorization retry one optimistic conflict after reloading and reapplying narrowing; a second conflict fails closed as ThreadRevisionConflict."
  - "Retained evidence is filtered by each turn's stored scope and marked historical until rechecked."
  - "Executive synthesis runs zero times for ordinary single-domain turns and at most once for explicit executive intent or two material cited domains."
  - "The synthesis allowlist is derived from the exact bounded normalized payload sent to the provider, preventing citations to retained entries truncated after the first 50."
  - "The REST provider path has both caller-level wall-clock enforcement and deadline-aware response streaming, so slow-drip responses cannot reset the canonical deadline."
  - "Durable expiry cleanup uses bounded OneLake namespace pages instead of a contended global index, covers idle and absolute expiry, and deletes only the inspected storage revision."
  - "Every retained citation receives a deterministic thread/turn-qualified alias before synthesis; aliases actually used by synthesis are returned and persisted."
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
        ref: "tests/test_api_copilot_unified.py tests/test_orchestration_parity.py"
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

> **Corrective supersession (2026-09-07):** The prior completion evidence through
> `6c3d5fbb` and its reported 290-test matrix is superseded. A late independent
> review found seven defects that invalidated that completion claim. The
> corrective pass from `f3d8a502` through `ff86b35c` reproduced the defects
> test-first, fixed them, remediated all follow-up review findings, passed the
> expanded 375-test backend matrix, and received a final independent no-findings
> verdict. The authoritative evidence is recorded below.

**Operations Copilot now carries an authorized investigation thread safely across navigation, replicas, and restart, while optional executive synthesis remains conditional and citation-closed and orchestration telemetry remains low-cardinality and privacy-safe.**

## Corrective Pass

- Replaced raw 24k character slicing with structurally bounded valid JSON. The executive citation allowlist is derived only from findings and retained entries present in the exact serialized payload.
- Enforced remaining canonical wall-clock budget before executive admission and across provider execution. REST calls use a bounded worker guard plus deadline-aware chunk reads, and Agent Framework calls use `asyncio.wait_for`.
- Replaced the process-wide durable thread index with bounded OneLake namespace paging. Cleanup discovers pre-existing documents after restart, covers idle and absolute expiry, limits scans and deletion attempts, and uses ETag/revision-conditional deletion so a refreshed thread survives a stale cleanup pass.
- Redacted scope-less legacy turns to `historical_scope_unverified` with no evidence or citations instead of relabeling historical payload as current authorized evidence. Source ledgers remain unchanged.
- Rebuilt CAS retry results before the retry append so the returned and persisted `thread_revision` matches the committed winner and both projections include a controlled reconciliation warning.
- Qualified current tool citations by thread, predicted revision, and unique turn token. Retained citations receive deterministic thread/turn-qualified aliases, and authorized retained aliases actually used by synthesis are returned, persisted, and preserved by canonical route projection.
- Added `/copilot/investigate-context` parity for `ThreadStoreUnavailable` as 503 and `ThreadRevisionConflict` as 409.

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

Corrective commits (authoritative):

1. **Seven-defect RED:** `f3d8a502` — `test(11-06): reproduce continuity review defects`
2. **Seven-defect GREEN:** `94da1f6d` — `fix(11-06): harden continuity review boundaries`
3. **Bounded JSON compatibility:** `326c0e21` — `fix(11-06): preserve bounded prompt disclosure`
4. **First-review remediation:** `19dd9932` — `fix(11-06): close independent review gaps`
5. **Retained-citation RED:** `65d2cd82` — `test(11-06): reproduce retained citation collisions`
6. **Retained-citation GREEN:** `3fe6b843` — `fix(11-06): qualify retained citations`
7. **Final boundedness RED:** `2a7b2b09` — `test(11-06): reproduce boundedness review gaps`
8. **Final boundedness GREEN:** `ff86b35c` — `fix(11-06): bound serialization and cleanup attempts`

## Verification

| Gate | Command / scope | Result |
|---|---|---|
| Focused corrective regressions | all seven late-review defects plus retained-citation, slow-drip timeout, restart cleanup, conditional-delete race, and bounded-failure tests | pass |
| Plan 11-06 focused suites | `test_investigation_thread_store.py`, `test_copilot_evaluation_v2.py`, `test_api_copilot_unified.py`, `test_foundry_agent.py`, `test_onelake_documents.py` | pass |
| Final combined regression matrix | current thread, synthesis, canonical Copilot, Foundry, orchestration parity/policy, ledger, context-specialist, incident, MCP registry, and OneLake suites | **375 passed**, 1 pre-existing Starlette/httpx deprecation warning |
| Lint | `python3 -m ruff check src tests` | pass |
| Bytecode | `python3 -m compileall -q src` | pass |
| Whitespace | `git diff --check` | clean |
| Independent comprehensive review | complete corrective diff through `ff86b35c` | initial findings fixed; final focused re-review reports no significant issues |

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
10. Generic Foundry context remains valid JSON and at most 24,000 characters even with thousands of list-valued keys.
11. Executive calls cannot outlive the canonical caller budget, including slow-drip REST responses.
12. Cleanup discovers durable records without a global index and bounds scans and deletion attempts even when every delete fails.
13. Scope-less historical payload is redacted until revalidated rather than imported under current authority.
14. CAS retry persists the committed winner revision and reconciliation warning.
15. Current and retained citation IDs cannot collide across turns; used retained aliases survive result and route projection.

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

## Corrective Baseline and Delivery Status

- Corrective implementation HEAD before this summary: `ff86b35c3709f8017da45b7a203854334946ad60`
- Corrective range: `c5595f7a7790d7b6cd86cff8e6d53e10d38b314b..ff86b35c3709f8017da45b7a203854334946ad60`
- Latest fetched `origin/main`: `c5595f7a7790d7b6cd86cff8e6d53e10d38b314b`
- Merge-base with `origin/main`: `c5595f7a7790d7b6cd86cff8e6d53e10d38b314b`
- The corrective pass remained backend-only; no Plan 11-14 web, Exposure, ontology, network, remediation, Terraform, `STATE.md`, or `ROADMAP.md` files were changed.
- Nothing was pushed or deployed.
