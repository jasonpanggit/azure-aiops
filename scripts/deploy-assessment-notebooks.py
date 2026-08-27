#!/usr/bin/env python3
"""Deploy Phase 08 assessment Fabric notebook items to the configured workspace.

Usage:
    .venv/bin/python scripts/deploy-assessment-notebooks.py [--fabric-config path] [--run]

Credentials are sourced from the configured Fabric auth secret environment
variable, usually AZURE_CLIENT_SECRET. The script is idempotent: existing
Notebook items are updated, missing items are created.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fabric.auth import FabricAuthConfig, build_credential  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402
from fabric_pipelines.notebook_manager import (  # noqa: E402
    CHANGE_NOTEBOOK_DISPLAY_NAME,
    GOVERNANCE_NOTEBOOK_DISPLAY_NAME,
    IMPACT_CONTEXT_NOTEBOOK_DISPLAY_NAME,
    INVENTORY_BOOTSTRAP_NOTEBOOK_DISPLAY_NAME,
    LIFECYCLE_NOTEBOOK_DISPLAY_NAME,
    PATCH_NOTEBOOK_DISPLAY_NAME,
    PREDEPLOY_NOTEBOOK_DISPLAY_NAME,
    VULNERABILITY_NOTEBOOK_DISPLAY_NAME,
    NotebookManager,
    build_change_notebook_definition,
    build_governance_notebook_definition,
    build_impact_context_notebook_definition,
    build_inventory_bootstrap_notebook_definition,
    build_lifecycle_notebook_definition,
    build_patch_notebook_definition,
    build_predeploy_notebook_definition,
    build_vulnerability_notebook_definition,
    ensure_notebook,
)

DefinitionBuilder = Callable[..., dict[str, Any]]


NOTEBOOKS: tuple[tuple[str, str, DefinitionBuilder], ...] = (
    # Bootstrap inventory tables first (required by topology/ontology)
    ("inventory_bootstrap", INVENTORY_BOOTSTRAP_NOTEBOOK_DISPLAY_NAME, build_inventory_bootstrap_notebook_definition),
    # Assessment notebooks (no dependencies)
    ("governance_pipeline", GOVERNANCE_NOTEBOOK_DISPLAY_NAME, build_governance_notebook_definition),
    ("vulnerability_pipeline", VULNERABILITY_NOTEBOOK_DISPLAY_NAME, build_vulnerability_notebook_definition),
    ("lifecycle_pipeline", LIFECYCLE_NOTEBOOK_DISPLAY_NAME, build_lifecycle_notebook_definition),
    ("patch_pipeline", PATCH_NOTEBOOK_DISPLAY_NAME, build_patch_notebook_definition),
    ("change_pipeline", CHANGE_NOTEBOOK_DISPLAY_NAME, build_change_notebook_definition),
    ("predeploy_pipeline", PREDEPLOY_NOTEBOOK_DISPLAY_NAME, build_predeploy_notebook_definition),
    # Impact context depends on topology/ontology
    ("impact_context_pipeline", IMPACT_CONTEXT_NOTEBOOK_DISPLAY_NAME, build_impact_context_notebook_definition),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabric-config", default="fabric.config.yaml")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Also trigger an on-demand Fabric job run for each deployed notebook.",
    )
    args = parser.parse_args()

    config_path = Path(args.fabric_config)
    if not config_path.exists():
        print(f"error: {config_path} not found", file=sys.stderr)
        return 1

    raw = yaml.safe_load(config_path.read_text()) or {}
    fabric_cfg = raw.get("fabric") or {}
    workspace_id = str(fabric_cfg.get("workspace_id") or "")
    if not workspace_id or workspace_id == "00000000-0000-0000-0000-000000000000":
        print("error: fabric.workspace_id is not set to a real workspace", file=sys.stderr)
        return 1

    auth_cfg = FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
    credential = build_credential(auth_cfg)
    client = FabricClient(credential)
    manager = NotebookManager(client, workspace_id)

    topology_cfg = fabric_cfg.get("topology_pipeline") or {}
    environment_id = str(topology_cfg.get("environment_item_id") or "")
    lakehouse_id = str(fabric_cfg.get("lakehouse_id") or "")
    lakehouse_name = str(fabric_cfg.get("lakehouse_name") or "")

    deployed: list[dict[str, str]] = []
    for config_key, default_display_name, definition_builder in NOTEBOOKS:
        notebook_cfg = fabric_cfg.get(config_key) or {}
        display_name = str(notebook_cfg.get("notebook_display_name") or default_display_name)
        item_id = str(notebook_cfg.get("notebook_item_id") or "")
        notebook_environment_id = str(notebook_cfg.get("environment_item_id") or environment_id)

        print(f"Deploying notebook '{display_name}' to workspace {workspace_id} ...")
        result = ensure_notebook(
            manager,
            display_name=display_name,
            item_id=item_id,
            environment_id=notebook_environment_id,
            lakehouse_id=lakehouse_id,
            lakehouse_name=lakehouse_name,
            definition_builder=definition_builder,
        )
        notebook_id = str(result.get("id") or "")
        action = str(result.get("action") or "unknown")
        deployed.append({"display_name": display_name, "id": notebook_id, "action": action})
        print(f"Notebook {action}: id={notebook_id} displayName={display_name}")

        if args.run:
            print(f"Triggering on-demand run for '{display_name}' ...")
            run_result = manager.run_on_demand(notebook_id)
            print(f"Run triggered: {run_result}")

    print("\nDeployment summary:")
    for item in deployed:
        print(f"- {item['display_name']}: {item['action']} ({item['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
