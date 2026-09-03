"""Bounded Microsoft Defender for Cloud configuration execution.

Only the explicit actions in :data:`DEFENDER_CONFIGURATION_ACTIONS` can reach
ARM.  Request paths and bodies are code-authored; remediation plans select an
action and target but cannot supply arbitrary methods, URLs, or payloads.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from api.scope import Scope
from operations.patching.azure_adapter import ARM_ENDPOINT, ARM_SCOPE, TokenCredential

DEFENDER_CONFIGURATION_API_VERSION = "2024-01-01"
ENABLE_DEFENDER_SERVERS_P1 = "defender-enable-servers-plan-p1"
ENABLE_DEFENDER_STORAGE_V2 = "defender-enable-storage-plan-v2"

_SERVER_RESOURCE_TYPES = frozenset(
    {
        "microsoft.compute/virtualmachines",
        "microsoft.compute/virtualmachinescalesets",
        "microsoft.hybridcompute/machines",
    }
)


@dataclass(frozen=True)
class DefenderConfigurationAction:
    """One code-authored Defender configuration operation."""

    action_id: str
    operation: str
    pricing_name: str
    desired_properties: dict[str, Any]
    target_kind: str


DEFENDER_CONFIGURATION_ACTIONS: dict[str, DefenderConfigurationAction] = {
    ENABLE_DEFENDER_SERVERS_P1: DefenderConfigurationAction(
        action_id=ENABLE_DEFENDER_SERVERS_P1,
        operation="enable_defender_servers_plan_p1",
        pricing_name="virtualMachines",
        desired_properties={"pricingTier": "Standard", "subPlan": "P1"},
        target_kind="defender_resource_pricing",
    ),
    ENABLE_DEFENDER_STORAGE_V2: DefenderConfigurationAction(
        action_id=ENABLE_DEFENDER_STORAGE_V2,
        operation="enable_defender_storage_plan_v2",
        pricing_name="StorageAccounts",
        desired_properties={
            "pricingTier": "Standard",
            "subPlan": "DefenderForStorageV2",
            "extensions": [
                {"name": "OnUploadMalwareScanning", "isEnabled": "True"},
                {"name": "SensitiveDataDiscovery", "isEnabled": "True"},
            ],
        },
        target_kind="defender_subscription_pricing",
    ),
}
DEFENDER_CONFIGURATION_ACTION_IDS = frozenset(DEFENDER_CONFIGURATION_ACTIONS)


class DefenderConfigurationUnavailable(RuntimeError):
    """A Defender configuration action was refused or could not reach ARM."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "defender_configuration_unavailable",
        capability: str = "defender_configuration",
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.capability = capability


@dataclass(frozen=True)
class DefenderConfigurationResult:
    """The accepted Defender configuration submission."""

    provider: str
    provider_job_id: str
    state: str
    message: str


class DefenderConfigurationAdapter(Protocol):
    """Read and submit the bounded Defender configuration contract."""

    def inspect(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def submit(self, snapshot: dict[str, Any]) -> DefenderConfigurationResult: ...


class UnconfiguredDefenderConfigurationAdapter:
    """Safe default that refuses Defender configuration writes."""

    def inspect(self, request: dict[str, Any]) -> dict[str, Any]:
        raise DefenderConfigurationUnavailable(
            "No Defender configuration execution adapter is configured.",
            reason="configuration_execution_unavailable",
        )

    def submit(self, snapshot: dict[str, Any]) -> DefenderConfigurationResult:
        raise DefenderConfigurationUnavailable(
            "No Defender configuration execution adapter is configured.",
            reason="configuration_execution_unavailable",
        )


class AzureArmDefenderConfigurationAdapter:
    """Inspect and update explicit Microsoft.Security pricing resources."""

    def __init__(
        self,
        credential: TokenCredential,
        *,
        client: httpx.Client | None = None,
        endpoint: str = ARM_ENDPOINT,
        timeout: float = 30.0,
    ) -> None:
        self._credential = credential
        self._client = client
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout

    def inspect(self, request: dict[str, Any]) -> dict[str, Any]:
        """Read the current resource state used by the approval snapshot."""
        response = self._request("GET", request)
        if response.status_code == 404:
            return {"etag": "", "state_hash": _state_hash({}), "properties": {}}
        self._raise_for_status(response, "read")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DefenderConfigurationUnavailable(
                "Azure returned an invalid Defender configuration response."
            ) from exc
        if not isinstance(payload, dict):
            raise DefenderConfigurationUnavailable(
                "Azure returned an invalid Defender configuration response."
            )
        properties = payload.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        return {
            "etag": str(response.headers.get("ETag") or payload.get("etag") or ""),
            "state_hash": _state_hash(_configuration_state(properties)),
            "properties": properties,
        }

    def submit(self, snapshot: dict[str, Any]) -> DefenderConfigurationResult:
        """Revalidate approved state and issue the exact snapshotted PUT."""
        request = _validated_snapshot_request(snapshot)
        observed = self.inspect(request)
        expected = snapshot.get("precondition") or {}
        if observed["state_hash"] != str(expected.get("state_hash") or ""):
            raise DefenderConfigurationUnavailable(
                "Defender configuration changed after approval; refusing the stale write.",
                reason="execution_snapshot_drift",
            )
        expected_etag = str(expected.get("etag") or "")
        if expected_etag and observed["etag"] != expected_etag:
            raise DefenderConfigurationUnavailable(
                "Defender configuration ETag changed after approval; refusing the stale write.",
                reason="execution_snapshot_drift",
            )
        response = self._request(
            "PUT",
            request,
            headers={"If-Match": expected_etag} if expected_etag else None,
        )
        self._raise_for_status(response, "update")
        return DefenderConfigurationResult(
            provider="azure-arm-defender-configuration",
            provider_job_id=_request_url(self._endpoint, request),
            state="submitted",
            message="Accepted by Azure; a follow-up Microsoft.Security read is authoritative.",
        )

    def _request(
        self,
        method: str,
        request: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        token = self._token()
        request_headers = {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            **(headers or {}),
        }
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            return client.request(
                method,
                _request_url(self._endpoint, request),
                headers=request_headers,
                json=request["body"] if method == "PUT" else None,
            )
        except httpx.HTTPError as exc:
            raise DefenderConfigurationUnavailable(
                f"Azure Resource Manager was unreachable: {exc}"
            ) from exc
        finally:
            if self._client is None:
                client.close()

    def _token(self) -> str:
        try:
            token = self._credential.get_token(ARM_SCOPE)
        except Exception as exc:
            raise DefenderConfigurationUnavailable(
                f"Could not acquire an Azure management token: {exc}",
                reason="azure_arm_token_unavailable",
                capability="azure_arm_token",
            ) from exc
        value = str(getattr(token, "token", "") or "")
        if not value:
            raise DefenderConfigurationUnavailable(
                "Azure credential returned an empty management token.",
                reason="azure_arm_token_unavailable",
                capability="azure_arm_token",
            )
        return value

    @staticmethod
    def _raise_for_status(response: httpx.Response, operation: str) -> None:
        if response.status_code < 400:
            return
        raise DefenderConfigurationUnavailable(
            f"Azure rejected the Defender configuration {operation} "
            f"({response.status_code}): {_error_message(response)}"
        )


def build_defender_configuration_snapshot(
    plan: dict[str, Any],
    adapter: DefenderConfigurationAdapter,
    *,
    scope: Scope | None = None,
) -> dict[str, Any]:
    """Build a server-owned snapshot for an explicit supported action."""
    action_id = str(plan.get("action_id") or "")
    action = DEFENDER_CONFIGURATION_ACTIONS.get(action_id)
    if action is None:
        raise DefenderConfigurationUnavailable(
            "This Defender recommendation has no supported direct configuration action.",
            reason="unsupported_configuration_action",
        )
    target_id = _plan_target_id(plan, action)
    _validate_scope(target_id, scope)
    request = _request_for(action, target_id)
    observed = adapter.inspect(request)
    return {
        "snapshot_kind": "defender_configuration",
        "target_id": target_id,
        "patch_ids": [],
        "target_kind": action.target_kind,
        "operation": action.operation,
        "action_id": action.action_id,
        "action_version": str(plan.get("action_version") or ""),
        "request": request,
        "precondition": {
            "etag": str(observed.get("etag") or ""),
            "state_hash": str(observed.get("state_hash") or ""),
        },
        "prior_properties": _configuration_state(
            observed.get("properties")
            if isinstance(observed.get("properties"), dict)
            else {}
        ),
        "desired_properties": copy.deepcopy(action.desired_properties),
    }


def configuration_snapshot_hash(snapshot: dict[str, Any]) -> str:
    """Hash every executable Defender configuration snapshot field."""
    canonical = {
        key: snapshot.get(key)
        for key in (
            "snapshot_kind",
            "target_id",
            "target_kind",
            "operation",
            "action_id",
            "action_version",
            "request",
            "precondition",
            "prior_properties",
            "desired_properties",
        )
    }
    return hashlib.sha256(_stable_json(canonical).encode()).hexdigest()


def recommendation_action_id(recommendation: Any) -> str | None:
    """Map only exact known Defender recommendation titles to direct actions."""
    normalized = " ".join(str(recommendation or "").casefold().split())
    return {
        "microsoft defender for servers should be enabled": ENABLE_DEFENDER_SERVERS_P1,
        "azure defender for servers should be enabled": ENABLE_DEFENDER_SERVERS_P1,
        "microsoft defender for storage should be enabled": ENABLE_DEFENDER_STORAGE_V2,
        "azure defender for storage should be enabled": ENABLE_DEFENDER_STORAGE_V2,
    }.get(normalized)


def supported_recommendation_action_id(
    recommendation: Any, target_id: Any
) -> str | None:
    """Return a direct action only when both title and target are supported."""
    action_id = recommendation_action_id(recommendation)
    action = DEFENDER_CONFIGURATION_ACTIONS.get(action_id or "")
    if action is None:
        return None
    try:
        _plan_target_id(
            {
                "action_id": action.action_id,
                "resource": {"id": str(target_id or "")},
            },
            action,
        )
    except DefenderConfigurationUnavailable:
        return None
    return action.action_id


def is_defender_configuration_recommendation(recommendation: Any) -> bool:
    """Identify Defender configuration advice that needs mapping or refusal."""
    normalized = " ".join(str(recommendation or "").casefold().split())
    return (
        ("microsoft defender" in normalized or "azure defender" in normalized)
        and any(word in normalized for word in ("enable", "configure"))
    )


def _plan_target_id(
    plan: dict[str, Any], action: DefenderConfigurationAction
) -> str:
    resource = plan.get("resource") if isinstance(plan.get("resource"), dict) else {}
    target_id = str(resource.get("id") or plan.get("resource_key") or "").strip()
    if action.action_id == ENABLE_DEFENDER_STORAGE_V2:
        if not _is_subscription_id(target_id):
            raise DefenderConfigurationUnavailable(
                "Defender for Storage V2 is supported only for an explicitly "
                "subscription-scoped recommendation.",
                reason="configuration_target_not_supported",
            )
        return target_id.rstrip("/")
    resource_type = _resource_type(target_id)
    if (
        resource_type not in _SERVER_RESOURCE_TYPES
        or not _is_resource_id(target_id)
    ):
        raise DefenderConfigurationUnavailable(
            "Defender for Servers Plan 1 is supported only for an Azure VM, "
            "VM scale set, or Arc-enabled server target.",
            reason="configuration_target_not_supported",
        )
    return target_id.rstrip("/")


def _request_for(
    action: DefenderConfigurationAction, target_id: str
) -> dict[str, Any]:
    if action.target_kind == "defender_subscription_pricing":
        path = f"{target_id}/providers/Microsoft.Security/pricings/{action.pricing_name}"
    else:
        path = (
            f"{target_id}/providers/Microsoft.Security/pricings/{action.pricing_name}"
        )
    return {
        "method": "PUT",
        "path": path,
        "api_version": DEFENDER_CONFIGURATION_API_VERSION,
        "body": {"properties": copy.deepcopy(action.desired_properties)},
    }


def _validated_snapshot_request(snapshot: dict[str, Any]) -> dict[str, Any]:
    action = DEFENDER_CONFIGURATION_ACTIONS.get(str(snapshot.get("action_id") or ""))
    if action is None:
        raise DefenderConfigurationUnavailable(
            "The approved Defender configuration action is not supported.",
            reason="unsupported_configuration_action",
        )
    expected = _request_for(action, str(snapshot.get("target_id") or ""))
    request = snapshot.get("request")
    if request != expected or snapshot.get("desired_properties") != action.desired_properties:
        raise DefenderConfigurationUnavailable(
            "The approved Defender configuration request was altered.",
            reason="execution_snapshot_invalid",
        )
    return expected


def _validate_scope(target_id: str, scope: Scope | None) -> None:
    if scope is None or scope.is_unrestricted():
        return
    subscription = _subscription_id(target_id)
    allowed = {value.casefold() for value in scope.values("subscription")}
    if allowed and subscription.casefold() not in allowed:
        raise DefenderConfigurationUnavailable(
            "The Defender configuration target is outside the authorized subscription scope.",
            reason="scope_not_authorized",
        )


def _subscription_id(resource_id: str) -> str:
    parts = [part for part in resource_id.split("/") if part]
    if len(parts) >= 2 and parts[0].casefold() == "subscriptions":
        return parts[1]
    return ""


def _is_subscription_id(resource_id: str) -> bool:
    parts = [part for part in resource_id.split("/") if part]
    return len(parts) == 2 and parts[0].casefold() == "subscriptions" and bool(parts[1])


def _resource_type(resource_id: str) -> str:
    parts = [part for part in resource_id.split("/") if part]
    try:
        provider_index = next(
            index for index, part in enumerate(parts) if part.casefold() == "providers"
        )
    except StopIteration:
        return ""
    if provider_index + 2 >= len(parts):
        return ""
    return f"{parts[provider_index + 1]}/{parts[provider_index + 2]}".casefold()


def _is_resource_id(resource_id: str) -> bool:
    if "?" in resource_id or "#" in resource_id:
        return False
    parts = [part for part in resource_id.split("/") if part]
    return (
        resource_id.startswith("/")
        and len(parts) == 8
        and parts[0].casefold() == "subscriptions"
        and parts[2].casefold() == "resourcegroups"
        and parts[4].casefold() == "providers"
        and all(parts)
    )


def _state_hash(properties: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(properties).encode()).hexdigest()


def _configuration_state(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(properties[key])
        for key in ("pricingTier", "subPlan", "extensions")
        if key in properties
    }


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _request_url(endpoint: str, request: dict[str, Any]) -> str:
    return (
        f"{endpoint}{request['path']}?api-version={request['api_version']}"
    )


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or payload)[:500]
    return str(payload)[:500]


__all__ = [
    "DEFENDER_CONFIGURATION_ACTIONS",
    "DEFENDER_CONFIGURATION_ACTION_IDS",
    "ENABLE_DEFENDER_SERVERS_P1",
    "ENABLE_DEFENDER_STORAGE_V2",
    "AzureArmDefenderConfigurationAdapter",
    "DefenderConfigurationResult",
    "DefenderConfigurationUnavailable",
    "UnconfiguredDefenderConfigurationAdapter",
    "build_defender_configuration_snapshot",
    "configuration_snapshot_hash",
    "is_defender_configuration_recommendation",
    "recommendation_action_id",
    "supported_recommendation_action_id",
]
