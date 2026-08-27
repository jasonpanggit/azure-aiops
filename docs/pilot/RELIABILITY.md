# Reliability

## Service Level Objectives (pilot targets)

These are pilot-phase targets, not contractual SLAs. They are measured from
the signals in `OBSERVABILITY.md`.

| SLO | Target | Measured by |
| --- | --- | --- |
| API availability (`/ready` returns non-503) | 99.0% monthly | `hermes.api.requests` status class + `/ready` alert |
| API read-path latency (p95) | < 2s for graph/investigation endpoints | `hermes.api.request.duration` histogram |
| Provider freshness (required providers) | Stale ≤ `HERMES_PROVIDER_STALE_HOURS` (default 24h) | `ProviderRuntime.health()` freshness field |
| Copilot answer latency (p95, Foundry configured) | < 15s including one retry | Foundry client timeout (`FOUNDRY_TIMEOUT_SECONDS`, default 60s) + retry backoff |
| Background refresh cadence | Every `HERMES_PROVIDER_REFRESH_SECONDS` (default 30s) | `_start_background_refresh` thread |

A monthly SLO review compares actual Log Analytics data against these
targets; see `READINESS_REVIEW.md` for the review cadence during the pilot.

## Timeouts, retries, and circuit breaking

### Foundry Copilot calls (new in this phase)

`src/operations/foundry_agent.py::FoundryPromptAgent` now applies:

- **Bounded retry with exponential backoff** — only for transient failures
  (network errors, and HTTP `429/500/502/503/504`). Non-retryable errors
  (bad request, malformed response, empty answer) fail immediately since a
  retry cannot fix a content problem. Configurable via `FOUNDRY_MAX_RETRIES`
  (default 2) and a fixed 0.5s base backoff that doubles per attempt.
- **Circuit breaker** — after `FOUNDRY_CIRCUIT_BREAKER_THRESHOLD` (default 5)
  consecutive failures, subsequent calls are short-circuited immediately
  (`FoundryCircuitOpenError`) for `FOUNDRY_CIRCUIT_BREAKER_RESET_SECONDS`
  (default 60s) rather than each concurrent request separately paying the
  full retry/timeout budget against a dependency that is already down. The
  next call after the reset window is allowed through as a probe; a renewed
  failure re-opens the breaker.
- Both are unit-tested in `tests/test_api_copilot.py`
  (`test_transient_failure_is_retried_then_succeeds`,
  `test_circuit_breaker_opens_after_repeated_failures`,
  `test_circuit_breaker_resets_after_window_elapses`,
  `test_non_retryable_http_error_raises_immediately`).

### Provider refresh (pre-existing)

`src/api/providers.py::ProviderRuntime` already implements the platform's
core reliability pattern: a failed refresh **never replaces a working
provider** — it marks that provider `degraded`, schedules a bounded retry,
and continues serving the last good snapshot. `/health` accurately reports
the failure while `/ready` still passes if the stale snapshot is within
`HERMES_PROVIDER_STALE_HOURS`. Two locks (`_state_lock` for reads,
`_refresh_lock` for serializing actual refresh execution) mean a health
probe is never blocked behind a slow loader.

### Multi-agent investigation timeouts (fixed in the prior review phase)

`src/operations/autonomous_investigation.py::run_autonomous_investigation`
manages its `ThreadPoolExecutor` lifecycle manually
(`shutdown(wait=False, cancel_futures=True)` in a `finally` block) instead of
relying on the context manager, so a timed-out investigation actually
returns within its timeout budget instead of blocking on unfinished agent
threads.

## Degradation modes

| Failure | Behavior |
| --- | --- |
| Foundry unreachable / circuit open | Copilot degrades to retrieval-only: the retrieved facts are still returned, narration is replaced with a plain "narration unavailable" state. No fabricated answer is ever returned. |
| A required provider unavailable | `/ready` returns 503; already-served requests continue against the last good snapshot until it exceeds the staleness window. |
| Multi-agent investigation exceeds its timeout | Investigation returns partial findings with an explicit `timed_out` status rather than hanging the request. |
| Fabric ontology publication stale | `ontology_health()` freshness reported via `/health`; UI surfaces a stale-data banner (see `docs/semantic-architecture.md`). |

## Backup, restore, and disaster recovery

All durable platform state lives in **OneLake** (Fabric), not in a
platform-managed database (`infra/terraform/persistence.tf`,
`docs/PRODUCTION_RUNTIME_ACTIVATION.md`):

- **Connection registry, risk exceptions, cached CVE enrichment, dataset
  generations** — OneLake/Fabric Lakehouse. Recovery relies on Fabric's own
  workspace/capacity backup and versioning guarantees, not a Hermes-specific
  backup job. Fabric capacity and workspace-level access are the operator's
  responsibility per the Fabric admin's retention policy.
- **Ontology publication** — `docs/ONTOLOGY_RUNBOOK.md` documents the
  pre-publication rollback contract: a run holds the OneLake lease;
  table-write or pre-publication registration failures restore prior Delta
  table versions automatically. Once catalog/registration commit succeeds,
  the publication is retained even if a later step fails, and failed state
  drives an idempotent retry — never a silently rolled-back external
  reference.
- **Key Vault** — `soft_delete_retention_days = 7` is already set
  (`infra/terraform/main.tf`); purge protection is intentionally off in
  non-production so environments can be torn down and rebuilt under the same
  name. **The pilot production environment must enable
  `purge_protection_enabled = true`** before onboarding real customer
  secrets — tracked as a pilot go-live gate in `READINESS_REVIEW.md`.
- **Application state (in-memory)** — the multi-agent investigation ledger
  (`InvestigationLedgerStore`) and saved investigations/remediation
  plans/compliance exceptions (currently browser `localStorage`) are **not**
  durably backed up. This is a known, documented gap (see
  `DATA_GOVERNANCE.md` and the prior code-review checkpoint); the pilot
  scope note in `ONBOARDING_GUIDE.md` discloses this explicitly so the pilot
  customer does not rely on saved investigations surviving a browser data
  clear or ledger eviction (`MAX_LEDGER_ENTRIES = 1000`).
- **Disaster recovery drill** — before pilot go-live, run
  `infra/scripts/validate-runtime-e2e.sh` against a freshly-provisioned
  environment from the committed Terraform to prove the platform can be
  rebuilt from code + Fabric-restored data within the pilot's agreed RTO.
