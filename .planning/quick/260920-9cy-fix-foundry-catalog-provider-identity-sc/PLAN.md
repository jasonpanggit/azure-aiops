---
phase: quick-260920-9cy
quick_task: 260920-9cy
plan: 01
type: execute
wave: 1
depends_on: []
scope: "Fix Foundry candidate catalog provider identity uniqueness without changing runtime activation or tool contracts"
files_modified:
  - src/operations/foundry_candidate_catalog.py
  - tests/test_foundry_candidate_catalog.py
autonomous: true
requirements:
  - QUICK-260920-9CY
estimate:
  tokens: 12000
  raw_tokens: 12000
  tasks: 2
  confidence: low
must_haves:
  truths:
    - "Provider uniqueness is evaluated by the canonical case-insensitive pair `(agent_name, provider_version_id)` for the coordinator and all twelve specialists, so repeated bare provider version IDs belonging to different agents are valid (D-01)."
    - "The exact observed distribution—coordinator 6; network 16; vulnerability 17; patch 17; incident 16; change 17; governance 17; remediation 17; executive-summary 16; inventory-data-health, identity-access, finops, and resource-health-observability 1—produces all twelve specialists as `available_inactive` and `configured: false` (D-02, D-06)."
    - "A duplicate qualified identity fails closed case-insensitively, while duplicate manifest specialist IDs/names, malformed or credential-like IDs, IDs equal to latest/agent name/candidate version, wrong specialist mappings, and a malformed coordinator remain rejected (D-03, D-04)."
    - "Strict Pydantic `extra=\"forbid\"`, the existing candidate artifact shape, Operations-MCP-plus-Search-only tools, exact Azure AI Search target/query/cardinality contract, zero Azure MCP grants, and deterministic legacy runtime behavior remain unchanged (D-05, D-06, D-07)."
    - "Implementation, tests, review, commit, and pull request remain surgical and perform no Azure call, Terraform action, publication, deployment, promotion, or runtime activation (D-08, D-09, D-10)."
  artifacts:
    - path: "src/operations/foundry_candidate_catalog.py"
      provides: "Canonical qualified provider identity counting and coordinator/specialist collision enforcement"
    - path: "tests/test_foundry_candidate_catalog.py"
      provides: "Exact live-distribution acceptance plus qualified-collision and fail-closed regression coverage"
  key_links:
    - from: "src/operations/foundry_candidate_catalog.py::_validated_provider_id"
      to: "src/operations/foundry_candidate_catalog.py::validated_candidate_catalog"
      via: "validated and casefolded provider ID combined with casefolded agent name before collision counting"
      pattern: "agent_name.*casefold|provider_version_id.*casefold"
    - from: "src/operations/foundry_candidate_catalog.py::validated_candidate_catalog"
      to: "src/operations/foundry_agent.py::specialist_catalog"
      via: "validated candidate rows drive `available_inactive` without setting runtime `configured`"
      pattern: "validated_candidate_catalog|available_inactive"
    - from: "tests/test_foundry_candidate_catalog.py"
      to: "src/operations/specialists.v1.json"
      via: "manifest-derived twelve-specialist names and exact live provider-version distribution"
      pattern: "load_specialist_manifest"
---

<objective>
Correct the Foundry inactive-candidate catalog regression by qualifying provider version identity with its owning agent across the coordinator and all twelve specialists (D-01).

Purpose: The live service legitimately reuses bare provider version numbers across distinct agents; global bare-ID uniqueness currently hides valid candidates even though the provider identity is agent-qualified.
Output: A surgical two-file fix with exact live-distribution, collision, fail-closed, runtime-status, Search-contract, and no-Azure regressions, independently reviewed and proposed through a conventional pull request (D-02 through D-10).
</objective>

<execution_context>
@~/.copilot/gsd-core/workflows/execute-plan.md
@~/.copilot/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/11-cross-page-operations-copilot-orchestration-and-specialist-p/11-CONTEXT.md
@src/operations/foundry_candidate_catalog.py
@src/operations/foundry_agent.py
@src/operations/specialist_manifest.py
@src/operations/specialists.v1.json
@tests/test_foundry_candidate_catalog.py
@tests/test_foundry_agent.py
@tests/test_orchestration_parity.py
@tests/test_api_copilot_unified.py
@tests/test_specialist_manifest_packaging.py
@tests/test_mcp_protocol.py

This quick fix is compatible with the repository state: it does not address or weaken the active Phase 4 digest-to-workload, benchmark, or canary/rollback entry gate. It repairs a contained Phase 11 specialist-catalog regression on the clean `jasonpanggit-fix-foundry-catalog-identity` branch based on `origin/main`.

<decisions>
- D-01: Provider identity uniqueness is exactly `(agent_name.casefold(), provider_version_id.casefold())`, never a globally unique bare provider version ID.
- D-02: Cover the exact live distribution: coordinator `operations-copilot=6`; `network=16`; `vulnerability=17`; `patch=17`; `incident=16`; `change=17`; `governance=17`; `remediation=17`; `executive-summary=16`; and `inventory-data-health`, `identity-access`, `finops`, `resource-health-observability` each `1`.
- D-03: Preserve duplicate specialist ID/name rejection, immutable-ID rules, credential/malformed-ID rejection, and exact specialist-to-agent mapping checks; a duplicate qualified identity must fail closed.
- D-04: Coordinator validation remains artifact-wide: a malformed coordinator or a coordinator qualified-identity collision returns an empty catalog.
- D-05: Preserve every strict Pydantic model and `extra="forbid"` boundary; do not add evidence or compatibility fields to the artifact.
- D-06: Held validated candidates remain `available_inactive` with `configured: false`; deterministic legacy execution remains selected.
- D-07: Preserve Operations MCP plus exact Azure AI Search only: enabled true, the configured project connection and index, `vector_semantic_hybrid`, cardinality one, and no Azure MCP metadata or grants.
- D-08: Make no Azure/Fabric calls and run no Terraform, publication, deployment, promotion, rollback, or runtime activation command.
- D-09: Run focused and full relevant pytest, Ruff, diff hygiene, and a fresh independent code review before opening the PR.
- D-10: Expected implementation changes are exactly `src/operations/foundry_candidate_catalog.py` and `tests/test_foundry_candidate_catalog.py`; planning lifecycle artifacts are this `PLAN.md`, the generated `SUMMARY.md`, and the normal quick-task STATE entry only.
</decisions>

<interfaces>
From `src/operations/foundry_candidate_catalog.py`:
- `_validated_provider_id(value: Any) -> str` enforces provider-ID type, whitespace, syntax, and credential-marker rules.
- `_validate_provider_identity(provider_version_id: str, *, agent_name: str, candidate_version: str) -> None` rejects `latest`, the agent name, and the candidate version.
- `_CandidateArtifact` parses the coordinator strictly before specialist row filtering; artifact parse failure returns `{}`.
- `_agent_matches_manifest(...) -> bool` requires exact agent-name, model, prompt, MCP, Azure AI Search connection, index, and candidate-version mapping.
- `validated_candidate_catalog(manifest, *, now=None) -> dict[str, dict[str, Any]]` returns only validated candidate rows and is consumed by `specialist_catalog`.

From `src/operations/foundry_agent.py`:
- `specialist_catalog() -> list[dict[str, Any]]` reports a validated held candidate as `available_inactive`; `configured` becomes true only for an exactly configured runtime under `validated_promotion` or `validated_rollback`.

From `src/operations/specialist_manifest.py` and `src/operations/specialists.v1.json`:
- `LOCKED_SPECIALIST_IDS` fixes the ordered twelve-specialist portfolio.
- `SpecialistManifest.validate_specialist_graph` already rejects duplicate specialist IDs and Foundry names.
- Each specialist's `foundry.name` is the authoritative expected agent mapping; `azure_mcp_grants()` is empty for all specialists.
</interfaces>
</context>

<source_audit>

| Source | ID | Feature/requirement | Plan | Status | Notes |
|---|---|---|---|---|---|
| GOAL | — | Accept valid live Foundry candidates whose bare provider versions repeat across different agent names | 01 | COVERED | Task 1 |
| REQ | QUICK-260920-9CY | Canonical qualified provider identity across coordinator plus twelve specialists | 01 | COVERED | Task 1 |
| RESEARCH | — | Phase 11 requires one strict twelve-specialist manifest and exact parity across runtime/catalog/tool projections | 01 | COVERED | Existing manifest remains authoritative; Tasks 1–2 run parity contracts |
| RESEARCH | — | Optional Foundry/Search enrichment must degrade safely and never replace deterministic evidence access | 01 | COVERED | Tasks 1–2 preserve inactive/configured semantics and legacy runtime |
| CONTEXT | D-01 | Qualified casefolded identity pair, not global bare ID | 01 | COVERED | Task 1 |
| CONTEXT | D-02 | Exact coordinator and twelve-specialist live distribution | 01 | COVERED | Task 1 |
| CONTEXT | D-03 | Preserve specialist uniqueness, immutable/malformed/credential rules, mapping checks, and duplicate qualified rejection | 01 | COVERED | Task 1 |
| CONTEXT | D-04 | Malformed or colliding coordinator invalidates whole artifact | 01 | COVERED | Task 1 |
| CONTEXT | D-05 | Strict schema with no artifact evidence extras | 01 | COVERED | Tasks 1–2 |
| CONTEXT | D-06 | `available_inactive`, `configured: false`, deterministic legacy runtime | 01 | COVERED | Tasks 1–2 |
| CONTEXT | D-07 | No Azure MCP and exact Search contract | 01 | COVERED | Tasks 1–2 |
| CONTEXT | D-08 | No Azure calls or deployment | 01 | COVERED | Local-only commands in Tasks 1–2 |
| CONTEXT | D-09 | Focused/full tests, Ruff, independent review, commit, PR | 01 | COVERED | Tasks 1–2 |
| CONTEXT | D-10 | Surgical exact file set | 01 | COVERED | Tasks 1–2 |
</source_audit>

<dependency_graph>
1. Task 1 is the production tracer: one exact live artifact travels through strict artifact parsing, qualified identity validation, candidate projection, and runtime catalog status, proving all twelve held candidates survive without activation.
2. Task 2 depends on Task 1. It proves unchanged runtime/Search/security contracts, runs an independent review, creates the scoped conventional commit, and opens the pull request.
3. Both tasks intentionally share the same two files and therefore remain in one sequential Wave 1 plan.
</dependency_graph>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Accept the exact live distribution through qualified provider identities</name>
  <files>src/operations/foundry_candidate_catalog.py, tests/test_foundry_candidate_catalog.py</files>
  <reversibility rating="reversible">The change is isolated to an internal validation key and its regression tests; reverting restores the prior catalog behavior without migration or wire-format change.</reversibility>
  <behavior>
    - Build a candidate artifact with coordinator `operations-copilot` provider version `6` and the exact twelve specialist name/version pairs from D-02. `validated_candidate_catalog` returns all twelve rows in manifest order with the exact nested provider IDs.
    - Feed that same artifact through `specialist_catalog` under `legacy_unversioned` with version pinning required. Every specialist reports `status == "available_inactive"` and `configured is False`; deterministic runtime remains selected (D-06).
    - Repeated bare IDs `16`, `17`, and `1` are accepted because their agent names differ; case differences in a bare ID do not create a collision across distinct agent names (D-01).
    - Two specialist declarations with the same casefolded agent name and provider version are both excluded, including when one row has another malformed or wrong-mapping field; the duplicate valid identity cannot leak through row-local validation (D-03).
    - A coordinator may share a bare provider version with a differently named specialist, but a case-insensitive duplicate of a specialist's full qualified identity invalidates the whole artifact (D-01, D-04).
    - Existing malformed/credential ID, synthetic identity, wrong mapping, duplicate manifest ID/name, unknown-field, stale/partial artifact, and coordinator fail-closed tests continue to pass unchanged in meaning (D-03 through D-05).
  </behavior>
  <action>Write the regressions first in `tests/test_foundry_candidate_catalog.py`. Add one explicit live-distribution fixture or helper keyed by the twelve manifest specialist IDs and their exact D-02 provider values, then prove both direct candidate rows and the public `specialist_catalog()` statuses. Update collision regressions so they distinguish an allowed repeated bare ID owned by different agent names from a rejected duplicate qualified identity; include casefold variants and a coordinator collision. Keep the existing malformed coordinator parametrization artifact-wide and retain all row-local specialist rejection expectations.

In `src/operations/foundry_candidate_catalog.py`, replace the `Counter[str]` bare-ID census with one canonical qualified-identity representation shared by coordinator comparison, duplicate counting, and validated-row exclusion. Construct the key only after provider-ID syntax/credential validation and from the corresponding agent name, normalizing both components with `casefold()` exactly per D-01. Preserve the pre-parse raw specialist census so a duplicate qualified declaration cannot evade collision handling merely because another field later makes that row invalid. Continue parsing the coordinator as part of `_CandidateArtifact`, compare its qualified key against the specialist census, and retain artifact-wide refusal for coordinator invalidity/collision. Do not modify Pydantic models, returned row shape, manifest code/data, runtime activation logic, Search fields, MCP grants, Terraform, or scripts (D-03 through D-08, D-10).</action>
  <verify>
    <automated>uv run pytest -q tests/test_foundry_candidate_catalog.py &amp;&amp; uv run ruff check src/operations/foundry_candidate_catalog.py tests/test_foundry_candidate_catalog.py &amp;&amp; git diff --check</automated>
  </verify>
  <done>The exact live distribution yields twelve inactive/unconfigured specialists; bare versions may repeat across different names; duplicate qualified specialist identities are excluded; malformed or colliding coordinator identity still empties the catalog; all pre-existing strict validation behavior remains green (D-01 through D-08).</done>
</task>

<task type="auto">
  <name>Task 2: Prove unchanged contracts, independently review, commit, and open the PR</name>
  <files>src/operations/foundry_candidate_catalog.py, tests/test_foundry_candidate_catalog.py</files>
  <reversibility rating="reversible">Review fixes and the source commit remain confined to the same two internal files and can be reverted atomically.</reversibility>
  <action>Run the focused regression first, then the complete local catalog/runtime/parity/API/Search contract set named in `<verify>`. The packaging suite is local and mock-backed here; do not invoke its deployment scripts directly. Confirm that strict extras, no artifact evidence fields, empty Azure MCP projections, Operations-MCP-plus-Search-only payloads, exact Search connection/index/query/cardinality behavior, inactive `configured: false`, and deterministic compatibility runtime assertions still pass (D-05 through D-08).

Before committing, launch a fresh independent read-only code-review agent against only the two-file working diff. Ask it to check canonicalization consistency, malformed-row evasion, coordinator fail-closed ordering, false collisions, strict schema preservation, and regression completeness. Resolve every in-scope correctness or security finding in the same two files and rerun the focused suite, full relevant suite, Ruff, and `git diff --check`; stop and report rather than widening scope if a finding requires another implementation file (D-09, D-10).

Stage exactly `src/operations/foundry_candidate_catalog.py` and `tests/test_foundry_candidate_catalog.py`, inspect `git diff --cached --name-only`, and create the conventional commit `fix(foundry): qualify provider identities by agent` with trailer `Co-authored-by: Copilot App &lt;223556219+Copilot@users.noreply.github.com&gt;`. Push `jasonpanggit-fix-foundry-catalog-identity` to `origin`, then open a PR to `main` titled `fix(foundry): qualify provider identities by agent`. The PR body must summarize the qualified-key regression, exact live-distribution result, fail-closed cases, unchanged Search/MCP/runtime contracts, independent-review disposition, and exact test/Ruff commands. Do not request or perform deployment. Immediately notify the Unified deployment session per `AGENTS.md` with PR number/title/branch/base/merge state, a backend-only two-file scope summary, and that this is a follow-up to the inactive-catalog work with no deployment performed (D-08 through D-10).</action>
  <verify>
    <automated>uv run pytest -q tests/test_foundry_candidate_catalog.py &amp;&amp; uv run pytest -q tests/test_foundry_candidate_catalog.py tests/test_foundry_agent.py tests/test_orchestration_parity.py tests/test_api_copilot_unified.py tests/test_specialist_manifest_packaging.py tests/test_mcp_protocol.py &amp;&amp; uv run ruff check src/operations/foundry_candidate_catalog.py tests/test_foundry_candidate_catalog.py &amp;&amp; git diff --check</automated>
  </verify>
  <done>All focused and full relevant local contracts pass; independent review has no unresolved in-scope finding; the conventional commit contains exactly the two implementation files and required trailer; the PR targets `main`, records tests/review, and performs no Azure or deployment action (D-05 through D-10).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|---|---|
| Candidate artifact → strict Pydantic models | Untrusted JSON must not widen the artifact, tool, Search, identity, or validation contract. |
| Raw specialist declarations → identity census | Malformed rows must not hide a duplicate qualified identity that would let another row appear valid. |
| Validated candidate catalog → runtime catalog | Held evidence may change visibility to `available_inactive` but must not activate Foundry or set `configured`. |
| Local repository → GitHub pull request | Only the reviewed two-file source change and normal GSD planning lifecycle artifacts may enter the PR; no secrets or live evidence are added. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|---|---|---|---|---|---|
| T-9CY-01 | Spoofing | provider identity key | high | mitigate | Canonicalize both owning agent name and provider version case-insensitively, count exact qualified tuples, and test allowed bare-ID reuse versus rejected full-pair duplication. |
| T-9CY-02 | Tampering | malformed specialist row | high | mitigate | Preserve a raw declaration census before full row parsing so another invalid field cannot conceal a duplicate qualified identity. |
| T-9CY-03 | Elevation of privilege | inactive catalog → runtime | high | mitigate | Retain activation-source gating and assert every live-distribution row remains `configured: false` under deterministic legacy execution. |
| T-9CY-04 | Information disclosure | candidate artifact/tool metadata | medium | mitigate | Keep strict extras forbidden, add no evidence fields, retain credential-marker checks, and run exact Operations MCP/Search/no-Azure-MCP contract tests. |
| T-9CY-05 | Denial of service | legitimate repeated provider versions | medium | mitigate | Exact live-distribution regression proves repeated bare versions no longer suppress unrelated agent-qualified candidates. |
| T-9CY-06 | Repudiation | review and pull request | low | accept | Commit trailer, exact staged-file inspection, test commands, independent-review disposition, and PR record provide sufficient traceability for this local validator fix. |
| T-9CY-SC | Tampering | package-manager installs | low | accept | No dependency installation or package-manager mutation is planned. |
</threat_model>

<verification>
1. Run Task 1's focused candidate-catalog tests and Ruff before any commit.
2. Run Task 2's complete local catalog/runtime/API/parity/Search set; all external interactions remain mocked and no Azure command is executed.
3. Confirm the independent reviewer examined only the two-file implementation diff and all in-scope findings are resolved and retested.
4. Confirm the staged source commit lists exactly `src/operations/foundry_candidate_catalog.py` and `tests/test_foundry_candidate_catalog.py`, uses the required conventional subject and trailer, and has no secret or generated live evidence.
5. Confirm the PR targets `main`, documents tests and unchanged contracts, and explicitly states that no deployment was performed.
</verification>

<success_criteria>
- Provider uniqueness uses exactly the casefolded `(agent_name, provider_version_id)` pair across coordinator and all twelve specialists (D-01).
- The exact D-02 live distribution returns twelve candidate rows and twelve `available_inactive`, `configured: false` runtime catalog entries.
- Duplicate qualified identities and malformed/colliding coordinators fail closed without reviving global bare-ID rejection (D-03, D-04).
- Strict schema, credential/malformed/synthetic ID rejection, mapping checks, no evidence extras, no Azure MCP, exact Search, and deterministic legacy runtime contracts remain green (D-03 through D-07).
- Only the two expected implementation files change; local verification, independent review, conventional commit/trailer, push, PR, and Unified deployment-session notification complete without Azure calls or deployment (D-08 through D-10).
</success_criteria>

<output>
Create `.planning/quick/260920-9cy-fix-foundry-catalog-provider-identity-sc/SUMMARY.md` when done.
</output>
