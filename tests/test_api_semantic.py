"""API tests against a real semantic knowledge graph.

Builds the ontology through the real ingestion pipeline (the same harness used
by the connection lineage tests) and serves it through the API, so the context
routes are proven against real entities rather than stubs.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_connection_lineage_integration import _build_engine, make_connection

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

TOKEN = "admin-token-0123456789abcdef"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
SCOPED_TOKEN = "retail-reader-token-01234567"


@pytest.fixture
def client(tmp_path) -> TestClient:
    engine = _build_engine(make_connection())
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: engine,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


@pytest.fixture
def retail_scoped_client(tmp_path) -> TestClient:
    retail = make_connection()
    wealth = replace(
        make_connection(
            business_service="Wealth",
            application="Advisory",
            environment="production",
        ),
        connection_id="wealth-core",
        name="Wealth Core",
        subscription_id="sub-wealth",
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {
                SCOPED_TOKEN: Principal(
                    subject="retail-reader@example.com",
                    grants=(
                        Grant(
                            "reader",
                            Scope.from_mapping(
                                {"business_service": ["Retail Banking"]}
                            ),
                        ),
                    ),
                )
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: _build_engine(retail, wealth),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def test_health_reports_the_snapshot_is_loaded(client):
    assert client.get("/health").json()["semantic_snapshot_loaded"] is True


def test_application_context_is_served_from_the_semantic_layer(client):
    response = client.get("/api/v1/applications/Payments", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["subject"]
    evidence = body["evidence"][0]
    assert evidence["source_engine"] == "semantic.SemanticEngine"
    assert evidence["source_table"] == "ontology_entities"
    assert evidence["timestamp"] == "2026-01-01T00:00:00Z"
    assert evidence["freshness"] in {"fresh", "aging", "stale", "unknown"}


def test_business_service_context(client):
    response = client.get("/api/v1/business-services/Retail Banking", headers=HEADERS)
    assert response.status_code == 200


def test_subscription_connection_context_exposes_lineage(client):
    """The full Business Service -> Application -> Environment -> Connection chain."""
    response = client.get(
        "/api/v1/subscription-connections/prod-core/context", headers=HEADERS
    )
    assert response.status_code == 200
    sections = response.json()["data"]["sections"]
    assert sections["application_mappings"]
    assert sections["environment_mappings"]
    assert sections["business_service_linkages"]


def test_search_supports_the_documented_intents(client):
    response = client.get("/api/v1/search?q=production applications", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["evidence"][0]["confidence"] == "medium"


def test_unsupported_search_lists_the_supported_intents(client):
    """The semantic search surface is intent-driven, not free text. An
    unsupported phrase must tell the caller what *is* supported rather than
    returning zero results, which the UI would render as 'nothing found'.
    """
    response = client.get("/api/v1/search?q=Payments", headers=HEADERS)
    assert response.status_code == 400
    assert "production applications" in response.json()["error"]["message"]


def test_dependency_graph(client):
    response = client.get(
        "/api/v1/graph/dependencies/Payments?direction=both", headers=HEADERS
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "upstream" in data and "downstream" in data


def test_unknown_subject_is_404_not_500(client):
    response = client.get("/api/v1/applications/NoSuchApp", headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_scope_is_echoed_on_every_read(client):
    body = client.get("/api/v1/applications/Payments", headers=HEADERS).json()
    assert "scope" in body


def test_incident_route_reports_unavailable_when_no_engine_is_registered(client):
    """An unregistered engine must not look like an incident-free estate."""
    response = client.get("/api/v1/incidents", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert response.json()["error"]["details"]["capability"] == "incidents"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/applications/Advisory",
        "/api/v1/business-services/Wealth",
        "/api/v1/graph/dependencies/Advisory",
        "/api/v1/risk/Advisory",
        "/api/v1/impact/Advisory",
    ],
)
def test_scoped_reader_cannot_access_out_of_scope_semantic_subject(
    retail_scoped_client, path
):
    """Regression for F1/F2: semantic subjects must never bypass read scope."""
    response = retail_scoped_client.get(
        path, headers={"Authorization": f"Bearer {SCOPED_TOKEN}"}
    )
    assert response.status_code == 404
