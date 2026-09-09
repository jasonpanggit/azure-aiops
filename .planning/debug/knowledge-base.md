# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## fabric-topology-rollout — Topology tables missing from present_known/active during staged Fabric rollout
- **Date:** 2026-09-01
- **Error patterns:** topology_entities missing present_known, topology_edges missing present_known, topology tables not active, expected_missing_undispositioned
- **Root cause(s):** Topology rollout required an AND-gate fix across three missing mechanisms: runtime/config never enabled topology sync, schema registry omitted topology tables from known set, and sync lacked publication-manifest active upserts; additionally topology rows had to be mapped into governed envelope shape to satisfy data-quality validation.
- **Fix:** Added topology/ontology pipeline flag parsing in config, passed `topology_enabled` through runtime into sync service, derived and emitted governed topology rows (`topology_entities`, `topology_edges`) during sync, upserted active publication-manifest records for topology tables, and registered governed topology schemas in schema registry.
- **Files changed:** src/fabric/config.py, src/fabric/runtime.py, src/fabric/sync_service.py, src/fabric/schema_registry.py, tests/test_fabric_client.py, tests/test_incremental_sync.py, tests/test_topology_pipeline.py
- **Why not caught:** Existing gates only exercised standalone topology pipeline behavior; no integration gate validated topology-flag runtime wiring + known-table classification + manifest disposition under staged rollout conditions.
- **Recurrence guard:** Regression tests now lock the integration contract end-to-end (`tests/test_fabric_client.py::test_fabric_runtime_config_resolves_local_paths`, `tests/test_incremental_sync.py::test_sync_with_topology_flag_publishes_topology_tables`, `tests/test_topology_pipeline.py::test_validator_known_table_set_includes_topology_contract_tables`) plus governed topology schema registration.
---

## foundry-portal-model-support — Foundry portal rejected the prompt-agent model for Azure AI Search
- **Date:** 2026-09-01
- **Error patterns:** model not supported, Foundry portal, gpt-5-mini, Azure AI Search, Knowledge section
- **Root cause(s):** The specialists used `gpt-5-mini`, which Microsoft supports for MCP and Responses but not for the direct Azure AI Search prompt-agent tool; the portal correctly reported the unsupported model/tool combination even though the backend executed it successfully.
- **Fix:** Updated the managed prompt-agent model defaults to supported GA `gpt-5.4-mini` `2026-03-17` and applied the model/agent-only Terraform cutover.
- **Files changed:** infra/terraform/variables.tf, infra/README.md
- **Why not caught:** No gate existed for Foundry portal model/tool compatibility; runtime Search success could not detect a combination that works on the data plane but is explicitly unsupported by the portal contract.
- **Recurrence guard:** The config-default change in `infra/terraform/variables.tf` selects `gpt-5.4-mini` `2026-03-17`, whose current official matrix row supports both Azure AI Search and MCP; this KB pattern records that runtime success is not a substitute for compatibility-matrix validation.
---

## remediation-e2e — Unchanged live remediation action became stale between GET and approval
- **Date:** 2026-09-05
- **Error patterns:** HTTP 409, Remediation plan action version is stale, stale_action_version, action_version, CVE enrichment, citation order
- **Root cause(s):** Independent GET and decision-POST plan generations could vary optional KB-to-CVE enrichment or finding order, while live patch action-version construction hashed those derived suffixes and selected the first 10 citations before canonicalizing the complete evidence set.
- **Fix:** Normalize live patch citation IDs to their case-insensitive source-owned identities, strip only runtime-appended CVE/KB suffixes, deduplicate and sort before applying the 10-citation bound, and cover the request-to-request approval flow.
- **Files changed:** src/semantic/live_operations.py, tests/test_remediation_identity_and_audit_continuity.py, tests/test_api_remediation_approvals.py, .planning/debug/resolved/remediation-e2e.md
- **Why not caught:** Existing stability tests reused one unchanged in-memory planner and did not vary derived enrichment identities, source-id casing, or evidence ordering across the 10-citation boundary.
- **Recurrence guard:** `tests/test_remediation_identity_and_audit_continuity.py::test_live_patch_action_version_ignores_derived_cve_enrichment`, `::test_live_patch_action_version_canonicalizes_citations_before_limiting`, and `tests/test_api_remediation_approvals.py::test_patch_approval_survives_request_to_request_cve_enrichment_drift`.
---

## network-topology-live-ui — Warm topology requests blocked on provider refresh and hub ARM IDs failed routing
- **Date:** 2026-09-08
- **Error patterns:** full-detail p95 14397 ms, repeated 9–22 second network requests, Hub VNet not found, 404, leading slash missing, slash-prefixed ARM id
- **Root cause(s):** `ProviderRuntime.get()` synchronously resolved cache keys and could execute loaders on request threads, so slow Fabric semantic-version I/O delayed every managed-network endpoint; slash-prefixed hub ARM IDs were also transported through a lossy wildcard path and no longer matched the authorized snapshot after route normalization.
- **Fix:** Made `ProviderRuntime.get()` a state-lock-only last-known-good read owned by startup/background refresh, and added an exact query-parameter hub-dependents route used by the web client while retaining the legacy path adapter.
- **Files changed:** src/api/app.py, src/api/providers.py, src/api/routers/network.py, tests/test_api_network.py, tests/test_api_providers.py, tests/test_api_runtime.py, tests/test_exposure_consumer_parity.py, web/src/lib/network-services.test.ts, web/src/lib/services.ts, web/e2e/network-topology-deployed.spec.ts
- **Why not caught:** Provider tests pinned request-owned refresh behavior, and the earlier route regression checked encoded URL text rather than passing a slash-prefixed ARM ID through the actual FastAPI route stack; authenticated post-deploy timing was the first gate to expose the combined environment amplification.
- **Recurrence guard:** `tests/test_api_providers.py::{test_get_is_a_strict_last_known_good_read_without_refresh_io,test_concurrent_gets_do_no_io_during_background_refresh,test_initial_get_during_background_startup_does_not_duplicate_io}`, `tests/test_api_network.py::TestHubDependents::test_query_route_preserves_the_exact_slash_prefixed_arm_id`, the web query-contract test, and the unchanged authenticated five-sample p95/hub-200 checks in `web/e2e/network-topology-deployed.spec.ts`. The authenticated p95 <1,000 ms and hub-route run remains pending until a later authorized redeploy.
---

## network-topology-live-ui-final-timing — Server topology budget was applied to full Azure round-trip latency
- **Date:** 2026-09-08
- **Error patterns:** 9/10 live checks, HTTP p95 1646-1794 ms, server p95 unobservable, topology latency gate
- **Root cause(s):** The topology route exposed no post-serialization handler duration, so deployed Playwright compared full client-to-Azure round-trip p95 with the server-only <1,000 ms topology-build requirement.
- **Fix:** Added `X-AIOPS-Handler-Ms` around topology analysis plus FastAPI response serialization, then split the same five samples into strict server-handler p95 <1,000 ms and end-to-end HTTP p95 <3,000 ms gates with diagnostic distributions.
- **Files changed:** src/api/routers/network.py, tests/test_api_network.py, web/src/lib/network-topology-latency.ts, web/src/lib/network-topology-latency.test.ts, web/e2e/network-topology-deployed.spec.ts, .planning/phases/12-network-topology-integrity-and-scale/12-UI-REVIEW.md, .planning/phases/12-network-topology-integrity-and-scale/12-VERIFICATION.md
- **Why not caught:** The acceptance harness had one elapsed timer and no response-level server metric, so it could not distinguish server work from Azure ingress, TLS, network, and client overhead.
- **Recurrence guard:** `tests/test_api_network.py::TestTopology::{test_reports_handler_time_for_analysis_and_response_serialization,test_handler_time_header_is_additive_and_numeric,test_handler_timing_does_not_change_auth_or_error_responses}`, `web/src/lib/network-topology-latency.test.ts`, and the two explicit soft assertions in `web/e2e/network-topology-deployed.spec.ts`.
---

## network-summary-messages-links — RouteTable-to-firewall semantics depended on omitted Route IDs
- **Date:** 2026-09-08
- **Error patterns:** summary zero next_hop edges, full Route next_hop resolves AzureFirewall, RouteTable firewall edge missing, intentionally_omitted_ids, routes_via
- **Root cause(s):** The prior corrective implementation encoded RouteTable→AzureFirewall only as a summary-time source rewrite of each Route→AzureFirewall `next_hop` when the Route appeared in `intentionally_omitted_ids`; it emitted no first-class direct relationship and coupled summary semantics to omission bookkeeping.
- **Fix:** Preserve detailed Route→AzureFirewall `next_hop` edges and independently emit one sorted, deduplicated, provider-backed RouteTable→AzureFirewall `routes_via` relationship in Summary and Full detail for every uniquely resolved in-scope firewall target.
- **Files changed:** src/network/topology.py, tests/test_network_topology.py, web/src/lib/network-graph.test.ts, .planning/phases/12-network-topology-integrity-and-scale/12-UI-REVIEW.md, .planning/phases/12-network-topology-integrity-and-scale/12-VERIFICATION.md
- **Why not caught:** The existing topology gate asserted the projection workaround itself—summary `next_hop` with a substituted source—rather than requiring a distinct direct semantic in both detail levels, omission independence, deterministic multi-route deduplication, and unresolved/scope negatives.
- **Recurrence guard:** `tests/test_network_topology.py::{test_virtual_appliance_route_links_to_the_firewall_it_targets,test_route_table_firewall_relationship_is_deduplicated,test_unresolved_route_next_hop_does_not_infer_a_firewall_relationship,test_route_does_not_resolve_to_a_firewall_outside_authorized_scope}` and `web/src/lib/network-graph.test.ts` test `accepts provider-backed route-table to firewall relationships`.
---

## phase031-plan19-publication-atomicity — Hard death exposed partial canonical ontology heads as retry predecessors
- **Date:** 2026-09-09
- **Error patterns:** exit 137, absent Gold pointer, partial canonical ontology head, fresh retry, Ontology synchronized relationship graph exceeds bound, 467448 relationships
- **Root cause(s):** Canonical ontology publication had no durable completed-version marker, so hard exit 137 left newer per-table heads that a fresh service consumed as predecessor; relationship IDs also included mutable event intervals, making 231990 unchanged semantic edges look retired and recreated; at production cardinality this generated 233424 false tombstones and a 467448-row synchronized graph. The remote sync lock's active-lease breaking and unpinned activation source were independent publication-order defects that permitted interleaving.
- **Fix:** Record exact canonical entity/relationship Delta versions in the completed ingestion-state row after canonical finalization and before pointer activation; read lifecycle and semantic rows at that authoritative pair; materialize empty canonical version-0 tables; derive relationship identity from endpoint triples while retaining interval evidence in payload/history; enforce an exclusive renewable OneLake lease; pin activation to its immutable source run; and emit count-only overflow diagnostics.
- **Files changed:** src/fabric/schema_registry.py, src/fabric/sync_service.py, src/onboarding/activation.py, src/ontology/ontology_sync.py, src/ontology/relationship_builder.py, src/storage/delta_writer.py, src/storage/onelake_writer.py, tests/test_delta_tables.py, tests/test_fabric_sync_service.py, tests/test_onboarding_activation.py, tests/test_onelake_writer.py, tests/test_operational_context_graph_v2_hardening.py
- **Why not caught:** No gate modeled hard process death across fresh service instances or asserted a canonical completed-version pair; existing tests covered caught exceptions and pointer non-activation only. Relationship tests asserted row validity but not identity stability across mutable evidence intervals, and the lock test explicitly encoded unsafe active-lease breaking.
- **Recurrence guard:** Specified regression tests in `tests/test_fabric_sync_service.py` cover pre-marker partial death, finalized pre-pointer versions, post-pointer partial overwrite, semantic-reader time travel, and finalization order; `tests/test_operational_context_graph_v2_hardening.py` locks endpoint-stable identity and count-only bounds; `tests/test_onelake_writer.py` locks exclusive finite renewal/loss semantics; `tests/test_onboarding_activation.py` locks immutable activation source selection.
---

## phase031-plan19-delta-append-memory — Large Delta APPEND exhausted memory and bounded retries exposed partial commits
- **Date:** 2026-09-09
- **Error patterns:** exit 137, table 54, silver_exposure_observations, Delta APPEND, 154000 rows, partial Delta transaction, rows_added=0, skipped=True, active file without statistics, transient preflight failure
- **Root cause(s):** The original APPEND path eagerly duplicated the complete input, built one full Arrow table, and converted the complete target to Python rows; the valid approximately 154000-row temporal input and approximately 1.9 GiB remaining cgroup headroom jointly made that latent scale defect fatal. The first bounded correction used approximate `DeltaTable.count()` as an emptiness gate and moved mandatory preflight outside the retry envelope. Its per-chunk Delta transactions then exposed earlier chunks when a later batch failed, while final-attempt-only accounting misreported a successful commit followed by a transient exception as `rows_added=0` and `skipped=True`.
- **Fix:** Preflight immutable conflicts through retryable bounded incoming-key filters using active-file presence, derive only missing source indices, and feed lazily materialized configured-size RecordBatches through one `write_deltalake` transaction. Stamp each attempted transaction with a unique invocation ID and intended added-row count, then recover the matching bounded-history entry before retry deduplication after an ambiguous post-commit exception. Emit sanitized table-start name/count diagnostics.
- **Files changed:** src/storage/delta_writer.py, src/fabric/sync_service.py, tests/test_delta_tables.py, tests/test_fabric_sync_service.py
- **Why not caught:** The existing test/verify gate exercised only small APPENDs, happy-path idempotency, and caught publication exceptions. It did not assert N-1/N/N+1 materialization bounds, one transaction across multiple batches, absent/present target atomicity after a later batch failure, post-commit retry attribution, active files without row statistics, or complete preflight retry coverage.
- **Recurrence guard:** `tests/test_delta_tables.py::{test_delta_writer_append_bounds_python_and_arrow_materialization,test_delta_writer_append_is_atomic_when_later_batch_materialization_fails,test_delta_writer_append_reports_commit_that_raised_transient_error,test_delta_writer_append_rejects_conflict_when_active_file_lacks_statistics,test_delta_writer_append_deduplicates_active_file_without_statistics,test_delta_writer_append_retries_transient_preflight_existence_lookup,test_delta_writer_append_retries_transient_preflight_filtered_read}` locks the bounded, atomic, immutable, and truthfully attributed APPEND contract. `tests/test_fabric_sync_service.py::{test_deployed_publication_orders_observations_after_workload_checkpoint,test_sync_reports_successful_table_writes_in_completion_order}` locks the table-54 ordering evidence and sanitized start diagnostic.
---
