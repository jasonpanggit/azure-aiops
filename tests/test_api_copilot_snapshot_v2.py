from __future__ import annotations

from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, _context

from api.app import create_app
from operations.orchestration_contract import (
    OrchestrationResult,
    SnapshotCoverage,
)


def _body():
    return {
        "contract_version": "1",
        "question": "Show inventory resources and data health.",
        "requested_scope": {"subscription": ["sub-a"]},
        "snapshot": {
            "version": "2",
            "page_kind": "inventory",
            "page_id": "inventory:os",
            "coverage": {
                "visible_count": 1,
                "total_count": 1,
                "complete": True,
            },
            "evidence": [
                {
                    "evidence_id": "inventory:os:windows-2022",
                    "source": "inventory/os_observations",
                    "source_key": "windows-server|2022",
                    "entity": {
                        "type": "domain",
                        "namespace": "inventory",
                        "kind": "operating-system",
                        "source_key": "windows-server|2022",
                    },
                    "claim_type": "inventory-count",
                    "status": "ok",
                    "data": {
                        "os_name": "Windows Server",
                        "os_version": "2022",
                        "machine_count": 1,
                        "selected": False,
                        "inventory_context": {
                            "tab": "os",
                            "filters": {
                                "os_name": "all",
                                "os_version": "all",
                            },
                        },
                    },
                }
            ],
            "material_claims": [
                {
                    "claim_id": "visible-inventory",
                    "evidence_refs": ["inventory:os:windows-2022"],
                }
            ],
        },
    }


def test_snapshot_v2_api_rejects_orphaned_material_citations_before_io(tmp_path):
    calls = []

    class InventoryPort:
        def list_os_observations(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"items": [], "total": 0}

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)
    body = _body()
    body["snapshot"]["material_claims"][0]["evidence_refs"] = ["missing"]

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=body,
        headers=HEADERS,
    )

    assert response.status_code == 400
    assert calls == []
    assert response.json()["error"]["code"] == "invalid_request"


def test_snapshot_v2_api_rejects_unknown_fields_and_versions(tmp_path):
    client = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    )
    extra = _body()
    extra["snapshot"]["evidence"][0]["browser_authorized"] = True
    unknown_version = _body()
    unknown_version["snapshot"]["version"] = "3"

    assert (
        client.post(
            "/api/v1/copilot/investigations?subscription=sub-a",
            json=extra,
            headers=HEADERS,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/copilot/investigations?subscription=sub-a",
            json=unknown_version,
            headers=HEADERS,
        ).status_code
        == 400
    )


def test_snapshot_v2_api_never_retains_untrusted_browser_citations(tmp_path):
    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            assert scope.to_dict() == {"subscription": ["sub-a"]}
            assert family == "os"
            assert resource_type is None
            assert limit == 25
            return {"resources": [], "total": 0}

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=_body(),
        headers=HEADERS,
    )

    assert response.status_code == 200, response.text
    citations = response.json()["data"]["citations"]
    assert "inventory:os:windows-2022" not in {
        citation["citation_id"] for citation in citations
    }
    assert citations == []


def test_production_boundary_invokes_canonical_snapshot_normalization(
    tmp_path,
    monkeypatch,
):
    normalized = []

    def canonicalize(snapshot, **kwargs):
        normalized.append((snapshot, kwargs))
        return object()

    monkeypatch.setattr(
        "api.routers.copilot.canonicalize_snapshot_v2",
        canonicalize,
    )

    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            return {"resources": [], "total": 0}

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=_body(),
        headers=HEADERS,
    )

    assert response.status_code == 200, response.text
    assert len(normalized) == 1
    assert normalized[0][0].page_kind == "inventory"


def test_canonical_endpoint_accepts_remediation_snapshot_v2(
    tmp_path,
    monkeypatch,
):
    captured = []
    result = OrchestrationResult(
        status="empty",
        policy_status="fallback",
        fallback_reason="planner_unavailable",
        coverage=SnapshotCoverage(
            visible_count=0,
            total_count=0,
            complete=False,
        ),
        thread_id="thr-" + ("a" * 32),
        thread_revision=1,
    )

    def execute(_self, request, **_kwargs):
        captured.append(request)
        return result

    monkeypatch.setattr(
        "api.routers.copilot.OrchestrationService.execute",
        execute,
    )
    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json={
            "contract_version": "1",
            "question": "Explain the current governed remediation state.",
            "requested_scope": {"subscription": ["sub-a"]},
            "snapshot": {
                "version": "2",
                "page_kind": "remediation",
                "page_id": "remediation",
                "coverage": {
                    "visible_count": 0,
                    "total_count": 0,
                    "complete": True,
                },
                "freshness": [],
                "selected_entities": [],
                "evidence": [],
                "material_claims": [],
            },
        },
        headers=HEADERS,
    )

    assert response.status_code == 200, response.text
    assert captured[0].snapshot.page_kind == "remediation"
    assert captured[0].snapshot.coverage.complete is False
