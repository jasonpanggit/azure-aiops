"""HTTP-level tests for the Prompt 16 network routes.

These drive the real app factory over the real ``NetworkIntelligenceService``
built from the hub-spoke scenario estate, so scoping, envelopes, evidence and
the "unavailable, not empty" contract are validated end to end.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from network_scenario import (
    HUB_VNET,
    PROD_SUB,
    PROD_VNET,
    UAT_SUB,
    network_rows,
)

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from network.design import NetworkDesignPolicyStore
from network.service import NetworkIntelligenceService, build_service
from onboarding.service import SubscriptionOnboardingService

ADMIN_TOKEN = "admin-token-0123456789abcdef"
SCOPED_TOKEN = "scoped-token-0123456789abcdef"
SCOPED_ADMIN_TOKEN = "scoped-admin-token-0123456789abcdef"


def _principals() -> dict[str, Principal]:
    return {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        SCOPED_TOKEN: Principal(
            subject="scoped@example.com",
            grants=(Grant("reader", Scope.from_mapping({"subscription": [PROD_SUB]})),),
        ),
        SCOPED_ADMIN_TOKEN: Principal(
            subject="scoped-admin@example.com",
            grants=(Grant("admin", Scope.from_mapping({"subscription": [PROD_SUB]})),),
        ),
    }


def _client(
    tmp_path,
    *,
    with_network: bool = True,
    network_policy_store=None,
    network_service: NetworkIntelligenceService | None = None,
) -> TestClient:
    service = network_service or (build_service(network_rows()) if with_network else None)
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_provider=(lambda: service),
        network_policy_store=network_policy_store,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


@pytest.fixture
def client(tmp_path) -> TestClient:
    return _client(tmp_path)


def _auth(token: str = ADMIN_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _scope_leak_service() -> NetworkIntelligenceService:
    rows = network_rows()
    foreign_id = (
        f"/subscriptions/{UAT_SUB}/resourcegroups/rg-uat/providers/"
        "microsoft.keyvault/vaults/kv-foreign"
    )
    rows.append(
        {
            "subscription_id": UAT_SUB,
            "resource_id": foreign_id,
            "entity_type": "Resource",
            "name": "kv-foreign",
            "payload_json": json.dumps(
                {
                    "id": foreign_id,
                    "name": "kv-foreign",
                    "entityType": "Resource",
                    "subscriptionId": UAT_SUB,
                    "connection_id": "conn-uat",
                    "resourceType": "Microsoft.KeyVault/vaults",
                    "publicNetworkAccess": "Enabled",
                }
            ),
        }
    )
    return NetworkIntelligenceService.from_rows(
        rows,
        semantic_relationships=(
            {
                "subject_id": PROD_VNET,
                "object_id": f"{PROD_VNET}/subnets/snet-app",
                "predicate": "hosts",
            },
        ),
    )


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


class TestPolicy:
    def test_scoped_preview_matches_gaps_without_foreign_resources(
        self, tmp_path, monkeypatch
    ):
        import api.routers.network as network_router

        captured_relationships = []
        original_service = NetworkIntelligenceService

        class RecordingService(original_service):
            def __init__(self, *args, semantic_relationships=(), **kwargs):
                captured_relationships.append(tuple(semantic_relationships))
                super().__init__(
                    *args,
                    semantic_relationships=semantic_relationships,
                    **kwargs,
                )

        monkeypatch.setattr(
            network_router,
            "NetworkIntelligenceService",
            RecordingService,
        )
        client = _client(
            tmp_path,
            network_policy_store=NetworkDesignPolicyStore(),
            network_service=_scope_leak_service(),
        )

        preview = client.post(
            "/api/v1/network/policy/preview",
            headers=_auth(SCOPED_ADMIN_TOKEN),
            json={"rules": []},
        )
        gaps = client.get(
            "/api/v1/network/gaps",
            headers=_auth(SCOPED_ADMIN_TOKEN),
        )

        assert preview.status_code == 200
        assert gaps.status_code == 200
        preview_gaps = preview.json()["data"]["gaps"]
        scoped_gaps = gaps.json()["data"]["gaps"]
        assert {item["gap_id"] for item in preview_gaps} == {
            item["gap_id"] for item in scoped_gaps
        }
        assert all(item["subscription_id"] in {"", PROD_SUB} for item in preview_gaps)
        assert not any(item["resource_name"] == "kv-foreign" for item in preview_gaps)
        assert captured_relationships[-1], "preview must retain scoped semantic edges"

    @pytest.mark.parametrize(
        ("path", "collection"),
        (
            ("/api/v1/network/topology", "resources"),
            ("/api/v1/network/gaps", "gaps"),
            ("/api/v1/network/rule-findings", "findings"),
        ),
    )
    def test_scoped_network_routes_emit_no_foreign_subscription_ids(
        self, tmp_path, path, collection
    ):
        client = _client(tmp_path, network_service=_scope_leak_service())

        response = client.get(path, headers=_auth(SCOPED_TOKEN))

        assert response.status_code == 200
        data = response.json()["data"]
        items = (
            data["topology"][collection]
            if path.endswith("/topology")
            else data[collection]
        )
        assert all(item.get("subscription_id", "") in {"", PROD_SUB} for item in items)

    def test_service_has_one_scope_enforcement_path(self):
        assert not hasattr(NetworkIntelligenceService, "_scoped_topology")

    def test_read_reports_defaults_when_no_store_is_configured(self, tmp_path):
        client = _client(tmp_path, network_policy_store=None)
        response = client.get("/api/v1/network/policy", headers=_auth())
        assert response.status_code == 200
        body = response.json()
        rule_ids = {rule["rule_id"] for rule in body["data"]["rules"]}
        assert "internet-via-firewall" in rule_ids
        assert "nsg-override-default-outbound" in rule_ids
        assert body["warnings"]

    def test_read_marks_rules_the_analyzer_cannot_evaluate(self, tmp_path):
        client = _client(tmp_path, network_policy_store=NetworkDesignPolicyStore())
        client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={
                "rules": [
                    {"rule_id": "bring-your-own-rule", "name": "Custom", "enabled": True}
                ]
            },
        )
        body = client.get("/api/v1/network/policy", headers=_auth()).json()
        rules = {rule["rule_id"]: rule for rule in body["data"]["rules"]}
        assert rules["bring-your-own-rule"]["evaluated"] is False
        assert rules["internet-via-firewall"]["evaluated"] is True
        assert body["data"]["unevaluated_rule_ids"] == ["bring-your-own-rule"]
        # A rule nothing inspects must be called out, not silently accepted.
        assert any("not evaluated" in warning for warning in body["warnings"])

    def test_read_with_a_configured_store_has_no_warning(self, tmp_path):
        client = _client(tmp_path, network_policy_store=NetworkDesignPolicyStore())
        response = client.get("/api/v1/network/policy", headers=_auth())
        assert response.status_code == 200
        assert response.json().get("warnings", []) == []

    def test_write_requires_admin(self, tmp_path):
        client = _client(tmp_path, network_policy_store=NetworkDesignPolicyStore())
        response = client.patch(
            "/api/v1/network/policy",
            headers=_auth(SCOPED_TOKEN),
            json={"rules": [{"rule_id": "internet-via-firewall", "name": "x", "enabled": False}]},
        )
        assert response.status_code == 403

    def test_write_updates_and_persists_a_rule_toggle(self, tmp_path):
        store = NetworkDesignPolicyStore()
        client = _client(tmp_path, network_policy_store=store)
        response = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={"rules": [{"rule_id": "internet-via-firewall", "name": "x", "enabled": False}]},
        )
        assert response.status_code == 200
        rules = {r["rule_id"]: r for r in response.json()["data"]["rules"]}
        assert rules["internet-via-firewall"]["enabled"] is False
        # The other built-in rule is untouched by a partial update.
        assert rules["nsg-override-default-outbound"]["enabled"] is True
        # Persisted, so a second read reflects the change.
        follow_up = client.get("/api/v1/network/policy", headers=_auth())
        assert follow_up.json()["data"]["rules"] == response.json()["data"]["rules"]

    def test_write_without_a_store_reports_provider_unavailable(self, tmp_path):
        client = _client(tmp_path, network_policy_store=None)
        response = client.patch(
            "/api/v1/network/policy", headers=_auth(), json={"rules": []}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_unavailable"

    def test_write_rejects_a_rule_without_a_name(self, tmp_path):
        client = _client(tmp_path, network_policy_store=NetworkDesignPolicyStore())
        response = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={"rules": [{"rule_id": "internet-via-firewall"}]},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"

    def test_write_adds_a_custom_rule(self, tmp_path):
        client = _client(tmp_path, network_policy_store=NetworkDesignPolicyStore())
        response = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={
                "rules": [
                    {
                        "rule_id": "no-public-storage-endpoints",
                        "name": "No public storage endpoints",
                        "category": "custom",
                        "severity": "medium",
                        "enabled": True,
                    }
                ]
            },
        )
        assert response.status_code == 200
        rule_ids = {r["rule_id"] for r in response.json()["data"]["rules"]}
        assert "no-public-storage-endpoints" in rule_ids
        # Built-in rules remain untouched.
        assert "internet-via-firewall" in rule_ids
        assert response.json()["data"]["is_declared"] is True

    def test_write_removes_a_custom_rule(self, tmp_path):
        store = NetworkDesignPolicyStore()
        client = _client(tmp_path, network_policy_store=store)
        client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={
                "rules": [
                    {
                        "rule_id": "no-public-storage-endpoints",
                        "name": "No public storage endpoints",
                        "category": "custom",
                        "severity": "medium",
                        "enabled": True,
                    }
                ]
            },
        )
        response = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={"remove_rule_ids": ["no-public-storage-endpoints"]},
        )
        assert response.status_code == 200
        rule_ids = {r["rule_id"] for r in response.json()["data"]["rules"]}
        assert "no-public-storage-endpoints" not in rule_ids
        # Persisted removal.
        follow_up = client.get("/api/v1/network/policy", headers=_auth())
        follow_up_ids = {r["rule_id"] for r in follow_up.json()["data"]["rules"]}
        assert "no-public-storage-endpoints" not in follow_up_ids

    def test_write_removing_a_builtin_rule_is_a_noop(self, tmp_path):
        """Built-in rules are re-seeded on every read, so "deleting" one is a
        no-op rather than an error -- the UI hides the delete affordance for
        built-ins accordingly, but the API must not blow up if asked anyway."""
        client = _client(tmp_path, network_policy_store=NetworkDesignPolicyStore())
        response = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={"remove_rule_ids": ["internet-via-firewall"]},
        )
        assert response.status_code == 200
        rule_ids = {r["rule_id"] for r in response.json()["data"]["rules"]}
        assert "internet-via-firewall" in rule_ids

    def test_write_rejects_a_non_list_remove_rule_ids(self, tmp_path):
        client = _client(tmp_path, network_policy_store=NetworkDesignPolicyStore())
        response = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={"remove_rule_ids": "internet-via-firewall"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"
