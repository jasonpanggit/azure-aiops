#!/usr/bin/env python3
"""Push a generated Digital Twin Builder definition to Fabric.

This step MUST run as an interactive user (`az login`) -- Fabric's
Create/Update DigitalTwinBuilder item APIs explicitly do not support service
principals or managed identities (see infra/README.md). Run
`generate_digital_twin_builder.py` first to produce the definition JSON,
then run this script after `az login` as a user with Contributor+ on the
target workspace.

Usage:
    az login
    python3 infra/scripts/generate_digital_twin_builder.py \\
        --workspace-id <ws> --lakehouse-id <lh> --output /tmp/dtb.json
    python3 infra/scripts/push_digital_twin_builder.py \\
        --workspace-id <ws> --definition /tmp/dtb.json --display-name "Operational Context Graph"
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from typing import Any

import httpx

_API_BASE = "https://api.fabric.microsoft.com/v1"


def _get_user_token() -> str:
    result = subprocess.run(
        ["az", "account", "get-access-token", "--resource", "https://api.fabric.microsoft.com", "--query", "accessToken", "-o", "tsv"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(
            "Failed to get a user access token. Run `az login` (interactively, as a"
            " user, not a service principal) before running this script.",
            file=sys.stderr,
        )
        print(result.stderr, file=sys.stderr)
        raise SystemExit(1)
    return result.stdout.strip()


def _b64(payload: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _find_existing_item(client: httpx.Client, workspace_id: str, display_name: str) -> str | None:
    response = client.get(f"{_API_BASE}/workspaces/{workspace_id}/items", params={"type": "DigitalTwinBuilder"})
    response.raise_for_status()
    for item in response.json().get("value", []):
        if item.get("displayName") == display_name:
            return item.get("id")
    return None


def build_definition_parts(definition: dict[str, Any]) -> list[dict[str, str]]:
    parts = [
        {
            "path": "definition.json",
            "payload": _b64({"LakehouseId": definition["lakehouse_id"]}),
            "payloadType": "InlineBase64",
        }
    ]
    for table, entity_type in definition["entity_types"].items():
        parts.append(
            {
                "path": f"EntityTypes/{entity_type['Id']}.json",
                "payload": _b64(entity_type),
                "payloadType": "InlineBase64",
            }
        )
    for table, relationship in definition["relationship_types"].items():
        parts.append(
            {
                "path": f"EntityTypeRelationships/{relationship['Id']}.json",
                "payload": _b64(relationship),
                "payloadType": "InlineBase64",
            }
        )
    for table, operation in definition["contextualization_operations"].items():
        parts.append(
            {
                "path": f"ContextualizationOperations/{operation['OperationId']}.json",
                "payload": _b64(operation),
                "payloadType": "InlineBase64",
            }
        )
    for table, operation in definition["mapping_operations"].items():
        parts.append(
            {
                "path": f"MappingOperations/{operation['OperationId']}.json",
                "payload": _b64(operation),
                "payloadType": "InlineBase64",
            }
        )
    return parts


def _poll_lro(client: httpx.Client, response: httpx.Response) -> None:
    if response.status_code != 202:
        return
    operation_url = response.headers.get("Location")
    retry_after = float(response.headers.get("Retry-After", "2"))
    if not operation_url:
        return
    for _ in range(60):
        time.sleep(retry_after)
        poll = client.get(operation_url)
        poll.raise_for_status()
        status = poll.json().get("status")
        if status == "Succeeded":
            return
        if status == "Failed":
            raise RuntimeError(f"Fabric long-running operation failed: {poll.json()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--definition", required=True, help="Path to generate_digital_twin_builder.py output")
    parser.add_argument("--display-name", default="Operational Context Graph")
    args = parser.parse_args()

    definition = json.loads(open(args.definition).read())
    parts = build_definition_parts(definition)

    token = _get_user_token()
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=300.0) as client:
        existing_id = _find_existing_item(client, args.workspace_id, args.display_name)
        body = {"parts": parts}
        if existing_id:
            print(f"Updating existing DigitalTwinBuilder item {existing_id}...")
            response = client.post(
                f"{_API_BASE}/workspaces/{args.workspace_id}/items/{existing_id}/updateDefinition",
                json={"definition": body},
            )
        else:
            print("Creating new DigitalTwinBuilder item...")
            response = client.post(
                f"{_API_BASE}/workspaces/{args.workspace_id}/digitaltwinbuilders",
                json={"displayName": args.display_name, "definition": body},
            )
        response.raise_for_status()
        _poll_lro(client, response)

    print("Digital Twin Builder definition pushed successfully.")
    print(
        f"Entity types: {len(definition['entity_types'])}, "
        f"Relationship types: {len(definition['relationship_types'])}, "
        f"Mapping operations: {len(definition['mapping_operations'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
