---
phase: 10-fabric-medallion-capability-expansion
reviewed: 2026-09-03T14:51:59Z
depth: deep
files_reviewed: 33
files_reviewed_list:
  - src/api/routers/vulnerability.py
  - src/api/runtime.py
  - src/api/dependencies.py
  - src/intelligence/vulnerability/service.py
  - src/intelligence/vulnerability/models.py
  - src/intelligence/vulnerability/connector.py
  - src/intelligence/vulnerability/enrichment_cache.py
  - src/onboarding/query_catalog.py
  - src/onboarding/defender_normalize.py
  - src/onboarding/graph_normalize.py
  - src/onboarding/ingestion_service.py
  - src/onboarding/inventory_read_adapter.py
  - src/onboarding/discovery_source.py
  - src/fabric/dataset_mapper.py
  - src/fabric/schema_registry.py
  - src/fabric_pipelines/vulnerability_pipeline.py
  - src/ontology/relationship_builder.py
  - src/ontology/graph_queries.py
  - src/intelligence/remediation/defender_correlation.py
  - src/operations/tools.py
  - src/semantic/live_operations.py
  - src/semantic/live_provider.py
  - web/src/lib/services.ts
  - web/src/lib/types.ts
  - tests/test_api_vulnerability_router.py
  - tests/test_api_runtime_vulnerability_correlation.py
  - tests/test_vulnerability_intelligence.py
  - tests/test_vulnerability_connectors.py
  - tests/test_vulnerability_pipeline.py
  - tests/test_container_image_exposure.py
  - tests/test_defender_remediation_correlation.py
  - tests/test_defender_remediation_correlation_hardening.py
  - tests/test_incremental_sync.py
findings:
  critical: 10
  warning: 3
  info: 0
  total: 13
severity_counts:
  blocker: 10
  warning: 3
status: issues_found
---

# Phase 10: Exposure Capability Deep Review

**Reviewed:** 2026-09-03T14:51:59Z  
**Depth:** deep  
**Files reviewed:** 33  
**Status:** issues_found

## Executive assessment

The Exposure implementation has the components of a credible architecture—versioned ARG acquisition, normalized source-specific entities, Bronze/Silver datasets, a vulnerability intelligence service, scoped APIs, ontology projection, remediation correlation, and web/Copilot consumers—but it does not yet provide one authoritative end-to-end exposure view.

The principal architectural defect is split truth. Subscription-scoped aggregate routes switch to a request-time provider containing Azure Update Manager (AUM) rows only, while Defender routes use the persisted snapshot. A user can therefore see Defender findings in posture views but not in summary, priority, SLA, remediation, or Copilot calculations for the same scope. The live AUM path also does not correctly normalize ARG's list-shaped classifications.

Persistence is generation-based, but acquisition failures are converted to rows and the generation is still published. This allows a transient failure to replace a valid current snapshot with an empty source family instead of serving last-known-good evidence as stale. Temporal reconciliation has two further correctness defects: any historical install suppresses a current missing assessment, and patch publication time is used as detection time for SLA aging.

Container-image evidence is retained in a separate Silver/API projection, but the Fabric ontology rebuild drops the image-to-registry relationship. As a result, ontology traversal, business impact, remediation, and Copilot do not have equivalent semantics for image CVEs. Freshness and provenance are likewise too coarse to support defensible operations.

This capability should not be treated as an authoritative exposure or SLA system until the BLOCKER findings below are resolved.

## Narrative Findings (AI reviewer)

### Critical issues

#### CR-01 [BLOCKER]: Subscription-scoped aggregate routes discard Defender findings

**Files:** `src/api/routers/vulnerability.py:20-34`, `src/semantic/live_operations.py:120-171`

**Issue:** `_service()` selects the hybrid provider whenever a subscription scope is present. That provider queries only `PatchAssessmentResources` and `PatchInstallationResources` and builds `silver_patch_findings`; it never loads Defender subassessments, assessments, alerts, attack paths, secure score, or container-image evidence. The separate `_defender_service()` comment explicitly acknowledges this limitation, but only Defender-specific routes use that provider.

**Affected behavior/data:** Summary, exposures, asset exposures, patch priorities, CVE details, SLA, risk-remediation views, and Copilot can omit Defender-only CVEs and disagree with Defender posture for the identical subscription. Source precedence changes merely because a caller supplies scope.

**Fix:** Build one scope-aware service that overlays fresh live AUM observations onto the persisted scoped snapshot rather than replacing it. Merge Defender and image evidence before all aggregate calculations, and expose per-source status when one side is unavailable. Add parity tests asserting that scoped aggregate counts retain Defender-only findings.

#### CR-02 [BLOCKER]: Live AUM severity does not conform to the ARG patch contract

**File:** `src/semantic/live_operations.py:80-108`

**Issue:** Live normalization selects `properties.classification`, then `properties.classifications`, then `properties.severity`. ARG patch detail rows commonly expose `classifications` as an array and `msrcSeverity` as the scalar severity. `_first()` stringifies the array (for example, `['SecurityUpdates']`) and `msrcSeverity` is never considered.

**Affected behavior/data:** Subscription-scoped AUM findings can have unrecognized severities. Critical/high counts, ranking, SLA policy selection, and Copilot prioritization are consequently understated or fall back to defaults.

**Fix:** Share one normalization function with persisted onboarding. Normalize list-valued classifications deterministically and use `msrcSeverity` for severity, with validated enum fallback to `Unknown`. Add real ARG-shaped fixtures containing both `classifications` arrays and `msrcSeverity`.

#### CR-03 [BLOCKER]: A failed source query can publish a false-clear snapshot

**Files:** `src/onboarding/discovery_source.py:47-68`, `src/onboarding/graph_normalize.py:158-193`, `src/onboarding/ingestion_service.py:123-143`

**Issue:** Discovery converts exceptions and timeouts into synthetic failed rows. Defender normalizers discard those rows, while patch-family normalization processes them without first rejecting failed payloads. The ingestion service nevertheless writes and publishes the generation as completed.

**Affected behavior/data:** A temporary ARG/Defender outage can replace previously valid findings with an empty source family, making exposures disappear and posture appear remediated. Patch failures can additionally produce malformed entities with empty identifiers. This is silent data loss at the active-snapshot boundary.

**Fix:** Treat each source family as a checkpointed unit. Never project failure rows as domain entities. On failure, carry forward the prior successful partition with `stale/degraded` status, and publish a new active generation only when required families meet an explicit completeness policy. Surface partial status through API evidence and telemetry.

#### CR-04 [BLOCKER]: Historical installations suppress newer missing assessments

**File:** `src/api/runtime.py:809-835,929-935`

**Issue:** Runtime collects every installed `(target, KB)` pair and then drops every matching missing row. It does not compare assessment and installation timestamps, select the latest event, or account for a vulnerability being reintroduced.

**Affected behavior/data:** An old installation can erase a newer missing assessment, producing a false remediated state and excluding a genuinely exposed server from counts, SLA, remediation, and Copilot.

**Fix:** Reconcile by canonical target/KB using event time and source sequence. An install may close a missing assessment only when its successful completion time is later than the assessment's observation time. Preserve both observations and derive current state from the latest valid transition.

#### CR-05 [BLOCKER]: SLA age starts at patch publication, not first detection

**Files:** `src/api/runtime.py:820-834`, `src/intelligence/vulnerability/service.py:1275-1302`

**Issue:** AUM `published_at` is assigned to `first_observed_at`, and SLA calculations use that value for `days_open`, `due_at`, and `overdue`. Patch publication is vulnerability metadata, not evidence of when this tenant first became exposed.

**Affected behavior/data:** A newly detected missing patch may immediately appear months or years overdue. SLA reports, executive metrics, and remediation queues are materially misleading.

**Fix:** Persist a tenant-scoped `first_detected_at` derived from the first successful observation of the target/CVE or target/KB state. Keep patch publication in a separate field. Do not assign SLA aging when first detection is unknown.

#### CR-06 [BLOCKER]: Container-image exposure is disconnected from the persisted ontology

**Files:** `src/onboarding/graph_normalize.py:226-238`, `src/fabric/dataset_mapper.py:364-369`, `src/ontology/relationship_builder.py:358-456`

**Issue:** Initial normalization creates image-to-registry relationships, but Fabric mapping rebuilds relationships from entities. `RelationshipBuilder` has no projection for `ContainerImageExposure`, so those relationships disappear after persistence.

**Affected behavior/data:** API rows can show vulnerable images while ontology/graph queries cannot traverse image → registry → deployment/application/business service. Dependency impact, remediation correlation, and Copilot therefore miss container-image risk.

**Fix:** Add stable `ContainerImage`/`ContainerImageExposure` ontology projection and image-to-registry plus image-to-workload/deployment relationships. Include CVE observation edges rather than only aggregate CVE arrays. Verify relationship round-trips through Fabric.

#### CR-07 [BLOCKER]: Scoped CVE and KB catalog routes expose global snapshot membership

**Files:** `src/api/routers/vulnerability.py:311-355,409-427`, `src/intelligence/vulnerability/service.py:175-193`

**Issue:** `/cves` iterates the service-wide CVE map, and `cve_detail()` returns metadata even when scoped findings are empty. `/kbs` and `/kbs/{id}` similarly read global articles without establishing that the identifier is visible in the caller's scope. Although CVE/KB metadata is public, membership in this deployment's populated catalog is environment-derived.

**Affected behavior/security:** A principal limited to one subscription can enumerate CVEs and KBs observed or enriched because of other subscriptions. Empty scoped findings do not prevent this cross-scope side channel.

**Fix:** Separate a clearly public external catalog from tenant-observed catalog membership. For environment endpoints, derive visible identifiers from scoped findings before returning details. If unrestricted NVD lookup remains supported, return it through an explicitly external-catalog contract that cannot reveal whether another tenant observed the item.

#### CR-08 [BLOCKER]: Remediation evidence freshness is pinned to 2026-08-18

**Files:** `src/intelligence/remediation/defender_correlation.py:511-523`, `tests/test_defender_remediation_correlation_hardening.py:90-115`

**Issue:** `_citation_freshness()` compares evidence against a hard-coded date. Tests also construct data around that date, masking the production defect. At review time (2026-09-03), future-to-the-constant observations produce a negative age and cannot become stale under this check.

**Affected behavior/data:** Defender evidence after 2026-08-18 can remain classified as fresh indefinitely. Confidence and remediation-case status are not defensible.

**Fix:** Inject an `as_of` clock (defaulting to `datetime.now(UTC)`) and use it consistently in freshness classification. Freeze the clock only in tests and add boundary cases for now, threshold, threshold+1, and future timestamps.

#### CR-09 [BLOCKER]: Web Exposure collections silently stop at the first 100 rows

**Files:** `src/api/dependencies.py:299-300`, `src/api/routers/vulnerability.py:78-83,107-112,350-356,413-417`, `web/src/lib/services.ts:913-980`

**Issue:** Collection routes default to `limit=100` and return pagination metadata, but browser service methods expose neither `offset`/`limit` nor cursor iteration. Their return types are plain arrays, so pagination metadata is not available to page components.

**Affected behavior/data:** Large estates show incomplete exposure, asset, priority, Defender, image, CVE, and KB lists with no indication that rows were omitted. Users can make remediation decisions from a partial inventory.

**Fix:** Preserve the response envelope's pagination metadata in the TypeScript contract and implement explicit paging or bounded auto-pagination. Show total/loaded counts and continuation state in the UI. Add a test with more than 100 rows.

#### CR-10 [BLOCKER]: One live connection failure aborts a multi-subscription query

**File:** `src/semantic/live_provider.py:146-167`

**Issue:** `ConnectionScopedLiveResourceProvider.query()` loops over matching connections without per-connection exception isolation. Any failed reader prevents all successful subscriptions from returning, and there is no partial-result status.

**Affected behavior/data:** A single unavailable subscription can make an entire multi-subscription Exposure request fail, even when other subscriptions are healthy.

**Fix:** Isolate each connection, return successful rows plus structured per-connection failures, and let the API enforce a documented partial-result policy. Emit warnings and completeness counts; fail the whole request only when no authorized connection succeeds or policy requires atomicity.

### Warnings

#### WR-01 [WARNING]: Freshness and provenance collapse independent source families

**Files:** `src/api/runtime.py:450-475`, `src/api/routers/vulnerability.py:37-43`

**Issue:** Snapshot freshness is the maximum `startedAt` across connections, then every aggregate response is labeled `vulnerability_projection`. A fresh connection/source can mask stale or failed peers, and AUM, Defender, MSRC, NVD, EPSS, and KEV facts are not independently attributable in the response.

**Risk:** Operators cannot determine which source supports a result, whether coverage is complete, or which observation is stale.

**Fix:** Return source- and connection-specific evidence (`observed_at`, `ingested_at`, status, run ID, provenance IDs, coverage) and compute aggregate freshness conservatively from required contributing sources.

#### WR-02 [WARNING]: Runtime enrichment can return incomplete CVE coverage without a durable quality signal

**Files:** `src/api/runtime.py:608-700,937-1054`, `src/intelligence/vulnerability/connector.py:158-221`

**Issue:** KB/CVE enrichment occurs during service construction and is cached only in process memory. NVD rate limiting breaks the remaining batch, while endpoint evidence still describes the result as the generic vulnerability projection.

**Risk:** Identical snapshots can produce different CVE expansion after restart, rate limiting, or external outages. Missing enrichments are hard to distinguish from “no CVE exists,” undermining reproducibility.

**Fix:** Materialize versioned enrichment facts in Fabric with per-item success/error status and source timestamps. Serve the latest governed snapshot and refresh asynchronously; report unresolved and stale enrichment counts.

#### WR-03 [WARNING]: The declared vulnerability pipeline output is outside the production contract

**Files:** `src/fabric_pipelines/vulnerability_pipeline.py:18-19,42-72`, `src/fabric/schema_registry.py:1-512`

**Issue:** The pipeline declares `assessment_vulnerability_findings`, but the output has no registered schema and no production persistence/consumer path in the reviewed runtime. Runtime rebuilds exposure independently from Silver inputs.

**Risk:** Two implementations can drift while pipeline tests remain green, giving false confidence that the table drives production behavior.

**Fix:** Either register, persist, and consume the output as the governed Gold read model, or remove the unused pipeline and test the actual runtime path. Keep one exposure derivation contract.

## Source-of-truth, merge, deduplication, provenance, and freshness

| Evidence family | Upstream authority | Normalized/persisted representation | Current merge semantics | Review assessment |
|---|---|---|---|---|
| AUM missing patches | ARG `PatchAssessmentResources` detail rows (`query_catalog.py:130-143`) | Patch detail entities and `silver_patch_findings` | KBs are expanded through MSRC; AUM becomes the primary finding where it shares canonical `(server_id, cve_id)` with Defender | Appropriate authority for current patch-assessment state, but live severity, failed-run retention, and temporal reconciliation are incorrect. |
| AUM installations | ARG `PatchInstallationResources` (`query_catalog.py:145-151`) | Installed patch rows in `silver_patch_findings` | Any matching target/KB installation removes the missing row (`runtime.py:809-819,929-935`) | Installation history is evidence of an event, not unconditional current-state authority. Event ordering is required. |
| Defender posture | ARG top-level `microsoft.security/assessments` (`query_catalog.py:73-86`) | `silver_defender_assessments` | Kept as a separate posture projection and excluded from aggregate vulnerability findings | Correctly distinct from CVE findings, but split provider selection makes aggregate and posture views inconsistent. |
| Defender CVE findings | ARG assessment subassessments (`query_catalog.py:87-96`) | `silver_defender_findings`, one normalized CVE observation per target | Deduped with AUM by canonical target/CVE; AUM is primary, strongest severity and evidence/source/recommendation IDs are unioned, latest Defender fields retained | The key is reasonable, but source precedence is hidden and no bitemporal/current-state policy protects against stale contradictions. |
| Container image CVEs | Defender top-level ACR image assessments | `silver_container_image_exposure`, currently aggregated per image | Remain separate from `VulnerabilityFinding`; not merged into aggregate exposure or ontology relationships | Preserves API display but loses cross-domain semantics and remediation/business impact. |
| CVE/KB intelligence | MSRC KB mapping and NVD CVE/CVSS | Runtime objects and in-memory cache | Enriched during runtime; unresolved KBs fall back to `KB-<id>` pseudo-CVEs | Useful fallback, but not durable or reproducible and partial external failures are not explicit. |
| Exploit likelihood | EPSS and CISA KEV | Runtime enrichment inputs | Adds prioritization signals to aggregate CVEs | Provenance/freshness is too coarse; stale fallback is not distinguishable in the endpoint evidence. |

### Deduplication details

- The principal AUM/Defender convergence key is canonical `(server_id, cve_id)`.
- One missing KB may expand into multiple CVEs via MSRC; a KB with no mapping becomes a pseudo identifier.
- Merged severity takes the strongest value; evidence IDs, sources, and recommendations are unioned.
- Earliest observation is retained as `first_observed_at`, but AUM currently supplies publication time, so the resulting minimum is semantically invalid for tenant aging.
- Defender image evidence is aggregated by image and CVE arrays rather than represented as the same observation model.
- Installed/missing deduplication uses membership only, not event time, generation, result status, or source confidence.

### Provenance and freshness conclusion

The current service can say that a projection was built, but cannot reliably answer “which source and run proved this target was exposed at this time?” Evidence is aggregated at service level, freshness uses the newest connection timestamp, and external enrichment is runtime-local. Source status partially exists for Defender but is not a complete capability-wide quality contract. This is insufficient for auditable SLA, remediation, or executive reporting.

## End-to-end contract trace

1. **Upstream query**
   - `src/onboarding/query_catalog.py:60-151` defines separate Defender assessment/subassessment and AUM assessment/installation queries.
   - `src/onboarding/inventory_read_adapter.py` performs ARG reads and page assembly; `src/onboarding/discovery_source.py:47-68` converts acquisition failures into row-shaped results.

2. **Normalization**
   - `src/onboarding/graph_normalize.py:158-238` turns patch and image payloads into graph entities/relationships.
   - `src/onboarding/defender_normalize.py:26-239,511-622` separates posture, CVE subassessments, and image exposure.
   - Contract break: failure rows are not consistently excluded, and live AUM uses a different normalizer.

3. **Bronze/Silver mapping and schema**
   - `src/fabric/dataset_mapper.py:305-538,769-873` maps governed entities into source-specific Silver tables.
   - `src/fabric/schema_registry.py:129-274,490-512` registers patch, Defender, image, and source-status schemas.
   - Contract break: the ontology relationship rebuild loses image edges, and the pipeline's declared Gold-like output is not registered.

4. **API runtime/service**
   - `src/api/runtime.py:782-1054` assembles AUM, Defender, image, source status, and external enrichment into `VulnerabilityIntelligenceService`.
   - `src/intelligence/vulnerability/service.py:175-500,511-973,1275-1302` scopes details, computes aggregates/priorities, and derives SLA.
   - Contract break: scoped hybrid selection bypasses most of this persisted evidence; temporal and first-detection semantics are wrong.

5. **Endpoint and web contract**
   - `src/api/routers/vulnerability.py:20-427` applies route-level provider choice, filtering, scope, and pagination.
   - `web/src/lib/services.ts:913-980` and `web/src/lib/types.ts:474-685,795-860` expose browser contracts.
   - Contract break: browser methods erase pagination, and collection/catalog scope semantics are inconsistent.

6. **Ontology, remediation, and Copilot**
   - `src/ontology/relationship_builder.py:358-456` and `src/ontology/graph_queries.py` provide graph relationships and traversal.
   - `src/intelligence/remediation/defender_correlation.py:119-228,326-523` builds remediation cases from Defender evidence.
   - `src/operations/tools.py:482-640,739-837` exposes Exposure to Copilot.
   - Contract break: container-image paths disappear, remediation freshness uses a fixed clock, and the Copilot business-service filter reads a field aggregate rows do not contain (`tools.py:482-493`; `models.py:252-275`), so a supplied filter returns an empty result rather than scoped exposure.

## Prioritized capability enhancement recommendations

### 1. Establish a unified scoped Exposure read model

**Value / effort / risk:** Very high / medium-high / medium  
**Action:** Make one governed, scope-aware read model the source for summary, details, Defender posture, images, SLA, remediation, web, and Copilot. Overlay live AUM deltas onto the persisted snapshot without replacing Defender evidence.

**Cross-layer surfaces:** `query_catalog.py`, all vulnerability normalizers, `dataset_mapper.py`, `schema_registry.py`, `runtime.py`, `service.py`, `vulnerability.py`, web service/types, and Copilot tools.

**Success metric:** For every scope, aggregate counts reconcile to source-family details; a fixture containing AUM-only, Defender-only, shared, and image findings produces identical identifiers/counts across API, web, remediation, and Copilot.

**Ontology change necessary:** **No** for read-model unification itself; use existing vulnerability relationships while recommendation 4 adds missing image semantics.

### 2. Add source-partition checkpoints and a data-quality/freshness contract

**Value / effort / risk:** Very high / medium / low-medium  
**Action:** Retain last-known-good partitions per connection/source family, publish explicit complete/partial/stale states, and separate event time, ingestion time, run time, and enrichment time.

**Cross-layer surfaces:** ARG read adapter, `discovery_source.py`, `ingestion_service.py`, generation manifests, source-status Silver schema, runtime evidence, API envelopes, dashboards, and telemetry/alerts.

**Success metric:** Injecting a failure in any one family never false-clears prior findings; responses identify the failed family and age; alerts fire within one ingestion cycle.

**Ontology change necessary:** **No.** Quality/run metadata belongs in governed metadata tables and evidence envelopes, not domain edges.

### 3. Introduce temporal exposure-state reconciliation

**Value / effort / risk:** Very high / high / medium-high  
**Action:** Preserve immutable missing, installed, resolved, and reintroduced observations; derive current state by event time and generation. Store true first detection separately from publication and last assessment.

**Cross-layer surfaces:** patch/Defender normalization, Silver schemas, dataset mapper, runtime merge, vulnerability models/service, SLA/remediation calculations, API types, and history views.

**Success metric:** A temporal test matrix (missing→installed, installed→missing, stale install, reintroduction, out-of-order arrival) always yields the correct current state and SLA clock; no publication date enters `first_detected_at`.

**Ontology change necessary:** **Yes.** Add a first-class exposure/assessment observation (or equivalent state-event node) linked to target, CVE/KB, source, and remediation transition.

### 4. Make container-image exposure first-class and deployment-aware

**Value / effort / risk:** High / high / medium  
**Action:** Project image/digest-level CVE observations and connect registry images to deployed workloads, applications, business services, and remediation ownership. Include image findings in aggregate prioritization without conflating registries with servers.

**Cross-layer surfaces:** Defender image normalizer, Silver schema/mapper, ontology relationship builder and graph queries, vulnerability service, remediation correlation, API/web views, and Copilot tools.

**Success metric:** Every displayed vulnerable image can be traversed from CVE → digest → registry → deployed workload → application/business service, with no relationship loss after a Fabric round-trip.

**Ontology change necessary:** **Yes.** Add stable image/digest entities and explicit vulnerability, registry, deployment, and service relationships.

### 5. Deliver a scalable, completeness-aware query contract

**Value / effort / risk:** High / medium / low  
**Action:** Move filtering/sorting/paging onto a persisted Gold Exposure read model; use cursor pagination; preserve totals and completeness in web/Copilot contracts; execute enrichment asynchronously.

**Cross-layer surfaces:** vulnerability pipeline and schema registry, Fabric persistence, service query interface, API pagination, TypeScript envelope/types, Exposure pages, Copilot bounding logic, and enrichment jobs.

**Success metric:** A 100k-finding benchmark returns deterministic first-page results within the agreed SLO, all pages enumerate exactly the reported total with no duplicates, and Copilot explicitly reports the represented/total row count.

**Ontology change necessary:** **No.** This is a query/read-model capability; it should consume, not reshape, ontology semantics.

## Test and observability gaps

### Missing or inadequate tests

- No test proves subscription-scoped aggregate parity when Defender-only and AUM-only evidence coexist.
- No live-path fixture uses actual ARG `classifications` arrays plus `msrcSeverity`.
- No test verifies last-known-good retention when AUM, Defender subassessments, or image acquisition fails.
- No temporal test compares installation completion against assessment observation or covers vulnerability reintroduction.
- SLA tests do not distinguish patch publication, first detection, last observation, and remediation timestamps.
- Container tests validate API projection but not Fabric ontology relationship round-trip or workload/business-service traversal.
- Browser tests do not use more than 100 rows or verify continuation and totals.
- Scope tests validate finding arrays but not CVE/KB catalog membership isolation.
- Remediation freshness tests freeze data around the production hard-coded date instead of injecting a clock.
- Copilot tests do not exercise `business_service` against aggregate exposure rows.
- Multi-connection live tests do not inject one successful and one failed connection.
- Enrichment tests do not assert a visible partial/stale signal after NVD 429, MSRC failure, stale KEV fallback, or process restart.

### Missing observability

- Per connection/source family: last attempted, last successful, event watermark, row count, failure reason, carry-forward age, and completeness state.
- Ingestion invariants: sudden zero-row/large-drop alerts, malformed identifier counts, duplicate canonical keys, unresolved KB-to-CVE mappings, and cross-generation churn.
- Merge metrics: AUM-only, Defender-only, merged, contradictory, suppressed-by-install, and reintroduced findings.
- Enrichment metrics: request volume, latency, cache hit/miss, rate limits, unresolved IDs, fallback age, and partial batch count.
- API metrics: total versus returned rows, provider selected, partial-connection count, source ages, and scope dimensions.
- Cross-layer reconciliation: periodic checks that Silver, ontology, API aggregate, remediation, web totals, and Copilot totals agree for the same generation/scope.

## Verification performed

The primary Exposure test set was run against the current working tree:

`uv run pytest -q tests/test_api_vulnerability_router.py tests/test_api_runtime_vulnerability_correlation.py tests/test_vulnerability_intelligence.py tests/test_vulnerability_connectors.py tests/test_vulnerability_pipeline.py tests/test_container_image_exposure.py tests/test_defender_remediation_correlation.py tests/test_incremental_sync.py`

Result: **143 passed**. Passing tests do not cover the failure and contract cases listed above.

---

_Reviewed: 2026-09-03T14:51:59Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: deep_
