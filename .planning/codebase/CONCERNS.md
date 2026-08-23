# Codebase Concerns

**Analysis Date:** 2026-08-23

## Tech Debt

**Large multi-responsibility modules:**
- Issue: Core behavior is concentrated in very large modules, including semantic query/normalization logic, synchronization orchestration, API runtime composition, and several intelligence engines.
- Files: `src/semantic/semantic_engine.py`, `src/fabric/sync_service.py`, `src/api/runtime.py`, `src/intelligence/patch/patch_intelligence.py`, `src/agents/operations/operations_agent.py`
- Impact: Changes cross many concerns, increase regression risk, and make review and targeted testing difficult.
- Fix approach: Extract stable ports and focused services around query execution, ingestion stages, provider construction, and intelligence projections; preserve the existing API contracts while moving one responsibility at a time.

**Duplicated local/cloud storage paths:**
- Issue: The connector and API support local files, OneLake/fsspec paths, Data Lake SDK paths, Delta tables, and JSONL/Parquet generations through separate branches.
- Files: `src/hermes_arg_connector/storage.py`, `src/hermes_arg_connector/onelake_fs.py`, `src/storage/onelake_writer.py`, `src/storage/onelake_documents.py`, `src/storage/delta_writer.py`
- Impact: Semantics such as atomic activation, cleanup, permissions, and error handling can diverge between development and production.
- Fix approach: Define one storage abstraction with conformance tests for local and OneLake implementations, especially for publish interruption, concurrent writers, and partial remote writes.

**Runtime configuration is spread across environment variables and Terraform:**
- Issue: Authentication, grants, Foundry, Fabric, Key Vault, image, and scaling behavior are configured across `src/api/runtime.py`, shell launchers, and Terraform variables rather than validated by one startup configuration model.
- Files: `src/api/runtime.py`, `scripts/start-api.sh`, `infra/terraform/variables.tf`, `infra/terraform/container_apps.tf`
- Impact: Invalid or inconsistent deployment combinations can start in a degraded state and only fail when a provider or route is used.
- Fix approach: Centralize typed configuration validation, fail startup for mandatory production settings, and add a deployment smoke test for every supported mode.

## Known Bugs

**Remote ingestion lock can expire during a long sync:**
- Symptoms: A OneLake writer lease is acquired for 60 seconds, but the sync path does not renew it while processing large datasets or waiting on upstream services; another replica can acquire the lock after expiry while the first sync is still writing.
- Files: `src/hermes_arg_connector/locking.py`, `src/storage/onelake_writer.py`, `src/fabric/sync_service.py`
- Trigger: A production ingestion run lasts longer than `LEASE_DURATION_SECONDS`.
- Workaround: Keep runs below the lease duration or manually coordinate a single replica; this is not a reliable safeguard.

**Provider refresh work is process-local:**
- Symptoms: Every API replica starts its own background refresh thread and maintains its own provider/snapshot state.
- Files: `src/api/app.py`, `src/api/providers.py`, `src/api/runtime.py`
- Trigger: Scaling the API beyond one replica or restarting a replica during a refresh cycle.
- Workaround: Use the persisted Fabric/OneLake snapshot and tolerate provider staleness; add distributed refresh coordination and shared status before relying on synchronized freshness.

## Security Considerations

**Header-based identity has a trust-boundary dependency:**
- Risk: `HeaderPrincipalAuthenticator` accepts identity and role headers without validating a token. Direct exposure of the API, a misconfigured ingress, or a route that bypasses the trusted gateway can enable forged principals.
- Files: `src/api/auth.py`, `src/api/runtime.py`, `infra/terraform/container_apps.tf`
- Current mitigation: Production Terraform selects Entra mode and the authenticator documents that it must be behind a validating gateway; an Entra JWT implementation also exists in `src/api/auth.py`.
- Recommendations: Prefer `EntraJwtAuthenticator` or cryptographically bind gateway assertions, reject direct production ingress unless explicitly protected, and add an integration test proving forged headers cannot authorize a request.

**API ingress and browser credentials are broadly enabled by defaults:**
- Risk: `api_external_ingress` defaults to true and CORS allows credentials, all methods, and all headers for configured origins. A deployment mistake can expose a credential-bearing API more broadly than intended.
- Files: `infra/terraform/variables.tf`, `infra/terraform/container_apps.tf`, `src/api/app.py`
- Current mitigation: The default origin list is local-only and production Terraform sets the web origin explicitly.
- Recommendations: Make external ingress opt-in for non-public deployments, restrict methods and headers, validate origins as HTTPS in production, and add Terraform policy checks for public ingress plus missing identity protection.

**Key Vault runtime identity is over-privileged:**
- Risk: The API identity is granted `Key Vault Secrets Officer`, which permits broad secret data-plane operations even though the application primarily needs narrowly defined read/write operations.
- Files: `infra/terraform/main.tf`, `src/onboarding/credentials.py`, `src/api/routers/admin.py`
- Current mitigation: Secrets are stored in Key Vault rather than the registry, and application secret names are allowlisted in `src/api/routers/admin.py`.
- Recommendations: Separate writer and reader identities, use the least-privilege custom roles supported by the deployment, restrict vault scope, and add an audit alert for unexpected secret deletion or enumeration.

**Infrastructure credentials remain Terraform inputs:**
- Risk: `client_secret` is passed into multiple Terraform providers and can be retained in Terraform state or provider/resource metadata if state handling is misconfigured.
- Files: `infra/terraform/providers.tf`, `infra/terraform/variables.tf`, `infra/terraform/main.tf`
- Current mitigation: The variable is marked sensitive and local state/tfvars are ignored by `.gitignore`.
- Recommendations: Use workload identity/OIDC for deployment where possible, store remote state in a protected backend with encryption and access logging, and add a CI check that rejects local state, tfvars, or secret-bearing artifacts.

**Sensitive operational data may be sent to external AI services:**
- Risk: The Copilot and Foundry integration sends retrieved operational context to a Foundry agent; context can include asset, incident, vulnerability, and business metadata. Scope filtering errors or overly broad prompts could disclose estate information.
- Files: `src/api/routers/copilot.py`, `src/operations/foundry_agent.py`, `src/operations/tools.py`
- Current mitigation: Requests require read scope, tool results are filtered, and context is placed in the user turn rather than agent instructions.
- Recommendations: Minimize and classify fields before transmission, enforce tenant/business-service scope immediately before the outbound call, document retention/residency, and add red-team tests for prompt injection and cross-scope data leakage.

## Performance Bottlenecks

**Freshness fallback scans complete Delta tables:**
- Problem: If the SQL reader is unavailable, freshness calculation reads every row from each present governed table solely to find a maximum timestamp.
- Files: `src/fabric/sync_service.py`, `src/storage/delta_writer.py`
- Cause: `_global_freshness_watermark` falls back from aggregate SQL queries to full `delta.read` calls across many tables.
- Improvement path: Persist per-table watermarks during writes, use Delta statistics or metadata-only aggregation, and bound fallback work with an explicit degraded/stale state.

**Full generation materialization duplicates large datasets:**
- Problem: Publishing prepares sorted JSONL strings, converts all rows to Parquet in memory, then writes immutable generations and retains three generations.
- Files: `src/hermes_arg_connector/storage.py`
- Cause: `_write_dataset` builds complete serialized representations and `pyarrow.Table.from_pylist` before writing; cleanup is deferred until after activation.
- Improvement path: Stream or batch serialization, write Parquet incrementally, cap dataset sizes, and make retention configurable by environment.

**Autonomous investigation work can outlive the request:**
- Problem: After timeout, worker futures are cancelled where possible but the executor is shut down with `wait=False`; running tasks continue while the request proceeds to reconciliation and executive synthesis.
- Files: `src/operations/autonomous_investigation.py`, `src/api/routers/multi_agent.py`
- Cause: Python threads cannot be forcibly cancelled and the implementation does not propagate a cancellation token to agent work.
- Improvement path: Pass cooperative cancellation through every tool call, enforce per-agent budgets, use a bounded shared executor, and persist asynchronous jobs instead of keeping long work tied to request execution.

## Fragile Areas

**Multi-stage Fabric sync and rollback:**
- Files: `src/fabric/sync_service.py`, `src/storage/delta_writer.py`, `src/ontology/ontology_sync.py`
- Why fragile: Multiple tables are written concurrently, followed by catalog publication, ontology publication, state updates, shortcuts, and rollback. Failures after data commit intentionally retain graph tables, so intermediate states are possible.
- Safe modification: Preserve idempotent run IDs and state transitions, test failures at every stage, and never add a side effect after commit without defining recovery behavior.
- Test coverage: `tests/test_incremental_sync.py` and related Fabric/ontology tests cover core paths, but external OneLake failures, lease expiry, and process termination during commit are not fully exercised.

**Scope narrowing and row-level authorization:**
- Files: `src/api/rbac.py`, `src/api/scope.py`, `src/api/routers/context.py`, `src/api/routers/copilot.py`, `src/api/routers/operations.py`
- Why fragile: Authorization requires both action gating and filtering; several providers return nested structures that are recursively filtered, making a new response shape easy to expose accidentally.
- Safe modification: Add a scope projection for every new field/provider, apply filtering immediately after provider retrieval, and test subscription/business-service combinations plus empty and unrestricted scopes.
- Test coverage: API RBAC tests exist, but each newly added intelligence response needs explicit cross-scope fixtures rather than relying only on route-level tests.

**Cross-platform path and lock behavior:**
- Files: `src/hermes_arg_connector/storage.py`, `src/hermes_arg_connector/onelake_fs.py`, `src/hermes_arg_connector/locking.py`, `src/storage/onelake_writer.py`
- Why fragile: Local paths use platform-specific `Path` behavior while remote paths use URI/string operations; lock acquisition and atomic activation have different guarantees.
- Safe modification: Keep remote paths in POSIX form, reject traversal after normalization, and run local tests on Linux and Windows semantics where supported.
- Test coverage: `tests/test_run_lock.py`, `tests/test_onelake_fs.py`, and `tests/test_onelake_documents.py` exercise adapters, but live service lease and rename behavior require integration coverage.

## Scaling Limits

**In-memory provider and API result processing:**
- Current capacity: API pagination caps individual collection responses at 500 rows, but provider refreshes and many service methods materialize complete datasets.
- Limit: Memory and latency grow with the full ontology, intelligence tables, and concurrent refreshes; three API replicas each maintain their own copies.
- Scaling path: Push filtering, pagination, and aggregates into SQL/Delta queries, use bounded caches, and share immutable snapshot artifacts rather than repeatedly materializing Python lists.

**ARG pagination ceiling:**
- Current capacity: ARG clients permit at most 1,000 pages with a default page size of 1,000.
- Limit: Larger estates fail rather than completing after the ceiling, while a single sync can issue up to one million-row pages of work.
- Scaling path: Add resumable checkpoints, query partitioning by subscription, telemetry for approaching the limit, and an explicit operator-configured maximum.
- Files: `src/hermes_arg_connector/azure.py`, `src/hermes_arg_connector/config.py`, `src/hermes_arg_connector/source.py`

## Dependencies at Risk

**External CLI and image installation supply chain:**
- Risk: The runtime image installs Azure CLI from a remote `https://aka.ms/InstallAzureCLIDeb` script and relies on the `resource-graph` extension; availability or upstream changes can alter builds and runtime behavior.
- Files: `Dockerfile`, `src/hermes_arg_connector/azure.py`
- Impact: Reproducibility and build trust depend on an external installer and mutable extension contents.
- Migration plan: Pin a trusted Azure CLI package/version and extension version, verify checksums/signatures where available, and remove the CLI fallback by using the Resource Graph SDK when its required capabilities are available.

**FastAPI/httpx test-client compatibility warning:**
- Risk: Test collection reports a Starlette deprecation warning because the installed TestClient path uses an older httpx compatibility surface.
- Files: `pyproject.toml`, `tests/test_api_http.py`
- Impact: A future dependency update can break API tests or mask real failures.
- Migration plan: Align FastAPI/Starlette/httpx constraints and migrate tests to the supported client combination before upgrading the dependency set.

## Missing Critical Features

**No durable job model for long-running operations:**
- Problem: Syncs, provider refreshes, and autonomous investigations can be slow but are invoked through synchronous API paths or process-local background threads.
- Blocks: Reliable retries, progress reporting, cancellation, and exactly-once coordination across replicas.
- Files: `src/api/app.py`, `src/api/routers/connections.py`, `src/api/routers/multi_agent.py`, `src/fabric/sync_service.py`

**No production-grade distributed observability contract:**
- Problem: Correlation IDs and request metrics exist, but there is no demonstrated end-to-end trace propagation to ARG, Fabric, Key Vault, or Foundry, nor an explicit alert policy for data freshness, failed rollbacks, or authorization anomalies.
- Blocks: Fast diagnosis of partial ingestion and cross-service latency/security incidents.
- Files: `src/api/telemetry.py`, `src/fabric/telemetry.py`, `infra/terraform/alerting.tf`, `src/operations/foundry_agent.py`

## Test Coverage Gaps

**Live Azure and OneLake failure modes:**
- What's not tested: Token expiry during a request, private endpoint/DNS failures, remote lease expiry/renewal, partial upload, and concurrent remote generation cleanup.
- Files: `src/hermes_arg_connector/azure.py`, `src/hermes_arg_connector/locking.py`, `src/storage/onelake_writer.py`, `src/hermes_arg_connector/storage.py`
- Risk: Production-only failures can leave stale data, overlapping syncs, or unrecoverable generation pointers.
- Priority: High

**Security-boundary integration tests:**
- What's not tested: Direct access to header authentication, production CORS/ingress combinations, Key Vault least privilege, and prompt-injection/cross-scope behavior through Foundry.
- Files: `src/api/auth.py`, `src/api/app.py`, `infra/terraform/container_apps.tf`, `src/api/routers/copilot.py`
- Risk: Configuration drift or a new response shape can bypass otherwise well-tested unit-level authorization.
- Priority: High

**Failure injection across post-commit sync stages:**
- What's not tested: Process death or network failure between data commit, catalog write, ontology publication, state completion, and shortcut creation.
- Files: `src/fabric/sync_service.py`, `src/ontology/ontology_publisher.py`, `src/storage/delta_writer.py`
- Risk: Operators may see completed or failed status that does not fully represent the durable data state.
- Priority: Medium

---

*Concerns audit: 2026-08-23*
