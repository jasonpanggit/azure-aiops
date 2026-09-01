from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from azure.identity import DefaultAzureCredential

ARM_SCOPE = "https://management.azure.com/.default"
ARM_ENDPOINT = "https://management.azure.com"
ARM_API_VERSION = "2023-11-01"


class TokenCredential(Protocol):
    def get_token(self, *scopes: str, **kwargs: Any) -> Any: ...


def _default_arm_credential() -> TokenCredential:
    return DefaultAzureCredential()


def _checked_at(clock: Callable[[], datetime] | None = None) -> str:
    current = (clock or (lambda: datetime.now(UTC)))()
    return current.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _classify(raw_state: str) -> str:
    state = raw_state.casefold()
    if state == "active":
        return "healthy"
    if state == "paused":
        return "unavailable"
    return "unknown"


def check_capacity_state(
    subscription_id: str,
    resource_group: str,
    capacity_name: str,
    *,
    credential: TokenCredential | None = None,
    requester: Callable[..., httpx.Response] = httpx.request,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, str]:
    checked = _checked_at(clock)
    response_shape = {
        "state": "unknown",
        "raw_state": "",
        "provisioning_state": "",
        "sku": "",
        "checked_at": checked,
    }
    if not subscription_id or not resource_group or not capacity_name:
        return response_shape
    active_credential = credential or _default_arm_credential()
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Fabric/capacities/{capacity_name}"
    )
    url = f"{ARM_ENDPOINT}{resource_id}"
    try:
        token = active_credential.get_token(ARM_SCOPE)
        access_token = str(getattr(token, "token", "") or "")
        if not access_token:
            return response_shape
        response = requester(
            "GET",
            url,
            params={"api-version": ARM_API_VERSION},
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001 - unknown is the explicit error state
        return response_shape

    properties = payload.get("properties") if isinstance(payload, dict) else {}
    sku = payload.get("sku") if isinstance(payload, dict) else {}
    raw_state = str((properties or {}).get("state") or "")
    return {
        "state": _classify(raw_state),
        "raw_state": raw_state,
        "provisioning_state": str((properties or {}).get("provisioningState") or ""),
        "sku": str((sku or {}).get("name") or ""),
        "checked_at": checked,
    }
