from datetime import UTC, datetime
from urllib.parse import quote

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.config import ConnectorConfig
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_service import IngestionService

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


def test_production_ingestion_publishes_arg_activity_and_source_status(tmp_path) -> None:
    import json
    from pathlib import Path

    fixture = json.loads(Path("tests/fixtures/phase1_signal_payloads.json").read_text())
    fixture = {"resource_changes": fixture["resource_changes"]}

    class FixtureSource:
        def list_subscriptions(self):
            return [{"subscriptionId": "sub-a"}]

        def fetch(self, specs, subscriptions):
            return {spec.name: list(fixture.get(spec.name, [])) for spec in specs}

    started = datetime(2026, 8, 25, 2, tzinfo=UTC)
    service = IngestionService(
        ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-a",)),
        source=FixtureSource(),
        clock=lambda: started,
    )

    service.run()
    evidence = service.store.read_dataset("situations/evidence")
    statuses = service.store.read_dataset("situations/source_status")

    assert [row["source_family"] for row in evidence] == ["arg_activity_log"]
    assert evidence[0]["source_object_id"] == "change-1"
    assert evidence[0]["observed_at"] == "2026-08-25T01:00:00Z"
    assert evidence[0]["ingested_at"] == "2026-08-25T02:00:00Z"
    assert evidence[0]["run_id"] == statuses[0]["run_id"]
    assert statuses[0]["source_family"] == "arg_activity_log"
    assert statuses[0]["status"] == "succeeded"
    assert statuses[0]["watermark"] == "2026-08-25T01:00:00Z"
    assert statuses[0]["requested_scope"] == {"subscription": ["sub-a"]}


def test_production_ingestion_retains_failed_arg_status_without_watermark(tmp_path) -> None:
    class FailedSource:
        def list_subscriptions(self):
            return [{"subscriptionId": "sub-a"}]

        def fetch(self, specs, subscriptions):
            return {
                spec.name: (
                    [{"status": "failed", "error": "provider offline", "watermark": "future"}]
                    if spec.name == "resource_changes"
                    else []
                )
                for spec in specs
            }

    service = IngestionService(
        ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-a",)),
        source=FailedSource(),
        clock=lambda: datetime(2026, 8, 25, 2, tzinfo=UTC),
    )
    service.run()
    status = service.store.read_dataset("situations/source_status")[0]

    assert status["status"] == "failed"
    assert status["watermark"] == ""
    assert status["availability"] == "unavailable"
    assert service.store.read_dataset("situations/evidence") == []


def test_normalizer_production_graph_contains_all_six_signal_families() -> None:
    import json
    from pathlib import Path

    payload = json.loads(Path("tests/fixtures/phase1_signal_payloads.json").read_text())
    graph = Normalizer().normalize(
        payload,
        datetime(2026, 8, 25, 2, tzinfo=UTC),
        run_id="six-family-run",
        requested_scope={"subscription": ["sub-a"]},
    )

    assert {row["source_family"] for row in graph.evidence} == {
        "arg_activity_log",
        "monitor",
        "service_health",
        "defender",
        "policy",
        "vulnerability",
    }
    # source_status additionally carries per-signal granular Defender family
    # rows (defender_assessments, defender_subassessments, defender_alerts,
    # defender_attack_paths, defender_secure_scores,
    # defender_secure_score_controls) alongside the six canonical families —
    # the normalizer emits status for every granular Defender signal, not
    # just the coarse "defender" bucket used for evidence records.
    source_status_families = {row["source_family"] for row in graph.source_status}
    non_defender_families = {
        "arg_activity_log",
        "monitor",
        "service_health",
        "policy",
        "vulnerability",
    }
    assert non_defender_families <= source_status_families
    defender_families = {
        family for family in source_status_families if family.startswith("defender")
    }
    assert defender_families == {
        "defender",
        "defender_assessments",
        "defender_subassessments",
        "defender_alerts",
        "defender_attack_paths",
        "defender_secure_scores",
        "defender_secure_score_controls",
    }
    assert all(row["run_id"] == "six-family-run" for row in graph.evidence)
