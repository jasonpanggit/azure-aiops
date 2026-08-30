from __future__ import annotations

from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, StubAgent, _context

from api.app import create_app
from operations.autonomous_investigation import ledger_store


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
                "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/routeTables/route-1",
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
        "resource_id": "/subscriptions/other-sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet",
        "resource_type": "Microsoft.Network/virtualNetworks",
        "attributes": {"subscription": "other-sub"},
    }]
    response = client.post(
        "/api/v1/copilot/investigate-context?subscription=sub-1",
        json=out_of_scope,
        headers=HEADERS,
    )
    assert response.status_code == 400


def test_context_loop_preserves_status_and_exposes_policy_grounding(tmp_path):
    body = _body()
    body["snapshot"]["evidence"] = [
        {
            "evidence_id": "seg-1",
            "section": "network",
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet",
            "status": "denied",
            "data": {"category": "segmentation", "issue": "Unverified segment boundary"},
        }
    ]
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)
    response = client.post("/api/v1/copilot/investigate-context", json=body, headers=HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    finding = data["findings"][0]
    assert finding["policy_id"] == "NET-SEG-001"
    assert finding["source_status"] == "denied"
    assert finding["actionable"] is False
    assert data["stages"] == ["plan", "observe", "delegate", "reassess"]


def test_context_route_preserves_freshness_warning_and_downgrades_finding(tmp_path):
    body = _body()
    body["snapshot"]["freshness"] = [{
        "source": "network-api",
        "observed_at": "2026-08-28T00:00:00Z",
        "status": "partial",
    }]
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)
    response = client.post("/api/v1/copilot/investigate-context", json=body, headers=HEADERS)
    assert response.status_code == 200
    data = response.json()["data"]
    finding = data["findings"][0]
    assert finding["status"] == "hypothesis"
    assert finding["actionable"] is False
    assert any("partial" in warning for warning in data["warnings"])


def test_context_route_rejects_out_of_scope_evidence_identity(tmp_path):
    body = _body()
    body["snapshot"]["evidence"][0]["resource_id"] = (
        "/subscriptions/other-sub/resourceGroups/rg/providers/"
        "Microsoft.Network/routeTables/route-1"
    )
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)
    response = client.post(
        "/api/v1/copilot/investigate-context?subscription=sub-1",
        json=body,
        headers=HEADERS,
    )
    assert response.status_code == 400


def test_context_route_sends_non_network_page_evidence_to_foundry(tmp_path):
    body = {
        "snapshot": {
            "version": "1",
            "page_kind": "vulnerability",
            "page_id": "exposure",
            "question": "Explain this exposure",
            "scope": {"declared": {}},
            "selected_resources": [],
            "evidence": [
                {
                    "evidence_id": "cve-1",
                    "section": "vulnerability",
                    "data": {
                        "cve_id": "CVE-2026-0001",
                        "severity": "critical",
                        "finding": "Publicly reachable vulnerable workload",
                        "resource_id": "CVE-2026-0001",
                    },
                }
            ],
        }
    }
    agent = StubAgent()
    client = TestClient(create_app(_context(tmp_path, agent)), raise_server_exceptions=False)
    response = client.post("/api/v1/copilot/investigate-context", json=body, headers=HEADERS)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["synthesis"]["mode"] == "foundry"
    finding = data["findings"][0]
    assert finding["summary"] == "Publicly reachable vulnerable workload"
    assert finding["evidence_refs"] == ["cve-1"]
    assert finding["resource_ids"] == []
    assert agent.calls[0]["context"]["findings"][0]["details"]["cve_id"] == "CVE-2026-0001"
