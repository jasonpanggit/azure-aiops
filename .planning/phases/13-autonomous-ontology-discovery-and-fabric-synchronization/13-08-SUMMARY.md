---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 08
subsystem: ontology-governance
tags: [checkpoint, generation-cutover, rbac, foundry]

requires:
  - phase: 13-04
    provides: deployed proposal-only curator contract
  - phase: 13-06
    provides: complete consumer inventory and three-state compatibility suite
  - phase: 13-07
    provides: deployed identity separation and live RBAC evidence
provides:
  - approved active-generation pointer cutover
  - approved dedicated publisher RBAC boundary
  - confirmed Foundry prompt-agent runtime
affects: [13-09, ontology-publication]

key-decisions:
  - "approve-pointer-cutover: Plan 13-06 inventories all five consumer families and passes old/new/rollback compatibility tests."
  - "approve-publisher-rbac: Plan 13-07 live evidence proves API/coordinator denial, publisher stage/CAS/rollback, and curator read-only isolation."
  - "prompt-agent: no executed evidence requires custom hosted-agent protocols; scheduling, policy, publication, and rollback remain deterministic."

requirements-completed: [AUTO-ONT-03, AUTO-ONT-05, AUTO-ONT-07]
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 08: Consequential Cutover Decisions Summary

**All three evidence-backed decisions are approved, permitting Plan 13-09 to proceed with the prompt-agent architecture.**

## Decisions

| Decision | Selection | Evidence |
|---|---|---|
| Active-generation consumer cutover | `approve-pointer-cutover` | `13-06-SUMMARY.md`; complete five-family inventory; before/after/rollback suite |
| Publisher authorization boundary | `approve-publisher-rbac` | `13-07-LIVE-RBAC.json`; live denied-write matrix and control-plane audit |
| Agent runtime | `prompt-agent` | Deployed `gpt-5.4-mini` proposal-only curator with exactly four read-only tools |

## Rationale

- The pointer/alias contract has executable coverage across API, Fabric, agent,
  export, and semantic consumers, including rollback.
- Live evidence proves non-publisher identities cannot stage or move the
  validation pointer, while the publisher can stage, CAS, roll back, and clean
  up.
- The curator requires no custom protocol or agent-owned orchestration; hosted
  agent cost and runtime complexity are therefore unjustified.

## Gate Result

`runtime_selection=prompt-agent`

Plan 13-09 is unblocked. The hosted-agent exception was not selected and no
replanning branch is required.
