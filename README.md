# Azure AI Operations Platform

An AI-powered operations platform for Azure that enables operators to move from detected situations to evidence-backed, auditable, human-approved remediation without losing context or control. Built on existing Azure Resource Graph, Fabric Ontology, FastAPI, Entra, and Next.js foundations.

**Core Value:** Operators detect Azure incidents, receive cited evidence and recommendations, approve bounded remediation actions, observe durable execution, and maintain full audit trails.

**Status:** Phase 7 (Unified Resource Inventory) - Planning stage. See [`.planning/STATE.md`](.planning/STATE.md) for roadmap and current progress.

For existing ARG connector capabilities and AIOps integration, see [`docs/PRODUCTION_RUNTIME_ACTIVATION.md`](docs/PRODUCTION_RUNTIME_ACTIVATION.md).

## What is implemented

### Foundation Layer (Phase 1+)
- **Durable situation records** with lifecycle, severity, priority, scope, and ownership
- **Evidence foundation** from Azure Resource Graph, Activity Log, Monitor, Defender, Policy, and vulnerability feeds
- **Normalized entities and relationships** with source traceability and freshness signals
- **Audit trail primitives** for immutable event logging
- **Authorization boundaries** enforced via Entra/RBAC scope

### ARG Connector (Brownfield Foundation)
The existing AIOps Azure Resource Graph connector provides:
- Azure MCP subscription discovery
- ARG extraction and normalization for Resources, ResourceContainers, ResourceChanges, PatchAssessmentResources, and Advisor recommendations
- Normalized entities: Subscription, Resource Group, Resource, Virtual Machine, Arc Server, Patch Assessment, Advisor Recommendation
- Relationships with confidence, source, timestamps
- Atomic JSONL/Parquet publication with idempotent behavior
- Incremental watermarking and accumulated change history
- OneLake/Delta persistence and Fabric Ontology projection
- Read-only agent queries and AIOps plugin integration

See `docs/architecture.md` for architecture diagram and `IMPLEMENTATION_SUMMARY.md` for verification results.

## Important Azure MCP boundary

The preinstalled Azure MCP executable is used for Azure subscription discovery. Its current command surface does not provide a general arbitrary Azure Resource Graph query operation. The five required ARG queries therefore use the installed Azure CLI command `az graph query`. This is a narrow subprocess adapter—not a custom Azure SDK wrapper—and is isolated behind `AzureCliArgClient` so it can be replaced if Azure MCP adds arbitrary ARG support.

## Prerequisites

- Python 3.11+
- `uv` (Python package manager)
- Node.js 18+ and `npm`
- Azure CLI with Resource Graph extension
- Docker (for containerized deployments)
- An Azure identity authenticated for Azure MCP and Azure CLI
- Read permissions for configured subscriptions and ARG tables

Authenticate with your normal enterprise-approved Azure CLI flow before running. No credentials are stored by this project.

## Project Structure

```
.
├── .planning/                      # GSD planning artifacts (roadmap, requirements, state)
├── .github/                        # GitHub configuration and workflows
├── src/
│   ├── onboarding/       # ARG ingestion and connector CLI
│   ├── fabric/                     # Fabric/OneLake persistence and authentication
│   ├── storage/                    # Delta, Parquet, OneLake writers
│   ├── ontology/                   # Fabric Ontology creation and updates
│   ├── semantic/                   # Semantic Knowledge Layer (operations context)
│   ├── agents/                     # Agent reasoning and orchestration
│   ├── api/                        # FastAPI backend for situations, evidence, approvals
│   ├── operations/                 # Operations execution and verification
│   ├── intelligence/               # Intelligence modules (patch, lifecycle, incident, change, predictive)
│   ├── network/                    # Network and dependency graph
│   └── onboarding/                 # Discovery and onboarding workflows
├── web/                            # Next.js frontend (situations, evidence, recommendations, approvals)
├── tests/                          # Test suite (no live Azure credentials required)
├── docs/                           # Architecture, runbooks, and API documentation
├── infra/                          # Infrastructure and deployment templates
├── skills/                         # AIOps skill plugins
├── live-data/                      # Local runtime data (datasets, state, cache)
├── pyproject.toml                  # Python project definition
├── config.example.yaml             # ARG connector configuration template
└── fabric.*.example.yaml           # Fabric persistence configuration templates
```

## Getting Started

### 1. Install dependencies

```bash
uv sync --extra test
cd web && npm install && cd ..
cp config.example.yaml config.yaml
```

### 2. Configure ARG connector

Edit `config.yaml` with your Azure subscription and storage preferences:

```yaml
azure:
  subscriptions: []  # Empty = all subscriptions from Azure MCP
  tenant_id: ""
  mcp_command: ["azmcp"]
  page_size: 1000
  max_pages: 1000
  command_timeout_seconds: 60
  max_query_workers: 5
  change_overlap_minutes: 10
storage:
  output_dir: "./live-data"
  retain_raw_queries: false
```

### 3. Run ARG ingestion

**On demand:**
```bash
uv run aiops-inventory sync --config config.yaml
```

**Scheduled (via AIOps cron):**
```bash
uv run aiops-inventory schedule --config config.yaml --schedule "every 30m"
```

### 4. Sync to Fabric (optional)

```bash
cp fabric.config.example.yaml fabric.config.yaml
# Edit fabric.config.yaml with workspace and Lakehouse IDs
uv run aiops-inventory fabric "Sync Azure inventory to OneLake" --config fabric.config.yaml
```

### 5. Run tests

```bash
uv run --extra test pytest
```

No live Azure credentials required; tests use mock fixtures.

## Important Azure MCP Boundary

The preinstalled Azure MCP executable is used for Azure subscription discovery. Its current command surface does not provide a general arbitrary Azure Resource Graph query operation. The required ARG queries therefore use the installed Azure CLI command `az graph query`. This is a narrow subprocess adapter—not a custom Azure SDK wrapper—and is isolated behind `AzureCliArgClient` so it can be replaced if Azure MCP adds arbitrary ARG support in the future.

## Data Layers

### 1. ARG Ingestion and Normalization
Raw resource and change data from Azure Resource Graph are queried, normalized, deduplicated, and published as JSONL/Parquet datasets with full provenance and freshness signals. See `src/onboarding/` and `src/storage/`.

### 2. Fabric Ontology and OneLake Persistence
Normalized datasets sync to Microsoft Fabric Lakehouse via OneLake, building queryable Delta tables. The Fabric Ontology item creates a semantic authority for entities and relationships.

**Configuration templates:**
- `fabric.config.example.yaml` — managed identity
- `fabric.service-principal.example.yaml` — service principal, secret from environment
- `fabric.local.example.yaml` — local Delta mock with no cloud calls

**Operator commands:**
```bash
uv run aiops-inventory fabric "Sync Azure inventory to OneLake" --config fabric.config.yaml
uv run aiops-inventory ontology "Who owns this VM?" --entity vm-prod-01 --config fabric.config.yaml
uv run aiops-inventory ontology "What applications are affected by patch failures?" --config fabric.config.yaml
```

See `src/fabric/`, `src/storage/`, and `docs/FABRIC_INTEGRATION.md`.

### 3. Semantic Knowledge Layer
The Semantic Layer assembles safe application, service, resource, subscription, ownership, compliance, patching, dependency, impact, risk, lifecycle, cost, security, and health context over Fabric Ontology. Agents receive evidence-backed reasoning through `operations_analysis`.

```bash
uv run aiops-inventory semantic \
  "What is the blast radius of this failure?" \
  --subject vm-identity \
  --config fabric.config.yaml
```

See `src/semantic/` and `docs/semantic-architecture.md`.

### 4. Operations Intelligence
The platform includes specialized intelligence modules for:
- **Patch Intelligence:** Workflow, scoring, prioritization, and compliance
- **Lifecycle Intelligence:** Risk, modernization, exposure, and end-of-support
- **Incident Causality:** Change correlation and causal scoring
- **Predictive Operations:** Forecasts and debt analysis
- **Remediation Planning:** Workflow, approval, risk, rollback simulation

See `src/intelligence/` and corresponding runbooks in `docs/`.

### 5. API and Frontend
- **FastAPI backend** (`src/api/`): REST endpoints for situations, evidence, recommendations, approvals, and execution
- **Next.js frontend** (`web/`): Web UI for operators to investigate, approve, and monitor remediation

## Development Workflow

### Running the ARG connector in development

```bash
# One-time setup
uv sync --extra test
cp config.example.yaml config.yaml

# Run once
uv run aiops-inventory sync --config config.yaml

# Or schedule
uv run aiops-inventory schedule --config config.yaml --schedule "every 30m"

# Query the ontology
uv run aiops-inventory query "Show me all VMs." --output-dir live-data
uv run aiops-inventory query "Show me non-compliant servers." --output-dir live-data
```

### Running the web frontend

```bash
cd web
npm run dev
# Open http://localhost:3000
```

### Running tests

```bash
uv run --extra test pytest -v
```

Test coverage spans ARG extraction, normalization, storage, Fabric sync, AIOps plugin integration, and data quality—all without live Azure credentials.

## AIOps Plugin Integration

The repository registers as a AIOps plugin (`plugin.yaml`, `__init__.py`):
- **CLI commands:** `aiops azure-graph`, `aiops-inventory fabric`, `aiops-inventory ontology`, `aiops-inventory semantic`
- **Agent tool:** `operations_analysis` (read-only reasoning over operational context)
- **Toolset:** `azure_operational_context` (evidence and graph queries)

Set `AIOPS_FABRIC_CONFIG` to the trusted Fabric configuration path. The agent schema cannot supply paths, credentials, workspace IDs, or Lakehouse IDs—all are operator-managed.

## Production Notes

- Restrict Azure RBAC to read-only access at the narrowest subscription scope
- Treat generated raw query datasets as operationally sensitive; protect the data root with the same controls as Azure inventory
- ARG writers use an owner-only local lock; Fabric sync uses OneLake file leases in cloud mode
- Preinstall a pinned Azure MCP build and test before upgrades
- Monitor cron run history and the generated manifest/state files
- Validate Fabric Ontology publication and binding in a credentialed tenant before rollout

## Documentation Index

**Architecture and Design:**
- `docs/architecture.md` — ARG connector architecture
- `docs/fabric-architecture.md` — Fabric persistence architecture
- `docs/ontology-architecture.md` — Ontology and semantic authority design
- `docs/semantic-architecture.md` — Semantic Knowledge Layer design
- `docs/operations-agent-architecture.md` — operations reasoning workflows

**Runbooks and Operations:**
- `docs/FABRIC_RUNBOOK.md` — operations, replay, recovery
- `docs/LOCAL_DEVELOPMENT.md` — mock Fabric development
- `docs/OPERATIONS_AGENT_RUNBOOK.md` — deployment, telemetry, troubleshooting
- `docs/PATCH_INTELLIGENCE_RUNBOOK.md` — patch intelligence deployment
- `docs/LIFECYCLE_INTELLIGENCE_RUNBOOK.md` — lifecycle intelligence operations
- `docs/INCIDENT_CAUSALITY_RUNBOOK.md` — incident correlation verification
- `docs/CHANGE_INTELLIGENCE_RUNBOOK.md` — change tracking verification
- `docs/PREDICTIVE_OPERATIONS_RUNBOOK.md` — forecast verification
- `docs/REMEDIATION_PLANNING_RUNBOOK.md` — remediation operations and testing
- `docs/SEMANTIC_RUNBOOK.md` — Semantic Layer operations

**APIs and Configuration:**
- `docs/OPERATIONS_API.md` — HTTP Operations API, RBAC, error codes
- `docs/SEMANTIC_API.md` — Semantic Knowledge Layer API
- `docs/PATCH_INTELLIGENCE_CONFIG.md` — patch intelligence configuration
- `docs/LIFECYCLE_INTELLIGENCE_CONFIG.md` — lifecycle intelligence configuration
- `docs/INCIDENT_CAUSALITY_CONFIG.md` — incident correlation configuration
- `docs/CHANGE_INTELLIGENCE_CONFIG.md` — change tracking configuration
- `docs/PREDICTIVE_OPERATIONS_CONFIG.md` — predictive operations configuration
- `docs/REMEDIATION_PLANNING_CONFIG.md` — remediation action catalog and policy

**References:**
- `docs/IMPLEMENTATION_SUMMARY.md` — ARG connector verification results
- `REPOSITORY_STRUCTURE.md` — detailed directory layout
- `ARCHITECTURE.md` — project-level architecture overview

## End-to-end architecture

The platform is a Python service and Next.js workbench organized around immutable,
scope-aware data snapshots. Azure services remain the systems of record. The
connector acquires provider data, canonicalizes it, publishes a complete
generation, and exposes that generation to the Fabric projection, semantic
readers, API, agents, and UI.

```text
Azure MCP ── subscription discovery ──┐
Azure CLI `az graph query` ───────────┼─> IngestionService
Azure Monitor Logs / ConfigurationData ┘       │
                                              v
                                   Normalizer + inventory normalization
                                              │
                                              v
                              DatasetStore immutable generation
                              JSONL + Parquet + manifest + current pointer
                                  │                         │
                                  │                         └─> AIOps context queries
                                  v
                         FabricSyncService / DeltaWriter
                                  │
                                  v
                    OneLake Delta tables + persistent Ontology
                        + cached inventory projection
                                  │
                                  v
                         SemanticEngine / provider runtime
                                  │
                         ┌────────┴────────┐
                         v                 v
                    FastAPI API       AIOps agents
                         │             (read-only tools)
                         v
                    Next.js web workbench
```

### Data sources and discovery

- **Azure MCP** (`AzureMcpClient`) discovers the subscriptions available to the
  configured identity. It is not currently the general-purpose ARG query
  interface.
- **Azure Resource Graph** is queried through the installed Azure CLI command
  `az graph query`, isolated behind `AzureCliArgClient`. The query catalog covers
  resource containers, resources, changes, patch assessments, advisor data, and
  other configured ARG families.
- **Azure Monitor Logs** supplies `ConfigurationData` for installed software.
  `IngestionService` queries only server-owned workspace mappings for the active
  connection; browser-selected workspaces are not accepted.
- **Cost Management** is an optional, best-effort side channel. Its failure
  degrades cost data to an empty result and does not block discovery.

`IngestionService` coordinates subscription resolution, query execution,
watermarks, independent source status, normalization, and publication. The
normalizer emits canonical entities and relationships, while
`inventory_normalize.py` performs exact resource-ID joins for software and
preserves raw software identity and unlinked rows rather than inferring joins
from hostnames.

### Unified resource inventory and semantic modelling

The current implementation publishes inventory observations alongside the
established graph in the same immutable generation:

- `inventory/os_observations` contains normalized machine observations.
- `inventory/software_observations` contains normalized installed-software
  observations.
- `inventory/source_status` and `inventory/software_source_status` retain
  readiness, partial, degraded, or unavailable source state.
- A failed software refresh retains the last published software rows while
  keeping the source status degraded or unavailable; a successful empty result
  remains distinguishable from a failed refresh.

`DatasetStore` writes JSONL and Parquet datasets under a run-specific
`generations/` directory, writes a manifest and content hashes, and atomically
activates the generation. Local storage uses a directory symlink; OneLake
storage uses a `current.json` generation pointer because OneLake does not
provide the local symlink behavior. The store retains the most recent three
generations. These mechanisms provide a consistent read snapshot and make
freshness, watermarks, and source status available to consumers.

`FabricSyncService` maps the active inventory snapshot into validated OneLake
Delta tables using `InventoryDatasetMapper`, `DeltaWriter`, and `OneLakeWriter`.
OneLake is the persistent analytical layer for the Fabric Ontology and the
cached inventory that the Unified Resource Inventory publishes. The service
also validates and synchronizes ontology entities and relationships, retaining
removed records as retired records. Fabric/OneLake is therefore the durable
query and cache layer, not the Azure system of record or the owner of inventory
acquisition.

`SemanticEngine` is a read-only knowledge interface over the Fabric Ontology
projection. It indexes entities, relationships, inventory, compliance, security,
and cost rows and applies bounded traversal, validation, caching, freshness, and
telemetry. Assessment domains such as patching, vulnerability, policy, advisor,
metrics, and health retain their own data planes and join to inventory by
resource ID; inventory owns resource identity facts such as type, location,
tags, containment, and raw properties.

### API, web, and agents

The FastAPI application in `src/api/` authenticates requests, enforces Entra/RBAC
scope, routes to providers, and translates failures into stable error responses.
Successful responses use an envelope containing `data`, `evidence`, and `scope`.
The inventory router resolves the server-side `InventoryService` provider and
serves OS groups, OS detail, lifecycle review/confirmation, software groups,
software mappings, and deterministic inventory narrative data.

The Next.js 14 App Router application in `web/` is an operator workbench. MSAL
provides browser authentication when configured; local development can use the
explicit dev-token path. Typed API clients send scope and correlation
information to the backend. Fluent UI components render health, search,
investigation, inventory, approvals, and other API-backed views. The web layer
does not query Azure or Fabric directly and does not fabricate unavailable
capabilities.

AIOps integration is provided by `plugin.yaml`, `__init__.py`, and
`src/onboarding/plugin.py`. The `operations_analysis` tool and the
`azure_operational_context` toolset provide read-only operational reasoning.
Current context-query helpers read the published snapshot and support a bounded
set of operational questions; they are not a write or remediation authority.
Agents consume governed context and cannot supply storage paths, workspace IDs,
Lakehouse IDs, or credentials through their tool schema.

### Ownership boundaries and delivery status

The code currently has a single ingestion/publish path: ARG discovery,
ConfigurationData enrichment, normalization, and inventory projection are
coordinated by `IngestionService`, then published by `DatasetStore`. The
following boundaries are the approved evolution of that path:

- **Phase 7 — Unified Resource Inventory:** extract inventory into an
  independent domain that owns acquisition, normalization, retention, status,
  and publication into the persistent OneLake/Fabric cache, and generalize it
  to resource families including PaaS.
  The characterization tests and extraction/inversion work for this boundary
  are planned; the current co-located projection is not evidence that the
  extraction is complete.
- **Phase 8 — Resource identity plane:** migrate AIOps discovery and semantic
  modelling to the inventory resource contract. `ResourceObservation` must be
  lossless for raw properties and per-family watermarks. Until that contract
  and migration are implemented, AIOps still contains its existing ARG
  connector path.
- **Phase 9 — API, agents, and web pivot:** rewire consumers to the unified
  inventory provider. Existing API routers already resolve providers, but the
  consumer migration and the full web impact review are planned rather than
  complete.

Remediation remains a separate, human-approved capability. The inventory and
semantic layers provide evidence and context; they do not themselves execute
Azure changes. Live Azure walkthroughs and final end-to-end verification remain
deployment/test activities, not claims of the local fixture test suite.
