from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.telemetry import ApiTelemetry
from hermes_arg_connector.inventory_normalize import normalize_configuration_data
from intelligence.inventory import InventoryService
from onboarding.service import SubscriptionOnboardingService

TOKEN = "inventory-token-0123456789"
FIXTURE = Path(__file__).parent / "fixtures" / "mock_inventory_arg.json"
SOFTWARE_FIXTURE = Path(__file__).parent / "fixtures" / "mock_configurationdata.json"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    os_service = InventoryService.from_fixture(FIXTURE)
    software_rows = json.loads(SOFTWARE_FIXTURE.read_text(encoding="utf-8"))
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["software_observations"] = [
        row.to_dict()
        for row in normalize_configuration_data(software_rows, os_service.snapshot.observations)
    ]
    payload["software_source_status"] = {"logs": {"state": "ready", "query_version": "inventory-software-v1"}}
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "hermes"),
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        inventory_provider=lambda: InventoryService(payload),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer " + TOKEN}


def test_os_collection_is_scoped_before_grouping(client: TestClient) -> None:
    response = client.get(
        "/api/v1/inventory/os",
        params={"subscription": "sub-a", "limit": 100},
        headers=_auth(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == {"subscription": ["sub-a"]}
    assert body["pagination"] == {"offset": 0, "limit": 100, "total": 3, "next_offset": None}
    windows = next(group for group in body["data"]["groups"] if group["key"] == "Windows Server|2019")
    assert windows["machine_count"] == 2
    assert body["data"]["source_status"]["arc"]["state"] == "partial"


def test_detail_rejects_invalid_key_and_does_not_accept_machine_list(client: TestClient) -> None:
    invalid = client.get("/api/v1/inventory/os/not-a-group", headers=_auth())
    assert invalid.status_code == 400

    valid = client.get(
        "/api/v1/inventory/os/Windows%20Server%7C2019",
        params={"subscription": "sub-a", "machines": "forged"},
        headers=_auth(),
    )
    assert valid.status_code == 200
    assert all("forged" not in row["resource_id"] for row in valid.json()["data"]["machines"])


def test_detail_scope_isolation_and_unknown_review_state(client: TestClient) -> None:
    response = client.get(
        "/api/v1/inventory/os/Windows%20Server%7C2099-preview",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )
    assert response.status_code == 200
    machine = response.json()["data"]["machines"][0]
    assert machine["review_required"] is True
    assert machine["environment"] == "dev"

    outside = client.get(
        "/api/v1/inventory/os/Windows%20Server%7C2019",
        params={"subscription": "sub-c"},
        headers=_auth(),
    )
    assert outside.status_code == 404


def test_software_routes_return_canonical_exact_details_and_unlinked_status(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/inventory/software",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )
    assert response.status_code == 200
    body = response.json()
    seven_zip = next(group for group in body["data"]["groups"] if group["key"] == "7-Zip|19.00")
    assert seven_zip["install_count"] == 1
    assert body["data"]["source_status"]["logs"]["state"] == "ready"

    detail = client.get(
        "/api/v1/inventory/software/7-Zip%7C19.00",
        params={"subscription": "sub-a"},
        headers=_auth(),
    )
    assert detail.status_code == 200
    machine = detail.json()["data"]["machines"][0]
    assert machine["environment"] == "prod"
    assert machine["resource_join_status"] == "linked"
    assert machine["raw_identity"]["name"] == "7-Zip v19.00"

    assert client.get(
        "/api/v1/inventory/software/7-Zip%7C18.00",
        params={"subscription": "sub-a"},
        headers=_auth(),
    ).status_code == 404
