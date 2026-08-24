# Codebase Concerns

**Analysis Date:** 2026-08-24

## Tech Debt

**Large multi-responsibility modules:**
- Issue: Core behavior is concentrated in very large modules (semantic query/runtime assembly, synchronization orchestration, and intelligence processing).
- Files: `src/semantic/semantic_engine.py`, `src/fabric/sync_service.py`, `src/api/runtime.py`, `src/intelligence/patch/patch_intelligence.py`, `src/agents/operations/operations_agent.py`
- Impact: Changes cut across multiple concerns, increasing regression risk and review complexity.
- Fix approach: Extract narrow services behind stable interfaces (query execution, provider composition, synchronization phases) while preserving route and data contracts.

**Storage behavior is split across multiple backends and code paths:**
- Issue: Local filesystem and OneLake paths diverge across `Path`, fsspec, and Data Lake SDK logic, including lock semantics and atomic publish behavior.
- Files: `src/hermes_arg_connector/storage.py`, `src/hermes_arg_connector/onelake_fs.py`, `src/hermes_arg_connector/locking.py`, `src/storage/onelake_writer.py`, `src/storage/onelake_documents.py`
- Impact: Correctness guarantees differ by environment, making production-only failures more likely.
- Fix approach: Define one storage/locking contract with conformance tests that run against both local and OneLake implementations.

**Exception handling policy is inconsistent and often broad:**
- Issue: Broad `except Exception` handlers are used in runtime composition, refresh loops, and sync paths, which can hide root causes behind degraded states.
- Files: `src/api/app.py`, `src/api/runtime.py`, `src/api/providers.py`, `src/fabric/sync_service.py`, `src/hermes_arg_connector/service.py`, `src/operations/autonomous_investigation.py`
- Impact: Operators get less precise failure diagnostics and engineers face longer incident triage time.
- Fix approach: Narrow exception boundaries to expected failure classes and emit structured failure reasons with actionable remediation context.

## Known Bugs

**OneLake connector lock lease can expire during long ingestion runs:**
- Symptoms: `RunLock` uses a finite `LEASE_DURATION_SECONDS = 60`, and `IngestionService.run()` acquires the lock once without periodic renewal.
- Files: `src/hermes_arg_connector/locking.py`, `src/hermes_arg_connector/service.py`
- Trigger: Long-running ingestion exceeds 60 seconds while writing/normalizing large estates.
- Workaround: Operate with a single replica and shorter runs; this is operationally fragile and not deterministic.

**Timed-out autonomous investigation threads can continue running:**
- Symptoms: Futures are cancelled when possible, but the executor is shut down with `wait=False`, so in-flight work can outlive request timeout.
- Files: `src/operations/autonomous_investigation.py`, `src/api/routers/multi_agent.py`
- Trigger: Investigation timeout with agents blocked on external calls or long computation.
- Workaround: Lower timeout and reduce agent fan-out; behavior remains best-effort due to non-cooperative thread cancellation.

## Security Considerations

**Header-based principal assertion depends on strict perimeter trust:**
- Risk: `HeaderPrincipalAuthenticator` trusts asserted headers and does not verify bearer tokens itself.
- Files: `src/api/auth.py`, `src/api/runtime.py`
- Current mitigation: Entra JWT auth path exists and header mode requires configured grants resolver.
- Recommendations: Default production auth to `EntraJwtAuthenticator`, and enforce ingress policy preventing direct access paths that can spoof assertion headers.

**CORS and ingress defaults are permissive for credential-bearing requests:**
- Risk: API enables `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`, and Terraform defaults `api_external_ingress` to true.
- Files: `src/api/app.py`, `infra/terraform/variables.tf`, `infra/terraform/container_apps.tf`
- Current mitigation: Localhost origins are defaulted for development, and deployments can override origins.
- Recommendations: Make external ingress opt-in by default, constrain CORS methods/headers, and enforce HTTPS-only origin validation in production.

**Key Vault and deployment secrets posture is broad:**
- Risk: App identity gets `Key Vault Secrets Officer`, and Terraform providers still consume `client_secret` as input.
- Files: `infra/terraform/main.tf`, `infra/terraform/providers.tf`, `infra/terraform/variables.tf`, `src/api/routers/admin.py`
- Current mitigation: Sensitive Terraform variables are flagged as sensitive and Key Vault is used instead of plaintext persistence.
- Recommendations: Move deployment auth to workload identity/OIDC, reduce runtime role privileges where feasible, and add policy checks against local/unsafe state handling.

## Performance Bottlenecks

**Freshness fallback performs full-table Delta scans:**
- Problem: If SQL endpoint aggregation fails, freshness logic iterates full rows across governed tables to find a max timestamp.
- Files: `src/fabric/sync_service.py`
- Cause: `_global_freshness_watermark()` falls back from SQL max aggregation to repeated `delta.read()` scans.
- Improvement path: Persist incremental table watermarks on write and query metadata/aggregates instead of full reads.

**Dataset publishing materializes full JSONL and Parquet payloads in memory:**
- Problem: `_write_dataset()` builds complete JSONL strings and full `pyarrow.Table.from_pylist(...)` before writing.
- Files: `src/hermes_arg_connector/storage.py`
- Cause: Serialization pipeline is batch-in-memory, not streaming/chunked.
- Improvement path: Introduce chunked writers for JSONL/Parquet and enforce upper bounds per dataset generation.

**Process-local refresh loops duplicate expensive work across replicas:**
- Problem: Each API process runs its own background provider refresh thread.
- Files: `src/api/app.py`, `src/api/providers.py`
- Cause: Refresh scheduling and state are instance-local rather than coordinated.
- Improvement path: Add distributed refresh coordination and shared freshness markers.

## Fragile Areas

**Multi-stage sync transaction boundaries:**
- Files: `src/fabric/sync_service.py`, `src/storage/delta_writer.py`, `src/ontology/ontology_publisher.py`
- Why fragile: Sync spans dataset mapping, parallel writes, ontology publication, and state transition/rollback handling across separate subsystems.
- Safe modification: Preserve idempotent run IDs and explicit failure-stage semantics; add failure-injection tests for each stage boundary.
- Test coverage: `tests/test_incremental_sync.py`, `tests/test_ontology_sync.py`, and `tests/test_delta_tables.py` cover primary flows but not full stage-failure permutations in live environments.

**Authorization + scope filtering on nested payloads:**
- Files: `src/api/rbac.py`, `src/api/scope.py`, `src/api/routers/context.py`, `src/api/routers/copilot.py`, `src/api/routers/operations.py`
- Why fragile: Correctness depends on both action authorization and post-query scope filtering across diverse payload structures.
- Safe modification: Apply scope projection immediately after data retrieval and require explicit scope tests for every new response field.
- Test coverage: `tests/test_api_primitives.py` validates core grant behavior, but route-level regression coverage is uneven for newly added nested response shapes.

**Remote locking semantics differ between connector and sync writer:**
- Files: `src/hermes_arg_connector/locking.py`, `src/storage/onelake_writer.py`, `src/fabric/sync_service.py`, `src/hermes_arg_connector/service.py`
- Why fragile: Connector uses finite renewable leases while sync writer uses explicit Data Lake lock files with indefinite lease/break behavior.
- Safe modification: Unify lock lifecycle policy and provide common lease telemetry (acquire, renew/break, release).
- Test coverage: `tests/test_run_lock.py` exercises lock semantics in isolation, but end-to-end multi-replica contention is not covered.

## Scaling Limits

**Azure Resource Graph extraction has hard pagination ceilings:**
- Current capacity: Default `page_size=1000` and `max_pages=1000` permit up to one million rows per query.
- Limit: Larger estates truncate/fail once maximum pages are exhausted.
- Scaling path: Add resumable checkpoints and partitioned query execution by subscription/management group.
- Files: `src/hermes_arg_connector/config.py`, `src/hermes_arg_connector/azure.py`, `src/hermes_arg_connector/source.py`

**Large in-memory snapshots and projections:**
- Current capacity: Providers and services repeatedly materialize full table payloads in Python objects.
- Limit: Memory and tail latency scale with ontology + intelligence table growth.
- Scaling path: Push pagination/aggregation into Delta SQL paths and use bounded caching.
- Files: `src/fabric/sync_service.py`, `src/api/providers.py`, `src/semantic/semantic_engine.py`

## Dependencies at Risk

**Azure CLI install path relies on remote bootstrap script:**
- Risk: Runtime image installs Azure CLI via `curl -sL https://aka.ms/InstallAzureCLIDeb | bash` and then adds `resource-graph` extension.
- Files: `Dockerfile`
- Impact: Build reproducibility and supply-chain integrity depend on mutable remote artifacts.
- Migration plan: Pin packaged CLI versions and extension versions with integrity verification.

## Missing Critical Features

**No durable async job model for long-running operations:**
- Problem: Sync and autonomous investigations are request-coupled or process-thread coupled.
- Blocks: Reliable retries, resumability, progress tracking, and deterministic cancellation across replicas.
- Files: `src/api/routers/connections.py`, `src/api/routers/multi_agent.py`, `src/fabric/sync_service.py`, `src/api/app.py`

**No distributed provider-refresh ownership:**
- Problem: Provider refresh is process-local, so replicas can drift in freshness and degradation state.
- Blocks: Predictable multi-replica behavior and single-source runtime health truth.
- Files: `src/api/app.py`, `src/api/providers.py`, `src/api/runtime.py`

## Test Coverage Gaps

**Ingress/CORS security posture is not explicitly integration-tested:**
- What's not tested: Production-like combinations of ingress exposure + credentialed CORS behavior.
- Files: `src/api/app.py`, `infra/terraform/container_apps.tf`, `infra/terraform/variables.tf`
- Risk: Configuration drift can silently widen exposure.
- Priority: High

**Lease-expiry and multi-replica lock contention are under-tested end-to-end:**
- What's not tested: Long-running ingestion with lease renewal behavior under real OneLake timing and competing writers.
- Files: `src/hermes_arg_connector/locking.py`, `src/hermes_arg_connector/service.py`, `src/storage/onelake_writer.py`
- Risk: Duplicate or overlapping ingestion writes during peak workloads.
- Priority: High

**Timeout/cancellation semantics for multi-agent runs lack stress coverage:**
- What's not tested: Request timeout behavior with agents blocked on external dependencies while futures continue beyond timeout.
- Files: `src/operations/autonomous_investigation.py`, `src/api/routers/multi_agent.py`, `src/operations/foundry_agent.py`
- Risk: Background resource leakage and inconsistent operator expectations after timeout responses.
- Priority: Medium

---

*Concerns audit: 2026-08-24*
