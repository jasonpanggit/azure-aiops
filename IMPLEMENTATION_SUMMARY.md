# Implementation Summary

## Delivered

The first AIOps Operations Graph vertical slice is implemented as a standalone, modular AIOps plugin and Python package.

### Azure acquisition

- Uses the official Azure MCP package for authenticated subscription discovery.
- Runs versioned ARG queries for `Resources`, `ResourceContainers`, `ResourceChanges`, `PatchAssessmentResources`, and Advisor recommendations in `advisorresources`.
- Uses `az graph query` only for arbitrary ARG because the tested Azure MCP package has no general ARG query operation.
- Handles ARG continuation tokens and configurable page/page-count limits.

### Processing and persistence

- Normalizes Subscription, Resource Group, Resource, Virtual Machine, Arc Server, Patch Assessment, and Advisor Recommendation entities.
- Generates `belongsTo`, `assessedBy`, and `impacts` relationships with confidence, source, creation, and last-observed metadata.
- Writes owner-only JSONL and Zstandard-compressed Parquet datasets as immutable generations with an atomic `current` switch.
- Generates `ontology.json` from discovered entity properties on every run.
- Tracks successful-run and maximum-observed `ResourceChanges` watermarks with an overlap window in `state/state.json`.
- Accumulates and deduplicates incremental resource-change history.
- Uses semantic hashes for change detection while refreshing observation timestamps, preserves creation timestamps, and rejects concurrent writers.

### AIOps integration

- On-demand: `uv run aiops-inventory sync --config config.yaml`.
- Scheduled: `uv run aiops-inventory schedule --config config.yaml --schedule 'every 30m'`; this creates a script-only AIOps cron job rather than a custom scheduler.
- Primary read-only agent tool: `operations_analysis` in toolset `azure_operational_context`; it consumes the Semantic Knowledge Layer internally.
- Direct Azure-dataset and raw Ontology query tools are no longer registered for agent use.
- Agent responses expose compact validated semantic projections rather than Azure IDs, raw properties, lineage, or Delta rows.

### Production hardening

- Accepts Azure CLI snake_case continuation tokens and tests multi-page traversal.
- Filters patch child rows so only assessment summaries become ontology entities.
- Drops relationships whose endpoints were not discovered in the same graph projection.
- Publishes complete immutable generations under owner-only permissions and atomically switches `current`.
- Disables sensitive raw query datasets by default and makes retention explicit.
- Removes caller-selected data roots from the agent schema and rejects symlink escapes.
- Validates both the atomic `current` pointer and every dataset path remain inside the trusted root.
- Loads the AIOps tool without importing ingestion-only PyArrow/PyYAML dependencies.
- Uses a preinstalled Azure MCP executable by default, parallel ARG queries, and bounded command timeouts.

## Verification performed

- Current unit and mock integration suite: 561 tests passed.
- Ruff static analysis and Bandit security scanning passed with no findings.
- Source distribution and wheel builds succeeded; the wheel installed into a clean Python 3.11 virtual environment and exposed the `aiops-inventory` CLI.
- AIOps directory-plugin loading registers only `operations_analysis`; Semantic/Fabric diagnostics and synchronization remain operator CLI/API functionality.
- A schedule integration check in an isolated temporary `AIOPS_HOME` created an active script-only 30-minute AIOps cron job and executable wrapper.
- Live Azure MCP subscription discovery succeeded.
- Live ARG ingestion completed for one configured subscription.
- Live result set contained 71 resources, six resource containers, 104 accumulated changes, two patch-assessment summaries, and 125 Advisor recommendations.
- Live hardened output contained 155 relationships, all with endpoints present in the generated entity datasets; files were mode `0600` under a mode `0700` root.
- A third unchanged live run returned `changedDatasets: []`, demonstrating idempotency after the incremental watermark settled.
- All four agent questions executed against the live normalized datasets.

## Explicit boundary

The implemented scope now includes OneLake/Lakehouse persistence, Fabric Ontology binding, deterministic semantic knowledge models, retrieval, impact analysis, search, risk scoring, and the read-only Operations Agent for evidence-backed reasoning and recommendations. Chat/copilot experiences, memory, autonomous actions, multi-agent orchestration, and remediation remain intentionally out of scope.

## Operating System Lifecycle Intelligence

- Adds a governed 29-entry vendor lifecycle catalog for Windows Server, SQL Server, Ubuntu, RHEL, Debian, Azure Stack HCI, Azure Local, and Kubernetes, with updateable Metadata Lakehouse and Ontology projections.
- Classifies Supported, Approaching EOL, Near EOL, Critical, EOL, and Unknown states using configurable thresholds and explicit support-channel policy.
- Correlates lifecycle and Patch Intelligence posture through public Semantic Layer APIs into explainable 0–100 risk, business impact, exposure, lifecycle debt, modernization priority, and 30/90/180-day trends.
- Exposes eight bounded lifecycle commands and six executive/operational reports through the existing read-only Operations Agent; recommendations are advisory and execute no upgrade, remediation, or change action.
- Preserves one lifecycle observation per resource per sync even for same-second runs, rejects exact duplicate history identities, and aliases raw subscription identifiers before public reporting.
- Documents architecture, workflow, risk and prioritization models, configuration, examples, and operations in `docs/LIFECYCLE_INTELLIGENCE.md`, `docs/LIFECYCLE_INTELLIGENCE_CONFIG.md`, and `docs/LIFECYCLE_INTELLIGENCE_RUNBOOK.md`.

## Incident Correlation and Operational Causality

- Correlates governed incidents and alerts with ARG resource changes, explicit patch failures, lifecycle posture, Semantic dependencies, ownership, support teams, and business-service mappings.
- Ranks evidence with a deterministic 0–100 causal-evidence model and capped confidence; outputs remain probabilistic and never assert confirmed root cause.
- Distinguishes probable causes, contributing factors, post-incident context, and noncausal lifecycle posture.
- Produces bounded blast-radius, business-impact, recurring-pattern, operational-causality, and executive reports.
- Retains seven original `IncidentPortfolio` commands and adds eight requested incident/portfolio reasoning commands with read-only, advisory-only contracts.
- Validates and deduplicates incident/evidence/history identities, canonicalizes resource IDs, redacts embedded operational identifiers, caps nested strings/collections/items, and enforces a serialized response limit.
- Documents architecture, configuration, operations, examples, and testing in `docs/INCIDENT_CAUSALITY.md`, `docs/INCIDENT_CAUSALITY_CONFIG.md`, and `docs/INCIDENT_CAUSALITY_RUNBOOK.md`.
- Adds the requested eight-module `src/intelligence/incidents/` framework, normalized operational events, deterministic timelines, expanded root-cause reasoning, dependency-tree blast radius, audience-specific summaries, and first-class incident causality ontology entities.
- Detects repeated patch/lifecycle risks, ownership gaps, subscription degradation, recurring risks, and chronic configuration contributors while keeping every conclusion evidence-backed and probabilistic.

## Change and Configuration Intelligence

- Correlates ARG ResourceChanges with governed policy, security baseline, network, identity, IaC, incident, configuration, and Semantic operational context.
- Explains what changed, evidence-backed actor or Unknown attribution, timestamp, source, drift, compliance, risk, and probabilistic incident contribution.
- Adds deterministic 0–100 change risk, exact expected-vs-observed drift analysis, resource compliance, and 30/90/180-day trends.
- Retains eight original bounded Change Intelligence command aliases and five original reports without remediation, infrastructure changes, rollback, or deployment capability.
- Validates canonical identities and timestamps, rejects duplicate changes/incidents/deviations, ignores inactive deviations, bounds nested output, enforces a serialized response cap, and redacts literal/percent/base64/hex identifiers and GUIDs.
- Documents architecture, configuration, operational verification, and testing in `docs/CHANGE_INTELLIGENCE.md`, `docs/CHANGE_INTELLIGENCE_CONFIG.md`, and `docs/CHANGE_INTELLIGENCE_RUNBOOK.md`.
- Adds the requested eight-module enterprise framework, first-class change/baseline/drift/deviation/authorization ontology entities, named network/identity/ownership/tag/policy drift, four timeline windows, and application/service/subscription compliance.
- Registers ten requested `ChangePortfolio` commands in both the Operations Agent and AIOps plugin schema while retaining prior aliases.

## Predictive Operations Intelligence

- Produces explainable 30-, 60-, and 90-day scenario-risk projections for workload failure, incident likelihood, patch-debt growth, lifecycle exposure, configuration drift, compliance degradation, and ownership risk.
- Aggregates resource forecasts into application instability, business-service risk, and operational-debt views using governed Fabric and public Semantic context only.
- Integrates Patch, Lifecycle, Incident, and Change posture through canonical internal identities without querying Azure directly or exposing resource identifiers publicly.
- Retains eight original read-only predictive command aliases and six bounded executive/operational reports.
- Adds the requested nine-module framework, privacy-safe subscription/resource-group/environment forecasts, explicit VM and Arc risk models, five-category operational debt, Advisor exposure, evidence-weighted incident estimates, and predictive ontology projections.
- Exposes the ten requested commands, including application-scoped risk lookup, while retaining the earlier command aliases for compatibility.
- Labels confidence as evidence sufficiency rather than calibrated probability and keeps all intervention guidance advisory-only.
- Fails closed on malformed bounds, canonical aliases, duplicate or future history, empty evidence, nested identifier encoding, and truncated portfolio output.
- Documents architecture, configuration, operations, feature weights, forecast semantics, telemetry, examples, and tests in `docs/PREDICTIVE_OPERATIONS.md`, `docs/PREDICTIVE_OPERATIONS_CONFIG.md`, and `docs/PREDICTIVE_OPERATIONS_RUNBOOK.md`.

## Autonomous Remediation Planning

- Converts governed Patch, Lifecycle, Incident, Change, Predictive, Ontology, and Semantic evidence into approval-ready draft plans without executing infrastructure changes.
- Uses governed declarative action catalogs rather than hardcoded workflows; an empty catalog produces no plans.
- Generates dependency context, four-dimensional risk assessments, configurable approvals, mandatory reversible rollback contracts, simulation estimates, and Priority 1–4 scores.
- Adds remediation ontology entities for plans, approvals, rollback, execution steps, risk, and simulation plus application/service relationships.
- Exposes ten bounded `RemediationPortfolio` Operations Agent commands and six executive planning reports.
- Fails closed on malformed catalogs/policies, duplicate identities, unknown evidence, invalid percentages/bounds, dependency amplification, encoded identifiers, and oversized output.
- Documents workflow, approval model, risk model, rollback framework, prioritization, simulation, examples, configuration, operations, and tests in `docs/REMEDIATION_PLANNING.md`, `docs/REMEDIATION_PLANNING_CONFIG.md`, and `docs/REMEDIATION_PLANNING_RUNBOOK.md`.

## Fabric OneLake persistence increment

Implemented enterprise Lakehouse persistence as the governed foundation for Ontology and semantic retrieval:

- Managed-identity and service-principal authentication with separate Fabric and storage token scopes.
- Workspace/Lakehouse selection by ID or name, optional Lakehouse creation, continuation handling, long-running operations, and transient REST retries.
- OneLake ADLS folder/file operations and canonical Lakehouse `Tables` paths.
- Delta overwrite, append, and merge/upsert with change-version idempotency, run-level append dedupe, partition policy, and transient retry.
- Snapshot overwrite reconciliation removes resources absent from authoritative ARG, including completely empty required tables.
- A local/cloud run lock serializes writers. Pre-publication table failures restore prior Delta versions or remove new tables; committed graph tables are retained across publication/shortcut failures for coherent idempotent retry.
- Fabric LRO result locations, transport retries, immutable GUID OneLake paths, and schema-enabled Lakehouse paths are supported.
- Versioned Arrow contracts back data-quality schema validation.
- Standard Bronze, Silver, Ontology, and metadata structures.
- Required operational columns on all inventory Delta tables.
- Durable `metadata_ingestion_state` and `metadata_quality_reports` tables.
- Source-generation replay and failed-run recovery.
- Required-field, schema, duplicate, orphan-relationship, and subscription-consistency validation.
- Catalog metadata generation, shortcut creation, and Fabric table-registration verification.
- OpenTelemetry duration and row-count instruments.
- AIOps agent/CLI commands for sync, refresh, status, last sync, and validation.

## Microsoft Fabric Operational Context Graph

- Automatic tenant-scoped entity generation for management, infrastructure, operational, application, service, environment, ownership, support, and business context types.
- Case-insensitive tag intelligence with no hardcoded environment or entity values.
- Deterministic structural, tag-derived, compliance, recommendation, ownership, and service relationships with lineage and semantic metadata.
- Incremental graph synchronization, semantic fingerprints, ontology versions, and soft retirement for removed entities and relationships.
- Typed OneLake entity/relationship projections bound to a Microsoft Fabric Ontology item through the documented public-definition REST API.
- Operator graph traversal remains available through `aiops-inventory ontology`; the Operations Agent consumes only governed Semantic Layer APIs.
- Application, infrastructure, and business context views; ontology health and quality Delta reports; OpenTelemetry graph metrics.
- No custom graph database and no Cosmos DB dependency.

Final ontology-enabled local mock verification wrote 76 Delta tables, processed 1,336 rows, generated 215 active entities and 165 active relationships, and reported zero orphan resources or synchronization errors. The live source currently lacks application/owner/service tags for its VM/Arc records, so the four live graph queries correctly returned empty results; tagged sample tests prove non-empty ownership, application, service, and impact traversals. Live Fabric Ontology publication remains tenant-credential verification work.

## Semantic Knowledge Layer

- Thirteen registered domain models: Application, Service, Infrastructure, Compliance, Patching, Ownership, Business Impact, Resource Health, Operational Risk, Dependencies, Lifecycle, Cost, and Security.
- Version-aware active-entity, name, type, relationship, inventory, compliance, security, and cost indexes.
- Reusable application, service, resource, and subscription contexts optimized for future LLM consumption.
- Direction-aware dependency and impact analysis for resources, applications, patch failures, and subscriptions.
- Explainable 0–100 operational risk scoring with Low, Moderate, High, and Critical levels.
- Semantic searches for production applications, ownership/team context, failed patching, ownership gaps, business services, risky services, and critical infrastructure.
- TTL/LRU cache keyed by knowledge version; exact hit/miss ratio available without creating a second system of record.
- OpenTelemetry query, traversal, context-generation, cache, freshness, and Ontology-lag instruments.
- Strict response validation excludes raw payloads and operational identifiers from agent output.

## Operations Agent

- Primary `operations_analysis` agent tool with ten bounded read-only commands for VM, application, subscription, business-service, risk, patch, health, impact, executive-summary, and incident analysis.
- Modular context routing, operational reasoning, health/compliance/ownership/impact/incident analyzers, recommendation engine, and operational summary generator under `src/agents/operations`.
- Deterministic 0–100 health scoring for resource, application, service, subscription, business-service, and environment contexts.
- Evidence-triggered advisory recommendations for ownership, patch, security, high risk, actual cost facts, and lifecycle/obsolete-SKU evidence; no execution or remediation capability.
- Direction-aware dependency and blast-radius analysis, incident-ready context, explicit unknown affected-user estimates, and bounded/truncation-aware output.
- Explainability contracts on every conclusion and recommendation, with no raw Azure/Fabric identifiers or caller-reflected resource IDs.
- OpenTelemetry analysis, recommendation, knowledge-retrieval, impact, and context-generation latency instruments.
- Offline-from-Azure operation over the latest synchronized Fabric Ontology and OneLake-backed Semantic Layer snapshot.
