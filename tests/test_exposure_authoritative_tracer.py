from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from exposure_scenario import load_exposure_scenario
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from fabric_pipelines.vulnerability_pipeline import publish_exposure_page
from intelligence.vulnerability.read_port import ExposureReadPort
from onboarding.service import SubscriptionOnboardingService
from storage.datasets import DatasetStore

TOKEN = "exposure-tracer-token-0123456789"
IMAGE_EXPOSURE_ID = "exposure:image:platform-api:cve-2026-2001"


def _finding_rows(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    identities = scenario["identity_cases"]
    connections = {
        item["subscription_id"]: item["connection_id"]
        for item in scenario["scope"]["connections"]
    }
    rows = [
        {
            **identity,
            "subscription_id": identity["target_id"].split("/")[2],
            "connection_ids": [
                connections[identity["target_id"].split("/")[2]]
            ],
            "read_model_generation_id": scenario["read_model_generation_id"],
            "completeness": "complete",
        }
        for identity in identities.values()
    ]
    image = scenario["container_cases"]["digests"][0]
    rows.append(
        {
            "exposure_id": IMAGE_EXPOSURE_ID,
            "target_id": image["digest"],
            "target_kind": "container_image",
            "weakness_id": image["cve_ids"][0],
            "source_families": ["defender"],
            "subscription_id": scenario["scope"]["authorized_subscriptions"][1],
            "connection_ids": ["connection-defender-west"],
            "read_model_generation_id": scenario["read_model_generation_id"],
            "completeness": "complete",
        }
    )
    return rows


def _publish_fixture(store: DatasetStore) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scenario = load_exposure_scenario()
    rows = _finding_rows(scenario)
    publish_exposure_page(
        store,
        rows,
        generation_id=scenario["read_model_generation_id"],
        source_status=scenario["source_partitions"][:2],
    )
    return scenario, rows


def test_persisted_page_is_generation_pinned_and_scoped_before_count(
    tmp_path: Path,
) -> None:
    store = DatasetStore(tmp_path / "exposure")
    scenario, rows = _publish_fixture(store)
    scope = Scope.from_mapping(
        {"subscription": scenario["scope"]["authorized_subscriptions"]}
    )

    result = ExposureReadPort(store).list_exposures(scope, limit=100)

    expected_ids = {
        scenario["identity_cases"]["aum_only"]["exposure_id"],
        scenario["identity_cases"]["defender_only"]["exposure_id"],
        scenario["identity_cases"]["merged"]["exposure_id"],
        IMAGE_EXPOSURE_ID,
    }
    unauthorized_id = scenario["identity_cases"]["unauthorized"]["exposure_id"]
    assert store.current_generation() is not None
    assert len(rows) == 5
    assert result["read_model_generation_id"] == scenario["read_model_generation_id"]
    assert result["returned_count"] == result["total_count"] == 4
    assert {row["exposure_id"] for row in result["findings"]} == expected_ids
    assert unauthorized_id not in {
        row["exposure_id"] for row in result["findings"]
    }
    merged = next(
        row
        for row in result["findings"]
        if row["exposure_id"] == scenario["identity_cases"]["merged"]["exposure_id"]
    )
    image = next(
        row for row in result["findings"] if row["exposure_id"] == IMAGE_EXPOSURE_ID
    )
    assert merged["source_families"] == ["aum", "defender"]
    assert image["target_id"].startswith("sha256:")
    assert image["target_kind"] == "container_image"
    assert result["completeness"] == {
        "state": "complete",
        "represented_connections": 2,
        "expected_connections": 2,
    }
    assert result["source_attribution"] == [
        {"source_family": "aum", "finding_count": 2},
        {"source_family": "defender", "finding_count": 3},
    ]


def test_exposure_read_port_rejects_non_server_scope(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "exposure")
    _publish_fixture(store)

    with pytest.raises(TypeError, match="server-derived effective scope"):
        ExposureReadPort(store).list_exposures(None)


def test_authenticated_collection_route_uses_authoritative_read_port(
    tmp_path: Path,
) -> None:
    store = DatasetStore(tmp_path / "exposure")
    scenario, _ = _publish_fixture(store)
    authorized = scenario["scope"]["authorized_subscriptions"]
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal(
                    subject="exposure-reader@example.com",
                    grants=(
                        Grant(
                            "reader",
                            Scope.from_mapping({"subscription": authorized}),
                        ),
                    ),
                )
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    context.exposure_read_port_provider = lambda: ExposureReadPort(store)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/vulnerabilities/exposures",
        params={"limit": 100},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["read_model_generation_id"] == scenario[
        "read_model_generation_id"
    ]
    assert body["data"]["returned_count"] == body["data"]["total_count"] == 4
    assert body["data"]["completeness"]["state"] == "complete"
    assert body["data"]["source_attribution"] == [
        {"source_family": "aum", "finding_count": 2},
        {"source_family": "defender", "finding_count": 3},
    ]
    assert body["pagination"]["total"] == 4
    assert body["scope"] == {"subscription": sorted(authorized)}
    assert scenario["identity_cases"]["unauthorized"]["exposure_id"] not in {
        row["exposure_id"] for row in body["data"]["findings"]
    }


def test_invalid_publication_never_replaces_active_generation(tmp_path: Path) -> None:
    store = DatasetStore(tmp_path / "exposure")
    scenario, rows = _publish_fixture(store)
    active_generation = store.current_generation()
    invalid = [dict(row) for row in rows]
    invalid[1]["exposure_id"] = invalid[0]["exposure_id"]

    with pytest.raises(ValueError, match="quality validation failed"):
        publish_exposure_page(
            store,
            invalid,
            generation_id="exposure-generation-invalid",
            source_status=scenario["source_partitions"][:2],
        )

    assert store.current_generation() == active_generation
    result = ExposureReadPort(store).list_exposures(
        Scope.from_mapping(
            {"subscription": scenario["scope"]["authorized_subscriptions"]}
        )
    )
    assert result["read_model_generation_id"] == scenario["read_model_generation_id"]
