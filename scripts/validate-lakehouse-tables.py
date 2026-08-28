#!/usr/bin/env .venv/bin/python3
"""Compare Delta tables present in a Fabric lakehouse against code expectations.

Usage:
    AZURE_CLIENT_SECRET=<secret> .venv/bin/python scripts/validate-lakehouse-tables.py \
        [--config fabric.config.yaml] [--lakehouse-id <id>]

Reports:
  - tables actually present in the lakehouse
  - tables the codebase knows how to write (versioned schema registry)
  - present-but-unknown tables (legacy/orphans)
  - expected-but-missing tables (not yet regenerated)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml

from fabric.auth import FabricAuthConfig, build_credential
from storage.onelake_writer import OneLakeWriter


def known_table_names() -> set[str]:
    """Tables with a versioned schema declared in code."""
    from fabric.schema_registry import SCHEMAS

    names = set(SCHEMAS)
    try:
        from intelligence.inventory.fabric_contracts import (
            INVENTORY_FABRIC_SCHEMAS_BY_TABLE,
        )

        names |= set(INVENTORY_FABRIC_SCHEMAS_BY_TABLE)
    except Exception:  # noqa: BLE001 - the registry is the primary source
        pass
    return names


def list_lakehouse_tables(writer: OneLakeWriter, lakehouse_id: str) -> set[str]:
    file_system = writer.service.get_file_system_client(writer.workspace_id)
    root = str(PurePosixPath(lakehouse_id) / "Tables")
    names: set[str] = set()
    for path in file_system.get_paths(path=root, recursive=False):
        if not getattr(path, "is_directory", False):
            continue
        names.add(PurePosixPath(path.name).name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="fabric.config.yaml")
    parser.add_argument("--lakehouse-id", default="")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    raw = yaml.safe_load(Path(args.config).read_text()) or {}
    fabric_cfg = raw.get("fabric") or {}

    workspace_id = fabric_cfg.get("workspace_id")
    lakehouse_id = args.lakehouse_id or fabric_cfg.get("lakehouse_id")
    if not workspace_id or not lakehouse_id:
        print("error: workspace_id and lakehouse_id are required")
        return 1

    credential = build_credential(
        FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
    )
    writer = OneLakeWriter(
        workspace_id=workspace_id,
        lakehouse_id=lakehouse_id,
        workspace_name=fabric_cfg.get("workspace_name", ""),
        lakehouse_name=fabric_cfg.get("lakehouse_name", ""),
        credential=credential,
    )

    present = list_lakehouse_tables(writer, lakehouse_id)
    known = known_table_names()

    # Ontology entity/relationship tables are generated per subject/predicate at
    # sync time, so they have a pattern-based schema rather than a registry entry.
    def is_generated(name: str) -> bool:
        return name.startswith("ontology_rel_") or (
            name.startswith("ontology_") and name.endswith("_entities")
        )

    present_generated = {name for name in present if is_generated(name)}
    present_known = {name for name in present if name in known}
    present_unknown = present - present_known - present_generated
    missing = known - present

    report = {
        "workspace_id": workspace_id,
        "lakehouse_id": lakehouse_id,
        "lakehouse_name": fabric_cfg.get("lakehouse_name", ""),
        "present_total": len(present),
        "present_known": sorted(present_known),
        "present_generated_ontology": sorted(present_generated),
        "present_unknown": sorted(present_unknown),
        "expected_missing": sorted(missing),
        "known_total": len(known),
    }

    print(f"Lakehouse: {report['lakehouse_name']} ({lakehouse_id})")
    print(f"  Tables present:                 {len(present)}")
    print(f"  Code-declared schemas:          {len(known)}")
    print(f"  Present & code-declared:        {len(present_known)}")
    print(f"  Present generated ontology:     {len(present_generated)}")
    print(f"  Present but unknown to code:    {len(present_unknown)}")
    print(f"  Code-declared but missing:      {len(missing)}")

    if missing:
        print("\nMissing (code-declared, not yet regenerated):")
        for name in sorted(missing):
            print(f"  - {name}")
    if present_unknown:
        print("\nPresent but unknown to code:")
        for name in sorted(present_unknown):
            print(f"  - {name}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nReport written to {args.json_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
