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
  - Additive, immutable specialist version rollout with a retained rollback target
  - Exact offline parity gate and read-only live parity gate with an explicit BLOCKED outcome
affects: [11-12, 11-16]
actuals:
  tokens: 20400
  tasks: 2
  commits: 4
tech-stack:
  added: []
  patterns:
    - Terraform decodes the committed manifest instead of restating specialist grants
    - Deployed agent names and version stamps are projected, never hand-listed
    - Promotion is a recorded decision that follows a parity gate, never precedes it
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
key-decisions:
  - "Terraform decodes src/operations/specialists.v1.json directly; the duplicated eight-specialist Operations/Azure grant maps are removed and no manifest tool name may appear as a string literal in foundry.tf."
  - "Deployed agent names are projected as `<prefix><manifest foundry.name><suffix>`, whose defaults reproduce the eight already-deployed names exactly, so the rollout adds four agents rather than orphaning eight."
  - "Deployed version is `<foundry_specialist_release>.<manifest foundry.version>`; the release default moves to 2026.09 and pinning it back to 2026.08 re-selects the previously published set."
  - "The manifest's `foundry.model` (gpt-4.1) is carried as `contract_model` and reported separately from the real Azure deployment name (`var.foundry_model_name`), because forcing them equal would point every agent at a model deployment that does not exist."
  - "`var.foundry_specialists` is retained as a deprecated compatibility input and surfaced as FOUNDRY_SPECIALISTS_LEGACY_JSON; it no longer drives any deployed definition."
  - "Live parity that cannot be performed reports `blocked` with exit code 3 and holds promotion; it is never reported as a pass."
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

**Terraform, Container Apps, the wheel, and the API image now project the twelve specialists from the one committed manifest, and no specialist version can be promoted without an exact parity gate that reports BLOCKED rather than passing when it cannot verify.**

## Accomplishments

- Replaced the duplicated eight-specialist Operations/Azure MCP grant maps in `foundry.tf` with `jsondecode(file(...))` of `src/operations/specialists.v1.json`, so all twelve agent names, versions, prompts, grants, and metadata are one decode away from the reviewed contract.
- Added `risk_context`, `search`, and `inventory_resources` to the Terraform tool registry, closing the gap that would otherwise have failed the plan when the four new specialists' grants were projected.
- Collapsed eight retyped role prompts into one shared behavioral contract plus a per-specialist domain directive, both indexed by manifest ID so a specialist without a reviewed directive fails at plan time instead of deploying a generic prompt.
- Projected deployed agent names and immutable version stamps from the manifest, reproducing the eight already-deployed names byte-for-byte and extending deterministically to the four new specialists.
- Generated the twelve `FOUNDRY_<SPECIALIST>_AGENT_NAME/_VERSION` Container Apps env pairs the API runtime reads, and published the manifest digest alongside them.
- Pinned the manifest at `operations/specialists.v1.json` in the wheel and added a build-time manifest assertion to the API image.
- Added `scripts/validate_specialist_parity.py`: six exact offline checks plus read-only live checks of deployed Foundry versions and both MCP `tools/list` catalogs.
- Reordered the rollout to create immutable versions → validate parity → write the promotion record, retaining the previously promoted set as an explicit rollback target.
- Made `validate-runtime-e2e.sh` run the parity gate before it prints any promotion decision, and restricted its report to an allowlist of IDs, statuses, and counts.

## Task Commits

1. **Task 1 (RED):** `f619571a` — `test(11-05): add failing manifest packaging and Terraform projection tests`
2. **Task 1 (GREEN):** `e6ff2855` — `feat(11-05): derive Foundry and container projections from the specialist manifest`
3. **Task 2 (RED):** `ed3d82a9` — `test(11-05): add failing offline/live parity and additive rollout tests`
4. **Task 2 (GREEN):** `6a0f00ac` — `feat(11-05): gate additive specialist rollout on exact offline/live parity`

## Verification

| Gate | Command | Result |
|---|---|---|
| Terraform format | `cd infra/terraform && terraform fmt -check` | pass |
| Terraform validate | `terraform validate -no-color` | `Success! The configuration is valid.` |
| Projection evaluation | `terraform console` on `local.foundry_specialist_deployment` / `local.foundry_specialist_instructions` | twelve distinct name/version/prompt entries |
| Wheel build | `.venv/bin/python -m build --wheel` | built; `operations/specialists.v1.json` present once and byte-identical to source |
| Focused tests | `pytest tests/test_specialist_manifest_packaging.py tests/test_orchestration_parity.py -q` | 44 passed |
| Offline parity | `python scripts/validate_specialist_parity.py --offline` | `status: pass`, 12 specialists, 0 failures, exit 0 |
| Live parity (unconfigured) | `python scripts/validate_specialist_parity.py --live` | `status: blocked`, `reason: live_parity_not_configured`, exit 3 |
| Shell syntax | `bash -n infra/scripts/create-foundry-agent.sh infra/scripts/validate-runtime-e2e.sh` | pass |
| Lint | `ruff check` on all files touched by this plan | pass |
| Bytecode | `compileall` on new/changed Python | pass |
| Whitespace | `git diff --check` | clean |
| Regression | full `pytest -q` | all passed |

## Blocked Live Gates

**Live specialist parity is BLOCKED and promotion is held.** `--live` requires `FOUNDRY_PROJECT_ENDPOINT`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `OPERATIONS_MCP_SERVER_URL`, and `AZURE_MCP_SERVER_URL`; none are present in this environment. The gate reports `blocked` with the missing variable *names* only and exits 3 — never 0 — so it cannot be mistaken for a pass. Offline parity remains fully runnable and green. This is the manual/environment gate 11-VALIDATION.md already records for COP-03, and Plan 12 repeats it against the deployed revision.

Nothing was deployed, applied, pushed, or switched. No live agent version was promoted.

## Deviations from Plan

**1. [Rule 3 - Blocking] Repointed `tests/test_foundry_tool_registry_matches_implementation.py` at the manifest**

- **Found during:** Task 1 regression run.
- **Issue:** Three tests in that file parsed the hardcoded `network = concat([...])` / `remediation = concat([...])` Terraform blocks that Task 1 is explicitly required to remove, so they failed by construction.
- **Fix:** Re-sourced "which specialist is assigned this tool" from `load_specialist_manifest()` instead of Terraform text, preserving every invariant the file guards (registry rows exist, advertised operations tools are implemented, no registry entry is unassigned, the remediation-decision tools are assigned to `remediation` alone).
- **Files modified:** `tests/test_foundry_tool_registry_matches_implementation.py`
- **Commit:** `6a0f00ac`
- **Scope note:** Outside the plan's declared file list, but the plan's stated behavior ("Replace duplicated Terraform specialist/grant maps with manifest decoding") is impossible without it.

**2. [Design] Manifest model vs. deployed model kept distinct**

The manifest declares `foundry.model = "gpt-4.1"`; the real Azure deployment is `var.foundry_model_name` (default `gpt-5.4-mini`). Making the manifest authoritative for the model would point every agent at a model deployment that does not exist. The projection carries both: `model` (the deployment) and `contract_model` (the manifest), and the parity report surfaces them separately rather than hiding the divergence. The manifest is locked by a policy digest, so reconciling the two is a separate reviewed change.

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

- **Live API shape is unexercised.** `run_live()` assumes the Foundry versions endpoint returns `{"value": [...]}` with `definition.tools[].allowed_tools` per `server_label`, and that each MCP server answers a JSON-RPC `tools/list`. Both are modeled on the existing scripts and research, but neither path has been executed against a live service. Any shape mismatch surfaces as `blocked: live_services_unreachable` or `agent_version_unreadable`, not as a false pass.
- **The "metadata switch" is a promotion record, not an HTTP call.** In this codebase the runtime selects a specialist version through the `FOUNDRY_<SPECIALIST>_AGENT_VERSION` environment, so promotion is modeled as a recorded decision rather than a speculative `PATCH` against an undocumented default-version field. `FOUNDRY_PROMOTION_RECORD` is unset by default, so the record is opt-in.
- **`MUTATION_MARKERS` in the validator is suffix-anchored** (`_apply`, `_send`, `_set`, `_start`, `_stop`) precisely because bare `apply`/`deploy`/`set` false-positived on the read tool `arm_get_deployment_status`. Worth a second look if the azmcp catalog grows.
- **Version stamp default moved to `2026.09`,** which produces a new version string for all twelve specialists. Rollback is `-var foundry_specialist_release=2026.08`.
- **Container Apps env ordering changed** because sixteen static `env` blocks became two `dynamic "env"` blocks (deterministic, key-sorted). A plan against a live workspace will show env reordering in addition to the four added specialists.
- **`.planning/STATE.md`, `ROADMAP.md`, and `REQUIREMENTS.md` were deliberately not updated** — the execution brief fences them off and STATE.md is known stale at Phase 10.
- **Pre-existing, untouched:** `ruff check scripts/` reports 20 errors in `scripts/delete-lakehouse-tables.py`, `scripts/deploy-relationship-suggestion-agent.py`, and `scripts/validate-lakehouse-tables.py`. Out of scope; the files this plan added or changed are clean.
- **`build` was installed into the local `.venv` only** to run the plan's wheel gate. `pyproject.toml` dependencies and `uv.lock` were not touched, so the packaging test skips itself where `build` is absent.

## Self-Check: PASSED

All ten declared/created artifacts exist on disk and all four task commits are present in `git log`.
