# Fabric frontend enhancement plan

## Scope and phase boundary

This plan separates the delivered Phase 03.1-compatible evidence correction from
proposed Fabric architecture and UI work. It does not adopt native Fabric IQ,
open Phase 03.7/03.8, change publication authority, enable semantic execution, or
close Phase 4's exact-container, qualified-100k, or canary/rollback evidence gates.
Phase 13 deployed lifecycle acceptance remains a separate prerequisite; a local
implementation is not deployed acceptance evidence.

The implementation surfaces are `web/src/app/connections/fabric/page.tsx` and
`web/src/components/fabric/medallion.tsx`. Shared services, types, Copilot adapters,
RBAC, global navigation, and runtime endpoints are unchanged by this frontend slice.
All endpoint paths below are relative to `/api/v1`.

## Delivered corrections

- The dedicated page and panel share the same five independently loaded section
  responses. An embedded panel still loads its own sections, preserves tab semantics,
  and applies a subscription selector only within its caller's global scope.
- Copilot retains each existing layer/manifest/governance/capability envelope's
  evidence and freshness instead of generating freshness from transport success.
  This per-envelope behavior was already present on this branch and is preserved.
  Empty evidence stays unknown; the page's compatibility aggregate uses partial
  because the existing Copilot freshness union has no unknown member.
- A visible section-evidence summary distinguishes request failure/loading/response
  receipt from reported fresh, aging, stale, or unknown evidence. Response receipt
  means the endpoint answered, not that its datasets or consumers are ready.
- Unknown and disabled readiness are neutral, stale/degraded readiness is warning,
  and failed readiness is critical. The semantic model's reported reason is shown;
  deployment-blocked no longer implies that its definition was validated.
- Data Agent configuration is explicitly not evaluation or query-success evidence.
  The backend companion change returns unknown when configured but unverified,
  disabled when not configured, and keeps `configured` in the existing shape.
- Gold registration/publication is not semantic-model or Data Agent readiness.
  A lineage URL is labeled a reference, not verified native lineage. Maintenance
  failure remains failed rather than contributing to an all-green coverage score.
- Empty ingestion history no longer claims all runs succeeded. A failure's attempts
  are recorded attempts, not an invented retry budget or exhausted-attempt count.

No frontend stage receipts are fabricated. In particular, the companion backend
must not interpret generic ontology projection success/failure as semantic model
deployment success/failure; its existing `{status, reason}` contract is sufficient.

## Current contracts and proposed evolution

| Operator question | Existing contract and current display | Proposed future contract/UI, not delivered |
| --- | --- | --- |
| Which subscription and workspace am I inspecting? | `/connections` supplies onboarded subscriptions; scope and URL selection constrain every medallion request. `/fabric-medallion/capabilities` provides capacity status/name, role and maintenance signals, and a lineage reference. | Read-only workspace/lakehouse/capacity identity inventory with environment, purpose, owning principal, region, isolation boundary and last verified time. Distinguish operational, state, canary and analytical workspaces; do not assume one subscription maps to one workspace. |
| Is capacity usable? | Existing capacity status and paused/throttled callouts; capacity is not inferred from a successful dataset request. | Explicit independently timestamped capacity availability, workload pressure and blocked causes, scoped server-side. No browser capacity resume, scale or role mutation. |
| What arrived in Bronze? | `/fabric-medallion/layers`, `/datasets/{table}`, optional `/datasets/{table}/contract`, and `/ingestion-history`: registered tables, reported counts, clocks, diagnostics and failures. | Source-family cards with acquisition completeness, immutable observation identity, provider time, ingestion time and last-known-good checkpoint; distinguish empty-complete from unavailable or not collected. |
| What is trustworthy in Silver? | Dataset quality/freshness and governance summaries; contract inspection labels deployed-schema validation, producer ownership and dependency graph as not collected. | Normalization/schema versions, typed entity keys, deduplication/reconciliation counts, quarantined records, owner and referential-integrity receipts. Drill down from aggregate to exact scoped source diagnostics. |
| Which Gold product can a consumer use? | Layers, per-dataset status and `/manifest` expose registration/disposition/version. Gold counts do not prove downstream deployment. | Product grain, consumer contract, exact active generation, inputs and generation-pinned reconciliation receipts. Keep Exposure, operational context, ontology projections and analytical products distinct rather than using a generic Gold-ready flag. |
| Is this a native ontology or a Delta projection? | Manifest and dataset lineage describe recorded projection evidence. There is no native ontology readiness field in this contract. | Separate native ontology definition/binding/index/read/query receipts from authoritative application ontology generations and Delta entity/relationship projections. A Delta table or workspace URL must never stand in for a native Fabric ontology item or relationship validation. Native adoption remains gated. |
| Is the semantic model ready? | `capabilities.semantic_readiness.status/reason`; absent deployment proof is unknown, not a failed deployment. Generic ontology attempts belong in ingestion history. | Model item/definition identity, relationship/measure/schema validation, security mode, exact Gold generation binding, deploy/refresh/query receipts and independent blocked causes. Direct Lake compatibility and a published model require different evidence. |
| Is the Data Agent usable? | `capabilities.data_agent_readiness.status/configured`; configured-but-unverified is unknown, not query-ready. | Separate configured, reachable, authorized, model-bound, scoped-query-verified and evaluated stages. Include tool/evaluation version, model/generation identity and latest result, without credentials or unrestricted browser queries. |
| How old is this evidence? | Envelope evidence, dataset observed/ingested/checkpoint fields and optional server `freshness_budget`; metadata-status age is not upstream catch-up proof. | Server-evaluated clock semantics and per-source thresholds with completeness and generation identity on every relevant receipt. Show provider, ingestion, publication and evaluation clocks separately; do not compute one universal freshness from request time. |
| What is publishing, and why is it blocked? | Manifest dispositions and ingestion attempt status/message/recorded count; ontology automation already has separate `/ontology-discovery/status`, `/runs`, `/publications`, `/generations` and evaluation surfaces. | Receipt-backed stages from acquisition through validation, candidate publication, activation and consumer verification. Include exact blocked stage/cause, safe operator guidance and links to already authorized workflows. No synthetic percentage from table count; no joining unrelated generations. |

## Proposed design sequence

1. **Agree on evidence contracts before new dashboards.** Backend owners define
   read-only stage receipts with family, item identity, effective scope, generation,
   observed/evaluated time, availability, freshness, quality and blocked cause.
   Missing and disabled are different from failed; stale is independent of transport
   health. Add optional/versioned fields so existing callers remain supported.
   Keep known statuses and a visible unknown fallback for new vocabulary.
2. **Add workspace and product inventory.** Render workspace/capacity identities and
   Bronze/Silver/Gold products without imposing a universal physical layout. Map
   raw source observations to normalized entities and explicit Gold consumer
   products. Show which isolation and capacity facts were actually verified.
3. **Add generation-pinned lineage and publication drilldowns.** Link product ->
   generation -> source-family diagnostics -> exact publication/evaluation receipts.
   Preserve subscription, connection, environment and all other global constraints,
   selected product, filters, pagination and return location in scoped URL state.
   Do not claim current-generation reconciliation from a historical attempt.
4. **Add independent semantic and Data Agent readiness stages.** Bind them to exact
   model/product/generation receipts. Keep configured, deployed, refreshed, reachable,
   authorized and evaluated separate. A stage not supplied by the server renders
   not verified, not completed. This work needs new contracts and explicit phase
   approval; it is not delivered by relabeling today's capability snapshot.
5. **Only after the native gates open, add native IQ surfaces.** Display native
   ontology item/binding/query evidence separately from application ontology and
   Delta projections. Phase 03.7/03.8 and Phase 13/4 acceptance cannot be bypassed
   by calling a new tab an enhancement or by treating a local test as live proof.

## Interaction and safety requirements

Use independently recoverable sections: a governance failure must not blank valid
dataset evidence, and a capability failure must not turn missing registration into
an empty layer. Continue to use the layer endpoint's table registration as fallback.
Within-layer per-dataset partial recovery is delivered in the next additive
frontend wave: successful dataset cards remain inspectable when another dataset
read fails. Failed table names and errors remain explicit, with loaded/registered
counts and refresh guidance. If all reads fail the layer is unavailable, not
empty. Independent layer-summary counts are not recomputed from successful
requests. No new global request/cache framework or backend contract is required.

Copilot remains read-only and grounded in the displayed effective scope and loaded
envelopes. The shared reads remove duplicate section traffic and page/panel drift,
but do not create an atomic generation snapshot across endpoints. Future generation
contracts must prove alignment before Copilot correlates receipts. The current
adapter collapses unknown evidence to its existing unavailable/partial vocabulary;
it is not a full lifecycle-state transport. Extending that vocabulary requires a
separate coordinated shared-adapter/types change, not fabricated freshness values.

Preserve server-side scope authorization and distinct read/operate/approve roles.
Any future action uses the existing authorized/audited workflow, never a new browser
publisher or direct Fabric credential. No secrets, service principal keys, tokens,
connection strings or provider administration credentials belong in page payloads,
URLs, telemetry or Copilot context.

Keep semantic HTML regions/headings, text status labels (not color alone), keyboard
navigation, contract-inspection focus restoration and embedded tab relationships.
Reuse the existing page cards, filters, pagination and evidence components. Avoid
adding native links or claims unless the server supplies and authorizes them.

## Acceptance and handoff

The delivered regressions cover successful requests with absent/stale evidence,
independent endpoint failure, distinct unknown/disabled/stale/degraded/failed tones,
single section reads per refresh, scope narrowing/refusal, standalone embedding,
and the existing scope-change race/contract-inspection behavior.

Future work needs contract fixtures for contradictory stages, missing timestamps,
mixed generations, incomplete lineage, disabled features, unauthorized scope and
one failed source among healthy peers. Native/model/query acceptance additionally
requires approved live evidence; mocked UI fixtures cannot close those gates.

The first frontend wave required no new endpoint fields. The companion backend
readiness correction is needed for truthful semantic status; this frontend does not
independently verify a model or Data Agent. No cloud mutation, deployment, commit,
push or pull request is part of this worktree handoff.

## Next additive wave: recorded source evidence

The product/backend owners verified that no scoped serving-product or model receipt
recorder exists at this baseline. This wave therefore does not implement product
generation cards or inferred model qualification. The agreed additive contracts are:

- `/fabric-medallion/datasets/{table}` optionally supplies `recorded_evidence` with
  `evidence_mode=recorded_metadata`, `generation_kind=source_partition`, and scoped
  source records. Each has recorded/provider status, metadata observation/freshness,
  partition identity, last attempted generation/time/safe reason code, distinct
  last-good retention generation/time/reason, and a recorded lineage reference.
- `/fabric-medallion/capabilities` optionally supplies `readiness_evidence` for scoped
  projection publication, native ontology, semantic definition validation, semantic
  publication and semantic query qualification. Every current stage is explicitly
  unknown/not-recorded, with no attempt or last-good receipt; compatibility
  capabilities do not override that missing proof.

Dataset cards expose paginated source-partition evidence through keyboard-accessible
native disclosure controls, using the already loaded, scoped dataset response.
Generations remain per partition, never aggregated into a product pointer. Null
last-good evidence remains unknown, never borrowed from a newer failed attempt.
Lineage references remain text, not arbitrary navigation URLs or a claimed DAG.
Legacy responses render missing receipt evidence explicitly. No browser credentials,
publication actions, cloud probes, or gate changes are introduced.

Copilot continues to cite the existing page section envelopes and readiness fields.
These source-partition details are not silently promoted into serving-product
evidence or appended to its closed snapshot contract; that would require a separate
coordinated adapter change and generation-binding evidence.
