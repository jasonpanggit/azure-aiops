#!/usr/bin/env python3
"""Test whether Fabric notebook execution fails due to environment dependency."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fabric.auth import FabricAuthConfig, build_credential  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402
from fabric_pipelines.notebook_manager import (  # noqa: E402
    NotebookManager,
    build_inventory_bootstrap_notebook_definition,
    ensure_notebook,
)


def deploy_and_test(
    manager: NotebookManager,
    workspace_id: str,
    lakehouse_id: str,
    lakehouse_name: str,
    environment_id: str | None,
    test_label: str,
) -> None:
    """Deploy and run notebook with given environment configuration."""
    print(f"\n{'='*60}")
    print(f"TEST: {test_label}")
    print(f"{'='*60}")
    
    if environment_id:
        print(f"Environment ID: {environment_id}")
    else:
        print("Environment ID: (none)")

    def definition_builder(
        environment_id: str = "",
        workspace_id: str = "",
        lakehouse_id: str = "",
        lakehouse_name: str = "",
    ) -> dict[str, Any]:
        return build_inventory_bootstrap_notebook_definition(
            environment_id=environment_id,
            workspace_id=workspace_id,
            lakehouse_id=lakehouse_id,
            lakehouse_name=lakehouse_name,
        )

    try:
        print("Deploying notebook...")
        result = ensure_notebook(
            manager,
            display_name=f"test_inventory_bootstrap_{test_label.replace(' ', '_')}",
            item_id="",
            environment_id=environment_id or "",
            lakehouse_id=lakehouse_id,
            lakehouse_name=lakehouse_name,
            definition_builder=definition_builder,
        )
        notebook_id = result.get("id", "")
        print(f"✓ Deployed: {notebook_id}")

        print("Triggering on-demand run...")
        run_result = manager.run_on_demand(notebook_id)
        print(f"✓ Run succeeded: status={run_result['status']}")
        
    except Exception as e:
        print(f"✗ Failed with error:")
        print(f"  {type(e).__name__}: {e}")


def main() -> int:
    config_path = Path("fabric.config.yaml")
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

    # Test 1: WITHOUT environment
    deploy_and_test(
        manager,
        workspace_id,
        lakehouse_id,
        lakehouse_name,
        environment_id=None,
        test_label="WITHOUT environment",
    )

    # Test 2: WITH environment (if configured)
    if environment_id:
        deploy_and_test(
            manager,
            workspace_id,
            lakehouse_id,
            lakehouse_name,
            environment_id=environment_id,
            test_label="WITH environment",
        )
    else:
        print("\n" + "="*60)
        print("SKIPPING: WITH environment test (no environment_id configured)")
        print("="*60)

    print("\n" + "="*60)
    print("ANALYSIS")
    print("="*60)
    print("If test 1 succeeds and test 2 fails:")
    print("  → Environment dependency is causing the Spark session failure")
    print("If both fail:")
    print("  → Issue is lakehouse attachment or Spark context initialization")
    print("If both succeed:")
    print("  → Root cause is unknown or environment configuration changed")
    print("="*60 + "\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
