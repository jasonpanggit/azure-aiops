---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 08
current_phase_name: resource-identity-plane
status: executing
stopped_at: Completed 08-02-PLAN.md
last_updated: "2026-08-27T04:10:20.168Z"
last_activity: 2026-08-27
last_activity_desc: Phase 08 execution started
progress:
  total_phases: 4
  completed_phases: 1
  total_plans: 23
  completed_plans: 20
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-08-23)

**Core value:** Operators can move from a detected Azure situation to an evidence-backed, auditable, human-approved remediation without losing context or control.
**Current focus:** Phase 08 — resource-identity-plane

## Current Position

Phase: 08 (resource-identity-plane) — EXECUTING
Plan: 3 of 3
Status: Ready to execute
Last activity: 2026-08-27 — Phase 08 execution started

Progress: ██░░░░░░░░ [█████████░] 87%

## Performance Metrics

**Velocity:**

- Total plans completed: 19
- Average duration: 18 min
- Total execution time: 0.9 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Evidence and Situation Foundation | 2 | 36 min | 18 min |

**Recent Trend:**

- Last 5 plans: 01-02 (22 min), 01-01 (14 min)
- Trend: Stable

**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01 | 14 min | 3 tasks | 21 files |
| Phase 01 P02 | 40 min | 3 tasks | 28 files |
| Phase 01 P03 | 16 min | 3 tasks | 9 files |
| Phase 06 P01 | 8min | 2 tasks | 14 files |
| Phase 06 P02 | 9min | 2 tasks | 9 files |
| Phase 06 P03 | 9min | 2 tasks | 14 files |
| Phase 06 P04 | 18min | 2 tasks | 12 files |
| Phase 06 P05 | 13min | 2 tasks | 13 files |
| Phase 06 P06 | 8min | 3 tasks | 7 files |
| Phase 06 P07 | 9min | 2 tasks | 13 files |
| Phase 06 P08 | 7min | 2 tasks | 10 files |
| Phase 06 P09 | 13min | 2 tasks | 8 files |
| Phase 07 P01 | 35min | 3 tasks | 7 files |
| Phase 07 P02 | 8min | 2 tasks | 26 files |
| Phase 07-unified-resource-inventory P03 | 11min | 5 tasks | 21 files |
| Phase 07-unified-resource-inventory P04 | 7min | 3 tasks | 7 files |
| Phase 07-unified-resource-inventory P05 | 8min | 3 tasks | 9 files |
| Phase 07-unified-resource-inventory P06 | 8min | 3 tasks | 7 files |
| Phase 08 P01 | 45min | 3 tasks | 7 files |
| Phase 08 P02 | 55min | 2 tasks | 11 files |

## Accumulated Context

### Decisions

Recent decisions affecting current work:

- [Phase 7]: **Fabric pivot (2026-08-26)** — Fabric/OneLake is the unified inventory data platform and durable source of truth for inventory. Inventory acquisition and normalization still belong to the inventory domain, but publication targets governed Fabric-backed inventory tables/lakehouse datasets rather than a repo-local/Hermes generation root as the final architecture.
- [Phase 7]: Live Fabric deployment evidence (2026-08-26) — `inventory-refresh --fabric-config fabric.config.yaml --connection-id local-spn` published to workspace `1c328da7-2490-48dc-9ba6-de8c1f333756` / lakehouse `aef9854d-ab23-413e-a86d-99a344a269c0`; run `0bc31dd4-7965-4650-91f0-b6347c635400` completed with ARG-backed `inventory_os_observations`, `inventory_resource_observations`, and source-status tables written to OneLake.
- [Phase 7]: LAW auth audience fix (2026-08-26) — Azure Monitor Logs tokens use `https://api.loganalytics.io/.default`; the live query now authenticates and returns a semantic source error because workspace `4cf2b41b-bace-4dd6-8ec0-61c7050ed552` has no `ConfigurationData` table.
- [Phase 7]: The original 07-03 was superseded and replaced. Execute only the new Fabric-backed 07-03 plan, which defines Fabric table contracts, OneLake persistence, Fabric quality gates, and inventory-owned publication/read compatibility before removing Hermes ownership.
- [Phase 7]: Hermes remains a consumer: it performs graph construction, relationship modelling, semantic traversal, and agent-safe context packaging from Fabric-backed unified inventory and must not manage inventory lifecycle or call ARG for inventory identity once the pivot is implemented.
- [Phase 7/8]: Hermes is not an autonomous/self-learning discovery agent. Its current discovery path is deterministic coded acquisition and normalization; under the Fabric pivot, source discovery/acquisition/cataloguing/ETL belong to Fabric/inventory. Preserve Hermes only for graph-specific value: relationship/topology inference, confidence/provenance modelling, traversal, semantic query APIs, and agent-safe context packaging.
- [Phase 7]: Two publishers sharing one generation root also share `state/dataset_hashes.json`. A partial publish marks every absent dataset as removed (`storage.py:128`) and overwrites the hash baseline wholesale (`storage.py:143`), destroying Hermes incremental-change detection. Publication must merge-not-replace or namespace per domain — planned as 07-03 T1a, ahead of the tracer.
- [Phase 7]: The `"hermes_arg_connector"` `source_engine` literal in `intelligence/inventory/models.py:208,219` is a frozen published dataset value protected by D-06. Decoupling greps must be import-anchored so no executor "cleans up" a published field value.
- [Phase 7]: Inventory does NOT ride along with `_preserve_created_timestamps` / `_preserve_source_watermarks` — those iterate `graph.source_status`, while inventory status lives on the separate `graph.inventory_software_source_status` (`service.py:122`). The CONTEXT claim was wrong; 07-01 T2 verifies empirically and "no such behavior exists" is a valid recorded outcome rather than a manufactured passing test.
- [Phase 7]: Characterization tests reach their driver only through a single named seam (`tests/inventory_harness.py`). Without it the suite is coupled to Hermes being the publisher and would need editing during the inversion — the D-05 failure mode.
- [Phase 7]: Golden rows and key sets are captured as source literals, never derived from `to_dict()` of the object under test. A self-referential assertion moves with the refactor and can never fail.
- [Phase 7]: 07-01 completed the contract characterization baseline. The test suite now pins the four published inventory dataset names, representative golden machine/software rows, source-status key shapes, group keys, evidence fields, failed-refresh retention, successful empty refresh, no pre-generation snapshot, and pagination behavior.
- [Phase 7]: Empirical preservation finding from 07-01: inventory timestamp/watermark preservation does not exist today; `inventory/software_source_status` has no `watermark`, and inventory created/observed timestamps are regenerated per run. 07-03 task 2's preservation requirement is therefore dropped unless new behavior is intentionally introduced.
- [Phase 7]: 07-02 moved immutable dataset publication into neutral `storage.datasets.DatasetStore`. The neutral store takes explicit dataset mappings and caller-supplied ontology metadata, and imports no Hermes modules. `hermes_arg_connector.storage.DatasetStore` remains as the graph-shaped compatibility shim for Hermes until ownership inversion.
- [Phase 7]: Shared OneLake filesystem and run-lock helpers now live in `storage.fs`, `storage.onelake_fs`, and `storage.locking`; old Hermes paths are compatibility re-exports.
- Build on existing FastAPI, Next.js, OneLake/Delta, Fabric, Entra, and Terraform foundations.
- Sequence evidence and approval before any write adapter; keep remediation typed, allowlisted, bounded, and human-approved.
- Treat Fabric Ontology as a projection and Azure services as systems of record.
- [Phase ?]: Use compact immutable Pydantic situation/evidence records with deterministic IDs and keep raw provider payloads outside API responses.
- [Phase ?]: Preserve overlapping pre-existing worktree edits and commit only newly owned situation foundation files.
- [Phase ?]: Keep all six source families on the existing NormalizedGraph and immutable generation path; do not add a parallel ingestion store.
- [Phase ?]: Persist unresolved operational links with explicit quality instead of dropping targets absent from the authorized entity index.
- [Phase ?]: Use service-recorded audit events only for audit history; local Save view locally state is not server audit.
- [Phase ?]: Treat each nested audit event scope_snapshot as an authorization predicate before serialization.
- [Phase ?]: Derive freshness from UTC timestamp age bands with valid provider bands preserved.
- [Phase ?]: Keep service-recorded audit failure distinct from successful empty history and local collaboration.
- [Phase ?]: D-01: Group OS observations by canonical OS name/version and use server-owned keys for drill-down.
- [Phase ?]: D-02: Keep Azure VM and Arc source labels in one grouped view without collapsing source identity.
- [Phase ?]: D-09: Unknown lifecycle matches remain visible with an explicit EOL date review flag.
- [Phase ?]: Read source status from the active immutable generation and scope row counts before projection.
- [Phase ?]: Native VM image SKU and latest image version remain image metadata; installed OS release remains Unknown without an installed observation.
- [Phase ?]: Native VM and Arc ARG queries remain independent so a family failure is degraded without erasing usable rows.
- [Phase ?]: Environment uses case-insensitive resource tags in environment, env, environmentName precedence and otherwise persists Unknown.
- [Phase ?]: ConfigurationData uses Azure Monitor Logs Query API rather than Azure Resource Graph.
- [Phase ?]: Canonical software identity and exact resource joins preserve current state, raw identity, and environment without hostname inference.
- [Phase ?]: Logs source status distinguishes successful empty results from malformed, failed, or degraded data.
- [Phase ?]: Only validated server-owned workspace mappings are queried for each connection; browser workspace selection is not accepted.
- [Phase ?]: Logs lifecycle distinguishes unavailable, ready empty, partial, degraded, and stale states while retaining last-known rows after failed refreshes.
- [Phase ?]: Inventory freshness is read from the active immutable generation manifest so stale data remains available but clearly marked.
- [Phase ?]: Curated lifecycle catalog is consulted at request time; catalog misses remain review-required and never auto-select a candidate.
- [Phase ?]: Lifecycle confirmation uses effective operate scope, exact normalized OS keys, validated HTTPS provenance, and atomic optimistic revisions.
- [Phase ?]: D-06: Keep the curated lifecycle catalog server-owned, revisioned, and authoritative at request time.
- [Phase ?]: D-07: Preserve endoflife.date, official-vendor, and web/LLM candidates independently with citations and source failures.
- [Phase ?]: D-08: Require explicit operator confirmation with an expected catalog revision; never auto-select a candidate.
- [Phase ?]: D-14: Keep external web/LLM resolution disabled until an approved provider endpoint and credential contract is configured.
- [Phase ?]: Only approved software mappings may affect grouped counts; suggestions and rejections remain review state.
- [Phase ?]: Software mapping mutations require effective operate scope and expected per-mapping revision.
- [Phase ?]: External web/LLM search remains disabled unless approved provider configuration exists.
- [Phase ?]: Build narration from server-owned, scope-filtered OS and approved software aggregates only.
- [Phase ?]: Keep fact summary, model narration, confidence, citations, source status, and warnings as separate response fields.
- [Phase ?]: Keep Foundry optional; timeout, malformed, ungrounded, or unavailable output degrades to fact-only inventory.
- [Phase ?]: Use semantic ARIA tabs and one discoverable Software Inventory route for OS and Installed Software.
- [Phase ?]: Narrow subscription selection through the existing authorized API scope; keep other filters as views over returned rows.
- [Phase ?]: Export only exact authorized software detail rows with quoted and formula-protected CSV cells.

- [Phase 7]: Hermes is a consumer of inventory, never its owner; inventory owns its own acquisition, normalization, retention, status, and publication.
- [Phase 7]: Phase 6 UAT entry gate waived (2026-08-26, operator decision) — Phase 7 relocates the pipeline UAT would exercise, so verification is deferred into Phase 7 exit criteria and paid once against the final pipeline.
- [Phase 7]: Because no verified live baseline exists, characterization tests asserting dataset names, row shapes, and the failed-refresh retention rule are a hard precondition before any code moves.
- [Phase 7]: Blast radius corrected — "53 files" measured module coupling, not inventory coupling. Real surface is 6 src + 4 test files with exactly one cross-domain inventory read (`hermes_arg_connector/service.py:116`). Risk is behavioral (retention rule, publication timing, timestamp/watermark preservation), not structural.
- [Phase 7]: Full Phase 7 elected over the 7a/7b split; the split only de-risked starting before sign-off, which no longer applies.
- [Phase 7]: Sequence is characterize → extract → invert → expand → migrate consumers; consumer migration includes the Hermes side.
- [Phase 8/9]: Inventory owns the resource **identity** plane (what exists, type, location, tags, containment, raw properties); assessment domains (patch/vuln/policy/advisor/metrics/health) keep their own planes and join by resource ID. Prevents inventory becoming a god module.
- [Phase 8]: `ResourceObservation` must preserve the full raw property bag and watermark semantics, designed from Hermes's real read patterns rather than UI needs — otherwise Hermes cannot drop its ARG identity path.
- [Phase 8]: Operator direction (2026-08-27) is to treat Hermes removal as the default hypothesis because Fabric/Fabric IQ and Foundry cover governed graph access and grounded AI assessment. Hermes remains only if the reproducible Phase 8 comparison demonstrates material unique operator value.
- [Phase 9]: API pivot is mostly wiring — routers already depend on `ProviderSpec` providers, not datasets; no router reads `read_dataset`/`entities/` directly. `agent_queries.py` is the exception.
- [Phase 7/8/9]: Split the system-wide pivot into three phases rather than one. Inverting ownership, redefining the resource contract, and rewiring consumers simultaneously — with no verified live baseline — is the failure mode the waived gate was meant to prevent.
- [Phase ?]: Phase 7 Plan 03 selected new-fabric-names-with-adapter for inventory Fabric tables while preserving inventory/* compatibility aliases.
- [Phase ?]: Phase 7 Plan 03 made DatasetStore compatibility/local staging while InventoryPipeline owns refresh and Fabric-backed publication.
- [Phase ?]: Phase 7 Plan 04 stores ResourceObservation provider payloads as canonical provider_payload_json in Fabric while keeping API payloads redacted.
- [Phase ?]: Phase 7 Plan 05 projects PaaS from one generic Resources inventory query and exposes only identity-plane route fields.
- [Phase ?]: Phase 7 Plan 06 established InventoryReadPort as the scope-required cross-domain inventory access path; direct inventory dataset reads outside inventory are guarded.
- [Phase ?]: Containment derived in-process from existing ResourceObservation fields; no persisted containment table, no separate ResourceContainers acquisition path
- [Phase ?]: Management-group ancestry left None (not fabricated) since ResourceObservation lacks it yet
- [Phase ?]: identity_source flag defaults to arg; IngestionService only requires inventory_read_port when flipped to inventory
- [Phase ?]: 08-02 checkpoint: Fabric-native compute architecture = fabric-hosted-notebook (genuine Fabric Spark notebook, demoable, not Python-writer extension)
- [Phase ?]: 08-02 checkpoint: NSG Flow Logs/Traffic Analytics = fixture only (no live provisioning; flag allowed-vs-observed as fixture-only in 08-03 comparison report)
- [Phase ?]: 08-02 checkpoint: Traversal mechanism = fabric-iq-native (no azure-kusto-data, no KQL/Gremlin, ontology-binding step is both registration and traversal surface)

### Roadmap Evolution

- Phase 6 added: Software and OS Inventory Visibility — UI page extracting OS inventory (Azure VMs + Arc-enabled servers) and installed software (Arc Change Tracking & Inventory) from ARG, with OS EOL dates from official vendor sources.
- Phase 7 added: Unified Resource Inventory — inventory becomes an independent domain owning acquisition, normalization, retention, and status while publishing to Fabric/OneLake as the unified data platform; generalizes to all resource families including PaaS; consumed by the semantic graph rather than owned by it.
- Phase 6 UAT re-scoped (2026-08-26): entry gate waived; the five residual walkthroughs plus windows #9-#13 now close under Phase 7 exit criteria.
- Phases 8 and 9 added (2026-08-26): operator directed that Hermes pivot to unified inventory for discovery and semantic modelling instead of calling ARG directly, and that web/API pivot to it for the UI. Scoped as Phase 8 (resource identity plane; Hermes drops ARG identity queries) and Phase 9 (API/agent-queries/web pivot) rather than folded into Phase 7.

### Pending Todos

- Complete remaining live Phase 7 verification: enable or target a Log Analytics workspace with `ConfigurationData`, rerun software inventory publication, then complete browser UX/accessibility walkthroughs for OS/software, failed-refresh retention, exact software/version search, EOL citation review, PaaS drill-down, and per-family degradation.
- Triage the three recorded full-suite failures in `.planning/WINDOWS.md` so full-suite green is a usable signal after Phase 7.
- Configure `APPROVED_SEARCH_API_ENDPOINT` / `APPROVED_SEARCH_API_KEY` if the third EOL source is operationally required.

### Blockers/Concerns

- Phase 7: Implementation plans 07-01 through 07-06 are complete and ARG-backed Fabric inventory tables have been deployed. LAW software inventory remains source-degraded until the configured workspace exposes `ConfigurationData`; browser verification remains open in `.planning/WINDOWS.md`.
- Phase 7: Confirmed via Fabric REST API (2026-08-26) that all 5 `inventory_*` Delta tables are registered in lakehouse `operational_context_graph`, and that the native `Inventory Refresh` DataPipeline plus enabled 60-minute Cron schedule exist and run successfully end-to-end. Root cause of the earlier `CapacityNotActive`/`datasetSettings` failures: capacity was paused (now started) and the Fabric connection was created with the wrong type (`"Web"` instead of `"WebForPipeline"`, which is required for pipeline WebActivity). Fixed connection type + activity `relativeUrl` field in `push_inventory_refresh_pipeline.py`; re-pushed and verified an on-demand run reaches `Completed` with the API logging `200 OK` on `POST /api/v1/inventory/refresh`.
- Phase 7: Proceeding without a verified live inventory baseline. Live-only regressions introduced by the refactor cannot be distinguished from pre-existing Phase 6 defects. Accepted risk; mitigated by characterization tests rather than empirical comparison.
- Phase 8: **Contract losslessness is the pivot's single point of failure.** If `ResourceObservation` cannot carry the full raw property bag and per-family watermark semantics, Hermes must keep its own ARG identity path and the pivot cannot complete. Resolve by auditing Hermes's actual reads into `properties` (normalize.py, network_normalize.py, identity specs) *before* fixing the contract shape. Also validate whether Hermes adds graph-specific value beyond deterministic acquisition/normalization; if not, do not preserve a separate Hermes discovery role.
- Phase 9: Web page impact is unaudited. Pages surfacing resource identity (`services`, `search`, `investigate`, `twin`, `changes`) need review at plan time; the "most pages need no change" expectation rests on route contracts holding.

- Phase 1: Validate exact provider contracts, permissions, pagination, watermarks, retention, and cross-domain identity normalization.
- Phase 2: Select and validate durable workflow and approval expiry semantics.
- Phase 3: Validate remediation API versions, rollback semantics, execution identity, and AI/data boundaries.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v2 | Broad integrations, actions, multi-cloud, retraining, and policy-exemption mutation | Deferred | 2026-08-23 |

## Session Continuity

Last session: 2026-08-27T04:10:20.153Z
Stopped at: Completed 08-02-PLAN.md
Resume file: None
