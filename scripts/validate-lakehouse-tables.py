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

from fabric.auth import (
    FabricAuthConfig,
    build_credential,
    build_delta_storage_options,
)
from ontology.publication_manifest import PublicationManifestStore
from storage.delta_writer import DeltaWriter
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


def load_publication_manifest(
    writer: OneLakeWriter,
    credential: object,
) -> PublicationManifestStore:
    """Load persisted publication manifest rows when available.

    Missing table or read failures degrade to an empty registry where every
    lookup becomes ``unknown``.
    """
    table_uri = writer.table_uri("metadata", "publication_manifest")
    delta = DeltaWriter(storage_options=build_delta_storage_options(credential))
    try:
        if not delta.exists(table_uri):
            return PublicationManifestStore()
        rows = delta.read(table_uri)
    except Exception as exc:  # noqa: BLE001 - diagnostics script must keep auditing.
        print(
            f"warning: failed to read metadata_publication_manifest ({exc}); "
            "classifying dispositions as unknown",
            file=sys.stderr,
        )
        return PublicationManifestStore()
    return PublicationManifestStore.from_list(
        [
            {
                "projection_name": str(row.get("projection_name") or ""),
                "disposition": str(row.get("disposition") or "active"),
                "compatibility_version": (
                    str(row["compatibility_version"])
                    if row.get("compatibility_version")
                    else None
                ),
                "retired_reason": (
                    str(row["retired_reason"]) if row.get("retired_reason") else None
                ),
                "registered_at": str(row.get("registered_at") or ""),
                "updated_at": str(row.get("updated_at") or ""),
            }
            for row in rows
        ]
    )


def classify_dispositions(
    table_names: set[str], manifest_store: PublicationManifestStore
) -> dict[str, str]:
    return {
        table_name: manifest_store.get(table_name).disposition
        for table_name in sorted(table_names)
    }


def undispositioned_missing_tables(
    expected_missing: set[str], dispositions: dict[str, str]
) -> list[str]:
    return sorted(
        table_name
        for table_name in expected_missing
        if dispositions.get(table_name, "unknown") == "unknown"
    )


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
    manifest_store = load_publication_manifest(writer, credential)
    all_tables = present_known | present_unknown | missing
    dispositions = classify_dispositions(all_tables, manifest_store)
    missing_undispositioned = undispositioned_missing_tables(missing, dispositions)

    report = {
        "workspace_id": workspace_id,
        "lakehouse_id": lakehouse_id,
        "lakehouse_name": fabric_cfg.get("lakehouse_name", ""),
        "present_total": len(present),
        "present_known": sorted(present_known),
        "present_generated_ontology": sorted(present_generated),
        "present_unknown": sorted(present_unknown),
        "expected_missing": sorted(missing),
        "expected_missing_undispositioned": missing_undispositioned,
        "dispositions": dispositions,
        "known_total": len(known),
    }

    print(f"Lakehouse: {report['lakehouse_name']} ({lakehouse_id})")
    print(f"  Tables present:                 {len(present)}")
    print(f"  Code-declared schemas:          {len(known)}")
    print(f"  Present & code-declared:        {len(present_known)}")
    print(f"  Present generated ontology:     {len(present_generated)}")
    print(f"  Present but unknown to code:    {len(present_unknown)}")
    print(f"  Code-declared but missing:      {len(missing)}")
    print(f"  Missing & manifest-unknown:     {len(missing_undispositioned)}")

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
