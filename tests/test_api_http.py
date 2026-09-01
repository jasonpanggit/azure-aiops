"""HTTP-level tests for the Operations API.

Exercises the real app factory over the real onboarding service (backed by a
temporary registry), so authentication, RBAC, envelopes and error translation
are validated end to end rather than in isolation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

ADMIN_TOKEN = "admin-token-0123456789abcdef"
READER_TOKEN = "reader-token-0123456789abcdef"
SCOPED_TOKEN = "scoped-token-0123456789abcdef"
OPERATOR_TOKEN = "operator-token-0123456789abcd"
SCOPED_ADMIN_TOKEN = "scoped-admin-token-0123456789"
SCOPED_OPERATOR_TOKEN = "scoped-operator-token-012345"
SERVICE_ADMIN_TOKEN = "service-admin-token-0123456789"

SUB_A = "11111111-1111-1111-1111-111111111111"
SUB_B = "22222222-2222-2222-2222-222222222222"
TENANT = "33333333-3333-3333-3333-333333333333"
CLIENT = "44444444-4444-4444-4444-444444444444"


class FakeSecretWriter:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str]] = []

    def store(self, *, connection_id: str, secret_value: str) -> str:
        self.stored.append((connection_id, secret_value))
        return f"keyvault://kv-aiops-example-test/secrets/aiops-conn-{connection_id}/v1"


def _principals() -> dict[str, Principal]:
    return {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
        OPERATOR_TOKEN: Principal(
            subject="operator@example.com", grants=(Grant("operator"),)
        ),
        SCOPED_TOKEN: Principal(
            subject="scoped@example.com",
            grants=(Grant("reader", Scope.from_mapping({"subscription": [SUB_A]})),),
        ),
        SCOPED_ADMIN_TOKEN: Principal(
            subject="scoped-admin@example.com",
            grants=(Grant("admin", Scope.from_mapping({"subscription": [SUB_A]})),),
        ),
        SCOPED_OPERATOR_TOKEN: Principal(
            subject="scoped-operator@example.com",
            grants=(
                Grant("operator", Scope.from_mapping({"subscription": [SUB_A]})),
            ),
        ),
        SERVICE_ADMIN_TOKEN: Principal(
            subject="service-admin@example.com",
            grants=(
                Grant(
                    "admin",
                    Scope.from_mapping({"business_service": ["Retail Banking"]}),
                ),
            ),
        ),
    }


@pytest.fixture
def onboarding(tmp_path) -> SubscriptionOnboardingService:
    return SubscriptionOnboardingService(
        tmp_path / "aiops",
        secret_writer=FakeSecretWriter(),
    )


@pytest.fixture
def client(onboarding) -> TestClient:
    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create(client: TestClient, connection_id: str, subscription_id: str, **overrides):
    payload = {
        "connection_id": connection_id,
        "name": overrides.get("name", connection_id),
        "tenant_id": TENANT,
        "subscription_id": subscription_id,
        "credential": {"client_id": CLIENT, "secret_ref": "kv://vault/spn-secret"},
        "metadata": overrides.get(
            "metadata",
            {
                "business_service": "Retail Banking",
                "application": "Payments",
                "environment": "prod",
                "criticality": "high",
            },
        ),
    }
    return client.post(
        "/api/v1/subscription-connections", json=payload, headers=_auth(ADMIN_TOKEN)
    )


class TestMeta:
    def test_health_is_open(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_openapi_documents_every_route(self, client):
        spec = client.get("/openapi.json").json()
        paths = spec["paths"]
        assert "/api/v1/subscription-connections" in paths
        assert "/api/v1/search" in paths
        assert "/api/v1/network/topology" in paths
        assert "bearerAuth" in spec["components"]["securitySchemes"]
        connection_list = paths["/api/v1/subscription-connections"]["get"]
        assert connection_list["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"].endswith("/EnvelopeModel")
        assert "401" in connection_list["responses"]
        assert {item["name"] for item in connection_list["parameters"]} >= {
            "subscription",
            "business_service",
            "offset",
            "limit",
        }


class TestAuthentication:
    def test_missing_credentials_is_401(self, client):
        response = client.get("/api/v1/subscription-connections")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"

    def test_bad_token_is_401(self, client):
        response = client.get(
            "/api/v1/subscription-connections", headers=_auth("wrong-token-aaaaaaaaaaaa")
        )
        assert response.status_code == 401


class TestAuthorization:
    def test_reader_cannot_create_a_connection(self, client):
        response = client.post(
            "/api/v1/subscription-connections",
            json={
                "connection_id": "c1",
                "name": "c1",
                "tenant_id": TENANT,
                "subscription_id": SUB_A,
                "credential": {"client_id": CLIENT, "secret_ref": "kv://v/s"},
                "metadata": {},
            },
            headers=_auth(READER_TOKEN),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    def test_operator_cannot_write_but_admin_can(self, client):
        assert _create(client, "c-admin", SUB_A).status_code == 201
        response = client.post(
            "/api/v1/subscription-connections",
            json={
                "connection_id": "c-op",
                "name": "c-op",
                "tenant_id": TENANT,
                "subscription_id": SUB_A,
                "credential": {"client_id": CLIENT, "secret_ref": "kv://v/s"},
                "metadata": {},
            },
            headers=_auth(OPERATOR_TOKEN),
        )
        assert response.status_code == 403

    def test_scoped_reader_cannot_see_other_subscriptions(self, client):
        """Cross-subscription leak regression."""
        _create(client, "conn-a", SUB_A)
        _create(client, "conn-b", SUB_B)

        everything = client.get(
            "/api/v1/subscription-connections", headers=_auth(ADMIN_TOKEN)
        ).json()["data"]
        assert {row["connection_id"] for row in everything} == {"conn-a", "conn-b"}

        visible = client.get(
            "/api/v1/subscription-connections", headers=_auth(SCOPED_TOKEN)
        ).json()["data"]
        assert {row["connection_id"] for row in visible} == {"conn-a"}

    def test_scoped_admin_cannot_create_or_mutate_other_subscription(self, client):
        _create(client, "conn-b", SUB_B)

        create = client.post(
            "/api/v1/subscription-connections",
            json={
                "connection_id": "conn-b2",
                "name": "conn-b2",
                "tenant_id": TENANT,
                "subscription_id": SUB_B,
                "credential": {"client_id": CLIENT, "secret_ref": "kv://v/s"},
                "metadata": {},
            },
            headers=_auth(SCOPED_ADMIN_TOKEN),
        )
        disable = client.post(
            "/api/v1/subscription-connections/conn-b/disable",
            headers=_auth(SCOPED_ADMIN_TOKEN),
        )

        assert create.status_code == 404
        assert disable.status_code == 404

    def test_scoped_operator_cannot_run_other_subscription(self, client):
        _create(client, "conn-b", SUB_B)

        response = client.post(
            "/api/v1/subscription-connections/conn-b/validate",
            headers=_auth(SCOPED_OPERATOR_TOKEN),
        )

        assert response.status_code == 404

    def test_scoped_admin_cannot_remap_connection_outside_business_service(self, client):
        _create(client, "conn-a", SUB_A)
        client.put(
            "/api/v1/subscription-connections/conn-a/metadata",
            json={"metadata": {"business_service": "Retail Banking"}},
            headers=_auth(ADMIN_TOKEN),
        )

        response = client.put(
            "/api/v1/subscription-connections/conn-a/metadata",
            json={"metadata": {"business_service": "Wealth"}},
            headers=_auth(SERVICE_ADMIN_TOKEN),
        )

        assert response.status_code == 404

    def test_connection_list_paginates_after_scope_filtering(self, client):
        _create(client, "conn-a", SUB_A)
        _create(client, "conn-b", SUB_B)
        response = client.get(
            "/api/v1/subscription-connections?offset=1&limit=1",
            headers=_auth(ADMIN_TOKEN),
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        assert response.json()["pagination"] == {
            "offset": 1,
            "limit": 1,
            "total": 2,
            "next_offset": None,
        }

    def test_response_carries_a_correlation_id(self, client):
        response = client.get(
            "/api/v1/subscription-connections",
            headers={**_auth(ADMIN_TOKEN), "X-Correlation-ID": "trace_0001"},
        )
        assert response.headers["x-correlation-id"] == "trace_0001"

    def test_error_carries_a_correlation_id(self, client):
        response = client.get("/api/v1/subscription-connections")
        assert response.status_code == 401
        assert response.json()["error"]["details"]["correlation_id"] == response.headers[
            "x-correlation-id"
        ]

    def test_scoped_reader_gets_404_on_out_of_scope_detail(self, client):
        _create(client, "conn-b", SUB_B)
        response = client.get(
            "/api/v1/subscription-connections/conn-b", headers=_auth(SCOPED_TOKEN)
        )
        # Not 403: existence itself must not be disclosed.
        assert response.status_code == 404

    def test_requesting_a_scope_outside_the_grant_is_403(self, client):
        response = client.get(
            f"/api/v1/subscription-connections?subscription={SUB_B}",
            headers=_auth(SCOPED_TOKEN),
        )
        assert response.status_code == 403


class TestConnectionsCrud:
    def test_create_then_read_back(self, client):
        created = _create(client, "conn-a", SUB_A)
        assert created.status_code == 201
        body = created.json()
        assert body["data"]["connection_id"] == "conn-a"
        assert body["data"]["validation"]["status"] == "failed"
        assert body["data"]["initial_sync"]["status"] == "not_started"
        assert "client_secret" not in created.text
        assert body["evidence"][0]["source_engine"].endswith(
            "SubscriptionOnboardingService"
        )

        detail = client.get(
            "/api/v1/subscription-connections/conn-a", headers=_auth(ADMIN_TOKEN)
        )
        assert detail.status_code == 200
        assert detail.json()["data"]["subscription_id"] == SUB_A

    def test_duplicate_connection_is_409(self, client):
        _create(client, "conn-a", SUB_A)
        assert _create(client, "conn-a", SUB_A).status_code == 409

    def test_unknown_connection_is_404(self, client):
        response = client.get(
            "/api/v1/subscription-connections/nope", headers=_auth(ADMIN_TOKEN)
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_unknown_connection_health_is_handled_not_a_server_crash(self, onboarding):
        """A missing connection is a domain 404, never an unhandled ASGI crash.

        ``raise_server_exceptions=False`` on the shared fixture masks handler
        escapes, so this asserts against a strict client: if the exception
        reaches ServerErrorMiddleware (which always re-raises), this fails.
        """
        context = ApiContext(
            onboarding=onboarding,
            authenticator=StaticTokenAuthenticator(_principals()),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
        )
        strict = TestClient(create_app(context))
        for path in (
            "/api/v1/subscription-connections/nope",
            "/api/v1/subscription-connections/nope/health",
        ):
            response = strict.get(path, headers=_auth(ADMIN_TOKEN))
            assert response.status_code == 404, path
            assert response.json()["error"]["code"] == "not_found"

    def test_metadata_mapping(self, client):
        _create(client, "conn-a", SUB_A, metadata={})
        response = client.put(
            "/api/v1/subscription-connections/conn-a/metadata",
            json={
                "metadata": {
                    "business_service": "Retail Banking",
                    "application": "Payments",
                    "environment": "prod",
                    "project_owner": "ops@example.com",
                    "support_team": "SRE",
                    "criticality": "high",
                    "region": "australiaeast",
                    "cost_center": "CC-100",
                }
            },
            headers=_auth(ADMIN_TOKEN),
        )
        assert response.status_code == 200
        metadata = response.json()["data"]["business_metadata"]
        assert metadata["business_service"] == "Retail Banking"
        assert metadata["cost_center"] == "CC-100"

    def test_disable_and_enable(self, client):
        _create(client, "conn-a", SUB_A)
        disabled = client.post(
            "/api/v1/subscription-connections/conn-a/disable", headers=_auth(ADMIN_TOKEN)
        )
        assert disabled.status_code == 200
        assert disabled.json()["data"]["is_active"] is False

        enabled = client.post(
            "/api/v1/subscription-connections/conn-a/enable", headers=_auth(ADMIN_TOKEN)
        )
        assert enabled.json()["data"]["is_active"] is True

    def test_delete_connection(self, client):
        _create(client, "conn-a", SUB_A)

        deleted = client.delete(
            "/api/v1/subscription-connections/conn-a", headers=_auth(ADMIN_TOKEN)
        )

        assert deleted.status_code == 204
        missing = client.get(
            "/api/v1/subscription-connections/conn-a", headers=_auth(ADMIN_TOKEN)
        )
        assert missing.status_code == 404

    def test_rejects_unknown_fields(self, client):
        response = client.post(
            "/api/v1/subscription-connections",
            json={
                "connection_id": "c1",
                "name": "c1",
                "tenant_id": TENANT,
                "subscription_id": SUB_A,
                "credential": {"client_id": CLIENT, "secret_ref": "kv://v/s"},
                "metadata": {},
                "client_secret": "should-never-be-accepted",
            },
            headers=_auth(ADMIN_TOKEN),
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"

    def test_create_accepts_client_secret_and_persists_key_vault_reference(self, client):
        response = client.post(
            "/api/v1/subscription-connections",
            json={
                "connection_id": "conn-secret",
                "name": "conn-secret",
                "tenant_id": TENANT,
                "subscription_id": SUB_A,
                "credential": {"client_id": CLIENT, "client_secret": "from-user"},
                "metadata": {},
            },
            headers=_auth(ADMIN_TOKEN),
        )

        assert response.status_code == 201
        credential = response.json()["data"]["credential"]
        assert (
            credential["secret_ref"]
            == "keyvault://kv-aiops-example-test/secrets/aiops-conn-conn-secret/v1"
        )
        assert "from-user" not in response.text

    def test_health_route(self, client):
        _create(client, "conn-a", SUB_A)
        response = client.get(
            "/api/v1/subscription-connections/conn-a/health", headers=_auth(ADMIN_TOKEN)
        )
        assert response.status_code == 200
        assert "status_counts" in response.json()["data"]


class TestSecretHygiene:
    def test_no_secret_material_in_any_connection_response(self, client):
        _create(client, "conn-a", SUB_A)
        for path in (
            "/api/v1/subscription-connections",
            "/api/v1/subscription-connections/conn-a",
            "/api/v1/subscription-connections/conn-a/health",
        ):
            body = client.get(path, headers=_auth(ADMIN_TOKEN)).text
            assert "client_secret" not in body
            assert "spn-secret" not in body or "kv://" in body


class TestSemanticGuard:
    def test_context_routes_report_missing_snapshot_not_empty_data(self, client):
        """No snapshot must never be rendered as 'nothing is wrong'."""
        response = client.get(
            "/api/v1/applications/Payments", headers=_auth(ADMIN_TOKEN)
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_unavailable"


class TestPlannedCapabilities:
    @pytest.mark.parametrize(
        ("path", "capability"),
        [
            ("/api/v1/kbs", "vulnerability.kb"),
            ("/api/v1/cves", "vulnerability.cve"),
        ],
    )
    def test_unavailable_vulnerability_capabilities_return_503(
        self, client, path, capability
    ):
        response = client.get(path, headers=_auth(ADMIN_TOKEN))
        assert response.status_code == 503
        body = response.json()["error"]
        assert body["code"] == "provider_unavailable"
        assert body["details"]["capability"] == "vulnerability"

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/network/topology",
            "/api/v1/network/traffic-flow?source=a&destination=b",
            "/api/v1/network/gaps",
        ],
    )
    def test_network_routes_report_unavailable_rather_than_empty(self, client, path):
        """Prompt 16 built these, but with no snapshot loaded they must still
        refuse to imply a clean estate."""
        response = client.get(path, headers=_auth(ADMIN_TOKEN))
        assert response.status_code != 200
        assert response.json()["error"]["code"] != "not_implemented"
