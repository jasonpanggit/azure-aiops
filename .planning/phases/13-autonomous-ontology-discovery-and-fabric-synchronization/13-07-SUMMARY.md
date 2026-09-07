---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 07
subsystem: ontology-deployment
tags: [ontology, foundry, container-apps-jobs, fabric, managed-identity, rbac]

requires:
  - phase: 13-02
    provides: durable finite coordinator and run-once CLI
  - phase: 13-04
    provides: proposal-only curator contract and four read-only tools
provides:
  - scheduled finite ACA ontology discovery Job with a dedicated coordinator identity
  - separately versioned Foundry ontology curator prompt agent
  - isolated non-production Fabric state and RBAC-validation workspaces
  - dedicated publisher identity and fail-closed live authorization evidence
affects: [13-08, 13-09, 13-10, ontology-publication, foundry-agents]

actuals:
  tasks: 3
  commits: 25

tech-stack:
  added: []
  patterns:
    - split operation evidence from privileged control-plane audit
    - isolate scheduled state and authorization canaries in separate Fabric workspaces
    - use a dedicated immutable image tag only for ontology Jobs

key-files:
  created:
    - infra/terraform/ontology_discovery_job.tf
    - infra/terraform/ontology_discovery_identity.tf
    - scripts/validate_ontology_publisher_rbac.py
    - .planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-07-LIVE-RBAC.json
  modified:
    - infra/terraform/foundry.tf
    - infra/terraform/variables.tf
    - infra/scripts/create-foundry-agent.sh
    - tests/test_ontology_discovery_job_infra.py
    - tests/test_ontology_publisher_identity.py
    - tests/test_ontology_curator_infra.py

key-decisions:
  - "Fabric Contributor is the platform's least broad working Lakehouse writer role, so it is granted only to isolated coordinator/publisher workspaces."
  - "Production API Fabric permissions stay unchanged until Plan 13-10 migrates legacy write paths."
  - "The curator remains outside the interactive specialist manifest and has exactly four read-only ontology tools."
  - "Live write behavior runs inside a manual three-UAI Job; role and agent-definition audit runs separately under the deployer."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-03, AUTO-ONT-05, AUTO-ONT-07]

completed: 2026-09-07
status: complete
---

# Phase 13 Plan 07: Autonomous Ontology Deployment Summary

**A scheduled browser-independent discovery Job, proposal-only Foundry curator, and isolated least-privilege publisher boundary are deployed and live-verified.**

## Accomplishments

- Deployed `aiops-dev-ontology-discovery` on a 15-minute UTC schedule with a dedicated coordinator identity, finite timeout/retry policy, and no publisher credential.
- Deployed `aiops-ontology-curator-agent` on `gpt-5.4-mini` with exactly four reviewed Operations MCP read tools.
- Created separate non-production Fabric workspaces/lakehouses for durable coordinator state and authorization canaries, reusing the existing Fabric capacity.
- Deployed a manual-only RBAC validation Job and proved API/coordinator stage and pointer writes are denied while publisher stage/CAS/rollback/cleanup succeeds.
- Proved by control-plane audit that publisher alone is Contributor in the validation workspace and the curator has no writer role or writer tool.

## Deployment Evidence

- Immutable API image: `aiops-api:phase13-ontology-split-20260906-173930`
- Digest: `sha256:865bc6aed31e7eb0930962cf825b87aeac7d8526a903ab73d6bf8bc7a3fd3ba1`
- Infrastructure apply: 12 resources added, 0 existing resources changed, 0 destroyed (4 successful creates before paused-capacity retry; 8 after capacity resume).
- Validator image updates: two in-place Job updates, 0 destroys.
- Live write matrix execution: `aiops-dev-ontology-rbac-check-yuywrdn` — succeeded.
- Sanitized retained evidence: `13-07-LIVE-RBAC.json`.
- Five most recent scheduled discovery executions: succeeded.

## Verification

- Phase 13 dependency preflight passed.
- Plan 13-07 unit/infrastructure suites passed (29 focused tests after validator split; raw-state and live-schema regressions added afterward).
- Relevant ontology/Foundry regressions passed with one existing skip.
- Ruff, Terraform formatting, Terraform validation, Python compile, and diff hygiene passed.
- Azure validation workflow completed with `Status: Validated`.
- Production API/web Container Apps, APIM, Foundry account/project, production Fabric workspace/lakehouse/roles, and global image outputs were unchanged.

## Deviations Resolved

1. Replaced an ineffective Azure resource-group custom data role with isolated Fabric workspace Contributor assignments, the least broad platform writer permission.
2. Decoupled curator deployment from the unrelated Phase 11 specialist-candidate flag.
3. Split non-production state and authorization canaries into separate workspaces rather than reducing production API permissions.
4. Added a manual three-UAI validation Job because local processes cannot impersonate unattached user-assigned identities.
5. Split actual write evidence from deployer-owned role/agent-definition inspection to avoid elevating the publisher.
6. Added client correlation fallback, raw Terraform dynamic-value decoding, and live Foundry `data`/`allowed_tools.tool_names` schema compatibility.

## Next Phase Readiness

- Plan 13-08 may evaluate the retained consumer, RBAC, and prompt-agent evidence.
- Authoritative publication remains disabled; model proposals remain shadow-only.
- The Fabric capacity is active so the scheduled coordinator can run.

## Self-Check: PASSED

- All required resources are provisioned and healthy.
- Live denied/allowed authorization evidence is retained and sanitized.
- Scheduled runs succeed without a browser.
- No production data plane or existing app resource was replaced.
