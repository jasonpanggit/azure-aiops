---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 7
current_phase_name: Unified Resource Inventory
status: planned
stopped_at: Phase 7 planned and verified — 6 plans, 19 tasks, ready to execute
last_updated: "2026-08-26T13:40:00.000Z"
last_activity: 2026-08-26
last_activity_desc: Planned Phase 7 (6 plans, 19 tasks, 6 sequential waves). Plan-checker found 5 blockers + 5 should-fixes; all resolved and re-verified. Split 07-03 T1 into T1a (publication safety) and T1b (tracer).
progress:
  total_phases: 9
  completed_phases: 1
  total_plans: 18
  completed_plans: 12
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-08-23)

**Core value:** Operators can move from a detected Azure situation to an evidence-backed, auditable, human-approved remediation without losing context or control.
**Current focus:** Phase 1: Evidence and Situation Foundation

## Current Position

Phase: 1 of 5 (Evidence and Situation Foundation)
Plan: 2 of 2 in current phase
Status: Phase complete — ready for verification
Last activity: 2026-08-23 — Created brownfield MVP roadmap with complete v1 requirement coverage.

Progress: ██░░░░░░░░ [█████████░] 92%

## Performance Metrics

**Velocity:**

- Total plans completed: 2
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

## Accumulated Context

### Decisions

Recent decisions affecting current work:

- [Phase 7]: Two publishers sharing one generation root also share `state/dataset_hashes.json`. A partial publish marks every absent dataset as removed (`storage.py:128`) and overwrites the hash baseline wholesale (`storage.py:143`), destroying Hermes incremental-change detection. Publication must merge-not-replace or namespace per domain — planned as 07-03 T1a, ahead of the tracer.
- [Phase 7]: The `"hermes_arg_connector"` `source_engine` literal in `intelligence/inventory/models.py:208,219` is a frozen published dataset value protected by D-06. Decoupling greps must be import-anchored so no executor "cleans up" a published field value.
- [Phase 7]: Inventory does NOT ride along with `_preserve_created_timestamps` / `_preserve_source_watermarks` — those iterate `graph.source_status`, while inventory status lives on the separate `graph.inventory_software_source_status` (`service.py:122`). The CONTEXT claim was wrong; 07-01 T2 verifies empirically and "no such behavior exists" is a valid recorded outcome rather than a manufactured passing test.
- [Phase 7]: Characterization tests reach their driver only through a single named seam (`tests/inventory_harness.py`). Without it the suite is coupled to Hermes being the publisher and would need editing during the inversion — the D-05 failure mode.
- [Phase 7]: Golden rows and key sets are captured as source literals, never derived from `to_dict()` of the object under test. A self-referential assertion moves with the refactor and can never fail.
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
- [Phase 9]: API pivot is mostly wiring — routers already depend on `ProviderSpec` providers, not datasets; no router reads `read_dataset`/`entities/` directly. `agent_queries.py` is the exception.
- [Phase 7/8/9]: Split the system-wide pivot into three phases rather than one. Inverting ownership, redefining the resource contract, and rewiring consumers simultaneously — with no verified live baseline — is the failure mode the waived gate was meant to prevent.

### Roadmap Evolution

- Phase 6 added: Software and OS Inventory Visibility — UI page extracting OS inventory (Azure VMs + Arc-enabled servers) and installed software (Arc Change Tracking & Inventory) from ARG, with OS EOL dates from official vendor sources.
- Phase 7 added: Unified Resource Inventory — inventory becomes an independent domain owning its own acquisition, normalization, retention, status, and publication; generalizes to all resource families including PaaS; consumed by the semantic graph rather than owned by it.
- Phase 6 UAT re-scoped (2026-08-26): entry gate waived; the five residual walkthroughs plus windows #9-#13 now close under Phase 7 exit criteria.
- Phases 8 and 9 added (2026-08-26): operator directed that Hermes pivot to unified inventory for discovery and semantic modelling instead of calling ARG directly, and that web/API pivot to it for the UI. Scoped as Phase 8 (resource identity plane; Hermes drops ARG identity queries) and Phase 9 (API/agent-queries/web pivot) rather than folded into Phase 7.

### Pending Todos

- Write characterization tests pinning current inventory dataset names, row shapes, exact joins, source status, and the failed-refresh retention rule. **Hard precondition for Phase 7 step 1** — sole regression net now that the live-baseline gate is waived.
- Plan Phase 7 (`gsd-plan-phase 7`).
- Deferred to Phase 7 exit: authenticated Azure/ARG/LAW walkthrough, healthy/failed workspace refresh, unknown-OS lifecycle review, exact software/version search, EOL citation review, browser UX/accessibility.
- Triage the pre-existing `web/src/app/compliance/page.test.tsx` failure so full-suite green is a usable signal during Phase 7.
- Configure `APPROVED_SEARCH_API_ENDPOINT` / `APPROVED_SEARCH_API_KEY` if the third EOL source is operationally required.

### Blockers/Concerns

- Phase 7: Proceeding without a verified live inventory baseline. Live-only regressions introduced by the refactor cannot be distinguished from pre-existing Phase 6 defects. Accepted risk; mitigated by characterization tests rather than empirical comparison.
- Phase 8: **Contract losslessness is the pivot's single point of failure.** If `ResourceObservation` cannot carry the full raw property bag and per-family watermark semantics, Hermes must keep its own ARG identity path and the pivot cannot complete. Resolve by auditing Hermes's actual reads into `properties` (normalize.py, network_normalize.py, identity specs) *before* fixing the contract shape.
- Phase 9: Web page impact is unaudited. Pages surfacing resource identity (`services`, `search`, `investigate`, `twin`, `changes`) need review at plan time; the "most pages need no change" expectation rests on route contracts holding.

- Phase 1: Validate exact provider contracts, permissions, pagination, watermarks, retention, and cross-domain identity normalization.
- Phase 2: Select and validate durable workflow and approval expiry semantics.
- Phase 3: Validate remediation API versions, rollback semantics, execution identity, and AI/data boundaries.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v2 | Broad integrations, actions, multi-cloud, retraining, and policy-exemption mutation | Deferred | 2026-08-23 |

## Session Continuity

Last session: 2026-08-25T16:54:47.165Z
Stopped at: Completed 06-09-PLAN.md
Resume file: None
