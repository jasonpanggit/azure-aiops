"""HTTP-level tests for the Prompt 16 network routes.

These drive the real app factory over the real ``NetworkIntelligenceService``
built from the hub-spoke scenario estate, so scoping, envelopes, evidence and
the "unavailable, not empty" contract are validated end to end.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from network_scenario import (
    HUB_VNET,
    PROD_SUB,
    UAT_SUB,
    network_rows,
)

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from network.service import build_service
from onboarding.service import SubscriptionOnboardingService

ADMIN_TOKEN = "admin-token-0123456789abcdef"
SCOPED_TOKEN = "scoped-token-0123456789abcdef"


def _principals() -> dict[str, Principal]:
    return {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        SCOPED_TOKEN: Principal(
            subject="scoped@example.com",
            grants=(Grant("reader", Scope.from_mapping({"subscription": [PROD_SUB]})),),
        ),
    }


def _client(tmp_path, *, with_network: bool = True) -> TestClient:
    service = build_service(network_rows()) if with_network else None
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "hermes"),
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_provider=(lambda: service),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path) -> TestClient:
    return _client(tmp_path)


def _auth(token: str = ADMIN_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestTopology:
    def test_returns_stitched_hub_spoke_topology(self, client):
        response = client.get("/api/v1/network/topology", headers=_auth())
        assert response.status_code == 200
        body = response.json()
        topology = body["data"]["topology"]
        assert topology["spokes"] or topology["hubs"]
        assert body["data"]["summary"]

    def test_carries_evidence_naming_the_engine(self, client):
        body = client.get("/api/v1/network/topology", headers=_auth()).json()
        evidence = body["evidence"][0]
        assert evidence["source_engine"] == "network.NetworkIntelligenceService"
        assert evidence["timestamp"]

    def test_scope_narrows_the_estate(self, client):
        """A scoped principal must not see VNets outside their subscription."""
        scoped = client.get("/api/v1/network/topology", headers=_auth(SCOPED_TOKEN))
        assert scoped.status_code == 200
        topology = scoped.json()["data"]["topology"]
        classified = topology["hubs"] + topology["spokes"] + topology["isolated"]
        assert classified
        assert all(item["subscription_id"] == PROD_SUB for item in classified)

    def test_scope_narrows_the_derived_counts_too(self, client):
        """Counts are derived from the snapshot, so they must be scoped as
        well -- otherwise a scoped caller learns the size of the whole estate
        across the very boundary the scope enforces."""
        full = client.get("/api/v1/network/topology", headers=_auth()).json()
        scoped = client.get(
            "/api/v1/network/topology", headers=_auth(SCOPED_TOKEN)
        ).json()
        assert scoped["data"]["topology"]["counts"]["vnets"] == 1
        assert full["data"]["topology"]["counts"]["vnets"] == 3
        assert scoped["data"]["topology"]["connection_ids"] == ["conn-prod"]

    def test_outbound_peering_to_an_out_of_scope_vnet_stays_visible(self, client):
        """A scoped owner must still see that their VNet peers outward, or the
        view would hide a real dependency. Only the remote's own resources are
        withheld."""
        topology = client.get(
            "/api/v1/network/topology", headers=_auth(SCOPED_TOKEN)
        ).json()["data"]["topology"]
        remotes = {link["remote_vnet_id"] for link in topology["links"]}
        assert any(UAT_SUB in remote for remote in remotes)


class TestHubDependents:
    def test_answers_what_depends_on_the_hub(self, client):
        response = client.get(
            f"/api/v1/network/topology/hubs/{HUB_VNET}/dependents", headers=_auth()
        )
        assert response.status_code == 200
        assert response.json()["data"]["dependent_count"] >= 1

    def test_unknown_hub_is_not_found_rather_than_empty(self, client):
        response = client.get(
            "/api/v1/network/topology/hubs/no-such-vnet/dependents", headers=_auth()
        )
        assert response.status_code == 404


class TestTrafficFlow:
    def test_validates_a_flow_and_shows_the_deciding_path(self, client):
        response = client.get(
            "/api/v1/network/traffic-flow",
            params={"source": "10.2.1.10", "destination": "10.1.1.10", "port": 1433},
            headers=_auth(),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["verdict"] in {"allowed", "denied", "indeterminate"}
        assert "hops" in data

    def test_missing_endpoints_are_rejected_by_validation(self, client):
        response = client.get("/api/v1/network/traffic-flow", headers=_auth())
        assert response.status_code == 400

    def test_port_is_range_checked(self, client):
        response = client.get(
            "/api/v1/network/traffic-flow",
            params={"source": "10.2.1.10", "destination": "10.1.1.10", "port": 99999},
            headers=_auth(),
        )
        assert response.status_code == 400


class TestGaps:
    def test_reports_design_gaps(self, client):
        response = client.get("/api/v1/network/gaps", headers=_auth())
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["gaps"]
        assert "intended_design_declared" in body["data"]

    def test_absent_policy_is_reported_not_silently_passed(self, client):
        body = client.get("/api/v1/network/gaps", headers=_auth()).json()
        assert body["data"]["intended_design_declared"] is False

    def test_severity_filter_applies(self, client):
        body = client.get(
            "/api/v1/network/gaps", params={"severity": "critical"}, headers=_auth()
        ).json()
        assert all(gap["severity"] == "critical" for gap in body["data"]["gaps"])

    def test_unknown_severity_is_rejected(self, client):
        response = client.get(
            "/api/v1/network/gaps", params={"severity": "catastrophic"}, headers=_auth()
        )
        assert response.status_code == 400

    def test_paginates(self, client):
        body = client.get(
            "/api/v1/network/gaps", params={"limit": 1}, headers=_auth()
        ).json()
        assert len(body["data"]["gaps"]) <= 1
        assert body["pagination"]["limit"] == 1


class TestRuleFindings:
    def test_reports_overly_broad_rules(self, client):
        body = client.get("/api/v1/network/rule-findings", headers=_auth()).json()
        assert body["data"]["findings"]

    def test_findings_are_medium_confidence_because_no_flow_logs_exist(self, client):
        body = client.get("/api/v1/network/rule-findings", headers=_auth()).json()
        assert body["evidence"][0]["confidence"] == "medium"


class TestFirewallBypass:
    def test_answers_which_spokes_bypass_the_firewall(self, client):
        response = client.get("/api/v1/network/firewall-bypass", headers=_auth())
        assert response.status_code == 200
        assert response.json()["data"]["count"] >= 1


class TestUnavailableSnapshot:
    """Without a snapshot the routes must refuse, never imply a clean estate."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/network/topology",
            "/api/v1/network/gaps",
            "/api/v1/network/rule-findings",
            "/api/v1/network/firewall-bypass",
            "/api/v1/network/summary",
        ],
    )
    def test_reports_provider_unavailable(self, tmp_path, path):
        client = _client(tmp_path, with_network=False)
        response = client.get(path, headers=_auth())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_unavailable"


class TestAuthentication:
    def test_anonymous_access_is_refused(self, client):
        assert client.get("/api/v1/network/topology").status_code == 401
