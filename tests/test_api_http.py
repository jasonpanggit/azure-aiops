"""HTTP-level tests for the Operations API.

Exercises the real app factory over the real onboarding service (backed by a
temporary registry), so authentication, RBAC, envelopes and error translation
are validated end to end rather than in isolation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

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

    def test_connection_list_evidence_uses_latest_visible_sync_timestamp(
        self,
        client,
        onboarding,
        monkeypatch,
    ):
        observed = datetime.now(UTC)
        observed_at = observed.isoformat()
        lexically_later_but_older = (observed - timedelta(hours=2)).astimezone(
            timezone(timedelta(hours=14))
        ).isoformat()
        assert lexically_later_but_older > observed_at
        monkeypatch.setattr(
            onboarding,
            "list",
            lambda *, include_disabled=True: [
                {
                    "connection_id": "conn-a",
                    "name": "conn-a",
                    "subscription_id": SUB_A,
                    "last_synced_at": observed_at,
                    "last_successful_sync_at": observed_at,
                },
                {
                    "connection_id": "conn-b",
                    "name": "conn-b",
                    "subscription_id": SUB_B,
                    "last_synced_at": lexically_later_but_older,
                    "last_successful_sync_at": lexically_later_but_older,
                }
            ],
        )

        response = client.get(
            "/api/v1/subscription-connections",
            headers=_auth(ADMIN_TOKEN),
        )

        assert response.status_code == 200
        evidence = response.json()["evidence"][0]
        assert evidence["timestamp"] == observed_at
        assert evidence["freshness"] == "fresh"

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

    def test_fabric_dataset_receipts_separate_failed_attempt_from_retained_source(
        self, fabric_medallion_client, monkeypatch
    ):
        from api.routers import fabric_medallion as routes

        now = datetime.now(UTC).replace(microsecond=0)
        attempted = now.isoformat()
        previous = (now - timedelta(hours=1)).isoformat()
        row = {
            "source_family": "bronze_resources",
            "subscription_id": SUB_A,
            "subscription_connection": "conn-a",
            "partition_key": "partition-a",
            "requested_scope": {"subscription": [SUB_B]},
            "status": "partial",
            "provider_status": "failed",
            "availability": "degraded",
            "quality": "incomplete",
            "ingested_at": attempted,
            "attempted_at": attempted,
            "last_success_at": previous,
            "attempted_generation": "attempt-new",
            "effective_generation": "retained-old",
            "safe_error_code": "provider_timeout",
            "error": "sensitive provider response must not enter receipt",
            "lineage_ref": "opaque-partition-reference",
        }
        monkeypatch.setattr(routes, "_metadata_source_status_rows", lambda _context: [
            row,
            {
                **row, "partition_key": "partition-b", "effective_generation": "other-retained",
                "last_success_at": (now - timedelta(hours=2)).isoformat(),
            },
            {
                **row, "subscription_id": SUB_B, "subscription_connection": "conn-hidden",
                "partition_key": "hidden", "effective_generation": "hidden-generation",
            },
        ])
        response = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/datasets/bronze_resources?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == {"subscription": [SUB_A]}
        assert body["evidence"][0]["source_engine"] == "fabric.medallion_health"
        data = body["data"]
        recorded = data["recorded_evidence"]
        assert recorded["evidence_mode"] == "recorded_metadata"
        assert recorded["generation_kind"] == "source_partition"
        assert len(recorded["sources"]) == 2
        source = recorded["sources"][0]
        assert source == {
            "scope": {"subscription": [SUB_A], "subscription_connection": ["conn-a"]},
            "partition_key": "partition-a",
            "observed_at": attempted,
            "freshness": data["freshness_budget"]["sources"][0]["state"],
            "recorded_status": "partial",
            "provider_status": "failed",
            "last_attempt": {
                "status": "partial", "generation_id": "attempt-new",
                "attempted_at": attempted, "reason_code": "provider_timeout",
            },
            "last_good": {
                "status": "recorded", "generation_id": "retained-old",
                "observed_at": previous, "reason_code": "source_last_good_recorded",
            },
            "lineage_ref": "opaque-partition-reference",
        }
        assert recorded["sources"][1]["last_good"]["generation_id"] == "other-retained"
        serialized = json.dumps(recorded)
        assert "hidden-generation" not in serialized
        assert "sensitive provider" not in serialized
        assert "active_generation" not in serialized

    def test_fabric_dataset_legacy_success_does_not_invent_source_receipts(
        self, fabric_medallion_client
    ):
        response = fabric_medallion_client.get(
            "/api/v1/fabric-medallion/datasets/bronze_resources", headers=_auth(ADMIN_TOKEN)
        )
        assert response.status_code == 200
        source = response.json()["data"]["recorded_evidence"]["sources"][0]
        assert source["partition_key"] is None
        assert source["last_attempt"] == {
            "status": "succeeded", "generation_id": None, "attempted_at": None, "reason_code": None,
        }
        assert source["last_good"] == {
            "status": "unknown", "generation_id": None,
            "observed_at": None, "reason_code": "no_recorded_source_last_good",
        }

    @pytest.mark.parametrize("include_unorderable", [False, True])
    def test_fabric_dataset_receipts_reuse_conservative_partition_selection(
        self, fabric_medallion_client, monkeypatch, include_unorderable
    ):
        from api.routers import fabric_medallion as routes

        row = {
            "source_family": "bronze_resources", "subscription_id": SUB_A,
            "subscription_connection": "conn-a", "partition_key": "partition-a",
            "status": "succeeded", "ingested_at": "2026-10-19T12:00:00+00:00",
            "attempted_generation": "obsolete", "effective_generation": "retained",
            "last_success_at": "2026-10-19T12:00:00+00:00",
        }
        newer = {
            **row, "status": "failed", "ingested_at": "2026-10-19T08:30:00-04:00",
            "attempted_generation": "latest",
        }
        unknown_clock = {
            **row, "status": "failed", "ingested_at": "invalid-clock",
            "attempted_generation": "unorderable", "effective_generation": "",
        }
        rows = [newer, row] + ([unknown_clock] if include_unorderable else [])
        monkeypatch.setattr(routes, "_metadata_source_status_rows", lambda _context: rows)
        response = fabric_medallion_client.get(
            "/api/v1/fabric-medallion/datasets/bronze_resources", headers=_auth(ADMIN_TOKEN)
        )
        assert response.status_code == 200
        data = response.json()["data"]
        sources = data["recorded_evidence"]["sources"]
        assert len(sources) == data["freshness_budget"]["source_count"] == 1
        assert sources[0]["last_attempt"]["generation_id"] == (
            "unorderable" if include_unorderable else "latest"
        )
        assert sources[0]["last_attempt"]["status"] == "failed"
        assert sources[0]["last_good"]["status"] == (
            "unknown" if include_unorderable else "recorded"
        )
        assert sources[0]["freshness"] == data["freshness_budget"]["sources"][0]["state"]
        if include_unorderable:
            assert sources[0]["freshness"] == data["freshness"] == "unknown"

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

    def test_fabric_freshness_budget_is_scoped_and_keeps_authoritative_connection_identity(
        self, fabric_medallion_client, monkeypatch
    ):
        from api.routers import fabric_medallion as routes
        now = datetime.now(UTC)
        base = {
            "source_family": "bronze_resources", "status": "succeeded", "quality": "complete",
            "row_count": 5, "subscription_id": SUB_A,
            "requested_scope": {"subscription": [SUB_B], "subscription_connection": ["obsolete"]},
        }
        monkeypatch.setattr(routes, "_metadata_source_status_rows", lambda _: [
            {**base, "subscription_connection": "one", "ingested_at": (now - timedelta(days=2)).isoformat()},
            {**base, "subscription_connection": "two", "ingested_at": now.isoformat()},
            {**base, "subscription_id": SUB_B, "subscription_connection": "hidden", "ingested_at": now.isoformat()},
        ])
        response = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/datasets/bronze_resources?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["row_count"] == 10
        assert body["data"]["freshness"] == body["evidence"][0]["freshness"] == "stale"
        assert body["data"]["freshness_budget"]["source_count"] == 2
        assert [source["scope"] for source in body["data"]["freshness_budget"]["sources"]] == [
            {"subscription": [SUB_A], "subscription_connection": ["one"]},
            {"subscription": [SUB_A], "subscription_connection": ["two"]},
        ]
        layers = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/layers?subscription={SUB_A}", headers=_auth(SCOPED_TOKEN),
        ).json()
        assert layers["data"]["layers"]["bronze"] == {"healthy": 0, "total": 1}
        assert layers["evidence"][0]["freshness"] == "stale"

    def test_fabric_cannot_expose_multi_subscription_aggregate_using_only_first_scope_value(
        self, fabric_medallion_client, monkeypatch
    ):
        from api.routers import fabric_medallion as routes
        monkeypatch.setattr(routes, "_metadata_source_status_rows", lambda _: [
            {"source_family": "bronze_resources", "requested_scope": {"subscription": [SUB_A, SUB_B]},
             "row_count": 42, "ingested_at": datetime.now(UTC).isoformat()},
        ])
        response = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/datasets/bronze_resources?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        )
        assert response.status_code == 404

    def test_fabric_declared_contract_requires_authorization_and_registered_scope(self, fabric_medallion_client):
        assert fabric_medallion_client.get("/api/v1/fabric-medallion/datasets/bronze_resources/contract").status_code == 401
        hidden = fabric_medallion_client.get(
            "/api/v1/fabric-medallion/datasets/gold_hidden/contract", headers=_auth(SCOPED_TOKEN),
        )
        assert hidden.status_code == 404
        forbidden = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/datasets/bronze_resources/contract?subscription={SUB_B}", headers=_auth(SCOPED_TOKEN),
        )
        assert forbidden.status_code == 403
        response = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/datasets/bronze_resources/contract?subscription={SUB_A}", headers=_auth(SCOPED_TOKEN),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["declared_schema"]["status"] == "available"
        assert body["data"]["declared_schema"]["fields"]
        assert body["data"]["deployed_schema_validation"] == body["data"]["dataset_dependency_graph"] == "not_collected"
        assert body["scope"] == {"subscription": [SUB_A]}
        assert body["evidence"][0]["source_engine"] == "fabric.schema_registry"
        assert body["evidence"][1]["source_table"] == "metadata_source_status"
        assert len(body["data"]["source_diagnostics"]) == 1
        assert body["data"]["source_diagnostics"][0]["lineage_ref"] == "bronze-entity"

    def test_fabric_unknown_clock_stays_unknown_in_evidence_despite_recent_sibling(
        self, fabric_medallion_client, monkeypatch
    ):
        from api.routers import fabric_medallion as routes
        monkeypatch.setattr(routes, "_metadata_source_status_rows", lambda _: [
            {"source_family": "bronze_resources", "subscription_id": SUB_A, "subscription_connection": "one"},
            {"source_family": "bronze_resources", "subscription_id": SUB_A, "subscription_connection": "two",
             "ingested_at": datetime.now(UTC).isoformat()},
        ])
        body = fabric_medallion_client.get(
            f"/api/v1/fabric-medallion/datasets/bronze_resources?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        ).json()
        assert body["data"]["freshness"] == body["evidence"][0]["freshness"] == "unknown"
        assert body["evidence"][0]["timestamp"] == ""


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
        assert data["semantic_readiness"] == {
            "status": "unknown",
            "reason": "no_recorded_semantic_model_deployment_result",
        }
        assert data["data_agent_readiness"] == {
            "status": "unknown",
            "configured": True,
            "reason": "reachability_not_verified",
        }
        assert data["lineage"]["native_lineage_url"].endswith("/workspace-abc")
        assert any(
            row["table_name"] == "gold_operational_context"
            and row["lineage"]["upstream_count"] == 1
            for row in data["lineage"]["datasets"]
        )

    @pytest.mark.parametrize("publication_status", ["succeeded", "failed", "unavailable", "unknown", None])
    def test_fabric_readiness_does_not_promote_projection_publication_evidence(
        self, fabric_medallion_capabilities_client, monkeypatch, publication_status
    ):
        from api.routers import fabric_medallion as routes

        rows = [] if publication_status is None else [{
            "projection_name": "ontology_entities",
            "status": publication_status,
            "attempted_at": "2026-10-19T12:00:00Z",
            "attempts": 2,
            "retry_eligible": publication_status == "failed",
            "message": "projection publication failed" if publication_status == "failed" else "",
            "source": "publication-state",
        }]
        monkeypatch.setattr(routes, "_publication_attempt_rows", lambda _context, _scope: rows)

        response = fabric_medallion_capabilities_client.get(
            f"/api/v1/fabric-medallion/capabilities?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == {"subscription": [SUB_A]}
        assert body["evidence"][0]["source_engine"] == "fabric.medallion_capabilities"
        assert body["data"]["semantic_readiness"] == {
            "status": "unknown",
            "reason": "no_recorded_semantic_model_deployment_result",
        }

        history = fabric_medallion_capabilities_client.get(
            f"/api/v1/fabric-medallion/ingestion-history?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        )
        assert history.status_code == 200
        history_body = history.json()
        assert history_body["scope"] == body["scope"]
        assert history_body["evidence"][0]["source_engine"] == "onboarding.sync"
        assert [
            row for row in history_body["data"]["runs"] if row["source"] == "publication-state"
        ] == rows

    @pytest.mark.parametrize("configured", [True, False])
    def test_fabric_data_agent_settings_do_not_verify_reachability(
        self, fabric_medallion_capabilities_client, monkeypatch, configured
    ):
        from api.routers import fabric_medallion as routes

        monkeypatch.setattr(routes, "gold_grounding_configured", lambda _scope: configured)
        response = fabric_medallion_capabilities_client.get(
            "/api/v1/fabric-medallion/capabilities", headers=_auth(ADMIN_TOKEN),
        )
        assert response.status_code == 200
        assert response.json()["data"]["data_agent_readiness"] == {
            "status": "unknown" if configured else "disabled",
            "configured": configured,
            "reason": "reachability_not_verified" if configured else "not_configured",
        }

    def test_fabric_readiness_capabilities_preserve_authorization(
        self, fabric_medallion_capabilities_client
    ):
        assert fabric_medallion_capabilities_client.get(
            "/api/v1/fabric-medallion/capabilities",
        ).status_code == 401
        assert fabric_medallion_capabilities_client.get(
            f"/api/v1/fabric-medallion/capabilities?subscription={SUB_B}",
            headers=_auth(SCOPED_TOKEN),
        ).status_code == 403

    def test_fabric_capability_stage_receipts_stay_independently_unrecorded(
        self, fabric_medallion_capabilities_client
    ):
        response = fabric_medallion_capabilities_client.get(
            f"/api/v1/fabric-medallion/capabilities?subscription={SUB_A}",
            headers=_auth(SCOPED_TOKEN),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == {"subscription": [SUB_A]}
        stages = body["data"]["readiness_evidence"]
        assert set(stages) == {"projection_publication", "native_ontology", "semantic_model"}
        assert set(stages["semantic_model"]) == {
            "definition_validation", "publication", "query_qualification",
        }
        expected = [
            (stages["projection_publication"], "no_scoped_publication_recorder"),
            (stages["native_ontology"], "no_recorded_native_ontology_receipt"),
            (stages["semantic_model"]["definition_validation"], "no_recorded_semantic_definition_validation"),
            (stages["semantic_model"]["publication"], "no_recorded_semantic_model_publication"),
            (stages["semantic_model"]["query_qualification"], "no_recorded_semantic_query_qualification"),
        ]
        for stage, reason in expected:
            assert stage == {
                "status": "unknown", "evidence_mode": "not_recorded", "reason_code": reason,
                "last_attempt": None, "last_good": None,
            }

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
            Scope({"subscription": {"customer-subscription"}}),
        )

        assert config == {
            "subscription_id": "subscription-config",
            "resource_group": "rg-config",
            "capacity_name": "cap-config",
            "workspace_id": "workspace-config",
            "lakehouse_id": "lakehouse-config",
        }

    @pytest.mark.parametrize("file_exists", [True, False])
    def test_fabric_medallion_uses_canonical_json_override(
        self, tmp_path, monkeypatch, file_exists
    ):
        from api.routers import fabric_medallion as routes

        config_path = tmp_path / "fabric.yaml"
        if file_exists:
            config_path.write_text(
                "fabric:\n  workspace_id: obsolete-workspace\n  lakehouse_id: obsolete-lakehouse\n"
            )
        monkeypatch.setenv("AIOPS_FABRIC_CONFIG", str(config_path))
        monkeypatch.setenv("FABRIC_WORKSPACE_ID", "obsolete-env-workspace")
        monkeypatch.setenv("AIOPS_FABRIC_CONFIG_JSON", json.dumps({
            "fabric": {
                "workspace_id": "effective-workspace",
                "lakehouse_id": "effective-lakehouse",
                "capacity": {
                    "subscription_id": "effective-subscription",
                    "resource_group": "effective-group",
                    "capacity_name": "effective-capacity",
                },
            },
        }))
        assert routes._capacity_config(object(), Scope()) == {
            "subscription_id": "effective-subscription",
            "resource_group": "effective-group",
            "capacity_name": "effective-capacity",
            "workspace_id": "effective-workspace",
            "lakehouse_id": "effective-lakehouse",
        }

    def test_fabric_capacity_probe_uses_configured_user_assigned_identity(
        self, fabric_medallion_capabilities_client, monkeypatch,
    ):
        from types import SimpleNamespace

        from api.routers import fabric_medallion as fabric_medallion_router
        from fabric.config import FabricAuthConfig

        auth = FabricAuthConfig(
            mode="managed_identity",
            managed_identity_client_id="apps-identity",
        )
        credential = object()
        monkeypatch.setattr(
            fabric_medallion_router, "_runtime_config",
            lambda: SimpleNamespace(auth=auth),
        )

        def build(config):
            assert config is auth
            return credential

        def probe(**kwargs):
            assert kwargs["credential"] is credential
            assert kwargs["subscription_id"] == SUB_A
            return {"state": "healthy", "raw_state": "Active", "sku": "F4"}

        monkeypatch.setattr(fabric_medallion_router, "build_credential", build)
        monkeypatch.setattr(fabric_medallion_router, "check_capacity_state", probe)
        response = fabric_medallion_capabilities_client.get(
            "/api/v1/fabric-medallion/capabilities", headers=_auth(ADMIN_TOKEN),
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["capacity"]["sku"] == "F4"

    def test_fabric_medallion_router_routes_are_get_only(self):
        from api.routers import fabric_medallion as fabric_medallion_router

        for route in fabric_medallion_router.router.routes:
            if not route.path.startswith("/api/v1/fabric-medallion"):
                continue
            methods = set(getattr(route, "methods", set()))
            assert methods <= {"GET", "HEAD", "OPTIONS"}
