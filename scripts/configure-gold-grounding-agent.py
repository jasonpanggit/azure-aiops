#!/usr/bin/env python3
"""Stage and optionally publish the code-reviewed AI Ops Data Agent definition."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fabric.auth import FabricAuthConfig, build_credential
from fabric.data_agent_manager import (
    DataAgentManager,
    hydrate_data_agent_table_selection,
)
from fabric.fabric_client import FabricClient
from fabric.gold_grounding_definition import (
    GOLD_GROUNDING_FEW_SHOTS,
    GOLD_GROUNDING_TABLES,
    build_gold_grounding_definition,
)
from fabric.lakehouse_manager import LakehouseManager
from ontology_discovery.generation_resolver import (
    CompatibilityAlias,
    GenerationSelection,
)

DESCRIPTION = (
    "Read-only Gold and deterministic ontology evidence for Operations Copilot. "
    "Advisory only; unified inventory remains the resource-identity authority."
)


def main() -> int:
    """Configure the existing Gold-grounding Data Agent from repository contracts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabric-config", default="fabric.config.yaml")
    parser.add_argument(
        "--generation-path",
        required=True,
        help="Immutable generation path selected for all Data Agent tables.",
    )
    parser.add_argument(
        "--source-generation",
        required=True,
        help="Source generation recorded in the immutable ontology manifest.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish only after the staged definition has been reviewed.",
    )
    args = parser.parse_args()

    config_path = Path(args.fabric_config)
    if not config_path.exists():
        print(f"error: {config_path} not found", file=sys.stderr)
        return 1

    raw = yaml.safe_load(config_path.read_text())
    fabric_cfg = raw.get("fabric") or {}
    workspace_id = str(fabric_cfg.get("workspace_id") or "").strip()
    lakehouse_id = str(fabric_cfg.get("lakehouse_id") or "").strip()
    lakehouse_name = str(fabric_cfg.get("lakehouse_name") or "").strip()
    agent_cfg = fabric_cfg.get("gold_grounding_agent") or {}
    item_id = str(agent_cfg.get("item_id") or "").strip()
    display_name = str(agent_cfg.get("display_name") or "AI Ops Data Agent").strip()
    if not workspace_id or not lakehouse_id:
        print(
            "error: real fabric workspace_id and lakehouse_id are required",
            file=sys.stderr,
        )
        return 1
    if not item_id:
        print(
            "error: fabric.gold_grounding_agent.item_id is required; "
            "Terraform owns the Data Agent lifecycle",
            file=sys.stderr,
        )
        return 1

    credential = build_credential(
        FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
    )
    client = FabricClient(credential)
    manager = DataAgentManager(client, workspace_id)
    lakehouse = LakehouseManager(client, workspace_id).resolve(
        lakehouse_id=lakehouse_id,
        lakehouse_name=lakehouse_name,
    )
    lakehouse_display_name = str(
        lakehouse.get("displayName") or lakehouse_name or "operational_context_graph"
    )
    generation = GenerationSelection(
        active_generation=args.generation_path,
        active_generation_uri=args.generation_path,
        prior_generation=None,
        pointer_etag="operator-pinned",
        source_generation=args.source_generation,
    )
    aliases = {
        name: CompatibilityAlias(
            logical_name=name,
            physical_path=f"{args.generation_path.rstrip('/')}/{name}",
            generation_id=generation.generation_id,
        )
        for name in GOLD_GROUNDING_TABLES
    }
    definition = build_gold_grounding_definition(
        lakehouse_id=lakehouse_id,
        workspace_id=workspace_id,
        lakehouse_display_name=lakehouse_display_name,
        generation=generation,
        table_aliases=aliases,
    )

    item = manager.resolve(item_id=item_id)
    if item is None:
        print(
            f"error: configured Data Agent item {item_id} was not found",
            file=sys.stderr,
        )
        return 1

    agent_id = str(item["id"])
    existing_definition = manager.get_definition(agent_id)
    definition = hydrate_data_agent_table_selection(
        definition,
        existing_definition,
        GOLD_GROUNDING_TABLES,
    )
    manager.update_definition(
        agent_id,
        definition,
        existing_definition=existing_definition,
    )
    print(f"Data Agent updated: id={agent_id} displayName={display_name}")
    print(f"Selected tables: {', '.join(GOLD_GROUNDING_TABLES)}")
    print(f"Few-shot queries: {len(GOLD_GROUNDING_FEW_SHOTS)}")
    if args.publish:
        manager.publish(
            agent_id,
            published_description=DESCRIPTION,
        )
        print("Published reviewed Data Agent definition.")
    else:
        print("Draft staged only; inspect the live definition before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
