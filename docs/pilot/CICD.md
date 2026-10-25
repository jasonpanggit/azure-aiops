# Deployment and CI/CD

## Pipeline (`.github/workflows/ci.yml`, hardened in this phase)

| Job | What it validates | Blocking? |
| --- | --- | --- |
| `backend-tests` (four shards) | `ruff check src tests`, full pytest collection partitioned across four runners | Yes, through `backend` |
| `backend` | Requires every backend shard to succeed, including when a shard fails or is cancelled | Yes |
| `frontend` (new) | `next lint`, `vitest run`, `next build` | Yes |
| `security-scan` (new) | Trivy filesystem scan (`vuln`, `secret`, `misconfig`), SARIF uploaded to the repo Security tab | Advisory (`exit-code: 0`) — surfaces findings without blocking merges while the pilot burns down any existing findings; tighten to blocking once a baseline is clean |

Runs are also deduplicated per ref
(`concurrency: cancel-in-progress: true`) so a rapid sequence of pushes to the
same PR doesn't queue redundant, superseded CI runs — important once the
frontend and security jobs add wall-clock time to every push.

Backend sharding is opt-in: `--ci-shard-index=0 --ci-shard-count=4` selects
every fourth collected test case, with indices 0 through 3 partitioning the
entire collection exactly once. Each shard retains collection order and its
own runner/filesystem. Ordinary `python -m pytest` still runs everything.
No integration, full-manifest or authorization checks are skipped or weakened.
The stable required `backend` check fails unless all shards succeed;
`fail-fast: false` lets the other shards finish collecting failure evidence.

CI prints individual test names, the 30 slowest durations per shard and JUnit
reports uploaded as `backend-results-0` through `backend-results-3`, including
on failure. Use those results to distinguish an expensive real-storage test
from a stalled runner instead of relying on quiet progress percentages.

Before this phase, CI only ran the backend `ruff`/`pytest` job; the frontend
(`npm run lint` / `npm test` / `npm run build`) was validated manually per
session but not gated in CI. This closed that gap.

## Build

- **Backend**: no container build step in CI yet; production images are
  built by `infra/scripts/build-and-push.sh`, which pushes to the
  Terraform-provisioned Azure Container Registry
  (`azurerm_container_registry.main` in `infra/terraform/main.tf`).
- **Frontend**: the production web image must be built with
  `NEXT_PUBLIC_ENTRA_CLIENT_ID`, `NEXT_PUBLIC_ENTRA_TENANT_ID`, and
  `NEXT_PUBLIC_ENTRA_API_SCOPE` baked in at build time (Next.js
  `NEXT_PUBLIC_*` variables are compiled into the client bundle, not read at
  runtime); `build-and-push.sh` already requires and passes all three.

## Deployment and environment promotion

- `infra/scripts/deploy.sh` runs `terraform apply` against the environment's
  `.tfvars`. Environments are separated by Terraform workspace/variable file,
  not by branch — there is no "deploy on merge to main" auto-promotion today.
- **Promotion model for the pilot**: build once, promote the same image tag
  across dev → pilot by re-running `deploy.sh` with the pilot's `.tfvars`
  and `image_tag` pinned to the validated tag — never rebuild per
  environment, which would let dev and pilot silently diverge.
- `infra/scripts/validate-runtime-e2e.sh` is the deploy-time smoke test:
  run it against a freshly-applied environment before considering a
  promotion complete.

## Rollback

- **Application rollback**: Container Apps' `revision_mode = "Single"`
  (`infra/terraform/container_apps.tf`) means a rollback is "redeploy the
  previous known-good `image_tag`" via `deploy.sh`, not a Container
  Apps-native revision-traffic-split rollback. Keep the previous tag's image
  in the registry (ACR retention) so this is always possible.
- **Ontology rollback**: `docs/ONTOLOGY_RUNBOOK.md` — pre-publication
  failures automatically restore prior Delta table versions; catalog/
  registration commit is the publication boundary after which failed state
  drives idempotent retry, not silent rollback.
- **Infrastructure rollback**: standard Terraform — `terraform plan` against
  the previous commit's `.tf`/`.tfvars` and apply, since state is versioned
  in git alongside the code.

## Versioning

- API version string: `API_VERSION` in `src/api/app.py`, surfaced in
  `GET /health`. Bump it on any breaking change to the envelope contract
  (`{data, evidence[], scope{}, knowledge_version?, warnings?, pagination?}`).
- Container images: tagged by `var.image_tag` (Terraform variable), set by
  `build-and-push.sh` — recommend git SHA or semantic release tag, not
  `latest`, so a specific deployed build is always reproducible from the tag
  alone.
- Ontology schema version: `ontology_version` field already threaded through
  `ProviderState`/`/health` — a pilot customer's Copilot/graph answers can be
  correlated to the exact ontology generation that produced them.

## Configuration validation

- The API fails loudly at startup on misconfiguration rather than 500ing on
  the first request — this is the explicit design intent of
  `src/api/runtime.py` (see its module docstring).
- `src/api/akv_bootstrap.py` validates `AIOPS_AKV_BOOTSTRAP_SECRETS` JSON
  shape and Key-Vault-safe naming before attempting any write, and fails
  container startup on a malformed mapping rather than silently skipping it.
- **New checklist item for the pilot**: add a `terraform validate` +
  `terraform fmt -check` step to CI (or at minimum to `deploy.sh`) so a
  malformed `.tf`/`.tfvars` change is caught before `apply` rather than
  during a live deployment. Not yet added to `ci.yml` in this phase because
  it requires provider credentials/backend config to fully validate in some
  configurations; track as a fast-follow.
