---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 04
subsystem: ontology-discovery
tags: [foundry, responses-api, pydantic, mcp, scope-isolation, async]

requires:
  - phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
    plan: 03
    provides: exact 50/200/40 EvidenceBatch contracts and durable pre-dispatch records
  - phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
    plan: 06
    provides: request-scoped immutable generation resolver used by Operations tools
provides:
  - proposal-only async Foundry Responses adapter with strict local ProposalBatch validation
  - independent 60-second transport, two-retry, and two-repair safety budgets
  - exact four-tool read-only ontology curator MCP catalog
  - scope-filtered generation-pinned ontology evidence projections
affects: [13-05, 13-07, 13-08, 13-09, ontology-policy, foundry-agent-provisioning]

actuals:
  tokens: 14548
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - async managed-identity Responses transport with local whole-document validation
    - inert evidence user turns with sanitized schema-only repair prompts
    - specialist-specific MCP grant preceding separately-owned deployment provisioning
    - generation-selected provider reads filtered by authenticated effective scope

key-files:
  created:
    - src/ontology_discovery/curator.py
    - src/ontology_discovery/prompts/ontology_curator.md
    - tests/test_ontology_curator_agent.py
  modified:
    - src/ontology_discovery/contracts.py
    - src/operations/mcp_server.py
    - src/operations/tools.py
    - tests/test_foundry_tool_registry_matches_implementation.py
    - tests/test_mcp_protocol.py

key-decisions:
  - "Keep Foundry output advisory and untrusted: every complete response is parsed locally with strict Pydantic models, then checked against trusted batch endpoints, citations, and mutation tripwires."
  - "Set every Responses API hard ceiling to 2,000 tokens while separately enforcing the normal 8,000-input/1,200-requested-output admission budgets."
  - "Expose the ontology_curator runtime grant as exactly four read-only tools now; Plan 13-07 retains ownership of adding the deployed specialist to the generated Foundry manifest and Terraform."
  - "Reuse call_tool's one request-scoped GenerationSelection and authenticated Scope for curator reads rather than re-resolving or accepting model-supplied scope."
  - "Preserve root STATE.md Phase 03.1 ownership during this approved concurrent Phase 13 plan."

patterns-established:
  - "Curator recovery: transport retries and schema repairs have independent fixed budgets, and every individual call is deadline-bounded."
  - "Curator disclosure: repair prompts and audit metadata retain only schema locations/types, hashes, counts, usage, latency, and version identifiers."
  - "Ontology MCP reads: valid absence is status=empty, authorization/malformed calls use safe serialized errors, and result lists are capped before model exposure."

requirements-completed: [AUTO-ONT-03, AUTO-ONT-07]

coverage:
  - id: D1
    description: "Bounded async prompt-agent adapter produces only complete, cited, locally validated advisory ProposalBatch documents."
    requirement: AUTO-ONT-03
    verification:
      - kind: integration
        ref: "tests/test_ontology_curator_agent.py#test_normal_token_budgets_and_hard_api_ceiling_are_independent"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_curator_agent.py#test_transport_retries_and_schema_repairs_have_separate_bounds"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_curator_agent.py#test_proposal_parser_accepts_only_whole_strict_cited_json"
        status: pass
    human_judgment: false
  - id: D2
    description: "The ontology curator receives exactly four generation-pinned, scope-filtered, bounded read-only MCP tools."
    requirement: AUTO-ONT-07
    verification:
      - kind: integration
        ref: "tests/test_ontology_curator_agent.py#test_ontology_tools_reuse_generation_selection_and_enforce_result_caps"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_curator_agent.py#test_entity_evidence_filters_colliding_cross_scope_ids_without_disclosure"
        status: pass
      - kind: integration
        ref: "tests/test_mcp_protocol.py#test_ontology_curator_gets_exact_read_only_catalog_with_strict_schemas"
        status: pass
    human_judgment: false

duration: 17min
completed: 2026-09-06
status: complete
---

# Phase 13 Plan 04: Bounded Ontology Curator and Read-Only Evidence Tools Summary

**Async Foundry proposal curation now fails closed behind exact evidence/token/deadline budgets and four generation-pinned, scope-safe MCP reads.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-09-06T14:40:20Z
- **Completed:** 2026-09-06T14:57:42Z
- **Tasks:** 2
- **Files modified:** 8 implementation/test files

## Accomplishments

- Added a managed-identity async Responses transport with the correct Foundry audience, transient-status retry allowlist, circuit breaker, 60-second per-attempt deadline, and a hard 2,000-token API ceiling.
- Added strict `RelationshipProposal`/`ProposalBatch` contracts and deterministic checks that reject prose wrappers, extras, changed batch IDs, unknown endpoints/citations, model-owned scope/lifecycle fields, and mutation instructions.
- Kept repair calls fresh and bounded to two, with only the original bounded evidence, schema, and sanitized error locations/types crossing the repair boundary.
- Added exactly `list_changed_entities`, `get_entity_evidence`, `get_ontology_vocabulary`, and `search_relationship_history` for the curator, with strict no-extra argument schemas and 50/40/200 result caps.
- Integrated ontology tools with Plan 13-06's current request generation selection and existing authenticated scope filtering, including collision and non-disclosure tests.

## Task Commits

Each TDD task has a RED commit followed by its GREEN implementation:

1. **Task 1 RED: bounded curator contracts** - `54483c1a`
2. **Task 1 GREEN: strict async ontology curator** - `bb9ca92a`
3. **Task 2 RED: governed tool boundary contracts** - `77930c54`
4. **Task 2 GREEN: four scope-derived evidence tools** - `aa83626e`

## Files Created/Modified

- `src/ontology_discovery/curator.py` - Async token/transport boundary, hard budgets, strict parser, repair loop, and sanitized audit metadata.
- `src/ontology_discovery/contracts.py` - Strict proposal and proposal-batch Pydantic contracts.
- `src/ontology_discovery/prompts/ontology_curator.md` - Proposal-only, inert-data, no-scope-widening system contract.
- `src/operations/mcp_server.py` - Exact curator tool grant and strict argument schemas.
- `src/operations/tools.py` - Four bounded, scope-filtered, generation-selected read handlers integrated into the existing registry.
- `tests/test_ontology_curator_agent.py` - Caps, token estimation, timeout/retry/repair, parser, scope collision, disclosure, and tool-boundary coverage.
- `tests/test_foundry_tool_registry_matches_implementation.py` - Curator tool implementation/read-only registry guard.
- `tests/test_mcp_protocol.py` - Exact specialist catalog and strict schema contract.

## Decisions Made

- Foundry Agent Service structured output is not treated as an enforcement boundary; strict local `model_validate_json` and deterministic trust checks are mandatory.
- The normal requested output budget remains 1,200 tokens even though every API call carries the separately required 2,000-token hard maximum.
- Curator MCP registration is runtime-only in this plan. Plan 13-07 owns the specialist manifest/Terraform provisioning, avoiding premature infrastructure work.
- Operations tools consume the `GenerationSelection` already resolved once by `call_tool`, preserving Plan 13-06 rollback-safe behavior rather than duplicating pointer reads.
- Root planning state, roadmap, and requirements remain untouched because Phase 03.1 owns the active root planning workstream.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used the repository's native async-test pattern**
- **Found during:** Task 1 GREEN verification
- **Issue:** The repository does not install a pytest async plugin, so `pytest.mark.asyncio` could not execute the new async contract tests.
- **Fix:** Kept production code async end-to-end and drove coroutines with `asyncio.run` in synchronous pytest tests; no unplanned package was installed.
- **Files modified:** `tests/test_ontology_curator_agent.py`
- **Verification:** `uv run pytest -q tests/test_ontology_curator_agent.py -x`
- **Committed in:** `bb9ca92a`

**2. [Rule 2 - Missing Critical] Sanitized model-controlled validation paths**
- **Found during:** Task 1 GREEN adversarial audit test
- **Issue:** Pydantic error locations could echo an attacker-chosen extra field name into repair/audit metadata.
- **Fix:** Validation paths now retain only known schema fields and numeric indexes, replacing unknown segments with a fixed marker.
- **Files modified:** `src/ontology_discovery/curator.py`
- **Verification:** `test_repair_limit_fails_closed_and_audit_metadata_is_sanitized`
- **Committed in:** `bb9ca92a`

---

**Total deviations:** 2 auto-fixed (1 blocking issue, 1 missing critical security control).
**Impact on plan:** Both changes were required for executable tests and the specified disclosure boundary; no feature or infrastructure scope was added.

## Issues Encountered

- Context7 CLI was unavailable, so no package was downloaded automatically; implementation followed the version-locked Phase 13 AI specification and inspected repository-installed API patterns.
- Relevant regressions emit pre-existing Starlette/FastAPI deprecation warnings. They are recorded in `deferred-items.md` and were not changed by this plan.

## Verification

- Phase 13 dependency preflight — passed before and after implementation.
- Required Plan 13-04 suite — 29 passed.
- Relevant MCP, Foundry, and Operations regressions — 103 passed.
- Ontology discovery, coordinator, store, incremental, and pending-relationship regressions — 42 passed.
- `uv run ruff check src/ontology_discovery/curator.py src/ontology_discovery/contracts.py src/operations/mcp_server.py src/operations/tools.py` — passed.
- `git diff --check` — passed.
- All four task commits contain the required Copilot trailer.

## Known Stubs

None.

## User Setup Required

None - no deployment, credential setup, push, or external service mutation was performed.

## Next Phase Readiness

- Plan 13-05 may consume strict advisory proposals and remain responsible for deterministic policy/review decisions.
- Plan 13-07 may add the already-tested exact four-tool curator grant to the specialist manifest and Foundry/Terraform deployment path.
- No Plan 13-05 or later implementation was started.
- Phase 03.1 remains the active root planning workstream.

## Self-Check: PASSED

- All eight implementation/test artifacts and this summary exist.
- All four Task 1/Task 2 RED and GREEN commits are present in repository history.
- Summary status and requirement coverage are complete.
- Root `.planning/STATE.md` SHA-256 remains unchanged with Phase 03.1 active.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-06*
