from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.config import ConnectorConfig
from onboarding.credentials import CredentialResolver
from onboarding.runtime import build_onboarding_service
from onboarding.service import SubscriptionOnboardingService
from onboarding.validation import (
    CONNECTION_CHECKS,
    ArgConnectionProbe,
    ConnectionValidator,
)

TENANT = "11111111-1111-1111-1111-111111111111"
SUBSCRIPTION = "22222222-2222-2222-2222-222222222222"
CLIENT = "33333333-3333-3333-3333-333333333333"
TOKEN = "preflight-writer-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PAYLOAD = {
    "connection_id": "preview",
    "name": "Preview",
    "tenant_id": TENANT,
    "subscription_id": SUBSCRIPTION,
    "credential": {
        "kind": "service_principal",
        "client_id": CLIENT,
        "client_secret": "synthetic-test-secret",
    },
    "metadata": {"business_service": "Payments"},
}


def _service(
    tmp_path: Path, failure: bool = False, advisor_failure: bool = False
) -> tuple[SubscriptionOnboardingService, list[str]]:
    seen = []

    def credential_factory(**kwargs):
        secret = kwargs["client_secret"]
        seen.append(secret)
        if failure:
            raise RuntimeError(f"SDK failure accidentally containing {secret}")
        return SimpleNamespace(
            get_token=lambda _: SimpleNamespace(token="synthetic-token")
        )

    def query(spec, subscriptions):
        if advisor_failure and "advisorresources" in spec.query:
            raise RuntimeError("optional capability denied")
        return [{"id": subscriptions[0]}]

    arg = SimpleNamespace(query=query)
    service = SubscriptionOnboardingService(
        str(tmp_path),
        secret_writer=Mock(),
        resolver=CredentialResolver(credential_factory=credential_factory),
        preflight_validator_factory=lambda resolver: ConnectionValidator(
            probe=ArgConnectionProbe(resolver=resolver, arg_client=arg),
        ),
    )
    return service, seen


def _client(
    service: SubscriptionOnboardingService,
    role: str = "admin",
    scope: Scope | None = None,
) -> TestClient:
    context = ApiContext(
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal(
                    subject="writer", grants=(Grant(role, scope or Scope()),)
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        onboarding=service,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def test_preview_checks_access_without_storing_or_starting_anything(
    tmp_path: Path,
) -> None:
    service, seen = _service(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    service.sync_async = Mock(side_effect=AssertionError("preflight must not sync"))
    response = _client(service).post(
        "/api/v1/subscription-connections/preflight", json=PAYLOAD, headers=AUTH
    )
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["passed"] is True
    assert report["advisory_only"] is True
    assert report["persisted"] is False
    assert report["sync_started"] is False
    assert [check["name"] for check in report["checks"]] == list(CONNECTION_CHECKS)
    assert seen == ["synthetic-test-secret"]
    service.secret_writer.store.assert_not_called()
    service.sync_async.assert_not_called()
    assert service.registry.list() == []
    assert {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before
    assert "synthetic-test-secret" not in response.text


def test_failure_details_do_not_echo_credentials_or_sdk_messages(
    tmp_path: Path, caplog
) -> None:
    service, _ = _service(tmp_path, failure=True)
    response = _client(service).post(
        "/api/v1/subscription-connections/preflight", json=PAYLOAD, headers=AUTH
    )
    assert response.status_code == 200
    assert response.json()["data"]["passed"] is False
    assert response.json()["data"]["checks"][0]["remediation"]
    assert "synthetic-test-secret" not in response.text + caplog.text
    assert "SDK failure" not in response.text
    assert service.registry.list() == []


def test_optional_access_failure_is_degraded_not_a_required_access_failure(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path, advisor_failure=True)
    response = _client(service).post(
        "/api/v1/subscription-connections/preflight", json=PAYLOAD, headers=AUTH
    )
    assert response.status_code == 200
    report = response.json()["data"]
    assert report["passed"] is True
    assert report["status"] == "degraded"
    assert report["failed_optional"] == ["advisor_read"]
    assert report["failed_required"] == []
    assert "optional capability denied" not in response.text


@pytest.mark.parametrize(
    ("role", "scope"),
    [
        ("reader", Scope()),
        ("operator", Scope()),
        ("admin", Scope.from_mapping({"subscription": ["outside"]})),
        (
            "admin",
            Scope.from_mapping(
                {"subscription": [SUBSCRIPTION], "business_service": ["Other"]}
            ),
        ),
    ],
)
def test_preflight_authorization_precedes_every_probe(
    tmp_path: Path, role: str, scope: Scope
) -> None:
    service, seen = _service(tmp_path)
    response = _client(service, role, scope).post(
        "/api/v1/subscription-connections/preflight", json=PAYLOAD, headers=AUTH
    )
    assert response.status_code in {403, 404}
    assert seen == []
    service.secret_writer.store.assert_not_called()


def test_unconfigured_preflight_is_unavailable_and_does_not_use_shared_validator(
    tmp_path: Path,
) -> None:
    service, seen = _service(tmp_path)
    service.preflight_validator_factory = None
    service.validator = Mock(
        side_effect=AssertionError("shared validator must not be used")
    )
    response = _client(service).post(
        "/api/v1/subscription-connections/preflight", json=PAYLOAD, headers=AUTH
    )
    assert response.status_code == 503
    assert seen == []


def test_request_local_credentials_are_isolated_under_concurrent_previews(
    tmp_path: Path,
) -> None:
    service, seen = _service(tmp_path)

    def preview(secret: str):
        return service.preflight(
            connection_id="preview",
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            client_id=CLIENT,
            client_secret=secret,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        reports = list(executor.map(preview, ["synthetic-one", "synthetic-two"]))
    assert all(report["passed"] for report in reports)
    assert sorted(seen) == ["synthetic-one", "synthetic-two"]
    assert service.registry.list() == []


def test_runtime_preflight_factory_uses_request_local_resolver(tmp_path: Path) -> None:
    def credential_factory(**kwargs):
        assert kwargs["client_secret"] == "synthetic-request-secret"
        return SimpleNamespace(
            get_token=lambda _: SimpleNamespace(token="synthetic-token")
        )

    resolver = CredentialResolver(credential_factory=credential_factory)
    arg = SimpleNamespace(query=lambda _spec, subscriptions: [{"id": subscriptions[0]}])
    service = build_onboarding_service(
        ConnectorConfig(output_dir=tmp_path), resolver=resolver, arg_client=arg
    )
    assert (
        service.preflight(
            connection_id="preview",
            tenant_id=TENANT,
            subscription_id=SUBSCRIPTION,
            client_id=CLIENT,
            client_secret="synthetic-request-secret",
        )["passed"]
        is True
    )
    assert service.registry.list() == []


def test_invalid_inputs_do_not_resolve_or_persist_secrets(tmp_path: Path) -> None:
    service, seen = _service(tmp_path)
    client = _client(service)
    for replacement in [
        {"subscription_id": "not-guid"},
        {"connection_id": "../bad"},
        {"credential": {**PAYLOAD["credential"], "secret_ref": "env://PRIVATE"}},
    ]:
        response = client.post(
            "/api/v1/subscription-connections/preflight",
            json={**PAYLOAD, **replacement},
            headers=AUTH,
        )
        assert response.status_code == 400, response.text
    assert seen == []
    assert service.registry.list() == []
    assert "synthetic-test-secret" not in json.dumps(service.list())
