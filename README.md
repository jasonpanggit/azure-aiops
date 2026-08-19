# Hermes Azure Resource Graph Connector

First end-to-end slice of Hermes Operations Graph: discover Azure subscriptions through Azure MCP, query Azure Resource Graph, normalize operational entities and relationships, write Fabric-aligned JSONL/Parquet datasets, and expose read-only agent questions.

## What is implemented

- Azure MCP subscription discovery through pinned `@azure/mcp`.
- ARG extraction for:
  - `Resources`
  - `ResourceContainers`
  - `ResourceChanges`
  - `PatchAssessmentResources`
  - Advisor recommendations from `advisorresources`
- Normalized entities:
  - Subscription
  - Resource Group
  - Resource
  - Virtual Machine
  - Arc Server
  - Patch Assessment
  - Advisor Recommendation
- Relationships: `belongsTo`, `assessedBy`, and `impacts`, each with confidence, source, created timestamp, and last-observed timestamp.
- Atomic JSONL and Parquet publication.
- Automatic ontology metadata generation.
- Incremental `ResourceChanges` watermarking and accumulated change history.
- Content hashes, change detection, and idempotent dataset publication.
- On-demand CLI, Hermes cron scheduling, and a read-only Hermes agent tool.

See `docs/architecture.md` for the Mermaid architecture diagram and `IMPLEMENTATION_SUMMARY.md` for the executed verification results.

## Important Azure MCP boundary

The preinstalled Azure MCP executable is used for Azure subscription discovery. Its current command surface does not provide a general arbitrary Azure Resource Graph query operation. The five required ARG queries therefore use the installed Azure CLI command `az graph query`. This is a narrow subprocess adapter—not a custom Azure SDK wrapper—and is isolated behind `AzureCliArgClient` so it can be replaced if Azure MCP adds arbitrary ARG support.

## Prerequisites

- Python 3.11+
- `uv`
- Node.js and `npx`
- Azure CLI with the Resource Graph extension/command available
- An Azure identity authenticated for both Azure MCP and Azure CLI
- Read permissions for the configured subscriptions and ARG tables

Authenticate with your normal enterprise-approved Azure CLI flow before running. No credentials are stored by this project.

## Setup

```bash
uv sync --extra test
cp config.example.yaml config.yaml
```

Edit only the project-local `config.yaml`:

```yaml
azure:
  # Empty means all subscriptions returned by Azure MCP.
  subscriptions: []
  tenant_id: ""
  mcp_command: ["azmcp"]
  page_size: 1000
  max_pages: 1000
  command_timeout_seconds: 60
  max_query_workers: 5
  change_overlap_minutes: 10
storage:
  output_dir: "./data"
  retain_raw_queries: false
```

Preinstall, pin, and verify Azure MCP during image/deployment creation. Scheduled runs must not download npm packages. A development environment can explicitly set `mcp_command` to a pinned `npx` command, but production should use the preinstalled `azmcp` executable.

## Run on demand

```bash
uv run hermes-arg sync --config config.yaml
```

The command prints a manifest containing row counts, semantic hashes, changed datasets, run ID, and subscription scope.

## Schedule with Hermes

Reuse the existing durable Hermes scheduler:

```bash
uv run hermes-arg schedule \
  --config config.yaml \
  --schedule "every 30m"
```

This installs a restricted wrapper at `$HERMES_HOME/scripts/azure-resource-graph-sync.sh` and creates a script-only, local-delivery Hermes cron job. It does not create another polling framework.

Inspect or operate the job with:

```bash
hermes cron list
hermes cron status
```

## Query operational context

```bash
uv run hermes-arg query "Show me all VMs." --output-dir data
uv run hermes-arg query "Show me non-compliant servers." --output-dir data
uv run hermes-arg query "Show servers approaching OS EOL." --output-dir data
uv run hermes-arg query "Show patch failures." --output-dir data
```

The query surface returns concise operational fields and intentionally excludes full raw Azure `properties` documents.

OS-EOL answers are evidence-based: this slice returns servers linked to matching Advisor recommendations. An empty result means no matching current recommendation was found; it is not proof that every operating system is supported.

## Hermes plugin integration

The repository root contains `plugin.yaml` and `__init__.py`. The plugin registers:

- CLI command: `hermes azure-graph`
- Primary read-only reasoning tool: `operations_analysis`
- Toolset: `azure_operational_context`

The plugin depends on `pyarrow` and `PyYAML`; install the Python project into the same Hermes environment or package it as part of deployment. Hermes manifest dependency metadata documents these dependencies but does not substitute for environment provisioning.

Enable only the `azure_operational_context` toolset for agents that need this data. The tool is read-only.

Set `HERMES_FABRIC_CONFIG` on the Hermes gateway to the single trusted Fabric runtime configuration. Its operator-managed `source_data_root` remains subject to the trusted-root and symlink-boundary checks; the semantic agent schema cannot supply paths, credentials, workspace IDs, or Lakehouse IDs. Plugin discovery/tool registration remains available without importing PyArrow or PyYAML; ingestion CLI commands require the declared dependencies.

## Sample dataset

The deterministic mock ARG response is:

`tests/fixtures/mock_arg_responses.json`

Generate sample JSONL/Parquet and ontology outputs:

```bash
uv run hermes-arg sample \
  --fixture tests/fixtures/mock_arg_responses.json \
  --output-dir sample-data
```

## Output layout

```text
<data-root>/
├── current -> generations/<run-id>/
├── generations/
│   └── <run-id>/
│   ├── changes/resource_changes.{jsonl,parquet}
│   ├── entities/<EntityType>.{jsonl,parquet}
│   ├── ontology/ontology.json
│   ├── relationships/relationships.{jsonl,parquet}
│   └── manifest.json
└── state/
    ├── dataset_hashes.json
    ├── run.lock
    └── state.json
```

`changes/resource_changes` retains accumulated, deduplicated incremental history. Entity and relationship datasets are the Fabric-aligned projection. Raw `queries/` datasets are disabled by default because source properties can be sensitive; set `retain_raw_queries: true` only in a separately governed data root.

## Incremental and idempotent behavior

1. `state/state.json` supplies the maximum successfully observed `ResourceChanges` timestamp.
2. The next resource-change query applies a configurable overlap before that watermark to tolerate delayed events.
3. New change rows merge by stable source ID into retained change history.
4. All datasets receive semantic content hashes that exclude run-only timestamps.
5. A complete owner-only generation is written before an atomic `current` symlink switch; semantic `changedDatasets` remains empty when only observation timestamps advance.
6. A cross-process writer lock rejects overlapping cron/on-demand runs, and state advances only after every query, normalization, and generation publication step succeeds.

Full inventory-style tables are refreshed each run because ARG remains authoritative. `ResourceChanges` provides event history and change evidence rather than replacing reconciliation.

## Tests

```bash
uv run --extra test pytest
```

Test layers:

- Query catalog and incremental filters: `tests/test_queries.py`
- Azure MCP/ARG command adapters and pagination: `tests/test_azure_clients.py`
- Entity and relationship normalization: `tests/test_normalize.py`
- JSONL/Parquet/ontology publication and idempotency: `tests/test_storage.py`
- Mock end-to-end ingestion and incremental history: `tests/test_service.py`
- Agent questions and response minimization: `tests/test_agent_queries.py`
- Hermes plugin and cron command integration: `tests/test_plugin_schedule.py`
- Fabric REST/authentication: `tests/test_fabric_client.py`
- OneLake folders/files: `tests/test_onelake_writer.py`
- Delta overwrite/append/merge/retry: `tests/test_delta_tables.py`
- Incremental/replay/recovery/registration: `tests/test_incremental_sync.py`
- Data quality: `tests/test_data_quality.py`

No live Azure credentials are required by the automated tests.

## Repository structure

```text
.
├── __init__.py                     # Hermes directory-plugin entry point
├── hermes_plugin.py                # Import-friendly plugin facade
├── plugin.yaml                     # Hermes plugin manifest
├── pyproject.toml
├── config.example.yaml
├── fabric.config.example.yaml
├── fabric.service-principal.example.yaml
├── fabric.local.example.yaml
├── src/hermes_arg_connector/
│   ├── agent_queries.py
│   ├── azure.py
│   ├── cli.py
│   ├── config.py
│   ├── locking.py
│   ├── normalize.py
│   ├── ontology.py
│   ├── plugin.py
│   ├── queries.py
│   ├── schedule.py
│   ├── service.py
│   ├── source.py
│   ├── state.py
│   └── storage.py
├── src/fabric/
│   ├── auth.py
│   ├── fabric_client.py
│   ├── workspace_manager.py
│   ├── lakehouse_manager.py
│   ├── data_quality.py
│   ├── dataset_mapper.py
│   ├── sync_service.py
│   ├── telemetry.py
│   └── commands.py
├── src/storage/
│   ├── onelake_writer.py
│   ├── delta_writer.py
│   ├── parquet_writer.py
│   └── partitioning.py
├── tests/
│   ├── fixtures/mock_arg_responses.json
│   ├── test_config.py
│   └── test_*.py
├── docs/architecture.md
└── IMPLEMENTATION_SUMMARY.md
```

## Microsoft Fabric OneLake persistence

The connector can persist every normalized generation into queryable Delta tables in a Fabric Lakehouse.

Configuration templates:

- `fabric.config.example.yaml` — managed identity
- `fabric.service-principal.example.yaml` — service principal, secret from environment
- `fabric.local.example.yaml` — local Delta mock with no cloud calls

Run the required command through the operator CLI (it is intentionally not exposed as an agent tool):

```bash
uv run hermes-arg fabric \
  "Sync Azure inventory to OneLake" \
  --config fabric.config.yaml
```

Other supported commands:

```text
Refresh inventory lakehouse
Show ingestion status
Show last Fabric sync
Validate inventory data
```

Set `HERMES_FABRIC_CONFIG` to the trusted configuration path for Hermes agent use. The agent schema cannot override credentials, source roots, workspace IDs, or Lakehouse IDs.

Fabric persistence artifacts:

- `src/fabric/auth.py`, `fabric_client.py`, `workspace_manager.py`, `lakehouse_manager.py`
- `src/storage/onelake_writer.py`, `delta_writer.py`, `parquet_writer.py`, `partitioning.py`
- `docs/fabric-architecture.md` — architecture diagram
- `docs/fabric-data-flow.md` — data-flow diagram and table layout
- `docs/FABRIC_RUNBOOK.md` — operations, replay, and recovery
- `docs/LOCAL_DEVELOPMENT.md` — mock Fabric development

The persistence slice remains limited to Fabric-native operational storage and synchronization; the completed read-only Semantic Knowledge Layer above Fabric Ontology is documented below. Multi-agent orchestration, Copilot experiences, remediation workflows, and autonomous actions remain intentionally out of scope.

## Microsoft Fabric Operational Context Graph

Every Fabric synchronization builds tenant-scoped entities, discovers structural and tag-derived relationships, versions and soft-retires graph records, writes typed OneLake Delta projections, and creates or incrementally updates a Fabric Ontology item through the public definition API. Fabric Ontology—not a custom graph database—is the semantic authority.

```bash
uv run hermes-arg fabric "Sync operational ontology" --config fabric.config.yaml
uv run hermes-arg ontology "Who owns this VM?" --entity vm-prod-01 --config fabric.config.yaml
uv run hermes-arg ontology "What applications are affected by patch failures?" --config fabric.config.yaml
```

Operator-level Ontology and Semantic Layer CLIs remain available, while agents receive evidence-backed reasoning through `operations_analysis`. See:

- `docs/ontology-architecture.md`
- `docs/ontology-model.md`
- `docs/FABRIC_ONTOLOGY_DEPLOYMENT.md`
- `docs/ONTOLOGY_RUNBOOK.md`

## Production notes

- Restrict Azure RBAC to read-only access at the narrowest subscription scope.
- Treat generated raw query datasets as operationally sensitive; protect the data root with the same controls as Azure inventory.
- ARG writers use an owner-only local lock. Fabric sync uses the same local lock in mock mode and an infinite OneLake file lease in cloud mode. Failures before the publication boundary roll Delta tables back; after catalog/registration commit, graph tables are retained for idempotent Ontology publication retry so a published definition is never left pointing at rolled-back data.
- Preinstall a pinned Azure MCP build and test before upgrades.
- Monitor cron run history and the generated manifest/state files.
- Live Fabric Ontology publication and binding must be validated in a credentialed tenant before rollout; AI reasoning, copilots, and remediation remain outside this slice.

## Semantic Knowledge Layer

The Semantic Layer is the primary operational knowledge interface for future agents. It assembles safe application, service, resource, subscription, ownership, compliance, patching, dependency, impact, risk, lifecycle, cost, security, and health context over Fabric Ontology.

```bash
uv run hermes-arg semantic \
  "What is the blast radius of this failure?" \
  --subject vm-identity \
  --config fabric.config.yaml
```

The plugin exposes only `operations_analysis` for read-only agent reasoning. It consumes the Semantic Knowledge Layer internally; direct Semantic, Azure dataset, Delta, Ontology traversal, Fabric mutation, and remediation tools are not registered for agents.

Operations Agent documentation:

- `docs/operations-agent-architecture.md` — architecture, workflows, health model, recommendations, and incident examples
- `docs/OPERATIONS_AGENT_RUNBOOK.md` — deployment, telemetry, smoke tests, and troubleshooting
- `docs/PATCH_INTELLIGENCE.md` — patch workflow, scoring, prioritization, queries, and reports
- `docs/PATCH_INTELLIGENCE_RUNBOOK.md` — patch intelligence deployment and operations
- `docs/PATCH_INTELLIGENCE_CONFIG.md` — governed input and runtime configuration
- `docs/patch-intelligence-architecture.html` — interactive architecture diagram
- `docs/LIFECYCLE_INTELLIGENCE.md` — lifecycle workflow, risk, modernization, exposure, and reports
- `docs/LIFECYCLE_INTELLIGENCE_RUNBOOK.md` — lifecycle deployment, catalog updates, monitoring, and recovery
- `docs/LIFECYCLE_INTELLIGENCE_CONFIG.md` — catalog, thresholds, matching, bounds, and authorization
- `docs/lifecycle-intelligence-architecture.html` — interactive lifecycle architecture diagram
- `docs/INCIDENT_CAUSALITY.md` — incident correlation workflow, causal scoring, patterns, and reports
- `docs/INCIDENT_CAUSALITY_CONFIG.md` — governed inputs, bounds, and runtime configuration
- `docs/INCIDENT_CAUSALITY_RUNBOOK.md` — verification, monitoring, and troubleshooting
- `docs/incident-causality-architecture.html` — interactive incident causality architecture diagram
- `docs/CHANGE_INTELLIGENCE.md` — change, drift, risk, incident contribution, and reports
- `docs/CHANGE_INTELLIGENCE_CONFIG.md` — governed change sources and runtime bounds
- `docs/CHANGE_INTELLIGENCE_RUNBOOK.md` — operational verification and troubleshooting
- `docs/change-intelligence-architecture.html` — interactive change intelligence architecture diagram
- `docs/PREDICTIVE_OPERATIONS.md` — predictive features, horizons, debt, explainability, and reports
- `docs/PREDICTIVE_OPERATIONS_CONFIG.md` — governed predictive inputs and runtime bounds
- `docs/PREDICTIVE_OPERATIONS_RUNBOOK.md` — forecast verification and troubleshooting
- `docs/predictive-operations-architecture.html` — interactive predictive architecture diagram
- `docs/REMEDIATION_PLANNING.md` — planning workflow, approval, risk, rollback, simulation, prioritization, and examples
- `docs/REMEDIATION_PLANNING_CONFIG.md` — governed action catalog, approval policy, and runtime bounds
- `docs/REMEDIATION_PLANNING_RUNBOOK.md` — operations, catalog promotion, monitoring, and testing
- `docs/remediation-planning-architecture.html` — interactive remediation planning architecture diagram

- `docs/semantic-architecture.md`
- `docs/SEMANTIC_API.md`
- `docs/RISK_SCORING.md`
- `docs/SEMANTIC_RUNBOOK.md`
