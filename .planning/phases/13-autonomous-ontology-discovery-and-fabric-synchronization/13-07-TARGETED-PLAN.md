# Plan 13-07 Targeted Deployment Review

**Generated:** 2026-09-06T17:34Z
**Status:** Reviewed plan only — **do not apply yet**  
**State source:** canonical local state from the main checkout  
**Variables:** canonical main `terraform.tfvars`, canonical deployment environment,
global app image preserved at deployed `azure-mcp-timeout-20260906-1454`,
currently deployed
`ontology_discovery_image_tag=phase13-ontology-corr-20260906-172205`, and
`enable_ontology_curator_agent=true`  
**Planning mode:** `-refresh=false -lock=false` with explicit targets  
**Current code-only delta:** 0 creates, 1 in-place update, 0 destroys,
0 output changes

## Deployed Phase 13 Target Set

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

The twelve resources above are now present in canonical state. The current
split-validator plan changes exactly one resource:

| Address | Action | Purpose |
|---|---|---|
| `azurerm_container_app_job.ontology_rbac_validation[0]` | update in place | Add `--write-matrix-only` and remove curator/Fabric-control-plane/Foundry-management environment inputs |

No replacement or destruction is present. The targeted plan excludes
the Exposure enrichment Job, all existing Container App revisions, the legacy
`terraform_data.foundry_agent`, the specialist promotion gate, APIM, the
Foundry account/project, the production `fabric_workspace.ops`,
`fabric_lakehouse.context_graph`, and
`fabric_workspace_role_assignment.apps`, and all later Phase 13 resources.
Existing API/web resources and their `api_image`/`web_image` outputs remain on
`azure-mcp-timeout-20260906-1454`.

## Authorization Evidence Design

- **Job write matrix (`--write-matrix-only`):**
  - **API identity:** actual create-only stage and conditional-pointer attempts
  against only the validation lakehouse; only explicit `401`/`403` is accepted.
  - **Coordinator identity:** actual create-only stage and conditional-pointer
  attempts against only the validation lakehouse; only explicit `401`/`403` is
  accepted. Its separate Contributor grant applies only in the state workspace.
  - **Publisher identity:** actual canary stage, pointer CAS, rollback CAS, and
  cleanup under a unique prefix in the validation lakehouse.
- **Deployer control-plane audit (`--control-plane-audit`):**
  - Queries live validation-workspace assignments under the existing deployment
    principal and requires publisher exactly Contributor while API,
    coordinator, and curator have no writer role.
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

The ACA Job performs no Fabric role-assignment or Foundry agent-management
request. The control-plane audit performs no OneLake write.

## Post-Apply Evidence Commands

Start the bounded Job write matrix:

```bash
az containerapp job start \
  --name aiops-dev-ontology-rbac-check \
  --resource-group aiops-dev-rg
```

Run the read-only deployer control-plane audit from this repository:

```bash
uv run --env-file /Users/jasonmba/workspace/azure-aiops/web/.env.local \
  python scripts/validate_ontology_publisher_rbac.py \
  --non-production \
  --fail-on-missing-evidence \
  --control-plane-audit \
  --config /Users/jasonmba/workspace/azure-aiops/fabric.config.deploy.yaml \
  --terraform-state /Users/jasonmba/workspace/azure-aiops/infra/terraform/terraform.tfstate
```

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

1. **Image artifact:** build and publish a new immutable ontology API image
   containing the split validator before apply. Do not overwrite
   `phase13-ontology-corr-20260906-172205`. Supplying the new
   `ontology_discovery_image_tag` will intentionally update both ontology Jobs
   while existing applications stay pinned to
   `azure-mcp-timeout-20260906-1454`.
2. **Live evidence:** after the targeted apply, retain both the manual Job
   write-matrix report and the local deployer control-plane audit report. Plan
   13-07 remains incomplete until both pass.
3. **Canonical tfvars drift:** the supplied main `terraform.tfvars` currently
   records `remediation-final-20260905-0035`, while canonical state and the
   deployed apps use `azure-mcp-timeout-20260906-1454`. The reviewed plan
   preserved the deployed global tag explicitly to prove zero output changes.
   Reconcile that external, gitignored tfvars value before apply or retain the
   same state-preserving value on the apply command.

The plan artifact is `/tmp/13-07-rbac-split.tfplan` with mode `0600`; it is
ephemeral, contains deployment inputs, and must not be committed or applied.
