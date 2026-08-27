#!/usr/bin/env python3
"""Seeds the ``inventory_network_vnets`` / ``inventory_network_security_groups``
Delta tables in the configured Fabric lakehouse with realistic fixture rows,
so the Fabric-hosted ``topology_pipeline_notebook`` (see
``fabric_pipelines.notebook_manager``) has something to read via
``spark.read.table(...)`` when it runs -- those tables don't exist in the
live lakehouse otherwise, which is one of the two reasons the notebook's
on-demand run previously failed.

Reuses this repo's own ``DeltaWriter``/``OneLakeWriter`` (Don't Hand-Roll --
the same writer path ``hermes_arg_connector.inventory_refresh`` already uses
to publish inventory to this exact lakehouse), and adapts the shared
VNet/NSG fixture already used by the topology-pipeline test suite
(``tests/topology_comparison_scenario.py``) so the seeded rows are known to
match the shape ``derive_edges()``/``network_normalize.py`` expect.

This is a one-off operator script (not part of the automated test suite).

Usage:
    .venv/bin/python scripts/seed-topology-fixtures.py [--fabric-config path]

Credentials are sourced from the environment (AZURE_CLIENT_SECRET, or
whatever fabric.yaml's auth.client_secret_env names) exactly as the rest of
this repo's Fabric tooling expects -- source web/.env.local first if needed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fabric.auth import FabricAuthConfig, build_credential, build_delta_storage_options  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402
from fabric.lakehouse_manager import LakehouseManager  # noqa: E402
from fabric.workspace_manager import WorkspaceManager  # noqa: E402
from storage.delta_writer import DeltaWriteMode, DeltaWriter  # noqa: E402
from storage.onelake_writer import OneLakeWriter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from topology_comparison_scenario import topology_comparison_scenario  # noqa: E402


def _drop_empty_lists(value: object) -> object:
    """Recursively strips keys whose value is an empty ``list`` from nested
    dicts/lists (leaving non-empty lists/dicts otherwise untouched).

    ``pyarrow.Table.from_pylist`` infers an empty Python list's element type
    as ``null`` (Parquet "void"), which Spark's Parquet reader cannot decode
    (``Unable to create Parquet converter for data type "void"``) -- so an
    empty ``virtualNetworkPeerings: []`` in the raw ARG-shaped fixture rows
    made the notebook's ``spark.read.table(...)`` call fail entirely. Since
    every normalizer in ``network_normalize.py`` already treats a *missing*
    sub-resource key the same as an *empty list* one (``_list(props.get(...))``
    defaults to ``[]``), dropping the key is behavior-preserving for
    ``derive_edges()`` while producing a Parquet-safe schema."""
    if isinstance(value, dict):
        return {k: _drop_empty_lists(v) for k, v in value.items() if not (isinstance(v, list) and not v)}
    if isinstance(value, list):
        return [_drop_empty_lists(item) for item in value]
    return value


#: DeltaWriter enforces these columns on every row it writes (see
#: storage/delta_writer.py:REQUIRED_COLUMNS). The topology-comparison
#: fixture rows are raw-ARG-shaped and don't carry inventory's own
#: publication-envelope fields, so this adds the minimum needed to satisfy
#: the writer's contract without altering the row shape derive_edges()
#: actually reads (id/name/type/tenantId/subscriptionId/tags/properties).
def _with_delta_envelope(row: dict, *, ingestion_run_id: str) -> dict:
    sanitized = _drop_empty_lists(row)
    return {
        **sanitized,
        "tenant_id": row.get("tenantId", ""),
        "subscription_id": row.get("subscriptionId", ""),
        "resource_id": row["id"],
        "timestamp": "2026-08-27T00:00:00Z",
        "change_version": "seed-fixture-2",
        "ingestion_run_id": ingestion_run_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabric-config", default="fabric.config.yaml")
    args = parser.parse_args()

    config_path = Path(args.fabric_config)
    if not config_path.exists():
        print(f"error: {config_path} not found", file=sys.stderr)
        return 1

    raw = yaml.safe_load(config_path.read_text())
    fabric_cfg = raw.get("fabric") or {}
    workspace_id = str(fabric_cfg.get("workspace_id") or "")
    if not workspace_id or workspace_id == "00000000-0000-0000-0000-000000000000":
        print("error: fabric.workspace_id is not set to a real workspace", file=sys.stderr)
        return 1

    auth_cfg = FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
    credential = build_credential(auth_cfg)
    client = FabricClient(credential)

    workspace = WorkspaceManager(client).resolve(
        workspace_id=workspace_id,
        workspace_name=str(fabric_cfg.get("workspace_name") or ""),
    )
    lakehouse = LakehouseManager(client, str(workspace["id"])).resolve(
        lakehouse_id=str(fabric_cfg.get("lakehouse_id") or ""),
        lakehouse_name=str(fabric_cfg.get("lakehouse_name") or ""),
        create_if_missing=bool(fabric_cfg.get("create_lakehouse_if_missing")),
        enable_schemas=bool(fabric_cfg.get("table_schema")),
    )
    storage_options = build_delta_storage_options(credential)
    onelake = OneLakeWriter(
        str(workspace["id"]),
        str(lakehouse["id"]),
        workspace_name=str(workspace.get("displayName") or ""),
        lakehouse_name=str(lakehouse.get("displayName") or ""),
        table_schema=str(fabric_cfg.get("table_schema") or ""),
        credential=credential,
        storage_options=storage_options,
    )
    delta_writer = DeltaWriter(
        storage_options=storage_options,
        storage_options_provider=lambda: build_delta_storage_options(credential),
    )

    scenario = topology_comparison_scenario()
    ingestion_run_id = "seed-topology-fixtures-1"

    tables = {
        "network_vnets": scenario["network_vnets"],
        "network_security_groups": scenario["network_security_groups"],
    }
    for logical_name, rows in tables.items():
        envelope_rows = [_with_delta_envelope(row, ingestion_run_id=ingestion_run_id) for row in rows]
        # ``inventory_{logical_name}`` matches the exact table name the
        # notebook reads via spark.read.table(...): OneLakeWriter.table_uri
        # names tables "{layer}_{table_name}".
        table_uri = onelake.table_uri("inventory", logical_name)
        # DeltaWriter.write() always uses schema_mode="merge" on overwrite,
        # so a stale column type (e.g. an empty-list field that once
        # inferred as Parquet "void") from a prior seed run would persist
        # across re-seeds even though the new rows no longer contain it.
        # Dropping the table first guarantees each seed run starts from the
        # freshly-inferred (Parquet-safe) schema of the current fixture rows.
        onelake.delete_table("inventory", logical_name)
        result = delta_writer.write(
            table_uri,
            envelope_rows,
            mode=DeltaWriteMode.OVERWRITE,
            key_columns=("resource_id",),
        )
        print(f"Wrote inventory_{logical_name}: {result} -> {table_uri}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
