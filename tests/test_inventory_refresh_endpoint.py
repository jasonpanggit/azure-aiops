"""Contract tests for the POST /api/v1/inventory/refresh trigger endpoint.

This endpoint exists so a native Fabric Data Pipeline (Web activity + schedule
trigger) can invoke the same `InventoryPipeline` refresh used by the
`inventory-refresh` CLI, without duplicating acquisition/normalization logic
inside Fabric. See `src/hermes_arg_connector/inventory_refresh.py`.

Authenticated by a dedicated shared secret (`HERMES_REFRESH_TRIGGER_SECRET`)
rather than the Entra principal flow, because the caller is a Fabric Web
activity on a schedule, not an interactive/gateway-authenticated user.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.telemetry import ApiTelemetry
from intelligence.inventory import InventoryService
from onboarding.service import SubscriptionOnboardingService

FIXTURE = Path(__file__).parent / "fixtures" / "mock_inventory_arg.json"
SECRET = "trigger-secret-0123456789"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("HERMES_REFRESH_TRIGGER_SECRET", SECRET)
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "hermes"),
        authenticator=StaticTokenAuthenticator(
            {"unused-token-0123456789": Principal(subject="unused", grants=(Grant("reader"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        inventory_provider=lambda: InventoryService(payload),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth(secret: str = SECRET) -> dict[str, str]:
    return {"x-hermes-trigger-secret": secret}


def test_refresh_requires_trigger_secret(client: TestClient) -> None:
    response = client.post("/api/v1/inventory/refresh")
    assert response.status_code == 401


def test_refresh_rejects_wrong_trigger_secret(client: TestClient) -> None:
    response = client.post("/api/v1/inventory/refresh", headers=_auth("wrong-secret"))
    assert response.status_code == 401


def test_refresh_returns_provider_unavailable_when_secret_unconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HERMES_REFRESH_TRIGGER_SECRET", raising=False)
    response = client.post("/api/v1/inventory/refresh", headers=_auth())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_refresh_returns_provider_unavailable_when_arg_config_unconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HERMES_ARG_CONFIG", raising=False)
    response = client.post("/api/v1/inventory/refresh", headers=_auth())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_refresh_runs_shared_pipeline_and_returns_manifest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("output_dir: " + str(tmp_path / "out"), encoding="utf-8")
    monkeypatch.setenv("HERMES_ARG_CONFIG", str(config_path))
    monkeypatch.delenv("HERMES_FABRIC_CONFIG", raising=False)

    with patch(
        "hermes_arg_connector.inventory_refresh.run_inventory_refresh",
        return_value={"status": "ok", "rows": 5},
    ) as mock_run:
        response = client.post("/api/v1/inventory/refresh", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["manifest"] == {"status": "ok", "rows": 5}
    mock_run.assert_called_once_with(str(config_path), fabric_config_path="")


def test_refresh_wraps_pipeline_failure_as_internal_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("output_dir: " + str(tmp_path / "out"), encoding="utf-8")
    monkeypatch.setenv("HERMES_ARG_CONFIG", str(config_path))

    with patch(
        "hermes_arg_connector.inventory_refresh.run_inventory_refresh",
        side_effect=RuntimeError("boom"),
    ):
        response = client.post("/api/v1/inventory/refresh", headers=_auth())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
