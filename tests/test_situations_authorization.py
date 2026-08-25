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
