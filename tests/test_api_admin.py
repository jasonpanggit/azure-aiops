"""Tests for administrator-only Key Vault configuration writes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.telemetry import ApiTelemetry
from onboarding.credentials import KeyVaultSecretWriter
from onboarding.service import SubscriptionOnboardingService

ADMIN_TOKEN = "admin-token-0123456789abcdef"
READER_TOKEN = "reader-token-0123456789abcdef"
PAYLOAD = {
    "entra_web_client_id": "11111111-1111-1111-1111-111111111111",
    "entra_tenant_id": "22222222-2222-2222-2222-222222222222",
    "entra_api_audience": "api://operations",
    "entra_api_scope": "api://operations/access_as_user",
    "entra_grants_json": '{"admin@example.com":[{"role":"admin"}]}',
}


class FakeSecretClient:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def set_secret(self, name: str, value: str):
        self.writes.append((name, value))


def _client(tmp_path):
    secret_client = FakeSecretClient()
    onboarding = SubscriptionOnboardingService(tmp_path / "aiops")
    onboarding.secret_writer = KeyVaultSecretWriter(
        "ops-kv", client_factory=lambda _vault: secret_client
    )
    principals = {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
    }
    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False), secret_client


def test_admin_can_save_configuration_without_returning_values(tmp_path):
    client, secret_client = _client(tmp_path)
    response = client.post(
        "/api/v1/admin/akv-config",
        json=PAYLOAD,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["saved"] == [
        "entra_web_client_id",
        "entra_tenant_id",
        "entra_api_audience",
        "entra_api_scope",
        "entra_grants_json",
    ]
    assert PAYLOAD["entra_grants_json"] not in response.text
    assert len(secret_client.writes) == 5


def test_non_admin_cannot_save_configuration(tmp_path):
    client, secret_client = _client(tmp_path)
    response = client.post(
        "/api/v1/admin/akv-config",
        json=PAYLOAD,
        headers={"Authorization": f"Bearer {READER_TOKEN}"},
    )

    assert response.status_code == 403
    assert secret_client.writes == []


def test_invalid_grants_json_is_rejected(tmp_path):
    client, secret_client = _client(tmp_path)
    response = client.post(
        "/api/v1/admin/akv-config",
        json={**PAYLOAD, "entra_grants_json": "[]"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )

    assert response.status_code == 400
    assert secret_client.writes == []
