# Hermes Operations Graph Implementation Plan

> **For Hermes:** Execute this plan phase-by-phase only after architecture approval. Use test-driven delivery, security review, and two-stage review (spec compliance, then quality) for implementation tasks.

**Goal:** Deliver a self-maintaining, Azure-first Operational Context Graph and Fabric digital twin that links authoritative Azure and enterprise operational sources without replacing their inventory, telemetry, CMDB, monitoring, incident, or patch functions.

**Architecture:** Managed discovery services produce compact source observations and relationship assertions. A stewardship layer resolves identity, provenance, confidence, conflicts, and time. Versioned curated tables in OneLake bind into Fabric IQ Ontology; Microsoft Foundry agents consume the ontology and approved read-only Azure MCP tools.

**Primary services:** Azure Resource Graph, Azure Monitor/Log Analytics/Application Insights/OpenTelemetry, Microsoft Sentinel, Defender for Cloud, Azure Update Manager, Entra ID/Microsoft Graph, ServiceNow, Azure DevOps, OneLake/Lakehouse, Fabric IQ Ontology, Microsoft Foundry Agent Service, Azure MCP Server, Azure Functions or Container Apps Jobs, Key Vault, managed identities, Azure Monitor.

---

## 1. Delivery approach

Use incremental vertical slices, not source-by-source bulk ingestion. The first pilot should answer a bounded set of operational questions for one business service with representative Azure resources:

1. What resources and applications support the service?
2. Who owns them?
3. What are their current dependencies?
4. Which incident/finding/patch affects them?
5. Which approved runbook mitigates the issue?
6. What is the source, confidence, and observation time for every traversed edge?

Each phase has an explicit exit gate. Preview or unsupported capabilities must fail a gate rather than be hidden behind custom code.

## 2. Phase 0 — Decisions and prerequisites

### Objectives

- Approve system boundaries and sources of truth.
- Validate tenant, subscription, Fabric capacity, and preview-feature policy.
- Select a pilot business service and representative resource types.

### Activities

1. Review and approve all eight discovery artifacts.
2. Assign architecture, security, Fabric, operations, data governance, and service-owner decision makers.
3. Complete the system-of-record matrix at property and relationship level.
4. Confirm management-group/subscription scope, tenant boundaries, regions, sovereign-cloud needs, and data residency.
5. Confirm Fabric IQ Ontology preview may be used in the target tenant and capacity.
6. Identify ServiceNow tables/APIs and Azure DevOps organizations/projects available to the pilot.
7. Define sensitive-field allowlists, retention, and model-use restrictions.
8. Approve initial confidence bands and human-review policies.

### Deliverables

- Approved architecture decision records.
- Pilot charter and source access matrix.
- Threat model and data classification.
- Fabric preview go/no-go record.
- Measurable baseline/exit metrics.

### Exit gate

Proceed only if every entity has an authoritative identity source, every required source has an approved access path or explicit deferral, and the Fabric preview/fallback decision is accepted.

## 3. Phase 1 — Capability spikes

### Objectives

Remove the largest technical uncertainties before building the platform.

### Spikes

#### 1A. Azure MCP

- Pin a candidate Azure MCP Server version.
- Enumerate tools at runtime.
- Verify read-only/namespace filtering, authentication, tenant/subscription context, LAW query, Azure Monitor metrics, Resource Health, resource listing/insights, and audit behavior. Verify arbitrary ARG querying through a separately governed ARG SDK/REST tool rather than assuming Azure MCP provides it.
- Confirm required-source gaps rather than assuming tool coverage.

#### 1B. Fabric IQ Ontology

- Create a disposable ontology in an isolated workspace.
- Validate all eight entity types and six directional relationships.
- Validate relationship attributes for confidence/source/timestamps.
- Validate managed Lakehouse bindings, identity keys, graph query/traversal, manual/scheduled refresh behavior, security, and deletion/rollback.
- Test naming/type limits and representative scale.
- Determine supported source control/deployment mechanism and whether any public API supports required lifecycle operations.

#### 1C. Source access

- Run minimal read-only queries against ARG, LAW/App Insights, Sentinel, Defender, Update Manager, Entra, ServiceNow, and Azure DevOps.
- Capture stable identifiers, paging, throttling, timestamps, permissions, schema variability, and deep links.
- Verify that raw telemetry need not leave its source.

### Exit gate

Publish a capability report with passed, failed, and deferred requirements. If Fabric cannot represent mandatory relationship attributes or cannot be operated safely, pause and approve the fallback query/semantic approach before further delivery.

## 4. Phase 2 — Foundation and contracts

### Objectives

Create the secure managed platform boundary and executable data contracts.

### Work packages

1. Establish dev/test/prod environment topology and infrastructure-as-code standards.
2. Define separate managed identities for discovery, stewardship, publication, and agents.
3. Apply least-privilege RBAC, Key Vault, networking, policy, and logging.
4. Formalize entity, alias, observation, assertion, evidence-reference, decision, watermark, and publication contracts.
5. Define source registry, precedence, confidence, decay, expiry, and review policies.
6. Establish OneLake managed tables for compact curated projections.
7. Establish Azure Monitor/Application Insights/OpenTelemetry observability for the platform.
8. Create contract, data-quality, security, and reconciliation test suites using synthetic data.

### Validation

- RBAC positive and negative tests.
- Contract tests reject missing mandatory relationship metadata.
- Replay is idempotent.
- No test fixture contains production data or secrets.
- Observability reports source and publication watermarks.

### Exit gate

A synthetic end-to-end assertion can pass validation, stewardship, OneLake publication, and rollback with a complete audit trail.

## 5. Phase 3 — Resource and deterministic topology slice

### Objectives

Deliver the first trustworthy technical graph using ARG and deterministic Azure topology.

### Work packages

1. Implement versioned, reviewed ARG query packs for the pilot scope.
2. Normalize ARM identities and source aliases.
3. Support paging, throttling, partial access, resource changes, and periodic full reconciliation.
4. Produce Resource entities and deterministic `hosts`, `supports`, and `dependsOn` proposals from approved Azure properties.
5. Add successful-observation and grace-period lifecycle semantics.
6. Reconcile resource counts and representative samples directly with ARG.

### Validation

- 100% canonical resources have tenant-scoped source IDs and timestamps.
- No resource is expired after a failed/partial run.
- Deterministic edge endpoint/type validation is clean.
- Pilot resource coverage and freshness meet approved thresholds.

### Exit gate

Service owners confirm representative resources and declared relationships against Azure; discrepancies are explainable and traceable.

## 6. Phase 4 — Runtime dependencies and business context

### Objectives

Add observed dependencies, applications, business services, and teams without creating shadow telemetry or CMDB stores.

### Work packages

1. Query aggregate Application Insights/LAW dependency windows and OpenTelemetry semantic attributes.
2. Map telemetry services/endpoints to canonical Applications and Resources.
3. Add ServiceNow service, CI-reference, ownership, and team projections through approved supported access.
4. Add governed Azure tag and Entra group evidence.
5. Add Azure DevOps application/repository/pipeline/team references where included in the pilot.
6. Implement source precedence, contradiction detection, confidence scoring, decay, and steward review.
7. Build Fabric/Power BI or Azure Workbook quality views.

### Validation

- Labeled dependency set measures precision/recall and direction correctness.
- Runtime noise and ephemeral instances do not create permanent Applications.
- Low-confidence AI/name matches remain proposals.
- Accepted `ownedBy` and `supports` edges have an authoritative/approved basis.

### Exit gate

Pilot owners accept agreed precision and coverage. The review queue is usable, decisions are reversible, and the graph is demonstrably not a CMDB copy.

## 7. Phase 5 — Incidents, findings, patches, and runbooks

### Objectives

Connect operational risk and learning to the technical/business graph.

### Work packages

1. Project approved Sentinel and ServiceNow incident fields.
2. Correlate incidents by explicit cross-reference first; queue similarity-based matches.
3. Add Defender for Cloud findings/recommendations with affected resource IDs.
4. Add Update Manager assessment/installation projections and patch identities.
5. Add approved runbook metadata/deep links from designated systems.
6. Produce provisional `impacts` and `mitigatedBy` assertions.
7. Re-score after incident resolution and steward/post-incident decisions.
8. Apply redaction and sensitive-content tests before model use.

### Validation

- No full incident comments, raw alerts, traces, or ticket histories are copied.
- Cross-system incident false merges can be undone.
- Suggested, executed, and successful mitigation states are not conflated.
- Historical incident-time traversal reproduces approved examples.

### Exit gate

For the pilot, an operator can trace a real or safely reconstructed incident to affected service/resources, owner, findings/patches, and an approved runbook with complete provenance.

## 8. Phase 6 — Fabric Ontology publication

### Objectives

Publish the approved operational vocabulary and graph through Fabric IQ.

### Work packages

1. Produce versioned graph-ready OneLake entity and relationship projections.
2. Map logical schema to Fabric-supported physical names/types.
3. Bind managed Lakehouse tables to the ontology.
4. Configure relationship types and all mandatory attributes.
5. Implement publication watermarking, graph refresh monitoring, validation queries, and rollback.
6. Produce evidence, current accepted, proposed, incident-time, and agent-safe views where supported.
7. Document preview constraints and operator runbooks.

### Validation

- Entity and relationship counts reconcile with curated tables.
- Randomly sampled graph paths preserve source/confidence/timestamps.
- Failed refresh is detected and does not masquerade as fresh data.
- Prior schema/data version can be restored.
- Authorization tests prove workspace and data boundaries.

### Exit gate

The Fabric ontology satisfies mandatory semantics and operational readiness. Otherwise invoke the approved fallback and keep the canonical projections portable.

## 9. Phase 7 — Foundry agent integration

### Objectives

Provide grounded, read-only operational reasoning.

### Work packages

1. Configure Foundry Agent Service and Fabric IQ tool integration.
2. Configure a pinned, read-only, namespace-filtered Azure MCP profile and a separately governed read-only ARG query tool if agent scenarios require arbitrary Resource Graph queries.
3. Add approved direct connectors/tools only for required Azure MCP gaps.
4. Enforce query budgets, traversal depth, tenant/environment scope, and sensitive-field policy.
5. Define a response contract that includes path, source, confidence, observation time, and uncertainty.
6. Create a golden evaluation set and adversarial prompt-injection/overreach tests.
7. Capture agent telemetry in Azure Monitor/Application Insights without logging sensitive source payloads.

### Evaluation scenarios

- owner of an affected service/resource;
- upstream/downstream dependency and blast radius;
- relevant current findings/patches;
- prior related incidents and applied runbook;
- stale or conflicting evidence;
- unsupported operation or inaccessible source;
- malicious content in a ticket/runbook field;
- request for mutation in read-only mode.

### Exit gate

Agent reaches approved correctness, groundedness, citation, authorization, and refusal thresholds. No write/action capability is enabled.

## 10. Phase 8 — Production readiness and rollout

### Objectives

Validate reliability, cost, governance, and support before broader adoption.

### Activities

1. Representative-scale load, graph-refresh, and cost tests.
2. Source outage, throttling, schema drift, permission loss, stale graph, and rollback drills.
3. Security review and penetration/prompt-injection testing.
4. Data-governance and privacy sign-off.
5. SLOs, dashboards, alerts, runbooks, support rota, capacity, and escalation.
6. Controlled pilot release, observation period, and retrospective.
7. Expand by business service and source only after quality gates pass.

### Exit criteria

- Provenance completeness is 100% for published edges.
- No invalid endpoint/type records are published.
- Freshness and graph publication objectives are met for the pilot.
- Cost is within approved budget at projected scale.
- Operators can recover from failed publication and source outage.
- Service owners and stewards accept graph utility and error rates.

## 11. Test strategy

- **Contract:** entity/relationship schemas and mandatory provenance.
- **Unit:** normalization, endpoint rules, confidence policy, temporal logic.
- **Source integration:** paging, throttling, schema drift, permissions, partial failure.
- **Data quality:** uniqueness, referential integrity, freshness, conflicts, PII/secrets.
- **Reconciliation:** compare graph projections to authoritative source queries.
- **Fabric:** binding, graph refresh, query paths, authorization, rollback.
- **Security:** RBAC, network, prompt injection, MCP tool restriction, data exfiltration.
- **Agent evaluation:** grounded path correctness, source attribution, uncertainty, refusal.
- **Resilience:** replay, dead-letter recovery, source outage, stale watermark.
- **Performance/cost:** source query volume, OneLake growth, graph refresh, agent token/tool budgets.

## 12. Release and rollback

- Promote immutable artifacts and schema versions through dev, test, and production.
- Separate runtime release from ontology schema/data publication.
- Validate compatibility before each promotion.
- Keep prior curated projection and ontology mapping until post-release validation completes.
- Rollback must restore runtime, data publication pointer/watermark, and ontology mapping together.
- Never repair production by deleting contradictory evidence; supersede it with audited policy/decision.

## 13. Major dependencies and open decisions

- Fabric IQ Ontology preview approval, capacity, regions, limits, and lifecycle APIs.
- Organization-specific ServiceNow schema and source-of-truth policy.
- Sentinel incident operating model and Defender portal integration state.
- Update Manager data retention and required assessment freshness.
- Entra app permission consent and personal-data policy.
- Azure DevOps organization boundaries and service-hook policy.
- Management-group ARG visibility and cross-tenant requirements.
- Whether Azure SRE Agent complements or overlaps the Foundry integration in a later phase.

## 14. Definition of done

A feature is done only when it:

- uses an approved managed/source-native capability;
- preserves source authority and stable identity;
- does not duplicate raw telemetry/CMDB/inventory/ticket data;
- is idempotent, observable, secure, documented, and recoverable;
- passes contract, integration, data-quality, and security tests;
- exposes provenance and freshness;
- has a named owner and operational runbook;
- has passed the phase exit gate.
