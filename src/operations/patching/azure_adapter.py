"""Azure ARM execution adapter for patch runs.

This is the only module in HOG that issues a state-changing Azure call. It
translates an already-validated :class:`PatchRun` into exactly one ARM POST:

* Azure VM          -> ``Microsoft.Compute/virtualMachines/installPatches``
* Arc-enabled server-> ``Microsoft.HybridCompute/machines/installPatches``
* AKS node pool     -> ``Microsoft.ContainerService/.../agentPools/upgradeNodeImageVersion``

Design constraints that are deliberate:

* **No fan-out.** One run targets one resource. There is no "patch everything"
  path, because there is no way to approve one.
* **Selection is passed through verbatim.** The KB/package ids come from the
  run's allowlist, which :class:`operations.patching.service.PatchingService`
  already validated against what the target actually offers. This adapter never
  widens the selection, and never falls back to "all patches" if the list is
  empty -- it refuses instead.
* **HOG does not claim success.** These ARM operations are long-running. A 2xx
  means *accepted*, so the run is recorded as ``submitted`` with the upstream
  operation URL as ``provider_job_id``. Update Manager and AKS remain the
  authority on the final outcome.
"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .adapters import PatchExecutionResult, PatchExecutionUnavailable
from .models import (
    OPERATION_NODE_IMAGE_UPGRADE,
    TARGET_KIND_AKS_NODE,
    TARGET_KIND_ARC_SERVER,
    TARGET_KIND_AZURE_VM,
    PatchRun,
    PatchTarget,
)

ARM_ENDPOINT = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"

# Pinned per resource provider. Update Manager's Arc surface is still preview,
# which is itself a reason to keep this boundary narrow and explicit.
COMPUTE_API_VERSION = "2024-07-01"
HYBRID_COMPUTE_API_VERSION = "2024-07-10"
CONTAINER_SERVICE_API_VERSION = "2024-05-01"

# Update Manager rejects a request that selects nothing, and "no filter" means
# "install everything" -- which is precisely the unbounded action this system
# is designed not to perform implicitly.
_LINUX_OS_HINTS = ("linux", "ubuntu", "rhel", "red hat", "centos", "suse", "sles", "debian")


class TokenCredential(Protocol):
    """The ``get_token`` slice of azure-identity we actually depend on."""

    def get_token(self, *scopes: str, **kwargs: Any) -> Any: ...


def classify_azure_response_failure(status_code: int) -> str:
    """Map one Azure ARM HTTP status code onto the closed failure vocabulary.

    Single source of truth for status-to-class mapping (Phase 03.3's
    Failure Classification decision): every adapter that receives an HTTP
    error response from Azure -- the patch adapter's POST and the Defender
    configuration adapter's GET/PUT -- classifies through this one helper,
    so there is exactly one status-to-class mapping in the codebase.
    """
    if status_code in (401, 403):
        return "provider_authorization"
    if status_code == 429 or status_code >= 500:
        return "provider_transient"
    return "provider_rejected"


def _is_linux(target: PatchTarget) -> bool:
    os_family = str(target.os_family or "").casefold()
    return any(hint in os_family for hint in _LINUX_OS_HINTS)


def _resource_group(resource_id: str) -> str:
    parts = [part for part in str(resource_id or "").split("/") if part]
    for index, part in enumerate(parts):
        if part.casefold() == "resourcegroups" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _install_patches_body(run: PatchRun, target: PatchTarget) -> dict[str, Any]:
    """Build an installPatches body restricted to the approved selection."""
    patch_ids = [patch_id for patch_id in run.patch_ids if patch_id]
    if not patch_ids:
        raise PatchExecutionUnavailable(
            "Refusing to submit an installPatches request with no selected "
            "patches: an empty filter installs everything.",
            capability="update_manager_install_patches",
            provider_submitted=False,
            failure_class="internal_validation",
        )

    body: dict[str, Any] = {
        "maximumDuration": "PT2H",
        "rebootSetting": run.reboot_setting or "IfRequired",
    }
    if _is_linux(target):
        # Linux Update Manager filters by package name, not KB number.
        body["linuxParameters"] = {"packageNameMasksToInclude": patch_ids}
    else:
        body["windowsParameters"] = {"kbNumbersToInclude": patch_ids}
    return body


class AzureArmPatchExecutionAdapter:
    """Submits approved patch runs to Azure Resource Manager.

    The credential must carry the narrow write roles these operations need
    (for example ``Azure Connected Machine Resource Administrator`` for Arc and
    a role granting ``Microsoft.ContainerService/managedClusters/agentPools/
    upgradeNodeImageVersion/action`` for AKS). Deliberately no broad
    Contributor assumption is baked in here.
    """

    name = "azure-arm"

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

    # -- HTTP -------------------------------------------------------------

    def _token(self) -> str:
        try:
            token = self._credential.get_token(ARM_SCOPE)
        except Exception as exc:  # surfaced as a typed refusal below
            raise PatchExecutionUnavailable(
                f"Could not acquire an Azure management token: {exc}",
                capability="azure_arm_token",
                provider_submitted=False,
                failure_class="provider_authorization",
            ) from exc
        value = getattr(token, "token", "") or ""
        if not value:
            raise PatchExecutionUnavailable(
                "Azure credential returned an empty management token.",
                capability="azure_arm_token",
                provider_submitted=False,
                failure_class="provider_authorization",
            )
        return str(value)

    def _post(self, path: str, api_version: str, body: dict[str, Any] | None) -> httpx.Response:
        url = f"{self._endpoint}{path}?api-version={api_version}"
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
        }
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            return client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            # This IS the mutating POST -- there is no read-only path in
            # this adapter. The request may have already crossed the
            # mutation boundary before the transport failed, so this must
            # fail closed as submission-ambiguous and consume budget until
            # reconciled (Recommendation 2, Submission Accounting decision).
            raise PatchExecutionUnavailable(
                f"Azure Resource Manager was unreachable: {exc}",
                capability="azure_arm_request",
                provider_submitted=True,
                failure_class="submission_ambiguous",
            ) from exc
        finally:
            if self._client is None:
                client.close()

    # -- Adapter protocol -------------------------------------------------

    def submit(self, run: PatchRun, target: PatchTarget) -> PatchExecutionResult:
        if run.operation == OPERATION_NODE_IMAGE_UPGRADE:
            path, api_version, body = self._node_image_request(run, target)
        else:
            path, api_version, body = self._install_patches_request(run, target)

        response = self._post(path, api_version, body)
        if response.status_code >= 400:
            raise PatchExecutionUnavailable(
                f"Azure rejected the patch request ({response.status_code}): "
                f"{_error_message(response)}",
                capability=_capability(run),
                provider_submitted=True,
                failure_class=classify_azure_response_failure(response.status_code),
            )

        # 200/201/202 all mean accepted for these long-running operations. The
        # tracking URL is the system of record for the outcome.
        operation_url = (
            response.headers.get("Azure-AsyncOperation")
            or response.headers.get("Location")
            or ""
        )
        return PatchExecutionResult(
            provider=self.name,
            provider_job_id=operation_url,
            state="submitted",
            message=(
                "Accepted by Azure; Update Manager is authoritative for the outcome."
                if run.operation != OPERATION_NODE_IMAGE_UPGRADE
                else "Accepted by Azure; AKS is authoritative for the upgrade outcome."
            ),
            details={
                "http_status": response.status_code,
                "operation_url": operation_url,
                "resource_id": target.target_id,
                "api_version": api_version,
            },
        )

    # -- Request builders -------------------------------------------------

    def _install_patches_request(
        self, run: PatchRun, target: PatchTarget
    ) -> tuple[str, str, dict[str, Any]]:
        if target.inventory_kind == TARGET_KIND_ARC_SERVER:
            api_version = HYBRID_COMPUTE_API_VERSION
        elif target.inventory_kind == TARGET_KIND_AZURE_VM:
            api_version = COMPUTE_API_VERSION
        else:
            raise PatchExecutionUnavailable(
                f"No install-patches route for inventory kind {target.inventory_kind!r}.",
                capability="update_manager_install_patches",
                provider_submitted=False,
                failure_class="target_precondition",
            )

        resource_id = _require_resource_id(target)
        return f"{resource_id}/installPatches", api_version, _install_patches_body(run, target)

    def _node_image_request(
        self, run: PatchRun, target: PatchTarget
    ) -> tuple[str, str, None]:
        if target.inventory_kind != TARGET_KIND_AKS_NODE:
            raise PatchExecutionUnavailable(
                f"Node image upgrade is not valid for inventory kind {target.inventory_kind!r}.",
                capability="aks_node_image_upgrade",
                provider_submitted=False,
                failure_class="target_precondition",
            )

        cluster_id = _require_resource_id(target)
        node_pool = _node_pool(run, target)
        if not node_pool:
            raise PatchExecutionUnavailable(
                "The AKS node pool could not be determined for this upgrade; "
                "HOG will not upgrade every pool in the cluster implicitly.",
                capability="aks_node_image_upgrade",
                provider_submitted=False,
                failure_class="target_precondition",
            )
        path = f"{cluster_id}/agentPools/{quote(node_pool, safe='')}/upgradeNodeImageVersion"
        # The ARM operation always rolls the pool to the latest available image;
        # it takes no body. The selected version is retained on the run record
        # so the operator's intent stays auditable.
        return path, CONTAINER_SERVICE_API_VERSION, None


def _require_resource_id(target: PatchTarget) -> str:
    resource_id = str(target.target_id or "").strip()
    if not resource_id.startswith("/subscriptions/"):
        raise PatchExecutionUnavailable(
            f"{target.target_id!r} is not an Azure resource id, so it cannot be "
            "patched through Resource Manager.",
            capability="azure_arm_request",
            provider_submitted=False,
            failure_class="target_precondition",
        )
    if not _resource_group(resource_id):
        raise PatchExecutionUnavailable(
            f"{target.target_id!r} has no resource group segment.",
            capability="azure_arm_request",
            provider_submitted=False,
            failure_class="target_precondition",
        )
    return resource_id.rstrip("/")


def _node_pool(run: PatchRun, target: PatchTarget) -> str:
    """The pool named by the selected upgrade, falling back to target metadata."""
    selected = {patch_id for patch_id in run.patch_ids if patch_id}
    for patch in target.available_patches:
        if patch.patch_id in selected and patch.node_pool:
            return patch.node_pool
    return str(run.details.get("node_pool") or "").strip()


def _capability(run: PatchRun) -> str:
    return (
        "aks_node_image_upgrade"
        if run.operation == OPERATION_NODE_IMAGE_UPGRADE
        else "update_manager_install_patches"
    )


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - non-JSON error bodies are still useful
        return response.text[:500]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or payload)[:500]
    return str(payload)[:500]


__all__ = [
    "ARM_ENDPOINT",
    "ARM_SCOPE",
    "AzureArmPatchExecutionAdapter",
    "TokenCredential",
    "classify_azure_response_failure",
]
