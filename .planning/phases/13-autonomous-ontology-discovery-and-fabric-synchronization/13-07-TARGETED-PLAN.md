# Plan 13-07 Targeted Deployment Review

**Generated:** 2026-09-06T16:29Z  
**Status:** Reviewed plan only — **do not apply yet**  
**State source:** canonical local state from the main checkout  
**Variables:** canonical main `terraform.tfvars`, canonical deployment environment,
`image_tag=azure-mcp-timeout-20260906-1454`, and
`enable_ontology_curator_agent=true`  
**Planning mode:** `-refresh=false -lock=false` with explicit targets  
**Result:** 7 creates, 1 in-place update, 0 destroys

## Exact Targets

1. `azurerm_user_assigned_identity.ontology_coordinator`
2. `azurerm_role_assignment.ontology_coordinator_acr_pull`
3. `azurerm_container_app_job.ontology_discovery`
4. `azurerm_user_assigned_identity.ontology_publisher`
5. `fabric_workspace_role_assignment.apps[0]`
6. `fabric_workspace_role_assignment.ontology_publisher[0]`
7. `terraform_data.foundry_ontology_curator_agent[0]`
8. `azurerm_container_app_job.ontology_rbac_validation[0]`

## Exact Planned Actions

| Address | Action | Purpose |
|---|---|---|
| `azurerm_user_assigned_identity.ontology_coordinator` | create | Dedicated scheduled coordinator identity |
| `azurerm_role_assignment.ontology_coordinator_acr_pull` | create | Image pull only for the coordinator identity |
| `azurerm_container_app_job.ontology_discovery` | create | Finite scheduled `run-once` coordinator |
| `azurerm_user_assigned_identity.ontology_publisher` | create | Dedicated authoritative publisher identity |
| `fabric_workspace_role_assignment.apps[0]` | update in place | Reduce shared API/web identity from Contributor to Viewer |
| `fabric_workspace_role_assignment.ontology_publisher[0]` | create | Grant the publisher Fabric Contributor, the platform's least broad Lakehouse writer role |
| `terraform_data.foundry_ontology_curator_agent[0]` | create | Publish the independent `gpt-5.4-mini` four-tool curator |
| `azurerm_container_app_job.ontology_rbac_validation[0]` | create | Manual-only three-UAI live validation runtime |

No resource replacement or destruction is present. The targeted plan excludes
the Exposure enrichment Job, all existing Container App revisions, the legacy
`terraform_data.foundry_agent`, the specialist promotion gate, APIM, the
Foundry account/project, the Fabric workspace/lakehouse, and all later Phase 13
resources.

## Authorization Evidence Design

- **API identity:** actual create-only stage and conditional-pointer attempts;
  only explicit `401`/`403` is accepted.
- **Coordinator identity:** actual create-only stage and conditional-pointer
  attempts; only explicit `401`/`403` is accepted.
- **Publisher identity:** actual canary stage, pointer CAS, rollback CAS, and
  cleanup under a unique non-production prefix.
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
The ineffective Azure resource-group custom role was removed. Publisher
Contributor is therefore the least broad working platform grant. API is reduced
to Viewer; coordinator and curator receive no Fabric workspace assignment.
Application-level create-only writes, ETag CAS, fencing, canary isolation, and
rollback remain mandatory defense in depth.

## Remaining Blockers Before Apply

1. **Image artifact:** the reviewed plan still references
   `azure-mcp-timeout-20260906-1454`. That existing image does not contain the
   newly packaged validator script. Build and publish a new immutable API image,
   then regenerate this same targeted plan with that tag. Do not apply the
   current saved plan.
2. **API write cutover:** changing the shared app identity from Contributor to
   Viewer intentionally removes existing direct Fabric write access. Confirm
   the non-production cutover window before apply; any still-active legacy API
   Fabric write path will be denied after the update.
3. **Live evidence:** after the targeted apply, manually start only
   `aiops-dev-ontology-rbac-check` and retain its sanitized report. Plan 13-07
   remains incomplete until all four evidence classes pass.
4. **Curator read authority:** the existing API identity is used only to read
   the deployed Foundry agent definition. If its current Foundry Consumer /
   Runtime roles cannot list agent versions, validation must block. Do not
   broaden the API or validator Job to Foundry Project Manager merely to make
   the check pass.

The plan artifact is `/tmp/13-07-targeted.tfplan` with mode `0600`; it is
ephemeral, contains deployment inputs, and must not be committed or applied.
