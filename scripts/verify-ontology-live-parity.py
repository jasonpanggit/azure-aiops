#!/usr/bin/env python3
"""One-off verification script: reads back the live Fabric-hosted
``ontology_entities``/``ontology_relationships`` Delta tables (written by the
on-demand ``ontology_pipeline_notebook`` run against the seeded
``ontology_comparison_scenario()`` fixture) and diffs them against a local
run of the real Hermes ``EntityBuilder``/``RelationshipBuilder`` on the
identical fixture -- the "did the live notebook actually produce the same
operational context graph as Hermes" proof, not just "did it run without
error".

Usage:
    .venv/bin/python scripts/verify-ontology-live-parity.py [--fabric-config path]

Credentials are sourced from the environment exactly as the rest of this
repo's Fabric tooling expects -- source web/.env.local first if needed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from deltalake import DeltaTable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from fabric.auth import FabricAuthConfig, build_credential, build_delta_storage_options  # noqa: E402
from ontology.entity_builder import EntityBuilder  # noqa: E402
from ontology.relationship_builder import RelationshipBuilder  # noqa: E402
from hermes_arg_connector.ontology import generate_ontology_metadata  # noqa: E402
from ontology_comparison_scenario import TIMESTAMP, ontology_comparison_scenario  # noqa: E402

RUN_ID = "ontology-live-verification"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabric-config", default="fabric.config.yaml")
    args = parser.parse_args()

    config_path = Path(args.fabric_config)
    raw = yaml.safe_load(config_path.read_text())
    fabric_cfg = raw.get("fabric") or {}
    workspace_id = str(fabric_cfg.get("workspace_id") or "")
    lakehouse_id = str(fabric_cfg.get("lakehouse_id") or "")

    auth_cfg = FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
    credential = build_credential(auth_cfg)
    storage_options = build_delta_storage_options(credential)

    base = f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/{lakehouse_id}/Tables"
    entities_uri = f"{base}/ontology_entities"
    relationships_uri = f"{base}/ontology_relationships"

    print(f"Reading live table: {entities_uri}")
    live_entities = DeltaTable(entities_uri, storage_options=storage_options).to_pyarrow_table().to_pylist()
    print(f"Reading live table: {relationships_uri}")
    live_relationships = DeltaTable(
        relationships_uri, storage_options=storage_options
    ).to_pyarrow_table().to_pylist()

    live_entity_ids = {row["resource_id"] for row in live_entities}
    live_triples = {
        (row["subject_id"], row["predicate"], row["object_id"]) for row in live_relationships
    }

    # -- Hermes-direct arm, run locally against the identical fixture --
    rows = ontology_comparison_scenario()
    hermes_entities = EntityBuilder().build(rows, RUN_ID, timestamp=TIMESTAMP)
    hermes_relationships = RelationshipBuilder().build(hermes_entities, RUN_ID)
    hermes_entity_ids = {row["resource_id"] for row in hermes_entities}
    hermes_triples = {
        (row["subject_id"], row["predicate"], row["object_id"]) for row in hermes_relationships
    }

    entity_diff_hermes_only = hermes_entity_ids - live_entity_ids
    entity_diff_live_only = live_entity_ids - hermes_entity_ids
    rel_diff_hermes_only = hermes_triples - live_triples
    rel_diff_live_only = live_triples - hermes_triples

    print()
    print("=== Live-Fabric vs Hermes-direct parity report ===")
    print(f"Hermes entities: {len(hermes_entity_ids)}   Live entities: {len(live_entity_ids)}")
    print(f"Hermes relationships: {len(hermes_triples)}   Live relationships: {len(live_triples)}")
    print(f"Entity ids only in Hermes (missing from live): {len(entity_diff_hermes_only)}")
    print(f"Entity ids only in live (unexpected): {len(entity_diff_live_only)}")
    print(f"Relationship triples only in Hermes (missing from live): {len(rel_diff_hermes_only)}")
    print(f"Relationship triples only in live (unexpected): {len(rel_diff_live_only)}")

    zero_diff = not (
        entity_diff_hermes_only
        or entity_diff_live_only
        or rel_diff_hermes_only
        or rel_diff_live_only
    )
    if zero_diff:
        print("\nRESULT: ZERO DIFF -- live Fabric notebook output matches Hermes exactly.")
        return 0

    print("\nRESULT: DIFF DETECTED")
    if entity_diff_hermes_only:
        print(f"  missing entities: {sorted(entity_diff_hermes_only)[:10]}")
    if entity_diff_live_only:
        print(f"  unexpected entities: {sorted(entity_diff_live_only)[:10]}")
    if rel_diff_hermes_only:
        print(f"  missing relationships: {sorted(rel_diff_hermes_only)[:10]}")
    if rel_diff_live_only:
        print(f"  unexpected relationships: {sorted(rel_diff_live_only)[:10]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
