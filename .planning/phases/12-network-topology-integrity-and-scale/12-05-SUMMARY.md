---
phase: 12-network-topology-integrity-and-scale
plan: 05
subsystem: network-semantics
tags: [fabric, cognitive-services, private-link, checkpoint, icons]
requires:
  - phase: 12-network-topology-integrity-and-scale
    plan: 03
    provides: scope-safe topology and evidence provenance
provides:
  - confirmed Fabric tenant/workspace private-link semantics
  - confirmed Cognitive Services per-resource private-endpoint semantics
  - V21 icon availability disposition
affects: [12-06, 12-10, network-gap-analysis, network-topology]
actuals:
  tasks: 2
  commits: 1
key-files:
  created:
    - .planning/phases/12-network-topology-integrity-and-scale/12-FABRIC-PRIVATE-LINK-DECISION.md
    - .planning/phases/12-network-topology-integrity-and-scale/12-05-SUMMARY.md
requirements-completed: [TOPO-02]
duration: 15min
completed: 2026-09-06
status: complete
---

# Phase 12 Plan 05: Private Link Semantics Checkpoint Summary

**Current Microsoft documentation resolves the checkpoint: Fabric controls are tenant/workspace scoped, Cognitive Services endpoints are per resource, and only Cognitive Services has a suitable V21 Azure architecture icon.**

## Accomplishments

- Confirmed that `Microsoft.Fabric/capacities` does not support the per-capacity private-endpoint control assumed by the existing gap rule.
- Confirmed that `Microsoft.CognitiveServices/accounts` supports resource-specific private endpoints.
- Inspected the official Azure Public Service Icons V21 archive: Cognitive Services is present; Microsoft Fabric is absent, and Azure Service Fabric icons are not substitutes.
- Recorded a per-type server, UI, and icon directive in `12-FABRIC-PRIVATE-LINK-DECISION.md`.

## Decision

Plan 12-06 must project both node types, suppress the false per-capacity Fabric `missing_private_endpoint` gap in the server payload, retain the Cognitive Services gap unchanged, add a tenant/workspace-scope qualification for Fabric, use the official V21 Cognitive Services SVG, and render Fabric with the existing icon-less fallback.

## Verification

- Decision artifact is non-empty and includes an explicit disposition table.
- Every technical conclusion links to current official Microsoft documentation.
- Azure Public Service Icons V21 was inspected directly; no package or production source was changed.
- `git status --short src/ web/src/` showed no Plan 12-05 source change before close-out.

## Deviations from Plan

None - the blocking checkpoint was resolved from current official Microsoft evidence under the orchestrator instruction to continue when the behavior was unambiguous.

## Issues Encountered

The Azure documentation MCP timed out, so the same first-party Microsoft Learn pages and official Microsoft icon archive were fetched directly. No claim relies on unofficial evidence.

## Self-Check: PASSED

The decision artifact exists, names both resource types and icon outcomes, records dated first-party sources, and gives Plan 12-06 an executable disposition without leaving a semantic choice open.
