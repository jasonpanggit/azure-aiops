# Azure AI Operations Platform

## What This Is

Azure AI Operations Platform is an internal operations workbench for SRE, cloud
platform, and security teams. It combines Azure resource and operational data,
semantic graph intelligence, evidence-backed investigations, and approved
remediation workflows in one dashboard and API.

## Core Value

Operators can move from a detected Azure situation to an evidence-backed,
auditable, human-approved remediation without losing context or control.

## Requirements

### Validated

- ✓ Azure Resource Graph discovery and normalized operational data ingestion — existing
- ✓ OneLake/Delta persistence and Fabric Ontology projection — existing
- ✓ FastAPI API with Entra authentication and operational routers — existing
- ✓ Semantic, hybrid, live, and evidence-backed query services — existing
- ✓ Next.js operations workbench with graph and situation views — existing
- ✓ Domain intelligence for incidents, changes, lifecycle, patching, prediction, remediation, and vulnerabilities — existing
- ✓ Terraform deployment configuration for Azure Container Apps and Fabric — existing
- ✓ Scope-safe, bounded network topology with truthful coverage, governed policy refresh, private-link semantics, and diagnosable evidence — validated in Phase 12

### Active

- [ ] Deliver one integrated workflow from situation detection through evidence-backed explanation, recommendation, approval, and remediation execution.
- [ ] Provide a controlled Azure pilot experience spanning incidents, exposure, compliance, vulnerabilities, and the operational twin.
- [ ] Make every recommendation and executed change traceable through evidence, approval state, and audit history.
- [ ] Keep remediation safe by enforcing explicit human approval and bounded execution controls.
- [ ] Make the dashboard and API usable by SRE, platform, and security teams through consistent cross-domain workflows.

### Out of Scope

- Unapproved autonomous production changes — safety requires human approval for the pilot.
- Replacing Azure and enterprise systems of record — this platform materializes governed projections and evidence.
- A separate native mobile application — the initial pilot is web and API based.
- Broad multi-cloud support — Azure is the initial operational scope.

## Context

- This is a brownfield Python and Next.js repository with an existing codebase map in `.planning/codebase/`.
- The backend uses FastAPI, Azure identity, Resource Graph, OneLake/Delta, Fabric Ontology, and modular intelligence services.
- The frontend is a Next.js operations workbench using Fluent UI and Cytoscape for graph visualization.
- Existing infrastructure provisions Azure Container Apps and Fabric resources with Terraform.
- The intended first release is a controlled Azure pilot, not an unrestricted autonomous operator.

## Constraints

- **Safety**: Remediation must require explicit approval and remain bounded by policy and configuration.
- **Compatibility**: Extend the existing FastAPI, semantic, Fabric/OneLake, Terraform, and Next.js architecture rather than introducing a parallel platform.
- **Security**: Preserve Entra authentication, least-privilege Azure access, secret isolation, and auditable actions.
- **Evidence**: Explanations and recommendations must link back to source data, provenance, and quality context.
- **Scope**: Prioritize an end-to-end Azure workflow across SRE, platform, and security use cases for the pilot.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use one integrated workflow across SRE, platform, and security | Operators need a shared operational view rather than disconnected tools | — Pending |
| Prioritize detect → explain → recommend → approved execution | This is the smallest complete value loop for the pilot | — Pending |
| Keep human approval before remediation | Prevents unsafe autonomous production changes | — Pending |
| Build on the existing Azure and Fabric architecture | The repository already contains the required ingestion, semantic, API, UI, and infrastructure foundations | — Pending |
| Enforce network scope before topology derivation | A single authorization seam prevents resource, relationship, finding, drill-down, agent, and MCP leakage | ✓ Validated in Phase 12 |
| Keep the topology API default compatible and let the web request bounded summary detail explicitly | Existing consumers retain byte-compatible behavior while enterprise canvases remain bounded and honest | ✓ Validated in Phase 12 |
| Evaluate Fabric private-link posture at tenant or workspace scope, not per capacity | Microsoft Fabric does not expose the per-capacity private-endpoint control assumed by the prior rule | ✓ Validated in Phase 12 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid
4. Update Context with current state

---
*Last updated: 2026-09-06 after Phase 12 completion*
