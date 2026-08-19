# Local Fabric Persistence Development

## Install

```bash
cd /Users/jasonmba/workspace/azure-aiops
uv sync --extra test
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
