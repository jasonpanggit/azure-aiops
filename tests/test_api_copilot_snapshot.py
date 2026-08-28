from __future__ import annotations

from fastapi.testclient import TestClient
from test_api_copilot_investigation import _context, HEADERS
from operations.autonomous_investigation import ledger_store
from api.app import create_app


def _body():
    return {
        "snapshot": {
            "version": "1",
            "page_kind": "network",
            "page_id": "topology",
            "question": "Review this network page",
            "scope": {"declared": {}},
            "evidence": [{
                "evidence_id": "route-1",
                "section": "route",
                "resource_id": "route-1",
                "data": {"finding": "Default route bypasses firewall", "compliant": False},
            }],
        }
    }


def test_context_route_returns_cited_deterministic_ledger(tmp_path):
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)
    response = client.post("/api/v1/copilot/investigate-context", json=_body(), headers=HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["snapshot_version"] == "1"
    assert data["snapshot_hash"]
    assert data["synthesis"]["mode"] == "deterministic"
    assert data["findings"][0]["evidence_refs"] == ["route-1"]
    assert ledger_store().get(data["ledger_id"], "admin@example.com") is not None


def test_context_route_rejects_unknown_version_and_wider_scope(tmp_path):
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)
    invalid = _body()
    invalid["snapshot"]["version"] = "2"
    assert client.post("/api/v1/copilot/investigate-context", json=invalid, headers=HEADERS).status_code == 400

    out_of_scope = _body()
    out_of_scope["snapshot"]["scope"] = {"declared": {"subscription": ["other-sub"]}}
    out_of_scope["snapshot"]["selected_resources"] = [{
        "resource_id": "resource-1",
        "resource_type": "Microsoft.Network/virtualNetworks",
        "attributes": {"subscription": "other-sub"},
    }]
    response = client.post(
        "/api/v1/copilot/investigate-context?subscription=sub-1",
        json=out_of_scope,
        headers=HEADERS,
    )
    assert response.status_code == 400
