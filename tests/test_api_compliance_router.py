"""HTTP-level tests for the compliance router.

Covers that ChangeIntelligence's policy/security deviation and configuration
drift findings are exposed through governed, evidence-backed endpoints, that
scope narrowing hides out-of-scope resources, and that an unconfigured
provider fails loudly (503) instead of silently reporting "fully compliant".
"""

from __future__ import annotations

import pytest
from change_scenario import change_engine
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

ADMIN_TOKEN = "admin-token-0123456789abcdef"
SCOPED_TOKEN = "scoped-token-0123456789abcde"


class FakeSecretWriter:
    def store(self, *, connection_id: str, secret_value: str) -> str:
        return f"keyvault://kv-aiops-example-test/secrets/aiops-conn-{connection_id}/v1"


def _principals() -> dict[str, Principal]:
    return {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        SCOPED_TOKEN: Principal(
            subject="scoped@example.com",
            grants=(Grant("reader", Scope({"subscription": {"sub-2"}})),),
        ),
    }


@pytest.fixture
def build_client(tmp_path):
    def _build(*, engine=None, principals=None) -> TestClient:
        context = ApiContext(
            onboarding=SubscriptionOnboardingService(
                tmp_path / "aiops", secret_writer=FakeSecretWriter()
            ),
            authenticator=StaticTokenAuthenticator(principals or _principals()),
            authorizer=Authorizer(),
            telemetry=ApiTelemetry(),
            change_provider=lambda: engine if engine is not None else change_engine(),
        )
        return TestClient(create_app(context), raise_server_exceptions=False)

    return _build


@pytest.fixture
def client(build_client) -> TestClient:
    return build_client()


def _auth(token: str = ADMIN_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_policy_deviations_are_exposed(client: TestClient) -> None:
    response = client.get("/api/v1/compliance/policy-deviations", headers=_auth())
    assert response.status_code == 200
    body = response.json()
    ids = [row["deviation_id"] for row in body["data"]]
    assert "POL-100" in ids
    assert body["evidence"][0]["source_engine"] == "intelligence.change.ChangeIntelligence"


def test_security_deviations_are_exposed(client: TestClient) -> None:
    response = client.get("/api/v1/compliance/security-deviations", headers=_auth())
    assert response.status_code == 200
    ids = [row["deviation_id"] for row in response.json()["data"]]
    assert "SEC-100" in ids


def test_configuration_drift_lists_drifted_resources(client: TestClient) -> None:
    response = client.get("/api/v1/compliance/configuration-drift", headers=_auth())
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows
    assert all(row["configuration_compliant"] is False for row in rows)


def test_posture_returns_per_resource_compliance_scores(client: TestClient) -> None:
    response = client.get("/api/v1/compliance/posture", headers=_auth())
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows
    assert all("compliance_score" in row for row in rows)


def test_summary_reports_counts_and_trends(client: TestClient) -> None:
    response = client.get("/api/v1/compliance/summary", headers=_auth())
    assert response.status_code == 200
    payload = response.json()["data"]
    assert "change_count" in payload["summary"]
    assert payload["trends"] is not None


def test_scope_narrowing_hides_out_of_scope_deviations(client: TestClient) -> None:
    response = client.get(
        "/api/v1/compliance/policy-deviations", headers=_auth(SCOPED_TOKEN)
    )
    assert response.status_code == 200
    ids = [row["deviation_id"] for row in response.json()["data"]]
    assert "POL-100" not in ids


def test_missing_provider_fails_loudly_rather_than_reporting_compliant(
    build_client,
) -> None:
    client = TestClient(
        create_app(
            ApiContext(
                onboarding=SubscriptionOnboardingService(
                    __import__("pathlib").Path("/tmp/aiops-compliance-test"),
                    secret_writer=FakeSecretWriter(),
                ),
                authenticator=StaticTokenAuthenticator(_principals()),
                authorizer=Authorizer(),
                telemetry=ApiTelemetry(),
                change_provider=lambda: None,
            )
        ),
        raise_server_exceptions=False,
    )
    response = client.get("/api/v1/compliance/policy-deviations", headers=_auth())
    assert response.status_code == 503
