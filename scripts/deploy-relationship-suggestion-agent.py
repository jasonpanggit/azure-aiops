#!/usr/bin/env python3
"""Provision (create/resolve + publish) the advisory relationship-suggestion
Fabric Data Agent, pointed at this workspace's ``operational_context_graph``
lakehouse, per the user's "relationship suggestion layer" request.

This is a one-off operator script (not part of the automated test suite),
using the repository's standard CLI and credential-loading style.

SCOPE (read before running -- see ``docs/fabric-data-agent-relationship-suggestions.md``
for the full write-up): this script provisions the DataAgent *item* itself --
creates it (if missing) with a staged lakehouse datasource + AI instructions,
and publishes it so its MCP/runtime query endpoint becomes reachable. It does
NOT invoke the agent or write any rows to ``relationship_suggestions`` --
that query step requires either (a) the Fabric portal's chat UI against the
published agent, or (b) the ``fabric-data-agent-sdk``'s OpenAI-compatible
client, which this repo's own ``src/fabric`` package namespace-collides with
(see ``fabric.data_agent_manager``'s module docstring) and so cannot be
exercised from this repo's own scripts/tests today.

Usage:
    .venv/bin/python scripts/deploy-relationship-suggestion-agent.py [--fabric-config path]

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
from fabric.data_agent_manager import DataAgentManager, ensure_data_agent  # noqa: E402
from fabric.fabric_client import FabricClient  # noqa: E402
from fabric.lakehouse_manager import LakehouseManager  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fabric-config", default="fabric.config.yaml")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Also publish the data agent's staged configuration after creating/resolving it.",
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

    lakehouse_id = str(fabric_cfg.get("lakehouse_id") or "")
    lakehouse_name = str(fabric_cfg.get("lakehouse_name") or "")
    if not lakehouse_id:
        print("error: fabric.lakehouse_id is not set", file=sys.stderr)
        return 1

    agent_cfg = fabric_cfg.get("relationship_suggestion_agent") or {}
    display_name = str(agent_cfg.get("display_name") or "relationship_suggestion_agent")
    item_id = str(agent_cfg.get("item_id") or "")

    auth_cfg = FabricAuthConfig.from_mapping(fabric_cfg.get("auth") or {})
    credential = build_credential(auth_cfg)
    client = FabricClient(credential)

    # Resolve the lakehouse item so we can pass its live displayName through
    # (mirrors LakehouseManager's existing resolve-by-id usage elsewhere).
    lakehouse_manager = LakehouseManager(client, workspace_id)
    lakehouse_item = lakehouse_manager.resolve(lakehouse_id=lakehouse_id, lakehouse_name=lakehouse_name)
    lakehouse_display_name = str(lakehouse_item.get("displayName") or lakehouse_name or "ontology_lakehouse")

    manager = DataAgentManager(client, workspace_id)
    print(f"Resolving/creating data agent '{display_name}' in workspace {workspace_id} ...")
    result = ensure_data_agent(
        manager,
        display_name=display_name,
        lakehouse_id=lakehouse_id,
        lakehouse_workspace_id=workspace_id,
        lakehouse_display_name=lakehouse_display_name,
        item_id=item_id,
    )
    agent_id = str(result["id"])
    print(f"Data agent {result['action']}: id={agent_id} displayName={result.get('displayName')}")

    if args.publish:
        print("Publishing data agent staged configuration ...")
        published = manager.publish(agent_id)
        print(f"Publish complete: {published.get('id', agent_id)}")
        mcp_url = (
            f"https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspace_id}"
            f"/dataagents/{agent_id}/agent"
        )
        print(f"MCP query endpoint (per Microsoft Learn's Data Agent SDK doc): {mcp_url}")

    print(
        "Set fabric.relationship_suggestion_agent.item_id: "
        f'"{agent_id}" in {config_path} to reuse this item on future runs.'
    )
    print(
        "NOTE: this script provisions the item only. Invoking the agent to "
        "actually generate suggestions currently requires the Fabric portal's "
        "chat UI or the fabric-data-agent-sdk's OpenAI-compatible client "
        "(which this repo cannot import due to a namespace collision -- see "
        "docs/fabric-data-agent-relationship-suggestions.md)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
