from datetime import UTC, datetime
from urllib.parse import quote

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from hermes_arg_connector.normalize import Normalizer

TOKEN = "situation-tracer-token-012345"


class EmptyOnboarding:
    pass


def test_normalization_to_scoped_api_read(tmp_path) -> None:
    observed = datetime(2026, 8, 25, tzinfo=UTC)
    graph = Normalizer().normalize(
        {
            "resources": [
                {
                    "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                    "name": "vm1",
                    "type": "Microsoft.Compute/virtualMachines",
                    "subscriptionId": "sub-a",
                    "tags": {"owner": "sre"},
                }
            ],
            "resource_changes": [
                {
                    "id": "change-1",
                    "properties": {
                        "targetResourceId": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
                        "changeType": "Microsoft.Compute/virtualMachines/write",
                        "changeAttributes": {"timestamp": observed.isoformat()},
                    },
                }
            ],
        },
        observed,
    )
    situation = graph.situations[0]
    from situations.store import SituationStore

    source = SituationStore(tmp_path)
    source.publish(graph, {}, {"runId": "tracer-run", "startedAt": observed.isoformat()})
    provider = source.provider()
    principal = Principal(
        subject="reader@example.com",
        grants=(Grant("reader", Scope.from_mapping({"subscription": ["sub-a"]})),),
    )
    context = ApiContext(
        onboarding=EmptyOnboarding(),  # type: ignore[arg-type]
        authenticator=StaticTokenAuthenticator({TOKEN: principal}),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        situation_provider=lambda: provider,
    )

    response = TestClient(create_app(context)).get(
        f"/api/v1/situations/{quote(situation['situation_id'], safe='')}",
        headers={"authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["evidence"][0]["source_family"] == "arg_activity_log"

    forbidden = TestClient(create_app(context)).get(
        f"/api/v1/situations/{quote(situation['situation_id'], safe='')}",
        params={"subscription": "sub-b"},
        headers={"authorization": f"Bearer {TOKEN}"},
    )
    assert forbidden.status_code in {403, 404}
