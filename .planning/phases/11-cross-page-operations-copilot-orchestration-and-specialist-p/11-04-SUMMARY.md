---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 04
subsystem: operations-copilot
tags: [manifest, specialists, foundry, mcp, authorization]
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 01
    provides: Governed Inventory & Data Health tracer and strict manifest loader
provides:
  - One strict versioned contract for the twelve locked domain specialists
  - Manifest-derived runtime, prompt, catalog, page-mapping, and Operations MCP projections
  - Exact read-only Operations and Azure MCP grant validation
  - Drift-blocking parity and security tests
affects: [11-03, 11-05, 11-06, 11-16]
actuals:
  tasks: 2
  commits: 3
tech-stack:
  added: []
  patterns:
    - Manifest projections replace parallel specialist ID, runtime, prompt, catalog, and MCP authorities
    - Azure MCP grants are accepted only from a pinned reviewed read-only catalog
    - Optional provider absence remains explicit and does not block deterministic execution
key-files:
  created:
    - tests/test_orchestration_parity.py
  modified:
    - src/api/dependencies.py
    - src/operations/specialists.v1.json
    - src/operations/specialist_manifest.py
    - src/operations/autonomous_investigation.py
    - src/operations/foundry_agent.py
    - src/operations/mcp_server.py
key-decisions:
  - "The locked portfolio is exactly twelve stable IDs; Inventory & Data Health retains the `inventory_data_health` ID and sole `inventory_resources` Operations grant."
  - "Executive Summary is aggregation-only and has no Operations or Azure MCP grants."
  - "Legacy MCP callers keep their prior catalog while specialist-bound calls receive exact manifest grants."
  - "The local Operations registry and reviewed MCP catalog must have exact tool-name equality."
  - "Security-sensitive grant, dependency, page, citation, and read-only fields are checked against an independent locked policy digest."
requirements-completed: [COP-03]
coverage:
  - id: 11-04-01
    description: "The twelve-specialist manifest rejects unknown fields, duplicate IDs, dependency cycles, credentials, missing tools, invalid pages, and mutation-capable grants."
    requirement: COP-03
    verification:
      - kind: unit
        ref: "tests/test_orchestration_parity.py"
        status: pass
    human_judgment: false
  - id: 11-04-02
    description: "Runtime definitions, prompts, catalogs, page mappings, provider resolution, and Operations MCP grants equal manifest projections."
    requirement: COP-03
    verification:
      - kind: integration
        ref: "tests/test_orchestration_parity.py tests/test_mcp_tools.py tests/test_foundry_agent.py tests/test_context_specialist_routing.py"
        status: pass
    human_judgment: false
completed: 2026-09-05
status: complete
---

# Phase 11 Plan 04: Specialist Manifest and Runtime Parity Summary

**The Operations Copilot now uses one strict manifest for twelve bounded specialists, with exact runtime, prompt, catalog, page-mapping, and read-only MCP projections.**

## Accomplishments

- Expanded the versioned manifest from the Inventory tracer to the complete locked twelve-specialist portfolio while preserving all existing IDs.
- Added strict cycle, credential, page, duplicate, implemented-tool, Azure read-only catalog, and aggregation-only validation.
- Replaced parallel runtime IDs, agent definitions, finding contracts, prompts, API/UI catalog metadata, and Operations MCP grants with manifest projections.
- Closed patch, change, governance, inventory, registry, and MCP parity gaps without adding mutation capabilities.
- Added bounded Inventory & Data Health, Identity & Access, FinOps, and Resource Health & Observability domains with explicit optional-provider degradation.
- Preserved legacy page anchors and MCP catalog behavior while making specialist-bound grants exact.

## Task Commit

1. **Tasks 1-2: Twelve-specialist contract and runtime parity** - `e0efdf26` (`feat`)
2. **Review hardening: argument schemas, fail-closed invocation, and locked policy parity** - `7bb6aa53` (`fix`)
3. **Final review hardening: complete manifest lock, bounded enrichment, and legacy routing** - `954e8106` (`fix`)

## Validation

- Plan-targeted suite: 64 passed.
- Adjacent Copilot, MCP, Foundry, specialist-output, routing, and Plan 11-01 regressions: 230 passed.
- Ruff passed for every changed Python file.
- `compileall` passed for every changed Python module.
- `git diff --check` passed.

## Review Fixes

1. Manifest-derived provider resolution now admits all twelve locked specialists through `ApiContext` instead of the previous eight-ID allowlist.
2. Existing `vulnerability`, `patch`, and `incident` snapshot page kinds retain their page-anchored specialist behavior.
3. Azure MCP grants now fail closed against an exact reviewed read-only catalog; unknown or mutation-capable names are rejected.
4. Context delegation reserves budget for every selected specialist and preserves the bounded post-delegation network enrichment pass.
5. Parameterized tools now run only when bounded required arguments can be derived; skipped tools perform no I/O and consume no call budget.
6. Remediation business-decision and Defender case tools now publish their exact required and optional MCP schemas.
7. Security-sensitive per-specialist grants and citation requirements are locked independently of mutable manifest input.
8. Credential markers embedded in manifest string values are rejected recursively, not only credential-shaped keys.
9. The policy digest now covers the complete normalized manifest, including output fields and statuses, routing intents, knowledge policy, and Foundry deployment metadata.
10. Post-delegation Fabric IQ enrichment validates required arguments and performs no provider I/O for an empty network subject.
11. Defender remediation cases omit the optional business-service filter unless the question names a service explicitly.
12. Legacy `resource` and `remediation` routes retain Governance alongside their added domain specialists.

## Scope and Merge Notes

- No web, Terraform, remediation, exposure, Fabric, deployment-plan, debug, tfvars, or `.planning/STATE.md` files were modified.
- `src/operations/tools.py` required no change, so there is no direct Plan 11-04 overlap with Exposure plans 03.1-14/21 in that file.
- The branch differs from `origin/main` in all seven implementation/test files listed above. These changes build on Plan 11-01 commit `da5de142`, so merge or cherry-pick must preserve that dependency.
- Terraform/packaging/live Foundry and Azure MCP projection remains Plan 11-05 work. Local runtime and catalog behavior degrade explicitly when those optional providers are unavailable.
- The copied `11-CONTEXT.md`, `11-PATTERNS.md`, and `11-REVIEW.md` support artifacts remain uncommitted and byte-identical to the requested main-checkout sources.

## User Setup Required

None.

---
*Phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p*
*Completed: 2026-09-05*
