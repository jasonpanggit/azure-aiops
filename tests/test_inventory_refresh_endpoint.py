"""Contract tests for the POST /api/v1/inventory/refresh trigger endpoint.

This endpoint exists so a native Fabric Data Pipeline (Web activity + schedule
trigger) can invoke the same `InventoryPipeline` refresh used by the
`inventory-refresh` CLI, without duplicating acquisition/normalization logic
inside Fabric. See `src/onboarding/inventory_refresh.py`.

Authenticated by a dedicated shared secret (`AIOPS_REFRESH_TRIGGER_SECRET`)
rather than the Entra principal flow, because the caller is a Fabric Web
activity on a schedule, not an interactive/gateway-authenticated user.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api import inventory_refresh_runs
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
    monkeypatch.setenv("AIOPS_REFRESH_TRIGGER_SECRET", SECRET)
    inventory_refresh_runs.reset_for_tests()
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {"unused-token-0123456789": Principal(subject="unused", grants=(Grant("reader"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        inventory_provider=lambda: InventoryService(payload),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth(secret: str = SECRET) -> dict[str, str]:
    return {"x-aiops-trigger-secret": secret}


def _await_terminal(client: TestClient, run_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/inventory/refresh/{run_id}", headers=_auth()).json()
        if body.get("status") in {"succeeded", "failed"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s")


def test_refresh_requires_trigger_secret(client: TestClient) -> None:
    response = client.post("/api/v1/inventory/refresh")
    assert response.status_code == 401


def test_refresh_rejects_wrong_trigger_secret(client: TestClient) -> None:
    response = client.post("/api/v1/inventory/refresh", headers=_auth("wrong-secret"))
    assert response.status_code == 401


def test_refresh_returns_provider_unavailable_when_secret_unconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIOPS_REFRESH_TRIGGER_SECRET", raising=False)
    response = client.post("/api/v1/inventory/refresh", headers=_auth())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_refresh_returns_provider_unavailable_when_arg_config_unconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AIOPS_ARG_CONFIG", raising=False)
    response = client.post("/api/v1/inventory/refresh", headers=_auth())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_refresh_runs_shared_pipeline_in_background(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("output_dir: " + str(tmp_path / "out"), encoding="utf-8")
    monkeypatch.setenv("AIOPS_ARG_CONFIG", str(config_path))
    monkeypatch.delenv("AIOPS_FABRIC_CONFIG", raising=False)

    with patch(
        "api.inventory_orchestration.run_inventory_refresh_all_connections",
        return_value={"status": "completed", "connections": {}, "combined_manifest": {"rows": 5}},
    ) as mock_run:
        response = client.post("/api/v1/inventory/refresh", headers=_auth())
        run_id = response.json()["run_id"]
        status = _await_terminal(client, run_id)

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert response.json()["adopted_existing_run"] is False
    assert response.headers["location"].endswith(f"/api/v1/inventory/refresh/{run_id}")
    assert response.headers["retry-after"] == "30"
    assert status["status"] == "succeeded"
    assert status["result"]["combined_manifest"] == {"rows": 5}
    mock_run.assert_called_once_with(str(config_path), fabric_config_path="")


def test_refresh_reports_pipeline_failure_on_the_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("output_dir: " + str(tmp_path / "out"), encoding="utf-8")
    monkeypatch.setenv("AIOPS_ARG_CONFIG", str(config_path))

    with patch(
        "api.inventory_orchestration.run_inventory_refresh_all_connections",
        side_effect=RuntimeError("boom"),
    ):
        response = client.post("/api/v1/inventory/refresh", headers=_auth())
        status = _await_terminal(client, response.json()["run_id"])

    assert response.status_code == 202
    assert status["status"] == "failed"
    assert "boom" in status["error"]


def test_refresh_is_single_flight(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The hourly schedule must never stack a second acquisition on a live run."""

    config_path = tmp_path / "config.yaml"
    config_path.write_text("output_dir: " + str(tmp_path / "out"), encoding="utf-8")
    monkeypatch.setenv("AIOPS_ARG_CONFIG", str(config_path))
    release = threading.Event()

    def _blocking(*_args: object, **_kwargs: object) -> dict[str, object]:
        release.wait(timeout=10)
        return {"status": "completed"}

    with patch(
        "api.inventory_orchestration.run_inventory_refresh_all_connections",
        side_effect=_blocking,
    ) as mock_run:
        first = client.post("/api/v1/inventory/refresh", headers=_auth())
        second = client.post("/api/v1/inventory/refresh", headers=_auth())
        release.set()
        _await_terminal(client, first.json()["run_id"])

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.headers["location"] == first.headers["location"]
    assert second.json()["adopted_existing_run"] is True
    assert second.json()["run_id"] == first.json()["run_id"]
    assert mock_run.call_count == 1


def test_refresh_status_requires_trigger_secret_for_unknown_run(client: TestClient) -> None:
    response = client.get("/api/v1/inventory/refresh/refresh-unknown")
    assert response.status_code == 401


def test_refresh_status_latest_alias_requires_trigger_secret(client: TestClient) -> None:
    response = client.get("/api/v1/inventory/refresh/latest")
    assert response.status_code == 401


def test_refresh_status_follows_async_request_reply_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A polling Web activity must see 202 while running, then the real outcome."""

    config_path = tmp_path / "config.yaml"
    config_path.write_text("output_dir: " + str(tmp_path / "out"), encoding="utf-8")
    monkeypatch.setenv("AIOPS_ARG_CONFIG", str(config_path))
    release = threading.Event()

    def _blocking(*_args: object, **_kwargs: object) -> dict[str, object]:
        release.wait(timeout=10)
        raise RuntimeError("publication failed")

    with patch(
        "api.inventory_orchestration.run_inventory_refresh_all_connections",
        side_effect=_blocking,
    ):
        trigger = client.post("/api/v1/inventory/refresh", headers=_auth())
        run_id = trigger.json()["run_id"]
        # Polling without the trigger header, as a Web activity may.
        running = client.get(f"/api/v1/inventory/refresh/{run_id}")
        release.set()
        _await_terminal(client, run_id)
        finished = client.get(f"/api/v1/inventory/refresh/{run_id}")

    assert running.status_code == 202
    assert running.headers["location"] == trigger.headers["location"]
    assert running.json()["status"] == "running"
    assert finished.status_code == 500
    assert finished.json()["status"] == "failed"
    assert "error" not in finished.json()


def test_refresh_status_returns_not_found_for_unknown_run(client: TestClient) -> None:
    response = client.get("/api/v1/inventory/refresh/refresh-unknown", headers=_auth())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_refresh_status_latest_alias(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("output_dir: " + str(tmp_path / "out"), encoding="utf-8")
    monkeypatch.setenv("AIOPS_ARG_CONFIG", str(config_path))

    with patch(
        "api.inventory_orchestration.run_inventory_refresh_all_connections",
        return_value={"status": "completed"},
    ):
        response = client.post("/api/v1/inventory/refresh", headers=_auth())
        _await_terminal(client, response.json()["run_id"])

    latest = client.get("/api/v1/inventory/refresh/latest", headers=_auth())
    assert latest.status_code == 200
    assert latest.json()["result"] == {"status": "completed"}
    assert latest.json()["run_id"] == response.json()["run_id"]
