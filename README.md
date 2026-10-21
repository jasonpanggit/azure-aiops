# Azure AI Operations Platform

An Azure operations workbench that connects resource inventory, operational
evidence, Microsoft Fabric, and AI-assisted investigation. Operators can inspect
scope-aware findings, review cited recommendations, approve supported remediation,
and follow durable execution and verification records.

The repository includes a **Python/FastAPI backend**, a **Next.js 14 / React 18
frontend**, an **Azure Resource Graph connector**, **OneLake/Delta publication**,
and **governed Operations Copilot and ontology workflows**.

Implementation is not the same as live qualification: available data, credentials,
provider configuration, rollout settings, and release evidence determine which
capabilities are usable in an environment. See [delivery boundaries](#delivery-boundaries)
and [planning state](.planning/STATE.md) for outstanding acceptance gates.

## Current capabilities

| Area | Implemented surfaces |
| --- | --- |
| Connections and inventory | Subscription onboarding, credential references, validation, connection-scoped sync, resource catalog, OS/software observations, lifecycle review, and Fabric publication |
| Operations workbench | Overview, resource health, situations, investigations, service portfolio/reliability, change analysis, and operational twin |
| Exposure and security | Generation-pinned Exposure queries, CVE/KB detail, patch priorities, Defender posture, vulnerability intelligence, and review-only container remediation handoffs |
| Network | Scope-aware topology, private-link and service dependencies, evidence drawers, exports, and bounded contextual Insights |
| Governance | Identity, governance, compliance, FinOps, and evidence-backed risk/review projections |
| Copilot and agents | Page-bound Insights and follow-ups, durable threads, specialist tools, canonical orchestration, explicit compatibility/shadow/canary/default rollout modes, and evaluation tooling |
| Remediation | Separate approve/operate permissions, evidence-bound approvals, durable attempts, bounded retries, verification deadlines, reconciliation, and audit lineage for supported action families |
| Fabric and ontology | Typed Delta tables, generation-aware readers, SQL-backed analytical reads, governed discovery/publication, native ontology-agent navigation, and separately gated maintenance |

Missing, stale, degraded, and unavailable sources remain distinct from successful
empty results. An AI recommendation, a rendered page, or an HTTP 200 response is
not evidence that a cloud action ran or a downstream model refreshed.

## Architecture

```text
Azure MCP subscription discovery + Azure CLI Resource Graph
Azure Monitor / Defender / Policy / Cost and configured intelligence feeds
                              |
                Registered connection acquisition
               + inventory and domain normalization
                              |
             Immutable datasets, manifests, source status
                              |
          OneLake / Delta: inventory, ontology, Silver / Gold
                              |
       Generation-aware readers + semantic / live providers
                              |
                   FastAPI Operations API
                              |
          Next.js workbench + governed Copilot / agent tools

Separate control paths:
  reviewed approvals -> supported execution -> durable verification / audit
  ontology coordinator -> deterministic governance -> isolated publisher
  native Fabric agent -> user-reviewed Plan / Act in the Fabric portal
```

### Acquisition and inventory

`src/onboarding/` handles subscription connections, source acquisition, credentials,
and connector commands. Azure MCP discovers subscriptions; arbitrary ARG queries
use the installed Azure CLI `az graph query` adapter in `AzureCliArgClient`.
These are separate interfaces, not an interchangeable general-purpose MCP query.
Production runs should use registered connections and their scoped credentials,
not an unqualified local identity.

Inventory acquisition and publication are implemented in
`src/intelligence/inventory/`. The multi-connection refresh entry point is
`src/api/inventory_orchestration.py`; the CLI delegates selected-connection
refreshes to it. Inventory owns resource identity and observations, while patch,
vulnerability, policy, health, and cost domains retain their own evidence paths.
Software joins use explicit resource IDs rather than inferred hostnames.

Dataset publication retains manifests, hashes, source status, and generation
pointers. Local and OneLake stores use their respective activation mechanisms;
failed source-family acquisition must not silently clear last-known-good data.
OneLake/Fabric is the durable analytical layer, not the Azure system of record.

### Fabric, ontology, and analytical reads

`src/fabric/`, `src/storage/`, and `src/ontology/` provide authentication, Delta
writes, typed schemas, SQL access, and ontology bindings. Generation resolution
and governed discovery live in `src/ontology_discovery/`; semantic context
readers live in `src/semantic/`.

Authoritative ontology publication is separated from proposal generation and API
reads. The native Fabric ontology agent is a distinct delegated-user Plan/Act
experience, not the legacy JSON publisher or an unattended Foundry job. Opening
its configured link neither submits a prompt nor applies a definition.

The typed container-exposure projection includes explicit `registry_resource_id`
and `connection_id` scalars. A separate, request-hash-pinned migration CLI offers
read-only inspection by default and guarded, single-table execution only when
explicitly selected and authorized. Its finite SQL acceptance cutoff is
240 seconds; lease, version, authority, transaction, full-readback, and guarded
rollback checks remain mandatory. Source publication, SQL propagation, native
schema preservation, native consumption, and graph freshness are separate gates.
See the [scalar migration contract](docs/exposure-scalar-migration.md).

### API, web, and AI

`src/api/app.py:create_app` builds the FastAPI application. The API authenticates
requests, applies scope/RBAC checks, resolves providers, and returns success
envelopes containing `data`, `evidence`, and `scope`, with a separate stable error
contract. Interactive API documentation is available at `/docs` when enabled by
the deployment.

The web application uses the Next.js App Router, TypeScript, Fluent UI, and MSAL.
It calls the Operations API rather than directly querying Azure or Fabric.
Development-token authentication is a local-only alternative, not a production
identity mechanism.

Copilot combines bounded, scoped tool results with explicit narration provenance.
Page-bound follow-ups retain the reviewed snapshot and thread revision.
Deterministic or unavailable narration must not be labeled as a successful model
answer. Network **Refresh insights** reviews the current bounded page snapshot;
it does not trigger a subscription sync or execute suggested remediation.
If Network narration is rejected, deterministic evidence and its warning remain.
Inspect `data.synthesis.executive` for that result; a
`provider_error_reason=response_contract` indicates failed response validation,
not necessarily a provider outage.

## Prerequisites

- Python **3.11+** and [`uv`](https://docs.astral.sh/uv/).
- Node.js **20** (the CI version) and npm.
- For live Azure acquisition: Azure CLI with the Resource Graph extension, the
  configured Azure MCP executable, and approved scoped credentials.
- For live Fabric: workspace/Lakehouse configuration, OneLake access, and the
  permissions required by the selected reader or publisher role.
- For Fabric SQL reads: the `fabric-sql` Python extra (`pyodbc`) and Microsoft
  ODBC Driver 18 with its platform dependencies.
- For container deployment: Docker and the infrastructure tooling documented in
  [`infra/README.md`](infra/README.md).

Fixture-backed development does not require Azure credentials. Install and pin
cloud tools before scheduled production runs; do not download executables during
ingestion.

## Quick start: local fixtures

From the repository root:

```bash
uv sync --extra test --extra api
cp web/.env.local.example web/.env.local
cd web
npm ci
```

Keep Azure credential fields in `web/.env.local` unset or at their template
placeholders for fixture mode. Do not copy production credentials or data into
the demo environment.

Start the API from `web/`:

```bash
AIOPS_LOCAL_SEED=1 AIOPS_LOCAL_AUTO_SYNC=0 npm run start:api
```

Start the frontend in a second terminal:

```bash
cd web
npm run dev
```

Open <http://localhost:3000>; the API defaults to
<http://127.0.0.1:8080>. The example's local token is shared by the API startup
script and the server-side development-token route.

**Startup is explicit:** `scripts/start-api.sh` defaults to
`AIOPS_LOCAL_SEED=0` and production runtime mode, not fixture seeding. With
`AIOPS_LOCAL_SEED=1`, it selects demo mode and seeds local data. If all four
`AZURE_*` service-principal values are real, that path registers the connection
instead of the fixture; `AIOPS_LOCAL_AUTO_SYNC=0` prevents automatic discovery.
The script reads `web/.env.local`, so review that file before starting it.

To generate a deterministic standalone snapshot without starting the API:

```bash
uv run aiops-inventory sample \
  --fixture tests/fixtures/mock_arg_responses.json \
  --output-dir sample-data
uv run aiops-inventory query "Show me all VMs." --output-dir sample-data
```

## Connector and Fabric workflows

Copy and review configuration before running live commands:

```bash
cp config.example.yaml config.yaml
```

`config.example.yaml` documents subscription selection, MCP command, query bounds,
Cost Management options, and the output directory. An empty subscription list
uses the subscriptions visible through discovery; use explicit scope when that
is not intended. Credentials should be referenced through the connection
registry's supported secret providers, not embedded in datasets or committed
configuration.

```bash
# Inspect registered connections.
uv run aiops-inventory subscriptions list --config config.yaml

# Live Azure acquisition: writes the configured dataset output.
uv run aiops-inventory sync --config config.yaml

# Refresh inventory for one registered connection.
uv run aiops-inventory inventory-refresh --config config.yaml \
  --connection-id <connection-id>
```

The CLI also supports `subscriptions add`, `validate`, `sync`, `health`,
`identity-evidence`, and metadata updates. Use `--help` for required inputs.
`schedule` installs an AIOps cron job; it is not a local in-process scheduler.

Fabric templates select different operational modes:

| Template | Purpose |
| --- | --- |
| [`fabric.local.example.yaml`](fabric.local.example.yaml) | Local Delta mock with an explicit local OneLake root |
| [`fabric.config.example.yaml`](fabric.config.example.yaml) | Managed-identity Fabric configuration |
| [`fabric.service-principal.example.yaml`](fabric.service-principal.example.yaml) | Service-principal configuration with environment-based secret input |

For a local Fabric exercise, first generate `sample-data` using the fixture
command above; the local template reads that directory:

```bash
cp fabric.local.example.yaml fabric.local.yaml
uv run aiops-inventory fabric "Sync Azure inventory to OneLake" \
  --config fabric.local.yaml
uv run aiops-inventory fabric "Validate inventory data" \
  --config fabric.local.yaml
uv run aiops-inventory semantic "What is the blast radius of this failure?" \
  --subject vm-identity --config fabric.local.yaml
```

The same command with a cloud configuration can publish to Fabric. Review the
target, identity, source generation, and write authority first; a local mock
result does not qualify a live deployment.

## Development and validation

Run backend checks from the repository root:

```bash
uv run --extra test ruff check src tests
uv run --extra test --extra api pytest
```

Run frontend checks from `web/`:

```bash
npm run lint:fix
npm test
npm run build
```

For browser tests, install the required Playwright browser once, then run the
suite against its configured test environment:

```bash
npx playwright install chromium
npm run test:e2e
```

CI runs backend Ruff/pytest, frontend lint/Vitest/build, and Trivy scanning.
Local fixtures and mocks exercise contracts without live credentials; live
scripts and runtime walkthroughs require separately approved environments and
are not implied by passing unit tests. The optional `eval` extra is isolated
from the `api` extra because their AI dependency lines conflict.

## Repository layout

```text
src/
  api/                  FastAPI routers, providers, auth, and orchestration
  onboarding/           Subscription connections, acquisition, and CLI
  intelligence/         Inventory, patch, vulnerability, and other domains
  fabric/               Fabric REST/SQL, schemas, and publication contracts
  fabric_pipelines/     Fabric pipeline definitions and orchestration support
  storage/              Dataset stores, Delta, OneLake, leases, and activation
  ontology/             Ontology models, mappings, and bindings
  ontology_discovery/   Governed discovery, generations, and maintenance
  semantic/             Read-only semantic context and bounded traversal
  operations/           Copilot, specialists, remediation, and verification
  agents/               Agent integrations
  network/              Topology and dependency projections
  situations/           Situation models, persistence, and transitions
  mcp_server/           MCP server integration
web/                    Next.js operator workbench and browser/unit tests
tests/                  Backend tests and deterministic fixtures
scripts/                Local startup, evaluations, and operational validators
infra/                  Terraform and release/deployment scripts
docs/                   Architecture, API contracts, and runbooks
skills/                 AIOps plugin skills
.planning/              Roadmap, phase plans, and acceptance records
```

`plugin.yaml`, `__init__.py`, and `src/onboarding/plugin.py` integrate the
connector with AIOps. `operations_analysis` and `azure_operational_context`
provide read-only reasoning and evidence queries. `AIOPS_FABRIC_CONFIG` selects
the trusted operator-owned configuration; agent inputs do not supply credentials,
storage paths, workspace IDs, or Lakehouse IDs.

## Delivery boundaries

- **Least privilege:** acquisition, API reads, proposal generation, publication,
  approval, and execution have distinct responsibilities. Inventory and semantic
  queries do not themselves authorize remediation.
- **Human control:** approve and operate are separate permissions. Unsupported
  container actions remain review/handoff-only; recommendations are not writes.
- **Evidence preservation:** retain source status, immutable generations,
  transaction receipts, and original IDs/bindings when changing projections or
  ontology definitions. A definition write is not a native-agent execution.
- **Native versus unattended maintenance:** native portal Plan/Act is separate
  from the proposed Foundry-plus-deterministic-governance maintenance path.
  Offline maintenance validators do not admit unattended production authoring.
- **Separate live gates:** exact digest-to-workload traversal, the qualified
  100k benchmark, and live canary/rollback acceptance remain explicit Phase 4
  gates. Source publication or an additive native schema update does not close
  them or establish runtime/graph freshness.
- **Release discipline:** validate the exact source, build immutable images, and
  verify deployed state. Do not treat historical planning summaries or local
  fixture results as current production evidence.

## Documentation

| Topic | Reference |
| --- | --- |
| Local development and mock Fabric | [Local development](docs/LOCAL_DEVELOPMENT.md) |
| API contract and RBAC | [Operations API](docs/OPERATIONS_API.md) |
| Live connection activation | [Production runtime activation](docs/PRODUCTION_RUNTIME_ACTIVATION.md) |
| Infrastructure and deployment | [Infrastructure README](infra/README.md) |
| Fabric operations and recovery | [Fabric runbook](docs/FABRIC_RUNBOOK.md) |
| Ontology architecture | [Ontology architecture](docs/ontology-architecture.md) |
| Generation consumers | [Consumer inventory](docs/ontology-generation-consumer-inventory.md) |
| Native Plan/Act integration | [Native ontology agent](docs/native-ontology-agent.md) |
| Governed ontology discovery | [Discovery operations](docs/ontology-discovery-operations.md) |
| Offline maintenance and admission gates | [Ontology maintenance](docs/ontology-agent-maintenance.md) |
| Exposure scalar publication | [Scalar migration](docs/exposure-scalar-migration.md) |
| Exposure live acceptance | [Phase 4 evidence gate](docs/phase-4-exposure-evidence-gate.md) |
| Copilot rollout and provenance | [Copilot runbook](docs/runbooks/copilot-orchestration-rollout.md) |
| Semantic context | [Semantic architecture](docs/semantic-architecture.md) |
| Remediation planning | [Remediation runbook](docs/REMEDIATION_PLANNING_RUNBOOK.md) |
| Roadmap and acceptance status | [Roadmap](.planning/ROADMAP.md), [state](.planning/STATE.md) |
