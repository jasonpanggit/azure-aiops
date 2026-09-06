---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 05
subsystem: operations-copilot-deployment
tags: [manifest, terraform, foundry, packaging, parity, rollout]
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 04
    provides: Strict twelve-specialist manifest and runtime/MCP/catalog projections
provides:
  - Manifest-derived Terraform, Foundry, dual-MCP, and Container Apps projections
  - Wheel and container image manifest packaging pinned at the loader path
  - Two-stage immutable specialist rollout using validated provider version IDs with a retained rollback target
  - Exact offline parity gate and read-only live parity gate with an explicit BLOCKED outcome
affects: [11-12, 11-16]
actuals:
  tokens: 20400
  tasks: 2
  commits: 19
tech-stack:
  added: []
  patterns:
    - Terraform decodes the committed manifest instead of restating specialist grants
    - Deployed agent names and version stamps are projected, never hand-listed
    - Container Apps activates only an explicitly selected validated provider-ID mapping, never current-apply candidates
    - Candidate publication is disabled by default until the version-pinning runtime is separately deployed and verified
    - Shared Operations Copilot narration is pinned and live-validated with the specialist provider-ID set
    - Rollback mappings remain immutable until an operator supplies a new rotation epoch
    - Active and rollback gates validate their own artifact metadata, so rollback remains reachable across manifest changes
    - Promotion artifacts fail closed when corrupt and are replaced atomically
    - Foundry and APIM credentials use distinct token audiences
    - An unverifiable live gate reports BLOCKED rather than a pass
key-files:
  created:
    - scripts/validate_specialist_parity.py
    - tests/test_specialist_manifest_packaging.py
  modified:
    - infra/terraform/foundry.tf
    - infra/terraform/variables.tf
    - infra/terraform/container_apps.tf
    - infra/scripts/create-foundry-agent.sh
    - infra/scripts/validate-runtime-e2e.sh
    - pyproject.toml
    - Dockerfile
    - tests/test_foundry_tool_registry_matches_implementation.py
    - src/operations/foundry_agent.py
    - src/api/runtime.py
    - tests/test_foundry_agent.py
key-decisions:
  - "Terraform decodes src/operations/specialists.v1.json directly; the duplicated eight-specialist Operations/Azure grant maps are removed and no manifest tool name may appear as a string literal in foundry.tf."
  - "Deployed agent names are projected as `<prefix><manifest foundry.name><suffix>`, whose defaults reproduce the eight already-deployed names exactly, so the rollout adds four agents rather than orphaning eight."
  - "The manifest-derived `<foundry_specialist_release>.<manifest foundry.version>` value is a candidate contract stamp only; runtime activation uses the immutable provider version ID returned by Foundry."
  - "The manifest's `foundry.model` (gpt-4.1) is carried as `contract_model` and reported separately from the real Azure deployment name (`var.foundry_model_name`), because forcing them equal would point every agent at a model deployment that does not exist."
  - "`var.foundry_specialists` is retained as a deprecated compatibility input and surfaced as FOUNDRY_SPECIALISTS_LEGACY_JSON; it no longer drives any deployed definition."
  - "Candidate publication is a separate, opt-in stage after the pinned runtime is deployed and explicitly verified; only a persisted artifact reviewed on a later plan can activate provider IDs."
  - "Activation is explicit: legacy omits versions and fails closed to deterministic evidence, active selects the validated agents map, and rollback selects the validated prior mapping."
  - "Active and rollback modes pin the shared Operations Copilot coordinator to a live-validated provider ID; legacy may remain unversioned only before staged adoption."
  - "Successful publications do not move the rollback target unless a new non-empty rollback rotation epoch is supplied."
  - "When an activated provider version is configured, runtime uses the version-capable REST path and includes that exact ID in the outbound agent reference instead of relying on preview MAF name resolution."
  - "Live parity that lacks configuration reports `blocked` with exit code 3 and holds promotion; configured authentication, transport, schema, or parity errors fail closed."
requirements-completed: [COP-03, COP-05]
coverage:
  - id: 11-05-01
    description: "Terraform, Container Apps, the wheel, and the API image derive the twelve specialists' names, versions, prompts, and read-only grants from the one committed manifest."
    requirement: COP-03
    verification:
      - kind: infrastructure
        ref: "terraform fmt -check && terraform validate -no-color"
        status: pass
      - kind: build
        ref: "python -m build --wheel + wheel content inspection"
        status: pass
      - kind: unit
        ref: "tests/test_specialist_manifest_packaging.py"
        status: pass
    human_judgment: false
  - id: 11-05-02
    description: "Offline parity is exact and runnable without credentials; live parity is read-only, rejects extra/missing/nonexistent/mutation-capable grants, and reports an explicit blocked gate when unconfigured."
    requirement: COP-03
    verification:
      - kind: script
        ref: "scripts/validate_specialist_parity.py --offline (exit 0), --live unconfigured (exit 3)"
        status: pass
      - kind: unit
        ref: "tests/test_specialist_manifest_packaging.py tests/test_orchestration_parity.py"
        status: pass
      - kind: shell
        ref: "bash -n infra/scripts/create-foundry-agent.sh infra/scripts/validate-runtime-e2e.sh"
        status: pass
  - id: 11-05-03
    description: "Live Foundry/Operations MCP/Azure MCP catalog parity against a deployed revision."
    requirement: COP-05
    verification:
      - kind: live
        ref: "scripts/validate_specialist_parity.py --live"
        status: blocked
    human_judgment: true
completed: 2026-09-06
status: complete
---

# Phase 11 Plan 05: Manifest-Derived Deployment and Parity Gates Summary

**Terraform, Container Apps, the wheel, and the API image now project the twelve specialists from one committed manifest, while a two-stage gate ensures the running revision consumes only immutable Foundry provider IDs validated in a prior rollout.**

## Accomplishments

- Replaced the duplicated eight-specialist Operations/Azure MCP grant maps in `foundry.tf` with `jsondecode(file(...))` of `src/operations/specialists.v1.json`, so all twelve agent names, versions, prompts, grants, and metadata are one decode away from the reviewed contract.
- Added `risk_context`, `search`, and `inventory_resources` to the Terraform tool registry, closing the gap that would otherwise have failed the plan when the four new specialists' grants were projected.
- Collapsed eight retyped role prompts into one shared behavioral contract plus a per-specialist domain directive, both indexed by manifest ID so a specialist without a reviewed directive fails at plan time instead of deploying a generic prompt.
- Projected candidate agent names and contract stamps from the manifest, reproducing the eight already-deployed names byte-for-byte and extending deterministically to the four new specialists.
- Added a persisted promotion artifact and Terraform precondition resource: Container Apps reads exact provider IDs only from an explicitly selected validated active or rollback mapping.
- Pinned the manifest at `operations/specialists.v1.json` in the wheel and added a build-time manifest assertion to the API image.
- Added `scripts/validate_specialist_parity.py`: six exact offline checks plus read-only live checks of deployed Foundry versions and both MCP `tools/list` catalogs.
- Captured immutable provider version IDs from Foundry create/version responses, validated those exact IDs rather than list order or synthetic labels, and retained the prior provider-ID mapping as the rollback target.
- Split Foundry and APIM client-credential scopes, rejected non-HTTPS live endpoints before token acquisition, and made configured auth/service failures fail rather than degrade to `blocked`.
- Defaulted rollout validation to the repository virtualenv and added a candidate-record guard so an unavailable validator cannot republish the same unverifiable set repeatedly.
- Pinned runtime invocation to the activated provider ID: the REST payload includes the exact ID and versioned specialists bypass the preview MAF path, preventing candidate publication from changing active behavior.
- Added Terraform rollout triggers for the promotion artifact path, rollout script digest, and parity-validator digest so reviewed gate changes cannot leave the provisioner stale.
- Disabled candidate publication by default and made it depend on a separately deployed API revision plus an explicit version-pinning-runtime verification assertion, closing the first-rollout name/latest race.
- Added explicit `legacy`, `active`, and `rollback` activation modes. Legacy mode emits names without synthetic versions and sets `AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED=true`; both Foundry clients then reject unversioned configuration and preserve deterministic fallback.
- Applied identical fail-closed provider-ID normalization in rollout capture and live parity: version-resource paths reduce to their immutable final segment, while agent-resource IDs and malformed values are rejected.
- Preserved `api.runtime`'s injectable REST/MAF adapter boundary while retaining version-aware REST selection, restoring multi-agent test doubles without weakening provider-ID pinning.
- Published, live-validated, persisted, and emitted the shared Operations Copilot narrator's immutable provider version alongside the twelve specialist versions.
- Made rollback selection stable across later successful publications. A new operator-chosen rotation epoch advances it once; reusing that epoch cannot move it again.
- Split promotion-gate preconditions by activation target: active validates the current manifest mapping, while rollback validates the persisted prior status, digest, provider IDs, and coordinator independently.
- Added pre-publication corruption checks and same-directory atomic artifact replacement with flush/fsync/rename so an interrupted write cannot silently erase the validated active or rollback mapping.
- Made `validate-runtime-e2e.sh` run the parity gate before it prints any promotion decision, and restricted its report to an allowlist of IDs, statuses, and counts.

## Task Commits

1. **Task 1 (RED):** `f619571a` — `test(11-05): add failing manifest packaging and Terraform projection tests`
2. **Task 1 (GREEN):** `e6ff2855` — `feat(11-05): derive Foundry and container projections from the specialist manifest`
3. **Task 2 (RED):** `ed3d82a9` — `test(11-05): add failing offline/live parity and additive rollout tests`
4. **Task 2 (GREEN):** `6a0f00ac` — `feat(11-05): gate additive specialist rollout on exact offline/live parity`
5. **Review fixes (RED):** `84fabfdb` — `test(11-05): require a real promotion boundary and actual provider IDs`
6. **Review fixes (GREEN):** `63bf68d1` — `fix(11-05): enforce validated provider version promotion`
7. **Release lint:** `9b779b69` — `fix(11-05): satisfy parity release lint`
8. **Runtime pinning (RED):** `f78ce4d6` — `test(11-05): require pinned runtime invocation and rollout triggers`
9. **Runtime pinning (GREEN):** `b2091916` — `fix(11-05): pin runtime to promoted provider versions`
10. **Staged adoption (RED):** `e5ec6de0` — `test(11-05): require staged adoption and selectable rollback`
11. **Staged adoption (GREEN):** `d0c1b9f7` — `fix(11-05): stage specialist activation and rollback`
12. **Provider-ID normalization:** `b1d2c7fd` — `fix(11-05): normalize provider resource IDs`
13. **Runtime injection compatibility:** `0ace2450` — `fix(11-05): preserve runtime agent injection boundary`
14. **Coordinator/rollback safety (RED):** `c0530788` — `test(11-05): lock coordinator and rollback safety`
15. **Coordinator/rollback safety (GREEN):** `399d5587` — `fix(11-05): pin coordinator and stabilize rollback`
16. **Provider normalization hardening (RED):** `6d9524a6` — `test(11-05): require safe provider ID normalization`
17. **Provider normalization hardening (GREEN):** `92788d8c` — `fix(11-05): normalize only immutable version IDs`
18. **Rollback/artifact durability (RED):** `e6dcae11` — `test(11-05): require reachable rollback and durable artifacts`
19. **Rollback/artifact durability (GREEN):** `3c107d85` — `fix(11-05): validate rollback and persist artifacts atomically`

## Verification

| Gate | Command | Result |
|---|---|---|
| Terraform format | `cd infra/terraform && terraform fmt -check` | pass |
| Terraform validate | `terraform validate -no-color` | `Success! The configuration is valid.` |
| Projection evaluation | `terraform console` on `local.foundry_specialist_deployment` / `local.foundry_specialist_instructions` | twelve distinct name/version/prompt entries |
| Wheel build | `.venv/bin/python -m build --wheel` | built; `operations/specialists.v1.json` present once and byte-identical to source |
| Focused tests | `pytest tests/test_specialist_manifest_packaging.py tests/test_orchestration_parity.py tests/test_foundry_tool_registry_matches_implementation.py -q` | pass |
| Offline parity | `python scripts/validate_specialist_parity.py --offline` | `status: pass`, 12 specialists, 0 failures, exit 0 |
| Live parity (unconfigured) | `python scripts/validate_specialist_parity.py --live` | `status: blocked`, `reason: live_parity_not_configured`, exit 3 |
| Configured live failure behavior | focused mocked live tests | 401/403 → `live_auth_rejected`; 5xx/transport/schema/parity → fail; no configured error becomes `blocked` |
| Shell syntax | `bash -n infra/scripts/create-foundry-agent.sh infra/scripts/validate-runtime-e2e.sh` | pass |
| Lint | `ruff check` on all files touched by this plan | pass |
| Bytecode | `compileall` on new/changed Python | pass |
| Whitespace | `git diff --check` | clean |
| Foundry runtime regression | `pytest tests/test_foundry_agent.py tests/test_api_copilot.py tests/test_gold_grounding_specialist.py tests/test_foundry_incident_specialist.py tests/test_operations_mcp_foundry.py tests/test_specialist_manifest_packaging.py -q` | pass |
| Final combined Plan 11-05 + Foundry runtime gate | focused parity, registry, Foundry, API multi-agent, grounding, and MCP suites | 179 passed, 1 pre-existing Starlette deprecation warning |
| Independent comprehensive review | `f67f137e..3c107d85` including final delta re-review | no significant issues; rollback reachability and artifact durability fixes verified closed |

## Blocked Live Gates

**Live specialist parity is BLOCKED and promotion is held.** `--live` requires `FOUNDRY_PROJECT_ENDPOINT`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `OPERATIONS_MCP_SERVER_URL`, `AZURE_MCP_SERVER_URL`, `MCP_APIM_AUDIENCE`, and `FOUNDRY_CANDIDATE_MAPPING`; none are present in this environment. The gate reports `blocked` with missing variable *names* only and exits 3. Once those inputs are configured, authentication, transport, schema, pinned-version, model, catalog, and grant errors are failures rather than blocked outcomes. Offline parity remains fully runnable and green.

Nothing was deployed, applied, pushed, or switched. No live agent version was promoted.

## Deviations from Plan

**1. [Review fix] Added a two-stage provider-ID activation boundary**

- **Issue:** The initial implementation exposed manifest-derived candidate stamps to Container Apps before a live gate had validated the corresponding Foundry versions.
- **Fix:** Terraform now activates only an exact, digest-bound, twelve-specialist provider-ID mapping persisted by an earlier successful gate; otherwise it emits the legacy eight-agent mapping. The active Container App resource depends on the promotion gate preconditions.
- **Commits:** `84fabfdb`, `63bf68d1`

**2. [Review fix] Captured actual Foundry version IDs and separated token audiences**

- **Issue:** Synthetic labels and list order could select an unvalidated version, while the Foundry token could not authenticate to APIM MCP endpoints.
- **Fix:** Rollout captures service-returned IDs, pins validation to those IDs, preserves the prior mapping for rollback, uses separate Foundry/APIM scopes, validates HTTPS before token acquisition, and fails configured service errors closed.
- **Commits:** `84fabfdb`, `63bf68d1`

**3. [Review fix] Pinned actual runtime invocation and rollout invalidation**

- **Issue:** The initial provider-ID artifact controlled environment metadata, but the REST request referenced only the agent name and the preview MAF path could resolve by name. The rollout resource also did not change when its promotion path or validation implementation changed.
- **Fix:** Versioned runtime uses the REST client, its outbound `agent_reference` carries the exact activated provider ID, and Terraform hashes both rollout scripts while tracking the promotion artifact path.
- **Commits:** `f78ce4d6`, `b2091916`

**4. [Review fix] Separated pinned-runtime deployment, candidate publication, and activation**

- **Issue:** Publishing candidates while a legacy runtime could still resolve agents by name allowed first-rollout drift, and the persisted prior mapping was not selectable as a rollback target.
- **Fix:** Candidate publication is disabled by default, requires the API revision plus an explicit runtime-verification assertion, and cannot run without a persistent promotion path. Activation now explicitly selects `legacy`, `active`, or `rollback`; only validated provider-ID maps emit version variables, while legacy migration is unversioned and Foundry calls fail closed to deterministic evidence.
- **Commits:** `e5ec6de0`, `d0c1b9f7`

**5. [Review fix] Normalized the provider `id` fallback**

- **Issue:** Rollout capture and live parity initially disagreed on path-shaped IDs, and the first correction could mistake an agent-resource ID's final agent-name segment for a provider version.
- **Fix:** Both paths use the same normalization rules: plain provider IDs remain valid, paths are accepted only when they identify a `/versions/` resource, malformed values fall through consistently, and agent-resource IDs fail closed.
- **Commits:** `b1d2c7fd`, `6d9524a6`, `92788d8c`

**6. [Review fix] Preserved the API runtime injection boundary**

- **Issue:** Moving version-aware class selection into `operations.foundry_agent` bypassed `api.runtime`'s module-level adapter bindings, breaking four multi-agent tests and existing monkeypatch/test-double injection.
- **Fix:** The selector still decides versioned REST versus unversioned MAF, but accepts the runtime's injectable REST and MAF class bindings. Versioned configurations continue to force the supplied REST adapter.
- **Commit:** `0ace2450`

**7. [Review fix] Pinned the shared coordinator and made rollback rotation explicit**

- **Issue:** Pinning-required revisions had no `FOUNDRY_AGENT_VERSION`, permanently disabling the shared Operations Copilot narrator. Separately, every successful publication rewrote the positional rollback pointer and could silently reselect the mapping an operator had rolled back from.
- **Fix:** The candidate rollout now publishes and live-validates the coordinator's actual provider ID, promotion/rollback artifacts persist coordinator IDs, and active/rollback Container App revisions emit the selected `FOUNDRY_AGENT_VERSION`. Rollback mappings remain unchanged until a new non-empty operator rotation epoch advances them once.
- **Commits:** `c0530788`, `399d5587`

**8. [Review fix] Made cross-manifest rollback reachable and artifacts durable**

- **Issue:** Rollback mode still evaluated active-manifest preconditions, making a prior-manifest rollback impossible. Promotion records were also truncated in place and a corrupt existing record was treated as empty, risking silent loss of both mappings.
- **Fix:** Active and rollback modes now evaluate separate mapping-specific preconditions. Rollback trusts the persisted validated prior status/digest and requires non-empty provider IDs and a pinned coordinator without comparing it to the current manifest. Existing corrupt artifacts halt before publication, and successful records are flushed, fsynced, and atomically replaced.
- **Commits:** `e6dcae11`, `3c107d85`

**9. [Rule 3 - Blocking] Repointed `tests/test_foundry_tool_registry_matches_implementation.py` at the manifest**

- **Found during:** Task 1 regression run.
- **Issue:** Three tests in that file parsed the hardcoded `network = concat([...])` / `remediation = concat([...])` Terraform blocks that Task 1 is explicitly required to remove, so they failed by construction.
- **Fix:** Re-sourced "which specialist is assigned this tool" from `load_specialist_manifest()` instead of Terraform text, preserving every invariant the file guards (registry rows exist, advertised operations tools are implemented, no registry entry is unassigned, the remediation-decision tools are assigned to `remediation` alone).
- **Files modified:** `tests/test_foundry_tool_registry_matches_implementation.py`
- **Commit:** `6a0f00ac`
- **Scope note:** Outside the plan's declared file list, but the plan's stated behavior ("Replace duplicated Terraform specialist/grant maps with manifest decoding") is impossible without it.

**10. [Design] Manifest model vs. deployed model kept distinct**

The manifest declares `foundry.model = "gpt-4.1"`; the real Azure deployment is `var.foundry_model_name` (default `gpt-5.4-mini`). Making the manifest value an Azure deployment name would point agents at a deployment that does not exist. The projection and offline report carry both meanings explicitly, and live parity verifies the actual deployed model name for each pinned provider version.

## Known Stubs

None.

## Threat Flags

None. All three registered threats for this plan are mitigated:

| Threat | Mitigation |
|---|---|
| T-11-16 (Elevation, Terraform grants) | Exact manifest projection; offline check fails if any manifest tool name is restated in `foundry.tf`; live check rejects extra, missing, nonexistent, and mutation-capable grants and never widens to the broader set. |
| T-11-17 (Tampering, package/deployment) | Wheel force-include + image build-time manifest assertion + manifest digest env; versions are additive and immutable; promotion is written only after the gate. |
| T-11-18 (Info disclosure, rollout scripts) | Credential variables are tested for presence only; reports carry IDs, statuses, and counts; `validate-runtime-e2e.sh` output is a key allowlist, asserted by test. |

## Caveats for Independent Review

- **Live API shape is unexercised.** `run_live()` expects the Foundry versions endpoint to expose each immutable version ID and `definition.tools[].allowed_tools`, and each MCP server to answer JSON-RPC `tools/list`. A configured shape/auth/service mismatch fails closed; only missing configuration is blocked.
- **Promotion is deliberately staged.** Legacy mode may remain unversioned before adoption. First deploy and verify the pinning-required API runtime; this temporarily fails unversioned specialist/coordinator calls closed. A later opt-in apply creates and validates twelve specialist versions plus the coordinator version. Another reviewed apply explicitly selects `active` or `rollback`, which emits every validated provider ID.
- **Rollback rotation is explicit.** Normal successful publications update the active candidate mapping but preserve the selected rollback mapping. A new non-empty `foundry_specialist_rollback_rotation` epoch advances rollback once to the previously active mapping; reusing the epoch is idempotent.
- **Preview MAF is unavailable in the deployed pinning-required runtime without a provider ID.** Once a promoted provider ID is configured, the runtime selects the REST path so the request itself carries that ID.
- **`MUTATION_MARKERS` in the validator is suffix-anchored** (`_apply`, `_send`, `_set`, `_start`, `_stop`) precisely because bare `apply`/`deploy`/`set` false-positived on the read tool `arm_get_deployment_status`. Worth a second look if the azmcp catalog grows.
- **Version stamp default moved to `2026.09`,** but it is candidate metadata only. Rollback and activation use persisted provider version IDs, never the synthetic stamp.
- **Container Apps env ordering changed** because sixteen static `env` blocks became two `dynamic "env"` blocks (deterministic, key-sorted). A plan against a live workspace will show env reordering in addition to the four added specialists.
- **`.planning/STATE.md`, `ROADMAP.md`, and `REQUIREMENTS.md` were deliberately not updated** — the execution brief fences them off and STATE.md is known stale at Phase 10.
- **Pre-existing, untouched:** `ruff check scripts/` reports 20 errors in `scripts/delete-lakehouse-tables.py`, `scripts/deploy-relationship-suggestion-agent.py`, and `scripts/validate-lakehouse-tables.py`. Out of scope; the files this plan added or changed are clean.
- **`build` was installed into the local `.venv` only** to run the plan's wheel gate. `pyproject.toml` dependencies and `uv.lock` were not touched, so the packaging test skips itself where `build` is absent.

## Self-Check: PASSED

All declared/created artifacts exist on disk and all nineteen implementation/test commits are present in `git log`.
