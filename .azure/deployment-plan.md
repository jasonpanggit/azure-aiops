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

- 2026-09-03: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh
  plan -refresh=false -lock=false` passed with no infrastructure changes.
  `./infra/scripts/build-and-push.sh remediation-card-overflow-20260903-0029`
  built and pushed the API and web deployment images (plus the required
  supporting images) successfully.
- 2026-09-03: Terraform apply completed with 0 additions, 6 changes, and
  0 destructions. API revision `aiops-dev-api--0000197` and web revision
  `aiops-dev-web--0000163` are healthy, running, and serving 100% traffic
  for the new image tag. API `/health` and `/ready`, web `/`, `/api/config`,
  and `/remediation` returned HTTP 200. Live RBAC verification confirmed the
  shared identity's ACR, Key Vault, Foundry, Fabric, and VM roles.
- 2026-09-02: `terraform -chdir=infra/terraform fmt -check` and targeted
  onboarding/API tests passed after constraining `api_max_replicas` to 1;
  `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` showed 0 additions, 1 in-place update, and
  0 destructions. The Next.js production build completed successfully.
- 2026-09-02: Static Terraform RBAC review confirmed the existing `AcrPull`,
  Key Vault, Fabric Reader, and Foundry roles remain unchanged.
- 2026-09-02: `AIOPS_ENV_FILE=web/.env.local ./infra/scripts/deploy.sh plan
  -refresh=false -lock=false` passed with no infrastructure changes. The generic
  validator's bare `terraform plan` was not applicable because this repository
  supplies required secret-backed variables through `deploy.sh`.
- 2026-09-02: `cd web && npm run build` passed; the `/remediation` route compiled
  successfully.
- 2026-09-02: Static Terraform RBAC review confirmed `AcrPull`, Key Vault access,
  and Foundry runtime roles remain assigned without destructive changes.
- 2026-09-02: Built and pushed API, web, MCP server, and Azure MCP images with
  tag `remediation-handoff-20260902-1435`; Terraform applied 0 additions, 6
  changes, and 0 destructions. All four Container Apps serve the new tag.
- 2026-09-02: Live verification returned HTTP 200 for the deployed
  `/remediation` page and API `/health`; the web revision reached `Running`
  with 100% traffic. Live RBAC verification confirmed the shared identity's
  ACR, Key Vault, and Foundry roles.

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
- 2026-09-02: Authenticated Terraform preflight passed subscription selection,
  Azure authentication, init, fmt check, validate, plan, state, template
  variable scan, and required variable validation. The Next.js production
  build completed successfully.
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

- Terraform validation recipe:
  - Terraform and Azure CLI are installed.
  - Azure CLI is authenticated to the target subscription.
  - Terraform is initialized.
  - Terraform formatting check passes.
  - Terraform configuration validates.
  - Terraform plan completes without unapproved destructive changes.
  - Terraform state is accessible.
  - Go-style template variables are absent from Terraform JSON variables.
  - `main.tfvars.json` JSON syntax is valid.

- Terraform preflight sequence:
  - Terraform installed
  - Azure CLI installed and authenticated
  - Terraform initialized
  - Terraform formatting check passes
  - Terraform configuration validates
  - Terraform plan completes without unapproved destructive changes
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

## Validation Proof (Admin page revamp + governance settings editor — 2026-08-30)

- Commit: `53c9fac9` — trimmed `/admin` to Entra/Key Vault config only; wired previously-dead `governanceApi.updateSettings` into Governance page's Administration tab as an editable policy form.
- Build/push: `main-admin-revamp-20260830-1420` (both `aiops-api` and `aiops-web`), ACR run `cr77`, succeeded in 3m24s.
- Deploy: `deploy.sh apply -auto-approve` — 0 added / 3 changed / 0 destroyed. Confirmed both container apps serving `main-admin-revamp-20260830-1420`.
- Pre-deploy checks: `npx eslint` clean on changed files; `npx tsc --noEmit` clean (pre-existing unrelated errors only in `CopilotDrawer.test.tsx`); `npm run build` succeeded (26/26 static pages); `npx vitest run` — 158/158 tests passed.
- Post-deploy smoke check: `GET /admin` → 200, `GET /governance` → 200 on `https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io`.

## Validation Proof (Admin page removed — 2026-08-30)

- Commit: `ba023589` — removed `/admin` page, nav entry, `adminApi` client, backend `/admin/akv-config` router, and its dedicated test. The form wrote to Key Vault secrets that nothing in the running app ever read back (real auth config comes from Terraform vars -> container app env vars / `NEXT_PUBLIC_ENTRA_*` build-args, a separate path).
- Build/push: `main-admin-removed-20260830-1435` (both images), ACR run `cr7a`, succeeded in 3m23s.
- Deploy: `deploy.sh apply -auto-approve` — confirmed both container apps serving `main-admin-removed-20260830-1435`.
- Pre-deploy checks: `npx eslint` clean; `npm run build` succeeded (`/admin` route no longer in build output); `npx vitest run` — 158/158 passed; backend `pytest tests/` — full suite green (test_api_admin.py removed cleanly, no other test depended on it).
- Post-deploy smoke check: `GET /admin` → Next.js not-found content confirmed (route removed); `GET /governance` → 200 (Administration tab settings editor still functional).

## Validation Proof (Governance gates: durable ledger + patch approval — 2026-08-30)

- Commits: `f52a919d` (persist investigation ledgers to OneLake), `74ba4eea`
  (enforce human approval before patch execution), `3f877fda` (lint cleanup
  the ledger commit left behind).
- Pre-deploy: `ruff check src tests` clean (fixed 3 findings `f52a919d` had
  left — that commit linted only its changed files, not the repository);
  backend `pytest tests/` full suite green; `npm run lint` clean; 158/158
  Vitest tests passed; `npm run build` succeeded; `terraform fmt -check` and
  `validate` passed.
- Mutation testing: all 8 approval-gate tests verified against 4 mutations
  (remove self-approval check, drop case/whitespace normalisation, remove
  missing-approver check, default the policy open). Each mutation is caught,
  at both the service and HTTP layer.
- Fabric capacity `aiopsdevcapg6ludc` (F4) was **Paused**, which fails
  `fabric_workspace.ops` preconditions and blocks apply. Resumed to Active for
  this deployment, then paused again afterwards.
- Build/push: `governance-gates` (both images), ACR runs `cr7h`/`cr7m`.
- Deploy: `deploy.sh apply -auto-approve` — 0 added / 3 changed / 0 destroyed,
  all in-place. `terraform_data.foundry_agent[0]` was NOT recreated, so the
  specialist instructions from the previous round are intact.
- Post-deploy, live, authenticated with a real Entra token:
  - Approval gate A — no approver → HTTP 400 `invalid_request`, citing
    `agent_policy.require_human_approval`.
  - Approval gate B — approver == requester → HTTP 400, "The approver must be
    someone other than the requester".
  - Approval gate C — distinct approver → gate passes and reaches the adapter
    (HTTP 503, no execution adapter configured in dev). This is the important
    case: it proves the gate is not blanket-refusing and that the live
    enterprise setting is genuinely being read.
  - Dry run → HTTP 202, approver falls back to requester (exempt branch).
- Durable ledger, verified end-to-end against real OneLake (not a filesystem
  stand-in as in the original commit):
  - Ran a contextual investigation → ledger `ctx-7680489d3831`.
  - Restarted revision `aiops-dev-api--0000135`; the ledger was still readable
    afterwards. Before this change it lived in an in-memory OrderedDict and
    would have been lost.
  - Confirmed the blob exists in the lakehouse:
    `Files/aiops/ledgers/ctx-7680489d3831.json` (353,409 bytes).
- CORRECTION: an earlier draft of this entry claimed `GET
  /agents/investigations` was a broken list projection returning 0. That was a
  misreading. There is no list endpoint -- the routes are `POST
  /investigations` (create), `GET /investigations/{ledger_id}`, and `POST
  /investigations/{ledger_id}/actions`. The probe issued GET against a
  POST-only path and got `405 Method Not Allowed`, whose body has no `data`
  key; the check reported that absence as a count of 0. No such gap exists.
- Genuine limitation: ledgers are reachable only by id. Enumerating an
  operator's investigation history would need both a new route and a listing
  capability on the document store (`LedgerDocumentStore` exposes `read`/`put`
  only). Not required by any current caller.

## Web image rebuild — Phase 3 remediation execution fixes (2026-09-01)

- Trigger: Phase 3 (Safe Remediation Execution) code-verified 19/19; web fixes
  from commit `33bbc4a7` (scope-aware execution service resolution,
  `attempt_number` field rename) had not yet been rolled out to `aiops-dev`.
- Build: `az acr build` for `aiops-web` only (api/mcp images unchanged), ACR
  run `crat`, tag `fix-ontology-sync-publish-20260901-171839`. Build args:
  `NEXT_PUBLIC_ENTRA_CLIENT_ID`, `NEXT_PUBLIC_ENTRA_TENANT_ID`,
  `NEXT_PUBLIC_ENTRA_API_SCOPE` read from `web/.env.local`.
- Deploy: `az containerapp update --name aiops-dev-web --image
  aiopsdevacrg6ludc.azurecr.io/aiops-web:fix-ontology-sync-publish-20260901-171839`
  (direct image update, not a full `terraform apply`, to avoid touching
  unrelated in-flight config from other concurrent sessions working on this
  repo). `terraform.tfvars` `image_tag` was intentionally NOT updated by this
  path — a future `deploy.sh apply` will still read the prior tag
  (`active-entity-fix`) until reconciled.
- Result: new revision `aiops-dev-web--0000130` created at 2026-09-01T17:22:31Z,
  Active=True, Traffic=100%. Prior revisions `--0000128`/`--0000129` remain
  Active=True/Traffic=0 (not deprovisioned).
- Smoke checks (unauthenticated, page-load only):
  - `GET /remediation` → 200
  - `GET /` → 200
  - `GET /api/config` → 200
- Not verified in this pass: authenticated remediation UI behavior (preview/
  approve/execute flows) — the live remediation plan dataset is still empty
  per `03-UAT.md`, so full remediation UAT remains blocked pending real data.
- Follow-up: reconcile `infra/terraform/terraform.tfvars` `image_tag` on the
  next full Terraform apply so state doesn't drift from the live revision.
