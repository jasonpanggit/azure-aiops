#!/usr/bin/env python3
"""Seeds the ``inventory_resources`` Delta table in the configured Fabric
lakehouse with realistic fixture rows, so the Fabric-hosted
``ontology_pipeline_notebook`` (see ``fabric_pipelines.notebook_manager``)
has something to read via ``spark.read.table(...)`` when it runs -- that
table doesn't exist in the live lakehouse otherwise.

Reuses this repo's own ``DeltaWriter``/``OneLakeWriter`` (Don't Hand-Roll --
the same writer path ``scripts/seed-topology-fixtures.py`` already uses to
publish fixtures to this exact lakehouse), and seeds the exact same
comprehensive fixture (``tests/ontology_comparison_scenario.py``) the local
Hermes-vs-Fabric parity test suite (``tests/test_hermes_fabric_ontology_
comparison.py``) runs against -- so the live notebook's Delta-table output
can be read back and diffed against a local run of the real
``EntityBuilder``/``RelationshipBuilder`` on the identical input, proving
live-Fabric parity rather than merely "the notebook executed". Covers the
full Hermes ontology scope: every ``TAG_ENTITY_TYPES``/``RESOURCE_ENTITY_
TYPES`` entity type and every relationship predicate ``RelationshipBuilder``
infers (structural, tag-derived, subscription-connection lineage,
management-group hierarchy, cost/patch/advisor edges, full network
topology).

This is a one-off operator script (not part of the automated test suite).

Usage:
    .venv/bin/python scripts/seed-ontology-fixtures.py [--fabric-config path]

Credentials are sourced from the environment (AZURE_CLIENT_SECRET, or
whatever fabric.yaml's auth.client_secret_env names) exactly as the rest of
this repo's Fabric tooling expects -- source web/.env.local first if needed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from azure.core.exceptions import ResourceNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fabric.auth import FabricAuthConfig, build_credential, build_delta_storage_options  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402
from fabric.lakehouse_manager import LakehouseManager  # noqa: E402
from fabric.workspace_manager import WorkspaceManager  # noqa: E402
from storage.delta_writer import DeltaWriteMode, DeltaWriter  # noqa: E402
from storage.onelake_writer import OneLakeWriter  # noqa: E402
from ontology_comparison_scenario import ontology_comparison_scenario  # noqa: E402


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

    rows = ontology_comparison_scenario()
    # pyarrow.Table.from_pylist infers its schema from each row's own key
    # set, so heterogeneous fixture rows (e.g. only the SubscriptionConnection
    # row carries connection_id/connection_name/... fields) silently lose
    # those extra columns for every other row -- and EntityBuilder never
    # even sees them once round-tripped through Parquet/Delta. Union every
    # row's keys and backfill missing ones with None so the written schema
    # carries every field every row needs (same defensive-normalization
    # spirit as seed-topology-fixtures.py's ``_drop_empty_lists``).
    all_keys: set[str] = set()
    for row in rows:
        all_keys.update(row.keys())
    rows = [{key: row.get(key) for key in all_keys} for row in rows]
    logical_name = "resources"
    # DeltaWriter.write() always uses schema_mode="merge" on overwrite, so a
    # stale column/type from a prior seed run would persist across re-seeds.
    # Dropping the table first guarantees each seed run starts from the
    # freshly-inferred schema of the current fixture rows (mirrors
    # scripts/seed-topology-fixtures.py's gotcha fix).
    try:
        onelake.delete_table("inventory", logical_name)
    except ResourceNotFoundError:
        # First-ever seed run: the table doesn't exist yet, so there's
        # nothing stale to drop -- this is expected, not an error.
        pass
    table_uri = onelake.table_uri("inventory", logical_name)
    result = delta_writer.write(
        table_uri,
        rows,
        mode=DeltaWriteMode.OVERWRITE,
        key_columns=("resource_id",),
    )
    print(f"Wrote inventory_{logical_name}: {result} -> {table_uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
