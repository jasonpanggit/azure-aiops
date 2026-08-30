# Azure Deployment Plan

Status: Validated

## Objective

Build and push the API and web container images to Azure Container Registry,
then update the existing Azure Container Apps deployment.

Current repair: restore Foundry specialist narration on every contextual page by
accepting JSON media-type parameters at the existing APIM MCP policy, registering
all eight specialist clients in the API provider runtime, selecting the page's
specialist for narration, and deduplicating safe fallback warnings in the web UI.
APIM must be updated in place and must not be destroyed or replaced.

Current follow-up: make the Network specialist answer the operator's actual
question instead of emitting a findings-only JSON inventory, deduplicate
equivalent deterministic evidence, and suppress repeated finding cards when a
Foundry narration is present. APIM remains in place and is not destroyed or
replaced.

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

- 2026-08-30: Diagnosed contextual agent failures from Log Analytics:
  Foundry tool enumeration received APIM HTTP 415 because the MCP policy
  required an exact `application/json` header and rejected compatible media
  types with parameters.
- 2026-08-30: `.venv/bin/python -m ruff check src tests` passed.
- 2026-08-30: Full backend `pytest` suite passed.
- 2026-08-30: `npm run lint`, all 157 Vitest tests, and `npm run build`
  passed under `web/`.
- 2026-08-30: `terraform -chdir=infra/terraform fmt -check` and `validate`
  passed after formatting `variables.tf`.
- 2026-08-30: The generic Terraform preflight could not run its bare `plan`
  because this repository intentionally supplies required secret-backed inputs
  through `deploy.sh`. The canonical
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan` passed with
  the current image tag: 0 additions, 2 in-place APIM policy updates, and
  0 destructions. `azurerm_api_management.main` is unchanged.
- 2026-08-30: Foundry access roles remain least-privileged and assigned to the
  shared app identity: `Foundry Agent Consumer` plus
  `Foundry Project Runtime User`; deployment management remains separately
  assigned to the deployer.
- 2026-08-30: Network-response follow-up passed `ruff check src tests`, the
  complete backend suite (1,655 tests), frontend lint, all 158 Vitest tests,
  the Next.js production build, Terraform format check, and Terraform
  validation.
- 2026-08-30: Canonical `./infra/scripts/deploy.sh plan` for the Network
  response follow-up contains no APIM resource destruction or replacement.
  The only replacement is the non-resource `terraform_data.foundry_agent`
  provisioner trigger needed to publish updated Foundry agent instructions.
- 2026-08-30: Built and pushed API/web tag
  `network-direct-answer-20260830-1625`, then deployed it with 100% traffic on
  API revision `aiops-dev-api--0000128` and web revision
  `aiops-dev-web--0000095`. Terraform reported no Azure resource destruction;
  the one destroyed/recreated object was the expected local
  `terraform_data.foundry_agent` trigger.
- 2026-08-30: Live API `/health` and `/ready`, web `/`, and web `/api/config`
  returned HTTP 200. A direct live invocation of `aiops-network-agent` for
  `Can UAT reach PROD?` led with a concrete answer, cited topology evidence,
  and stated the unresolved UAT/PROD mapping instead of returning a generic
  findings JSON payload. Current API logs contain no MCP 415,
  `tool_user_error`, or Foundry contextual narration failure.
- 2026-08-30: Live RBAC verification confirmed app identity
  `2c367602-bb4f-4868-8dbb-7f4ca117a719` retains `AcrPull`,
  `Foundry Agent Consumer`, and `Foundry Project Runtime User`.
- 2026-08-22: `terraform -chdir=infra/terraform fmt -check` passed.
- 2026-08-22: `terraform -chdir=infra/terraform validate` passed.
- 2026-08-30: Fixed subscription-sync "Network request failed" bug — replaced
  `@app.middleware("http")` (Starlette `BaseHTTPMiddleware`) with pure ASGI
  `_ObserveMiddleware` in `src/api/app.py` to stop already-handled exceptions
  from re-raising and dropping the connection after a valid response was sent
  (commit `a35c1ca6`). `pytest tests/ -q -k "api or connection"` passed.
  Built/pushed `main-syncfix-20260830-1509` (api+web), deployed via
  `deploy.sh apply -auto-approve`; both apps serving the new tag. Post-deploy
  curl smoke test: `/health` 200, `/api/v1/subscription-connections/<id>/health`
  and `.../sync` for an unregistered id return clean `401` (auth-required),
  not a dropped connection.
- 2026-08-30: Fixed compliance page evidence panel still squashing labels
  into 1-char-per-line columns. Root cause: `.structured-data-nested` kept
  `container-type: inline-size` (re-entering the 420px column breakpoint
  inside a narrow parent cell) and `.compliance-detail dl` was a bare
  descendant selector matching every nested `<dl>`, both fighting the
  earlier ac41fe5e stacking fix. Set nested evidence `container-type:
  normal` (always stacks) and scoped the plain violation field list to a
  new `.compliance-fact-list` class (commit `637fad29`). Verified with a
  static HTML harness reproducing the real evidence markup/CSS (not just
  computed-style checks, which looked correct while the rendered layout
  was still broken from a cache-stale reload) — labels now render stacked
  above values at narrow widths. `npx vitest run` (156/156) and
  `npx eslint src/app/compliance/page.tsx` passed. Built/pushed
  `main-compliance-css-20260830-1548` (api+web), deployed via
  `deploy.sh apply -auto-approve`; both apps serving the new tag.
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
- 2026-08-30: Merged PR #5 (CI hardening: ruff import/lint fixes, backend test
  fixes, `/investigate` Suspense boundary fix) to `main`; validating the merged
  `main` build (commit `e76c23e4`) end to end.
- 2026-08-30: `set -a; source web/.env.local; set +a; IMAGE_TAG=main-validation-20260830-1430
  ./infra/scripts/build-and-push.sh` built and pushed both images. API digest
  `sha256:60115010f1bad754670bd3326511efbaa50c31bb3006304d31ac044647be57e7`; web
  digest `sha256:2a0c7d91fb114cef4800ee861c50fcb8ec1f0fae5bd81c751d20695e40d711e4`.
- 2026-08-30: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` produced an image-only plan: 0 additions, 4
  changes, 0 destructions.
- 2026-08-30: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh apply
  -auto-approve -var deploy_images=true -var image_tag=main-validation-20260830-1430`
  completed with 0 additions, 5 changed, 0 destroyed. Both `aiops-dev-api` and
  `aiops-dev-web` revisions reached `Succeeded` and served
  `main-validation-20260830-1430` at 100% traffic.
- 2026-08-30: Deployed API `/health` and `/ready` returned HTTP 200; deployed
  web `/` and `/api/config` returned HTTP 200.

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

## Validation Proof (Round 2 — remaining 7 specialists, 2026-08-30)

- Change: applied the same "answer the operator's actual question directly; do not replace the answer with a generic inventory of findings; do not repeat the same finding in both prose and a list" instruction (already used for `network`) to the remaining 7 specialists (`vulnerability`, `patch`, `incident`, `change`, `governance`, `remediation`, `executive_summary`) in `infra/terraform/foundry.tf`.
- Reviewed `src/operations/autonomous_investigation.py` contextual routing (`run_context_investigation`) and `web/src/components/ui/CopilotDrawer.tsx` finding-suppression logic — both already apply generically to all page kinds/specialists (fixed once for network, covers all). No additional code changes required.
- `ruff check` — passed (no findings).
- `PYTHONPATH=.:src pytest -q` — full suite passed, no failures/errors.
- `terraform -chdir=infra/terraform fmt -check` and `validate` — passed.
- `terraform plan` reviewed: 1 to add / 2 to change / 1 to destroy — only `terraform_data.foundry_agent[0]` replacement (expected trigger on specialist-instruction hash) and in-place APIM policy/connection updates. No APIM resource (`azurerm_api_management.main` or sub-resources) destroyed.
- `terraform apply -auto-approve` — succeeded: 1 added, 2 changed, 1 destroyed (same non-resource `terraform_data.foundry_agent` trigger). No image rebuild required (Terraform-only change); existing image tag `network-direct-answer-20260830-1625` continued serving.
- Live verification: `/health` → 200, `/ready` → 200, web `/` → 200.
- Live Foundry agent invocation (Responses API) for all 8 specialists — each answered the operator's question directly, cited real tool results, distinguished fact vs. inference, and gave bounded recommendations without a generic findings dump or duplicated content:
  - `aiops-network-agent` (previously verified)
  - `aiops-vulnerability-agent` — direct CVE exposure answer
  - `aiops-patch-agent` — direct missing-patch assessment
  - `aiops-incident-agent` — direct incident-timeline answer (one transient 503 from MCP backend on first call, succeeded on retry — not a regression)
  - `aiops-change-agent` — direct blast-radius answer
  - `aiops-governance-agent` — direct policy-gap answer
  - `aiops-remediation-agent` — direct remediation-priority answer
  - `aiops-executive-summary-agent` (note: hyphenated name per `var.foundry_specialists.executive_summary.name` in `variables.tf`, not underscored) — direct executive risk summary
- RBAC re-verified via `az role assignment list --assignee 2c367602-bb4f-4868-8dbb-7f4ca117a719 --all` — all prior roles intact (AcrPull, Foundry Agent Consumer, Foundry Project Runtime User, Key Vault Secrets Officer, Cognitive Services OpenAI User, Foundry Project Manager). No regressions.

## Validation Proof (Bearer-token auth fix, 2026-08-30)

- Root cause: `web/Dockerfile` requires `NEXT_PUBLIC_ENTRA_CLIENT_ID`,
  `NEXT_PUBLIC_ENTRA_TENANT_ID`, and `NEXT_PUBLIC_ENTRA_API_SCOPE` as Docker
  build-args (Next.js inlines `NEXT_PUBLIC_*` vars at build time, not runtime).
  The two prior image builds this session (`main-syncfix-...`,
  `main-compliance-css-...`) were run without first sourcing
  `web/.env.local`, so `infra/scripts/build-and-push.sh` picked up empty/stale
  values for those build-args. The browser bundle shipped with no Entra
  client/tenant ID, so MSAL could never acquire an access token client-side —
  every authenticated API call from the web UI failed with the backend's
  genuine `401 unauthenticated` / "A bearer token is required" response.
  Confirmed via live container logs: 100% of non-OPTIONS, non-`/health`
  browser-origin API calls (`/api/v1/subscription-connections`,
  `/api/v1/situations`, `/api/v1/network/*`, `/api/v1/vulnerabilities/summary`)
  were returning 401, not an isolated sync-only issue.
- Fix: rebuilt both images with `web/.env.local` sourced into the shell
  (`set -a && source web/.env.local && set +a`) before running
  `build-and-push.sh`, ensuring the three `NEXT_PUBLIC_ENTRA_*` build-args are
  populated. Tag: `main-authfix-20260830-1359`.
- `./infra/scripts/build-and-push.sh main-authfix-20260830-1359` — both
  `aiops-api` and `aiops-web` built and pushed successfully.
- `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh apply -auto-approve`
  — 0 added, 3 changed, 0 destroyed; both `aiops-dev-api` and `aiops-dev-web`
  confirmed serving `main-authfix-20260830-1359`.
- Live verification: fetched the deployed web app's `/_next/static/chunks/*.js`
  and confirmed the Entra client ID (`306c1437-0e7d-43bd-940b-79b878166331`)
  is now present in the served bundle (previously absent/empty), confirming
  MSAL is correctly configured client-side.
- No source code change was required — this was purely a deployment/build
  pipeline gap (missing env sourcing before an ad hoc build invocation), not a
  regression in `src/api/auth.py` or `web/src/lib` auth wiring.
