"""HTTP-level tests for the Operations API.

Exercises the real app factory over the real onboarding service (backed by a
temporary registry), so authentication, RBAC, envelopes and error translation
are validated end to end rather than in isolation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from fabric.sync_service import _table_source_status_rows
from onboarding.service import SubscriptionOnboardingService
from storage.delta_writer import DeltaWriteMode, DeltaWriter
from storage.onelake_writer import OneLakeWriter

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


class TestFabricMedallionRouterTask1:
    @pytest.fixture
    def fabric_medallion_client(self, tmp_path, monkeypatch) -> TestClient:
        from api.routers import fabric_medallion as fabric_medallion_router

        context = ApiContext(
            onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
            authenticator=StaticTokenAuthenticator(_principals()),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
        )
        app = create_app(context)

        now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        source_rows = [
            {
                "source_family": "bronze_resources",
                "status": "succeeded",
                "availability": "healthy",
                "quality": "complete",
                "row_count": 12,
                "ingested_at": now,
                "lineage_ref": "bronze-entity",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
            },
            {
                "source_family": "silver_incidents",
                "status": "succeeded",
                "availability": "healthy",
                "quality": "complete",
                "row_count": 3,
                "ingested_at": now,
                "lineage_ref": "silver-entity",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
            },
            {
                "source_family": "gold_operational_context",
                "status": "succeeded",
                "availability": "healthy",
                "quality": "complete",
                "row_count": 1,
                "ingested_at": now,
                "lineage_ref": "gold-entity",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
            },
            {
                "source_family": "gold_hidden",
                "status": "succeeded",
                "availability": "healthy",
                "quality": "complete",
                "row_count": 1,
                "ingested_at": now,
                "lineage_ref": "gold-hidden-entity",
                "requested_scope_json": json.dumps({"subscription": [SUB_B]}),
            },
        ]
        manifest_rows = [
            {
                "projection_name": "topology_entities",
                "disposition": "active",
                "compatibility_version": None,
                "retired_reason": None,
                "registered_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-01T00:00:00Z",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
            },
            {
                "projection_name": "topology_edges",
                "disposition": "dormant",
                "compatibility_version": None,
                "retired_reason": None,
                "registered_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-01T00:00:00Z",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
            },
            {
                "projection_name": "hidden_edges",
                "disposition": "active",
                "compatibility_version": None,
                "retired_reason": None,
                "registered_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-01T00:00:00Z",
                "requested_scope_json": json.dumps({"subscription": [SUB_B]}),
            },
        ]

        monkeypatch.setattr(
            fabric_medallion_router,
            "_metadata_source_status_rows",
            lambda _context: source_rows,
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "_metadata_publication_manifest_rows",
            lambda _context: manifest_rows,
        )
        return TestClient(app, raise_server_exceptions=False)

    def test_fabric_medallion_layers_returns_bronze_silver_gold_summaries(
        self, fabric_medallion_client
    ):
        response = fabric_medallion_client.get(
            "/api/v1/fabric-medallion/layers", headers=_auth(ADMIN_TOKEN)
        )

        assert response.status_code == 200
        body = response.json()
        assert set(body["data"]["layers"]) == {"bronze", "silver", "gold"}
        assert body["data"]["layers"]["bronze"] == {"healthy": 1, "total": 1}
        assert body["data"]["layers"]["silver"] == {"healthy": 1, "total": 1}
        assert body["data"]["layers"]["gold"] == {"healthy": 2, "total": 2}
        assert body["data"]["tables"] == {
            "bronze": ["bronze_resources"],
            "silver": ["silver_incidents"],
            "gold": ["gold_hidden", "gold_operational_context"],
        }
        assert body["evidence"][0]["source_engine"] == "fabric.medallion_health"

    def test_fabric_medallion_layers_keeps_sync_generated_scope(
        self, fabric_medallion_client, monkeypatch
    ):
        from api.routers import fabric_medallion as fabric_medallion_router

        generated_rows = _table_source_status_rows(
            {
                "bronze_resources": [{"subscription_id": SUB_A}],
                "silver_empty": [],
            },
            "run-generated",
            datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            requested_scope={"subscription": [SUB_A]},
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "_metadata_source_status_rows",
            lambda _context: generated_rows,
        )

        response = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/layers?subscription={SUB_A}",
            headers=_auth(SCOPED_ADMIN_TOKEN),
        )

        assert response.status_code == 200
        assert response.json()["data"]["layers"] == {
            "bronze": {"healthy": 1, "total": 1},
            "silver": {"healthy": 1, "total": 1},
            "gold": {"healthy": 0, "total": 0},
        }

    def test_fabric_medallion_dataset_detail_wraps_status_and_404s_unknown(
        self, fabric_medallion_client
    ):
        response = fabric_medallion_client.get(
            "/api/v1/fabric-medallion/datasets/bronze_resources",
            headers=_auth(ADMIN_TOKEN),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["availability"] == "healthy"
        assert data["row_count"] == 12

        missing = fabric_medallion_client.get(
            "/api/v1/fabric-medallion/datasets/does_not_exist",
            headers=_auth(ADMIN_TOKEN),
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"

    def test_fabric_medallion_manifest_returns_all_entries_with_dispositions(
        self, fabric_medallion_client
    ):
        response = fabric_medallion_client.get(
            "/api/v1/fabric-medallion/manifest", headers=_auth(ADMIN_TOKEN)
        )

        assert response.status_code == 200
        entries = response.json()["data"]["entries"]
        assert {entry["projection_name"] for entry in entries} == {
            "topology_entities",
            "topology_edges",
            "hidden_edges",
        }
        assert {entry["disposition"] for entry in entries} == {"active", "dormant"}

    def test_fabric_medallion_manifest_filters_subscription_scope(
        self, fabric_medallion_client
    ):
        response = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/manifest?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        )

        assert response.status_code == 200
        entries = response.json()["data"]["entries"]
        assert {entry["projection_name"] for entry in entries} == {
            "topology_entities",
            "topology_edges",
        }
        assert {entry["subscription_id"] for entry in entries} == {SUB_A}

    def test_fabric_medallion_manifest_keeps_system_lifecycle_for_scoped_requests(
        self, fabric_medallion_client, monkeypatch
    ):
        from api.routers import fabric_medallion as fabric_medallion_router

        monkeypatch.setattr(
            fabric_medallion_router,
            "_metadata_publication_manifest_rows",
            lambda _context: [
                {
                    "projection_name": "system_projection",
                    "disposition": "deployment-blocked",
                    "compatibility_version": None,
                    "retired_reason": "blocked",
                    "registered_at": "2026-09-01T00:00:00Z",
                    "updated_at": "2026-09-01T00:00:00Z",
                    "subscription_id": "system",
                }
            ],
        )

        response = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/manifest?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        )

        assert response.status_code == 200
        assert response.json()["data"]["entries"] == [
            {
                "projection_name": "system_projection",
                "disposition": "deployment-blocked",
                "compatibility_version": None,
                "retired_reason": "blocked",
                "registered_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-01T00:00:00Z",
                "subscription_id": SUB_A,
                "subscription_connection": "",
            }
        ]

    def test_fabric_medallion_routes_enforce_auth_and_scope(self, fabric_medallion_client):
        unauthenticated = fabric_medallion_client.get("/api/v1/fabric-medallion/layers")
        assert unauthenticated.status_code == 401

        forbidden_scope = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/layers?subscription={SUB_B}",
            headers=_auth(SCOPED_TOKEN),
        )
        assert forbidden_scope.status_code == 403

        hidden_detail = fabric_medallion_client.get(
            "/api/v1/fabric-medallion/datasets/gold_hidden",
            headers=_auth(SCOPED_TOKEN),
        )
        assert hidden_detail.status_code == 404


def test_fabric_medallion_reads_live_delta_metadata_when_json_snapshot_is_empty(
    tmp_path, monkeypatch
):
    from fabric.schema_registry import schema_for

    config_path = tmp_path / "fabric.config.yaml"
    lakehouse_root = tmp_path / "onelake"
    source_root = tmp_path / "source"
    source_root.mkdir()
    config_path.write_text(
        "\n".join(
            [
                "fabric:",
                f"  source_data_root: {source_root}",
                "  workspace_id: workspace-a",
                "  lakehouse_id: lakehouse-a",
                f"  local_onelake_root: {lakehouse_root}",
                "",
            ]
        )
    )
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", str(config_path))
    onelake = OneLakeWriter(
        "workspace-a",
        "lakehouse-a",
        local_root=lakehouse_root,
    )
    delta = DeltaWriter()
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    base = {
        "tenant_id": "tenant-a",
        "subscription_id": SUB_A,
        "timestamp": observed_at,
        "change_version": "v1",
        "ingestion_run_id": "run-a",
    }
    delta.write(
        onelake.table_uri("metadata", "source_status"),
        [
            {
                **base,
                "resource_id": "source://gold_operational_context",
                "source_family": "gold_operational_context",
                "run_id": "run-a",
                "status": "succeeded",
                "observed_at": observed_at,
                "ingested_at": observed_at,
                "watermark": observed_at,
                "query_version": "1.0.0",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
                "provider_status": "succeeded",
                "freshness": "fresh",
                "availability": "healthy",
                "quality": "complete",
                "row_count": 3,
                "lineage_ref": "gold-entity",
                "error": "",
            }
        ],
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("metadata_source_status"),
    )
    delta.write(
        onelake.table_uri("metadata", "publication_manifest"),
        [
            {
                **base,
                "resource_id": "publication-manifest://topology_entities",
                "projection_name": "topology_entities",
                "disposition": "active",
                "compatibility_version": None,
                "retired_reason": None,
                "registered_at": observed_at,
                "updated_at": observed_at,
            }
        ],
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("metadata_publication_manifest"),
    )
    delta.write(
        onelake.table_uri("metadata", "quality_reports"),
        [
            {
                **base,
                "resource_id": "quality://run-a",
                "source_run_id": "run-a",
                "passed": False,
                "failed_records": 2,
                "report_json": json.dumps(
                    [
                        {
                            "table_name": "gold_operational_context",
                            "rule_counts": {
                                "ownership_coverage": 1,
                                "tag_coverage": 1,
                                "orphan_relationships": 0,
                            },
                        }
                    ]
                ),
            }
        ],
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("metadata_quality_reports"),
    )

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    app = create_app(context)
    client = TestClient(app, raise_server_exceptions=False)

    layers = client.get("/api/v1/fabric-medallion/layers", headers=_auth(ADMIN_TOKEN))
    manifest = client.get("/api/v1/fabric-medallion/manifest", headers=_auth(ADMIN_TOKEN))
    governance = client.get("/api/v1/fabric-medallion/governance", headers=_auth(ADMIN_TOKEN))

    assert layers.status_code == 200
    assert layers.json()["data"]["layers"]["gold"] == {"healthy": 1, "total": 1}
    assert manifest.status_code == 200
    assert manifest.json()["data"]["entries"] == [
        {
            "projection_name": "topology_entities",
            "disposition": "active",
            "compatibility_version": None,
            "retired_reason": None,
            "registered_at": observed_at,
            "updated_at": observed_at,
            "subscription_id": SUB_A,
            "subscription_connection": "",
        }
    ]
    assert governance.status_code == 200
    assert governance.json()["data"]["ownership_gap_count"] == 1
    assert governance.json()["data"]["tag_gap_count"] == 1


def test_fabric_medallion_governance_delta_fallback_filters_scope(
    tmp_path, monkeypatch
):
    from fabric.schema_registry import schema_for

    config_path = tmp_path / "fabric.config.yaml"
    lakehouse_root = tmp_path / "onelake"
    source_root = tmp_path / "source"
    source_root.mkdir()
    config_path.write_text(
        "\n".join(
            [
                "fabric:",
                f"  source_data_root: {source_root}",
                "  workspace_id: workspace-a",
                "  lakehouse_id: lakehouse-a",
                f"  local_onelake_root: {lakehouse_root}",
                "",
            ]
        )
    )
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", str(config_path))
    onelake = OneLakeWriter(
        "workspace-a",
        "lakehouse-a",
        local_root=lakehouse_root,
    )
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    base = {
        "tenant_id": "tenant-a",
        "timestamp": observed_at,
        "change_version": "v1",
        "ingestion_run_id": "run-a",
    }
    DeltaWriter().write(
        onelake.table_uri("metadata", "quality_reports"),
        [
            {
                **base,
                "subscription_id": SUB_A,
                "resource_id": "quality://sub-a",
                "source_run_id": "run-a",
                "passed": False,
                "failed_records": 1,
                "report_json": json.dumps(
                    [
                        {
                            "table_name": "silver_allowed",
                            "rule_counts": {
                                "ownership_coverage": 1,
                                "tag_coverage": 0,
                                "orphan_relationships": 0,
                            },
                        }
                    ]
                ),
            },
            {
                **base,
                "subscription_id": SUB_B,
                "resource_id": "quality://sub-b",
                "source_run_id": "run-b",
                "passed": False,
                "failed_records": 99,
                "report_json": json.dumps(
                    [
                        {
                            "table_name": "silver_hidden",
                            "rule_counts": {
                                "ownership_coverage": 99,
                                "tag_coverage": 99,
                                "orphan_relationships": 99,
                            },
                        }
                    ]
                ),
            },
        ],
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("metadata_quality_reports"),
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(
        "/api/v1/fabric-medallion/governance",
        headers=_auth(SCOPED_TOKEN),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ownership_gap_count"] == 1
    assert [gap["table_name"] for gap in data["gaps"]] == ["silver_allowed"]


class TestFabricMedallionRouterTask2:
    @pytest.fixture
    def fabric_medallion_capabilities_client(self, tmp_path, monkeypatch) -> TestClient:
        from api.routers import fabric_medallion as fabric_medallion_router

        context = ApiContext(
            onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
            authenticator=StaticTokenAuthenticator(_principals()),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
        )
        app = create_app(context)

        now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        source_rows = [
            {
                "source_family": "gold_operational_context",
                "status": "succeeded",
                "availability": "healthy",
                "quality": "complete",
                "row_count": 4,
                "ingested_at": now,
                "lineage_ref": "gold-ops-entity",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
                "subscription_id": SUB_A,
                "subscription_connection": "conn-a",
            },
            {
                "source_family": "silver_incidents",
                "status": "failed",
                "availability": "degraded",
                "quality": "incomplete",
                "row_count": 0,
                "ingested_at": now,
                "error": "capacity throttled",
                "lineage_ref": "silver-incident-entity",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
                "subscription_id": SUB_A,
                "subscription_connection": "conn-a",
            },
            {
                "source_family": "bronze_inventory",
                "status": "unavailable",
                "availability": "unavailable",
                "quality": "unknown",
                "row_count": 0,
                "ingested_at": now,
                "error": "workspace offline",
                "lineage_ref": "bronze-inventory-entity",
                "requested_scope_json": json.dumps({"subscription": [SUB_A]}),
                "subscription_id": SUB_A,
                "subscription_connection": "conn-a",
            },
        ]

        quality_rows = [
            {
                "observed_at": now,
                "report_json": json.dumps(
                    [
                        {
                            "table_name": "silver_incidents",
                            "rule_counts": {
                                "ownership_coverage": 2,
                                "tag_coverage": 1,
                                "orphan_relationships": 3,
                            },
                        },
                        {
                            "table_name": "gold_operational_context",
                            "rule_counts": {
                                "ownership_coverage": 1,
                                "tag_coverage": 0,
                                "orphan_relationships": 1,
                            },
                        },
                    ]
                ),
            }
        ]

        publication_rows = [
            {
                "projection_name": "ontology_entities",
                "status": "succeeded",
                "attempted_at": now,
                "attempts": 1,
                "retry_eligible": False,
                "message": "",
                "source": "publication-manifest",
            }
        ]

        semantic_entities = {
            "gold-ops-entity": {
                "upstream": ["silver-incident-entity"],
                "downstream": [],
                "lineage_depth": 1,
            },
            "silver-incident-entity": {
                "upstream": ["bronze-inventory-entity"],
                "downstream": ["gold-ops-entity"],
                "lineage_depth": 2,
            },
            "bronze-inventory-entity": {
                "upstream": [],
                "downstream": ["silver-incident-entity"],
                "lineage_depth": 0,
            },
        }

        monkeypatch.setattr(
            fabric_medallion_router,
            "_scoped_source_rows",
            lambda _context, _scope: source_rows,
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "_metadata_quality_report_rows",
            lambda _context, _scope: quality_rows,
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "_publication_attempt_rows",
            lambda _context, _scope: publication_rows,
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "_capacity_config",
            lambda _context, _scope: {
                "subscription_id": SUB_A,
                "resource_group": "rg-fabric",
                "capacity_name": "cap-aiops-prod",
                "workspace_id": "workspace-abc",
                "lakehouse_id": "lakehouse-def",
            },
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "check_capacity_state",
            lambda **_kwargs: {"status": "healthy", "reason": "", "checked_at": now},
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "list_roles",
            lambda _workspace_id, _item_id: [
                {"principal": "reader", "role": "Lakehouse.Reader"},
                {"principal": "contributor", "role": "Lakehouse.Contributor"},
            ],
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "last_maintenance_status",
            lambda _workspace_id, _lakehouse_id: {
                "status": "healthy",
                "checked_at": now,
                "last_compaction_at": now,
            },
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "_semantic_entities",
            lambda _context: semantic_entities,
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "entity_lineage_summary",
            lambda entity_id, entities: {
                "entity_id": entity_id,
                "upstream_count": len(entities.get(entity_id, {}).get("upstream", [])),
                "downstream_count": len(
                    entities.get(entity_id, {}).get("downstream", [])
                ),
                "lineage_depth": entities.get(entity_id, {}).get("lineage_depth", 0),
            },
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "native_lineage_url",
            lambda workspace_id: f"https://fabric.microsoft.com/lineage/{workspace_id}",
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "_semantic_readiness",
            lambda _context, _scope: {
                "status": "deployment-blocked",
                "reason": "definition_validated_not_deployed",
            },
        )
        monkeypatch.setattr(
            fabric_medallion_router,
            "gold_grounding_configured",
            lambda _scope: True,
        )
        return TestClient(app, raise_server_exceptions=False)

    def test_fabric_medallion_governance_returns_gap_and_blocker_counts(
        self, fabric_medallion_capabilities_client
    ):
        response = fabric_medallion_capabilities_client.get(
            "/api/v1/fabric-medallion/governance", headers=_auth(ADMIN_TOKEN)
        )
        assert response.status_code == 200

        payload = response.json()["data"]
        assert payload["ownership_gap_count"] == 3
        assert payload["tag_gap_count"] == 1
        assert payload["referential_integrity_blockers"] == 4
        assert payload["gaps"][0]["table_name"] == "silver_incidents"
        assert all("owner" not in entry for entry in payload["gaps"])

    def test_fabric_medallion_ingestion_history_marks_retry_eligibility(
        self, fabric_medallion_capabilities_client
    ):
        response = fabric_medallion_capabilities_client.get(
            "/api/v1/fabric-medallion/ingestion-history",
            headers=_auth(ADMIN_TOKEN),
        )
        assert response.status_code == 200

        runs = response.json()["data"]["runs"]
        by_status = {row["status"]: row for row in runs}
        assert by_status["failed"]["retry_eligible"] is True
        assert by_status["unavailable"]["retry_eligible"] is False
        assert by_status["succeeded"]["retry_eligible"] is False

    def test_fabric_medallion_capabilities_compose_read_only_signals_and_lineage(
        self, fabric_medallion_capabilities_client
    ):
        response = fabric_medallion_capabilities_client.get(
            "/api/v1/fabric-medallion/capabilities",
            headers=_auth(ADMIN_TOKEN),
        )
        assert response.status_code == 200

        data = response.json()["data"]
        assert data["capacity"]["status"] == "healthy"
        assert data["data_access_roles"]["status"] == "available"
        assert data["data_access_roles"]["total_roles"] == 2
        assert data["data_access_roles"]["roles"] == [
            {"name": "Lakehouse.Reader", "permission_count": 0},
            {"name": "Lakehouse.Contributor", "permission_count": 0},
        ]
        assert all("principal" not in role for role in data["data_access_roles"]["roles"])
        assert data["maintenance"]["status"] == "healthy"
        assert data["semantic_readiness"]["status"] == "deployment-blocked"
        assert data["data_agent_readiness"]["status"] == "available"
        assert data["lineage"]["native_lineage_url"].endswith("/workspace-abc")
        assert any(
            row["table_name"] == "gold_operational_context"
            and row["lineage"]["upstream_count"] == 1
            for row in data["lineage"]["datasets"]
        )

    def test_fabric_medallion_capacity_config_prefers_runtime_config(
        self, tmp_path, monkeypatch
    ):
        from api.routers import fabric_medallion as fabric_medallion_router

        config_path = tmp_path / "fabric.yaml"
        config_path.write_text(
            """
fabric:
  auth:
    mode: managed_identity
  workspace_id: workspace-config
  lakehouse_id: lakehouse-config
  capacity:
    subscription_id: subscription-config
    resource_group: rg-config
    capacity_name: cap-config
"""
        )
        monkeypatch.setenv("AIOPS_FABRIC_CONFIG", str(config_path))
        monkeypatch.setenv("AIOPS_FABRIC_CAPACITY_SUBSCRIPTION_ID", "subscription-env")
        monkeypatch.setenv("AIOPS_FABRIC_CAPACITY_RESOURCE_GROUP", "rg-env")
        monkeypatch.setenv("AIOPS_FABRIC_CAPACITY_NAME", "cap-env")

        config = fabric_medallion_router._capacity_config(
            object(),
            Scope.unrestricted(),
        )

        assert config == {
            "subscription_id": "subscription-config",
            "resource_group": "rg-config",
            "capacity_name": "cap-config",
            "workspace_id": "workspace-config",
            "lakehouse_id": "lakehouse-config",
        }

    def test_fabric_medallion_router_routes_are_get_only(self):
        from api.routers import fabric_medallion as fabric_medallion_router

        for route in fabric_medallion_router.router.routes:
            if not route.path.startswith("/api/v1/fabric-medallion"):
                continue
            methods = set(getattr(route, "methods", set()))
            assert methods <= {"GET", "HEAD", "OPTIONS"}
