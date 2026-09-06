"""HTTP-level tests for the Prompt 16 network routes.

These drive the real app factory over the real ``NetworkIntelligenceService``
built from the hub-spoke scenario estate, so scoping, envelopes, evidence and
the "unavailable, not empty" contract are validated end to end.
"""

from __future__ import annotations

import json
from urllib.parse import quote

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
from api.providers import ProviderRuntime, ProviderSpec
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from network.design import NetworkDesignPolicyStore
from network.models import NetworkSnapshot
from network.rule_engine import SUPPORTED_OPERATORS, SUPPORTED_TARGET_NAMES
from network.service import NetworkIntelligenceService, build_service
from onboarding.service import SubscriptionOnboardingService
from storage.onelake_documents import OneLakeDocumentStore

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
    provider_runtime: ProviderRuntime | None = None,
) -> TestClient:
    service = network_service or (build_service(network_rows()) if with_network else None)
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(_principals()),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_provider=(lambda: service),
        network_policy_store=network_policy_store,
        provider_runtime=provider_runtime,
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
    def test_detail_contract_is_additive_and_defaults_to_full(self, client):
        default = client.get("/api/v1/network/topology", headers=_auth())
        full = client.get(
            "/api/v1/network/topology",
            params={"detail": "full"},
            headers=_auth(),
        )
        summary = client.get(
            "/api/v1/network/topology",
            params={"detail": "summary"},
            headers=_auth(),
        )

        assert default.status_code == full.status_code == summary.status_code == 200
        assert default.content == full.content
        assert summary.json()["data"]["topology"]["coverage"]["truncated"] is False

    def test_rejects_an_unknown_detail_level(self, client):
        response = client.get(
            "/api/v1/network/topology",
            params={"detail": "everything"},
            headers=_auth(),
        )

        assert response.status_code == 400

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

    def test_withheld_nsg_rules_are_paginated_through_drill_down(self, tmp_path):
        service = build_service(network_rows())
        nsg = next(item for item in service.snapshot.nsgs if len(item.ordered_rules()) > 1)
        client = _client(tmp_path, network_service=service)

        response = client.get(
            "/api/v1/network/topology/resources/"
            f"{quote(nsg.resource_id.lstrip('/'), safe='/')}/details",
            params={"offset": 1, "limit": 1},
            headers=_auth(),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["resource_id"] == nsg.resource_id
        assert body["data"]["detail_type"] == "rules"
        assert len(body["data"]["items"]) == 1
        assert body["data"]["coverage"] == {
            "total": len(nsg.ordered_rules()),
            "returned": 1,
            "truncated": True,
        }
        assert body["pagination"] == {
            "offset": 1,
            "limit": 1,
            "total": len(nsg.ordered_rules()),
            "next_offset": 2,
        }
        assert body["warnings"]

    def test_drill_down_returns_no_data_for_an_out_of_scope_resource(self, tmp_path):
        service = build_service(network_rows())
        foreign_nsg = next(
            item for item in service.snapshot.nsgs if item.subscription_id == UAT_SUB
        )
        client = _client(tmp_path, network_service=service)

        response = client.get(
            "/api/v1/network/topology/resources/"
            f"{quote(foreign_nsg.resource_id.lstrip('/'), safe='/')}/details",
            headers=_auth(SCOPED_TOKEN),
        )

        assert response.status_code == 200
        assert response.json()["data"] == {
            "resource_id": foreign_nsg.resource_id,
            "detail_type": "",
            "items": [],
            "coverage": {"total": 0, "returned": 0, "truncated": False},
        }


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

    def test_coverage_and_pagination_are_additive_and_honest(self, client):
        complete = client.get(
            "/api/v1/network/gaps",
            params={"limit": 500},
            headers=_auth(),
        ).json()
        total = len(complete["data"]["gaps"])
        expected_legacy_types = {
            "gaps": list,
            "intended_design_declared": bool,
            "summary": dict,
        }

        assert total > 1
        assert all(
            key in complete["data"]
            and isinstance(complete["data"][key], expected_type)
            for key, expected_type in expected_legacy_types.items()
        )
        assert complete["data"]["coverage"] == {
            "total": total,
            "returned": total,
            "truncated": False,
        }
        assert "warnings" not in complete

        first = client.get(
            "/api/v1/network/gaps",
            params={"limit": 1, "offset": 0},
            headers=_auth(),
        ).json()
        second = client.get(
            "/api/v1/network/gaps",
            params={"limit": 1, "offset": 1},
            headers=_auth(),
        ).json()

        assert first["data"]["coverage"] == {
            "total": total,
            "returned": 1,
            "truncated": True,
        }
        assert second["data"]["gaps"] == complete["data"]["gaps"][1:2]
        assert second["pagination"]["next_offset"] == 2
        assert any(
            f"Showing 1 of {total} inspection gaps" in warning
            for warning in first["warnings"]
        )


class TestRuleFindings:
    def test_reports_overly_broad_rules(self, client):
        body = client.get("/api/v1/network/rule-findings", headers=_auth()).json()
        assert body["data"]["findings"]

    def test_findings_name_the_affected_resources_additively(self, client):
        body = client.get(
            "/api/v1/network/rule-findings",
            params={"limit": 500},
            headers=_auth(),
        ).json()
        finding = next(
            item
            for item in body["data"]["findings"]
            if item["control"] == "nsg" and item["affected_resource_ids"]
        )

        assert isinstance(finding["affected_resource_ids"], list)
        assert all(
            resource_id.startswith("/subscriptions/")
            for resource_id in finding["affected_resource_ids"]
        )

    def test_findings_are_medium_confidence_because_no_flow_logs_exist(self, client):
        body = client.get("/api/v1/network/rule-findings", headers=_auth()).json()
        assert body["evidence"][0]["confidence"] == "medium"

    def test_analyzed_flow_logs_raise_confidence_and_correct_basis(
        self,
        tmp_path,
    ):
        base = build_service(network_rows())
        flow = {
            "subject_id": "flow:endpoint",
            "object_id": "/rule/not-present",
            "predicate": "trafficObserved",
            "attributes": {"dataSource": "traffic_analytics"},
        }
        service = NetworkIntelligenceService(
            base.snapshot,
            semantic_relationships=(flow,),
            flow_observations=(flow,),
        )

        body = _client(
            tmp_path,
            network_service=service,
        ).get("/api/v1/network/rule-findings", headers=_auth()).json()

        assert body["evidence"][0]["confidence"] == "high"
        assert all(
            "flow logs are not ingested"
            not in str(finding.get("evidence", {}).get("basis", ""))
            for finding in body["data"]["findings"]
        )

    def test_coverage_and_pagination_are_additive_and_honest(self, client):
        complete = client.get(
            "/api/v1/network/rule-findings",
            params={"limit": 500},
            headers=_auth(),
        ).json()
        total = len(complete["data"]["findings"])
        expected_legacy_types = {"findings": list, "summary": dict}

        assert total > 1
        assert all(
            key in complete["data"]
            and isinstance(complete["data"][key], expected_type)
            for key, expected_type in expected_legacy_types.items()
        )
        assert complete["data"]["coverage"] == {
            "total": total,
            "returned": total,
            "truncated": False,
        }
        assert "warnings" not in complete

        first = client.get(
            "/api/v1/network/rule-findings",
            params={"limit": 1, "offset": 0},
            headers=_auth(),
        ).json()
        second = client.get(
            "/api/v1/network/rule-findings",
            params={"limit": 1, "offset": 1},
            headers=_auth(),
        ).json()

        assert first["data"]["coverage"] == {
            "total": total,
            "returned": 1,
            "truncated": True,
        }
        assert second["data"]["findings"] == complete["data"]["findings"][1:2]
        assert second["pagination"]["next_offset"] == 2
        assert any(
            f"Showing 1 of {total} rule findings" in warning
            for warning in first["warnings"]
        )


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
    def test_read_additively_publishes_the_rule_engine_contract(self, tmp_path):
        client = _client(tmp_path, network_policy_store=NetworkDesignPolicyStore())
        data = client.get("/api/v1/network/policy", headers=_auth()).json()["data"]
        legacy_types = {
            "name": str,
            "description": str,
            "is_declared": bool,
            "source_path": str,
            "hub_vnet_names": list,
            "require_firewall_in_hub": bool,
            "require_default_route_to_firewall": bool,
            "require_nsg_on_every_subnet": bool,
            "forbid_spoke_to_spoke_peering": bool,
            "forbid_public_ip_on_spoke_nics": bool,
            "require_private_endpoint_for_services": list,
            "require_private_dns_zone_link": bool,
            "require_bidirectional_peering": bool,
            "approved_peerings": list,
            "exempt_subnet_names": list,
            "exempt_vnet_names": list,
            "rules": list,
            "rules_declared": bool,
            "unevaluated_rule_ids": list,
            "invalid_rule_ids": list,
        }

        assert all(
            key in data and isinstance(data[key], expected_type)
            for key, expected_type in legacy_types.items()
        )
        assert data["supported_targets"] == list(SUPPORTED_TARGET_NAMES)
        assert data["supported_operators"] == list(SUPPORTED_OPERATORS)

    def test_malformed_declarative_rule_is_rejected_without_persisting(self, tmp_path):
        store = NetworkDesignPolicyStore()
        client = _client(tmp_path, network_policy_store=store)
        before_revision = store.revision

        response = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={
                "rules": [
                    {
                        "rule_id": "unsafe-expression",
                        "name": "Unsafe expression",
                        "parameters": {
                            "target": "subnets",
                            "assert": [{"field": "name", "eval": "resource.name"}],
                        },
                    }
                ]
            },
        )

        assert response.status_code == 400
        assert "no supported operator" in response.json()["error"]["message"]
        assert store.revision == before_revision
        assert store.read().rule("unsafe-expression") is None

    def test_valid_declarative_rule_previews_then_saves(self, tmp_path):
        store = NetworkDesignPolicyStore()
        client = _client(tmp_path, network_policy_store=store)
        rule = {
            "rule_id": "subnets-need-vnet",
            "name": "Subnets require a VNet",
            "category": "custom",
            "severity": "medium",
            "enabled": True,
            "parameters": {
                "target": "subnets",
                "assert": [{"field": "vnet_id", "exists": True}],
            },
        }

        preview = client.post(
            "/api/v1/network/policy/preview",
            headers=_auth(),
            json={"rules": [rule]},
        )
        assert preview.status_code == 200
        preview_rule = next(
            item
            for item in preview.json()["data"]["policy"]["rules"]
            if item["rule_id"] == rule["rule_id"]
        )
        assert preview_rule["declarative"] is True
        assert preview_rule["evaluated"] is True
        assert store.revision == 0
        assert store.read().rule(rule["rule_id"]) is None

        saved = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={"rules": [rule]},
        )
        assert saved.status_code == 200
        assert store.revision == 1
        assert store.read().rule(rule["rule_id"]) is not None

    @pytest.mark.parametrize("persistent", [False, True])
    def test_store_revision_increments_and_rejects_stale_writes(
        self, tmp_path, persistent
    ):
        documents = OneLakeDocumentStore(tmp_path / "documents") if persistent else None
        store = NetworkDesignPolicyStore(documents)

        assert store.revision == 0
        store.update({"description": "first"}, expected_revision=0)
        assert store.revision == 1
        store.update({"description": "second"}, expected_revision=1)
        assert store.revision == 2

        with pytest.raises(RuntimeError, match="revision"):
            store.update({"description": "stale"}, expected_revision=1)
        assert store.revision == 2
        assert store.read().description == "second"

    def test_write_invalidates_cached_derived_analysis(self, tmp_path):
        store = NetworkDesignPolicyStore()
        load_count = 0

        def load_network():
            nonlocal load_count
            load_count += 1
            return NetworkIntelligenceService.from_rows(
                network_rows(),
                policy=store.read(),
            )

        runtime = ProviderRuntime(
            {
                "network": ProviderSpec(
                    loader=load_network,
                    cache_key=lambda: ("network-policy", store.revision),
                )
            },
            refresh_interval_seconds=30,
            monotonic=lambda: 0.0,
        )
        client = _client(
            tmp_path,
            network_policy_store=store,
            provider_runtime=runtime,
        )

        before = client.get("/api/v1/network/gaps", headers=_auth())
        unchanged = client.get("/api/v1/network/gaps", headers=_auth())
        assert before.status_code == 200
        assert unchanged.status_code == 200
        assert load_count == 1
        assert any(
            gap["category"] == "dns_dependency_gap"
            for gap in before.json()["data"]["gaps"]
        )

        patched = client.patch(
            "/api/v1/network/policy",
            headers=_auth(),
            json={"require_private_dns_zone_link": False},
        )
        after = client.get("/api/v1/network/gaps", headers=_auth())

        assert patched.status_code == 200
        assert after.status_code == 200
        assert load_count == 2
        assert not any(
            gap["category"] == "dns_dependency_gap"
            for gap in after.json()["data"]["gaps"]
        )

    def test_revision_store_error_preserves_last_good_network_provider(self):
        now = [0.0]

        class FlakyRevisionDocuments:
            failing = False

            def read(self, name):
                if self.failing:
                    return {}
                return {"revision": 7, "policy": {}}

            def read_or_raise(self, name):
                if self.failing:
                    raise OSError("OneLake revision read failed")
                return {"revision": 7, "policy": {}}

        documents = FlakyRevisionDocuments()
        store = NetworkDesignPolicyStore(
            documents,
            revision_cache_seconds=1.0,
            monotonic=lambda: now[0],
        )
        loaded = object()
        load_count = 0

        def load_network():
            nonlocal load_count
            load_count += 1
            store.read()
            return loaded

        runtime = ProviderRuntime(
            {
                "network": ProviderSpec(
                    loader=load_network,
                    cache_key=lambda: (
                        "network-policy",
                        store.revision_or_raise(),
                    ),
                )
            },
            refresh_interval_seconds=30,
            monotonic=lambda: 0.0,
        )
        runtime.refresh(force=True)
        documents.failing = True
        now[0] = 2.0

        assert runtime.get("network") is loaded
        assert store.revision == 7
        assert load_count == 1

    def test_policy_body_error_preserves_last_good_network_provider(self):
        class FlakyPolicyDocuments:
            failing = False

            def read(self, name):
                del name
                return {}

            def read_or_raise(self, name):
                del name
                if self.failing:
                    raise OSError("OneLake policy body read failed")
                return {
                    "revision": 7,
                    "policy": {"description": "governed"},
                }

        documents = FlakyPolicyDocuments()
        store = NetworkDesignPolicyStore(
            documents,
            revision_cache_seconds=60.0,
            monotonic=lambda: 0.0,
        )

        def load_network():
            policy, _revision = store.read_with_revision_or_raise()
            return NetworkIntelligenceService(
                NetworkSnapshot(),
                policy=policy,
            )

        runtime = ProviderRuntime(
            {
                "network": ProviderSpec(
                    loader=load_network,
                    cache_key=lambda: (
                        "network-policy",
                        store.revision_or_raise(),
                    ),
                )
            },
            monotonic=lambda: 0.0,
        )
        runtime.refresh(force=True)
        first = runtime.get("network")
        documents.failing = True

        health = runtime.refresh(force=True)

        assert runtime.get("network") is first
        assert runtime.get("network").policy.description == "governed"
        assert health["providers"]["network"]["state"] == "degraded"

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

    def test_policy_preview_preserves_full_derivation_context(
        self, tmp_path, monkeypatch
    ):
        import api.routers.network as network_router

        flow_observation = {
            "subject_id": PROD_VNET,
            "object_id": f"{PROD_VNET}/subnets/snet-app",
            "predicate": "trafficObserved",
            "attributes": {"dataSource": "traffic_analytics"},
        }
        peer_resolutions = {"/subscriptions/peer/vnets/remote": "not_ingested"}
        base = build_service(network_rows())
        service = NetworkIntelligenceService(
            base.snapshot,
            policy=base.policy,
            semantic_relationships=(flow_observation,),
            flow_observations=(flow_observation,),
            peer_resolutions=peer_resolutions,
        )
        captured: list[dict[str, object]] = []
        original_service = NetworkIntelligenceService

        class RecordingService(original_service):
            def __init__(
                self,
                *args,
                flow_observations=None,
                peer_resolutions=None,
                **kwargs,
            ):
                captured.append(
                    {
                        "flow_observations": tuple(flow_observations or ()),
                        "peer_resolutions": dict(peer_resolutions or {}),
                    }
                )
                super().__init__(
                    *args,
                    flow_observations=flow_observations,
                    peer_resolutions=peer_resolutions,
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
            network_service=service,
        )

        response = client.post(
            "/api/v1/network/policy/preview",
            headers=_auth(),
            json={"rules": []},
        )

        assert response.status_code == 200
        assert captured[-1] == {
            "flow_observations": (flow_observation,),
            "peer_resolutions": peer_resolutions,
        }

    def test_rule_findings_evidence_reflects_analyzed_flow_logs(self, tmp_path):
        flow_observation = {
            "subject_id": PROD_VNET,
            "object_id": f"{PROD_VNET}/subnets/snet-app",
            "predicate": "trafficObserved",
            "attributes": {"dataSource": "traffic_analytics"},
        }
        base = build_service(network_rows())
        service = NetworkIntelligenceService(
            base.snapshot,
            policy=base.policy,
            semantic_relationships=(flow_observation,),
            flow_observations=(flow_observation,),
        )
        client = _client(tmp_path, network_service=service)

        response = client.get("/api/v1/network/rule-findings", headers=_auth())

        assert response.status_code == 200
        assert response.json()["evidence"][0]["confidence"] == "high"

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
