# Local Development

## Install

```bash
cd /Users/jasonmba/workspace/azure-aiops
uv sync --extra test
```

## Start the web app and Operations API without Azure

From `web/`, start the UI and API in separate terminals:

```bash
npm run start
npm run start:api
```

`npm run start` starts the web app. `npm run start:api` reads `web/.env.local`
and starts the API with token auth.

If `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and
`AZURE_CLIENT_SECRET` are set, the API startup injects a local subscription
connection into `.hermes-local/`. The connection stores only
`env://AZURE_CLIENT_SECRET`, so discovery can authenticate with the local SPN
without persisting the secret. Startup also removes the fixture-only demo
connection and runs initial sync for the SPN connection. Set
`HERMES_LOCAL_AUTO_SYNC=0` to register the connection without syncing.

If any SPN value is missing or still a placeholder, `npm run start:api` falls
back to a fixture-backed snapshot from `tests/fixtures/mock_arg_responses.json`.
The API runtime reads both real synced data and fixture snapshots through the
same `InventoryDatasetMapper` and Semantic Knowledge Layer.

Set `HERMES_LOCAL_SEED=0` when you intentionally want the live Azure-backed
local path instead. In that mode, `scripts/start-api.sh` uses the OneLake-backed
registry (or a local directory when `HERMES_HOME` is a path) and live connection
sync behavior.

You can also seed without starting the server:

```bash
uv run hermes-arg local --home .hermes-local
uv run hermes-arg local-spn --home .hermes-local
```

## Generate a deterministic source snapshot

```bash
uv run hermes-arg sample \
  --fixture tests/fixtures/mock_arg_responses.json \
  --output-dir sample-data
```

## Configure the mock Fabric environment

```bash
cp fabric.local.example.yaml fabric.local.yaml
```

The local adapter writes the same Delta tables and metadata structure to `mock-fabric-lakehouse/` without contacting Fabric or Azure. Authentication is deliberately bypassed only when `local_onelake_root` is explicitly set.

## Exercise the end-to-end flow

```bash
uv run hermes-arg fabric \
  "Sync Azure inventory to OneLake" \
  --config fabric.local.yaml

uv run hermes-arg fabric \
  "Refresh inventory lakehouse" \
  --config fabric.local.yaml

uv run hermes-arg fabric \
  "Validate inventory data" \
  --config fabric.local.yaml

uv run hermes-arg fabric \
  "Show last Fabric sync" \
  --config fabric.local.yaml
```

A second refresh should report zero changes for inventory/entity/relationship tables. Run-scoped health and quality rows intentionally replace their prior current-run records and therefore contribute small added/removed counts to the aggregate command result.

## Tests

```bash
uv run --extra test pytest
uvx ruff check src tests hermes_plugin.py __init__.py
uvx bandit -r src -q
```

Focused suites:

```bash
uv run pytest tests/test_fabric_client.py
uv run pytest tests/test_onelake_writer.py
uv run pytest tests/test_delta_tables.py
uv run pytest tests/test_incremental_sync.py
uv run pytest tests/test_data_quality.py
uv run pytest tests/test_fabric_commands.py
```

## Mock versus production

| Concern | Local mock | Production |
|---|---|---|
| Storage | Local filesystem | OneLake ADLS endpoint |
| Delta engine | delta-rs | delta-rs |
| Auth | Bypassed | Managed identity or service principal |
| Fabric REST | Not called | Workspace/Lakehouse/table/shortcut APIs |
| Table registration | Delta log asserted | Fabric table API polled |
| Metrics | OpenTelemetry no-op unless SDK configured | Export through configured OTel SDK/collector |

Do not place production credentials or copied production data in the mock directory.
