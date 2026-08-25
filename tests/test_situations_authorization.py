from datetime import UTC, datetime

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from hermes_arg_connector.normalize import Normalizer
from situations.store import SituationReadProvider


def test_out_of_scope_situation_does_not_disclose_existence() -> None:
    observed = datetime(2026, 8, 25, tzinfo=UTC)
    graph = Normalizer().normalize(
        {"resource_changes": [{"id": "change", "properties": {"targetResourceId": "/subscriptions/sub-b/r", "changeType": "write", "changeAttributes": {"timestamp": observed.isoformat()}}}]},
        observed,
    )
    provider = SituationReadProvider(None, situations=graph.situations, evidence=graph.evidence, links=graph.links, audits=graph.audit_events)
    token = "situation-auth-token-012345"
    context = ApiContext(
        onboarding=object(),  # type: ignore[arg-type]
        authenticator=StaticTokenAuthenticator({token: Principal(subject="reader", grants=(Grant("reader", Scope.from_mapping({"subscription": ["sub-a"]})),))}),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        situation_provider=lambda: provider,
    )
    response = TestClient(create_app(context)).get(
        f"/api/v1/situations/{graph.situations[0]['situation_id']}",
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert "sub-b" not in response.text


def test_nested_scope_filters_evidence_links_source_status_and_audit_references() -> None:
    situation_id = "situation://scoped"
    provider = SituationReadProvider(
        None,
        situations=[{
            "situation_id": situation_id,
            "scope": {"subscription": ["sub-a"]},
            "affected_resource_ids": ["/subscriptions/sub-a/vm"],
        }],
        evidence=[
            {"evidence_id": "evidence://a", "situation_id": situation_id, "resource_ids": ["/subscriptions/sub-a/vm"], "source_object_id": "source-a"},
            {"evidence_id": "evidence://b", "situation_id": situation_id, "resource_ids": ["/subscriptions/sub-b/vm"], "source_object_id": "source-b"},
        ],
        links=[
            {"link_id": "link://a", "situation_id": situation_id, "entity_id": "/subscriptions/sub-a/vm"},
            {"link_id": "link://b", "situation_id": situation_id, "entity_id": "/subscriptions/sub-b/vm"},
        ],
        source_status=[
            {"source_family": "defender", "requested_scope": {"subscription": ["sub-a"]}},
            {"source_family": "policy", "requested_scope": {"subscription": ["sub-b"]}},
        ],
        audits=[
            {"event_id": "audit://a", "situation_id": situation_id, "timestamp": "2026-01-01", "evidence_ids": ["evidence://a", "evidence://b"], "source_references": ["source-a", "source-b"]},
        ],
    )

    visible = provider.get(situation_id, Scope.from_mapping({"subscription": ["sub-a"]}))
    assert visible is not None
    assert [row["evidence_id"] for row in visible["evidence"]] == ["evidence://a"]
    assert [row["link_id"] for row in visible["links"]] == ["link://a"]
    assert [row["source_family"] for row in visible["source_status"]] == ["defender"]
    audit = provider.audit(situation_id, Scope.from_mapping({"subscription": ["sub-a"]}))
    assert audit == [{
        **provider._rows("audits")[0],
        "evidence_ids": ["evidence://a"],
        "source_references": ["source-a"],
    }]
    assert provider.evidence("evidence://b", Scope.from_mapping({"subscription": ["sub-a"]})) is None
