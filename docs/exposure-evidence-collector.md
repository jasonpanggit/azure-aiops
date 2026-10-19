# Fixed Exposure evidence collector

`scripts/exposure_mi_collector.py` collects read-only observations for the
corrected tenant `262a3a77-7d74-4684-8937-897d98d2a17a`, subscription
`890c9bfc-d09c-4143-9ce5-465e75e3eecc`, and existing operational Lakehouse.
It is not a general SQL runner, deployment command, fixture writer, or acceptance
certificate. Changing its target requires a source review and a new image digest.

## Execution boundary

The deployment owner must bake the source and tests into a reviewed image and
run a dedicated fixed manual ACA Job. Do not execute arbitrary commands inside
the production API container or override command, identity, or environment at
execution time. Use one replica, parallelism one, retry limit zero, 1 CPU, 1 GiB
memory, and a 960-second replica timeout. The collector enforces a 900-second
deadline, 20-second SQL statements, 4 MiB document reads, 64-row aggregate
transfers, and at most 6,000 benchmark queries returning at most 101 rows each.

Use the existing application user-assigned managed identity with client ID
`5d4d603a-343c-4b92-b43a-cd1ebe771ab6`. The collector uses
`ManagedIdentityCredential` explicitly; it does not fall back to a developer or
service-principal identity. Grant no new writer capability. Collection requires
read access to the connection registry and Gold pointer documents and SELECT
access to the fixed Gold, workload checkpoint/deployment, and ontology tables.
It never resolves the registry's secret references or writes provider data.

The fixed template must set:

```text
PYTHONPATH=/app:/app/src
AZURE_CLIENT_ID=5d4d603a-343c-4b92-b43a-cd1ebe771ab6
AIOPS_HOME=abfss://2c1fea36-104d-4c26-86db-12e09e432b41@onelake.dfs.fabric.microsoft.com/f995229d-970e-44ec-8af5-df9e25261d19/Files/aiops
AIOPS_CONNECTION_HOME=abfss://2c1fea36-104d-4c26-86db-12e09e432b41@onelake.dfs.fabric.microsoft.com/f995229d-970e-44ec-8af5-df9e25261d19/Files/aiops/connections
```

Inherit the actual effective `AIOPS_FABRIC_CONFIG_JSON` and the image's immutable
40-character `AIOPS_SOURCE_REVISION`. Do not print the configuration value.
The collector verifies selected Fabric endpoint, tenant, identity, and root
metadata against its fixed target. Do not use the baked configuration of a
retired tenant. ACA must supply its managed-identity endpoint environment.

Define separate fixed templates as needed:

```bash
python /app/scripts/exposure_mi_collector.py
python /app/scripts/exposure_mi_collector.py --benchmark
```

The first command reports aggregate source/publication observations. The second
also runs the existing production Fabric SQL benchmark against the active
registered scope and Gold pointer. A corpus outside 1 through 100,000 rows is
not walked. A corpus smaller than the required 100,000, missing either target
kind, or failing the existing correctness/SLO checks cannot qualify; the
benchmark command exits nonzero. No local deterministic fallback is used.

## Interpretation and retained receipts

Capture stdout together with immutable Job execution, revision, image, and
identity receipts. The JSON binds its source hash, release, generation, registry,
and pointer, and checks that registry and pointer did not change during the
collection. Source-run identifiers are hashed, provider payloads are not
exported, and SQL errors retain their SQLSTATE rather than becoming empty
successes. An unavailable source or table remains a recorded gap.

`observations_collected` means collection succeeded, not that acceptance passed.
The report always keeps `production_certified`, `phase4_ready`, and
`source_binding_complete` false. Generation-bound typed ontology edge counts
alone do not prove Silver identity reconciliation. Per-fact workload sums are
not distinct workload counts. Real source/publication receipts, exact
Silver-to-ontology identity reconciliation, canary/rollback, and authenticated
operator acceptance remain separate inputs to `validate_exposure_live.py`.

The fixed collector reads live data only. Deterministic 100k qualification
requires a separately governed isolated fixture target and lease; never
overwrite or delete production tables, invent registry scope, reuse the
ontology three-record fixture as a scale writer, or present synthetic fixture
rows as provider evidence. A retained prior Gold generation is also required
before any genuine canary/rollback exercise.
