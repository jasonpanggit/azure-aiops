from datetime import UTC, datetime
from urllib.parse import quote

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.telemetry import ApiTelemetry
from hermes_arg_connector.normalize import Normalizer
from situations.store import SituationReadProvider


def test_collection_audit_and_evidence_reads_use_the_envelope() -> None:
    observed = datetime(2026, 8, 25, tzinfo=UTC)
    graph = Normalizer().normalize(
        {"resource_changes": [{"id": "change", "properties": {"targetResourceId": "/subscriptions/sub-a/r", "changeType": "write", "changeAttributes": {"timestamp": observed.isoformat()}}}]},
        observed,
    )
    provider = SituationReadProvider(
        None, situations=graph.situations, evidence=graph.evidence, links=graph.links, audits=graph.audit_events
    )
    token = "situation-api-token-012345"
    context = ApiContext(
        onboarding=object(),  # type: ignore[arg-type]
        authenticator=StaticTokenAuthenticator({token: Principal(subject="reader", grants=(Grant("reader"),))}),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        situation_provider=lambda: provider,
    )
    client = TestClient(create_app(context))
    situation_id = graph.situations[0]["situation_id"]
    response = client.get("/api/v1/situations", headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["data"][0]["situation_id"] == situation_id
    detail = client.get(f"/api/v1/situations/{quote(situation_id, safe='')}", headers={"authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    evidence_id = graph.evidence[0]["evidence_id"]
    assert client.get(f"/api/v1/evidence/{quote(evidence_id, safe='')}", headers={"authorization": f"Bearer {token}"}).status_code == 200
    audit = client.get(f"/api/v1/situations/{quote(situation_id, safe='')}/audit", headers={"authorization": f"Bearer {token}"})
    assert audit.status_code == 200
    assert {row["action"] for row in audit.json()["data"]} == {
        "observation.recorded",
        "situation.created",
    }
