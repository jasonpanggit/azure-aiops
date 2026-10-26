"""Offline expected-output corpus for the three opt-in network scenarios."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.scope import Scope
from network.design import NetworkDesignPolicy, PolicyRule
from network.models import (
    NetworkSecurityGroup,
    NetworkSecurityRule,
    NetworkSnapshot,
    PrivateDnsZone,
    PrivateEndpoint,
    PrivateLinkResource,
    Subnet,
    VNet,
    VNetPeering,
)
from network.service import NetworkIntelligenceService
from operations.orchestration_contract import EvidenceSnapshotV2, SnapshotCoverage
from operations.orchestration_service import deterministic_network_claims
from operations.tools import call_tool

PRIVATE = "design-review-private-access"
PEERING = "design-review-peering-integrity"
NSG = "design-review-nsg-exposure"
NOW = datetime.now(UTC).isoformat()


def fixture_service():
    """Return a sanitized, deliberately divergent reviewed design."""
    policy = NetworkDesignPolicy(
        name="reviewed-fixture",
        rules=(
            PolicyRule(
                PRIVATE,
                "Private access",
                parameters={
                    "resource_types": ["microsoft.storage/storageaccounts"],
                },
            ),
            PolicyRule(PEERING, "Peering integrity"),
            PolicyRule(
                NSG,
                "No internet inbound",
                parameters={
                    "categories": ["internet_inbound"],
                    "directions": ["Inbound"],
                },
            ),
        ),
    )
    snapshot = NetworkSnapshot(
        observed_at=NOW,
        private_link_resources=(
            PrivateLinkResource(
                "/storage",
                "store",
                subscription_id="sub-a",
                resource_type="microsoft.storage/storageaccounts",
                public_network_access="Enabled",
            ),
        ),
        private_endpoints=(
            PrivateEndpoint(
                "/endpoint",
                "endpoint",
                subscription_id="sub-a",
                target_resource_id="/storage",
                connection_state="Approved",
            ),
        ),
        vnets=(
            VNet(
                "/hub", "hub", subscription_id="sub-a", address_spaces=("10.0.0.0/16",)
            ),
            VNet(
                "/spoke",
                "spoke",
                subscription_id="sub-b",
                address_spaces=("10.0.1.0/24",),
            ),
        ),
        peerings=(
            VNetPeering(
                "/hub/peer",
                "hub-to-spoke",
                subscription_id="sub-a",
                local_vnet_id="/hub",
                remote_vnet_id="/spoke",
                peering_state="Connected",
                allow_gateway_transit=True,
            ),
            VNetPeering(
                "/spoke/peer",
                "spoke-to-hub",
                subscription_id="sub-b",
                local_vnet_id="/spoke",
                remote_vnet_id="/hub",
                peering_state="Connected",
                use_remote_gateways=True,
            ),
        ),
        nsgs=(
            NetworkSecurityGroup(
                "/nsg",
                "nsg",
                subscription_id="sub-a",
                rules=(
                    NetworkSecurityRule(
                        "/nsg/allow",
                        "ssh",
                        nsg_id="/nsg",
                        priority=200,
                        source_address="Internet",
                        destination_port="22",
                        protocol="Tcp",
                    ),
                ),
            ),
        ),
    )
    return NetworkIntelligenceService(snapshot, policy=policy)


def review(service, scope=None):
    context = SimpleNamespace(
        provider_runtime=None,
        hybrid_network_provider=None,
        resolve_provider=lambda name: service if name == "network" else None,
    )
    return call_tool(
        "firewall_nsg_gaps",
        {"category": "design_review"},
        context=context,
        scope=scope or Scope(),
    )


def test_exact_reviewed_fixture_findings_and_no_gateway_symmetry_false_positive():
    result = review(fixture_service())
    assert result.status == "ok"
    data = result.data
    assert {(row["scenario_id"], row["check_id"]) for row in data["gaps"]} == {
        (PRIVATE, "public_access_enabled"),
        (PEERING, "address_overlap"),
        (NSG, "internet_inbound"),
    }
    assert data["design_review"]["version"] == "1"
    assert data["design_review"]["coverage"]["acquisition_complete"] is None
    assert data["design_review"]["coverage"]["complete"] is False
    assert data["design_review"]["unknown_count"] > 0  # DNS not demonstrated.
    assert result.evidence
    assert all(row["policy_id"] and row["evidence_refs"] for row in data["gaps"])


def test_undeclared_policy_is_unknown_not_default_best_practice_violation():
    service = fixture_service()
    service.policy = NetworkDesignPolicy()
    result = review(service)
    assert result.status == "ok"
    assert result.data["gaps"] == []
    assert result.data["design_review"]["unknown_count"] == 3
    assert "unknown" in result.data["design_review"]["summary"].lower()


def test_missing_settings_and_endpoint_approval_are_unknown_not_violations():
    service = fixture_service()
    service.snapshot = replace(
        service.snapshot,
        private_link_resources=(
            replace(
                service.snapshot.private_link_resources[0], public_network_access=""
            ),
        ),
        private_endpoints=(
            replace(service.snapshot.private_endpoints[0], connection_state=""),
        ),
    )
    result = review(service)
    assert not any(row["scenario_id"] == PRIVATE for row in result.data["gaps"])
    checks = result.data["design_review"]["assessments"]
    assert any(
        row["check_id"] == "public_access_unknown" and row["status"] == "unknown"
        for row in checks
    )
    assert any(row["check_id"] == "endpoint_approval_unknown" for row in checks)


def test_scope_excludes_remote_identity_and_retains_unknown_dependency():
    result = review(fixture_service(), Scope.from_mapping({"subscription": ["sub-a"]}))
    serialized = str(result.to_dict())
    assert "/spoke" not in serialized
    assert "sub-b" not in serialized
    assert any(
        row["check_id"] == "peer_coverage_unknown"
        for row in result.data["design_review"]["assessments"]
    )
    assert not any(row["check_id"] == "address_overlap" for row in result.data["gaps"])


def test_nsg_priority_direction_and_source_port_are_respected():
    service = fixture_service()
    nsg = service.snapshot.nsgs[0]
    allow = nsg.rules[0]
    deny = replace(
        allow, resource_id="/nsg/deny", name="deny", access="Deny", priority=100
    )
    service.snapshot = replace(
        service.snapshot, nsgs=(replace(nsg, rules=(deny, allow)),)
    )
    assert not any(row["scenario_id"] == NSG for row in review(service).data["gaps"])
    service.snapshot = replace(
        service.snapshot,
        nsgs=(
            replace(
                nsg,
                rules=(
                    replace(deny, source_port="443"),
                    allow,
                ),
            ),
        ),
    )
    assert any(row["scenario_id"] == NSG for row in review(service).data["gaps"])
    service.snapshot = replace(
        service.snapshot,
        nsgs=(replace(nsg, rules=(replace(allow, direction="Outbound"),)),),
    )
    assert not any(row["scenario_id"] == NSG for row in review(service).data["gaps"])


def test_deterministic_synthesis_cites_tool_and_keeps_unknowns_without_foundry():
    result = review(fixture_service())
    claims = deterministic_network_claims(
        snapshot=EvidenceSnapshotV2(
            page_kind="network",
            page_id="network-topology",
            coverage=SnapshotCoverage(visible_count=1, total_count=1, complete=True),
        ),
        tool_results=[
            {
                **result.to_dict(),
                "tool": "firewall_nsg_gaps",
                "call_id": "review",
            }
        ],
    )
    assert claims
    assert claims[0]["evidence_refs"] == ["tool:review:0"]
    assert "unknown" in claims[0]["summary"].lower()
    assert "reachability" in claims[0]["summary"].lower()
    assert claims[0]["uncertainty"]


@pytest.mark.parametrize(
    "expiry,expected",
    [
        ("2999-01-01T00:00:00Z", "excepted"),
        ("2000-01-01T00:00:00Z", "violation"),
    ],
)
def test_reviewed_exceptions_require_identity_reference_and_unexpired_window(
    expiry, expected
):
    service = fixture_service()
    rule = service.policy.rules[0]
    rule = replace(
        rule,
        parameters={
            **rule.parameters,
            "exceptions": [
                {
                    "resource_id": "/storage",
                    "reference": "review-ticket-42",
                    "expires_at": expiry,
                }
            ],
        },
    )
    service.policy = replace(service.policy, rules=(rule, *service.policy.rules[1:]))
    result = review(service)
    row = next(
        row
        for row in result.data["design_review"]["assessments"]
        if row["check_id"] == "public_access_enabled"
    )
    assert row["status"] == expected
    assert row["exception_reference"] == "review-ticket-42"
    assert (row["exception_status"] == "active") == (expected == "excepted")
    assert row["underlying_status"] == "violation"


@pytest.mark.parametrize(
    "parameters",
    [
        {"resource_types": []},
        {"resource_types": "all"},
        {
            "resource_types": ["microsoft.storage/storageaccounts"],
            "exceptions": "ignore",
        },
        {
            "resource_types": ["microsoft.storage/storageaccounts"],
            "exceptions": [
                {
                    "resource_id": "/storage",
                    "reference": "ticket",
                    "expires_at": "not-a-time",
                }
            ],
        },
    ],
)
def test_invalid_private_policy_is_unknown_not_compliant(parameters):
    service = fixture_service()
    service.policy = replace(
        service.policy, rules=(replace(service.policy.rules[0], parameters=parameters),)
    )
    result = review(service)
    assert result.data["gaps"] == []
    assert any(
        row["check_id"] == "invalid_policy"
        for row in result.data["design_review"]["assessments"]
    )


@pytest.mark.parametrize(
    "observed_at,freshness", [("", "unknown"), ("2000-01-01T00:00:00Z", "stale")]
)
def test_stale_or_missing_snapshot_time_cannot_become_healthy(observed_at, freshness):
    service = fixture_service()
    service.snapshot = replace(service.snapshot, observed_at=observed_at)
    result = review(service)
    assert result.data["design_review"]["freshness"] == freshness
    assert result.data["design_review"]["coverage"]["complete"] is False
    assert len(result.data["gaps"]) == 3


def test_bounded_results_keep_exact_denominator_and_partial_disclosure():
    service = fixture_service()
    service.snapshot = replace(
        service.snapshot,
        private_link_resources=tuple(
            replace(
                service.snapshot.private_link_resources[0], resource_id=f"/storage-{i}"
            )
            for i in range(35)
        ),
    )
    result = review(service)
    assert len(result.data["gaps"]) == 25
    assert result.data["design_review"]["coverage"]["finding_count"] == 37
    assert result.data["design_review"]["coverage"]["complete"] is False
    assert "showing 25 of" in result.warning


@pytest.mark.parametrize("transit,expected", [(True, "observed"), (False, "violation")])
def test_gateway_transit_requires_complementary_remote_provider_flag(transit, expected):
    service = fixture_service()
    service.snapshot = replace(
        service.snapshot,
        peerings=(
            replace(service.snapshot.peerings[0], allow_gateway_transit=transit),
            service.snapshot.peerings[1],
        ),
    )
    rows = review(service).data["design_review"]["assessments"]
    spoke = next(
        row
        for row in rows
        if row["resource_id"] == "/spoke/peer" and row["check_id"] == "gateway_transit"
    )
    assert spoke["status"] == expected


def test_normalized_gateway_defaults_and_incomplete_nsg_rules_remain_unknown():
    from network.loader import load_network_snapshot

    service = fixture_service()
    normalized = load_network_snapshot(
        [
            {
                "id": "/hub/peer",
                "name": "peer",
                "entityType": "VNetPeering",
                "localVnetId": "/hub",
                "remoteVnetId": "/spoke",
                "peeringState": "Connected",
            },
            {
                "id": "/nsg/allow",
                "name": "incomplete",
                "entityType": "NetworkSecurityRule",
                "nsgId": "/nsg",
            },
            {"id": "/nsg", "name": "nsg", "entityType": "NetworkSecurityGroup"},
        ]
    )
    assert not normalized.peerings[0].gateway_flags_observed
    assert not normalized.nsgs[0].rules[0].configuration_observed
    assert "gateway_flags_observed" not in normalized.peerings[0].to_dict()
    assert "configuration_observed" not in normalized.nsgs[0].rules[0].to_dict()
    service.snapshot = replace(
        service.snapshot,
        peerings=(
            normalized.peerings[0],
            service.snapshot.peerings[1],
        ),
        nsgs=normalized.nsgs,
    )
    result = review(service)
    checks = {row["check_id"] for row in result.data["design_review"]["assessments"]}
    assert {"gateway_flags_unknown", "nsg_rule_evidence_unknown"} <= checks
    assert not any(row["scenario_id"] == NSG for row in result.data["gaps"])


def test_arg_service_public_setting_reuses_existing_normalization_path():
    service = fixture_service()
    projected = NetworkIntelligenceService.from_arg_rows(
        [
            {
                "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/store",
                "name": "store",
                "type": "microsoft.storage/storageaccounts",
                "subscriptionId": "sub-a",
                "resourceGroup": "rg",
                "properties": {"publicNetworkAccess": "Enabled"},
            }
        ],
        policy=service.policy,
        observed_at=NOW,
    )
    assert (
        projected.snapshot.private_link_resources[0].public_network_access == "Enabled"
    )
    assert any(
        row["check_id"] == "public_access_enabled"
        for row in review(projected).data["gaps"]
    )


def test_unavailable_provider_is_not_an_empty_assessment():
    assert review(None).status == "unavailable"


def test_scenario_contract_reuses_locked_read_only_network_grants():
    from operations.mcp_server import validate_tool_arguments
    from operations.network_scenarios import NETWORK_DESIGN_REVIEW
    from operations.specialist_manifest import load_specialist_manifest

    manifest = load_specialist_manifest()
    owner = manifest.require(NETWORK_DESIGN_REVIEW["owner"])
    assert owner.read_only
    assert set(NETWORK_DESIGN_REVIEW["allowed_tools"]) <= set(
        owner.operations_tools_for_page("network")
    )
    assert validate_tool_arguments("firewall_nsg_gaps", {"category": "design_review"})[
        0
    ] == {"category": "design_review"}


@pytest.mark.parametrize("hinted", [True, False])
def test_canonical_api_runs_one_scoped_review_and_preserves_fallback(
    tmp_path, monkeypatch, hinted
):
    from fastapi.testclient import TestClient
    from test_api_copilot_investigation import HEADERS, _context

    from api.app import create_app
    from tests.copilot_authorization_fixtures import enable_authorized_canary

    enable_authorized_canary(monkeypatch)
    context = _context(tmp_path, None)
    calls = []

    def provider():
        calls.append("network")
        return fixture_service()

    context.network_provider = provider
    response = TestClient(create_app(context), raise_server_exceptions=False).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json={
            "contract_version": "1",
            "question": "Review network design",
            "requested_scope": {"subscription": ["sub-a"]},
            "snapshot": {
                "version": "2",
                "page_kind": "network",
                "page_id": "network-topology",
                "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
                "evidence": [],
            },
            **(
                {
                    "hint": {
                        "specialist_id": "network",
                        "tool": "firewall_nsg_gaps",
                        "arguments": {"category": "design_review"},
                    }
                }
                if hinted
                else {}
            ),
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert calls == ["network"]
    assert data["selected_tools"] == ["firewall_nsg_gaps"]
    assert data["tool_results"][0]["arguments"] == {"category": "design_review"}
    assert data["tool_results"][0]["data"]["design_review"]["unknown_count"] > 0
    assert data["synthesis"]["mode"] == "deterministic"
    assert data["synthesis"]["status"] != "synthesized"
    assert "unknown" in data["synthesis"]["claims"][0]["summary"]
    assert data["synthesis"]["claims"][0]["evidence_refs"]
    assert "/spoke" not in response.text


@pytest.mark.parametrize("mode", ["valid", "foreign_citation", "invented_policy_field"])
def test_optional_narrator_receives_bounded_policy_context_and_cannot_drop_facts(mode):
    import json

    from operations.foundry_agent import AgentAnswer
    from operations.orchestration_service import OrchestrationService

    result = review(fixture_service())

    class Narrator:
        def answer(self, *, context, **kwargs):
            assert context["network_design_review"][0]["policy_version"]
            assert len(context["network_design_review"][0]["assessments"]) <= 25
            assert "complementary" in context["network_design_review_constraints"]
            claim = {
                "finding_id": "narration",
                "evidence_refs": ["tool:review:0"],
                "confidence": "medium",
                "uncertainty": ["Acquisition coverage unknown"],
                "freshness": "unknown",
                "actionable": False,
                "next_check": "Review the cited configuration.",
                "summary": "Prioritize the observed policy findings; coverage remains unknown.",
            }
            if mode == "foreign_citation":
                claim["evidence_refs"] = ["invented:source"]
            elif mode == "invented_policy_field":
                claim["policy_id"] = "invented-policy"
            return AgentAnswer(
                text=json.dumps({"findings": [claim]}), agent_name="fixture-narrator"
            )

    synthesis = OrchestrationService(
        executive_agent=Narrator(),
        always_synthesize=True,
    )._synthesize(
        "Review network design",
        [{**result.to_dict(), "tool": "firewall_nsg_gaps", "call_id": "review"}],
        retained_evidence=[],
        current_retained_evidence=[
            {
                "evidence_id": "retained:legacy-heuristic",
                "source": "page_snapshot:network:network/gaps",
                "status": "ok",
                "claim_type": "network_gap",
                "observation_status": "current",
                "data": {
                    "issue": "Legacy heuristic must not replace explicit policy review."
                },
            }
        ],
        snapshot=EvidenceSnapshotV2(
            page_kind="network",
            page_id="network-topology",
            coverage=SnapshotCoverage(visible_count=0, total_count=0, complete=False),
        ),
    )
    assert synthesis.claims[0]["summary"].startswith("Network design review v1:")
    assert synthesis.claims[0]["evidence_refs"] == ["tool:review:0"]
    if mode == "valid":
        assert synthesis.status == "synthesized"
        assert synthesis.mode == "foundry"
    else:
        assert synthesis.status == "degraded"
        assert synthesis.degraded_reason == "response_contract"


def test_disabled_policy_and_observed_private_dns_do_not_claim_compliance():
    service = fixture_service()
    service.policy = replace(
        service.policy,
        rules=(
            replace(service.policy.rules[0], enabled=False),
            *service.policy.rules[1:],
        ),
    )
    assert not any(
        row["scenario_id"] == PRIVATE for row in review(service).data["gaps"]
    )
    service = fixture_service()
    service.snapshot = replace(
        service.snapshot,
        private_link_resources=(
            replace(
                service.snapshot.private_link_resources[0],
                public_network_access="Disabled",
            ),
        ),
        private_endpoints=(
            replace(
                service.snapshot.private_endpoints[0],
                subnet_id="/subnet",
                private_dns_zone_ids=("/zone",),
            ),
        ),
        subnets=(Subnet("/subnet", "subnet", vnet_id="/hub"),),
        private_dns_zones=(PrivateDnsZone("/zone", "zone", linked_vnet_ids=("/hub",)),),
    )
    result = review(service)
    assert not any(row["scenario_id"] == PRIVATE for row in result.data["gaps"])
    row = next(
        row
        for row in result.data["design_review"]["assessments"]
        if row["check_id"] == "dns_binding_observed"
    )
    assert row["status"] == "observed"
    assert "not demonstrated" in row["detail"]
    assert result.data["design_review"]["coverage"]["complete"] is False


def test_foreign_tool_is_denied_before_handler_and_only_review_fallback_runs(
    monkeypatch,
):
    from operations.orchestration_contract import (
        COVERAGE_CITATION_ID,
        CandidatePlan,
        InvestigationRequest,
        SpecialistStep,
        ToolCallCandidate,
    )
    from operations.orchestration_service import OrchestrationService
    from tests.copilot_authorization_fixtures import (
        install_valid_canary_evidence,
        route_authority_for_test,
    )

    install_valid_canary_evidence(monkeypatch)
    request = InvestigationRequest(
        question="Review network design",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="network",
            page_id="network-topology",
            coverage=SnapshotCoverage(visible_count=0, total_count=0, complete=False),
        ),
    )
    candidate = CandidatePlan(
        steps=[
            SpecialistStep(
                specialist_id="network",
                tool_calls=[
                    ToolCallCandidate(
                        tool="cve_exposure",
                        arguments={},
                        citation_ids=[COVERAGE_CITATION_ID],
                    )
                ],
            )
        ]
    )
    calls = []
    service = fixture_service()
    context = SimpleNamespace(
        provider_runtime=None,
        hybrid_network_provider=None,
        resolve_provider=lambda _: service,
    )

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return call_tool(name, arguments, context=context, scope=scope)

    result = OrchestrationService(
        planner=lambda _: candidate,
        executor=execute,
    ).execute(
        request,
        context=context,
        principal_subject="offline-reviewer",
        effective_scope=Scope.from_mapping({"subscription": ["sub-a"]}),
        route_authority=route_authority_for_test(request),
    )
    assert result.fallback_reason == "candidate_rejected:tool_not_granted"
    assert calls == ["firewall_nsg_gaps"]
    assert result.tool_results[0]["arguments"] == {"category": "design_review"}
