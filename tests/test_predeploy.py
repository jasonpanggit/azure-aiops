"""Tests for the change risk and pre-deployment impact engine.

Two properties get the most attention here because they are the ones whose
violation would be actively harmful rather than merely wrong:

* **Scope isolation** — a scoped principal must never learn about a resource
  outside its grant, including indirectly through an aggregate count, a
  business-service name, or a blast-radius roll-up.
* **No unsupported causal claims** — the engine assesses a change that has not
  happened yet. Nothing it emits may assert that an impact *will* occur or that
  a change *caused* anything.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.evidence import CONFIDENCE_HIGH, CONFIDENCE_LOW, CONFIDENCE_UNKNOWN
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.predeploy import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_REPLACE,
    ACTION_UPDATE,
    FINDING_MISSING_TARGET,
    FINDING_UNMANAGED_DRIFT,
    FINDING_UNTRACKED_CREATE,
    VERDICT_APPROVE,
    VERDICT_APPROVE_WITH_CONDITIONS,
    VERDICT_REQUIRE_REVIEW,
    DiscoveredResource,
    PreDeploymentImpactService,
    analyze_blast_radius,
    compare_states,
    ingest,
    parse_arm_diff,
    parse_azure_devops_change,
    parse_bicep_what_if,
    parse_github_pull_request,
    parse_terraform_plan,
    simulate,
)
from onboarding.service import SubscriptionOnboardingService

ADMIN_TOKEN = "admin-token-0123456789"
SCOPED_TOKEN = "scoped-token-0123456789"

NSG_A = "/subscriptions/sub-a/rg/net/providers/Microsoft.Network/networkSecurityGroups/web"
VM_A = "/subscriptions/sub-a/rg/net/providers/Microsoft.Compute/virtualMachines/vm-a"
APP_A = "/subscriptions/sub-a/rg/net/providers/Microsoft.Web/sites/portal"
SQL_B = "/subscriptions/sub-b/rg/data/providers/Microsoft.Sql/servers/finance"


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _discovered() -> list[DiscoveredResource]:
    """A two-subscription estate with a three-deep dependency chain in sub-a."""
    return [
        DiscoveredResource(
            resource_id=NSG_A,
            resource_type="Microsoft.Network/networkSecurityGroups",
            name="web",
            application="Portal",
            business_service="Customer Portal",
            environment="production",
            subscription="sub-a",
            owner="network-team",
            support_team="noc",
            region="australiaeast",
            criticality="critical",
            properties={"nsg_rules": ["allow-https"]},
            observed_at="2026-01-15T00:00:00+00:00",
        ),
        DiscoveredResource(
            resource_id=VM_A,
            resource_type="Microsoft.Compute/virtualMachines",
            name="vm-a",
            application="Portal",
            business_service="Customer Portal",
            environment="production",
            subscription="sub-a",
            owner="app-team",
            depends_on=(NSG_A,),
            observed_at="2026-01-15T00:00:00+00:00",
        ),
        DiscoveredResource(
            resource_id=APP_A,
            resource_type="Microsoft.Web/sites",
            name="portal",
            application="Portal",
            business_service="Customer Portal",
            environment="production",
            subscription="sub-a",
            depends_on=(VM_A,),
            observed_at="2026-01-15T00:00:00+00:00",
        ),
        DiscoveredResource(
            resource_id=SQL_B,
            resource_type="Microsoft.Sql/servers",
            name="finance",
            application="Finance",
            business_service="Finance Ledger",
            environment="production",
            subscription="sub-b",
            owner="finance-dba",
            criticality="critical",
            observed_at="2026-01-15T00:00:00+00:00",
        ),
    ]


def _terraform_plan(
    *,
    resource_id: str = NSG_A,
    actions: list[str] | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> dict:
    return {
        "terraform_version": "1.9.0",
        "resource_changes": [
            {
                "address": "azurerm_network_security_group.web",
                "type": "azurerm_network_security_group",
                "name": "web",
                "provider_name": "registry.terraform.io/hashicorp/azurerm",
                "change": {
                    "actions": actions or ["update"],
                    "before": {"id": resource_id, **(before or {})},
                    "after": {"id": resource_id, **(after or {})},
                },
            }
        ],
    }


# --------------------------------------------------------------------------
# Deliverable 1: ingestion
# --------------------------------------------------------------------------


def test_terraform_plan_normalizes_actions_and_ids():
    change = parse_terraform_plan(_terraform_plan())
    assert len(change.resource_changes) == 1
    item = change.resource_changes[0]
    assert item.action == ACTION_UPDATE
    assert item.resource_id == NSG_A
    assert item.address == "azurerm_network_security_group.web"
    assert change.target_subscriptions == ("sub-a",)


def test_terraform_delete_create_pair_is_one_replace():
    """A replace is destroy+create; reading it as two changes would double-count."""
    change = parse_terraform_plan(_terraform_plan(actions=["delete", "create"]))
    assert change.resource_changes[0].action == ACTION_REPLACE
    assert change.resource_changes[0].is_destructive


def test_terraform_after_unknown_becomes_a_declared_warning():
    plan = _terraform_plan()
    plan["resource_changes"][0]["change"]["after_unknown"] = {"subnet_id": True}
    change = parse_terraform_plan(plan)
    assert "subnet_id" in change.resource_changes[0].changed_properties
    assert any("unknown until apply" in warning for warning in change.ingestion_warnings)


def test_bicep_what_if_maps_change_types():
    change = parse_bicep_what_if(
        {
            "changes": [
                {
                    "resourceId": NSG_A,
                    "changeType": "Modify",
                    "delta": [{"path": "properties.securityRules"}],
                },
                {"resourceId": VM_A, "changeType": "Create"},
                {"resourceId": SQL_B, "changeType": "NoChange"},
            ]
        }
    )
    actions = {item.resource_id: item.action for item in change.resource_changes}
    assert actions[NSG_A] == ACTION_UPDATE
    assert actions[VM_A] == ACTION_CREATE
    # No-ops are parsed but excluded from the effective set.
    assert all(item.resource_id != SQL_B for item in change.effective_changes)


def test_arm_diff_reports_its_own_source():
    change = parse_arm_diff({"changes": [{"resourceId": NSG_A, "changeType": "Delete"}]})
    assert change.source == "arm_diff"
    assert change.resource_changes[0].action == ACTION_DELETE


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (
            parse_github_pull_request,
            {
                "number": 42,
                "title": "Open SSH",
                "user": {"login": "dev"},
                "files": [{"filename": "infra/net.tf"}, {"filename": "README.md"}],
            },
        ),
        (
            parse_azure_devops_change,
            {
                "pullRequestId": 42,
                "title": "Open SSH",
                "createdBy": {"displayName": "dev"},
                "changes": [{"item": {"path": "infra/net.tf"}}, {"item": {"path": "README.md"}}],
            },
        ),
    ],
)
def test_code_review_sources_filter_to_iac_and_always_warn(parser, payload):
    """File-level review data cannot yield resource-level state, and must say so."""
    change = parser(payload)
    assert len(change.resource_changes) == 1
    assert change.resource_changes[0].address.endswith("net.tf")
    assert change.ingestion_warnings, "code-review ingestion must declare its limits"


def test_ingest_rejects_an_unsupported_source():
    with pytest.raises(ValueError):
        ingest("carrier_pigeon", {})


def test_the_package_imports_without_the_api_package_loaded_first():
    """Regression: the engine imports api.scope, and api imports this router."""
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [_sys.executable, "-c", "import intelligence.predeploy"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# Deliverable 2: desired versus discovered
# --------------------------------------------------------------------------


def test_update_of_an_unknown_resource_is_a_missing_target():
    change = parse_terraform_plan(_terraform_plan(resource_id=SQL_B))
    result = compare_states(change, [r for r in _discovered() if r.subscription == "sub-a"])
    assert result["counts"][FINDING_MISSING_TARGET] == 1


def test_discovered_state_differing_from_plan_before_is_drift():
    change = parse_terraform_plan(
        _terraform_plan(before={"nsg_rules": ["allow-ssh"]}, after={"nsg_rules": []})
    )
    result = compare_states(change, _discovered())
    assert result["counts"][FINDING_UNMANAGED_DRIFT] == 1
    assert "nsg_rules" in result["comparisons"][0]["drifted_properties"]


def test_creating_an_existing_resource_is_flagged():
    change = parse_terraform_plan(_terraform_plan(actions=["create"]))
    result = compare_states(change, _discovered())
    assert result["counts"][FINDING_UNTRACKED_CREATE] == 1


def test_absent_properties_are_not_treated_as_drift():
    """A property the projection does not report is unobserved, not different."""
    change = parse_terraform_plan(_terraform_plan(before={"unobserved": "x"}, after={"unobserved": "y"}))
    result = compare_states(change, _discovered())
    assert result["counts"].get(FINDING_UNMANAGED_DRIFT, 0) == 0


# --------------------------------------------------------------------------
# Deliverable 3: blast radius
# --------------------------------------------------------------------------


def test_blast_radius_walks_transitive_dependents():
    change = parse_terraform_plan(_terraform_plan())
    result = analyze_blast_radius(change, _discovered())
    ids = {row["resource_id"] for row in result["impacted_resources"]}
    assert ids == {NSG_A, VM_A, APP_A}
    assert result["business_services"] == ["Customer Portal"]
    assert result["directly_changed_count"] == 1


def test_blast_radius_depth_bound_truncates_and_says_so():
    change = parse_terraform_plan(_terraform_plan())
    result = analyze_blast_radius(change, _discovered(), max_depth=1)
    ids = {row["resource_id"] for row in result["impacted_resources"]}
    assert ids == {NSG_A, VM_A}
    assert result["truncated"] is True
    assert any("Traversal stopped" in unknown for unknown in result["unknowns"])


def test_blast_radius_never_asserts_confirmed_impact():
    result = analyze_blast_radius(parse_terraform_plan(_terraform_plan()), _discovered())
    assert result["confirmed_impact"] is False
    assert "not a prediction" in result["interpretation"]


# --------------------------------------------------------------------------
# Deliverable 5: simulation
# --------------------------------------------------------------------------


def test_nsg_rule_opening_ssh_to_the_internet_is_high_severity():
    change = parse_terraform_plan(
        _terraform_plan(
            before={"security_rule": [{"name": "allow-https"}]},
            after={
                "security_rule": [
                    {
                        "name": "allow-ssh",
                        "access": "Allow",
                        "direction": "Inbound",
                        "source_address_prefix": "Internet",
                        "destination_port_range": "22",
                    }
                ]
            },
        )
    )
    result = simulate(change)
    effects = {effect["effect"] for effect in result["effects"]}
    assert "internet_inbound_exposure" in effects
    assert result["highest_severity"] == "high"


def test_removing_a_route_predicts_fallback_and_asks_for_validation():
    change = parse_terraform_plan(
        {
            "resource_changes": [
                {
                    "address": "azurerm_route_table.hub",
                    "type": "azurerm_route_table",
                    "change": {
                        "actions": ["update"],
                        "before": {"id": NSG_A, "routes": [{"name": "to-onprem"}]},
                        "after": {"id": NSG_A, "routes": []},
                    },
                }
            ]
        }
    )
    result = simulate(change)
    removed = [e for e in result["effects"] if e["effect"] == "routes_removed"]
    assert removed and removed[0]["requires_validation"]


def test_simulation_states_it_did_not_observe_runtime_behaviour():
    result = simulate(parse_terraform_plan(_terraform_plan()))
    assert result["confirmed_outcome"] is False
    assert result["basis"] == "declared_configuration"
    assert "No live traffic" in result["interpretation"]


def test_unclassified_resources_are_declared_not_silently_dropped():
    change = parse_terraform_plan(
        {
            "resource_changes": [
                {
                    "address": "azurerm_mystery.thing",
                    "type": "azurerm_mystery",
                    "change": {"actions": ["update"], "before": {}, "after": {}},
                }
            ]
        }
    )
    result = simulate(change)
    assert result["unclassified_addresses"] == ["azurerm_mystery.thing"]
    assert result["unknowns"]


# --------------------------------------------------------------------------
# Deliverable 4 and 6: risk and CAB
# --------------------------------------------------------------------------


def _assess(plan: dict, *, discovered=None, scope: Scope | None = None) -> dict:
    return PreDeploymentImpactService().assess(
        source="terraform_plan",
        payload=plan,
        discovered=_discovered() if discovered is None else discovered,
        scope=scope,
    )


def test_a_clean_low_reach_change_is_confidently_assessed():
    assessment = _assess(_terraform_plan())
    assert assessment["risk"]["confidence"] == CONFIDENCE_HIGH
    assert assessment["risk"]["unknowns"] == []


def test_every_scored_factor_carries_its_evidence():
    """A change board must be able to see why each point was added."""
    assessment = _assess(_terraform_plan(actions=["delete", "create"]))
    scored = set(assessment["risk"]["contributing_factors"])
    evidenced = {item["factor"] for item in assessment["risk"]["evidence"]}
    assert scored <= evidenced


def test_confidence_collapses_when_no_discovered_state_exists():
    assessment = _assess(_terraform_plan(), discovered=[])
    assert assessment["risk"]["confidence"] == CONFIDENCE_UNKNOWN
    assert assessment["risk"]["unknowns"]
    # An unassessable change must escalate, never sail through on a low score.
    assert assessment["cab_recommendation"]["verdict"] == VERDICT_REQUIRE_REVIEW


def test_confidence_degrades_when_inputs_are_incomplete():
    """Partial visibility is assessable but must not be reported as reliable."""
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_network_security_group.web",
                "type": "azurerm_network_security_group",
                "change": {
                    "actions": ["update"],
                    "before": {"id": NSG_A},
                    "after": {"id": NSG_A},
                },
                "after_unknown": {"subnet_id": True},
            },
            {
                "address": "azurerm_mssql_server.finance",
                "type": "azurerm_mssql_server",
                "change": {
                    "actions": ["update"],
                    "before": {"id": SQL_B},
                    "after": {"id": SQL_B},
                },
            },
        ]
    }
    assessment = PreDeploymentImpactService(max_depth=1).assess(
        source="terraform_plan",
        payload=plan,
        discovered=[r for r in _discovered() if r.subscription == "sub-a"],
    )
    assert assessment["risk"]["confidence"] == CONFIDENCE_LOW
    assert assessment["risk"]["unknowns"]


def test_destructive_data_change_requires_review():
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_mssql_server.finance",
                "type": "azurerm_mssql_server",
                "change": {
                    "actions": ["delete"],
                    "before": {"id": SQL_B},
                    "after": {},
                },
            }
        ]
    }
    assessment = _assess(plan)
    cab = assessment["cab_recommendation"]
    assert cab["verdict"] == VERDICT_REQUIRE_REVIEW
    assert cab["conditions"], "a destructive data change must carry conditions"
    assert "change_advisory_board" in cab["required_approvals"]


def test_a_benign_isolated_change_can_be_approved():
    """Not every change escalates; otherwise the verdict carries no information."""
    isolated = [
        DiscoveredResource(
            resource_id=VM_A,
            resource_type="Microsoft.Compute/virtualMachines",
            name="vm-a",
            environment="development",
            subscription="sub-a",
            observed_at="2026-01-15T00:00:00+00:00",
        )
    ]
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_linux_virtual_machine.dev",
                "type": "azurerm_linux_virtual_machine",
                "change": {
                    "actions": ["update"],
                    "before": {"id": VM_A, "tags": {"a": "1"}},
                    "after": {"id": VM_A, "tags": {"a": "2"}},
                },
            }
        ]
    }
    assessment = _assess(plan, discovered=isolated)
    assert assessment["cab_recommendation"]["verdict"] == VERDICT_APPROVE


def test_business_service_impact_attaches_conditions_not_a_block():
    assessment = _assess(_terraform_plan())
    cab = assessment["cab_recommendation"]
    assert cab["verdict"] in {VERDICT_APPROVE_WITH_CONDITIONS, VERDICT_REQUIRE_REVIEW}
    assert any("Customer Portal" in condition for condition in cab["conditions"])


# --------------------------------------------------------------------------
# Deliverable 8: no unsupported causal claims
# --------------------------------------------------------------------------


def test_no_stage_claims_confirmed_causality():
    assessment = _assess(_terraform_plan(actions=["delete", "create"]))
    assert assessment["confirmed_cause"] is False
    assert assessment["risk"]["confirmed_cause"] is False
    assert assessment["cab_recommendation"]["confirmed_cause"] is False
    assert assessment["blast_radius"]["confirmed_impact"] is False
    assert assessment["simulation"]["confirmed_outcome"] is False


def test_narrative_text_never_asserts_a_change_will_break_something():
    """Guard the wording, not just the flags: prose is what a reviewer reads."""
    assessment = _assess(_terraform_plan(actions=["delete", "create"]))
    prose = " ".join(
        [
            assessment["risk"]["interpretation"],
            assessment["risk"]["justification"],
            assessment["blast_radius"]["interpretation"],
            assessment["simulation"]["interpretation"],
            assessment["cab_recommendation"]["interpretation"],
            assessment["cab_recommendation"]["summary"],
        ]
    ).casefold()
    for forbidden in ("will break", "will cause", "caused by", "will fail", "confirmed cause"):
        assert forbidden not in prose


def test_risk_score_is_not_presented_as_a_failure_probability():
    assessment = _assess(_terraform_plan())
    assert "not a probability of failure" in assessment["risk"]["interpretation"]


# --------------------------------------------------------------------------
# Deliverable 8: scope isolation
# --------------------------------------------------------------------------


def test_a_scoped_assessment_excludes_other_subscriptions_entirely():
    scope = Scope.from_mapping({"subscription": ["sub-a"]})
    assessment = _assess(_terraform_plan(), scope=scope)
    serialized = str(assessment)
    assert "sub-b" not in serialized
    assert "Finance Ledger" not in serialized
    assert "finance-dba" not in serialized


def test_a_change_outside_scope_yields_no_impacted_resources():
    scope = Scope.from_mapping({"subscription": ["sub-b"]})
    assessment = _assess(_terraform_plan(), scope=scope)
    assert assessment["blast_radius"]["total_impacted_count"] == 0
    assert assessment["scope_excluded_resource_count"] > 0
    assert assessment["risk"]["confidence"] == CONFIDENCE_UNKNOWN


def test_scope_filtering_does_not_leak_through_aggregate_counts():
    """The roll-ups are the subtle leak: a count can disclose an unseen resource."""
    scope = Scope.from_mapping({"subscription": ["sub-a"]})
    assessment = _assess(_terraform_plan(), scope=scope)
    blast_radius = assessment["blast_radius"]
    assert blast_radius["subscriptions"] == ["sub-a"]
    assert blast_radius["total_impacted_count"] == 3
    assert "Finance Ledger" not in blast_radius["business_services"]


def test_a_narrow_listing_does_not_return_a_wider_assessment():
    service = PreDeploymentImpactService()
    service.assess(source="terraform_plan", payload=_terraform_plan(), discovered=_discovered())
    narrow = Scope.from_mapping({"subscription": ["sub-b"]})
    assert service.list_assessments(scope=narrow) == []
    assert len(service.list_assessments()) == 1


def test_a_disjoint_scope_yields_nothing_rather_than_everything():
    """An unsatisfiable scope must fail closed."""
    scope = Scope.from_mapping({"subscription": ["sub-a"]}).intersect(
        Scope.from_mapping({"subscription": ["sub-b"]})
    )
    assert not scope.is_satisfiable()
    assessment = _assess(_terraform_plan(), scope=scope)
    assert assessment["blast_radius"]["total_impacted_count"] == 0


# --------------------------------------------------------------------------
# Deliverable 7: API surface
# --------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path) -> TestClient:
    principals = {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        SCOPED_TOKEN: Principal(
            subject="scoped@example.com",
            grants=(Grant("admin", Scope.from_mapping({"subscription": ["sub-b"]})),),
        ),
    }
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "hermes"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth(token: str = ADMIN_TOKEN) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_capabilities_route_advertises_supported_sources(client):
    response = client.get("/api/v1/changes/assessment-sources", headers=_auth())
    assert response.status_code == 200
    data = response.json()["data"]
    assert "terraform_plan" in data["sources"]
    assert "nsg" in data["simulation_domains"]


def test_assess_route_returns_a_full_assessment(client):
    response = client.post(
        "/api/v1/changes/assess",
        headers=_auth(),
        json={"source": "terraform_plan", "payload": _terraform_plan()},
    )
    assert response.status_code == 201
    body = response.json()
    data = body["data"]
    assert data["risk"]["level"]
    assert data["cab_recommendation"]["verdict"] in {
        VERDICT_APPROVE,
        VERDICT_APPROVE_WITH_CONDITIONS,
        VERDICT_REQUIRE_REVIEW,
    }
    assert body["evidence"][0]["source_engine"].endswith("PreDeploymentImpactService")


def test_assess_route_rejects_an_unknown_source(client):
    response = client.post(
        "/api/v1/changes/assess",
        headers=_auth(),
        json={"source": "carrier_pigeon", "payload": {}},
    )
    assert response.status_code == 400


def test_an_assessment_is_retrievable_after_submission(client):
    created = client.post(
        "/api/v1/changes/assess",
        headers=_auth(),
        json={"source": "terraform_plan", "payload": _terraform_plan()},
    ).json()["data"]
    listed = client.get("/api/v1/changes/assessments", headers=_auth())
    assert listed.status_code == 200
    fetched = client.get(
        f"/api/v1/changes/assessments/{created['assessment_id']}", headers=_auth()
    )
    assert fetched.status_code == 200


def test_a_direct_fetch_is_not_a_way_around_scope(client):
    """The id must not be a back door past the listing filter."""
    created = client.post(
        "/api/v1/changes/assess",
        headers=_auth(),
        json={"source": "terraform_plan", "payload": _terraform_plan()},
    ).json()["data"]
    response = client.get(
        f"/api/v1/changes/assessments/{created['assessment_id']}",
        headers=_auth(SCOPED_TOKEN),
    )
    assert response.status_code == 404


def test_assessment_routes_require_authentication(client):
    assert client.get("/api/v1/changes/assessments").status_code == 401
    assert (
        client.post(
            "/api/v1/changes/assess",
            json={"source": "terraform_plan", "payload": {}},
        ).status_code
        == 401
    )


def test_explain_route_answers_what_may_be_affected(client):
    created = client.post(
        "/api/v1/changes/assess",
        headers=_auth(),
        json={"source": "terraform_plan", "payload": _terraform_plan()},
    ).json()["data"]
    response = client.get(
        f"/api/v1/changes/assessments/{created['assessment_id']}/explain",
        headers=_auth(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["verdict"] == created["cab_recommendation"]["verdict"]
    assert data["confidence"] == created["risk"]["confidence"]
    assert "why" in data


def test_explain_route_keeps_its_qualifiers_attached(client):
    """A narration payload must not be summarizable into a causal claim."""
    created = client.post(
        "/api/v1/changes/assess",
        headers=_auth(),
        json={"source": "terraform_plan", "payload": _terraform_plan()},
    ).json()["data"]
    data = client.get(
        f"/api/v1/changes/assessments/{created['assessment_id']}/explain",
        headers=_auth(),
    ).json()["data"]
    assert data["confirmed_cause"] is False
    assert "does not observe runtime behaviour" in data["interpretation"]


def test_explain_route_inherits_scope_isolation(client):
    created = client.post(
        "/api/v1/changes/assess",
        headers=_auth(),
        json={"source": "terraform_plan", "payload": _terraform_plan()},
    ).json()["data"]
    response = client.get(
        f"/api/v1/changes/assessments/{created['assessment_id']}/explain",
        headers=_auth(SCOPED_TOKEN),
    )
    assert response.status_code == 404
