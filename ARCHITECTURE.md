# Hermes Operations Graph — Architecture

## 1. Purpose

Hermes Operations Graph (HOG) is an Azure-first operational context and digital-twin platform. It connects authoritative operational data already held by Azure and enterprise systems into a governed graph that answers questions such as:

- What resources, applications, and business services are affected by this incident?
- Who owns them, what do they depend on, and which runbook applies?
- Which findings and missing patches increase risk?
- What did prior incidents teach us about impact and mitigation?

HOG does **not** replace Azure Resource Graph (ARG), Azure Monitor, Log Analytics, Application Insights, OpenTelemetry, Defender for Cloud, Microsoft Sentinel, Azure Update Manager, Microsoft Entra ID, ServiceNow, or Azure DevOps. Those systems remain authoritative. HOG materializes only normalized entity identity, relationship assertions, provenance, confidence, and the minimum source projection needed for governed graph use.

## 2. Architectural principles

1. **Source systems remain systems of record.** Never create a second inventory, CMDB, incident store, or telemetry store.
2. **Reference before replicate.** Keep source IDs and deep links; query live for detail. Materialize only graph-ready projections and history that the source cannot provide as a graph.
3. **Managed Azure first.** Prefer Azure MCP Server, ARG, Azure Monitor, Fabric/OneLake, Fabric IQ Ontology, and Microsoft Foundry Agent Service.
4. **Evidence before inference.** Every edge is an assertion with `confidence`, `source`, `createdTimestamp`, and `lastObservedTimestamp`.
5. **Deterministic before generative.** Native IDs, tags, topology, and telemetry correlations outrank AI-inferred mappings.
6. **Human governance for business semantics.** Agents may propose ownership and business mappings; stewards approve consequential or ambiguous changes.
7. **Read-only discovery by default.** Separate discovery identities from publishing identities. Agent-triggered mutations require explicit policy and approval.
8. **Time-aware and reversible.** Never silently overwrite relationship history; supersede or expire assertions.

## 3. Scope and system boundary

### In scope

- Cross-subscription/management-group Azure resource discovery.
- Structural, observed-runtime, operational, ownership, and business relationships.
- Eight graph entity types: Resources, Applications, Business Services, Teams, Incidents, Findings, Patches, and Runbooks.
- Six relationship predicates: `ownedBy`, `supports`, `hosts`, `dependsOn`, `impacts`, and `mitigatedBy`.
- Confidence scoring, provenance, reconciliation, stewardship, history, and graph publication.
- Fabric IQ Ontology as the shared semantic/query experience.
- Microsoft Foundry agents grounded through Fabric IQ and read-only Azure MCP tools.

### Out of scope

- Raw metrics, logs, traces, or security-event ingestion pipelines.
- Replacement monitoring, alerting, CMDB, asset inventory, ticketing, or patch orchestration.
- Autonomous remediation in the first delivery.
- Treating an LLM statement as authoritative evidence.

## 4. Logical architecture

```text
Authoritative sources
 ARG | Azure Monitor/LAW/App Insights/OTel | Sentinel | Defender
 Update Manager | Entra ID | ServiceNow | Azure DevOps
             │
             │ native APIs, KQL, ARG, connectors, Azure MCP
             ▼
Discovery and learning plane
 Resource Discovery Engine ───────┐
 Dependency Discovery Engine ─────┤
 Business Mapping Engine ─────────┤
 Incident Learning Engine ────────┤
                                  ▼
                         Assertion staging
                    identity resolution + evidence
                                  │
                                  ▼
                         Ontology Steward Engine
                   validate • score • reconcile • approve
                                  │
                                  ▼
Publication plane
 OneLake curated entity/edge tables ── Fabric Ontology Writer
                                  │
                                  ▼
                Fabric IQ Ontology / Graph in Microsoft Fabric
                         │                      │
                         ▼                      ▼
             Fabric/Data agents       governed analytics
                         │
                         ▼
              Foundry Agent Integration Layer
              Azure MCP + Fabric IQ + enterprise tools
```

The logical graph is not an extra operational database. Its durable product is a compact set of identity, assertion, evidence, and stewardship records in OneLake, bound into Fabric IQ Ontology. Source detail stays in the source.

## 5. Core components

### 5.1 Resource Discovery Engine

**Purpose:** establish canonical Resource entities and structural facts without creating a custom inventory.

**Primary sources:** ARG, ARM resource IDs, Azure Resource Changes, Azure Policy/RBAC metadata where needed.

**Responsibilities:**

- Execute approved, versioned ARG queries at management-group or subscription scope.
- Normalize ARM resource IDs (case-insensitive comparison; preserve source representation).
- Extract resource type, tenant/subscription/resource-group scope, location, tags, managed-by links, and source deep links.
- Emit Resource observations and high-confidence structural assertions.
- Mark resources as not observed after an agreed grace period; never infer deletion from one failed run.

**Explicit non-responsibility:** it is not an inventory UI or authoritative resource catalog. ARG remains authoritative.

### 5.2 Dependency Discovery Engine

**Purpose:** produce evidence-backed `hosts` and `dependsOn` assertions.

**Evidence tiers:**

1. **Declared topology:** ARM parent/child, resource properties, deployment metadata, Azure DevOps service declarations.
2. **Platform-observed topology:** Application Insights application map/dependency telemetry, OpenTelemetry resource and service attributes, Azure Monitor data.
3. **Operational co-occurrence:** incident and alert correlations.
4. **Inference:** model-proposed relationships, always lower confidence and stewardable.

It stores aggregate evidence windows and source references, not raw traces or logs. Direction is normalized as “subject depends on object” and “resource hosts application.” Conflicting directions are quarantined for review.

### 5.3 Business Mapping Engine

**Purpose:** connect technical entities to Applications, Business Services, and Teams.

**Source precedence:** approved ServiceNow service/CI relationships and designated ownership records; governed Azure tags; Entra groups/service-principal owners; Azure DevOps area/team/repository metadata; inferred naming similarity.

The engine emits proposals. It cannot turn an inferred owner or service mapping into an authoritative edge without policy. Absence of a tag is not evidence that no owner exists.

### 5.4 Incident Learning Engine

**Purpose:** learn durable impact and mitigation context from Sentinel and ServiceNow incidents, Azure Monitor alerts, post-incident records, runbooks, and Azure DevOps work items.

**Responsibilities:**

- Canonicalize cross-system incident references without merging unrelated incidents.
- Link incidents to affected entities using explicit affected-resource IDs first, temporal/telemetry correlation second.
- Extract candidate `impacts` and `mitigatedBy` assertions.
- Update confidence only after resolution evidence or steward approval.
- Retain links and concise summaries; do not copy full ticket histories or sensitive logs into the graph.

### 5.5 Ontology Steward Engine

**Purpose:** own semantic quality and lifecycle.

**Responsibilities:** schema validation, identity resolution, confidence computation, duplicate detection, source precedence, contradiction handling, temporal expiry, policy checks, review queues, audit history, and quality metrics.

**Decision classes:**

- **Auto-accept:** exact native identifiers and deterministic topology from approved sources.
- **Auto-accept with monitoring:** repeated telemetry relationships above configured evidence thresholds.
- **Human review:** business ownership, business-service support, ambiguous identity merges, and AI-only proposals.
- **Reject/quarantine:** invalid endpoint types, missing provenance, impossible timestamps, or forbidden data classes.

### 5.6 Fabric Ontology Writer

**Purpose:** publish the curated graph through supported Fabric mechanisms.

The name “Writer” does not imply an undocumented direct Ontology API. For the initial architecture it writes idempotent, graph-ready entity and relationship projections to governed OneLake managed tables and maintains their bindings to Fabric IQ Ontology. Fabric Ontology builds the queryable instance graph from those bindings.[1]

Because Ontology is preview and upstream changes require graph refresh, the writer must expose refresh state, publication watermark, and rollback to the prior curated version.[1]

### 5.7 Foundry Agent Integration Layer

**Purpose:** expose safe operational reasoning to Microsoft Foundry agents.

- Connect agents to Fabric IQ for ontology-grounded questions; optionally use the separate preview Fabric Ontology MCP consumption endpoint when a client requires MCP. Neither path is an ontology write API.
- Expose Azure MCP Server in read-only, namespace-filtered mode for Azure Monitor, Resource Health, resource listing/insights, and other validated Azure context. Use ARG's supported SDK/REST/CLI surfaces for arbitrary graph queries; current Azure MCP documentation does not expose a general-purpose ARG query tool.
- Use separate approved tools/connectors for Sentinel, Defender, Update Manager, Entra, ServiceNow, and Azure DevOps when Azure MCP has no native capability.
- Attach citations/source links and confidence to answers.
- Enforce maximum traversal depth, query budgets, tenant boundaries, and prompt-injection defenses.
- Require approval before any operational mutation.

Microsoft documents Fabric IQ as a Foundry agent tool and Azure MCP as an agent-to-Azure context surface.[2][3]

## 6. Data flow and maintenance loops

### Loop A — inventory and identity

1. Scheduled ARG discovery reads authoritative resource projections.
2. Stable IDs are normalized and matched.
3. Resource observations update `lastObservedTimestamp`.
4. Missing observations enter a grace state; confirmed source deletion closes validity.

### Loop B — dependency evidence

1. Query approved Application Insights/LAW summaries and platform topology.
2. Reduce evidence into endpoint pairs, observation windows, and counts.
3. Resolve endpoints to canonical Resource/Application IDs.
4. Score and publish or queue assertions.

### Loop C — business mapping

1. Read approved ServiceNow, Entra, tags, and Azure DevOps projections.
2. Apply source precedence and mapping rules.
3. Propose ownership/support edges.
4. Route ambiguous or high-impact changes to stewards.

### Loop D — incident learning

1. Observe incident lifecycle changes from Sentinel and ServiceNow.
2. Resolve affected entities and mitigation artifacts.
3. Emit provisional edges during the incident.
4. Re-evaluate after resolution/post-incident review.

### Loop E — publication and graph refresh

1. Steward Engine commits a versioned curated snapshot/delta.
2. Fabric Ontology Writer publishes entity and relationship tables.
3. Ontology graph refresh runs according to supported Fabric behavior.
4. Health checks compare source watermark, curated watermark, and graph watermark.

## 7. Confidence and conflict model

Confidence is a calibrated value from `0.0` to `1.0`, not a probability claim unless later calibrated as one.

Suggested starting bands:

- `0.95–1.00`: exact native relationship or steward-approved assertion.
- `0.80–0.94`: deterministic mapping from an approved authoritative field.
- `0.60–0.79`: repeated runtime observation with stable endpoint identity.
- `0.40–0.59`: multi-signal correlation requiring review for consequential use.
- `<0.40`: proposal only; excluded from default production traversal.

Score inputs include source reliability, identifier quality, observation frequency, recency, corroboration, contradiction, and steward disposition. Never combine scores by averaging blindly. Preserve each source assertion, then compute a separate effective edge view.

When sources disagree, retain both assertions, apply source policy, and expose the conflict. A steward decision supersedes rather than deletes evidence.

## 8. Security, privacy, and governance

- Use workload identities/managed identities, private endpoints where supported, and least-privilege Azure RBAC.
- Discovery identities are read-only. Publication identity can write only to designated OneLake/Fabric artifacts.
- Azure MCP runs with read-only mode and enabled-service filters for discovery agents; the server itself uses the caller’s RBAC permissions.[3]
- Separate tenant and environment data planes. No cross-tenant identity merging by display name.
- Keep secrets in Key Vault and configuration in managed configuration services.
- Minimize personal data: Team is the primary ownership entity; individual identities remain source references unless approved.
- Apply Fabric workspace roles, OneLake permissions, sensitivity labels, Purview policies, and audit logs.
- Redact ticket descriptions and log content before any model interaction.
- Record model/version/prompt-policy for AI proposals, but never store hidden chain-of-thought.

## 9. Reliability and observability

Each engine publishes:

- run ID, source scope, query version, start/end time, status;
- source and destination watermarks;
- observations/assertions accepted, rejected, quarantined, and expired;
- identity-resolution and schema failures;
- graph refresh lag and stale-source indicators.

Use Azure Monitor/Application Insights/OpenTelemetry for platform telemetry. Do not route HOG telemetry back through a bespoke telemetry pipeline. Failed runs retry idempotently; repeated failures dead-letter only compact work descriptors, not source payloads.

Initial service objectives:

- ARG/resource graph freshness: 95% within 30 minutes of the configured discovery cycle.
- Incident context freshness: 95% within 10 minutes of source event availability.
- Ontology publication lag: measured separately because preview refresh behavior may dominate.
- Provenance completeness: 100% of published edges.
- Invalid endpoint/type rate: 0 in published data.

Targets are hypotheses to validate in the pilot, not promises about source-system latency.

## 10. Deployment topology

Recommended managed building blocks, subject to implementation-phase validation:

- Azure Functions or Container Apps Jobs for scheduled/event-driven engines.
- Durable Functions only where orchestration state is necessary.
- Event Grid/Logic Apps for supported event and SaaS connectors.
- OneLake Lakehouse managed Delta tables for curated graph projections.
- Fabric IQ Ontology / Graph in Microsoft Fabric for semantic graph and query.
- Azure Monitor, Application Insights, and OpenTelemetry for HOG observability.
- Key Vault, managed identities, private networking, and Azure Policy.
- Microsoft Foundry Agent Service for managed agent execution.
- Azure MCP Server for supported live Azure tools, not as a universal ingestion API or general-purpose ARG façade.

## 11. Key architecture decisions

| Decision | Choice | Rationale |
|---|---|---|
| Authoritative inventory | ARG | Avoid a custom inventory and preserve Azure scope/IDs. |
| Raw telemetry | Remains in Azure Monitor/LAW/App Insights | Avoid duplicate telemetry pipeline and cost. |
| Graph persistence | Minimal curated projections in OneLake | Fabric-supported binding and governed history. |
| Semantic graph | Fabric IQ Ontology | Managed vocabulary, bindings, graph, and agent consumption.[1] |
| Agent live Azure access | Azure MCP, read-only/filter-scoped, plus direct ARG tool where needed | Managed tool surface with caller RBAC; arbitrary ARG querying is a separately governed capability.[3] |
| Business truth | Source precedence + steward approval | Prevent naming/tag inference from becoming CMDB truth. |
| Relationship model | Assertion history + effective view | Preserve provenance and resolve conflicts safely. |
| Preview isolation | Adapter + exportable canonical tables | Fabric Ontology can evolve without losing canonical data. |

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Fabric IQ Ontology is preview | Capability spike, adapter boundary, OneLake canonical tables, rollback path, GA exit review. |
| Azure MCP coverage is incomplete | Maintain a tested capability registry and use native APIs/connectors for gaps. |
| Graph becomes a shadow CMDB | Store only graph projections/provenance; deep-link to source; publish ownership rules. |
| Telemetry creates noisy dependencies | Aggregate windows, require stable identities/repetition, decay stale assertions. |
| Tag quality is poor | Treat tags as governed evidence, not universal truth; reconcile with ServiceNow/Entra/ADO. |
| AI hallucinated mappings | Proposal-only status, evidence requirement, thresholding, steward approval. |
| Cross-source identity collision | Namespaced stable keys; never merge solely by names. |
| Sensitive incident data leakage | Field allowlists, redaction, source authorization, scoped agent tools. |

## 13. Architecture acceptance criteria

- Every required entity and predicate is represented in the ontology.
- Every published relationship has all four mandatory metadata fields.
- Every entity carries a source-native stable key and source link.
- No component persists raw logs, metrics, traces, or full CMDB/ticket payloads.
- Unsupported Azure MCP capabilities are never implied.
- Fabric preview dependencies have a tested fallback/rollback.
- Agent answers can report path, confidence, source, and observation time.
- Steward decisions and automated score changes are auditable.

## References

[1] Microsoft, “What is ontology (preview)?,” Fabric IQ. https://learn.microsoft.com/en-us/fabric/iq/ontology/overview

[2] Microsoft, “Connect agents to Microsoft Fabric with Fabric IQ (preview).” https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq

[3] Microsoft, “Azure MCP Server documentation.” https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/
