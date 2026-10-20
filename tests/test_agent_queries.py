from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest

from api.scope import Scope
from onboarding.agent_queries import ContextQueryService, _failed
from onboarding.inventory_read_adapter import InventoryReadAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"


def test_agent_queries_answer_required_questions(tmp_path: Path) -> None:
    from datetime import datetime

    from onboarding.graph_normalize import Normalizer
    from onboarding.ingestion_storage import DatasetStore

    payload = json.loads(FIXTURE.read_text())
    graph = Normalizer().normalize(payload, datetime(2026, 8, 17, tzinfo=UTC))
    DatasetStore(tmp_path).publish(graph, payload, {"runId": "sample"})
    service = ContextQueryService(tmp_path)

    all_vms = service.answer("show me all vms")["items"]
    assert [item["name"] for item in all_vms] == ["vm-prod-01"]
    assert "properties" not in all_vms[0]
    assert {item["name"] for item in service.answer("show me non-compliant servers")["items"]} == {
        "vm-prod-01",
        "arc-legacy-01",
    }
    eol = service.answer("show servers approaching os eol")
    assert eol["items"][0]["name"] == "arc-legacy-01"
    failures = service.answer("show patch failures")
    assert failures["items"][0]["status"].lower() == "failed"


def test_success_error_envelope_is_not_a_patch_failure() -> None:
    assessment = {
        "status": "Succeeded",
        "errorDetails": {"code": "Success", "message": "0 error/s reported", "details": []},
    }
    assert not _failed(assessment)


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ({"subscription": ["sub-a"]}, ["vm-a"]),
        ({"environment": ["prod"]}, ["vm-a"]),
        ({"owner": ["team-a"]}, ["vm-a"]),
        ({"subscription_connection": ["connection-a"]}, ["vm-a"]),
        ({"subscription": ["sub-missing"]}, []),
        ({"business_service": ["unknown"]}, []),
    ],
)
def test_legacy_identity_adapter_enforces_effective_scope(
    tmp_path: Path, scope: dict[str, list[str]], expected: list[str]
) -> None:
    entity_dir = tmp_path / "current/entities"
    entity_dir.mkdir(parents=True)
    rows = [
        {
            "id": f"/subscriptions/sub-{suffix}/vm-{suffix}",
            "name": f"vm-{suffix}",
            "subscriptionId": f"sub-{suffix}",
            "environment": environment,
            "owner": f"team-{suffix}",
            "connectionId": f"connection-{suffix}",
        }
        for suffix, environment in (("a", "prod"), ("b", "dev"))
    ]
    (entity_dir / "VirtualMachine.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )

    result = ContextQueryService(
        tmp_path, scope=Scope.from_mapping(scope)
    ).answer("show me all vms")

    assert [row["name"] for row in result["items"]] == expected


def test_patch_failures_join_only_authorized_identity() -> None:
    class ScopedPort:
        def list_resources(self, scope, *, limit):
            assert scope == Scope.from_mapping({"subscription": ["sub-a"]})
            assert limit is None
            return {
                "total": 1,
                "resources": [
                    {
                        "family": "os",
                        "resource_id": "/subscriptions/sub-a/vm-a",
                        "resource_name": "vm-a",
                    }
                ]
            }

    rows = [
        {"id": "allowed", "targetResourceId": "/SUBSCRIPTIONS/SUB-A/VM-A", "status": "Failed"},
        {"id": "denied", "targetResourceId": "/subscriptions/sub-b/vm-b", "status": "Failed"},
        {"id": "unknown", "targetResourceId": "/subscriptions/sub-a/missing", "status": "Failed"},
        {"id": "unbound", "status": "Failed"},
        {"id": "succeeded", "targetResourceId": "/subscriptions/sub-a/vm-a", "status": "Succeeded"},
    ]
    service = ContextQueryService(
        inventory_adapter=InventoryReadAdapter(ScopedPort()),
        scope=Scope.from_mapping({"subscription": ["sub-a"]}),
        patch_reader=lambda: rows,
    )

    result = service.answer("show patch failures")

    assert [row["id"] for row in result["items"]] == ["allowed"]


def test_legacy_identity_adapter_requires_effective_scope(tmp_path: Path) -> None:
    adapter = InventoryReadAdapter(None, str(tmp_path), legacy=True)

    with pytest.raises(TypeError, match="server-derived effective scope"):
        adapter.resources(None)


def test_unknown_zero_patch_assessment_is_not_non_compliant(tmp_path: Path) -> None:
    entity_dir = tmp_path / "current/entities"
    entity_dir.mkdir(parents=True)
    server = {"id": "/subscriptions/sub-1/vm-1", "name": "vm-1"}
    assessment = {
        "id": "assessment-1",
        "targetResourceId": server["id"],
        "status": "unknown",
        "availablePatchCountByClassification": {},
        "errorDetails": [],
    }
    (entity_dir / "VirtualMachine.jsonl").write_text(json.dumps(server) + "\n")
    (entity_dir / "PatchAssessment.jsonl").write_text(json.dumps(assessment) + "\n")

    result = ContextQueryService(tmp_path).answer("show me non-compliant servers")

    assert result["items"] == []


def test_agent_query_rejects_unknown_intent(tmp_path: Path) -> None:
    service = ContextQueryService(tmp_path)
    try:
        service.answer("delete every vm")
    except ValueError as exc:
        assert "Supported questions" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_agent_query_rejects_dataset_symlink_outside_data_root(tmp_path: Path) -> None:
    entity_dir = tmp_path / "current/entities"
    entity_dir.mkdir(parents=True)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.jsonl"
    outside.write_text(json.dumps({"id": "outside", "name": "outside"}) + "\n")
    (entity_dir / "VirtualMachine.jsonl").symlink_to(outside)

    try:
        ContextQueryService(tmp_path).answer("show me all vms")
    except ValueError as exc:
        assert "outside configured data root" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_agent_query_rejects_current_symlink_outside_data_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-current"
    entity_dir = outside / "entities"
    entity_dir.mkdir(parents=True)
    (entity_dir / "VirtualMachine.jsonl").write_text(
        json.dumps({"id": "outside", "name": "outside"}) + "\n"
    )
    (tmp_path / "current").symlink_to(outside, target_is_directory=True)

    try:
        ContextQueryService(tmp_path).answer("show me all vms")
    except ValueError as exc:
        assert "outside configured data root" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_agent_query_rejects_escaped_current_even_when_dataset_is_missing(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-empty-outside-current"
    outside.mkdir()
    (tmp_path / "current").symlink_to(outside, target_is_directory=True)

    try:
        ContextQueryService(tmp_path).answer("show me all vms")
    except ValueError as exc:
        assert "outside configured data root" in str(exc)
    else:
        raise AssertionError("expected ValueError")
