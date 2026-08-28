# Readiness Review

Run this checklist before onboarding the first real pilot subscription, and
re-run it at the pilot's midpoint. Each row needs an evidence artifact (test
output, screenshot, terraform plan, log excerpt) — "looks fine" is not
evidence.

## Production readiness

| Check | Evidence | Status |
| --- | --- | --- |
| Full backend test suite passes | `uv run pytest -q` output | ✅ Passing as of this phase (see below) |
| Full frontend test suite passes | `npm test --prefix web -- --run` output | ✅ Passing as of this phase (see below) |
| Frontend build succeeds | `npm run build --prefix web` output | ✅ Passing as of this phase (see below) |
| Lint clean (backend + frontend) | `ruff check`, `npm run lint --prefix web` output | ✅ Passing as of this phase (see below) |
| Terraform validates | `terraform validate` output | ✅ Passing as of this phase (see below) |
| CI gates backend + frontend + security scan | `.github/workflows/ci.yml` | ✅ Added in this phase |
| `/health` and `/ready` behave correctly under a simulated provider failure | Manual test: force a provider loader exception, confirm `/health` reports `degraded` and `/ready` returns 503 only when a *required* provider is affected | ☐ Run before pilot go-live |
| End-to-end runtime validation | `infra/scripts/validate-runtime-e2e.sh` output against a live deployment | ☐ Run before pilot go-live |

## Security readiness

| Check | Evidence | Status |
| --- | --- | --- |
| Entra auth mode enforced in production Terraform | `infra/terraform/container_apps.tf` (`AIOPS_API_AUTH=entra` hardcoded) | ✅ |
| RBAC scope narrowing verified (no cross-scope leakage) | `tests/test_api_copilot.py` grounded-context assertion + equivalent scope tests in graph/network/vulnerability/twin routers | ✅ |
| Key Vault purge protection enabled for pilot environment | `terraform plan` diff showing `purge_protection_enabled = true` | ☐ Must be set before pilot secrets are stored — see `SECURITY.md` |
| Discovery SPNs are read-only against target subscriptions | Azure RBAC role assignment review per connection | ☐ Review per onboarded connection |
| `AIOPS_API_GATEWAY_GRANTS` reviewed for the pilot tenant | Grant map diff reviewed by security reviewer | ☐ Review before go-live |
| Secrets never logged | Code review of `akv_bootstrap.py`, `foundry_agent.py` (Authorization header masking) | ✅ |

## Reliability readiness

| Check | Evidence | Status |
| --- | --- | --- |
| Foundry retry/circuit-breaker behavior unit-tested | `tests/test_api_copilot.py::test_transient_failure_is_retried_then_succeeds`, `test_circuit_breaker_opens_after_repeated_failures`, `test_circuit_breaker_resets_after_window_elapses`, `test_non_retryable_http_error_raises_immediately` | ✅ Added in this phase |
| Provider refresh never replaces a working provider with a broken one | `src/api/providers.py::ProviderRuntime` design + existing tests | ✅ Pre-existing |
| Multi-agent investigation honors its timeout budget | Fixed executor lifecycle (`shutdown(wait=False, cancel_futures=True)`), verified in prior review phase | ✅ Fixed in prior phase |
| Alerting configured for API/web availability and provider health | `infra/terraform/alerting.tf` + `alert_email_addresses` set in pilot `.tfvars` | ☐ Set `alert_email_addresses` for the pilot environment before go-live |
| DR drill: rebuild from Terraform + Fabric-restored data within agreed RTO | Drill log/timing | ☐ Run before pilot go-live |

## Performance readiness

| Check | Evidence | Status |
| --- | --- | --- |
| API p95 read latency under target | Log Analytics query against `aiops.api.request.duration` | ☐ Baseline once alert_email/dashboard is live |
| Background refresh cadence matches `AIOPS_PROVIDER_REFRESH_SECONDS` under real discovery volume | Provider health `loaded_at`/`last_success_at` deltas over a day | ☐ Observe during first week of pilot |
| Copilot answer latency under target (if Foundry configured) | Foundry timeout/retry configuration reviewed against real network latency to the Foundry project endpoint | ☐ Measure during demo script walkthrough |

## UX readiness

| Check | Evidence | Status |
| --- | --- | --- |
| Executive Mode and Engineer Mode both validated with real pilot data | Demo script walkthrough (`ONBOARDING_GUIDE.md`) | ☐ Run with pilot customer sponsor |
| Loading/error states verified for a genuinely degraded provider | Manual test: force a provider into `degraded` state, confirm the UI shows an honest stale/error indicator, not silent fallback data | ☐ Run before pilot go-live |
| Accessible navigation across all workspaces | Existing frontend a11y-conscious component library (Fluent UI) + manual keyboard-nav spot check | ☐ Spot check before go-live |

## Customer-value readiness

| Check | Evidence | Status |
| --- | --- | --- |
| End-to-end flow demonstrated: risk → topology → vulnerability → evidence → Copilot conclusion → remediation candidate | Demo script (`ONBOARDING_GUIDE.md`) run against real pilot data | ☐ Run before go-live |
| Acceptance criteria (`ONBOARDING_GUIDE.md`) reviewed and agreed with pilot sponsor | Signed-off acceptance criteria checklist | ☐ Agree before go-live |
| Known limitations disclosed and acknowledged by pilot sponsor | Written acknowledgment (email/doc sign-off) referencing `SUPPORT_MODEL.md`'s known-limitations section | ☐ Obtain before go-live |

## How "✅ Passing as of this phase" was verified

At the time this pack was written, the following commands were run against
the working tree and passed:

```
uv run pytest -q
npm test --prefix web -- --run
npm run lint --prefix web
npm run build --prefix web
python -m py_compile src/operations/foundry_agent.py
terraform validate   # infra/terraform, after `terraform init -backend=false`
terraform fmt -check  # infra/terraform
```

Re-run all of the above (plus the ☐ items) immediately before the pilot's
first real subscription is onboarded, since infrastructure/dependency drift
between "this was validated" and "pilot go-live" is exactly the kind of gap
this readiness review exists to catch.
