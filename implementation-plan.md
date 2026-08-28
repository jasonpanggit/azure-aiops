# Implementation Plan

> **For AIOps:** Implement only after the discovery artifacts and architecture decisions are approved. Follow the codebase Footprint Ladder: extend existing code → CLI + skill → service-gated tool → standalone plugin → MCP → core tool only as a last resort.

## 1. Delivery principles

- Azure systems remain systems of record.
- Fabric Ontology is the system of context.
- AIOps is the self-maintaining orchestration, inference, confidence, learning, and stewardship engine.
- Build a standalone HOG plugin/project integration, not Azure-specific core sprawl.
- Reuse AIOps cron, webhooks, MCP client, registry/toolsets, delegation, Kanban, session state, monitoring, skills, and memory boundaries.
- Use deterministic source adapters and queries before agents.
- Keep all source and publication operations idempotent, observable, and reversible.
- No autonomous operational mutation in these phases.

## 2. Complexity scale

- **S:** configuration/skill/query asset; established framework.
- **M:** focused adapter/plugin feature with integration tests.
- **L:** multi-source identity/data lifecycle with security and scale testing.
- **XL:** preview/platform uncertainty or organization-wide semantic change.

Estimates are relative complexity, not calendar commitments.

## Phase 1 — Resource Graph

### Outcome

Authoritative Subscription, ResourceGroup, Resource, VirtualMachine, AKSCluster, Database, and StorageAccount discovery with structural relationships and event-assisted updates.

### Reusable components

- AIOps native MCP client and dynamic tool registry.
- Azure MCP subscription/group/Compute/AKS/Insights tools for interactive validation.
- Direct ARG REST/SDK for arbitrary deterministic queries.
- AIOps cron for incremental/full reconciliation and durable watermarks.
- AIOps webhooks for normalized Event Grid triggers.
- Plugin system for HOG adapters; no core-tool additions.
- Session state and gateway monitoring.

### New code/configuration required

- Standalone HOG plugin/package with source registry, canonical contracts, watermarks, schema validation, and OneLake publication adapter.
- Versioned ARG query pack and ARM identity normalization.
- Event Grid Resource Notifications → managed Function/Logic App → signed AIOps webhook integration.
- Resource change/tag/owner mapping policy.
- Fabric canonical tables and initial ontology binding.

### Risks

- Azure MCP 3.0 is beta and has no arbitrary ARG tool.
- ARG pagination/throttling and provider schema drift.
- Event Grid coverage and at-least-once/out-of-order delivery.
- Fabric Ontology preview binding/refresh/security limits.
- Live checkout is behind upstream and locally modified; implementation must begin from an approved clean baseline.

### Complexity

**L** — deterministic but foundational and cross-platform.

### Exit gate

A bounded subscription pilot reconciles current ARG, repairs a missed event, preserves delete history, and publishes complete provenance to Fabric.

## Phase 2 — Arc & Update Manager

### Outcome

ArcMachine and Patch context linked to resources/applications without replacing Arc or Update Manager.

### Reusable components

- Phase 1 ARG adapter/query pack.
- ARG resource types and Update Manager extension tables.
- AIOps cron/webhook/reconciliation framework.
- Azure MCP group listing for targeted inspection only.
- Steward confidence/lifecycle contracts.

### New code/configuration required

- Arc machine mapping for `Microsoft.HybridCompute/machines` and connectivity/status fields.
- Update Manager assessment/install query mappings (`patchassessmentresources`, `patchinstallationresources`) and patch identity normalization.
- Patch applicability versus requested/executed/successful state model.
- Arc/Update-specific freshness and retention policy.

### Risks

- No native Azure MCP Arc or Update Manager namespace in current discovery.
- Arc agent/status and patch-assessment cadence are not continuous.
- OS/package identifiers differ and can collide without namespacing.
- Update history retention may require an approved additional source.

### Complexity

**M–L**.

### Exit gate

Representative Azure and Arc machines reconcile with Update Manager and expose assessment age, missing patches, install results, and no false mitigation claims.

## Phase 3 — LAW & Application Insights

### Outcome

Observed `calls`, `connectsTo`, `hosts`, and `dependsOn` relationships for SQL, Storage, Key Vault, Service Bus, and AKS-hosted applications.

### Reusable components

- Azure MCP Monitor tools: workspace/table discovery, bounded KQL, metrics, activity logs.
- Direct Azure Monitor Query SDK/API for scheduled deterministic queries.
- Existing AIOps cron scripts/monitor mode.
- OpenTelemetry conventions and App Insights data model.
- Delegation for ambiguous endpoint analysis.
- Gateway OTLP monitoring for HOG runtime health.

### New code/configuration required

- Versioned aggregate KQL query pack.
- Application identity resolver and endpoint normalizers for Azure service FQDN/private endpoints.
- Evidence-window aggregation and confidence scoring.
- Labeled evaluation set and calibration reports.
- Source/query cost budgets.

### Risks

- Sampling, delayed ingestion, missing instrumentation, high cardinality.
- Treating OTel/App Insights/LAW as independent corroboration.
- False dependencies from retries, health checks, control-plane calls, shared gateways.
- Application identity drift.

### Complexity

**XL** — inference quality and identity resolution dominate.

### Exit gate

Approved precision/recall and direction targets are met on a labeled pilot; raw telemetry remains in Azure Monitor.

## Phase 4 — Defender & Sentinel

### Outcome

Finding and Incident entities linked to affected resources/applications/services with explicit source provenance.

### Reusable components

- LAW KQL path where Sentinel/Defender data already exists.
- Resource/identity resolution from earlier phases.
- AIOps webhooks/cron reconciliation.
- Incident-learning and steward review workflow.
- Azure MCP Resource Health/Advisor for complementary context, not Sentinel/Defender replacement.

### New code/configuration required

- Sentinel management API/source adapter and incident projection.
- Defender for Cloud assessments/ARG/continuous-export adapter selected per deployment.
- Strong/weak Sentinel entity-identifier handling.
- Security field allowlist/redaction and authorization tests.
- Finding/Incident impact confidence policy.

### Risks

- No native Azure MCP Defender/Sentinel namespaces.
- Double-counting LAW/Sentinel/Defender provenance.
- Sensitive security data and cross-workspace/tenant boundaries.
- Defender portal migration/experience changes; APIs must remain the contract.

### Complexity

**L**.

### Exit gate

A security incident traverses to exact affected entities/findings with authorized source links and no raw security payload replication.

## Phase 5 — Business Context

### Outcome

Application, BusinessService, Team, Person, CostCentre, ownership/support relationships, and runbook metadata.

### Reusable components

- AIOps plugin framework and generic webhooks.
- Microsoft Teams gateway and teams_pipeline patterns where operationally useful.
- Entra access through Microsoft Graph adapter.
- Azure DevOps REST/service hooks and existing GitHub/document skills as design patterns.
- Kanban review workflow.
- Built-in/external memory for stable operator preferences only.

### New code/configuration required

- ServiceNow ACL-aware adapter and source-of-truth mapping.
- Microsoft Graph Entra delta/identity adapter.
- Azure DevOps org/project/team/repo/pipeline/work-item adapter.
- Cost-centre source/tag governance mapping.
- Source precedence and ownership review policies.
- Person-data minimization and retention controls.

### Risks

- Organization-specific ServiceNow schema and governance.
- Confusing Entra technical owners/RBAC with operational accountability.
- PII and cross-tenant identity collision.
- Poor tag quality and multiple business authorities.

### Complexity

**XL** — semantic governance, not API mechanics, is the critical path.

### Exit gate

Pilot BusinessService has accepted support/dependency/owner paths, finance context, and no name-only identity merges.

## Phase 6 — Incident Learning

### Outcome

Accepted FailurePattern, RootCause, impact, and mitigation knowledge learned from Sentinel, ServiceNow, RCA, postmortem, Azure DevOps, and runbook sources.

### Reusable components

- Incident projections from Phase 4.
- `document-to-action-items`, `meeting-action-items`, `teams-meeting-pipeline`, `grounded-citations`, and OCR/document skills.
- AIOps agents/delegation for candidate extraction.
- Kanban for causal/pattern review.
- Cron/webhooks for lifecycle triggers.
- Session history for resumable investigations.

### New code/configuration required

- Correlation group and explicit-reference resolver.
- Redacted document extraction pipeline.
- RootCause/FailurePattern candidate schema and review lifecycle.
- Runbook suggested/executed/successful state tracking.
- Pattern fingerprinting, merge/split, and evaluation set.

### Risks

- LLM hallucination and prompt injection in source documents.
- Symptom/root-cause confusion.
- False cross-system incident merges.
- Sensitive ticket/RCA content leakage.
- Operational memory becoming a shadow incident store.

### Complexity

**XL**.

### Exit gate

No model-only causal fact is accepted; known incidents retrieve grounded pattern/root-cause/runbook paths with citation and confidence.

## Phase 7 — Foundry Agent Integration

### Outcome

Foundry agents safely consume Fabric context and approved live Azure tools.

### Reusable components

- Bundled `azure-foundry-provider` for model inference where appropriate.
- Microsoft Foundry Agent Service/Fabric IQ tool integration.
- Fabric Ontology preview MCP endpoint as optional consumption adapter.
- AIOps native MCP client/server and tool allowlisting.
- Azure MCP read-only Monitor/Resource Health/Advisor/resource inspection tools.
- Agent evaluation infrastructure and redacted gateway monitoring.

### New code/configuration required

- Agent-safe accepted ontology view.
- Foundry tool definitions/instructions and authorization mapping.
- Separately governed direct ARG/source tools for Azure MCP gaps.
- Response contract: path, confidence, source, source/graph freshness, uncertainty.
- Golden/adversarial evaluation set and query/tool budgets.

### Risks

- Fabric IQ/Ontology and Azure MCP beta/preview lifecycle.
- Permission mismatch between Foundry, Fabric, Azure, and external sources.
- Prompt injection/tool overreach.
- Stale graph represented as live truth.
- Agent schema/token footprint if too many Azure tools are exposed.

### Complexity

**L–XL**, driven by target authorization model and preview readiness.

### Exit gate

Agents meet approved path correctness, provenance, freshness, authorization, refusal, and prompt-injection thresholds. They remain read-only.

## 3. Cross-phase foundation work

Complete before or alongside Phase 1:

1. Approve system-of-record matrix and ontology v1.
2. Threat-model MCP, webhooks, source text, graph poisoning, and identity merging.
3. Decide Fabric preview acceptance/fallback.
4. Establish dev/test/prod isolation and separate managed identities.
5. Build synthetic fixtures and contract/security/data-quality tests.
6. Define SLOs and cost budgets.
7. Pin/test Azure MCP version; do not use `latest` in production.
8. Create architecture decision records for every unsupported/preview assumption.

## 4. Repository placement recommendation

Do not add Azure-specific modules to AIOps core initially.

Recommended delivery form:

- standalone HOG repository or `~/.aiops/plugins/aiops-operations-graph` plugin package;
- project-specific skills/query assets in that repository;
- Azure Function/Logic App infrastructure definitions for event normalization;
- Fabric ontology/OneLake mappings under source control;
- optional MCP server only for structured HOG-specific queries that cannot be expressed by existing MCP/source tools.

Core changes are justified only if a generic plugin/MCP/webhook/cron capability is proven missing and useful beyond Azure HOG.

## 5. Test strategy

- Contract and referential integrity.
- Source paging/throttling/partial-access/schema drift.
- Event replay/out-of-order/missed event.
- Identity merge/split and cross-tenant negative tests.
- Confidence calibration and decay.
- PII/secret/redaction/prompt-injection.
- Fabric binding/refresh/count/path/rollback.
- MCP version/tool compatibility and read-only allowlist.
- Agent grounding/refusal/freshness.
- Representative scale and cost.

## 6. Definition of done

A phase is done only when:

- it reuses an approved existing component where available;
- it introduces no duplicate inventory/monitoring/CMDB/telemetry/incident store;
- source authority and stable identity are preserved;
- every accepted relationship has confidence, source, and timestamps;
- operations are idempotent, observable, secure, and recoverable;
- integration, reconciliation, data-quality, and security tests pass;
- preview assumptions and fallback are documented;
- runbooks and named owners exist.
