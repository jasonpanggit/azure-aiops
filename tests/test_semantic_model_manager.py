from __future__ import annotations

import base64
import json

import httpx
import pytest

from fabric.fabric_client import FabricClient
from fabric.semantic_model_manager import build_semantic_model_definition
from fabric.semantic_model_manager import deploy_semantic_model


def _parts(definition: dict) -> dict[str, dict]:
    return {part["path"]: part for part in definition["parts"]}


def _decode_part(definition: dict, path: str) -> dict:
    payload = _parts(definition)[path]["payload"]
    return json.loads(base64.b64decode(payload).decode("utf-8"))


def test_build_definition_references_only_passed_gold_table_names() -> None:
    tables = ["gold_incident_summary", "gold_patch_risk"]
    definition = build_semantic_model_definition("aiops_gold_semantic_model", tables)
    model = _decode_part(definition, "model.bim")
    actual_table_names = [table["name"] for table in model["model"]["tables"]]

    assert actual_table_names == tables
    assert "gold_invented_table" not in actual_table_names


def test_build_definition_does_not_embed_unified_inventory_identity_fields() -> None:
    definition = build_semantic_model_definition(
        "aiops_gold_semantic_model",
        ["gold_service_health"],
    )
    model_payload_text = json.dumps(_decode_part(definition, "model.bim"), sort_keys=True)

    assert "resourceId" not in model_payload_text
    assert "subscriptionId" not in model_payload_text
    assert "tenantId" not in model_payload_text


def test_build_definition_emits_required_base64_parts() -> None:
    definition = build_semantic_model_definition(
        "aiops_gold_semantic_model",
        ["gold_cost_trends"],
    )
    parts = _parts(definition)

    assert set(parts) == {"model.bim", "definition.pbism", ".platform"}
    for part in parts.values():
        assert part["payloadType"] == "InlineBase64"
        decoded = json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
        assert isinstance(decoded, dict)


def test_build_definition_is_deterministic_for_same_table_set() -> None:
    a = build_semantic_model_definition(
        "aiops_gold_semantic_model",
        ["gold_patch_risk", "gold_incident_summary"],
    )
    b = build_semantic_model_definition(
        "aiops_gold_semantic_model",
        ["gold_incident_summary", "gold_patch_risk"],
    )

    assert a == b


class _Token:
    token = "token"
    expires_on = 4_102_444_800


class _Credential:
    def get_token(self, *scopes: str) -> _Token:
        assert scopes == ("https://api.fabric.microsoft.com/.default",)
        return _Token()


class _FakeManager:
    def __init__(self, *, items: list[dict] | None = None, definition: dict | None = None) -> None:
        self._items = list(items or [])
        self._definition = definition or {}
        self._post_error: Exception | None = None
        self.calls: list[tuple[str, str]] = []

    def set_post_error(self, error: Exception) -> None:
        self._post_error = error

    def iter_items(self, path: str, *, params: dict | None = None):
        self.calls.append(("ITER", path))
        assert params == {"type": "SemanticModel"}
        for item in self._items:
            yield item

    def request(self, method: str, path: str, **kwargs):
        self.calls.append((method, path))
        if method == "POST" and path.endswith("/getDefinition"):
            return {"definition": self._definition}
        if method == "POST" and path.endswith("/updateDefinition"):
            if self._post_error:
                raise self._post_error
            return {"id": "updated"}
        if method == "POST" and path.endswith("/semanticModels"):
            if self._post_error:
                raise self._post_error
            return {"id": "semantic-created"}
        raise AssertionError(f"Unexpected request: {method} {path}")


def _status_error(status: int, code: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.fabric.microsoft.com/v1/workspaces/ws/semanticModels")
    response = httpx.Response(status, request=request, json={"errorCode": code})
    return httpx.HTTPStatusError("fabric error", request=request, response=response)


def test_deploy_create_when_no_existing_semantic_model() -> None:
    manager = _FakeManager(items=[])
    result = deploy_semantic_model(
        manager, "workspace-1", "aiops_gold_semantic_model", ["gold_incident_summary"]
    )

    assert result == {"status": "created", "item_id": "semantic-created"}


def test_deploy_unchanged_returns_noop_for_equal_definition() -> None:
    display_name = "aiops_gold_semantic_model"
    gold_tables = ["gold_incident_summary"]
    existing_definition = build_semantic_model_definition(display_name, gold_tables)
    manager = _FakeManager(
        items=[{"id": "semantic-1", "displayName": display_name}],
        definition=existing_definition,
    )

    result = deploy_semantic_model(manager, "workspace-1", display_name, gold_tables)

    assert result == {"status": "unchanged", "item_id": "semantic-1"}


def test_deploy_changed_definition_updates_existing_item() -> None:
    display_name = "aiops_gold_semantic_model"
    manager = _FakeManager(
        items=[{"id": "semantic-1", "displayName": display_name}],
        definition=build_semantic_model_definition(display_name, ["gold_old_table"]),
    )

    result = deploy_semantic_model(
        manager, "workspace-1", display_name, ["gold_new_table"]
    )

    assert result == {"status": "updated", "item_id": "semantic-1"}


@pytest.mark.parametrize(
    "error_code",
    [
        "InvalidItemType",
        "ItemDisplayNameAlreadyInUse",
        "CorruptedPayload",
        "WorkspaceItemsLimitExceeded",
    ],
)
def test_deploy_maps_documented_create_errors_to_deployment_blocked(error_code: str) -> None:
    manager = _FakeManager(items=[])
    manager.set_post_error(_status_error(400, error_code))

    result = deploy_semantic_model(
        manager, "workspace-1", "aiops_gold_semantic_model", ["gold_incident_summary"]
    )

    assert result["status"] == "deployment-blocked"
    assert result["reason"] == error_code
    assert result["manifest_disposition"] == "dormant"


def test_deploy_maps_operation_failed_code_to_deployment_blocked() -> None:
    display_name = "aiops_gold_semantic_model"
    manager = _FakeManager(
        items=[{"id": "semantic-1", "displayName": display_name}],
        definition={},
    )
    manager.set_post_error(RuntimeError("Fabric operation failed: {'errorCode': 'CorruptedPayload'}"))

    result = deploy_semantic_model(manager, "workspace-1", display_name, ["gold_incident_summary"])

    assert result["status"] == "deployment-blocked"
    assert result["reason"] == "CorruptedPayload"


def test_deploy_retries_transient_failures_via_fabric_client_backoff() -> None:
    post_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/items"):
            return httpx.Response(200, request=request, json={"value": []})
        if request.url.path.endswith("/semanticModels"):
            post_calls.append(str(request.url))
            if len(post_calls) == 1:
                return httpx.Response(503, request=request, headers={"Retry-After": "0"})
            return httpx.Response(201, request=request, json={"id": "semantic-retried"})
        raise AssertionError(f"Unexpected path: {request.url.path}")

    client = FabricClient(
        _Credential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )

    result = deploy_semantic_model(
        client, "workspace-1", "aiops_gold_semantic_model", ["gold_incident_summary"]
    )

    assert result == {"status": "created", "item_id": "semantic-retried"}
    assert len(post_calls) == 2
