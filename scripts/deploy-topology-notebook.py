#!/usr/bin/env python3
"""Deploy the D-04a Fabric-hosted topology-pipeline notebook to the real
Fabric workspace configured in ``fabric.config.yaml``.

This is a one-off operator script (not part of the automated test suite):
it creates/updates the genuine Fabric-hosted Notebook item so it is visible
in the Fabric portal, fulfilling the `fabric-hosted-notebook` compute
decision from Phase 8 / plan 08-02 (as opposed to only being proven via
local fixtures/tests).

Usage:
    .venv/bin/python scripts/deploy-topology-notebook.py [--fabric-config path] [--run]

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

from fabric.auth import FabricAuthConfig, build_credential  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402
from fabric_pipelines.notebook_manager import NotebookManager, ensure_notebook  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabric-config", default="fabric.config.yaml")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Also trigger an on-demand Fabric job run of the notebook after deploying it.",
    )
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

    manager = NotebookManager(client, workspace_id)
    topology_cfg = fabric_cfg.get("topology_pipeline") or {}
    display_name = str(topology_cfg.get("notebook_display_name") or "topology_pipeline_notebook")
    item_id = str(topology_cfg.get("notebook_item_id") or "")
    environment_id = str(topology_cfg.get("environment_item_id") or "")
    lakehouse_id = str(fabric_cfg.get("lakehouse_id") or "")
    lakehouse_name = str(fabric_cfg.get("lakehouse_name") or "")

    print(f"Deploying notebook '{display_name}' to workspace {workspace_id} ...")
    result = ensure_notebook(
        manager,
        display_name=display_name,
        item_id=item_id,
        environment_id=environment_id,
        lakehouse_id=lakehouse_id,
        lakehouse_name=lakehouse_name,
    )
    print(f"Notebook {result['action']}: id={result.get('id')} displayName={result.get('displayName')}")

    if args.run:
        print("Triggering on-demand run ...")
        run_result = manager.run_on_demand(str(result["id"]))
        print(f"Run triggered: {run_result}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
