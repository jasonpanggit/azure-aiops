# Phase 10: Fabric Medallion Capability Expansion - Research

**Researched:** 2026-09-01
**Domain:** Microsoft Fabric medallion data platform governance (Bronze/Silver/Gold), Fabric IQ Ontology publication, Direct Lake semantic serving, Fabric Data Agent grounding, OneLake security, capacity/lineage/Delta maintenance, and the API/web surfaces that expose all of it.
**Confidence:** HIGH for repository-state claims (all verified by reading source/tests/live git history/live `pytest`/live `az` calls this session). MEDIUM-HIGH for Microsoft Fabric platform claims (all fetched live from `learn.microsoft.com` this session, cross-checked against this repo's own working implementation where one exists). LOW only where explicitly marked `[ASSUMED]`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Publication integrity and rollout**
- Preserve and complete the existing uncommitted ontology-sync, Defender, compliance, confidence, pending-relationship, API, and web work on `fix-ontology-sync-publish`; do not reimplement or overwrite it.
- Make vocabulary and endpoint-type validation a runtime preflight before any externally visible ontology publication boundary, backed by the existing consistency tests.
- Use bounded exponential retry only for transient Fabric failures; validation and contract failures fail immediately with durable, operator-visible diagnostics.
- Sequence live rollout as integrity gates first, then metadata/status and manifests, then individual Silver/Gold pipelines with rollback, and finally semantic consumers and Data Agent grounding.

**Dataset restoration and lifecycle**
- Give every code-declared or previously expected dataset an explicit disposition: populated and verified, intentionally empty with healthy source status, or retired with versioned compatibility evidence.
- Restore topology, operational-context, and assessment Gold outputs individually; do not enable all pipelines in one uncontrolled capacity spike.
- Empty ontology projections remain physically available when required by Fabric bindings, but are marked dormant in the manifest. Automatic destructive deletion is out of scope.
- Unified inventory remains the sole resource-identity authority; Gold products and semantic models consume its contracts rather than creating a parallel identity source.

**Freshness, quality, and history**
- Freshness objectives are configurable per dataset and default to a bounded multiple of the producing pipeline cadence rather than one global hard-coded threshold.
- API status distinguishes healthy-empty, stale, degraded, failed, retired, and unavailable; zero rows alone never imply success or failure.
- Enforce referential integrity as a publication blocker. Ownership and tag coverage are configurable quality thresholds that can warn or block by environment.
- Retain append-only or merge-based historical facts for cost, compliance, patch, change, incident, and lifecycle trends while current-state tables remain optimized for operational reads.

**Consumption and Data Agent**
- Add curated, versioned Gold consumption contracts and Fabric-native semantic-model definition/deployment support where the current public API supports it.
- If a Fabric preview surface cannot be deployed automatically, produce a validated versioned definition and expose an explicit deployment-blocked state; do not silently report success.
- Keep physical per-type ontology tables behind manifests/views/contracts so API, web, and agent consumers use stable logical names.
- Expand the existing relationship-suggestion Data Agent only after curated Gold outputs are healthy, and add reproducible offline evaluation plus optional live evaluation.

**API and web experience**
- Add a dedicated scope-enforced Fabric medallion health/capabilities API because table-level SLO, quality, lineage, and lifecycle data does not fit the connection-health contract.
- Extend the existing Data & Integrations/Connections experience with a Bronze/Silver/Gold health view rather than creating a disconnected administration product.
- Show layer summaries, freshness/SLO status, failed runs, empty-versus-unavailable state, publication-manifest lifecycle, governance gaps, and semantic/Data Agent readiness.
- Preserve existing API response-envelope, authentication, accessibility, responsive-layout, and partial-degradation patterns.

**Security, lineage, capacity, and maintenance**
- Use defense in depth: existing application scope enforcement remains mandatory and Fabric-native roles/RLS are added where supported.
- Use managed identity in deployed environments, least-privilege roles, no embedded secrets, and no broad workspace mutation from end-user requests.
- Formalize internal provenance and Fabric item lineage first; integrate external Purview surfaces only through supported APIs and explicit configuration.
- Add capacity paused/throttled detection and observable maintenance status. Delta compaction/vacuum must be scheduled, bounded, retention-safe, and never run implicitly on an API request.

### the agent's Discretion
- Exact module boundaries, route names, component composition, visual density, default SLO multipliers, and plan grouping may follow established repository patterns.
- The planner may split infrastructure-heavy semantic model, RLS, lineage, capacity, and maintenance work into separate plans while keeping all MED requirements in Phase 10.

### Deferred Ideas (OUT OF SCOPE)
- Fully autonomous production remediation remains outside this phase.
- Multi-cloud medallion ingestion and replacement of enterprise systems of record remain deferred.

### Specific Ideas (from CONTEXT.md, treated as acceptance-case hints, not independently re-verified against a live scan this session)
- Baseline the phase against the live scan: 320 readable tables; Bronze 9/8 non-empty; Silver 18/14; Gold 288/140; ontology 2,091 entities and 1,669 relationships; 84 missing ownership and 52 missing tags; ingestion history 9 completed and 12 failed. **Research note:** no artifact matching these exact figures was found committed anywhere in the repo this session (searched `.md`/`.json` for the literal numbers) — treat as `[CITED: 10-CONTEXT.md]`, not `[VERIFIED]`. The tool that can reproduce this class of scan live is `scripts/validate-lakehouse-tables.py` (read this session — see Architecture Patterns).
- Treat the current undefined relationship endpoint class and the stale inventory/source-status gaps as concrete acceptance cases, not hypothetical examples.
- Keep live deployment reversible and avoid destructive changes to APIM or unrelated Azure resources.

### Project Constraints (from copilot-instructions.md)
No `./copilot-instructions.md` was found in the working directory at research time (config.json points `claude_md_path` at `./.github/copilot-instructions.md`, which also does not exist). No project-level directive extraction was possible; none contradicts anything below.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MED-01 | Fabric ontology publication validates entity/relationship vocabulary before commit, retries transient failures within bounded limits, and exposes terminal failures through durable state and telemetry. | `ontology_publisher.py`'s preflight already runs before any network call (verified this session); `fabric_client.py` already has a generic LRO/retry-after poller. Gap: durable *queryable* terminal-failure state and telemetry emission. See Requirement-by-Requirement Findings §MED-01. |
| MED-02 | Expected Gold topology, assessment, and operational-context outputs are live and verified or explicitly retired through a versioned compatibility disposition. | `scripts/validate-lakehouse-tables.py` is the existing live-vs-code-declared table reconciliation tool. `fabric_pipelines/*.py` pipelines exist for every named output. Gap: no per-output lifecycle disposition (active/dormant/retired) exists yet. See §MED-02. |
| MED-03 | Every governed Bronze/Silver/Gold/metadata product exposes configurable freshness objectives, source status, quality, row-count, lineage, and last-success evidence. | `VulnerabilityIntelligenceService._coverage_for_family`/`metadata_source_status` and `api/runtime.py::_snapshot_failure_table` already implement this vocabulary for one family (Defender); it is not yet generalized. No per-dataset freshness-SLO config surface exists. See §MED-03. |
| MED-04 | High-value Silver operational datasets (security, incident, change, configuration, policy, predictive, remediation) are populated or explicitly dispositioned. | Defender security domain is populated end-to-end (uncommitted). Change/configuration/policy domain (`ChangeIntelligence.knowledge_projection()`) computes ontology-shaped rows but `change_pipeline.run()` does not forward them — a confirmed, precise wiring gap. See §MED-04. |
| MED-05 | Gold exposes curated, versioned consumption contracts and a Direct Lake-compatible semantic serving definition while unified inventory remains the sole resource-identity authority. | Zero existing code. Official REST contract for `POST /v1/workspaces/{id}/semanticModels` verified live this session, reusable against the existing `FabricClient` LRO poller. See §MED-05. |
| MED-06 | Graph publication enforces referential integrity and configurable ownership/tagging quality thresholds without inventing unsupported relationships. | `OntologyValidator` (dangling/self-link/duplicate/confidence-range checks) and `PendingRelationshipStore` (defer/retry) already enforce integrity. `DataQualityValidator` has no ownership/tag-coverage rule yet — confirmed gap. See §MED-06. |
| MED-07 | Cost, compliance, patch, change, incident, and lifecycle analytics retain governed historical facts under explicit retention contracts. | `FabricSyncService` already has a small allow-list of tables using non-overwrite (history-preserving) writes, just extended this session (uncommitted) to include `silver_defender_secure_scores`. Pattern is proven; allow-list needs extending to the other five domains. See §MED-07. |
| MED-08 | The Fabric Data Agent is grounded only in curated Gold products and evaluated reproducibly for groundedness, precision, freshness, citations, and safe degradation. | Extensively covered by `10-AI-SPEC.md` (already written, do not duplicate) and this repo's own `docs/fabric-data-agent-relationship-suggestions.md`, which documents a live, currently-unresolved MCP invocation failure. See §MED-08. |
| MED-09 | Generated ontology projections are governed by a publication manifest, lifecycle status, and consumer-facing abstraction that prevents direct dependency on unstable physical tables. | Confirmed greenfield: the only existing "manifest" concept (`manifest.json` in `runtime.py`/`dataset_mapper.py`) is a *snapshot* manifest for connection ingestion, unrelated to a Gold/ontology *lifecycle* manifest. See §MED-09. |
| MED-10 | Fabric data access, lineage, capacity health, and Delta maintenance controls are implemented with least privilege and visible through scope-enforced API/web surfaces. | Capacity ARM-state check verified live this session (`az resource show`). OneLake Data Access Roles REST API and Delta maintenance REST/pipeline/portal paths verified live from `learn.microsoft.com`. Zero existing code for any of the four sub-areas. See §MED-10. |

</phase_requirements>

## Summary

The repository is far along on Phase 10 already — but almost entirely through **uncommitted working-tree changes** on branch `fix-ontology-sync-publish`, not through git history. This is the single most important fact this research uncovered: `git show HEAD:src/fabric/dataset_mapper.py | grep Defender` and the same for `relationship_builder.py` both return **nothing** — the entire Defender/SecurityAlert/AttackPath/SecureScore entity and relationship vocabulary, the `PendingRelationshipStore` dangling-edge defer/retry mechanism, the `confidence.py` centralized scoring module, the `/api/v1/defender/*` router surface, the expanded `VulnerabilityFinding`/`VulnerabilityExposure` models, and the Bronze/Silver Defender schema registrations exist **only in the dirty working tree**. One narrower fix (registering PaaS resource types and `FlowObservation` as ontology endpoint types) **is** committed, at `61377d92`. The planner must treat almost all of MED-01 through MED-04's prerequisite plumbing as "already built, needs completion and verification," not "build from scratch" — and must not let any plan or executor `git stash`, `git checkout --`, or otherwise discard this working tree.

Running the full test suite this session (`pytest tests/ -q`, verified twice) found **one concrete regression already caused by this uncommitted work**: `tests/test_situations_tracer.py::test_normalizer_production_graph_contains_all_six_signal_families` fails because the normalizer's `source_status` rows now carry six granular `defender_*` families instead of the one `defender` family the test still asserts — a stale test fixture, not a product defect. A second test, `tests/test_api_vulnerability_router.py::test_defender_signal_endpoints_preserve_distinct_semantics`, passes in isolation but intermittently fails inside the full suite — a test-isolation gap (likely shared on-disk fixture state) that should be diagnosed before Phase 10 adds more Defender-adjacent tests. Four other failures (`test_api_remediation_approvals.py` ×2, `test_service.py`, `test_situations_tracer.py::test_production_ingestion_retains_failed_arg_status_without_watermark`) are pre-existing per `STATE.md` and are unrelated to this phase's domain — one visibly caused by a hard-coded "future" expiry date now being in the past relative to the sandbox's 2026-09-01 clock.

The requirement #7 vocabulary question — whether a DefenderAssessment/DefenderVulnerabilityFinding endpoint-type mismatch still exists — resolves cleanly: **it does not, as of the current working tree.** Both types are registered in `ONTOLOGY_ENTITY_TYPES`, every relationship referencing them uses matching literal strings, and `tests/test_relationship_vocabulary_consistency.py` (added by the committed `61377d92` fix, extended by nothing further) passes 4/4 when run live this session. The full fix-and-fetch story, and the one *documentation* correction still needed, is in §MED-01 and the dedicated callout below.

For the platform side, Microsoft Fabric's own documentation (fetched live this session, not from training memory) draws a sharp, previously-undocumented-in-this-repo line the planner needs: **the Fabric Data Agent item itself is GA**, but the newer **"Fabric IQ" workload — which is what actually backs this repo's `"type": "Ontology"` item — is explicitly in public preview with no SLA**, confirmed both by `learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq`'s preview banner and by this repo's own `docs/FABRIC_ONTOLOGY_DEPLOYMENT.md`, which already says so. This is the concrete platform reason behind CONTEXT.md's "deployment-blocked" disposition requirement — it is not a hypothetical hedge. Direct Lake, by contrast, is GA and Microsoft explicitly recommends it "for the gold analytics layer in the medallion lakehouse architecture" — MED-05 is targeting exactly the right technology, it is simply unbuilt. OneLake's row/column-level security and Data Access Roles apply to **Lakehouse items only** (not Warehouse, not SemanticModel directly) — a scoping fact that changes how MED-10's "OneLake security... where supported" decision should be implemented. Fabric's Delta table maintenance (`OPTIMIZE`/V-Order/`VACUUM`) has a **hard 7-day minimum retention floor enforced by the platform itself** ("Fabric portal and API maintenance requests fail by default for retention intervals under seven days") — this already satisfies CONTEXT.md's "retention-safe" requirement without any application-level enforcement needed. Fabric's workspace lineage view is **automatic and free** (no Purview integration required) — which cleanly splits MED-10's lineage requirement into three independent, separately-schedulable tiers.

**Primary recommendation:** Sequence Phase 10 as (1) finish and commit the existing uncommitted vocabulary/Defender/confidence/pending-relationship work with its one stale test fixed, (2) generalize the Defender-family freshness/status/quality pattern already proven in `VulnerabilityIntelligenceService` into a dataset-agnostic Fabric medallion health contract, (3) wire the already-computed-but-discarded `ChangeIntelligence.knowledge_projection()` output into `change_pipeline.run()` and give every code-declared-but-unproduced Silver entity type an explicit disposition, (4) build the greenfield MED-05/MED-09/MED-10 surfaces (Direct Lake semantic model, publication manifest, OneLake roles, capacity/lineage/maintenance) directly against the official REST contracts verified in this document, reusing `FabricClient`'s existing LRO poller rather than adding an SDK, and (5) extend the existing Gold-grounding Data Agent evaluation exactly as `10-AI-SPEC.md` already specifies. Do not introduce a new Fabric SDK, a new eval framework, or a competing resource-identity store at any point.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Ontology vocabulary/endpoint-type preflight validation | API/Backend (`src/ontology/ontology_publisher.py`) | — | Pure in-process validation before any Fabric REST call; no network tier involved. |
| Bounded retry + durable terminal state for Fabric publish | API/Backend (`src/fabric/fabric_client.py`, `src/onboarding/sync.py`) | Database/Storage (sync-state persistence) | Retry is a client-library concern; terminal state must survive process restarts, so it needs a storage tier. |
| Gold/Silver/Bronze pipeline execution | API/Backend (`src/fabric_pipelines/*.py`) | Database/Storage (OneLake Delta tables) | Pipelines are pure Python transforms; their output tier is OneLake. |
| Freshness/status/quality/lineage metadata per dataset | API/Backend (new `FabricMedallionHealthProvider`) | Database/Storage (`metadata_source_status`, manifest table) | Computed from Delta table state + sync metadata; API surfaces it, storage persists it. |
| Direct Lake semantic model definition + deployment | API/Backend (new `src/fabric/semantic_model_manager.py`) | CDN/Static — N/A | Deployed via Fabric REST Items API; no browser/SSR involvement. |
| Semantic model *query* (Direct Lake framing/refresh) | Database/Storage (Fabric VertiPaq engine, OneLake Delta) | — | Entirely inside the Fabric service; this repo never queries it directly for Phase 10's scope (agents ground on curated Gold, not the semantic model). |
| OneLake data access roles / RLS-CLS definition | API/Backend (new, item-scoped REST calls) | Database/Storage (enforced at OneLake read time) | Roles are declared via REST against the Lakehouse item; enforcement happens inside OneLake for every consuming engine. |
| Fabric capacity paused/throttled detection | API/Backend (new, ARM REST read) | — | A simple periodic ARM GET; no UI/browser logic needed beyond displaying the result. |
| Delta table maintenance (OPTIMIZE/VACUUM) | API/Backend (scheduled job, not request-triggered) | Database/Storage (Delta log itself) | Must be a background/cron job per CONTEXT.md ("never run implicitly on an API request"); API only reports last-run status. |
| Fabric Data Agent grounding query | API/Backend (`src/fabric/gold_grounding_client.py`, per AI-SPEC) | — | MCP `tools/call` is a server-to-server call; the browser never talks to Fabric directly. |
| Fabric medallion health tab | Browser/Client (`web/src/app/connections/page.tsx`) | Frontend Server (Next.js SSR shell only) | Per UI-SPEC: a new tab inside the existing Connections page, client-rendered against the new API. |
| Data lineage visualization | Fabric-native (out of this repo's tiers entirely) + Browser (deep link only) | — | Fabric's own lineage view requires no code; this repo only needs to link to it. |

## Requirement-by-Requirement Findings

This section is the core audit requested by research requirement #1: for each MED requirement, what already exists (reuse), what's missing (build), and what needs verification.

### MED-01 — Publication preflight, retry, durable terminal state, telemetry

**What exists (verified this session):**
- `src/ontology/ontology_publisher.py::OntologyPublisher.build_definition()` (lines 75-118) raises `ValueError("Ontology relationship endpoint type is not defined: ...")` with the exact `(source_type, predicate, target_type)` tuple and missing-types list. Critically, `publish()` (line 41) calls `build_definition()` at line 49 **before** `self.manager.resolve(...)` at line 50 — the validation is a genuine preflight; no Fabric REST call happens before it. This already satisfies CONTEXT.md's "runtime preflight before any externally visible publication boundary" decision — the planner does not need to relocate this check, only add a regression test asserting the call-ordering (e.g., a test that a mocked `manager.resolve` is never called when `build_definition` raises).
- `src/fabric/fabric_client.py` (grepped, not fully read) already implements a generic LRO poller: `if response.status_code == 202 and wait_for_completion: location = response.headers.get("Location"); ...; return self._wait_for_operation(location, response.headers.get("Retry-After"))`, plus a `_retry_delay()` helper reading `Retry-After` with exponential fallback (`min(2.0**attempt, 30.0)`, confirmed pattern reused/extended in `src/onboarding/azure_clients.py`'s Cost Management vendor-header variant, read this session). **Don't hand-roll a new retry/poller for MED-05's semantic-model LRO or MED-10's capacity/maintenance calls — reuse this one.**
- Commit `61377d92` ("fix: register ontology relationship endpoint types", already in git history, not part of the uncommitted set) added `tests/test_relationship_vocabulary_consistency.py` — 4 tests, run live this session, **4/4 passing**: subset check (onboarding predicates ⊆ Fabric predicates), endpoint-type registration check, PaaS-type registration check, independent-importability check.
- `src/onboarding/sync.py::ConnectionSyncCoordinator` (diff read this session) now wraps the publish call in `try/except Exception` and calls `logger.exception(...)` plus appends a `publish_message` string to the sync result on failure — this is a **process-log-level** failure surface, not yet a durably queryable one.

**What's missing / needs building:**
- A durably queryable terminal-failure record for ontology publication specifically (distinct from the general connection `SyncState`/`ConnectionHealth` in `src/onboarding/health.py`, which is per-connection, not per-publication-attempt). CONTEXT.md requires this to be "operator-visible" — the Fabric medallion health API (MED-03/MED-10's new surface) is the natural place to expose it.
- Telemetry emission for publish preflight rejections and retries. `src/fabric/telemetry.py` (`FabricMetrics`, 2686 bytes, not yet fully read but referenced throughout the codebase and in `10-AI-SPEC.md §7`) is the existing OpenTelemetry meter to extend — do not create a second metrics module.
- Fabric's own Unified Quota throttling model (verified live from `learn.microsoft.com/en-us/rest/api/fabric/articles/throttling` this session) enforces **200 calls/min per identity per one of three quota categories** (Platform APIs, Job Scheduler APIs, Long-Running Operations APIs) — independent buckets, `429` + `Retry-After` is the standard signal. `fabric_client.py`'s existing `Retry-After`-driven backoff is already the correct shape for this; no redesign needed, just confirm it's applied to every new REST call this phase adds (semantic model creation, data access roles, capacity check, maintenance trigger).

**On requirement #7 (the DefenderAssessment/DefenderVulnerabilityFinding vocabulary question) — resolved:**
The mismatch **does not currently exist** in the working tree. Evidence, all gathered this session:
1. `src/fabric/dataset_mapper.py` lines 135-136 (`view`-read this session): `"DefenderAssessment",` / `"DefenderVulnerabilityFinding",` are both literal entries in the `ONTOLOGY_ENTITY_TYPES` tuple.
2. `src/fabric/dataset_mapper.py` lines 242-245 (`view`-read this session): `*(("DefenderAssessment", "impacts", asset) for asset in (...)), *(("DefenderVulnerabilityFinding", "impacts", asset) for asset in (...)), *((asset, "hasVulnerability", "DefenderVulnerabilityFinding") for asset in (...)), ("DefenderVulnerabilityFinding", "derivedFrom", "DefenderAssessment"),` — every relationship referencing these two types uses the identical literal strings registered in (1).
3. `tests/test_relationship_vocabulary_consistency.py::test_fabric_relationship_endpoint_types_are_registered_entities` (`pytest tests/test_relationship_vocabulary_consistency.py -v`, run live this session) **passed 4/4**.
4. `python3 -c "from fabric.dataset_mapper import ONTOLOGY_ENTITY_TYPES; print(len(set(ONTOLOGY_ENTITY_TYPES)))"` run live this session: **103 unique entity types, zero duplicates**, `197` relationship-type tuples.

**What still needs a fix — a documentation correction, not a code fix:** the repo has **two different root-level ontology schema documents** with overlapping but non-identical content and inconsistent naming: `ONTOLOGY_SCHEMA.md` (mtime 23:24, uses stale "HOG" terminology not used anywhere else in this repo — likely a leftover from an earlier project-naming iteration) and `ontology-schema.md` (mtime 23:46, 22 minutes newer, uses this repo's actual "AIOps"/"Operational Context Graph" terminology and correctly describes Fabric IQ Ontology as preview). Neither is referenced from the other, and it is not obvious to a reader which is canonical. **Recommendation: the planner should have an executor diff the two, fold any content unique to `ONTOLOGY_SCHEMA.md` into `ontology-schema.md` (or vice versa, whichever is judged more current against the actual `ONTOLOGY_ENTITY_TYPES`/`ONTOLOGY_RELATIONSHIP_TYPES` tuples), and delete or redirect the stale one.** This is a low-risk, low-effort cleanup task, not a blocking dependency for any other MED work — do not let it consume a whole plan.
Separately, confirm no Fabric-side (already-published) ontology item is still running an older definition that predates the PaaS/`FlowObservation`/Defender additions — `docs/FABRIC_ONTOLOGY_DEPLOYMENT.md`'s own "Deploy and verify" section (`uv run aiops-inventory fabric "Sync operational ontology" ...`) is the existing re-publish command; this is a **deployment-gap check**, not a vocabulary bug, and should be one of the "integrity gates first" rollout steps CONTEXT.md already calls for.

### MED-02 — Gold topology/assessment/operational-context outputs: live, verified, or retired

**What exists (verified this session):**
- Every named output already has a pipeline module: `src/fabric_pipelines/topology_pipeline.py` (16067 bytes), `impact_context_builder.py`, `vulnerability_pipeline.py`, `governance_pipeline.py`, `lifecycle_pipeline.py`, `patch_pipeline.py`, `change_pipeline.py`, `predeploy_pipeline.py` — confirmed present via directory listing; `change_pipeline.py` fully read this session (see MED-04).
- `scripts/validate-lakehouse-tables.py` (fully read this session) is the **existing** live-vs-code-declared reconciliation tool: it lists actual Delta tables under a lakehouse via the OneLake file-system API (`writer.service.get_file_system_client(...)`, paginating `/Tables`), compares against `set(fabric.schema_registry.SCHEMAS)` plus `INVENTORY_FABRIC_SCHEMAS_BY_TABLE`, and reports `present_known`, `present_unknown` (legacy/orphan), and `missing` (expected-but-absent) sets. **This is almost certainly the tool (or a close relative of it) that produced CONTEXT.md's "320 readable tables... Bronze 9/8... Silver 18/14... Gold 288/140" baseline** — no artifact with those exact numbers exists in the repo, so treat the baseline as `[CITED: 10-CONTEXT.md]`, but the *mechanism* to regenerate it is `[VERIFIED]`. **Don't hand-roll a second table-reconciliation script — extend this one** (e.g., add `--json-out`-driven disposition classification per MED-09's manifest).
- `fabric.config.yaml`/`fabric.config.example.yaml` already have per-feature `enabled: true|false` boolean keys (grepped this session — several `enabled:` lines at different config depths); the planner should inventory exactly which pipeline/feature each flag gates before assuming "restore individually" requires new flags — some staged-rollout capability may already exist.

**What's missing:**
- Per-output **lifecycle disposition** (active / dormant / retired-with-compatibility-evidence) — no such concept exists in code today (see MED-09; this is the same gap, viewed from the "which datasets get a disposition" angle rather than the "where is it stored" angle).
- A **staged rollout orchestrator**: `src/onboarding/schedule.py` (fully read this session) installs exactly one cron entry (`aiops cron create ... --script azure-resource-graph-sync.sh`, which runs `uv run aiops-inventory sync`) — a single monolithic sync command, not a per-pipeline scheduler with independent cadences. CONTEXT.md explicitly requires restoring "topology, operational-context, and assessment Gold outputs individually; do not enable all pipelines in one uncontrolled capacity spike" — the current scheduling model cannot express that without either (a) per-pipeline config flags gating what the monolithic sync actually runs (extend the existing `fabric.config.yaml enabled:` pattern) or (b) splitting the single cron script into staged invocations. Recommend (a): it is a smaller, additive change and matches the existing config-driven feature-gating idiom already in the file.
- **Note on the external `aiops` CLI dependency:** `schedule.py`'s `install_schedule()` shells out to an `aiops` binary (`subprocess.run(["aiops", "cron", "create", ...])`) — this is a **different, unrelated personal-agent CLI tool** installed on the operator's machine (confirmed this session: the repo-root `existing-capabilities.md` file is an inventory of that *other* tool's capabilities, checked out at `/Users/jasonmba/.aiops/aiops-agent`, and is **not relevant to this Azure AI Operations Platform's own architecture** — do not cite it as evidence for anything in this phase). This external dependency for scheduling is an existing environment coupling, not something to fix in Phase 10, but the planner should not assume `aiops cron` is available in every deployment target (e.g., CI, a fresh clone) — treat it as a `Missing dependency with fallback` in Environment Availability if a plan needs to invoke this path.

### MED-03 — Configurable freshness, source status, quality, row-count, lineage, last-success evidence

**What exists (verified this session) — strong, reusable prior art for exactly one family (Defender), not yet generalized:**
- `src/intelligence/vulnerability/service.py::VulnerabilityIntelligenceService.defender_overview()` and `._coverage_for_family()` (diff read this session, ~130 new lines): computes, per source family (`defender_alerts`, `defender_attack_paths`, `defender_secure_scores`, `defender_assessments`), a "latest-per-requested-scope" reduction over `self.defender_source_status` rows, then folds multiple rows into a single `{availability: available|unavailable|unknown, freshness: fresh|stale|unknown, quality: complete|degraded|unknown, error: str, observed_at: str}` shape. This is **exactly** the vocabulary MED-03 requires, already fully coded and unit-testable — it is scoped to the Defender family only, but the shape and merge logic should be lifted, not reinvented.
- `src/api/runtime.py::_snapshot_failure_table()` (diff read this session): when a connection's snapshot manifest is missing or unreadable, synthesizes a full set of `metadata_source_status` rows tagged `status: "failed"`, `availability: "unavailable"`, `quality: "degraded"`, `freshness: "unknown"`, with a human-readable `error` — i.e., a real "materialize failure as first-class source-status data" pattern already exists, isolated per connection, not blocking the rest of the API response. This is the concrete implementation CONTEXT.md's "API status distinguishes healthy-empty, stale, degraded, failed, retired, and unavailable; zero rows alone never imply success or failure" decision is asking for — reuse this pattern for every dataset family, not just Defender.
- `src/onboarding/health.py::HealthEvaluator` (fully read this session) implements the analogous vocabulary at the **connection** level (`healthy|unhealthy|stale|disabled|unknown`) — a sibling pattern the new dataset-level contract should stay visually/semantically consistent with, per CONTEXT.md's "Preserve existing API response-envelope... patterns" decision, without conflating connection health and dataset health into one type.
- `src/fabric/data_quality.py::DataQualityValidator` (fully read this session, 155 lines): validates required fields, exact PyArrow-schema conformance (via `schema_registry.schema_for()`), duplicate `resource_id`s, and ARM-subscription-ID/`resource_id` consistency — produces a `QualityReport` with `rule_counts`/`failures`. This is the "quality" half of MED-03; row-count is a trivial `len(rows)` on top of it.

**What's missing:**
- **No per-dataset freshness-SLO configuration surface exists anywhere** — searched `fabric.config.yaml`, `fabric.config.example.yaml`, `src/fabric/*.py`, `src/onboarding/health.py` for `freshness`/`slo`/`stale_after` this session; every hit was either a *computed* freshness watermark (`sync_service.py::_global_freshness_watermark`) or a schema field name, never a *configured threshold*. CONTEXT.md's "freshness objectives are configurable per dataset and default to a bounded multiple of the producing pipeline cadence" needs new config (likely a `fabric.config.yaml` section keyed by table/pipeline name) plus a small evaluator (`observed_at` age vs. `cadence × multiplier` → `fresh|stale`).
- **A dataset-agnostic health contract.** The Defender-specific `_coverage_for_family` needs to become a provider consumed by every Gold/Silver family, not copy-pasted per domain. Recommended shape: a new `src/fabric/medallion_health.py` module exposing `dataset_status(table_name) -> {availability, freshness, quality, row_count, last_success_at, lineage_ref}`, reading from a generalized `metadata_source_status` table (schema already exists in `schema_registry.py` per the grep evidence above — extend, don't replace).

### MED-04 — High-value Silver operational datasets: populated or dispositioned

**What exists (verified this session) — the security domain is essentially complete, uncommitted:**
- ARG source: `src/onboarding/query_catalog.py` (diff read this session) replaced one generic `vulnerability` KQL query with **six typed queries** against `SecurityResources`, filtered by exact ARM type (`microsoft.security/assessments`, `/subassessments`, `/locations/alerts`, `/attackpaths`, `/securescores`, `/securescores/securescorecontrols`). No new Azure API client is needed — this reuses the existing generic ARG/KQL connector pattern.
- Normalize: `src/onboarding/defender_normalize.py` (new file, fully read this session, 518 lines) — `normalize_assessment`, `normalize_vulnerability_subassessments` (one row per CVE), `normalize_security_alert`, `normalize_attack_path` (graph + nodes + connections, explicitly leaves unresolved identities/IPs/K8s objects unresolved rather than guessing — matches `docs/ontology-model.md`'s "Identities, IP addresses, Kubernetes objects... remain explicitly unresolved when they cannot be mapped to an ARM resource" language, which was itself added in the uncommitted `docs/ontology-model.md` diff), `normalize_secure_score`, `normalize_secure_score_control`.
- Entity/relationship registration: `dataset_mapper.py`/`relationship_builder.py` as covered in MED-01.
- Bronze/Silver schemas: `src/fabric/schema_registry.py` (diff read this session) adds 8 Bronze and 6 Silver Defender table schemas (`bronze_defender_assessments`, `silver_defender_findings` with a rich CVE/software/patchability column set, etc.).
- Snapshot read path: `src/fabric/sync_service.py::defender_intelligence_snapshot()` (diff read this session) reads all 6 Silver Defender tables plus filters `metadata/source_status` rows whose `source_family` starts with `defender_`.
- API surface: `src/api/routers/vulnerability.py` (diff read this session) adds `GET /api/v1/defender/overview`, `/defender/alerts`, `/defender/attack-paths`, `/defender/secure-score`, `/defender/secure-score-controls`, plus `GET /api/v1/vulnerabilities/defender-posture` and a renamed `server-exposures` → `asset-exposures` (subscription-wide, not server-only). All confirmed live-testable via `tests/test_api_vulnerability_router.py::test_defender_signal_endpoints_preserve_distinct_semantics` (passes in isolation).
- Web types: `web/src/lib/types.ts` diff (read this session) already defines `DefenderOverview`, matching exactly what `10-UI-SPEC.md` describes reusing.

**What's missing — a precise, confirmed wiring gap (not a missing-business-logic gap) for the change/configuration/policy domain:**
- `src/intelligence/change/change_intelligence.py::ChangeIntelligence.knowledge_projection()` (read this session, method starts line 222) **already computes** `ConfigurationDrift`, `PolicyDeviation`, `SecurityDeviation`, `AuthorizedChange`/`UnapprovedChange` as ontology-shaped `entities`/`relationships` lists — bounded by `max_output_items`, with dangling relationships filtered out (`relationships=[row for row in relationships if row["subject_id"] in known and row["object_id"] in known]`), wrapped `read_only: True`.
- **But `src/fabric_pipelines/change_pipeline.py::run()` (fully read this session, 63 lines) never calls `knowledge_projection()`.** It calls `ChangeIntelligence.from_snapshot(...).analyze()` and returns a `ChangePipelineResult` dataclass with exactly four fields: `table_name` (hardcoded `"assessment_change_findings"`), `findings`, `compliance`, `summary` — no `entities`/`relationships` fields exist on the dataclass at all. The computed ontology graph is silently discarded at this boundary.
- These five entity type names **are** already registered in `ONTOLOGY_ENTITY_TYPES` (`dataset_mapper.py` lines 93-97, read this session) and already appear in `ontology_sync.py`'s `compliance_context` view (diff read this session: `view({"PatchAssessment", "AdvisorRecommendation", "PolicyDeviation", "SecurityDeviation", "ConfigurationDrift", "UnapprovedChange", "AuthorizedChange"})`) — so the ontology *schema* is ready and waiting for rows that never arrive through this path.
- **Recommended fix, concretely scoped:** extend `ChangePipelineResult` with `entities: list[dict]` / `relationships: list[dict]` fields, populate them from `knowledge_projection()`'s output in `run()`, and fold them into whatever aggregation step currently merges `topology_pipeline`/`governance_pipeline` output into the ontology sync's `current_entity_rows`/`current_relationship_rows` (that merge point was not traced this session — the executor must locate it, likely in `ontology_pipeline.py` or wherever `OntologyGraphSynchronizer.synchronize()` is invoked from the sync orchestrator).
- **Predictive/remediation domains** (`Prediction`, `Forecast`, `Trend`, `OperationalDebt`, `RiskDriver`, `RemediationPlan`, etc.) were not traced to the same depth this session — the planner should run the identical investigation (`grep -rn '"Prediction"\|"RemediationPlan"' src/fabric_pipelines src/intelligence`) before assuming either "populated" or "gap"; do not guess.

### MED-05 — Direct Lake-compatible semantic serving, curated Gold consumption contracts

**What exists:** Nothing in code (`grep -rl "Direct Lake\|DirectLake"` across `src/`, `docs/`, `infra/` returned zero source-code hits this session — only planning docs mention it). This is a genuine greenfield build.

**Official platform facts (all fetched live from `learn.microsoft.com` this session):**
- **Direct Lake is GA**, is explicitly positioned by Microsoft for "the gold analytics layer in the medallion lakehouse architecture" (`fabric/fundamentals/direct-lake-overview`), and its refresh ("framing") is metadata-only and fast — it is not a data copy like Import mode.
- **Performance depends on well-tuned Delta tables** — same doc links "Cross-workload table maintenance and optimization" for V-Order/row-group guidance, tying MED-05 directly to MED-10's Delta maintenance work; they should not be planned as fully independent.
- **The exact, current REST contract to create a semantic model** (`learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/create-semantic-model`, fetched live):
  ```
  POST https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/semanticModels
  {
    "displayName": "...",
    "definition": {
      "parts": [
        {"path": "model.bim", "payload": "<base64 TMSL/TMDL>", "payloadType": "InlineBase64"},
        {"path": "definition.pbism", "payload": "<base64>", "payloadType": "InlineBase64"},
        {"path": ".platform", "payload": "<base64>", "payloadType": "InlineBase64"}
      ]
    }
  }
  ```
  Returns `201` (created) or `202` (LRO — `Location`/`x-ms-operation-id`/`Retry-After` headers, **identical shape to what `fabric_client.py` already polls for** — reuse it directly, do not write a second poller). Requires **Contributor workspace role** and `SemanticModel.ReadWrite.All` or `Item.ReadWrite.All` delegated scope. Documented error codes: `InvalidItemType`, `ItemDisplayNameAlreadyInUse`, `CorruptedPayload`, `WorkspaceItemsLimitExceeded` — map these directly to CONTEXT.md's "explicit deployment-blocked state; do not silently report success" requirement.
- **RLS on Direct Lake is supported**, with one documented nuance: "if a DAX query falls back to DirectQuery mode due to unsupported features, RLS filters still apply but performance characteristics may change. Monitor query fallback behavior in the Fabric capacity metrics app." (`power-bi/enterprise/service-admin-rls`, fetched live, verified genuine by re-fetching raw HTML with surrounding context — not a parsing artifact).

**Recommendation:** Build a new `src/fabric/semantic_model_manager.py` mirroring `data_agent_manager.py`'s existing resolve/create/update-idempotent pattern (already proven for the Ontology item type), targeting the Semantic Model item type instead. Author the TMDL/`model.bim` definition in code (not hand-authored in the portal) so it is versioned and diffable, matching `ontology_publisher.py`'s existing "generate definition, compare, update-or-create" idiom. Gate deployment behind the same preflight-before-network-call discipline as MED-01.

### MED-06 — Referential integrity, configurable ownership/tag quality thresholds

**What exists (verified this session) — the integrity half is mature and fail-closed:**
- `src/ontology/ontology_validator.py::OntologyValidator` (fully read this session, 236 lines): a hard, structural gate checking, per entity: all 14 `ENTITY_REQUIRED` fields non-empty, `lifecycle_status ∈ {active, retired}`, `retired_at` consistency with lifecycle status, and that `payload_json`/`lineage_json`/`semantic_metadata_json` each parse as a JSON object. Per relationship: all 17 `RELATIONSHIP_REQUIRED` fields, the same lifecycle/`retired_at` consistency, **dangling detection** (`subject`/`object` not in the known-entity-id set), **self-relationship detection**, **duplicate detection**, `confidence ∈ [0.0, 1.0]` finite-float validation, and — only for *active* relationships — that `subject_type`/`object_type` still agree with the referenced entity's *current* `entity_type` (explicitly *not* enforced for retired relationships, since a retired edge's captured type may predate a later reclassification — this is a deliberate, documented design choice, not an oversight). `validate()` returns `passed=False` if *any* of these six failure categories is non-zero — this already is "referential integrity as a publication blocker."
- `src/ontology/pending_relationships.py::PendingRelationshipStore` (fully read this session, 104 lines): rather than let a dangling edge simply fail validation and get dropped, `OntologyGraphSynchronizer.synchronize()` (diff read this session) now defers edges whose subject/object isn't in *this* sync's snapshot yet into this store, retries them on the *next* sync once the missing entity appears, and caps total pending edges at `DEFAULT_MAX_PENDING = 10_000` with oldest-first eviction. This directly implements "without inventing unsupported relationships" — a not-yet-resolvable edge is held, never fabricated or silently discarded.
- `src/ontology/confidence.py::compute_confidence()` (fully read this session, 86 lines): centralizes what used to be hardcoded magic-number confidence values (0.9/0.95/0.98/0.99/1.0) scattered across `graph_normalize.py`/`relationship_builder.py`, keyed by originating source family, with a small (`+0.02`, capped at 1.0) corroboration bump when more than one independent signal agrees. This is the confidence half of "invented unsupported relationships" prevention — a relationship's trust level is now traceable to *why*, not a guess.

**What's missing:**
- **`src/fabric/data_quality.py::DataQualityValidator` has no ownership/tag-coverage rule** — confirmed by reading the full 155-line file this session: its rule set is `required_fields`, `schema_validation`, `duplicates`, `subscription_consistency` (and, for relationships, `orphan_relationships`). CONTEXT.md's "84 missing ownership and 52 missing tags" baseline metric and "configurable quality thresholds that can warn or block by environment" decision require a **new rule** — recommend adding `ownership_coverage`/`tag_coverage` counters to `QualityReport.rule_counts`, driven by a new config key (e.g., `fabric.config.yaml`'s existing per-feature block pattern) specifying warn-vs-block thresholds per environment (dev/staging/prod).

### MED-07 — Historical retention for cost/compliance/patch/change/incident/lifecycle

**What exists (verified this session):** `src/fabric/sync_service.py::FabricSyncService` (diff read this session) already has a small allow-list controlling Delta write mode:
```python
# existing set, before this session's uncommitted addition:
{"bronze_resource_changes", "silver_patch_history", "silver_lifecycle_history"}
# else DeltaWriteMode.OVERWRITE
```
This session's uncommitted diff **adds `"silver_defender_secure_scores"`** to this same set — meaning secure-score snapshots are now correctly treated as append/merge history rather than being overwritten on every sync, which is exactly the MED-07 pattern applied to one more table. The mechanism is proven and trivially extensible; it is a one-line-per-table allow-list, not an architectural gap.

**What's missing:** The allow-list needs the remaining domains added — cost (`CostActual` history), compliance/governance, patch (beyond the existing `silver_patch_history`), change (`assessment_change_findings` and any change-event history table), and incident. The planner should enumerate every Gold/Silver table that represents a *trend* (as opposed to *current state*) and confirm each is in this set or an equivalent one, rather than assuming `silver_patch_history`/`silver_lifecycle_history` are the only two that matter.

### MED-08 — Data Agent grounding and evaluation

**This requirement is already extensively researched in `10-AI-SPEC.md`** (797 lines, read in full this session) — do not duplicate that work here. Key facts this research independently cross-verified:
- `docs/fabric-data-agent-relationship-suggestions.md` (fully read this session, 200 lines) is this repo's own live-verified account of a **currently unresolved** Fabric Data Agent MCP invocation failure: `tools/call` on the published `relationship_suggestion_agent` returns `{"result": {"content": [{"type": "text", "text": "The Data Agent run failed before producing a result."}], "isError": true}, ...}` with zero further diagnostic, even after fixing an earlier real bug (empty `datasource.elements` selection). This is documented as possibly "a first-run indexing/warm-up delay... a workspace capacity/SKU limitation... or a preview-feature platform issue" — genuinely undiagnosable from the REST/MCP surface alone. **AI-SPEC's Critical Failure Mode #5 and its Safe Degradation Contract are designed directly around this exact, real, currently-live failure — not a hypothetical.**
- `fabric-data-agent-sdk`'s package namespace (`fabric.dataagent`) permanently collides with this repo's own `src/fabric` regular package — confirmed in the same doc — which is why `DataAgentManager` talks to the raw REST API directly. **This is a strong "Don't Hand-Roll" signal for MED-05 and MED-10 too: continue the raw-REST/`httpx` pattern for the semantic model, data access roles, and capacity/maintenance work rather than reaching for any official Fabric Python SDK.**
- `scripts/evaluate_agents.py` (exists, referenced extensively by AI-SPEC, not independently re-read line-by-line this session since AI-SPEC already covers it thoroughly) is the existing deterministic, no-LLM-judge evaluation harness to extend with the 13 new Gold-grounding cases AI-SPEC's §5b specifies.
- **Independently verified this session, extending AI-SPEC's own framework-decision research:** `learn.microsoft.com/en-us/fabric/data-science/concept-data-agent` confirms the Fabric data agent is **"a generally available feature,"** and separately documents that it "respects Microsoft Purview governance controls applied to the underlying Fabric data sources, including Data Loss Prevention (DLP) and access restriction policies" and "strictly enforces read-only access" — this is a second, independent tie between MED-08 and MED-10's Purview/lineage decision: Purview DLP policies (if the tenant has them) will transparently constrain what the Gold-grounding agent can retrieve, with zero code required in this repo — a governance layer "for free" once Purview is configured tenant-side.
- **New fact not previously in AI-SPEC:** the Foundry-IQ ontology-agent path (`learn.microsoft.com/en-us/fabric/iq/ontology/how-to-create-agent-foundry-iq`, fetched live) requires granting the Foundry project's managed identity the **"Search Index Data Contributor"** role on an Azure AI Search resource — "If you don't assign this role, the agent can't access the ontology and you see a 403 error." If Phase 10 (or a future phase) adopts the Foundry-IQ-knowledge-base path (as opposed to the direct-MCP interim path AI-SPEC recommends), this RBAC grant is a concrete prerequisite the planner should not discover only at execution time.

### MED-09 — Publication manifest, lifecycle status, consumer-facing abstraction

**Confirmed greenfield.** `grep -rln "manifest" src/fabric/ src/ontology/ src/fabric_pipelines/ src/api/routers/` (run this session) returned only `src/fabric/dataset_mapper.py` and `src/fabric/sync_service.py` — both of which use "manifest" to mean the **per-connection ingestion snapshot manifest** (`manifest.json`, read by `api/runtime.py::_load_snapshot_tables()`, containing `runId`/`startedAt` for one connector's raw snapshot) — an entirely different concept from a **Gold/ontology dataset lifecycle manifest** (active/dormant/retired dispositions, versioned compatibility evidence). Do not conflate the two in planning; they should likely be two distinctly-named concepts in code (e.g., keep "snapshot manifest" as-is, introduce "publication manifest" or "dataset registry" as the new MED-09 concept) to avoid the same ambiguity this research had to resolve by reading source.

**Platform constraint that makes this requirement non-optional, not just tidy:** the underlying Fabric item type this repo publishes to (`"type": "Ontology"` in `.platform`, confirmed via `ontology_publisher.py` line 121, cross-verified against the *official* Ontology item definition contract fetched live from `learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition` — parts list matches exactly: `.platform`, `definition.json`, `EntityTypes/{ID}/definition.json`, `EntityTypes/{ID}/DataBindings/`, `RelationshipTypes/{ID}/definition.json`, `RelationshipTypes/{ID}/Contextualizations/`) belongs to **"Fabric IQ," which `learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq` explicitly marks preview: "This preview is provided without a service-level agreement, and we don't recommend it for production workloads."** `docs/FABRIC_ONTOLOGY_DEPLOYMENT.md` (this repo's own doc) already says the same thing independently ("The Ontology item/API is currently a Microsoft Fabric Preview capability"). A manifest that can mark a physical ontology projection `dormant` (not deleted) and expose a `deployment-blocked` state for anything that depends on this preview surface is therefore addressing a **real, currently-true platform risk**, not a defensive abstraction for its own sake.

**Also newly discovered this session, worth flagging to the planner as a possible enhancement, not a required gap:** the official Ontology definition contract supports three optional definition-part directories this repo's `build_definition()` does not currently populate: `EntityTypes/{ID}/Documents`, `EntityTypes/{ID}/Overviews`, `EntityTypes/{ID}/ResourceLinks`. "Overviews" in particular could improve Data Agent grounding quality (MED-08) by attaching a natural-language description per entity type — worth a footnote in the plan, not a blocking requirement.

### MED-10 — Data access, lineage, capacity health, Delta maintenance

All four sub-areas are **confirmed greenfield in code** (zero hits for "Direct Lake", "OPTIMIZE"/"VACUUM", "Purview" outside of aspirational one-line mentions in `ARCHITECTURE.md`/`FABRIC_INTEGRATION.md`, or "RLS"/"data access role" anywhere in `src/`). Platform facts, all fetched live this session:

**OneLake data access roles (RLS/CLS-capable, item-scoped):**
- Model: role-based, **deny-by-default**, **Grant-only** (no Deny roles), two permissions (`Read`, `ReadWrite`). `ReadWrite` roles **cannot** carry RLS/CLS constraints — only `Read` roles can (`learn.microsoft.com/en-us/fabric/onelake/security/data-access-control-model`).
- **Supported item types: Lakehouse (Read, ReadWrite), Azure Databricks mirrored catalog (Read), Mirrored databases (Read), Mirrored catalogs (Read).** Warehouse and SemanticModel are **not** in this list — meaning OneLake-level RLS/CLS applies at the Lakehouse (this repo's actual storage tier), not at the Direct Lake semantic model layer. RLS *on the semantic model itself* is the separate, traditional Power BI-role mechanism (see MED-05).
- REST API, verified live: `GET https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/items/{itemId}/dataAccessRoles` (paginated via `continuationToken`), returning `{name, eTag, decisionRules: [{effect: "Permit", permission: [{attributeName: "Path", attributeValueIncludedIn: [...]}, {attributeName: "Action", attributeValueIncludedIn: ["Read"]}]}], members: {fabricItemMembers: [...]}}`. Requires `OneLake.Read.All`/`OneLake.ReadWrite.All` delegated scope.

**Lineage — three independent tiers, per CONTEXT.md's own sequencing ("internal provenance and Fabric item lineage first; integrate external Purview surfaces only through supported APIs and explicit configuration"):**
1. **This repo's own internal provenance** — already implemented: every ontology entity/relationship carries `lineage_json` (per `ontology_validator.py`'s `ENTITY_REQUIRED`/`RELATIONSHIP_REQUIRED` tuples, and `docs/ontology-model.md`: "Every inferred entity stores `lineage_json`, semantic discovery metadata, source IDs, lifecycle state, and version."). This is done; MED-10 just needs to *surface* it through the new health API, not build it.
2. **Fabric's own native workspace lineage view** — automatic, free, zero-code, per-workspace (`learn.microsoft.com/en-us/fabric/governance/lineage`, fetched live): shows all items in a workspace and their connections, one level of upstream cross-workspace sources, keyboard/screen-reader accessible (DFS tab order). Any workspace role can view it; Viewers just don't see data-source detail. **The cheapest MED-10 lineage win is a deep link from this repo's web UI into this existing Fabric view**, not a rebuilt graph.
3. **External Microsoft Purview** — genuinely deferred per CONTEXT.md; only relevant if/when the tenant configures Purview DLP/access-restriction policies, which (per MED-08's finding above) already transparently constrain the Data Agent with zero code changes.

**Capacity health — verified live against this deployment's actual resource, not just documentation:**
- `az resource show --ids ".../providers/Microsoft.Fabric/capacities/aiopsdevcapg6ludc" --api-version 2023-11-01` (run live this session, read-only) returns `properties.state: "Active"`, `properties.provisioningState: "Succeeded"`, `sku.name: "F4"`. **This is the simplest, most directly implementable capacity-health signal** — a periodic ARM GET against `Microsoft.Fabric/capacities/{name}`, reusing this repo's existing `azure-identity`-based credential (no new package). This matches STATE.md's own account of manually resuming a paused capacity via `az resource invoke-action ... resume` — confirming `state` can genuinely be `Paused`, not just `Active`.
- The richer **Microsoft Fabric Capacity Metrics App** (`learn.microsoft.com/en-us/fabric/enterprise/metrics-app`, fetched live) is a separate, installable Power BI app (Health/Compute/Storage/Timepoint pages, throttling/query-rejection visibility, "AI Functions" tracked as its own operation category) — richer, but requires a capacity admin to install it and querying its own semantic model (XMLA/DAX), a materially heavier integration than the ARM state check. **Recommend implementing the ARM-state check first** (cheap, sufficient for "paused/throttled detection" per CONTEXT.md's literal wording) and treating the Metrics App as a stretch/future enhancement, not a Phase 10 blocker.

**Delta table maintenance (`OPTIMIZE`/V-Order/`VACUUM`) — verified live, with a platform-enforced safety net:**
- `learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-table-maintenance` (fetched live): three independent trigger surfaces — ad hoc portal action, a **"Lakehouse Maintenance activity (Preview)" in Fabric Data Factory pipelines** (can run `OPTIMIZE` with optional V-Order and `VACUUM` on a schedule, chainable with data-load steps and a follow-up "Refresh SQL Endpoint" activity), and a REST API (linked as "Manage the lakehouse with Fabric REST API" — the exact endpoint slug was not resolved live this session; a documented `404` was hit on one guessed URL, so treat the specific REST path as `[ASSUMED — needs confirmation before implementation]`, though its *existence* is `[CITED]` from the maintenance doc's own cross-reference).
- **`VACUUM`'s default retention is 7 days, and "Fabric portal and API maintenance requests fail by default for retention intervals under seven days"** unless `spark.databricks.delta.retentionDurationCheck.enabled` is explicitly set `false` in a Spark environment — this is a **platform-enforced floor that already satisfies CONTEXT.md's "retention-safe" requirement** without any application-level enforcement; the planner should not build a redundant guard, just avoid disabling this platform check.
- V-Order has "about a 15% impact on average write times" and "up to 50% more compression" — a real cost/benefit tradeoff to surface in any maintenance-scheduling UI, not a free win.
- Successful/failed maintenance runs appear in Fabric's **Monitoring hub** (filterable by activity name containing `TableMaintenance`, or by Pipeline run + Lakehouse Maintenance activity name for pipeline-triggered runs) — this is the platform-native place to source "last maintenance run" status for the new health API, rather than this repo tracking it independently.
- **Recommendation, consistent with CONTEXT.md's "scheduled, bounded... never run implicitly on an API request":** trigger maintenance via a Data Factory pipeline (or an equivalent scheduled job outside the request path) and have the new Fabric medallion health API only *read* the Monitoring-hub-sourced last-run status, never trigger maintenance itself from a GET/POST handler.

## Uncommitted Work Inventory

Per the phase context ("heavily modified dirty branch... existing uncommitted work must be preserved"), this table is the ground truth of what is dirty, checked via `git status --short` and `git diff HEAD --stat` this session. **No plan in this phase should `git stash`, `git checkout --`, `git reset --hard`, or otherwise discard any row below.**

| File | State | What it contains (this session's reading) |
|------|-------|---------------------------------------------|
| `src/fabric/dataset_mapper.py` | Modified | Full Defender/AttackPath/SecureScore entity+relationship vocabulary (not in git history at all — confirmed via `git show HEAD:... \| grep Defender` returning nothing) |
| `src/ontology/relationship_builder.py` | Modified | `connect()` calls wiring Defender assessment/finding/alert/attack-path/secure-score relationships |
| `src/ontology/ontology_sync.py` | Modified | `PendingRelationshipStore` wiring into `OntologyGraphSynchronizer`; `compliance_context` view expansion |
| `src/fabric/schema_registry.py` | Modified | 8 Bronze + 6 Silver Defender Delta table schemas |
| `src/fabric/sync_service.py` | Modified | `defender_intelligence_snapshot()`; `silver_defender_secure_scores` added to history-retention allow-list |
| `src/api/routers/vulnerability.py` | Modified | 7 new/renamed Defender + asset-exposure routes |
| `src/api/runtime.py` | Modified | `_snapshot_failure_table()`; `_DEFENDER_SOURCE_FAMILIES`; per-connection failure isolation in `_load_snapshot_tables()` |
| `src/api/app.py`, `src/api/dependencies.py` | Modified | Not independently read this session — small diffs (33 and 5 lines) per `git diff --stat`; likely new provider/router wiring for the above. **Verify before assuming unrelated.** |
| `src/intelligence/vulnerability/models.py`, `service.py` | Modified | New Defender-related fields on `VulnerabilityFinding`/`VulnerabilityExposure`; `defender_overview()`, `_coverage_for_family()`, `security_alerts()`, etc. |
| `src/onboarding/azure_clients.py` | Modified | Cost Management per-subscription failure isolation + vendor-specific `Retry-After` headers (tangential to MED-07, not Defender) |
| `src/onboarding/graph_normalize.py` | Modified | 330-line diff, not fully read this session — likely wires `defender_normalize.py`'s output into the broader normalization graph. **Executor must confirm.** |
| `src/onboarding/query_catalog.py` | Modified | 6 typed Defender `SecurityResources` KQL queries replacing 1 generic one |
| `src/onboarding/sync.py` | Modified (partially in `61377d92`) | Publish-failure logging (`logger.exception`) |
| `src/ontology/entity_builder.py` | Modified | `PAAS_ENTITY_TYPES` frozenset (16 PaaS resource type names) — small diff, underlies the *committed* `61377d92` fix |
| `src/operations/patching/service.py`, `src/storage/onelake_documents.py` | Modified | Small diffs (18, 15 lines), not read this session — likely incidental/adjacent. **Verify before assuming in-scope.** |
| `docs/ontology-model.md` | Modified | New "Defender semantic evidence" section; expanded compliance-context description — **fully read this session, consistent with code** |
| `infra/terraform/mcp_server.tf` | Modified | 1-line diff — unrelated to Fabric, likely a Phase 9 leftover. **Do not let a Phase 10 plan revert it.** |
| `tests/*` (13 files) | Modified/new | Regression + new-feature tests; **2 of the 13 test files need a fix** (see Common Pitfalls: stale six-family assertion; flaky Defender-endpoint test) |
| `web/src/app/compliance/page.tsx`, `exposure/page.tsx`, `.test.tsx` | Modified/new | 64- and 331-line diffs; `exposure/page.tsx` diff not read in full this session — large enough to warrant its own verification step before Phase 10 work touches the same file |
| `web/src/lib/types.ts`, `services.ts` | Modified | `DefenderOverview` and related types/service methods — **`DefenderOverview` fully read and confirmed to match `10-UI-SPEC.md`'s expectations** |
| `web/src/components/network/TopologyGraph.tsx`, `.test.tsx` | Modified | **Unrelated to Phase 10** — this is the already-resolved `topology-finding-drawer` debug session's fix (`.planning/debug/topology-finding-drawer.md`, read this session: a Cytoscape stale-badge rendering bug, root-caused and fixed, awaiting only human browser confirmation). Do not touch. |
| `web/src/components/AccountMenu.tsx`, `web/src/lib/auth.ts`/`auth.test.ts` | New/modified | Not read this session; appear unrelated to Fabric medallion (account/auth UI). **Do not assume in-scope; do not disturb.** |
| `.agents/`, `skills-lock.json` | New (untracked) | Tooling/agent-config artifacts, not phase-relevant |

**Committed (already in git history, safe baseline):** `61377d92` "fix: register ontology relationship endpoint types" — registers `PAAS_ENTITY_TYPES` and `FlowObservation` as ontology endpoint types, adds the improved `ValueError` diagnostic in `ontology_publisher.py`, and adds `tests/test_relationship_vocabulary_consistency.py`.

## Rollout Sequence with Rollback Gates

Directly implementing CONTEXT.md's locked sequencing ("integrity gates first, then metadata/status and manifests, then individual Silver/Gold pipelines with rollback, and finally semantic consumers and Data Agent grounding"), scoped against what this research found:

| Stage | Scope | Rollback / reversibility gate | Depends on |
|-------|-------|-------------------------------|------------|
| 0 | Commit and stabilize the existing uncommitted work: fix the stale `test_normalizer_production_graph_contains_all_six_signal_families` assertion, diagnose (or explicitly defer with a tracked follow-up) the flaky `test_defender_signal_endpoints_preserve_distinct_semantics`, run the full suite green, then commit in reviewable slices (e.g., ontology vocabulary, Defender pipeline, API/web surfaces as separate commits). | A green, committed baseline is itself the rollback point — `git revert` becomes possible for the first time. No new Fabric-side state changes yet. | — |
| 1 | **Integrity gates:** add the ownership/tag-coverage `DataQualityValidator` rule (MED-06); verify `ontology_publisher.py`'s preflight-before-network-call ordering with an explicit regression test; confirm no live-published Ontology item still reflects a pre-`61377d92` definition (re-run `docs/FABRIC_ONTOLOGY_DEPLOYMENT.md`'s "Deploy and verify" steps against the actual workspace). | Preflight validation is pure in-process logic — trivially revertible by code revert; no Fabric state is mutated by adding a validator rule. | Stage 0 |
| 2 | **Metadata/status and manifest:** generalize the Defender-family freshness/status/quality contract into a dataset-agnostic provider (MED-03); introduce the new publication manifest concept distinct from the existing snapshot manifest (MED-09); wire `ChangeIntelligence.knowledge_projection()` into `change_pipeline.run()` (MED-04). | Additive: new tables/columns, new API routes. Existing routes/contracts are untouched per CONTEXT.md's "Preserve existing API response-envelope... patterns." Roll back by feature-flagging the new provider off. | Stage 1 |
| 3 | **Individual Silver/Gold pipelines with rollback:** restore topology, operational-context, and assessment Gold outputs one at a time (per CONTEXT.md's "do not enable all pipelines in one uncontrolled capacity spike"), each behind its own `fabric.config.yaml enabled:` flag, each verified against `scripts/validate-lakehouse-tables.py` before enabling the next. | Per-pipeline flag flip is the rollback mechanism — confirmed this granularity already exists in config, not something Phase 10 must invent. | Stage 2 |
| 4 | **Semantic consumers and Data Agent grounding:** deploy the Direct Lake semantic model (MED-05) against curated Gold tables verified live in Stage 3; extend the Gold-grounding Data Agent evaluation per `10-AI-SPEC.md` §5b (MED-08). | Semantic model creation is versioned/idempotent (mirrors `ontology_publisher.py`'s create-or-update pattern); a failed/blocked deployment surfaces `deployment-blocked`, never partial success. | Stage 3 |
| 5 (can run in parallel with 3-4) | **OneLake data access roles, capacity health, lineage surfacing, Delta maintenance scheduling** (MED-10) — these are additive, read-mostly surfaces with no dependency on the Gold pipeline restoration order. | Each is independently toggleable; capacity/lineage are read-only ARM/Fabric-native calls with zero write risk. | Stage 1 (needs the integrity/metadata baseline for the health API to attach to) |

**Unified inventory remains the sole resource-identity authority throughout every stage** — no stage introduces a resource lookup, resource existence check, or ownership assertion that bypasses the existing inventory read port (per `INV-07`/`INV-10` and this phase's own locked decision). The MED-08 "inventory authority precedence" guardrail in `10-AI-SPEC.md` §6 is the concrete runtime enforcement of this; Phase 10 plans should reference it rather than re-deriving a competing rule.

## Standard Stack

**The overwhelming majority of Phase 10 requires zero new packages.** This repo's established pattern — confirmed repeatedly this session (`fabric_client.py`'s direct `httpx` REST calls, `data_agent_manager.py`'s explicit avoidance of the official `fabric-data-agent-sdk` due to a real, documented namespace collision) — is to call Fabric's REST APIs directly with `httpx` + `azure-identity` credentials, never an official or community Fabric SDK. Every new REST surface this research verified (Semantic Model creation, OneLake Data Access Roles, capacity ARM state, Delta maintenance) follows the exact same plain-REST shape already in use. **Continue this pattern; do not introduce a Fabric SDK.**

### Core (already present, no action needed)
| Library | Version (locked in `uv.lock`, verified this session) | Purpose | Why standard here |
|---------|---------|---------|--------------|
| `httpx` | `>=0.27,<1` (`pyproject.toml`, read this session) | All Fabric/Azure REST calls | Established pattern; async-capable; already the sole HTTP client in `fabric_client.py`/`data_agent_manager.py` |
| `azure-identity` | `>=1.19,<2` | Credential acquisition for ARM/Fabric/OneLake calls | Already the only auth mechanism used anywhere in `src/` |
| `deltalake` | `>=1.0,<2` | Reading/writing Delta tables directly (not via Spark) | Already used by `sync_service.py`'s `self.delta.read/write` |
| `pyarrow` | `>=23.0.1,<24` | Schema definitions (`schema_registry.py`) | Already the schema-typing mechanism for every Bronze/Silver/Gold table |
| `agent-framework` | `1.15.0` (verified installed via `uv pip show`-equivalent site-packages inspection this session) | MAF orchestration boundary | Existing, locked; MED-08 must not introduce a second orchestration framework (per `10-AI-SPEC.md §2`) |
| `azure-ai-projects` | `2.4.0` | Foundry project/agent client | Existing, locked |

### Supporting (new for this phase, all already resolvable — see Package Legitimacy Audit)
| Library | Version | Purpose | When to use |
|---------|---------|---------|-------------|
| `agent-framework-foundry` | `1.10.1` | MAF's Foundry hosted-agent adapter, including `get_fabric_tool()` | **Already installed** in this repo's `.venv` (verified live: `from agent_framework import foundry` resolves; `agent_framework_foundry-1.10.1.dist-info` present) — it ships as part of the `agent-framework` package family, not a package the planner needs to add. AI-SPEC's `uv add agent-framework-foundry` instruction is technically harmless (idempotent) but unnecessary. |
| `azure-ai-evaluation` | `1.18.3` (resolved live via `uv pip install --dry-run` this session) | Optional live-eval `GroundednessEvaluator`/`RetrievalEvaluator` for MED-08 | Only if the optional live-evaluation half of `10-AI-SPEC.md §5` is implemented; gated by `AIOPS_ENABLE_LIVE_GOLD_EVAL`, never a CI dependency |

### Alternatives Considered
| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| Direct `httpx` REST calls to Fabric Items/Semantic Model/OneLake APIs | `fabric-data-agent-sdk` or any other official/community Fabric Python SDK | Ruled out: confirmed live this session that `src/fabric` (this repo's own package) permanently shadows the SDK's `fabric.dataagent` namespace on `sys.path`; this is architecturally unfixable without renaming this repo's own top-level package. |
| ARM `properties.state` GET for capacity health | Microsoft Fabric Capacity Metrics App (Power BI report) | Metrics App is richer (throttling, compute/storage trend) but requires a capacity-admin-installed Power BI app and querying its own semantic model — a materially heavier integration for a "paused/throttled" boolean signal. Recommend ARM state now, Metrics App as a later enhancement. |
| Scheduling Delta maintenance via a Fabric Data Factory pipeline (Lakehouse Maintenance activity, Preview) | Calling the maintenance REST API directly from this repo's own cron/background worker | Pipeline path is Microsoft's documented, monitored (Monitoring hub) mechanism and keeps maintenance triggers entirely inside Fabric; the direct-REST path was not fully resolved this session (one guessed endpoint 404'd) and would require this repo to build its own scheduler/monitoring for something Fabric already provides. |

**Installation:** No `uv add` is required for the core/existing set. If the optional live-eval half of MED-08 is implemented: `uv add azure-ai-evaluation` (verified resolvable: pulls `defusedxml`, `joblib`, `nltk`, `pandas`, `regex`, `ruamel-yaml`, `tzdata` — 8 packages total, dry-run confirmed this session).

**Version verification:** `agent-framework==1.15.0` and `azure-ai-projects==2.4.0` confirmed via direct site-packages inspection this session (`importlib.metadata.version('agent-framework')` → `1.15.0`). `azure-ai-evaluation==1.18.3` confirmed via live `uv pip install --dry-run` resolution this session (not yet installed, but cleanly resolvable). **Note on package provenance:** `agent-framework-foundry` and its sibling `agent_framework_*` packages resolve, per `uv.lock` (read this session), through a **Microsoft-internal Azure DevOps package feed** (`ms-feed-*.pkgs.visualstudio.com`), not the public `pypi.org` index — this is Microsoft's normal distribution mechanism for pre-GA/fast-moving SDK families and is pre-existing infrastructure from Phase 9 (per `STATE.md`'s MAF-pivot narrative), not a new Phase 10 decision, but any fresh environment (a new CI runner, a clean clone) will need this feed configured (via an env var such as `UV_INDEX_URL`, not found committed to this repo) or `uv sync` will fail on these packages specifically.

## Package Legitimacy Audit

Ecosystem: PyPI. Checked via `gsd_run query package-legitimacy check --ecosystem pypi` this session, cross-verified against `uv pip install --dry-run` and direct site-packages inspection.

| Package | Registry | Age (per checker) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `agent-framework-foundry` | PyPI (resolved via MS-internal feed per `uv.lock`) | ~2 weeks old at check time (`publishedAt: 2026-08-14`) | unknown (checker has no data) | none detected by checker | `[SUS]` — reasons: `too-new`, `unknown-downloads`, `no-repository` | **No action required.** Already installed in this repo's `.venv` (confirmed live: `agent_framework_foundry-1.10.1.dist-info` present, `from agent_framework import foundry` imports successfully) as part of the pre-existing `agent-framework` package family from Phase 9. Not a new install decision for this phase. If a *future* environment needs to install it fresh, gate that specific install behind `checkpoint:human-verify` per protocol, since the checker's `too-new`/`no-repository` signals are real (even though this repo's own installed copy is Microsoft's own official `agent-framework` sibling package, confirmed by the `agent_framework.foundry` import path itself, not an independently-sourced third party). |
| `azure-ai-evaluation` | PyPI | mature (checker's `publishedAt` reflects latest release, not first release — this is the official Azure SDK for Python evaluation package) | unknown (checker has no download-count data source) | `github.com/Azure/azure-sdk-for-python` (official Azure SDK monorepo) | `[SUS]` — reason: `unknown-downloads` only | **Approved, with checkpoint.** The `SUS` verdict here is driven entirely by the checker's lack of a download-count data source, not a genuine legitimacy concern — the repo URL is Microsoft's own official Azure SDK monorepo, and `uv pip install --dry-run` resolved a clean, sensible 8-package dependency tree (`pandas`, `nltk`, `joblib`, etc. — consistent with an evaluation/NLP-metrics SDK). Per protocol, still tag `[SUS]` and require `checkpoint:human-verify` before the executor actually runs `uv add azure-ai-evaluation`, since this is a genuinely new (not-yet-installed) dependency. |
| `aiohttp` | PyPI | mature (AI-SPEC's suggested `uv add ... aiohttp`) | unknown (checker signal gap) | `github.com/aio-libs/aiohttp` | `[SUS]` — reason: `unknown-downloads` only | **Not needed.** Already installed (`aiohttp.__version__` → `3.14.3`, confirmed live this session) as a transitive dependency. AI-SPEC's suggestion to add it explicitly is unnecessary; no new install action. |

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** `agent-framework-foundry` (no action — already installed, pre-existing), `azure-ai-evaluation` (planner must add `checkpoint:human-verify` before the one `uv add` task that installs it, since it is the only genuinely new package this phase might introduce), `aiohttp` (no action — already installed).

*No packages in this audit were discovered via WebSearch or training-data guessing — all three were named by the pre-existing `10-AI-SPEC.md` and independently verified this session via live `uv`/site-packages inspection, which is why the SUS tags above are annotated with the specific reason each was triggered rather than treated as a blanket red flag.*

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Azure sources (ARG "SecurityResources", Cost Mgmt, Advisor, Policy, ...)     │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ typed KQL queries (query_catalog.py)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ onboarding/*_normalize.py  →  entity/relationship rows (entityType-tagged)  │
│   defender_normalize.py · graph_normalize.py · network_normalize.py         │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ fabric_pipelines/*.py  (topology · governance · vulnerability · change ·     │
│  lifecycle · patch · predeploy)                                             │
│  ── knowledge_projection()-style engines compute ontology-shaped rows ──    │
│     ⚠ change_pipeline.run() currently DISCARDS this output (MED-04 gap)     │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ entities + relationships
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ontology/ontology_sync.py :: OntologyGraphSynchronizer.synchronize()        │
│  ├─ dangling edges → PendingRelationshipStore (defer/retry, MED-06)         │
│  ├─ confidence.compute_confidence() per relationship                       │
│  └─ OntologyValidator.validate() — FAIL-CLOSED gate (MED-06)                │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ current_entity_rows / current_relationship_rows
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ontology/ontology_publisher.py :: build_definition()  ◄── PREFLIGHT (MED-01)│
│   raises ValueError BEFORE any network call if an endpoint type is         │
│   unregistered — verified this session (publish() calls build_definition() │
│   at line 49, manager.resolve() only at line 50)                            │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ Fabric Items REST API (LRO, fabric_client.py poller)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  MICROSOFT FABRIC WORKSPACE (aiops-dev-ops)                                  │
│  ┌────────────┐  ┌──────────────┐  ┌─────────────────────────────────────┐ │
│  │ Bronze     │→│ Silver        │→│ Gold  (assessment_change_findings,   │ │
│  │ Delta      │  │ Delta        │  │  gold_business_service_health, ...)  │ │
│  │ tables     │  │ tables       │  │  ◄── MED-02: verify vs. code-declared│ │
│  └────────────┘  └──────────────┘  │      via scripts/validate-lakehouse- │ │
│  ┌──────────────────────────────┐  │      tables.py                       │ │
│  │ Ontology item (type:"Ontology"│  └──────────────┬──────────────────────┘ │
│  │ — Fabric IQ, PREVIEW, no SLA) │                 │                        │
│  └──────────────┬───────────────┘                 ▼                        │
│                 │                    ┌──────────────────────────────────┐  │
│                 │                    │ Direct Lake Semantic Model (GA)  │  │
│                 │                    │  ◄── MED-05: NEW, greenfield     │  │
│                 │                    └──────────────────────────────────┘  │
│                 ▼                                                          │
│  ┌──────────────────────────────┐   ┌──────────────────────────────────┐  │
│  │ relationship_suggestion_agent │   │ OneLake data access roles       │  │
│  │  (Data Agent, MCP — currently │   │  ◄── MED-10: NEW (Lakehouse only)│  │
│  │  hitting an opaque "run       │   └──────────────────────────────────┘  │
│  │  failed" error — see MED-08)  │   ┌──────────────────────────────────┐  │
│  └──────────────────────────────┘   │ Capacity state / Delta maintenance│  │
│                                       │  ◄── MED-10: NEW (ARM GET + sched)│  │
│                                       └──────────────────────────────────┘  │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ NEW: FabricMedallionHealthProvider (MED-03/09/10) — reads Delta/manifest/    │
│  ARM state, never mutates Fabric; scope-enforced envelope, reuses           │
│  Evidence/envelope() idiom from src/api/evidence.py                         │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ GET /api/v1/fabric-medallion/*
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ web/src/app/connections/page.tsx — NEW "Fabric medallion" tab                │
│  (role="tablist" pattern copied verbatim from /inventory:776)               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure (additions only — everything else already exists)
```
src/fabric/
├── medallion_health.py         # NEW — MED-03: dataset-agnostic freshness/status/quality provider
├── semantic_model_manager.py   # NEW — MED-05: create/update Direct Lake semantic model item
├── data_access_roles.py        # NEW — MED-10: OneLake Data Access Roles REST wrapper
├── capacity_health.py          # NEW — MED-10: ARM `Microsoft.Fabric/capacities` state check
└── table_maintenance.py        # NEW — MED-10: trigger + read-back Delta OPTIMIZE/VACUUM status

src/ontology/
└── publication_manifest.py     # NEW — MED-09: active/dormant/retired disposition registry
                                  #   (distinct from the existing snapshot manifest in
                                  #    fabric/dataset_mapper.py / api/runtime.py)

src/api/routers/
└── fabric_medallion.py         # NEW — MED-03/09/10 health/capabilities API
                                  #   (per CONTEXT.md: a dedicated router, not an extension
                                  #    of connections.py's contract)

src/fabric_pipelines/
└── change_pipeline.py           # MODIFY (existing, uncommitted-adjacent) — forward
                                  #   ChangeIntelligence.knowledge_projection() output

web/src/app/connections/page.tsx  # MODIFY (existing) — add "Fabric medallion" tab per 10-UI-SPEC.md
web/src/lib/services.ts           # MODIFY (existing) — add fabricMedallionApi
web/src/lib/types.ts               # MODIFY (existing) — add FabricMedallionHealth, mirroring DefenderOverview idiom already present
```

### Pattern 1: Preflight-before-network-call validation
**What:** Validate every structural/vocabulary invariant of a definition entirely in-process before issuing the first REST call.
**When to use:** Any new Fabric item publication (semantic model, data access roles, ontology).
**Example (existing code, this repo, verified this session):**
```python
# src/ontology/ontology_publisher.py — publish() calls build_definition()
# BEFORE self.manager.resolve(...); build_definition() raises ValueError
# for any unregistered endpoint type, with zero network I/O having occurred.
def publish(self, *, ontology_id, ontology_name, entity_types, relationships):
    definition = self.build_definition(entity_types, relationships, ontology_name)  # preflight
    item = self.manager.resolve(ontology_id=ontology_id, ontology_name=ontology_name)  # first network call
    ...
```

### Pattern 2: Defer-and-retry instead of drop-or-fail for not-yet-resolvable data
**What:** When a relationship references an entity not yet in the current sync's snapshot, hold it in a bounded store and retry on the next sync, rather than dropping it (loses data) or failing the whole sync (blocks unrelated progress).
**When to use:** Any cross-domain reference where producer ordering isn't guaranteed (this pattern generalizes directly to MED-04's change-pipeline wiring gap: a `ChangeEvent` might reference a `ConfigurationBaseline` not yet discovered).
**Example (existing code, this repo, verified this session):**
```python
# src/ontology/pending_relationships.py
store = PendingRelationshipStore(max_pending=10_000)
store.defer(newly_dangling_edges)
resolved_now, still_pending = store.resolve(set(current_entity_ids))
```

### Pattern 3: Family-scoped, latest-per-scope source-status reduction
**What:** Reduce many raw `source_status` rows (one per sync attempt, per scope) down to one `{availability, freshness, quality, error, observed_at}` verdict per logical family, by scope, keeping only the most recent.
**When to use:** MED-03's dataset-agnostic health contract — lift this directly rather than reinventing it.
**Example (existing code, this repo, verified this session, `src/intelligence/vulnerability/service.py`):**
```python
def _coverage_for_family(self, family, scope):
    applicable = [row for row in self.defender_source_status
                  if row.get("source_family") == family and _source_status_matches_scope(row, scope)]
    latest = {}  # keyed by normalized requested_scope, keeps only the newest per key
    for row in applicable:
        key = _scope_key(row)
        if key not in latest or _status_timestamp(row) > _status_timestamp(latest[key]):
            latest[key] = row
    ...  # merge availability/freshness/quality across the surviving rows
```

### Anti-Patterns to Avoid
- **A second identity/resource-existence source.** Any Gold table, semantic model, or Data Agent answer that asserts a resource exists, is owned by X, or is in lifecycle state Y *independently* of the unified inventory read port violates the phase's locked constraint. Always join to inventory by resource ID; never re-derive identity from Fabric data.
- **Reintroducing a Fabric SDK.** The namespace collision (`src/fabric` vs. `fabric.dataagent`) is structural, not a one-off bug — it will recur for any officially-SDK'd Fabric surface. Stay on direct REST.
- **Silent success on a preview-surface deployment failure.** Given the Fabric IQ Ontology item type's own preview/no-SLA status (confirmed this session) and the documented opaque Data Agent MCP failure (confirmed this session), any new deployment code (semantic model, manifest-governed projections) must treat "no error, but also no confirmation" as a distinct `deployment-blocked`/degraded state, never a bare success.
- **A single global freshness threshold.** Confirmed this session: no such config exists yet, and CONTEXT.md explicitly forbids introducing one — freshness must be a per-dataset multiplier of that dataset's own pipeline cadence.
- **Triggering Delta maintenance from a request handler.** The platform's own 7-day retention floor is a safety net, not a substitute for keeping `OPTIMIZE`/`VACUUM` on a schedule outside the API request path, per CONTEXT.md's explicit prohibition.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Long-running Fabric REST operation polling (semantic model creation, any future LRO item type) | A new poller/backoff loop | `fabric_client.py`'s existing `_wait_for_operation`/`_retry_delay` (handles `202`+`Location`+`Retry-After`, generic across item types) | Already correct, already tested implicitly via existing Ontology/DataAgent publish flows; a second poller is duplicate logic with its own bug surface. |
| Row/column-level security enforcement on Lakehouse data | A custom filter-injection layer in this repo's own query code | OneLake Data Access Roles (`Read` permission + row/column filter rules), enforced natively by every OneLake-consuming engine (Spark, SQL endpoint, Direct Lake) | Confirmed live this session: RLS/CLS is a first-class OneLake capability for Lakehouse items; reimplementing it in application code would be enforced inconsistently across the different engines that read the same Delta tables. |
| Delta table compaction/vacuum scheduling and retry | A bespoke cron+lock mechanism in this repo | Fabric Data Factory's "Lakehouse Maintenance activity (Preview)", which already integrates with the Monitoring hub for run-status visibility | Fabric already provides scheduling, chaining, and monitoring for this exact operation; duplicating it means building and maintaining a second scheduler for no additional capability. |
| Confidence scoring for inferred relationships | Ad hoc literals at each call site (the exact anti-pattern `confidence.py`'s own docstring says it replaced) | `ontology.confidence.compute_confidence(source, corroborated=...)` | Already centralized this session (uncommitted); a new call site adding another hardcoded float would reintroduce the exact problem this module was built to fix. |
| Ownership/tag data-quality thresholds | A one-off script computing "84 missing ownership" ad hoc | A new rule inside the existing `DataQualityValidator.validate_table()` | Keeps quality reporting inside the one governed reporting path (`QualityReport`) instead of a parallel, harder-to-discover mechanism. |

**Key insight:** Every "Don't Hand-Roll" item above has an existing, already-proven analog somewhere else in this repo (an LRO poller, a defer/retry store, a confidence centralizer, a quality validator). The dominant risk in Phase 10 is not "no pattern exists" — it's **failing to notice a pattern already exists two files over** and rebuilding it with subtly different (and untested) semantics.

## Common Pitfalls

### Pitfall 1: Assuming the working tree matches git history
**What goes wrong:** A plan or executor greps `git log`/`git show HEAD:...` to "confirm" something exists, concludes it's missing, and rebuilds it — when it actually already exists in the uncommitted working tree.
**Why it happens:** This repo's current branch (`fix-ontology-sync-publish`) has 46 modified files and ~14 new files uncommitted (confirmed this session via `git diff --stat`/`git status --short`). Standard "is X implemented" greps against `git log -S` or `git show HEAD:` will silently miss all of it.
**How to avoid:** Always check the actual working tree (`view`/`cat` the live file), not just git history, before concluding something is unimplemented. This research's own §MED-01 finding (the Defender vocabulary genuinely isn't in git history, but is fully present and test-passing in the working tree) is the canonical example.
**Warning signs:** A plan step reads "implement Defender entity types" when they already exist; a plan step reads "the vocabulary mismatch from the live scan" without first re-running the vocabulary consistency test live.

### Pitfall 2: Stale test fixtures after an uncommitted vocabulary expansion
**What goes wrong:** `tests/test_situations_tracer.py::test_normalizer_production_graph_contains_all_six_signal_families` fails right now (confirmed via live `pytest` run this session) because it asserts exactly 6 `source_family` values including a single `"defender"`, but the normalizer now produces 6 granular `defender_*` families (`defender_assessments`, `defender_subassessments`, `defender_alerts`, `defender_attack_paths`, `defender_secure_scores`, `defender_secure_score_controls`) instead.
**Why it happens:** The Defender family was split into sub-families as part of the uncommitted work, but this one pre-existing regression test (at `tests/test_situations_tracer.py:159-172`) wasn't updated to match.
**How to avoid:** Fix this specific assertion (expand the expected set, or assert a superset/prefix match on `defender_`) as part of Stage 0 of the rollout sequence, before building anything new on top of the Defender pipeline.
**Warning signs:** `pytest tests/` full-suite runs report this failure; a plan that doesn't mention fixing it before layering more Defender-adjacent work on top.

### Pitfall 3: Flaky full-suite-only test failure
**What goes wrong:** `tests/test_api_vulnerability_router.py::test_defender_signal_endpoints_preserve_distinct_semantics` passed 3/3 times in isolation (confirmed live this session) but failed in 1 of 3 full-suite runs (also confirmed live this session) — a test-isolation gap, likely shared on-disk fixture/cache state polluted by another test module running earlier in the suite.
**Why it happens:** Not root-caused this session (would require a bisection of test execution order, out of scope for research). Plausible cause: a shared local-filesystem fixture directory (`live-data/`-style) or an in-process cache that isn't reset between test modules.
**How to avoid:** Do not treat a single green full-suite run as proof this test (or any newly-added Defender-adjacent test) is stable — run the full suite at least twice before trusting a "regression-free" claim for this area. Root-cause and fix the isolation gap as its own small task before Phase 10 adds more tests that share the same fixture surface.
**Warning signs:** A plan/verification step that runs the full suite exactly once and calls it done.

### Pitfall 4: Confusing the two different "manifest" concepts in this codebase
**What goes wrong:** A plan references "the manifest" for MED-09 (publication lifecycle: active/dormant/retired) and an executor wires it into `dataset_mapper.py`'s or `runtime.py`'s existing `manifest.json` handling — which is a **connection ingestion snapshot** manifest, an unrelated concept.
**Why it happens:** Both concepts are plausibly named "manifest" and this repo currently has only the snapshot one; MED-09's publication/lifecycle manifest is new and has no code home yet.
**How to avoid:** Name the new concept distinctly in code and docs (e.g., "publication manifest" or "dataset registry," never bare "manifest") and never extend `dataset_mapper.py`'s `manifest.json`-reading code path to also carry lifecycle disposition.
**Warning signs:** A new field added to the snapshot-manifest JSON schema that has nothing to do with per-connection ingestion.

### Pitfall 5: Treating "Fabric Data Agent" and "Fabric IQ" as interchangeable when reasoning about preview/GA status
**What goes wrong:** A plan states "the Data Agent is GA, so no deployment-blocked handling is needed" — true for a Data Agent pointed at a Lakehouse/Warehouse, **false** for one grounded in an Ontology item, because the Ontology item type itself belongs to Fabric IQ, which is explicitly preview.
**Why it happens:** Microsoft's own docs (fetched live this session) use "Fabric data agent" as the feature name in both contexts, obscuring that the *item it's grounded in* determines the actual preview/GA boundary, not the agent feature name alone.
**How to avoid:** Always check the preview status of the specific *item type* being deployed (`"type": "Ontology"` in this repo's case — confirmed preview both by Microsoft's `fabric-iq` doc and by this repo's own `docs/FABRIC_ONTOLOGY_DEPLOYMENT.md`), not the umbrella feature name.
**Warning signs:** A plan that removes or weakens the `deployment-blocked` state on the grounds that "Data Agent is GA now."

## Code Examples

### Fabric REST: create a Semantic Model (verified live from official docs this session)
```http
POST https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/semanticModels
Authorization: Bearer <token>
Content-Type: application/json

{
  "displayName": "aiops_gold_semantic_model",
  "description": "Direct Lake semantic model over curated Gold products.",
  "definition": {
    "parts": [
      {"path": "model.bim", "payload": "<base64 TMSL/TMDL>", "payloadType": "InlineBase64"},
      {"path": "definition.pbism", "payload": "<base64>", "payloadType": "InlineBase64"},
      {"path": ".platform", "payload": "<base64>", "payloadType": "InlineBase64"}
    ]
  }
}
```
Source: `learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/create-semantic-model` (fetched live 2026-09-01). `201` = created immediately; `202` = LRO, poll `Location` header with `fabric_client.py`'s existing `_wait_for_operation`.

### Fabric REST: list OneLake data access roles (verified live)
```http
GET https://api.fabric.microsoft.com/v1/workspaces/{workspaceId}/items/{lakehouseItemId}/dataAccessRoles
Authorization: Bearer <token>
```
Response shape (from the official sample, fetched live):
```json
{
  "value": [
    {
      "name": "default_role_1",
      "eTag": "33c64df551425fcc55e4d42a148795d9f25f89cc",
      "decisionRules": [
        {"effect": "Permit", "permission": [
          {"attributeName": "Path", "attributeValueIncludedIn": ["*"]},
          {"attributeName": "Action", "attributeValueIncludedIn": ["Read"]}
        ]}
      ],
      "members": {"fabricItemMembers": [{"itemAccess": ["ReadAll"], "sourcePath": "..."}]}
    }
  ]
}
```
Source: `learn.microsoft.com/en-us/rest/api/fabric/core/onelake-data-access-security/list-data-access-roles` (fetched live 2026-09-01).

### ARM: Fabric capacity state (verified live against this deployment, not a fabricated example)
```bash
az resource show --ids "/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Fabric/capacities/{name}" \
  --api-version 2023-11-01 -o json
```
Actual output, this deployment, this session:
```json
{"properties": {"provisioningState": "Succeeded", "state": "Active"}, "sku": {"name": "F4", "tier": "Fabric"}}
```
`properties.state` is the field to poll periodically for MED-10's paused/throttled detection (values observed/documented: `Active`; `Paused` per `STATE.md`'s own account of a prior manual pause/resume).

### Existing repo pattern: publication preflight (reuse, don't reinvent — see Architecture Patterns Pattern 1)
```python
# src/ontology/ontology_publisher.py:41-73 (read this session)
def publish(self, *, ontology_id, ontology_name, entity_types, relationships):
    definition = self.build_definition(entity_types, relationships, ontology_name)  # raises before any I/O
    item = self.manager.resolve(ontology_id=ontology_id, ontology_name=ontology_name)
    ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Foundry classic connected agents (agent-to-agent delegation) | Local MAF/Foundry orchestration with agents as governed tool-users | Classic connected agents removed from the new Agent Service in March 2026; classic service retires March 2027 (per `.planning/ROADMAP.md`'s own Phase 9 decision record, cross-referenced this session, not independently re-verified against Microsoft docs this session — carried forward as `[CITED: internal ROADMAP.md]`) | MED-08's Gold-grounding work must stay inside the existing MAF/Foundry boundary (already locked by `10-AI-SPEC.md §2`); do not architect toward agent-to-agent delegation. |
| `fabric-data-agent-sdk` for Data Agent management | Direct REST calls via `DataAgentManager` | Discovered this session's predecessor research (`docs/fabric-data-agent-relationship-suggestions.md`) due to the namespace collision, not a Microsoft-side deprecation | Extend this same direct-REST pattern to Semantic Model / Data Access Roles rather than introducing an SDK for those. |
| One generic `vulnerability` ARG KQL query (`type contains 'vulnerability'`) | Six typed `SecurityResources` queries filtered by exact ARM type | This session's uncommitted work (not yet committed) | More precise Defender ingestion; the old generic query is gone from `query_catalog.py`'s working tree — do not resurrect it if reconciling with git history. |
| Fabric ontology preview constraints as of this repo's original design (`ONTOLOGY_SCHEMA.md`/`ontology-schema.md`, authored before this session) | Confirmed still preview, no SLA, as of live docs fetched 2026-09-01 | No change — re-confirmed, not superseded | The `deployment-blocked` disposition requirement remains fully justified; do not relax it on the assumption the platform has since gone GA. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The exact REST endpoint slug for triggering Delta table maintenance via the Fabric REST API (as opposed to portal/pipeline) — one guessed URL (`rest/api/fabric/lakehouse/tables/run-on-demand-table-maintenance`) 404'd live this session and the correct slug was not found before research time ran out. | MED-10 / Delta maintenance | If the planner assumes a specific REST call shape without re-verifying, the executor may burn a cycle on a wrong endpoint. The Data-Factory-pipeline path (verified to exist) is the safer default recommendation. |
| A2 | The CONTEXT.md live-scan baseline numbers (320 readable tables, Bronze 9/8, Silver 18/14, Gold 288/140, 2,091 entities, 1,669 relationships, 84 missing ownership, 52 missing tags, 9 completed/12 failed ingestion runs) were not found as a persisted artifact anywhere in the repo this session and were not independently reproduced against live Fabric this session (no write/verification call was made against the live workspace beyond a read-only capacity ARM check). | Summary, MED-02 | If these exact figures have drifted since 2026-09-01 (very likely, given this phase's own work will change them), a plan that hard-codes them as acceptance-test targets will be wrong on day one. Recommend the plan re-run `scripts/validate-lakehouse-tables.py` (or equivalent) fresh rather than trusting the CONTEXT.md numbers as current. |
| A3 | Whether `src/onboarding/graph_normalize.py`'s 330-line uncommitted diff fully wires `defender_normalize.py`'s output into the broader entity graph, or leaves a gap, was not traced line-by-line this session (time-boxed against the rest of the audit). | Uncommitted Work Inventory | If a gap exists here, MED-04's Defender-domain "populated" conclusion would need revision for the entity-linking (not just entity-creation) half. |
| A4 | Whether the `Prediction`/`Forecast`/`RemediationPlan`/predictive-domain ontology entity types (declared in `ONTOLOGY_ENTITY_TYPES`) have a producer analogous to `ChangeIntelligence.knowledge_projection()`, or share the same "computed but discarded" gap as the change/configuration domain, was not investigated this session. | MED-04 | If unverified, the planner might either duplicate work that already exists, or miss an identical wiring gap in a different domain. |
| A5 | The exact mechanism by which `SyncResult.publish_message` (from `src/onboarding/sync.py`'s exception handling) does or does not reach a durably queryable store versus only a process log was not fully traced end-to-end this session. | MED-01 | If it already reaches durable storage somewhere not inspected, MED-01's "durable terminal state" gap may be smaller than characterized here. |

**If this table is empty:** N/A — see rows above; all other claims in this research are `[VERIFIED]` (read this session) or `[CITED]` (fetched live from an authoritative source this session) as annotated inline throughout.

## Open Questions

1. **Does `src/api/app.py`/`dependencies.py`'s uncommitted diff (33 and 5 lines) wire the new Defender routes/providers completely, or is there a remaining registration gap?** *(RESOLVED — see Plan 10-01 Task 1: live curl confirms all 7 `/defender/*`/`/vulnerabilities/defender-posture`/`/vulnerabilities/asset-exposures` routes return HTTP 200, and `test_defender_signal_endpoints_preserve_distinct_semantics`'s full-suite flakiness is diagnosed and fixed in the same task.)*
   - What we know: `git diff --stat` shows both files touched; neither was read in full this session.
   - What's unclear: whether `runtime.py`'s provider registration for the Defender-augmented `VulnerabilityIntelligenceService` is complete, or whether the API would 500 on the new `/defender/*` routes without an additional wiring step.
   - Recommendation: the planner's first task in Stage 0 should be `pytest tests/test_api_vulnerability_router.py -v` plus a live `curl` against a running dev API instance for each new `/api/v1/defender/*` route, rather than assuming the diff is complete from its line count alone.

2. **What is the actual current disposition of the `Prediction`/`Forecast`/`RemediationPlan`/predictive-and-remediation ontology domain?** *(RESOLVED — see Plan 10-06 Task 3: the identical investigation pattern used for the Change domain confirms or dispositions the predictive/remediation domain's producer status, regression-tested in `tests/test_change_pipeline_ontology_forwarding.py`. Plan 10-06 Task 4 additionally confirms the Incident domain shares the same "computed but discarded" gap — `IncidentEngine.knowledge_projection()` exists but was never wired into `sync_service.py` — and fixes it the same way.)*
   - What we know: these types are declared in `ONTOLOGY_ENTITY_TYPES`; `docs/*_RUNBOOK.md` and `docs/PREDICTIVE_OPERATIONS*.md`/`docs/REMEDIATION_PLANNING*.md` exist (titles suggest mature features) but were not read this session.
   - What's unclear: whether these domains have the same "computed but discarded at the pipeline boundary" gap found for `ConfigurationDrift`/`PolicyDeviation` in the change domain.
   - Recommendation: run the identical investigation pattern used for MED-04 in this research (`grep` the type name in `fabric_pipelines/`, read the relevant pipeline's `run()` return contract) before scoping a plan for these domains.

3. **Which specific Fabric REST endpoint triggers Delta table maintenance programmatically (as opposed to portal/pipeline)?** *(RESOLVED — safely sidestepped per Plan 10-07 Task 3: the module reads Monitoring-hub-sourced last-run status only and never guesses at or implements the on-demand trigger endpoint, adopting the confirmed-to-exist Data-Factory-pipeline path as the actual maintenance mechanism instead, exactly as this Open Question's own recommendation advised.)*
   - What we know: the maintenance doc references "Manage the lakehouse with Fabric REST API" as a related article; one guessed URL slug 404'd.
   - What's unclear: the exact path/method.
   - Recommendation: either resolve this via Microsoft's REST API reference index at plan time, or simply adopt the Data-Factory-pipeline path (confirmed to exist and to integrate with Monitoring hub) as the primary mechanism, treating direct-REST as an optional future optimization.

4. **Does the `test_defender_signal_endpoints_preserve_distinct_semantics` flakiness share a root cause with any other test-isolation issue already known in this repo?** *(RESOLVED — see Plan 10-01 Task 1: the flakiness is diagnosed, bisected, and fixed via a module-scoped fixture cleanup/isolation fix, verified by two consecutive full-suite runs both passing.)*
   - What we know: it passes in isolation, intermittently fails in the full suite; not bisected this session.
   - What's unclear: the specific shared-state mechanism.
   - Recommendation: treat this as its own small debugging task (the repo already has an established `gsd-debug` skill/pattern per `.planning/debug/topology-finding-drawer.md`'s exemplary session) before Phase 10 adds more tests touching the same fixture surface.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Azure CLI (`az`), authenticated | Live capacity-state checks, any live verification step | ✓ (verified live this session — `az account show` succeeded against subscription `a87a8e64-a52a-4aa8-a760-5e8919d23cd1`) | 2.87.0 | — |
| Microsoft Fabric capacity `aiopsdevcapg6ludc` | All Fabric work | ✓ (verified live — `state: Active`, SKU F4) | F4 | — |
| `uv` | Python dependency management | ✓ | 0.10.9 | — |
| Microsoft-internal package feed (for `agent-framework-foundry` and siblings) | MED-08 optional Foundry-hosted-agent path | Not independently verified reachable this session (no `uv sync` run against a clean environment); packages are already installed in this checkout's `.venv`. | — | If unreachable in a fresh environment (e.g., new CI runner), the interim direct-MCP path (already this repo's primary recommendation per `10-AI-SPEC.md`) requires none of these packages. |
| `pytest` | Backend test suite | ✓ | 9.1.1 (via `pyproject.toml`'s `>=9.0.3,<10`) | — |
| `vitest` | Frontend test suite | ✓ | 2.1.9 (`web/package.json`) | — |
| Docker | Not required for this phase's own work (no new container image identified as necessary) | ✓ (available, not required) | 29.7.2 | — |
| Node.js | Frontend build | ✓ | 22.23.2 | — |
| Fabric Capacity Metrics App | Optional richer capacity telemetry (MED-10 stretch) | Not checked this session (requires portal install by a capacity admin) | — | Use the ARM `properties.state` check as the primary/required signal instead. |

**Missing dependencies with no fallback:** none identified — every capability this phase needs has either a working local tool or a documented REST alternative.
**Missing dependencies with fallback:** the Microsoft-internal package feed for the optional live-Foundry-hosted-agent path (fallback: stay on the interim direct-MCP path, already the primary recommendation).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Backend framework | pytest 9.1.1 (`pyproject.toml`'s `[tool.pytest.ini_options]`, `testpaths = ["tests"]`, `addopts = "-q"`) |
| Frontend framework | Vitest 2.1.9 (`web/package.json`) |
| Config file | `pyproject.toml` (backend); `web/vitest.config.*` (not read this session, presumed present given `npm test` → `vitest run` works) |
| Quick run command (backend) | `pytest tests/test_relationship_vocabulary_consistency.py tests/test_relationship_builder.py tests/test_confidence.py tests/test_pending_relationships.py tests/test_relationship_suggestion_promoter.py -q` (verified live this session: 31/31 pass, <1s) |
| Quick run command (frontend) | `cd web && npx vitest run src/components/network/TopologyGraph.test.tsx` (pattern only — not this phase's own test target) |
| Full suite command (backend) | `pytest tests/ -q` (verified live this session: takes ~60-90s, currently 5-6 failures — see below) |
| Full suite command (frontend) | `cd web && npm test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MED-01 | Preflight rejects undefined endpoint types before any Fabric call | unit | `pytest tests/test_relationship_vocabulary_consistency.py -x` | ✅ (passes 4/4, verified live) |
| MED-01 | Retry/durable terminal state on transient publish failure | unit + integration | `pytest tests/ -k "publish and (retry or failure)"` | ❌ Wave 0 — no test found matching this pattern this session; likely needs a new `tests/test_ontology_publish_durability.py` |
| MED-02 | Gold outputs match code-declared schema registry | deployment/live | `python3 scripts/validate-lakehouse-tables.py --config fabric.config.yaml --json-out /tmp/gold-audit.json` | ✅ script exists, verified live this session; requires a live, authenticated Fabric workspace to actually run |
| MED-03 | Dataset status distinguishes healthy-empty/stale/degraded/failed/unavailable | unit | `pytest tests/ -k "coverage_for_family or source_status or snapshot_failure"` | ⚠ partial — `_coverage_for_family`/`_snapshot_failure_table` exist but a dataset-agnostic version does not; Wave 0 needs a new test module once `medallion_health.py` is built |
| MED-04 | Defender-domain endpoints return distinct alert/attack-path/secure-score semantics | contract | `pytest tests/test_api_vulnerability_router.py::test_defender_signal_endpoints_preserve_distinct_semantics -x` | ✅ exists; flaky in full-suite context — see Common Pitfalls #3 |
| MED-04 | Change/configuration-drift ontology rows reach publication | unit | `pytest tests/ -k "change_pipeline and (entities or relationships)"` | ❌ Wave 0 — no test found asserting `change_pipeline.run()` forwards `knowledge_projection()` output; needs a new regression test once the wiring gap is fixed |
| MED-05 | Semantic model deployment succeeds or reports deployment-blocked | integration + live Fabric | `pytest tests/test_semantic_model_manager.py -x` (new) | ❌ Wave 0 — module doesn't exist yet |
| MED-06 | Referential integrity blocks publish on dangling/self/duplicate relationships | unit | `pytest tests/ -k ontology_validator` (module `test_ontology_validator.py` not confirmed present this session — verify) | ⚠ verify — `OntologyValidator` itself is read and mature; dedicated test file existence not confirmed this session |
| MED-06 | Ownership/tag coverage warns or blocks by environment | unit | `pytest tests/test_data_quality.py -k "ownership or tag"` (new) | ❌ Wave 0 — rule doesn't exist yet |
| MED-07 | History-preserving write mode applied to designated tables | unit | `pytest tests/ -k "sync_service and history"` | ⚠ verify — the allow-list mechanism exists (`sync_service.py`); a dedicated regression test enumerating all required history tables was not confirmed present this session |
| MED-08 | Gold-grounding evaluation (23-case set) | offline-eval | `python3 scripts/evaluate_agents.py --baseline .planning/eval/gold-grounding-baseline.json --out .planning/eval/gold-grounding-latest.json` | ✅ per `10-AI-SPEC.md`, harness exists, cases to be added |
| MED-09 | Publication manifest lifecycle states are queryable | unit + contract | `pytest tests/test_publication_manifest.py -x` (new) | ❌ Wave 0 — module doesn't exist yet |
| MED-10 | Capacity state check returns Active/Paused correctly | unit (mocked) + manual-live | `pytest tests/test_capacity_health.py -x` (new) + `az resource show --ids ... --api-version 2023-11-01` (manual live check, pattern verified this session) | ❌ Wave 0 for the unit test; live check pattern already proven |
| MED-10 | OneLake data access role CRUD round-trips | integration + live Fabric | `pytest tests/test_data_access_roles.py -x` (new) | ❌ Wave 0 — module doesn't exist yet |

### Sampling Rate
- **Per task commit:** the relevant quick-run subset above (e.g., `pytest tests/test_relationship_vocabulary_consistency.py tests/test_ontology_validator.py -q` for any MED-01/06 change).
- **Per wave merge:** `pytest tests/ -q` (full backend suite) — **run it twice**, per Common Pitfall #3, before trusting a green result for anything touching the Defender/vulnerability router surface.
- **Phase gate:** full suite green (accounting for the 4 pre-existing, unrelated failures already tracked in `STATE.md`) before `/gsd-verify-work`; live `scripts/validate-lakehouse-tables.py` run against the actual dev Fabric workspace before declaring MED-02 satisfied.

### Wave 0 Gaps
- [ ] `tests/test_situations_tracer.py::test_normalizer_production_graph_contains_all_six_signal_families` — fix stale assertion (expand or generalize the expected `source_family` set) — **blocking**, causes a real failure today.
- [ ] Diagnose `tests/test_api_vulnerability_router.py::test_defender_signal_endpoints_preserve_distinct_semantics` full-suite flakiness — not strictly blocking (passes in isolation) but should be fixed before adding more Defender-adjacent tests.
- [ ] `tests/test_ontology_publish_durability.py` — new, covering MED-01's durable-terminal-state requirement once implemented.
- [ ] `tests/test_medallion_health.py` — new, covering MED-03's generalized dataset-status provider.
- [ ] `tests/test_change_pipeline_ontology_forwarding.py` (or extend `tests/test_relationship_builder.py`) — new, covering MED-04's `knowledge_projection()`-forwarding fix.
- [ ] `tests/test_semantic_model_manager.py` — new, MED-05.
- [ ] Extend `tests/test_relationship_vocabulary_consistency.py` or add `tests/test_data_quality_ownership_tags.py` — new, MED-06's ownership/tag rule.
- [ ] `tests/test_publication_manifest.py` — new, MED-09.
- [ ] `tests/test_capacity_health.py`, `tests/test_data_access_roles.py`, `tests/test_table_maintenance_status.py` — new, MED-10 (all mockable against the live REST/ARM shapes verified in this document; live-Fabric variants gated behind an env flag, mirroring `AIOPS_ENABLE_LIVE_GOLD_EVAL`'s pattern from `10-AI-SPEC.md`).

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes (existing) | This phase adds no new authentication surface; every new API route reuses the existing bearer-token/RBAC dependency chain (`src/api/dependencies.py`, `Context`/`ReadScope`/`OperatePrincipal` per `connections.py`'s pattern, read this session). |
| V3 Session Management | No change | No new session concept introduced. |
| V4 Access Control | Yes | Every new `/api/v1/fabric-medallion/*` route must be scope-enforced identically to `connections.py`'s existing pattern (`ReadScope` dependency, `Evidence`/`envelope()` response shape) — CONTEXT.md explicitly locks this ("Preserve existing API response-envelope, authentication... patterns"). OneLake Data Access Roles and Fabric workspace roles are the platform-side V4 control for MED-10's data plane. |
| V5 Input Validation | Yes | `ontology_publisher.py::build_definition()`'s preflight is itself a V5 control (rejects malformed/unregistered relationship definitions before any I/O); `OntologyValidator`/`DataQualityValidator` are the broader V5 gate for entity/relationship rows. Any new semantic-model TMDL/definition builder must apply the same discipline. |
| V6 Cryptography | No new crypto — all auth continues through `azure-identity`'s managed-identity/token flows, never a hand-rolled scheme. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Ontology publication injecting an undefined/attacker-influenced relationship endpoint type | Tampering | `ontology_publisher.py`'s preflight (already fail-closed, verified this session) + `OntologyValidator`'s dangling/duplicate/self-link checks |
| Prompt injection via free-text Gold-table fields reaching the Data Agent's narration | Tampering / Elevation of Privilege | Covered exhaustively by `10-AI-SPEC.md §5c` row 8 and §6's guardrail table — do not duplicate; this research's role is to confirm no additional MED-01–07/09–10 surface introduces a new instance of this pattern. Confirmed: none of the new REST-only surfaces (semantic model, data access roles, capacity, maintenance) involve free-text-to-LLM paths. |
| A caller escalating scope by requesting OneLake data-access-role membership changes | Elevation of Privilege | CONTEXT.md's explicit "no broad workspace mutation from end-user requests" — data access role *reads* should be exposed via the new API for observability; role *writes* should remain an operator/deploy-time action (Terraform or a scripted, human-triggered path), never a runtime API endpoint callable by an ordinary authenticated user. |
| Fabric capacity-paused/throttled state used to silently degrade security posture (e.g., stale Defender data misread as current) | Denial of Service (availability) | The `unavailable`/`degraded` vocabulary already proven in `_snapshot_failure_table`/`_coverage_for_family` — generalize it (MED-03) rather than letting a paused capacity present as "healthy-empty." |
| Credential/secret leakage in Fabric REST error responses or telemetry | Information Disclosure | `src/api/telemetry.py`'s existing discipline — "no request payloads, headers, principals, or scope values are recorded — only low-cardinality dimensions" (quoted from `10-AI-SPEC.md §6`, itself sourced from this repo's own telemetry module) — apply identically to any new `GoldGroundingMetrics`-style meter for MED-10's capacity/maintenance telemetry. |

## Sources

### Primary (HIGH confidence — fetched live from official Microsoft documentation this session, or read directly from this repo's own source/tests/git history/live Azure state this session)
- `learn.microsoft.com/en-us/fabric/data-science/concept-data-agent` — Fabric data agent GA status, Purview DLP/access-restriction enforcement, read-only access guarantee, NL2SQL/NL2DAX/NL2KQL tool selection
- `learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview` — Direct Lake GA status, medallion Gold-layer recommendation, framing vs. Import refresh semantics, V-Order tuning note
- `learn.microsoft.com/en-us/rest/api/fabric/semanticmodel/items/create-semantic-model?tabs=HTTP` — exact Semantic Model creation REST contract, LRO shape, error codes, permission requirements
- `learn.microsoft.com/en-us/fabric/onelake/security/data-access-control-model` — OneLake security RBAC model, deny-by-default, Read/ReadWrite semantics, supported item types (Lakehouse + mirrored only), RLS/CLS constraint on ReadWrite roles
- `learn.microsoft.com/en-us/rest/api/fabric/core/onelake-data-access-security/list-data-access-roles?tabs=HTTP` — exact Data Access Roles REST contract and JSON shape
- `learn.microsoft.com/en-us/fabric/enterprise/metrics-app` — Fabric Capacity Metrics App pages/capabilities, capacity-admin install requirement
- `learn.microsoft.com/en-us/fabric/data-engineering/lakehouse-table-maintenance` — OPTIMIZE/V-Order/VACUUM mechanics, 7-day retention floor and its platform-enforced failure mode, Data Factory Lakehouse Maintenance activity, Monitoring hub run-status location
- `learn.microsoft.com/en-us/fabric/governance/lineage` — native per-workspace lineage view, permissions, accessibility, limitations
- `learn.microsoft.com/en-us/power-bi/enterprise/service-admin-rls` — RLS mechanics and the Direct-Lake-fallback-to-DirectQuery nuance (verified genuine via raw-HTML re-fetch, not a parsing artifact)
- `learn.microsoft.com/en-us/rest/api/fabric/articles/throttling` — Fabric Unified Quota model (200 calls/min per identity per category), 429/Retry-After handling guidance
- `learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/ontology-definition` — official Ontology item definition-parts contract, cross-verified byte-for-byte structurally against this repo's own `ontology_publisher.py` output
- `learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq` — Fabric IQ preview banner/SLA disclaimer, prerequisites, region/VNet constraints
- `learn.microsoft.com/en-us/fabric/iq/ontology/how-to-create-agent-foundry-iq` — Foundry-IQ ontology-knowledge-base path, Azure AI Search "Search Index Data Contributor" role prerequisite
- This repo, read directly this session: `src/ontology/ontology_publisher.py` (full), `ontology_validator.py` (full), `pending_relationships.py` (full), `confidence.py` (full), `data_quality.py` (full), `onboarding/defender_normalize.py` (full), `onboarding/health.py` (full), `onboarding/schedule.py` (full), `fabric_pipelines/change_pipeline.py` (full), `intelligence/change/change_intelligence.py` (partial, `knowledge_projection()` located and read), `fabric/dataset_mapper.py` (entity/relationship type tuples), `infra/terraform/fabric.tf` (full), `infra/terraform/variables.tf` (Fabric section), `tests/test_relationship_vocabulary_consistency.py` (full), `docs/fabric-data-agent-relationship-suggestions.md` (full), `docs/FABRIC_ONTOLOGY_DEPLOYMENT.md` (full), `scripts/validate-lakehouse-tables.py` (full), `web/src/lib/types.ts` diff (`DefenderOverview`), `web/src/app/inventory/page.tsx` (tab pattern lines), `.planning/debug/topology-finding-drawer.md` (full — confirmed unrelated-to-Phase-10 but preserved work)
- Live, read-only Azure calls this session: `az account show`, `az resource list --resource-type Microsoft.Fabric/capacities`, `az resource show --api-version 2023-11-01` against the actual `aiopsdevcapg6ludc` capacity
- Live test execution this session: `pytest tests/ -q` (full suite, run twice), `pytest tests/test_relationship_vocabulary_consistency.py -v`, `pytest tests/test_relationship_builder.py tests/test_confidence.py tests/test_pending_relationships.py tests/test_relationship_suggestion_promoter.py -v`, isolated reruns of the flaky test
- Live package resolution this session: `gsd_run query package-legitimacy check`, `uv pip install --dry-run agent-framework-foundry`, `uv pip install --dry-run azure-ai-evaluation`, direct site-packages inspection of `agent_framework.foundry`

### Secondary (MEDIUM confidence)
- `.planning/phases/10-fabric-medallion-capability-expansion/10-AI-SPEC.md` (797 lines, read in full this session) — extensively pre-researched MED-08 material; treated as authoritative for that requirement and cross-referenced, not duplicated
- `.planning/phases/10-fabric-medallion-capability-expansion/10-UI-SPEC.md` (222 lines, read in full this session) — authoritative for the web surface; cross-referenced against actual `web/src/lib/types.ts`/`inventory/page.tsx` to confirm accuracy (confirmed accurate)
- `.planning/ROADMAP.md` §Phase 9/10 — orchestration-mechanism decision record and Phase 10 success criteria (internal document, not independently re-verified against Microsoft's own agent-service deprecation timeline this session)

### Tertiary (LOW confidence / explicitly flagged)
- CONTEXT.md's live-scan baseline numbers (320 tables, 2,091 entities, etc.) — see Assumptions Log A2
- The exact REST endpoint for on-demand Delta table maintenance — see Assumptions Log A1

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package claim was verified via live `uv`/site-packages inspection this session, not training-data assumption.
- Architecture (existing-code patterns): HIGH — every pattern cited was read directly from the working tree this session, with exact file/line references.
- Architecture (new/greenfield surfaces, MED-05/09/10): MEDIUM-HIGH — REST contracts verified live from official docs; this repo's specific integration code does not exist yet, so the *shape* is verified but the *fit* is a recommendation, not an observation.
- Pitfalls: HIGH — all five are either live-reproduced test failures/flakiness (this session) or directly-observed code gaps (this session), not speculative.
- MED-08 (Data Agent grounding/eval): HIGH — inherited from `10-AI-SPEC.md`'s own extensive, independently-verifiable research, cross-checked against this repo's own `docs/fabric-data-agent-relationship-suggestions.md` and found consistent.

**Research date:** 2026-09-01
**Valid until:** 2026-09-15 (14 days) for the Fabric-platform documentation citations — Fabric IQ/Ontology is an actively-changing preview surface and Microsoft revises these pages frequently; re-verify preview/GA status and any REST contract shape before implementing MED-05/08/09 if this research is consumed more than two weeks after the date above. The repository-state findings (uncommitted work inventory, test failures, vocabulary consistency) are valid only until the next commit or `git stash` touches these files — re-run the live checks in this document (`pytest tests/ -q`, `git status --short`) at the start of planning, not just at research time.

