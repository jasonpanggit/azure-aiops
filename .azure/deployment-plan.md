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
- Fabric validation target: existing workspace with a separately named lakehouse
  (`OperationalContext_Validation`) and ontology (`Operational_Context_Graph_Validation`);
  production Fabric items remain untouched.

## Validation Proof

- 2026-08-22: `terraform -chdir=infra/terraform fmt -check` passed.
- 2026-08-22: `terraform -chdir=infra/terraform validate` passed.
- 2026-08-22: Azure CLI account context resolved to subscription
  `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`.
- 2026-08-22: Terraform state resolved registry
  `aiopsdevacrg6ludc.azurecr.io`.
- 2026-08-27: `terraform fmt infra/terraform/terraform.tfvars` completed, correcting the
  formatting-only preflight finding.
- 2026-08-27: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` passed with two image updates and no resource creation or
  destruction.
- 2026-08-27: `IMAGE_TAG=validation-20260827-1928 ./infra/scripts/build-and-push.sh`
  passed; API and web images were pushed to ACR. Web digest:
  `sha256:58d968dda5d4824d210ac93c77c5a177a4f110e4957317dcfc9956f6e52eea6c`.
- 2026-08-27: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh apply
  -auto-approve -var deploy_images=true -var image_tag=validation-20260827-1928`
  passed with 0 additions, 2 updates, and 0 destructions.
- 2026-08-27: ACA revisions reached `Succeeded`; API revision `aiops-dev-api--0000073`
  and web revision `aiops-dev-web--0000060` serve the validation tag.
- 2026-08-27: API `/health` and `/ready`, web `/api/config`, and web `/` returned
  successfully over HTTPS.
- 2026-08-28: New API/onboarding extraction changes require a fresh image build and
  ACA revision rollout; validation will use the separate Fabric lakehouse target.
- 2026-08-28: `AIOPS_BUILD_MODE=local ./infra/scripts/build-and-push.sh` built and
  pushed the API image; the web image was built natively by ACR Task `cr4j` after
  the local Apple Silicon npm build hit the known emulation failure. Web build
  completed `next build` successfully and pushed tag
  `api-onboarding-validation-20260828-0034`.
- 2026-08-28: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` produced an image-only plan: 0 additions, 2 updates,
  and 0 destructions.
- 2026-08-28: `./infra/scripts/deploy.sh apply -refresh=false -lock=false
  -auto-approve -var deploy_images=true -var image_tag=api-onboarding-validation-20260828-0034`
  completed with 0 additions, 2 updates, and 0 destructions. API revision
  `aiops-dev-api--0000074` received 100% traffic; web revision
  `aiops-dev-web--0000061` is healthy with 100% traffic.
- 2026-08-28: Deployed API `/health` and `/ready` returned HTTP 200; deployed
  web `/api/config` returned the API base URL successfully.

## All validation checks pass

- Terraform installed
- Azure CLI installed and authenticated to the target subscription
- Terraform initialized
- Terraform formatting check passes
- Terraform configuration validates
- Terraform plan reviewed for image-only ACA updates and no destructive changes
- Terraform state and template-variable checks pass
- `main.tfvars.json` JSON syntax is valid

- Terraform installed
- Azure CLI installed and authenticated to the target subscription
- Terraform initialized
- Terraform formatting check passes
- Terraform configuration validates
- Terraform plan reviewed for image-only ACA updates and no destructive changes
- Terraform state and template-variable checks pass
- `main.tfvars.json` JSON syntax is valid
- Terraform installed and Azure CLI installed.
- Azure CLI authenticated to the confirmed subscription.
- Terraform initialization, formatting, validation, and plan checks pass.
- Terraform state and template-variable checks pass.
- Existing Terraform-managed ACR and Container Apps resources are identified.
- Deployment uses the repository's `infra/scripts/build-and-push.sh` and `infra/scripts/deploy.sh` scripts.
  - Confirm Terraform and Azure CLI are installed.
  - Confirm Azure CLI is authenticated to the target subscription.
  - Run Terraform init, format check, validation, and plan.
  - Confirm Terraform state and template-variable checks pass.
  - Confirm `main.tfvars.json` JSON syntax.

## Role Assignment Verification

- Status: Verified
- Identities checked: shared user-assigned identity for the API and web apps; deploying principal
- Roles confirmed: `AcrPull` scoped to the ACR; `Key Vault Secrets Officer` scoped to the Key Vault; `Foundry Agent Consumer` scoped to the Foundry project; deploying principal has Key Vault Secrets Officer and Foundry Project Manager
- Issues: none found in the static Terraform review
