#!/usr/bin/env .venv/bin/python3
"""Delete classified tables from Fabric lakehouse to prepare for regeneration test.

Usage:
    AZURE_CLIENT_SECRET=<secret> .venv/bin/python scripts/delete-lakehouse-tables.py

Deletes 127 tables classified as:
  - Ontology derivatives (old Hermes outputs): 75 tables
  - Unknown tables (not referenced in code): 52 tables

Preserves:
  - 16 active required tables
  - 82 inventory input tables
  - 39 staging layers (bronze/silver, preserved for safety)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from pathlib import PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fabric.auth import FabricAuthConfig, build_credential
from storage.onelake_writer import OneLakeWriter
import yaml


def main() -> int:
    # Load config
    config_path = Path("fabric.config.yaml")
    raw = yaml.safe_load(config_path.read_text()) or {}
    fabric_cfg = raw.get("fabric") or {}

    workspace_id = fabric_cfg.get("workspace_id")
    lakehouse_id = fabric_cfg.get("lakehouse_id")
    lakehouse_name = fabric_cfg.get("lakehouse_name", "operational_context_graph")

    if not workspace_id or not lakehouse_id:
        print("error: workspace_id and lakehouse_id required in fabric.config.yaml")
        return 1

    # Load deletion targets
    classification_path = Path(".planning/table-deletion-classification.json")
    if not classification_path.exists():
        print(f"error: {classification_path} not found")
        return 1

    with open(classification_path) as f:
        classification = json.load(f)

    tables_to_delete = (
        classification["deletion_analysis"]["safe_to_delete_ontology_derivatives"]
        + classification["deletion_analysis"]["safe_to_delete_unknown"]
    )

    print(f"Preparing to delete {len(tables_to_delete)} tables")
    print(f"  Workspace: {workspace_id}")
    print(f"  Lakehouse: {lakehouse_name}")
    print()

    # Build credential
    try:
        auth_cfg = FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
        credential = build_credential(auth_cfg)
        print(f"✓ Authenticated")
    except Exception as e:
        print(f"✗ Authentication failed: {e}")
        return 1

    # Initialize OneLakeWriter
    try:
        onelake = OneLakeWriter(
            workspace_id=workspace_id,
            lakehouse_id=lakehouse_id,
            workspace_name=fabric_cfg.get("workspace_name", ""),
            lakehouse_name=lakehouse_name,
            credential=credential,
        )
        print(f"✓ OneLakeWriter initialized")
    except Exception as e:
        print(f"✗ OneLakeWriter initialization failed: {e}")
        return 1

    # Delete tables
    deleted_count = 0
    failed_count = 0
    failed_tables = []

    print(f"\nDeleting {len(tables_to_delete)} tables...")
    for i, table_name in enumerate(sorted(tables_to_delete), 1):
        try:
            file_system = onelake.service.get_file_system_client(workspace_id)
            table_path = str(PurePosixPath(lakehouse_id) / "Tables" / table_name)
            directory = file_system.get_directory_client(table_path)

            directory.delete_directory()
            deleted_count += 1
            if i % 20 == 0 or i == len(tables_to_delete):
                print(f"  [{i:3d}/{len(tables_to_delete)}] ✓ {table_name}")
        except Exception as e:
            error_str = str(e)
            if "ResourceNotFoundError" in error_str or "ResourceNotFound" in error_str:
                # Table doesn't exist, still count as success
                deleted_count += 1
            else:
                failed_count += 1
                failed_tables.append((table_name, error_str))

    print(f"\n" + "=" * 70)
    print(f"DELETION COMPLETE")
    print(f"=" * 70)
    print(f"Successfully deleted/not found: {deleted_count}/{len(tables_to_delete)}")
    print(f"Failed (actual errors): {failed_count}")

    if failed_tables:
        print(f"\nFailed tables (sample):")
        for tbl, err in failed_tables[:5]:
            print(f"  - {tbl}: {err[:80]}")
        if len(failed_tables) > 5:
            print(f"  ... +{len(failed_tables) - 5} more")

    # Save results
    results = {
        "tables_to_delete": len(tables_to_delete),
        "deleted": deleted_count,
        "failed": failed_count,
        "reduction": len(tables_to_delete) if failed_count == 0 else deleted_count,
    }

    with open(".planning/deletion-results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: .planning/deletion-results.json")
    print(
        f"Estimated lakehouse reduction: {len(tables_to_delete)} tables → {301 - deleted_count} remaining"
    )

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
