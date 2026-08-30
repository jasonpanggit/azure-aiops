---
phase: 09-consumer-pivot
plan: 02
subsystem: api
tags: [inventory, foundry, fabric-iq, onboarding, governance]
requires:
  - phase: 09-consumer-pivot
    provides: typed contextual Copilot and deterministic Network findings
provides:
  - Runtime-bound scope-enforcing InventoryReadPort
  - Migrated onboarding identity query consumer with patch-domain joins
  - Independent Foundry specialist catalog/provisioning and governed Fabric IQ tool boundary
affects: [consumer-pivot, agents, inventory, operations]
tech-stack:
  added: []
  patterns: [provider-bound read ports, explicit unavailable enrichment, independently versioned prompt agents]
key-files:
  created:
    - tests/test_inventory_consumer_guards.py
    - tests/test_foundry_agent.py
  modified:
    - src/api/dependencies.py
    - src/api/runtime.py
    - src/onboarding/agent_queries.py
    - src/onboarding/inventory_read_adapter.py
    - src/operations/foundry_agent.py
    - src/operations/autonomous_investigation.py
    - src/operations/tools.py
    - infra/scripts/create-foundry-agent.sh
    - infra/terraform/foundry.tf
    - infra/terraform/variables.tf
    - infra/terraform/container_apps.tf
decisions:
  - Inventory identity is resolved through the runtime-bound InventoryReadPort; patch assessments remain a separate domain joined by resource ID.
  - Fabric IQ is optional, allowlisted, scope-filtered, provenance-stamped evidence and never an identity authority.
  - Existing single-agent Foundry configuration remains a backward-compatible Network fallback.
metrics:
  duration: 35min
  completed: 2026-08-28
  status: complete
actuals:
  tokens: 12500
  tasks: 2
  commits: 3
---

# Phase 09 Plan 02: Consumer Pivot Summary

**Scope-enforced inventory identity now powers onboarding queries, while independently released Foundry specialists and an explicitly degradable Fabric IQ enrichment boundary preserve local governance.**

## Accomplishments

- Added runtime/provider resolution for `InventoryReadPort` and exposed it through `ApiContext`.
- Migrated `ContextQueryService` identity rows to the read port while keeping patch assessments and advisor recommendations in their existing domain projection.
- Added static repository consumer guards and compatibility translation for legacy graph snapshots.
- Added independently named/versioned Foundry specialist metadata for Network, Vulnerability, Patch, Incident, Change, Governance, Remediation, and Executive Summary.
- Preserved legacy `FOUNDRY_AGENT_NAME` behavior as the Network fallback and provisioned all configured specialists through the existing script/IaC seam.
- Added allowlisted Fabric IQ relationship, topology, and policy enrichment with scope filtering, bounded payloads, source/freshness/authorization/provenance metadata, and explicit unavailable/denied states.

## Task Commits

1. `e62192c5` — `feat(09-02): route agent identity queries through inventory read port`
2. `5c7970e3` — `test(09-02): define specialist identity and grounding gates`
3. `23abab6e` — `feat(09-02): add governed Foundry specialists and Fabric IQ boundary`

## Verification

- `uv run python -m pytest tests/test_agent_queries.py tests/test_inventory_read_port.py tests/test_api_runtime.py tests/test_inventory_consumer_guards.py -q`
- `uv run python -m pytest tests/test_foundry_agent.py tests/test_fabric_client.py tests/test_api_runtime.py tests/test_api_copilot_investigation.py tests/test_inventory_consumer_guards.py -q`
- `bash -n infra/scripts/create-foundry-agent.sh`
- `terraform -chdir=infra/terraform fmt -check`

All passed. Existing unrelated working-tree changes were preserved and not included in these commits.

## Deviations from Plan

None — plan executed as written. Fabric IQ remains explicitly unavailable unless a governed provider is configured; no tenant-specific preview capability was assumed.

## Known Stubs

None.

## Self-Check: PASSED

- Summary exists at `.planning/phases/09-consumer-pivot/09-02-SUMMARY.md`.
- Commits `e62192c5`, `5c7970e3`, and `23abab6e` are present.
- All automated verification commands above passed.
