from __future__ import annotations

from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, _context
from test_api_copilot_unified import _canonical_body

from api.app import create_app
from semantic.semantic_engine import SemanticEngine
from semantic.semantic_indexes import SemanticIndexes


def test_cross_scope_domain_entity_is_rejected_before_retention(
    tmp_path,
    monkeypatch,
):
    engine = SemanticEngine(
        SemanticIndexes(
            [
                {
                    "resource_id": "owner:sub-b-secret",
                    "entity_type": "Owner",
                    "name": "sub-b-secret",
                    "subscription_id": "sub-b",
                    "lifecycle_status": "active",
                }
            ],
            [],
        ),
        knowledge_version="domain-scope-test",
        freshness="2026-09-13T00:00:00Z",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "api.routers.copilot.call_tool",
        lambda name, *_args, **_kwargs: calls.append(name),
    )
    body = _canonical_body()
    body.pop("hint")
    body["question"] = "Who owns this resource?"
    body["snapshot"] = {
        **body["snapshot"],
        "page_kind": "governance",
        "page_id": "governance",
        "coverage": {
            "visible_count": 1,
            "total_count": 1,
            "complete": True,
        },
        "selected_entities": [
            {
                "type": "domain",
                "namespace": "browser",
                "kind": "owner",
                "source_key": "sub-b-secret",
            }
        ],
        "evidence": [
            {
                "evidence_id": "owner:secret",
                "source": "governance/page",
                "source_key": "sub-b-secret",
                "entity": {
                    "type": "domain",
                    "namespace": "browser",
                    "kind": "owner",
                    "source_key": "sub-b-secret",
                },
                "status": "ok",
                "selected": True,
                "direct": True,
                "quality": "high",
                "data": {"owner": "sub-b-secret"},
            }
        ],
        "material_claims": [
            {
                "claim_id": "owner",
                "evidence_refs": ["owner:secret"],
            }
        ],
    }

    response = TestClient(
        create_app(_context(tmp_path, None, engine=engine)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 400
    assert calls == []
    assert "retained:" not in response.text
    assert "sub-b-secret" not in response.text
