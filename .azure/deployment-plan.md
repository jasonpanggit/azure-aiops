# Azure Deployment Plan

Status: Validated

## Objective

Build and push the API and web container images to Azure Container Registry,
then update the existing Azure Container Apps deployment.

## Workspace

- Mode: MODIFY existing deployed application
- Components: Python Operations API, Next.js web UI
- Target: existing Azure Container Apps environment and registry
- IaC: existing Terraform under `infra/terraform`
- Execution: `infra/scripts/build-and-push.sh`, then Terraform/app revision update

## Configuration

- Authentication: Entra ID for the API and web UI
- Secrets: Azure Key Vault and managed identity
- Images: existing ACR repositories for API and web
- No destructive resource deletion

## Validation Proof

- 2026-08-22: `terraform -chdir=infra/terraform fmt -check` passed.
- 2026-08-22: `terraform -chdir=infra/terraform validate` passed.
- 2026-08-22: Azure CLI account context resolved to subscription
  `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`.
- 2026-08-22: Terraform state resolved registry
  `aiopsdevacrg6ludc.azurecr.io`.
