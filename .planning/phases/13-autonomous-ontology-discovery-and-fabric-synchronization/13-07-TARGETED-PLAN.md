# Plan 13-07 Targeted Deployment Review

**Generated:** 2026-09-06T16:50Z
**Status:** Reviewed plan only — **do not apply yet**  
**State source:** canonical local state from the main checkout  
**Variables:** canonical main `terraform.tfvars`, canonical deployment environment,
`image_tag=azure-mcp-timeout-20260906-1454`, and
`enable_ontology_curator_agent=true`  
**Planning mode:** `-refresh=false -lock=false` with explicit targets  
**Result:** 12 creates, 0 updates, 0 destroys

## Exact Targets

1. `azurerm_user_assigned_identity.ontology_coordinator`
2. `azurerm_role_assignment.ontology_coordinator_acr_pull`
3. `fabric_workspace.ontology_discovery_state[0]`
4. `fabric_lakehouse.ontology_discovery_state[0]`
5. `fabric_workspace_role_assignment.ontology_coordinator_state[0]`
6. `azurerm_container_app_job.ontology_discovery`
7. `azurerm_user_assigned_identity.ontology_publisher`
8. `fabric_workspace.ontology_rbac_validation[0]`
9. `fabric_lakehouse.ontology_rbac_validation[0]`
10. `fabric_workspace_role_assignment.ontology_publisher[0]`
11. `terraform_data.foundry_ontology_curator_agent[0]`
12. `azurerm_container_app_job.ontology_rbac_validation[0]`

## Exact Planned Actions

| Address | Action | Purpose |
|---|---|---|
| `azurerm_user_assigned_identity.ontology_coordinator` | create | Dedicated scheduled coordinator identity |
| `azurerm_role_assignment.ontology_coordinator_acr_pull` | create | Image pull only for the coordinator identity |
| `fabric_workspace.ontology_discovery_state[0]` | create | Dedicated non-production durable-state boundary on the existing capacity |
| `fabric_lakehouse.ontology_discovery_state[0]` | create | Run-ledger and evidence-batch storage |
| `fabric_workspace_role_assignment.ontology_coordinator_state[0]` | create | Grant only coordinator Contributor in the state workspace |
| `azurerm_container_app_job.ontology_discovery` | create | Finite scheduled `run-once` coordinator pointed at the state lakehouse |
| `azurerm_user_assigned_identity.ontology_publisher` | create | Dedicated authoritative publisher identity |
| `fabric_workspace.ontology_rbac_validation[0]` | create | Separate non-production authorization-canary boundary on the existing capacity |
| `fabric_lakehouse.ontology_rbac_validation[0]` | create | Isolated canary stage/pointer target |
| `fabric_workspace_role_assignment.ontology_publisher[0]` | create | Grant only publisher Contributor in the validation workspace |
| `terraform_data.foundry_ontology_curator_agent[0]` | create | Publish the independent `gpt-5.4-mini` four-tool curator |
| `azurerm_container_app_job.ontology_rbac_validation[0]` | create | Manual-only three-UAI live validation runtime |

All planned actions are additive. No update, replacement, or destruction is
present. The targeted plan excludes
the Exposure enrichment Job, all existing Container App revisions, the legacy
`terraform_data.foundry_agent`, the specialist promotion gate, APIM, the
Foundry account/project, the production `fabric_workspace.ops`,
`fabric_lakehouse.context_graph`, and
`fabric_workspace_role_assignment.apps`, and all later Phase 13 resources.

## Authorization Evidence Design

- **API identity:** actual create-only stage and conditional-pointer attempts
  against only the validation lakehouse; only explicit `401`/`403` is accepted.
- **Coordinator identity:** actual create-only stage and conditional-pointer
  attempts against only the validation lakehouse; only explicit `401`/`403` is
  accepted. Its separate Contributor grant applies only in the state workspace.
- **Publisher identity:** actual canary stage, pointer CAS, rollback CAS, and
  cleanup under a unique prefix in the validation lakehouse.
- **Curator identity:** structural live evidence, because a safe validator
  cannot impersonate the Foundry project identity without granting it a writer
  tool. The validator requires both:
  1. live Fabric workspace-role assignments show no Admin, Member, or
     Contributor role for the curator object ID; and
  2. every deployed version under the ontology-curator agent name contains
     exactly the four reviewed Operations MCP read tools, the expected model,
     and the expected prompt hash.

All evidence records contain only operation, identity class, result, evidence
kind, timestamp, role-definition hash, and hashed correlation evidence.

## Fabric Granularity Decision

Official Fabric authorization exposes Admin, Member, Contributor, and Viewer at
workspace scope; it does not expose a custom path-level Lakehouse writer role.
The ineffective Azure resource-group custom role was removed. Two additive
non-production workspaces preserve least privilege without touching production:
coordinator alone is Contributor in the state workspace, and publisher alone is
Contributor in the validation workspace. API and curator receive no role in
either. The production app Contributor assignment remains unchanged until Plan
13-10. Application-level create-only writes, ETag CAS, fencing, canary
isolation, and rollback remain mandatory defense in depth.

## Remaining Blockers Before Apply

1. **Image artifact:** the reviewed plan still references
   `azure-mcp-timeout-20260906-1454`. That existing image does not contain the
   newly packaged validator script. Build and publish a new immutable API image,
   then regenerate this same targeted plan with that tag. Do not apply the
   current saved plan.
2. **Live evidence:** after the targeted apply, manually start only
   `aiops-dev-ontology-rbac-check` and retain its sanitized report. Plan 13-07
   remains incomplete until all four evidence classes pass.
3. **Curator read authority:** the existing API identity is used only to read
   the deployed Foundry agent definition. If its current Foundry Consumer /
   Runtime roles cannot list agent versions, validation must block. Do not
   broaden the API or validator Job to Foundry Project Manager merely to make
   the check pass.

The plan artifact is `/tmp/13-07-targeted.tfplan` with mode `0600`; it is
ephemeral, contains deployment inputs, and must not be committed or applied.
