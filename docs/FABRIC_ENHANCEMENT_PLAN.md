# Fabric AIOps enhancement plan

**Reviewed:** 2026-10-19. **State:** design and bounded correctness implementation;
not a deployment approval or completion of Phase 03.7/03.8.

## 1. Findings and evidence boundaries

The persistence, temporal Exposure products, scoped APIs, and governed ontology
lifecycle are substantial foundations. The main problem is not a missing storage
technology: it is coupling between products, ambiguous readiness evidence, and
drift between configuration, documentation, deployed artifacts, and consumers.

| Finding | Repository or owner evidence | Consequence |
|---|---|---|
| Control-plane separation already exists | Unified Deployment's corrected-target handoff: distinct state, command, dispatch, publication and source/ops workspace/item bindings | Do not treat these workspaces as Bronze/Silver/Gold or consolidate away capability isolation |
| Historical defaults are not the current environment | `fabric.config.deploy.yaml` still names the historical tenant/workspace; deployment owner reports a corrected effective configuration | Resolve effective configuration and exact target before any deployment; do not deploy baked defaults blindly |
| Medallion classification is prefix-based | `fabric_medallion.py::_layer_for_table`; schema registry and producer determine actual semantics | Naming alone cannot establish lineage, quality, ownership or whether a table is in use |
| Publication does too much in one lifecycle | `FabricSyncService`; existing Phase 03.7 context and plans | Unrelated products contend for a writer and repeat projection work; reuse planned domain-product boundaries |
| Readiness conflates different artifacts | `_semantic_readiness` accepts a generic successful publication attempt; Data Agent readiness uses configuration | Neither proves a queryable semantic model, native Ontology, or reachable Data Agent |
| Frontend transport success can become data freshness | `/connections/fabric` supplies `fresh` when layer HTTP data exists; the page and panel repeat common reads | Operators and Copilot can receive overstated freshness; eliminate invented health before adding dashboards |
| Analytical bootstrap is overly physical | Historical exported model contains 472 tables; current builder explicitly returns a non-deployable scaffold | Do not regenerate a model by enumerating every Lakehouse table |
| Existing Gold names can obscure analytical grain | `exposure_projection.py` generates fact IDs per source state/generation and generic dimension/facet rows | Facts, unique exposures, resources and facet counts are not interchangeable; a generic facet dictionary is not a conformed star dimension |
| Native diagnostics have advanced beyond the old absence report | Current STATE records a migrated native Ontology and successful Application count through native MCP and independent SQL | Native item existence/query diagnostics are not proof of qualified unattended publication or production cutover |

The 472-table count is a historical survey, not a fresh inventory of the corrected
environment. The exported-model architecture document is likewise an adoption
baseline, not current live model inspection. A large number of typed ontology
tables is not, by itself, evidence of redundancy.

The original September publication test proved Delta writes. It did not prove
native Ontology definition publication or semantic-model deployment. Keep those
claims separate in logs, APIs, UI, tests and release reports.

## 2. Workspace and environment design

Use three independent concepts:

1. **Environment boundary:** development, validation/test and production. Promote
   versioned definitions/configuration between environments; never copy production
   data or access grants implicitly.
2. **Capability boundary:** source acquisition, coordinator state, command intake,
   dispatch and authoritative publication. Preserve existing distinct roots and
   identities, including their fixed-template and no-override protections.
3. **Data layer:** Bronze, Silver, Gold, ontology projections and operational
   metadata. These are data contracts, not a required workspace-per-layer design.

**Near term:** retain the existing source/ops Lakehouse and layer-prefixed tables.
Keep native Ontology and its bound source tables on a supported, verified path.
Do not move existing items simply to improve naming. Record effective tenant,
subscription, workspace, item, region, capacity, identity and config digest in
deployment receipts, keeping credentials out of artifacts and browsers.

**Later, only if justified:** isolate ingestion and serving workspaces where access
or workload measurements require it. Prefer supported shortcuts over duplicate
physical copies when they preserve security and source/generation semantics.
Validate cross-workspace native bindings, Direct Lake access, lineage and
rollback first. Schema-enabled Lakehouse migration needs explicit compatibility
work: current Terraform documents the flat-table-listing limitation. Do not
replace the existing Lakehouse to enable schemas in place.

Capacity assignment is a separate cost/performance decision. Do not create more
capacities by default. Measure existing capacity contention and reconcile scheduled
publication with planned pause windows before proposing a resize or relocation.

**Target layout decision:** Microsoft's current medallion guidance recommends
separate Lakehouses/warehouses for the layers. A future migration candidate is
an engineering workspace containing source landing/Bronze and conformed Silver,
plus a serving workspace containing Gold and analytical items, with the existing
state/command/dispatch/publication capability boundaries retained separately.
Development, validation and production use independent environment bindings.
This is an explicit proposed target, not the current physical layout.

The near-term single-Lakehouse decision is a deliberate compatibility exception,
not a claim that prefixes provide security isolation. Before adopting the target,
prove dual-read parity, supported shortcuts, source retention, effective access,
native binding compatibility and old/new/old rollback on a non-production copy.
Retain aliases through a measured consumer cutover; move no existing item or data
until that reviewed migration is executable. Additional Lakehouses/workspaces
must have an access or lifecycle purpose, not merely reproduce the medallion
labels in the workspace list.

## 3. Medallion and data-product contracts

ARG and Log Analytics are **sources**, not Bronze tables. Versioned source
generations under `Files/` are the landing/replay boundary. Those generations can
already contain normalized entities; do not advertise them as pristine provider
payloads unless actual capture fidelity establishes that.

| Family | Purpose and grain | Design requirements |
|---|---|---|
| Landing | Provider/source-family observations and acquisition receipts | Immutable source-run identity, observation/collection times, scope, completeness and replay provenance |
| Bronze | Source-aligned typed observations/snapshots | Preserve source provenance; define append, current-snapshot and deletion semantics per table, not globally |
| Silver | Conformed resource, software, workload, vulnerability and relationship products | Deterministic scoped identity, deduplication, source priority, provider time, temporal validity and explicit unknowns |
| Gold | API/analytics-ready facts, summaries and evidence | Document grain, additive/nonadditive measures, target kinds, generation boundaries and serving/query SLOs |
| Ontology | Typed entity/relationship projections and native bindings | Stable entity/edge identity, endpoint validation, provenance, lifecycle and reviewed taxonomy |
| Metadata/control | Source status, quality, manifests, attempts and audit | Distinguish latest attempt from last successful generation; retain failure and degraded evidence |

Reuse `schema_registry.py`, inventory-owned `fabric_contracts.py`, existing
manifests and source status; do not create a second schema authority. Extend their
contracts where needed with product owner, semantic layer, grain, consumers,
keys, freshness objective, retention, schema version and deprecation state.
Non-prefixed inventory/topology tables must have an explicit family and owner,
not be renamed or hidden merely to make the medallion diagram tidy.

Implement the existing Phase 03.7 tracer first after its gate passes: publish the
five-table inventory product without invoking unrelated ontology/Exposure/
incident projectors. A product manifest binds schema/content hashes, row counts,
source generations, quality, lineage and its atomic group. Preserve authoritative
CAS/fences, retained generations and audited rollback. Independent products may
advance separately; consumers needing several products must pin a compatible
generation vector rather than join whichever pointers happen to be newest.

Deletion requires a fresh target-specific inventory, source/code and runtime
consumer evidence, a named owner, a retained recovery path and explicit approval.
Zero rows or an old Delta commit are insufficient: content-identical dedup can
validly skip a write. First classify retain, compatibility alias, deprecate or
investigate; observe use before removing aliases. This plan deletes nothing.

## 4. Publication and orchestration

Use Fabric Data Factory for scheduling, dependencies and visible run orchestration
where supported. Reuse the deployed trigger/poll contract and governed fixed Job
templates. Data Factory is not a substitute for the deterministic Python
projectors, identity isolation, writer fencing or durable state.

The preferred compute boundary is a finite durable publisher worker, not a
multi-hour API thread. The API should authenticate/enqueue and expose bounded
status; lifecycle history must survive revision/replica changes. Do not add a
parallel ungoverned Job-start endpoint or let a request select image/command/root.
Move work only through the already planned lifecycle/publication separation.

Report independent stages: acquisition, product validation/materialization,
registration, ontology projection, native definition publication, semantic model
publication/binding, and consumer verification. A stage can be disabled, blocked,
failed, unknown or succeeded without converting unrelated stages to green.
Track last attempt and last known good separately. Lock contention should be
classified according to the worker's actual retry/skip contract, not swallowed as
success. A paused capacity is a dependency state, not healthy-empty data.

## 5. Ontology design

Keep the canonical inventory identity authority and deterministic taxonomy. Model
resources/workloads, business service/application/environment/owner, findings,
changes and remediation evidence with clear edge direction and source provenance.
Stable entity IDs are tenant-qualified; edge identity includes endpoints/predicate.
Review inverse relationships semantically: current `member_of` and `hosted_on`
edges are intentionally both produced and must not be deleted on model advice.

Maintain separate artifacts for:

- immutable candidate/generation and its quality report;
- entity/relationship Delta tables;
- native Fabric Ontology definition and bindings;
- native transport/query evidence and application consumer selection.

The migrated new-experience Ontology has a different definition representation
(STATE records 163 TMDL parts versus 230 legacy JSON parts). Export/readback and
format compatibility are prerequisites to retargeting any publisher. Preserve
the original and existing clients until reviewed migration and rollback are
demonstrated. A native diagnostic query does not authorize automatic publication.

Keep business semantics source-backed: define Application versus Business
Service versus Environment, each relationship's direction/cardinality and its
evidence predicate. Use descriptions and synonyms to explain those differences
to native agents. Proposed ChangeEvent-to-asset links require actual provider
resource/time evidence; do not synthesize them to make the graph connected.
Version taxonomy/binding changes and assess existing tool and UI consumers
before removing types or relationships.

Use AI asynchronously to propose missing relationships, descriptions and quality
findings. Bind proposals/citations to exact generations and scope; deterministic
validation, reviewer separation of duties and publisher authority remain intact.
Adopt native traversal first for the planned topology/blast-radius and governance
use cases, with separately labeled projection fallback and a kill switch.

## 6. Analytical semantic-model design

Native Ontology expresses relationships and operational semantics. The Power BI
semantic model expresses analytical grain, filtering and measures. One does not
replace the other and neither should mirror all physical tables.

Design a curated Direct Lake candidate from actual source schemas:

| Candidate analytical object | Source and constraints |
|---|---|
| Exposure facts | `gold_exposure_facts`; document target/weakness/source-state/generation grain; distinguish fact count from distinct exposure count |
| Exposure evidence | `gold_exposure_evidence`; validated many-to-one fact linkage within the selected generation; normally drillthrough rather than headline aggregation |
| Resource/target dimension | Build only from verified canonical identity; handle server and container/image target kinds explicitly; never join every `resource_id` by name |
| Subscription/connection, severity, source-family and status dimensions | Prove keys/uniqueness and compatible scope; materialize reviewed dimension contracts if existing generic facet rows cannot provide them |
| Date dimension | Source-generated UTC date keys and role-specific dates; preserve timestamp provenance and avoid string-only time analysis |
| Ownership/application/environment | Include only when grounded mappings and grain/unknown semantics are verified |
| Existing facets/summaries | Preserve for API serving; expose separately with declared scope/grain or omit from the analytical model to avoid double-counting |

Start the curated model with Exposure because it has established Gold contracts
and a canonical scoped query service. Add inventory, changes, cost and service
analytics only when their Gold product grain and conformed keys are ready.
Do not invent missing facts/dimensions in DAX or make the native graph's hundreds
of relationship projections visible as analytical tables.

Do not connect the generic `gold_exposure_dimensions` dictionary directly to every
fact column or sum facets across multiple dimension names/scope levels. Its key
includes scope, dimension name/value and generation. Fact IDs also encode
generation and are not globally stable resource IDs.

Use one-to-many, single-direction relationships with unique compatible keys.
Create explicit measures for active distinct exposures, affected targets,
overdue/indeterminate SLA and coverage using defined denominators; reconcile
them against canonical API queries for the same scope/generation. Do not sum
repeated workload counts or average percentages blindly.

Hide technical columns and Bronze/Silver/control internals from analytical
consumers; use readable names, descriptions, units, display folders and verified
filter propagation. Visibility is not access control: require effective
identity/security tests for the selected Direct Lake mode and serving path.
Keep app-side scope enforcement and do not assume workspace membership alone
implements end-user row isolation.

Choose and record Direct Lake on OneLake versus Direct Lake on SQL endpoints
explicitly: their security/fallback capabilities differ. Source existence,
successful framing, successful DAX and effective scoped data access are distinct
checks. A refresh of Direct Lake metadata is not a new source-ingestion run or
evidence that all products advanced atomically.

The current semantic builder is explicitly a scaffold. The narrow offline
validator rejects measures/hierarchies/roles and cannot certify DAX, live bindings
or Fabric acceptance. Do not extend its success label into deployment proof or
silently bypass it to publish a richer model. Use a reviewed full authoring path,
source-schema validation, model-engine queries, isolated deployment/readback,
comparison and rollback before definition-management cutover. Preserve
Terraform's existing destroy protection and definition ignores until that explicit
ownership transition.

## 7. Frontend and API consumption

Extend the existing Connections/Fabric experience rather than add a second console.

| User workflow | Backend evidence and UI behavior |
|---|---|
| Platform overview | Environment/workspace/capacity identity plus independently evidenced publication, native Ontology, semantic-model and Data Agent states |
| Data-product explorer | Family/layer, owner, grain, scope, row count, observed freshness, quality, generation and consumers; ontology/metadata remain distinct families |
| Lineage drilldown | Source run -> Bronze -> Silver -> Gold -> native bindings/model, with immutable references and explicit missing links |
| Publication operations | Attempt versus last-known-good, stage progress, duration, lock/capacity blockers, failures and retained rollback reference; commands remain role/approval gated |
| Native ontology inspection | Types/relationships/bindings and exact native-versus-projection provenance; link to supported Fabric UI rather than imply an app-side graph engine |
| Analytical readiness | Model identity/version, supported business metrics, binding/query verification and generation compatibility; configured is not verified |
| Exposure/Inventory/Topology | Existing scoped domain APIs, bounded server queries, stable drillthrough and compatible generation selection; no browser Delta queries |
| Copilot | Only current scoped visible evidence, real freshness and limitations; native/Data Agent results remain attributable optional enrichment |

First implement honest existing health semantics: successful HTTP data is not
freshness; generic publication success is not semantic-model proof; missing
evidence is unknown, not zero/green. Preserve independent-section errors, scoped
URL state, cancellation and keyboard/mobile behavior. Reuse common loaded data
where practical to avoid duplicate page/panel calls.

Initial UI acceptance scenarios:

1. HTTP 200 carrying stale/unknown evidence retains that state in both the panel
   and Copilot snapshot; unavailable sections do not erase other valid sections.
2. A generic successful projection attempt does not turn the semantic model
   green; a failed projection remains visible in ingestion history.
3. A configured Data Agent reads as configured/not verified, while an unconfigured
   agent reads as disabled; neither implies a successful query.
4. An empty ingestion history does not become a successful ingestion run.
5. The standalone page loads each shared layer/manifest/governance/capabilities
   endpoint once per refresh/scope, while embedded panel consumers still work.
   Dataset detail calls are separate and must not be included in that count.
6. Switching scope cannot retain an apparently current response from the previous
   scope. Keyboard focus, section errors, retry and loading states remain usable.

Future backend extensions should be additive/versioned and bounded, carrying
product/artifact kind, evidence mode, observed time, source/generation, status,
reason codes and last-good reference. These are proposed fields, not an already
implemented API. Publish the contract and consumer tests before frontend adoption.
No frontend credentials, client-selected authority roots or browser-based
publisher ownership. No page-specific Fabric tables.

Data Agent consumption should use the curated analytical model or explicitly
selected Gold products, not the full physical Lakehouse. Measure asynchronous
quality, citation validity and latency before considering synchronous Copilot
grounding. Preserve delegated identity/scope requirements; a service credential
or configured endpoint is not evidence of end-user delegation. AI suggestions
never approve themselves or directly alter analytical measures/native bindings.

## 8. Execution waves, ownership and acceptance

| Wave | Owner/session | Output | Release condition |
|---|---|---|---|
| 0: existing health correctness | Fabric readiness correctness; Fabric frontend health | Isolated backend/frontend patches, regressions and frontend enhancement plan | Existing contracts preserved; no new cloud operation or gated runtime |
| Prerequisites | Ontology; Unified Deployment; existing evidence owners | Qualified corrected-target image, durable coordinator roots, approved effective access, fixed evidence templates, lifecycle/restart/rollback receipts | Existing exact approval/verification gates; local tests and historical rollout are not substitutes |
| Independent offline maintenance | Ontology's user-directed Phase 14 | Planner capability gate, injectable advisory curator and durable proposal/review tracer | Does not establish unattended native authoring or bypass Phase 13/03.7/03.8 acceptance |
| 1: product decoupling/query scale | Existing Phase 03.7 plan owners, coordinated by Fabric | Five-table inventory tracer, status-only probes, bounded scoped SQL, shadow comparison and rollback | All 03.7 prerequisite summaries and passing verification required before any Wave 0 implementation |
| 2: native adoption | Ontology and existing Phase 03.8 owners | Reviewed definition-format compatibility, native traversal/bindings, strict provenance/auth, staged canary | All 03.8 prerequisites unqualified passed; preserve independent Exposure gates |
| 3: analytical curation | Fabric/semantic-model owner with Unified Deployment | Reviewed source-backed star candidate, source/engine checks, reconciled metrics, deployment/readback and rollback | Model ownership/security/migration review; no inference from scaffold/offline validation |
| 4: richer operator UX | Frontend owner with each domain API owner | Product/lineage/readiness views and generation-aware domain drilldowns | Delivered versioned contracts plus scoped, accessible browser acceptance; rollout stays with deployment owner |

Waves 3/4 are a target design and sequencing proposal, not an amendment that
removes existing phase gates or starts another parallel publisher. Assign
concrete implementation ownership only after overlap with the existing plans
has been reconciled.

Minimum acceptance:

- No scope leak; absent and out-of-scope identities remain indistinguishable.
- No loss of immutable observations, pointer history, last-good data or audit.
- Exact failure/degraded/healthy-empty handling; unchanged content does not wipe.
- Production-scale bounded queries and required 25,001/100k evidence use their
  existing plan definitions, not a smaller proxy.
- Native success requires independent native transport/definition/binding
  evidence; semantic-model success requires its own engine/query proof.
- Same scope/generation reconciles API counts, analytical measures and drilldowns;
  generation changes, conflicting source states and unknown mappings are tested.
- Frontend does not manufacture freshness, duplicate authority or hide failed
  dependencies behind a successful envelope.
- Compare publication duration/table writes, query latency/materialized rows,
  frontend request count and capacity cost against a qualified baseline before
  setting or claiming an improvement threshold.

The analytical reconciliation suite must explicitly compare unfiltered and
single-severity/source/connection slices, zero/unknown coverage, server versus
container targets, detail drillthrough and generation rollover. A relationship
that exists in metadata but does not propagate the expected filter fails
acceptance. Validate current and retained prior definitions so rollback includes
bindings, measures and consumer compatibility, not just a previous item name.

## 9. Current blockers and boundaries

STATE still records Phase 03.1 `gaps_found`, missing Phase 7 verification,
Phase 9 `human_needed`, Phase 13 deployed lifecycle failure and missing downstream
acceptance. Phase 03.7 and 03.8 are not executable merely because their plans
exist. Required Phase 11 closeout is also incomplete for native adoption.

Unified Deployment's corrected-target inventory finds five existing Jobs, no
qualified evidence/fixture/RBAC Job set, coordinator validation roots under
`/tmp`, missing corrected-registry qualified image/AcrPull, and an unresolved
collector grant. Metadata roles are not effective managed-identity access proof.
The deployment owner is stopped at an explicit security approval boundary.
This request does not fabricate that approval.

An exact read-only artifact check during this review found: Phase 03.7 summaries
01-12 and verification absent; Phase 11 summary 12 and verification absent;
Phase 13 summaries 21/22 absent with verification `gaps_found`; Phase 7 summaries
01-06 present but verification absent; Phase 9 summaries 10/11 absent with
verification `human_needed`. These findings govern sequencing; do not create
completion summaries to unblock execution.

No workspace creation, data relocation, deletion, grant, tenant-policy update,
native definition write, model deployment or active-pointer transition is
authorized by this design document. Local implementation and owner handoffs
must be recorded separately from merged, deployed and accepted states.

## 10. Implementation ledger

| Deliverable | State at review | Evidence/owner |
|---|---|---|
| This architecture and implementation plan | Written in the shared checkout, uncommitted | Fabric coordinator; existing dirty source/planning files preserved |
| Existing backend readiness correction | Implemented and tested in isolated worktree, not committed/deployed | Fabric readiness correctness, baseline `34bee34c3`; scoped API/config tests and Ruff pass |
| Existing frontend readiness/shared reads | Implemented and tested in isolated combined worktree, not committed/deployed | Fabric frontend health; existing API field shapes retained |
| Agent-led maintenance capability/proposal tracer | Independently owned offline work | Ontology's user-directed Phase 14; no native production activation inferred |
| Corrected-target prerequisite rollout | Blocked at existing approval/evidence boundary | Unified Deployment, exclusive deployment owner |
| Product decoupling/native adoption/model cutover | Proposed or existing gated work, not implemented by this review | Existing phase and source/security/rollout prerequisites remain authoritative |

The backend change reports semantic-model readiness as unknown when only
ontology projection attempts are present. It preserves those attempts and their
failures in ingestion history. Data Agent `configured` remains available as a
configuration signal; readiness is unknown when configured and disabled when
not configured. No source/model/native write or new live probe was introduced.

## References

- [Fabric persistence architecture](fabric-architecture.md)
- [Inventory data flow](fabric-data-flow.md)
- [Ontology architecture](ontology-architecture.md)
- [Lakehouse inventory, historical survey](LAKEHOUSE_TABLE_INVENTORY.md)
- [Semantic-model validation boundaries](semantic-model-validation.md)
- [Ontology operations and acceptance](ontology-discovery-operations.md)
- [Direct Lake overview](https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview)
- [Star-schema guidance](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema)
- [Medallion architecture](https://learn.microsoft.com/en-us/fabric/onelake/onelake-medallion-lakehouse-architecture)
