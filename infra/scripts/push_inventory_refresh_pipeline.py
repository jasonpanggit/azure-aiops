#!/usr/bin/env python3
"""Create/update the native Fabric Data Pipeline that triggers inventory refresh.

Unlike Digital Twin Builder, Fabric's DataPipeline item type supports both
service principal and managed identity callers (see
https://learn.microsoft.com/en-us/rest/api/fabric/datapipeline/items/create-data-pipeline#microsoft-entra-supported-identities),
so this script can run non-interactively as part of the SPN-driven deploy
flow -- it does not require `az login` as a user.

The pipeline has a single Web activity that POSTs to the deployed API's
`/api/v1/inventory/refresh` trigger endpoint (see
`src/api/routers/inventory.py`), authenticated via the same shared-secret
header the endpoint itself validates (`x-aiops-trigger-secret`). Fabric
owns *scheduling* only; all acquisition/normalization/publication logic
stays in Python (`run_inventory_refresh`) so there is exactly one
implementation of that logic to maintain.

Usage:
    python3 infra/scripts/push_inventory_refresh_pipeline.py \\
        --workspace-id <ws> \\
        --api-url https://aiops-dev-api.<region>.azurecontainerapps.io \\
        --trigger-secret <secret> \\
        [--display-name "Inventory Refresh"] \\
        [--schedule-interval Hour --schedule-frequency 1]

Auth: uses DefaultAzureCredential (same chain as the rest of the codebase),
so it picks up `az login`, a service principal via AZURE_CLIENT_ID/
AZURE_CLIENT_SECRET/AZURE_TENANT_ID, or a managed identity automatically.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from typing import Any

import httpx
from azure.identity import DefaultAzureCredential

_API_BASE = "https://api.fabric.microsoft.com/v1"
_SCOPE = "https://api.fabric.microsoft.com/.default"


def _b64(payload: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload, indent=2).encode("utf-8")).decode("ascii")


def _get_token() -> str:
    credential = DefaultAzureCredential()
    return credential.get_token(_SCOPE).token


def _find_existing_item(client: httpx.Client, workspace_id: str, display_name: str) -> str | None:
    response = client.get(f"{_API_BASE}/workspaces/{workspace_id}/items", params={"type": "DataPipeline"})
    response.raise_for_status()
    for item in response.json().get("value", []):
        if item.get("displayName") == display_name:
            return item.get("id")
    return None


def _find_existing_connection(client: httpx.Client, display_name: str) -> tuple[str, str] | None:
    response = client.get("/connections")
    response.raise_for_status()
    for conn in response.json().get("value", []):
        if conn.get("displayName") == display_name:
            conn_type = conn.get("connectionDetails", {}).get("type", "")
            return conn.get("id"), conn_type
    return None


def ensure_web_connection(client: httpx.Client, api_url: str, *, display_name: str) -> str:
    """Create (or reuse) the Fabric "WebForPipeline" connection the Web
    activity binds to.

    Fabric's pipeline WebActivity always resolves its target through a
    Connection resource (`externalReferences.connection`) -- unlike classic
    ADF, it has no inline-URL mode. The connector type must be
    "WebForPipeline" (creation method "WebForPipeline.Contents", parameter
    "baseUrl") -- the "Web" connector type is for Power Query/Dataflow Gen2
    and is NOT compatible with pipeline WebActivity; using it produces a
    misleading "datasetSettings are required for the connection 'Web'"
    runtime error. Authentication stays anonymous at the connection level
    because the real auth is the `x-aiops-trigger-secret` header baked
    into the activity's own `typeProperties.headers`.
    """
    existing = _find_existing_connection(client, display_name)
    if existing:
        existing_id, existing_type = existing
        if existing_type != "WebForPipeline":
            # Stale connection from before we learned pipeline WebActivity
            # requires the "WebForPipeline" connector (not the Power-Query
            # "Web" connector) -- delete and recreate with the right type.
            client.delete(f"/connections/{existing_id}")
        else:
            return existing_id
    body = {
        "connectivityType": "ShareableCloud",
        "displayName": display_name,
        "connectionDetails": {
            "type": "WebForPipeline",
            "creationMethod": "WebForPipeline.Contents",
            "parameters": [{"dataType": "Text", "name": "baseUrl", "value": api_url.rstrip("/")}],
        },
        "privacyLevel": "Organizational",
        "credentialDetails": {
            "singleSignOnType": "None",
            "connectionEncryption": "NotEncrypted",
            "credentials": {"credentialType": "Anonymous"},
        },
    }
    response = client.post("/connections", json=body)
    if response.status_code != 201:
        print(response.text, file=sys.stderr)
    response.raise_for_status()
    return response.json()["id"]


def sync_connection_access(client: httpx.Client, workspace_id: str, connection_id: str) -> None:
    """Grant every workspace Admin/Member user Owner access on the connection.

    Fabric connections have their own, separate role-assignment list from the
    workspace/item they're used by. A user can be a workspace Admin and still
    see "Failed to load the connection. Please make sure it exists and you
    have the permissions to access it." in the pipeline UI if they were never
    explicitly granted a role on the connection itself (this happened live:
    the connection was created by the deploying service principal, which
    made itself the sole Owner). This keeps human operators able to view/
    edit the pipeline in the portal without needing a manual one-off grant
    after every fresh deployment.
    """
    ws_roles = client.get(f"/workspaces/{workspace_id}/roleAssignments")
    ws_roles.raise_for_status()
    conn_roles = client.get(f"/connections/{connection_id}/roleAssignments")
    conn_roles.raise_for_status()
    existing_principal_ids = {r["principal"]["id"] for r in conn_roles.json().get("value", [])}

    for assignment in ws_roles.json().get("value", []):
        principal = assignment["principal"]
        if principal.get("type") != "User" or assignment.get("role") not in ("Admin", "Member"):
            continue
        if principal["id"] in existing_principal_ids:
            continue
        body = {"principal": {"id": principal["id"], "type": "User"}, "role": "Owner"}
        response = client.post(f"/connections/{connection_id}/roleAssignments", json=body)
        if response.status_code == 201:
            print(f"Granted connection access to {principal.get('displayName', principal['id'])}.", file=sys.stderr)
        elif response.status_code != 400:
            print(response.text, file=sys.stderr)


def build_pipeline_content(
    api_url: str,
    trigger_secret: str,
    connection_id: str,
    *,
    timeout_seconds: int = 3 * 60 * 60,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    request_timeout_seconds = min(timeout_seconds, 10 * 60)
    request_timeout = (
        f"{request_timeout_seconds // 3600:02d}:"
        f"{(request_timeout_seconds % 3600) // 60:02d}:"
        f"{request_timeout_seconds % 60:02d}"
    )
    return {
        "properties": {
            "description": (
                "Triggers the unified inventory refresh (ARG acquisition + "
                "normalization + OneLake publication) via the deployed API's "
                "POST /api/v1/inventory/refresh endpoint. All refresh logic "
                "lives in Python -- this pipeline only schedules the call."
            ),
            "activities": [
                {
                    "name": "TriggerInventoryRefresh",
                    "type": "WebActivity",
                    "dependsOn": [],
                    "policy": {
                        "timeout": f"0.{timeout_seconds // 3600:02d}:{(timeout_seconds % 3600) // 60:02d}:{timeout_seconds % 60:02d}",
                        "retry": 0,
                        "retryIntervalInSeconds": 30,
                        "secureOutput": False,
                        "secureInput": True,
                    },
                    "externalReferences": {"connection": connection_id},
                    "typeProperties": {
                        "relativeUrl": "/api/v1/inventory/refresh",
                        "method": "POST",
                        "httpRequestTimeout": request_timeout,
                        # The endpoint answers 202 + Location and the activity
                        # polls it until the refresh finishes, so the activity
                        # outcome is the refresh outcome. The activity policy
                        # timeout therefore bounds the whole refresh.
                        "disableAsyncPattern": False,
                        "headers": {
                            "Content-Type": "application/json",
                            "x-aiops-trigger-secret": trigger_secret,
                        },
                        "body": "{}",
                    },
                }
            ],
        }
    }


def build_definition_parts(pipeline_content: dict[str, Any]) -> list[dict[str, str]]:
    platform = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {
            "type": "DataPipeline",
            "displayName": "Inventory Refresh",
        },
        "config": {"version": "2.0", "logicalId": "00000000-0000-0000-0000-000000000000"},
    }
    return [
        {
            "path": "pipeline-content.json",
            "payload": _b64(pipeline_content),
            "payloadType": "InlineBase64",
        },
        {
            "path": ".platform",
            "payload": _b64(platform),
            "payloadType": "InlineBase64",
        },
    ]


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
    raise RuntimeError("Fabric long-running operation did not complete within the poll budget")


def create_schedule(
    client: httpx.Client,
    workspace_id: str,
    item_id: str,
    *,
    interval_minutes: int,
) -> None:
    """Create or reconcile one recurring Cron schedule for the pipeline.

    DataPipeline's runnable job type is "Pipeline". Schedules only control
    timing -- they cannot carry a custom payload -- which is fine here since
    the Web activity's request body/headers are already baked into the
    pipeline definition itself. Repeated deployments reuse the oldest
    schedule and disable duplicates so they cannot trigger overlapping runs.
    """
    start = time.gmtime()
    # Fabric requires an explicit endDateTime for Cron schedules; use a
    # 10-year horizon so this recurring schedule effectively never expires.
    end = time.gmtime(time.time() + 10 * 365 * 24 * 3600)
    schedules_path = (
        f"/workspaces/{workspace_id}/items/{item_id}/jobs/Pipeline/schedules"
    )
    configuration = {
        "type": "Cron",
        "interval": interval_minutes,
        "startDateTime": time.strftime("%Y-%m-%dT%H:%M:%S", start),
        "endDateTime": time.strftime("%Y-%m-%dT%H:%M:%S", end),
        "localTimeZoneId": "UTC",
    }
    schedule_payload = {
        "enabled": True,
        "configuration": configuration,
    }
    existing_response = client.get(schedules_path)
    existing_response.raise_for_status()
    existing = sorted(
        (
            schedule
            for schedule in existing_response.json().get("value", [])
            if schedule.get("id")
        ),
        key=lambda schedule: (
            str(schedule.get("createdDateTime") or ""),
            str(schedule["id"]),
        ),
    )
    if existing:
        primary = existing[0]
        response = client.patch(
            f"{schedules_path}/{primary['id']}",
            json=schedule_payload,
        )
        response.raise_for_status()
        _poll_lro(client, response)
        for duplicate in existing[1:]:
            response = client.patch(
                f"{schedules_path}/{duplicate['id']}",
                json={
                    "enabled": False,
                    "configuration": dict(
                        duplicate.get("configuration") or configuration
                    ),
                },
            )
            response.raise_for_status()
            _poll_lro(client, response)
        return

    response = client.post(
        schedules_path,
        json=schedule_payload,
    )
    if response.status_code not in (200, 201, 202):
        print(response.text, file=sys.stderr)
    response.raise_for_status()
    _poll_lro(client, response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--api-url", required=True, help="Base URL of the deployed API (e.g. https://aiops-dev-api.<region>.azurecontainerapps.io)")
    parser.add_argument("--trigger-secret", required=True, help="Value of AIOPS_REFRESH_TRIGGER_SECRET on the API")
    parser.add_argument("--display-name", default="Inventory Refresh")
    parser.add_argument("--timeout-seconds", type=int, default=3 * 60 * 60)
    parser.add_argument(
        "--schedule-interval-minutes",
        type=int,
        default=0,
        help="If set (>0), create/replace a recurring Cron schedule with this interval in minutes.",
    )
    args = parser.parse_args()

    token = _get_token()
    client = httpx.Client(
        base_url=_API_BASE,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=60,
    )

    connection_id = ensure_web_connection(client, args.api_url, display_name=f"{args.display_name} API")
    sync_connection_access(client, args.workspace_id, connection_id)
    pipeline_content = build_pipeline_content(
        args.api_url, args.trigger_secret, connection_id, timeout_seconds=args.timeout_seconds
    )
    parts = build_definition_parts(pipeline_content)
    definition = {"parts": parts}

    existing_id = _find_existing_item(client, args.workspace_id, args.display_name)
    if existing_id:
        print(f"Updating existing DataPipeline item {existing_id} ('{args.display_name}')...", file=sys.stderr)
        response = client.post(
            f"/workspaces/{args.workspace_id}/items/{existing_id}/updateDefinition",
            json={"definition": definition},
        )
        response.raise_for_status()
        _poll_lro(client, response)
        item_id = existing_id
    else:
        print(f"Creating new DataPipeline item '{args.display_name}'...", file=sys.stderr)
        response = client.post(
            f"/workspaces/{args.workspace_id}/dataPipelines",
            json={"displayName": args.display_name, "definition": definition},
        )
        if response.status_code not in (200, 201, 202):
            print(response.text, file=sys.stderr)
        response.raise_for_status()
        _poll_lro(client, response)
        item_id = response.json().get("id") if response.status_code == 201 else None
        if item_id is None:
            item_id = _find_existing_item(client, args.workspace_id, args.display_name)

    print(json.dumps({"workspaceId": args.workspace_id, "itemId": item_id, "displayName": args.display_name}, indent=2))

    if args.schedule_interval_minutes > 0:
        if not item_id:
            print("Cannot create schedule: item ID unavailable (unexpected 202 without polled ID).", file=sys.stderr)
        else:
            print(f"Creating {args.schedule_interval_minutes}-minute Cron schedule...", file=sys.stderr)
            create_schedule(client, args.workspace_id, item_id, interval_minutes=args.schedule_interval_minutes)
            print("Schedule created.", file=sys.stderr)
    else:
        print(
            "\nNo --schedule-interval-minutes given -- configure a schedule "
            "later via this script or the Fabric UI (pipeline > Home tab > Schedule).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
