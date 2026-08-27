"""Tests for the ARM execution adapter — the only code path that mutates Azure.

The assertions here are mostly about what the adapter *refuses* to do: submit
an unbounded patch request, upgrade a cluster when the node pool is unknown, or
report success for an operation Azure has merely accepted.
"""

from __future__ import annotations

import httpx
import pytest

from operations.patching.adapters import PatchExecutionUnavailable
from operations.patching.azure_adapter import (
    CONTAINER_SERVICE_API_VERSION,
    AzureArmPatchExecutionAdapter,
)
from operations.patching.models import AvailablePatch, PatchRun, PatchTarget

VM_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
ARC_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc1"
AKS_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks1"


class FakeToken:
    token = "fake-arm-token"


class FakeCredential:
    def __init__(self, token: object | None = None, error: Exception | None = None) -> None:
        self._token = token if token is not None else FakeToken()
        self._error = error

    def get_token(self, *scopes: str, **kwargs: object) -> object:
        if self._error:
            raise self._error
        return self._token


def _transport(recorder: list[httpx.Request], response: httpx.Response) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        return response

    return httpx.MockTransport(handler)


def _adapter(recorder: list[httpx.Request], response: httpx.Response, credential=None):
    client = httpx.Client(transport=_transport(recorder, response))
    return AzureArmPatchExecutionAdapter(credential or FakeCredential(), client=client)


def _target(**overrides) -> PatchTarget:
    defaults: dict = {
        "target_id": VM_ID,
        "name": "vm1",
        "inventory_kind": "Azure VM",
        "subscription_id": "sub-1",
        "resource_group": "rg",
        "os_family": "Windows Server 2022",
        "available_patches": (AvailablePatch(patch_id="KB600001"),),
    }
    defaults.update(overrides)
    return PatchTarget(**defaults)


def _run(**overrides) -> PatchRun:
    defaults: dict = {
        "run_id": "run-1",
        "target_id": VM_ID,
        "inventory_kind": "Azure VM",
        "operation": "install_patches",
        "patch_ids": ("KB600001",),
        "reboot_setting": "IfRequired",
    }
    defaults.update(overrides)
    return PatchRun(**defaults)


def _accepted(headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        202,
        headers=headers or {"Azure-AsyncOperation": "https://management.azure.com/op/123"},
        json={},
    )


def test_windows_vm_sends_only_the_selected_kbs() -> None:
    calls: list[httpx.Request] = []
    result = _adapter(calls, _accepted()).submit(_run(), _target())

    assert len(calls) == 1
    request = calls[0]
    assert request.url.path == f"{VM_ID}/installPatches"
    assert request.url.params["api-version"]
    assert request.headers["Authorization"] == "Bearer fake-arm-token"

    import json

    body = json.loads(request.content)
    assert body["windowsParameters"]["kbNumbersToInclude"] == ["KB600001"]
    assert body["rebootSetting"] == "IfRequired"
    # No blanket classification filter that would widen the run.
    assert "classificationsToInclude" not in body["windowsParameters"]

    assert result.state == "submitted"
    assert result.provider_job_id == "https://management.azure.com/op/123"


def test_linux_targets_use_package_masks_not_kb_numbers() -> None:
    calls: list[httpx.Request] = []
    _adapter(calls, _accepted()).submit(
        _run(patch_ids=("openssl",)),
        _target(os_family="Ubuntu 22.04", available_patches=(AvailablePatch(patch_id="openssl"),)),
    )

    import json

    body = json.loads(calls[0].content)
    assert body["linuxParameters"]["packageNameMasksToInclude"] == ["openssl"]
    assert "windowsParameters" not in body


def test_arc_servers_route_to_hybrid_compute() -> None:
    calls: list[httpx.Request] = []
    _adapter(calls, _accepted()).submit(
        _run(target_id=ARC_ID, inventory_kind="Arc-enabled server"),
        _target(target_id=ARC_ID, inventory_kind="Arc-enabled server"),
    )
    assert calls[0].url.path == f"{ARC_ID}/installPatches"


def test_empty_selection_is_refused_rather_than_installing_everything() -> None:
    calls: list[httpx.Request] = []
    adapter = _adapter(calls, _accepted())
    with pytest.raises(PatchExecutionUnavailable, match="installs everything"):
        adapter.submit(_run(patch_ids=()), _target())
    assert calls == []


def test_node_image_upgrade_targets_the_selected_pool() -> None:
    calls: list[httpx.Request] = []
    target = _target(
        target_id=AKS_ID,
        inventory_kind="AKS node",
        available_patches=(AvailablePatch(patch_id="latest", node_pool="systempool"),),
    )
    result = _adapter(calls, _accepted()).submit(
        _run(target_id=AKS_ID, inventory_kind="AKS node", operation="node_image_upgrade", patch_ids=("latest",)),
        target,
    )

    request = calls[0]
    assert request.url.path == f"{AKS_ID}/agentPools/systempool/upgradeNodeImageVersion"
    assert request.url.params["api-version"] == CONTAINER_SERVICE_API_VERSION
    # The ARM operation takes no body.
    assert request.content in (b"", b"null")
    assert result.state == "submitted"


def test_node_image_upgrade_accepts_a_pool_named_on_the_run() -> None:
    """The operator-supplied pool is how AKS upgrades are scoped in practice."""
    calls: list[httpx.Request] = []
    _adapter(calls, _accepted()).submit(
        _run(
            target_id=AKS_ID,
            inventory_kind="AKS node",
            operation="node_image_upgrade",
            patch_ids=("latest",),
            details={"node_pool": "userpool"},
        ),
        _target(
            target_id=AKS_ID,
            inventory_kind="AKS node",
            available_patches=(AvailablePatch(patch_id="latest"),),
        ),
    )
    assert calls[0].url.path == f"{AKS_ID}/agentPools/userpool/upgradeNodeImageVersion"


def test_node_image_upgrade_refuses_when_the_pool_is_unknown() -> None:
    calls: list[httpx.Request] = []
    adapter = _adapter(calls, _accepted())
    with pytest.raises(PatchExecutionUnavailable, match="node pool"):
        adapter.submit(
            _run(target_id=AKS_ID, inventory_kind="AKS node", operation="node_image_upgrade", patch_ids=("latest",)),
            _target(
                target_id=AKS_ID,
                inventory_kind="AKS node",
                available_patches=(AvailablePatch(patch_id="latest"),),
            ),
        )
    assert calls == []


def test_non_resource_id_targets_are_refused() -> None:
    calls: list[httpx.Request] = []
    adapter = _adapter(calls, _accepted())
    with pytest.raises(PatchExecutionUnavailable, match="not an Azure resource id"):
        adapter.submit(_run(target_id="server-1"), _target(target_id="server-1"))
    assert calls == []


def test_arm_error_is_surfaced_with_the_azure_message() -> None:
    calls: list[httpx.Request] = []
    response = httpx.Response(
        403,
        json={"error": {"code": "AuthorizationFailed", "message": "does not have permission"}},
    )
    adapter = _adapter(calls, response)
    with pytest.raises(PatchExecutionUnavailable, match="does not have permission"):
        adapter.submit(_run(), _target())


def test_token_failure_is_a_typed_refusal_not_a_crash() -> None:
    calls: list[httpx.Request] = []
    adapter = _adapter(calls, _accepted(), credential=FakeCredential(error=RuntimeError("no identity")))
    with pytest.raises(PatchExecutionUnavailable, match="management token"):
        adapter.submit(_run(), _target())
    assert calls == []


def test_unreachable_arm_is_a_typed_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = AzureArmPatchExecutionAdapter(FakeCredential(), client=client)
    with pytest.raises(PatchExecutionUnavailable, match="unreachable"):
        adapter.submit(_run(), _target())
