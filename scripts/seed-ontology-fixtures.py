#!/usr/bin/env python3
"""Seeds the ``inventory_resources`` Delta table in the configured Fabric
lakehouse with realistic fixture rows, so the Fabric-hosted
``ontology_pipeline_notebook`` (see ``fabric_pipelines.notebook_manager``)
has something to read via ``spark.read.table(...)`` when it runs -- that
table doesn't exist in the live lakehouse otherwise.

Reuses this repo's own ``DeltaWriter``/``OneLakeWriter`` (Don't Hand-Roll --
the same writer path ``scripts/seed-topology-fixtures.py`` already uses to
publish fixtures to this exact lakehouse), and seeds rows already shaped the
way ``ontology.entity_builder.EntityBuilder.build()`` consumes them
(``tenant_id``/``subscription_id``/``resource_id``/``payload_json`` with
tags and resourceType), covering the full Hermes ontology scope: a
VirtualMachine (with Application/BusinessService/Owner/SupportTeam/
Environment/Service tags), its PatchAssessment, and an AdvisorRecommendation
targeting it -- enough to exercise belongsTo/assessedBy/impacts-analog
predicates (``member_of``/``belongs_to``, ``evaluates``, ``affects``).

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

from fabric.auth import FabricAuthConfig, build_credential, build_delta_storage_options  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402
from fabric.lakehouse_manager import LakehouseManager  # noqa: E402
from fabric.workspace_manager import WorkspaceManager  # noqa: E402
from storage.delta_writer import DeltaWriteMode, DeltaWriter  # noqa: E402
from storage.onelake_writer import OneLakeWriter  # noqa: E402

_TENANT_ID = "22222222-2222-2222-2222-222222222222"
_SUBSCRIPTION_ID = "11111111-1111-1111-1111-111111111111"
_VM_ID = (
    f"/subscriptions/{_SUBSCRIPTION_ID}/resourcegroups/rg-ontology-fixture/"
    "providers/microsoft.compute/virtualmachines/vm-fixture"
)


def _ontology_fixture_rows(timestamp: str) -> list[dict]:
    """Returns raw-ARG-shaped inventory rows already in the envelope
    ``EntityBuilder.build()`` expects (mirrors the shape asserted against in
    ``tests/test_entity_builder.py``/``tests/test_ontology_pipeline.py``:
    ``payload_json`` as a JSON string, tags/resourceType nested inside)."""
    vm_payload = json.dumps(
        {
            "id": _VM_ID,
            "name": "vm-fixture",
            "tenantId": _TENANT_ID,
            "subscriptionId": _SUBSCRIPTION_ID,
            "resourceGroup": "rg-ontology-fixture",
            "tags": {
                "AppName": "Payments API",
                "Environment": "Production",
                "BusinessUnit": "Retail",
                "CostCenter": "CC-42",
                "Owner": "ops@example.com",
                "SupportGroup": "SRE",
                "Service": "Checkout",
            },
        },
        sort_keys=True,
    )
    assessment_payload = json.dumps(
        {
            "targetResourceId": _VM_ID,
            "tenantId": _TENANT_ID,
            "subscriptionId": _SUBSCRIPTION_ID,
        },
        sort_keys=True,
    )
    recommendation_payload = json.dumps(
        {
            "targetResourceId": _VM_ID,
            "tenantId": _TENANT_ID,
            "subscriptionId": _SUBSCRIPTION_ID,
        },
        sort_keys=True,
    )
    return [
        {
            "tenant_id": _TENANT_ID,
            "subscription_id": _SUBSCRIPTION_ID,
            "resource_id": _VM_ID,
            "timestamp": timestamp,
            "change_version": "seed-ontology-fixture-1",
            "ingestion_run_id": "seed-ontology-fixtures-1",
            "entity_type": "VirtualMachine",
            "name": "vm-fixture",
            "resource_type": "microsoft.compute/virtualmachines",
            "location": "eastus",
            "payload_json": vm_payload,
        },
        {
            "tenant_id": _TENANT_ID,
            "subscription_id": _SUBSCRIPTION_ID,
            "resource_id": f"{_VM_ID}/patchassessmentresults/latest",
            "timestamp": timestamp,
            "change_version": "seed-ontology-fixture-1",
            "ingestion_run_id": "seed-ontology-fixtures-1",
            "entity_type": "PatchAssessment",
            "name": "latest",
            "resource_type": "microsoft.compute/virtualmachines/patchassessmentresults",
            "location": "eastus",
            "payload_json": assessment_payload,
        },
        {
            "tenant_id": _TENANT_ID,
            "subscription_id": _SUBSCRIPTION_ID,
            "resource_id": (
                f"/subscriptions/{_SUBSCRIPTION_ID}/resourcegroups/rg-ontology-fixture/"
                "providers/microsoft.advisor/recommendations/rec-fixture"
            ),
            "timestamp": timestamp,
            "change_version": "seed-ontology-fixture-1",
            "ingestion_run_id": "seed-ontology-fixtures-1",
            "entity_type": "AdvisorRecommendation",
            "name": "rec-fixture",
            "resource_type": "microsoft.advisor/recommendations",
            "location": "eastus",
            "payload_json": recommendation_payload,
        },
    ]


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

    rows = _ontology_fixture_rows("2026-08-27T00:00:00Z")
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
