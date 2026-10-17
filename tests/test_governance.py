"""Tests for the enterprise governance engines and routes.

These lean deliberately on realistic row shapes -- ontology entities carrying
their source fields inside ``payload_json`` -- because the bug most likely to
ship in this area is a field that survives the engine but not the pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import runtime as api_runtime
from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.governance_snapshot import GovernanceSnapshot
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.governance import (
    AccessReviewBuilder,
    AuditExportBuilder,
    EnterpriseSettingsStore,
    FinOpsEngine,
    IdentityRiskEngine,
    SettingsValidationError,
    SpnGovernanceEngine,
    default_settings,
    validate_settings,
)
from onboarding.service import SubscriptionOnboardingService
from storage.datasets import DatasetStore

ADMIN_TOKEN = "admin-token-0123456789"
READER_TOKEN = "reader-token-0123456789"

NOW = datetime(2026, 1, 15, tzinfo=UTC)


def _entity(entity_type: str, resource_id: str, payload: dict) -> dict:
    """An ontology row as the dataset mapper actually writes it."""
    return {
        "resource_id": resource_id,
        "entity_type": entity_type,
        "name": resource_id.rsplit("/", 1)[-1],
        "subscription_id": payload.get("subscriptionId", ""),
        "payload_json": json.dumps(payload),
    }


def _advisor_row(
    resource_id: str,
    *,
    category: str = "Cost",
    savings: float | None = 1200.0,
    problem: str = "Right-size underutilized virtual machine",
    subscription: str = "sub-a",
) -> dict:
    extended = {"savingsCurrency": "USD"}
    if savings is not None:
        extended["annualSavingsAmount"] = savings
    return {
        "id": f"/advisor/{resource_id}",
        "category": category,
        "impact": "High",
        "problem": problem,
        "solution": "Resize or shut down the resource",
        "targetResourceId": resource_id,
        "subscriptionId": subscription,
        "application": "checkout",
        "business_service": "payments",
        "owner": "platform-team",
        "environment": "production",
        "properties": {"extendedProperties": extended},
    }


def _cost_row(
    resource_id: str,
    *,
    cost: float = 100.0,
    currency: str = "USD",
    usage_date: str = "2026-01-15",
    subscription: str = "sub-a",
) -> dict:
    return {
        "id": f"costactual://{subscription}/{usage_date}/row",
        "subscriptionId": subscription,
        "usageDate": usage_date,
        "cost": cost,
        "currency": currency,
        "targetResourceId": resource_id,
        "serviceName": "Virtual Machines",
    }


# --------------------------------------------------------------------------
# FinOps
# --------------------------------------------------------------------------


def test_savings_opportunities_use_advisor_figures_and_rank_by_value():
    engine = FinOpsEngine(
        advisor_recommendations=[
            _advisor_row("/vm/a", savings=500.0),
            _advisor_row("/vm/b", savings=2500.0),
            _advisor_row("/vm/c", savings=None),
        ]
    )
    opportunities = engine.savings_opportunities()

    assert [item.resource_id for item in opportunities] == ["/vm/b", "/vm/a", "/vm/c"]
    assert opportunities[0].annual_savings == 2500.0
    # An unquantified saving stays None so the UI can distinguish it from zero.
    assert opportunities[-1].annual_savings is None
    assert all(item.to_dict()["savings_source"] == "azure_advisor" for item in opportunities)


def test_identical_advisor_opportunities_are_deduplicated_keeping_highest_saving():
    duplicate = _advisor_row("/subscriptions/sub-a", savings=1699.0)
    engine = FinOpsEngine(
        advisor_recommendations=[
            duplicate,
            {**duplicate, "id": f"{duplicate['id']}/duplicate"},
            # Same resource/problem/solution/impact but a slightly different
            # (stale) savings estimate -- this is the same logical
            # recommendation and must collapse into one row, not two.
            {**duplicate, "id": f"{duplicate['id']}/lower", "properties": {"extendedProperties": {
                "annualSavingsAmount": 1695.0,
                "savingsCurrency": "USD",
            }}},
        ]
    )

    opportunities = engine.savings_opportunities()

    assert len(opportunities) == 1
    assert opportunities[0].annual_savings == 1699.0


def test_advisor_opportunities_for_different_resources_are_not_merged():
    engine = FinOpsEngine(
        advisor_recommendations=[
            _advisor_row("/subscriptions/sub-a", savings=500.0),
            _advisor_row("/subscriptions/sub-b", savings=310.0),
        ]
    )

    opportunities = engine.savings_opportunities()

    assert len(opportunities) == 2
    assert {item.resource_id for item in opportunities} == {"/subscriptions/sub-a", "/subscriptions/sub-b"}


def test_non_cost_advisor_recommendations_are_ignored():
    engine = FinOpsEngine(
        advisor_recommendations=[
            _advisor_row("/vm/a", category="Security", savings=900.0),
            _advisor_row("/vm/b", category="Cost", savings=100.0),
        ]
    )
    assert [item.resource_id for item in engine.savings_opportunities()] == ["/vm/b"]


def test_summary_never_invents_spend_and_names_what_is_unavailable():
    summary = FinOpsEngine(
        advisor_recommendations=[_advisor_row("/vm/a", savings=1000.0)]
    ).summary()

    assert summary["identified_annual_savings"] == 1000.0
    assert summary["currency"] == "USD"
    unavailable = {item["metric"] for item in summary["unavailable_metrics"]}
    # The whole point: actual spend is absent, and said to be absent.
    assert unavailable == {"actual_spend", "cost_forecast", "cost_anomaly"}
    assert all(item["reason"] for item in summary["unavailable_metrics"])


def test_summary_uses_cost_management_actuals_when_available():
    summary = FinOpsEngine(
        advisor_recommendations=[_advisor_row("/vm/a", savings=1000.0)],
        cost_actuals=[
            _cost_row("/vm/a", cost=12.25, usage_date="2026-01-14"),
            _cost_row("/vm/a", cost=17.75, usage_date="2026-01-15"),
        ],
    ).summary()

    assert summary["actual_spend"] == 30.0
    assert summary["actual_spend_currency"] == "USD"
    assert summary["actual_spend_source"] == "azure_cost_management"
    assert summary["actual_spend_period_start"] == "2026-01-14"
    assert summary["actual_spend_period_end"] == "2026-01-15"
    unavailable = {item["metric"] for item in summary["unavailable_metrics"]}
    assert "actual_spend" not in unavailable
    assert unavailable == {"cost_forecast", "cost_anomaly"}


def test_mixed_currency_totals_are_labelled_rather_than_summed_silently():
    engine = FinOpsEngine(
        advisor_recommendations=[
            {**_advisor_row("/vm/a", savings=100.0)},
            {
                **_advisor_row("/vm/b", savings=200.0),
                "properties": {
                    "extendedProperties": {
                        "annualSavingsAmount": 200.0,
                        "savingsCurrency": "EUR",
                    }
                },
            },
        ]
    )
    assert engine.summary()["currency"] == "mixed"


def test_waste_detects_unattached_disks_and_deallocated_vms():
    engine = FinOpsEngine(
        resources=[
            {
                "id": "/disks/orphan",
                "type": "microsoft.compute/disks",
                "properties": {"diskState": "Unattached"},
            },
            {
                "id": "/disks/attached",
                "type": "microsoft.compute/disks",
                "properties": {"diskState": "Attached"},
            },
            {
                "id": "/vms/stopped",
                "type": "microsoft.compute/virtualmachines",
                "properties": {"powerState": "PowerState/deallocated"},
            },
            {
                "id": "/vms/running",
                "type": "microsoft.compute/virtualmachines",
                "properties": {"powerState": "PowerState/running"},
            },
            {
                "id": "/ips/idle",
                "type": "microsoft.network/publicipaddresses",
                "properties": {},
            },
        ]
    )
    detected = {item.resource_id for item in engine.waste()}
    assert detected == {"/disks/orphan", "/vms/stopped", "/ips/idle"}
    assert all(item.detected_by == "resource_inventory" for item in engine.waste())


def test_advisor_waste_takes_precedence_over_inventory_detection():
    engine = FinOpsEngine(
        advisor_recommendations=[
            _advisor_row("/disks/orphan", problem="Delete unattached disk")
        ],
        resources=[
            {
                "id": "/disks/orphan",
                "type": "microsoft.compute/disks",
                "properties": {"diskState": "Unattached"},
            }
        ],
    )
    waste = engine.waste()
    assert len(waste) == 1
    assert waste[0].detected_by == "azure_advisor"


def test_attribution_groups_savings_by_business_dimension():
    engine = FinOpsEngine(
        advisor_recommendations=[
            _advisor_row("/vm/a", savings=100.0),
            {**_advisor_row("/vm/b", savings=300.0), "application": "search"},
        ]
    )
    groups = engine.by_dimension("application")
    assert [group["application"] for group in groups] == ["search", "checkout"]
    assert groups[0]["identified_annual_savings"] == 300.0


def test_unattributed_savings_are_labelled_not_dropped():
    engine = FinOpsEngine(
        advisor_recommendations=[
            {
                "id": "/advisor/x",
                "category": "Cost",
                "targetResourceId": "/vm/x",
                "problem": "p",
                "solution": "s",
                "impact": "Low",
                "properties": {"extendedProperties": {"annualSavingsAmount": 50.0}},
            }
        ]
    )
    groups = engine.by_dimension("application")
    assert groups[0]["application"] == "unattributed"
    assert groups[0]["identified_annual_savings"] == 50.0


def test_unsupported_finops_dimension_is_rejected():
    with pytest.raises(ValueError, match="Unsupported FinOps dimension"):
        FinOpsEngine().by_dimension("region")


def test_malformed_savings_values_do_not_become_fake_numbers():
    engine = FinOpsEngine(
        advisor_recommendations=[
            {
                **_advisor_row("/vm/a"),
                "properties": {"extendedProperties": {"annualSavingsAmount": "not-a-number"}},
            }
        ]
    )
    assert engine.savings_opportunities()[0].annual_savings is None
    assert engine.summary()["identified_annual_savings"] == 0.0
    assert engine.summary()["quantified_opportunity_count"] == 0


# --------------------------------------------------------------------------
# Identity risk
# --------------------------------------------------------------------------


def _assignment(
    assignment_id: str,
    *,
    principal: str,
    role: str = "/roles/reader",
    scope: str = "/subscriptions/sub-a/resourceGroups/rg1",
    principal_type: str = "User",
    changed: datetime | None = None,
) -> dict:
    return {
        "id": assignment_id,
        "principalId": principal,
        "principalType": principal_type,
        "roleDefinitionId": role,
        "assignmentScope": scope,
        "updatedOn": (changed or NOW).isoformat(),
        "subscriptionId": "sub-a",
    }


def _definition(role_id: str, name: str, actions: list[str] | None = None) -> dict:
    return {"id": role_id, "roleName": name, "actions": actions or ["*/read"]}


def _identity_engine(**kwargs) -> IdentityRiskEngine:
    kwargs.setdefault(
        "role_definitions",
        [
            _definition("/roles/reader", "Reader"),
            _definition("/roles/owner", "Owner", ["*"]),
            _definition("/roles/custom", "Custom Deployer", ["microsoft.authorization/roleassignments/write"]),
        ],
    )
    kwargs.setdefault("now", NOW)
    return IdentityRiskEngine(**kwargs)


def test_owner_role_is_privileged_and_ranks_first():
    engine = _identity_engine(
        role_assignments=[
            _assignment("a1", principal="p-reader"),
            _assignment(
                "a2", principal="p-owner", role="/roles/owner", scope="/subscriptions/sub-a"
            ),
        ]
    )
    principals = engine.principals()
    assert principals[0].principal_id == "p-owner"
    assert principals[0].privileged is True
    assert principals[1].privileged is False


def test_custom_role_granting_role_assignment_write_is_privileged():
    """A privileged custom role must be caught by its actions, not its name."""
    engine = _identity_engine(
        role_assignments=[_assignment("a1", principal="p1", role="/roles/custom")]
    )
    assert engine.principals()[0].privileged is True


def test_blast_radius_counts_scope_breadth_and_reports_widest():
    engine = _identity_engine(
        role_assignments=[
            _assignment("a1", principal="p1", scope="/subscriptions/sub-a"),
            _assignment(
                "a2", principal="p1", scope="/subscriptions/sub-a/resourceGroups/rg1"
            ),
            _assignment(
                "a3",
                principal="p1",
                scope="/subscriptions/sub-a/resourceGroups/rg1/providers/x/y/z",
            ),
        ]
    )
    record = engine.principals()[0]
    assert record.widest_scope_breadth == "subscription"
    assert record.blast_radius == {"subscription": 1, "resource_group": 1, "resource": 1}


def test_management_group_scope_outranks_subscription():
    engine = _identity_engine(
        role_assignments=[
            _assignment(
                "a1",
                principal="p1",
                scope="/providers/Microsoft.Management/managementGroups/root",
            ),
            _assignment("a2", principal="p1", scope="/subscriptions/sub-a"),
        ]
    )
    assert engine.principals()[0].widest_scope_breadth == "management_group"


def test_stale_access_uses_the_documented_threshold():
    fresh = NOW - timedelta(days=10)
    stale = NOW - timedelta(days=200)
    engine = _identity_engine(
        role_assignments=[
            _assignment("a1", principal="p-fresh", changed=fresh),
            _assignment("a2", principal="p-stale", changed=stale),
        ]
    )
    stale_ids = {item["principal_id"] for item in engine.stale_access()}
    assert stale_ids == {"p-stale"}


def test_assignment_without_timestamp_is_not_assumed_stale():
    """Unknown age must not fill the review queue with unactionable noise."""
    engine = _identity_engine(
        role_assignments=[
            {
                "id": "a1",
                "principalId": "p1",
                "principalType": "User",
                "roleDefinitionId": "/roles/reader",
                "assignmentScope": "/subscriptions/sub-a",
            }
        ]
    )
    assert engine.stale_access() == []
    assert engine.principals()[0].stale is False


@pytest.mark.parametrize("timestamp", ["", "not-a-clock", "2026-01-14T00:00:00", "2026-01-16T00:00:00Z"])
def test_identity_unknown_age_is_explicit_not_current_or_stale(timestamp):
    assignment = {**_assignment("a1", principal="p1", role="/roles/owner"), "updatedOn": timestamp, "createdOn": ""}
    engine = _identity_engine(role_assignments=[assignment])
    evidence = engine.principals()[0].to_dict()["risk_evidence"]
    assert evidence["unknown_age_assignments"] == 1
    assert evidence["stale_assignments"] == 0
    assert evidence["age_evaluated_at"] == NOW.isoformat()
    assert engine.stale_access() == []
    assert engine.subscription_owners() == []  # Resource-group owner, not a subscription owner.


def test_identity_unresolved_role_and_unknown_age_cannot_be_masked_by_recent_sibling():
    assignments = [
        _assignment("recent", principal="p1"),
        {**_assignment("unknown", principal="p1", role="/roles/missing"), "updatedOn": ""},
        _assignment("old", principal="p1", changed=NOW - timedelta(days=200)),
    ]
    evidence = _identity_engine(role_assignments=assignments).principals()[0].to_dict()["risk_evidence"]
    assert evidence == {
        "classification": "incomplete", "unresolved_role_assignments": 1,
        "unknown_age_assignments": 1, "stale_assignments": 1,
        "age_evaluated_at": NOW.isoformat(), "effective_access": "not_evaluated",
    }


@pytest.mark.parametrize("actions", [None, [], "*/read", [None], [""]])
def test_identity_unusable_action_evidence_is_not_standard_access(actions):
    engine = _identity_engine(
        role_assignments=[_assignment("a1", principal="p1")],
        role_definitions=[{**_definition("/roles/reader", "Reader"), "actions": actions}],
    )
    evidence = engine.principals()[0].to_dict()["risk_evidence"]
    assert evidence["classification"] == "incomplete"
    assert evidence["unresolved_role_assignments"] == 1


def test_identity_privileged_heuristic_remains_qualified_with_unknown_sibling():
    engine = _identity_engine(role_assignments=[
        _assignment("owner", principal="p1", role="/roles/owner", scope="/subscriptions/sub-a"),
        _assignment("missing", principal="p1", role="/roles/missing"),
    ])
    evidence = engine.principals()[0].to_dict()["risk_evidence"]
    assert evidence["classification"] == "privileged_signal"
    assert evidence["unresolved_role_assignments"] == 1
    assert evidence["effective_access"] == "not_evaluated"
    assert engine.subscription_owners()[0]["age_state"] == "within_review_window"


def test_identity_known_role_has_no_classified_signal_not_effective_access_assurance():
    evidence = _identity_engine(role_assignments=[_assignment("a1", principal="p1")]).principals()[0].risk_evidence
    assert evidence["classification"] == "no_classified_signal"
    assert evidence["unresolved_role_assignments"] == 0
    assert evidence["effective_access"] == "not_evaluated"


def test_least_privilege_review_explains_broad_and_elevated_grants():
    engine = _identity_engine(
        role_assignments=[
            _assignment(
                "owner-grant",
                principal="p-owner",
                role="/roles/owner",
                scope="/subscriptions/sub-a",
            ),
            _assignment(
                "reader-grant",
                principal="p-reader",
                scope="/subscriptions/sub-a/resourceGroups/rg1",
            ),
        ]
    )

    review = engine.least_privilege_review()

    assert review["effective_access"] == "not_evaluated"
    assert review["assignment_count"] == 2
    assert review["candidate_count"] == 2
    owner = review["candidates"][0]
    assert owner["assignment_id"] == "owner-grant"
    assert owner["scope_breadth"] == "subscription"
    assert "broad_subscription_scope" in owner["review_reasons"]
    assert "elevated_role_or_action_heuristic" in owner["review_reasons"]
    assert "Do not change access from this advisory alone." in owner["recommendation"]
    assert review["coverage"]["group_membership"] == "not_collected"
    assert review["coverage"]["deny_assignments"] == "not_collected"
    assert review["coverage"]["role_conditions"] == "presence_only_not_evaluated"


def test_least_privilege_review_includes_all_permission_blocks_and_condition_state():
    assignment = {
        **_assignment("conditional", principal="p1", scope="/subscriptions/sub-a/resourceGroups/rg1"),
        "properties": {"condition": "@Resource[name] StringEquals 'prod'"},
    }
    definition = {
        "id": "/roles/custom",
        "roleName": "Custom Data Operator",
        "properties": {
            "permissions": [
                {"actions": ["Microsoft.Storage/storageAccounts/read"], "notActions": ["Microsoft.Storage/*/delete"]},
                {"dataActions": ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"]},
            ]
        },
    }
    review = _identity_engine(
        role_assignments=[{**assignment, "roleDefinitionId": "/roles/custom"}],
        role_definitions=[definition],
    ).least_privilege_review()

    candidate = review["candidates"][0]
    profile = candidate["permission_profile"]
    assert profile["actions"]["patterns"] == ["Microsoft.Storage/storageAccounts/read"]
    assert profile["not_actions"]["patterns"] == ["Microsoft.Storage/*/delete"]
    assert profile["data_actions"]["patterns"] == [
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"
    ]
    assert profile["wildcard_pattern_count"] == 2
    assert candidate["condition_state"] == "present"
    assert review["coverage"]["conditional_assignments_observed"] == 1
    assert review["coverage"]["effective_access"] == "not_evaluated"


def test_least_privilege_review_marks_unresolved_role_and_unknown_age():
    assignment = {
        **_assignment(
            "missing",
            principal="p1",
            role="/roles/missing",
            scope="/subscriptions/sub-a",
        ),
        "updatedOn": "",
    }
    review = _identity_engine(role_assignments=[assignment]).least_privilege_review()

    assert review["candidate_count"] == 1
    assert review["coverage"]["role_definitions_resolved"] == 0
    assert review["coverage"]["assignment_age_unknown"] == 1
    assert set(review["candidates"][0]["review_reasons"]) == {
        "broad_subscription_scope",
        "assignment_change_age_unknown",
        "role_definition_or_permissions_unresolved",
    }


def test_least_privilege_review_marks_missing_scope_without_inventing_breadth():
    assignment = {
        **_assignment("scope-missing", principal="p1", scope=""),
        "updatedOn": NOW.isoformat(),
    }
    review = _identity_engine(role_assignments=[assignment]).least_privilege_review()

    assert review["candidate_count"] == 1
    assert review["candidates"][0]["scope_breadth"] == "unknown"
    assert set(review["candidates"][0]["review_reasons"]) == {
        "assignment_scope_unknown",
        "wildcard_permission_patterns",
    }
    assert review["coverage"]["assignment_scope_unknown"] == 1


def test_least_privilege_review_paginates_candidates_without_dropping_total():
    engine = _identity_engine(
        role_assignments=[
            _assignment(f"a{index}", principal=f"p{index}", scope="/subscriptions/sub-a")
            for index in range(3)
        ]
    )

    review = engine.least_privilege_review(offset=1, limit=1)

    assert review["candidate_count"] == 3
    assert review["offset"] == 1
    assert review["limit"] == 1
    assert len(review["candidates"]) == 1


def test_subscription_owners_exclude_resource_group_owners():
    engine = _identity_engine(
        role_assignments=[
            _assignment(
                "a1", principal="p-sub", role="/roles/owner", scope="/subscriptions/sub-a"
            ),
            _assignment(
                "a2",
                principal="p-rg",
                role="/roles/owner",
                scope="/subscriptions/sub-a/resourceGroups/rg1",
            ),
        ]
    )
    assert [item["principal_id"] for item in engine.subscription_owners()] == ["p-sub"]


def test_unused_managed_identity_is_still_reported():
    engine = _identity_engine(
        role_assignments=[],
        managed_identities=[
            {"id": "/mi/one", "name": "one", "principalId": "mi-principal"}
        ],
    )
    identities = engine.non_human_identities()
    assert len(identities) == 1
    assert identities[0]["assignment_count"] == 0


def test_service_principal_assignments_appear_as_non_human():
    engine = _identity_engine(
        role_assignments=[
            _assignment("a1", principal="spn-1", principal_type="ServicePrincipal"),
            _assignment("a2", principal="user-1", principal_type="User"),
        ]
    )
    assert [item["principal_id"] for item in engine.non_human_identities()] == ["spn-1"]


# --------------------------------------------------------------------------
# SPN governance
# --------------------------------------------------------------------------


def _connection(name: str, *, expires_at: str | None, last_sync: str = "") -> dict:
    return {
        "connection_id": f"conn-{name}",
        "name": name,
        "tenant_id": "tenant-1",
        "subscription_id": "sub-a",
        "credential": {
            "credential_id": f"cred-{name}",
            "client_id": f"client-{name}",
            "secret_ref": f"kv/{name}",
            "expires_at": expires_at,
            "scopes": ["https://management.azure.com/.default"],
            "active": True,
        },
        "sync_state": {"last_successful_sync": last_sync},
    }


def test_expired_and_expiring_credentials_rank_before_healthy_ones():
    engine = SpnGovernanceEngine(
        [
            _connection("healthy", expires_at=(NOW + timedelta(days=200)).isoformat()),
            _connection("expired", expires_at=(NOW - timedelta(days=5)).isoformat()),
            _connection("soon", expires_at=(NOW + timedelta(days=10)).isoformat()),
        ],
        now=NOW,
    )
    statuses = [record.rotation_status for record in engine.credentials()]
    assert statuses == ["expired", "expiring_soon", "healthy"]


def test_missing_expiry_is_unknown_not_healthy():
    """An unrecorded expiry is a governance gap and must not read as fine."""
    engine = SpnGovernanceEngine([_connection("mystery", expires_at=None)], now=NOW)
    record = engine.credentials()[0]
    assert record.rotation_status == "unknown"
    assert any("expiry is not recorded" in issue for issue in record.issues)


def test_credential_never_used_is_flagged_as_unused():
    engine = SpnGovernanceEngine(
        [
            _connection("used", expires_at=None, last_sync="2026-01-01T00:00:00Z"),
            _connection("unused", expires_at=None),
        ],
        now=NOW,
    )
    assert engine.summary()["unused_count"] == 1


def test_missing_secret_reference_is_reported_as_an_issue():
    connection = _connection("nosecret", expires_at=None)
    connection["credential"]["secret_ref"] = ""
    engine = SpnGovernanceEngine([connection], now=NOW)
    assert any("Key Vault" in issue for issue in engine.credentials()[0].issues)


def test_assignment_count_is_unresolved_without_an_object_id():
    """A client id never appears in role assignments, so we must not imply
    we looked and found nothing."""
    connection = _connection("noobject", expires_at=None)
    connection["credential"].pop("object_id", None)
    engine = SpnGovernanceEngine(
        [connection],
        role_assignments=[{"principalId": "obj-1"}],
        now=NOW,
    )
    record = engine.credentials()[0]
    assert record.observed_assignment_count is None
    assert record.assignment_lookup_state == "unresolved_no_object_id"


def test_assignment_count_is_resolved_by_object_id():
    connection = _connection("withobject", expires_at=None)
    connection["credential"]["object_id"] = "OBJ-1"
    engine = SpnGovernanceEngine(
        [connection],
        role_assignments=[{"principalId": "obj-1"}, {"principalId": "obj-1"}],
        now=NOW,
    )
    record = engine.credentials()[0]
    assert record.observed_assignment_count == 2
    assert record.assignment_lookup_state == "resolved"


def test_spn_summary_counts_each_rotation_state():
    engine = SpnGovernanceEngine(
        [
            _connection("a", expires_at=(NOW - timedelta(days=1)).isoformat()),
            _connection("b", expires_at=(NOW + timedelta(days=5)).isoformat()),
            _connection("c", expires_at=(NOW + timedelta(days=400)).isoformat()),
            _connection("d", expires_at=None),
        ],
        now=NOW,
    )
    summary = engine.summary()
    assert summary["expired_count"] == 1
    assert summary["expiring_soon_count"] == 1
    assert summary["healthy_count"] == 1
    assert summary["unknown_expiry_count"] == 1


# --------------------------------------------------------------------------
# Access reviews and audit exports
# --------------------------------------------------------------------------


def test_service_owner_pack_lists_only_actionable_grants():
    engine = _identity_engine(
        role_assignments=[
            _assignment("a1", principal="p-ordinary"),
            _assignment(
                "a2", principal="p-owner", role="/roles/owner", scope="/subscriptions/sub-a"
            ),
        ]
    )
    pack = AccessReviewBuilder(identity_engine=engine).build("service_owner")
    assert [item["principal_id"] for item in pack["items"]] == ["p-owner"]
    assert pack["total_principal_count"] == 2


def test_every_review_pack_carries_provenance():
    engine = _identity_engine(role_assignments=[_assignment("a1", principal="p1")])
    for audience in ("service_owner", "security", "auditor"):
        pack = AccessReviewBuilder(
            identity_engine=engine,
            scope={"subscription": ["sub-a"]},
            observed_at="2026-01-15T00:00:00Z",
        ).build(audience)
        provenance = pack["provenance"]
        assert provenance["source_engines"]
        assert provenance["observed_at"] == "2026-01-15T00:00:00Z"
        assert provenance["scope"] == {"subscription": ["sub-a"]}


def test_auditor_pack_states_its_coverage_limits():
    engine = _identity_engine(role_assignments=[])
    pack = AccessReviewBuilder(identity_engine=engine).build("auditor")
    assert "onboarded" in pack["coverage_note"]


def test_unknown_review_audience_is_rejected():
    with pytest.raises(ValueError, match="Unsupported access review audience"):
        AccessReviewBuilder(identity_engine=_identity_engine()).build("marketing")


def test_audit_export_records_section_counts_and_warnings():
    pack = AuditExportBuilder(observed_at="2026-01-15T00:00:00Z").build(
        "identity",
        {"principals": [{"principal_id": "p1"}], "summary": {}},
        engines=["identity"],
        warnings=["partial"],
    )
    assert pack["section_counts"]["principals"] == 1
    assert pack["provenance"]["warnings"] == ["partial"]


def test_unknown_export_kind_is_rejected():
    with pytest.raises(ValueError, match="Unsupported audit export kind"):
        AuditExportBuilder().build("marketing", {})


# --------------------------------------------------------------------------
# Enterprise settings
# --------------------------------------------------------------------------


def test_default_settings_are_conservative():
    settings = default_settings()
    assert settings["agent_policy"]["require_human_approval"] is True
    assert settings["agent_policy"]["allow_autonomous_remediation"] is False
    assert settings["onboarding_policy"]["allow_self_service"] is False


def test_settings_update_merges_over_defaults():
    store = EnterpriseSettingsStore()
    result = store.update(
        {"retention_policy": {"audit_log_days": 30}},
        expected_revision=0, reason="Review retention", actor="admin@example.com",
    )
    assert result["retention_policy"]["audit_log_days"] == 30
    # Untouched keys in the same section survive the partial update.
    assert result["retention_policy"]["estate_snapshot_days"] == 365


def test_removing_the_last_admin_role_is_rejected():
    with pytest.raises(SettingsValidationError, match="admin permission"):
        validate_settings(
            {"roles": [{"role_id": "viewer", "name": "V", "permissions": ["read"]}]}
        )


def test_autonomous_remediation_without_approval_is_rejected():
    with pytest.raises(SettingsValidationError, match="Autonomous remediation"):
        validate_settings(
            {
                "agent_policy": {
                    "allow_autonomous_remediation": True,
                    "require_human_approval": False,
                }
            }
        )


def test_unbounded_retention_is_rejected():
    with pytest.raises(SettingsValidationError, match="retention_policy"):
        validate_settings({"retention_policy": {"audit_log_days": 999_999}})


def test_unknown_settings_section_is_rejected():
    with pytest.raises(SettingsValidationError, match="Unknown settings sections"):
        validate_settings({"nonsense": {}})


def test_duplicate_role_ids_are_rejected():
    with pytest.raises(SettingsValidationError, match="Duplicate role_id"):
        validate_settings(
            {
                "roles": [
                    {"role_id": "a", "name": "A", "permissions": ["admin"]},
                    {"role_id": "a", "name": "A2", "permissions": ["read"]},
                ]
            }
        )


# --------------------------------------------------------------------------
# Scoped snapshot -- subscription isolation
# --------------------------------------------------------------------------


def _snapshot() -> GovernanceSnapshot:
    return GovernanceSnapshot(
        [
            _entity(
                "RoleAssignment",
                "/ra/a",
                {
                    "principalId": "p-a",
                    "principalType": "User",
                    "assignmentScope": "/subscriptions/sub-a",
                    "roleDefinitionId": "/roles/owner",
                    "subscriptionId": "sub-a",
                    "updatedOn": NOW.isoformat(),
                },
            ),
            _entity(
                "RoleAssignment",
                "/ra/b",
                {
                    "principalId": "p-b",
                    "principalType": "User",
                    "assignmentScope": "/subscriptions/sub-b",
                    "roleDefinitionId": "/roles/owner",
                    "subscriptionId": "sub-b",
                    "updatedOn": NOW.isoformat(),
                },
            ),
        ],
        observed_at="2026-01-15T00:00:00Z",
        connections=[
            {**_connection("a", expires_at=None), "subscription_id": "sub-a"},
            {**_connection("b", expires_at=None), "subscription_id": "sub-b"},
        ],
    )


def test_snapshot_unpacks_payload_fields_engines_depend_on():
    rows = _snapshot().rows("RoleAssignment")
    assert {row["principalId"] for row in rows} == {"p-a", "p-b"}
    assert rows[0]["assignmentScope"].startswith("/subscriptions/")


def test_scoping_a_snapshot_excludes_other_subscriptions():
    scoped = _snapshot().scoped(Scope({"subscription": {"sub-a"}}))
    assert [row["principalId"] for row in scoped.rows("RoleAssignment")] == ["p-a"]
    assert [item["subscription_id"] for item in scoped.connections] == ["sub-a"]


def test_unrestricted_scope_reuses_snapshot_without_copying_estate_rows():
    snapshot = _snapshot()

    assert snapshot.scoped(Scope.unrestricted()) is snapshot


def test_disjoint_scope_yields_nothing_rather_than_everything():
    """The failure mode that would leak an estate: an empty scope widening."""
    scoped = _snapshot().scoped(Scope({"subscription": {"sub-zzz"}}))
    assert scoped.rows("RoleAssignment") == []
    assert scoped.connections == []


def test_has_identity_data_distinguishes_empty_from_unsynced():
    assert _snapshot().has_identity_data is True
    assert GovernanceSnapshot([]).has_identity_data is False


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def _client(tmp_path, snapshot: GovernanceSnapshot | None = None):
    principals = {
        ADMIN_TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        READER_TOKEN: Principal(subject="reader@example.com", grants=(Grant("reader"),)),
    }
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        governance_provider=lambda: snapshot,
        settings_store=EnterpriseSettingsStore(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _headers(token: str = READER_TOKEN) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _fail_if_registry_listed(*, include_disabled: bool = False):
    del include_disabled
    raise AssertionError("snapshot-backed search must not access connection registry")


def test_governance_routes_report_unavailable_before_any_sync(tmp_path):
    """No data must never be presented as a clean bill of health."""
    client = _client(tmp_path, snapshot=None)
    response = client.get("/api/v1/governance/identity/summary", headers=_headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_search_resolves_exact_identity_id_without_semantic_provider(tmp_path):
    principal_id = "377ec4a4-4482-4433-975f-46e69461cb65"
    snapshot = GovernanceSnapshot(
        [
            _entity(
                "RoleAssignment",
                "/ra/exact",
                {
                    "principalId": principal_id,
                    "principalType": "ServicePrincipal",
                    "assignmentScope": "/subscriptions/sub-a",
                    "roleDefinitionId": "/roles/owner",
                    "subscriptionId": "sub-a",
                    "updatedOn": NOW.isoformat(),
                },
            ),
            _entity(
                "RoleDefinition",
                "/roles/owner",
                {
                    "id": "/roles/owner",
                    "roleName": "Owner",
                    "actions": ["*"],
                    "subscriptionId": "sub-a",
                },
            ),
        ],
        observed_at="2026-01-15T00:00:00Z",
    )
    client = _client(tmp_path, snapshot)
    client.app.state.context.onboarding.registry.list = _fail_if_registry_listed

    response = client.get(f"/api/v1/search?q={principal_id}", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["intent"] == "identity_identifier_lookup"
    assert body["data"]["count"] == 1
    assert body["data"]["results"][0]["principal_id"] == principal_id
    assert body["data"]["results"][0]["entity_type"] == "ServicePrincipal"
    assert body["evidence"][0]["source_engine"] == (
        "intelligence.governance.IdentityRiskEngine"
    )


def test_search_resolves_exact_user_assigned_managed_identity_arm_id(tmp_path):
    resource_id = (
        "/subscriptions/sub-a/resourceGroups/identity-rg/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/reconciler"
    )
    snapshot = GovernanceSnapshot(
        [
            _entity(
                "ManagedIdentity",
                resource_id,
                {
                    "id": resource_id,
                    "name": "reconciler",
                    "principalId": "377ec4a4-4482-4433-975f-46e69461cb65",
                    "subscriptionId": "sub-a",
                },
            )
        ],
        observed_at="2026-01-15T00:00:00Z",
    )
    client = _client(tmp_path, snapshot)
    client.app.state.context.onboarding.registry.list = _fail_if_registry_listed

    response = client.get(
        "/api/v1/search",
        params={"q": resource_id},
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["intent"] == "identity_identifier_lookup"
    assert body["data"]["results"][0]["id"] == resource_id
    assert body["data"]["results"][0]["entity_type"] == "ManagedIdentity"


def test_search_does_not_classify_ordinary_arm_resource_as_identity(tmp_path):
    resource_id = (
        "/subscriptions/sub-a/resourceGroups/compute-rg/providers/"
        "Microsoft.Compute/virtualMachines/vm-a"
    )
    principals = {
        READER_TOKEN: Principal(
            subject="reader@example.com",
            grants=(Grant("reader"),),
        )
    }
    semantic = SimpleNamespace(
        search=lambda query: {
            "query": query,
            "intent": "semantic_search",
            "items": [],
            "count": 0,
        }
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: semantic,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    client.app.state.context.onboarding.registry.list = _fail_if_registry_listed

    response = client.get(
        "/api/v1/search",
        params={"q": resource_id},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json()["data"]["intent"] == "semantic_search"


def test_identity_id_search_does_not_leak_out_of_scope_principal(tmp_path):
    principal_id = "377ec4a4-4482-4433-975f-46e69461cb65"
    snapshot = GovernanceSnapshot(
        [
            _entity(
                "RoleAssignment",
                "/ra/exact",
                {
                    "principalId": principal_id,
                    "principalType": "User",
                    "assignmentScope": "/subscriptions/sub-b",
                    "roleDefinitionId": "/roles/reader",
                    "subscriptionId": "sub-b",
                    "updatedOn": NOW.isoformat(),
                },
            )
        ],
        observed_at="2026-01-15T00:00:00Z",
    )
    scoped = Scope({"subscription": frozenset({"sub-a"})})
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {
                READER_TOKEN: Principal(
                    subject="scoped@example.com",
                    grants=(Grant("reader", scoped),),
                )
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        governance_provider=lambda: snapshot,
        settings_store=EnterpriseSettingsStore(),
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    response = client.get(f"/api/v1/search?q={principal_id}", headers=_headers())

    assert response.status_code == 200
    assert response.json()["data"]["results"] == []


def _publish_governance_generation(
    home,
    connection: dict,
    datasets: dict[str, list[dict]],
) -> None:
    store = DatasetStore(
        api_runtime._connection_dataset_dir(str(home), connection["connection_id"])
    )
    store.publish(
        datasets,
        {},
        {"runId": "governance-raw", "startedAt": NOW.isoformat()},
        ontology={},
    )


@pytest.mark.parametrize("separate_connection_root", [False, True])
def test_raw_connection_generation_serves_every_governance_section_without_ontology(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    separate_connection_root: bool,
) -> None:
    home = tmp_path / "aiops"
    connection = _connection(
        "a",
        expires_at=(NOW + timedelta(days=30)).isoformat(),
        last_sync=NOW.isoformat(),
    )
    datasets = {
        "entities/AdvisorRecommendation": [_advisor_row("/disks/orphan")],
        "entities/CostActual": [_cost_row("/disks/orphan")],
        "entities/Resource": [
            {
                "id": "/disks/orphan",
                "type": "microsoft.compute/disks",
                "subscriptionId": "sub-a",
                "properties": {"diskState": "Unattached"},
            }
        ],
        "entities/VirtualMachine": [],
        "entities/ArcServer": [],
        "entities/RoleAssignment": [
            _assignment(
                "assignment-a",
                principal="principal-a",
                role="/roles/owner",
                scope="/subscriptions/sub-a",
                principal_type="ServicePrincipal",
                changed=NOW - timedelta(days=200),
            )
        ],
        "entities/RoleDefinition": [_definition("/roles/owner", "Owner", ["*"])],
        "entities/ManagedIdentity": [
            {
                "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-a",
                "name": "id-a",
                "subscriptionId": "sub-a",
                "principalId": "managed-a",
            }
        ],
    }
    _publish_governance_generation(home, connection, datasets)
    monkeypatch.setattr(
        api_runtime, "aiops_home",
        lambda: tmp_path / "unrelated-home" if separate_connection_root else home,
    )
    if separate_connection_root:
        monkeypatch.setenv(api_runtime.ENV_CONNECTION_HOME, str(home))
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    principals = {
        READER_TOKEN: Principal(
            subject="scoped@example.com",
            grants=(Grant("reader", Scope({"subscription": {"sub-a"}})),),
        )
    }
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(home),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        governance_provider=lambda: None,
        governance_generation_provider=api_runtime._load_governance_generation_snapshot,
        settings_store=EnterpriseSettingsStore(),
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)

    expected = {
        "/api/v1/governance/finops/summary": ("savings_opportunity_count", 1),
        "/api/v1/governance/finops/opportunities": ("count", 1),
        "/api/v1/governance/finops/waste": ("count", 1),
        "/api/v1/governance/finops/attribution": ("count", 1),
        "/api/v1/governance/identity/summary": ("assignment_count", 1),
        "/api/v1/governance/identity/principals": ("count", 1),
        "/api/v1/governance/identity/least-privilege": ("candidate_count", 1),
        "/api/v1/governance/identity/non-human": ("count", 2),
        "/api/v1/governance/identity/stale-access": ("count", 1),
        "/api/v1/governance/identity/subscription-owners": ("count", 1),
        "/api/v1/governance/spn/credentials": ("count", 1),
    }
    for path, (field, value) in expected.items():
        response = client.get(path, headers=_headers())
        assert response.status_code == 200, (path, response.text)
        assert response.json()["data"][field] == value, path
        assert any(
            "empty results are not proven clean" in warning
            for warning in response.json().get("warnings", [])
        )


def test_governance_registry_uses_connection_boundary_without_resolving_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    root = tmp_path / "durable-connections"
    calls = []

    class Registry:
        def __init__(self, home):
            calls.append(home)

        def list(self, *, include_disabled):
            assert include_disabled is True
            return [{"connection_id": "durable-connection", "subscription_id": "sub-a"}]

    monkeypatch.setenv(api_runtime.ENV_CONNECTION_HOME, str(root))
    monkeypatch.setattr(api_runtime, "ConnectionRegistry", Registry)
    monkeypatch.setattr(
        api_runtime, "_onboarding_service",
        lambda *_args, **_kwargs: pytest.fail("Governance must not resolve credentials"),
    )

    assert api_runtime._governance_connections()[0]["connection_id"] == "durable-connection"
    assert calls == [str(root)]


def test_active_empty_governance_generation_is_not_reported_as_unsynced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection = _connection("a", expires_at=None, last_sync=NOW.isoformat())
    _publish_governance_generation(
        home,
        connection,
        {
            f"entities/{entity_type}": []
            for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
        },
    )
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    snapshot = api_runtime._load_governance_generation_snapshot(
        Scope({"subscription": {"sub-a"}})
    )

    assert snapshot is not None
    assert snapshot.rows("RoleAssignment") == []
    assert [row["connection_id"] for row in snapshot.connections] == ["conn-a"]


def test_missing_governance_dataset_declarations_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection = _connection("a", expires_at=None)
    _publish_governance_generation(home, connection, {})
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert snapshot.generation_available is False


def test_governance_rows_preserve_connection_and_business_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection = {
        **_connection("a", expires_at=None),
        "metadata": {
            "business": {
                "application": "checkout",
                "business_service": "payments",
                "environment": "production",
                "project_owner": "platform-team",
            }
        },
    }
    _publish_governance_generation(
        home,
        connection,
        {
            **{
                f"entities/{entity_type}": []
                for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
            },
            "entities/AdvisorRecommendation": [_advisor_row("/disks/orphan")],
        },
    )
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    snapshot = api_runtime._load_governance_generation_snapshot(
        Scope({
            "subscription_connection": {"conn-a"},
            "business_service": {"payments"},
            "application": {"checkout"},
            "environment": {"production"},
            "owner": {"platform-team"},
        })
    )

    assert snapshot is not None
    row = snapshot.rows("AdvisorRecommendation")[0]
    assert row["connection_id"] == "conn-a"
    assert row["business_service"] == "payments"
    assert row["application"] == "checkout"
    assert row["environment"] == "production"
    assert row["owner"] == "platform-team"


@pytest.mark.parametrize(
    "row",
    [
        {"id": "/resources/a", "subscriptionId": "sub-b"},
        {
            "id": "/assignments/a",
            "subscriptionId": "sub-a",
            "assignmentScope": "/subscriptions/sub-b",
        },
    ],
)
def test_governance_entity_rejects_scope_conflicts(row: dict) -> None:
    with pytest.raises(PermissionError, match="conflicts"):
        api_runtime._governance_entity(
            "RoleAssignment",
            row,
            connection_scope={
                "subscription_id": "sub-a",
                "connection_id": "conn-a",
            },
        )


def test_governance_snapshot_scopes_connections_by_nested_business_metadata() -> None:
    connection = {
        **_connection("a", expires_at=None),
        "metadata": {
            "business": {
                "business_service": "payments",
                "environment": "production",
            }
        },
    }
    snapshot = GovernanceSnapshot(
        [],
        connections=[
            {
                **connection,
                **api_runtime._governance_connection_scope(connection),
            }
        ],
    )

    scoped = snapshot.scoped(
        Scope({
            "business_service": {"payments"},
            "environment": {"production"},
        })
    )

    assert [row["connection_id"] for row in scoped.connections] == ["conn-a"]


def test_governance_reader_keeps_healthy_connections_when_one_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection_a = _connection("a", expires_at=None)
    connection_b = {
        **_connection("b", expires_at=None),
        "subscription_id": "sub-b",
    }
    _publish_governance_generation(
        home,
        connection_a,
        {
            **{
                f"entities/{entity_type}": []
                for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
            },
            "entities/RoleAssignment": [
                _assignment("a", principal="principal-a")
            ],
        },
    )
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(
        api_runtime,
        "_governance_connections",
        lambda: [connection_a, connection_b],
    )

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert [row["principalId"] for row in snapshot.rows("RoleAssignment")] == [
        "principal-a"
    ]
    assert {row["connection_id"] for row in snapshot.connections} == {
        "conn-a",
        "conn-b",
    }
    assert any("conn-b" in warning for warning in snapshot.warnings)


def test_failed_connection_does_not_leak_rows_or_poison_later_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_a = _connection("a", expires_at=None)
    connection_b = {
        **_connection("b", expires_at=None),
        "subscription_id": "sub-b",
    }
    empty_hash = api_runtime._governance_integrity_hash([])
    row = {"id": "/resources/healthy", "subscriptionId": "sub-b"}
    row_hash = api_runtime._governance_integrity_hash([row])

    class _Store:
        is_remote = False

        def __init__(self, root: str) -> None:
            self.connection_id = root.rsplit("/", 1)[-1]

    class _Resolver:
        def __init__(self, store: _Store) -> None:
            self.store = store

        def resolve(self) -> SimpleNamespace:
            return SimpleNamespace(active_generation=self.store.connection_id)

        def read_metadata(self, _name: str, *, selection) -> dict:
            return {
                "startedAt": NOW.isoformat(),
                "datasets": {
                    f"entities/{entity_type}": {
                        "rowCount": 1 if entity_type == "Resource" else 0,
                        "integrityHash": (
                            row_hash if entity_type == "Resource" else empty_hash
                        ),
                    }
                    for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
                },
            }

    def read(_store, generation, name, **_kwargs):
        if generation == "conn-a" and name == "entities/VirtualMachine":
            raise ValueError("late connection failure")
        if name == "entities/Resource":
            value = {
                "id": f"/resources/{generation}",
                "subscriptionId": "sub-a" if generation == "conn-a" else "sub-b",
            }
            return [value], 80
        return [], 0

    monkeypatch.setattr("storage.datasets.DatasetStore", _Store)
    monkeypatch.setattr(
        api_runtime,
        "_governance_active_generation",
        lambda store: _Resolver(store).resolve().active_generation,
    )
    monkeypatch.setattr(
        api_runtime,
        "_read_governance_manifest",
        lambda _store, _generation: _Resolver(_store).read_metadata(
            "manifest.json",
            selection=None,
        ),
    )
    monkeypatch.setattr(api_runtime, "_read_governance_dataset", read)
    monkeypatch.setattr(
        api_runtime,
        "_governance_connections",
        lambda: [connection_a, connection_b],
    )
    monkeypatch.setattr(api_runtime, "_MAX_GOVERNANCE_ROWS", 1)
    monkeypatch.setattr(api_runtime, "_MAX_GOVERNANCE_BYTES", 100)

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert [row["id"] for row in snapshot.rows("Resource")] == [
        "/resources/conn-b"
    ]
    assert {row["connection_id"] for row in snapshot.connections} == {
        "conn-a",
        "conn-b",
    }


def test_disabled_only_governance_scope_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = {**_connection("a", expires_at=None), "is_active": False}
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert snapshot.generation_available is False
    assert [row["connection_id"] for row in snapshot.connections] == ["conn-a"]


def test_registry_only_snapshot_serves_spn_but_not_finops(tmp_path) -> None:
    snapshot = GovernanceSnapshot(
        [],
        connections=[
            {**_connection("disabled", expires_at=None), "is_active": False}
        ],
        generation_available=False,
        warnings=["No active governance generation is available"],
    )
    client = _client(tmp_path, snapshot=snapshot)

    spn = client.get("/api/v1/governance/spn/credentials", headers=_headers())
    finops = client.get("/api/v1/governance/finops/summary", headers=_headers())
    onboarding = client.get(
        "/api/v1/governance/exports/subscription_onboarding",
        headers=_headers(),
    )

    assert spn.status_code == 200
    assert spn.json()["data"]["count"] == 1
    assert spn.json()["evidence"][0]["source_table"] == "connection_registry"
    assert finops.status_code == 503
    assert onboarding.status_code == 200
    assert onboarding.json()["evidence"][0]["source_table"] == "connection_registry"


def test_failed_active_generation_remains_visible_to_spn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    connection = _connection("failed", expires_at=None)
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: tmp_path / "aiops")
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert snapshot.generation_available is False
    assert [row["connection_id"] for row in snapshot.connections] == ["conn-failed"]


def test_disabled_connection_remains_visible_to_spn_with_active_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    active = _connection("active", expires_at=None)
    disabled = {
        **_connection("disabled", expires_at=None),
        "is_active": False,
    }
    _publish_governance_generation(
        home,
        active,
        {
            f"entities/{entity_type}": []
            for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
        },
    )
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(
        api_runtime,
        "_governance_connections",
        lambda: [active, disabled],
    )

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert {row["connection_id"] for row in snapshot.connections} == {
        "conn-active",
        "conn-disabled",
    }


def test_governance_reader_rejects_oversized_and_corrupt_generations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection = _connection("a", expires_at=None)
    datasets = {
        f"entities/{entity_type}": []
        for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
    }
    datasets["entities/Resource"] = [{
        "id": "/resources/a",
        "subscriptionId": "sub-a",
        "properties": {"payload": "x" * 100},
    }]
    _publish_governance_generation(home, connection, datasets)
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])
    monkeypatch.setattr(api_runtime, "_MAX_GOVERNANCE_BYTES", 32)

    oversized = api_runtime._load_governance_generation_snapshot(Scope({}))
    assert oversized is not None
    assert oversized.generation_available is False

    monkeypatch.setattr(api_runtime, "_MAX_GOVERNANCE_BYTES", 1024 * 1024)
    store = DatasetStore(
        api_runtime._connection_dataset_dir(str(home), connection["connection_id"])
    )
    generation = store.current_generation()
    assert generation is not None
    resource_path = (Path(generation) / "entities/Resource").with_suffix(".jsonl")
    resource_path.write_text(
        json.dumps({"id": "/resources/tampered", "subscriptionId": "sub-a"})
        + "\n"
    )

    corrupt = api_runtime._load_governance_generation_snapshot(Scope({}))
    assert corrupt is not None
    assert corrupt.generation_available is False


def test_governance_manifest_is_bounded_and_integrity_checked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = DatasetStore(tmp_path / "store")
    store.publish(
        {
            f"entities/{entity_type}": []
            for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
        },
        {},
        {"runId": "generation-1", "startedAt": NOW.isoformat()},
        ontology={},
    )
    generation = store.current_generation()
    assert generation is not None
    manifest_path = Path(generation) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["startedAt"] = (NOW + timedelta(days=1)).isoformat()
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="integrity"):
        api_runtime._read_governance_manifest(store, str(generation))

    monkeypatch.setattr(api_runtime, "_MAX_GOVERNANCE_MANIFEST_BYTES", 16)
    with pytest.raises(ValueError, match="byte limit"):
        api_runtime._read_governance_manifest(store, str(generation))


def test_governance_generation_pointer_is_bounded(tmp_path) -> None:
    store = DatasetStore(tmp_path / "store")
    pointer = Path(store.pointer_path)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_bytes(
        b'{"active_generation":"'
        + b"x" * api_runtime._MAX_GOVERNANCE_POINTER_BYTES
        + b'"}'
    )

    with pytest.raises(ValueError, match="pointer exceeds its byte limit"):
        api_runtime._governance_active_generation(store)


def test_stale_governance_source_status_qualifies_snapshot_time(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection = _connection("a", expires_at=None)
    stale_at = (NOW - timedelta(days=2)).isoformat()
    datasets = {
        f"entities/{entity_type}": []
        for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
    }
    datasets["entities/RoleAssignment"] = [
        _assignment("a", principal="principal-a")
    ]
    datasets["situations/source_status"] = [{
        "partition_key": "conn-a:role_assignments",
        "connection_id": "conn-a",
        "source_family": "role_assignments",
        "attempted_generation": "governance-raw",
        "effective_generation": "previous-generation",
        "attempted_at": NOW.isoformat(),
        "last_success_at": stale_at,
        "row_count": 0,
        "represented_count": 1,
        "expected_count": 1,
        "completeness": "stale",
        "safe_error_code": "provider_unavailable",
        "safe_error_summary": "Role assignment refresh failed",
    }]
    _publish_governance_generation(home, connection, datasets)
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert snapshot.observed_at == stale_at
    assert any("role_assignments" in warning for warning in snapshot.warnings)


def test_failed_governance_source_without_observation_time_is_not_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection = _connection("a", expires_at=None)
    datasets = {
        f"entities/{entity_type}": []
        for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
    }
    datasets["situations/source_status"] = [{
        "partition_key": "conn-a:cost_actuals",
        "connection_id": "conn-a",
        "source_family": "cost_actuals",
        "attempted_generation": "governance-raw",
        "effective_generation": "",
        "attempted_at": NOW.isoformat(),
        "last_success_at": "",
        "row_count": 0,
        "represented_count": 0,
        "expected_count": 1,
        "status": "unavailable",
        "availability": "unavailable",
        "freshness": "unknown",
        "completeness": "unavailable",
        "safe_error_code": "provider_unavailable",
        "safe_error_summary": "Cost refresh failed",
    }]
    _publish_governance_generation(home, connection, datasets)
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert snapshot.observed_at == ""
    assert any("cost_actuals" in warning for warning in snapshot.warnings)


def test_any_degraded_source_without_success_time_makes_snapshot_time_unknown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection = _connection("a", expires_at=None)
    datasets = {
        f"entities/{entity_type}": []
        for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
    }
    datasets["situations/source_status"] = [
        {
            "partition_key": "conn-a:role_assignments",
            "connection_id": "conn-a",
            "source_family": "role_assignments",
            "attempted_generation": "governance-raw",
            "effective_generation": "previous",
            "attempted_at": NOW.isoformat(),
            "last_success_at": (NOW - timedelta(days=1)).isoformat(),
            "row_count": 0,
            "represented_count": 1,
            "expected_count": 1,
            "completeness": "stale",
            "safe_error_code": "provider_unavailable",
            "safe_error_summary": "Role refresh failed",
        },
        {
            "partition_key": "conn-a:cost_actuals",
            "connection_id": "conn-a",
            "source_family": "cost_actuals",
            "attempted_generation": "governance-raw",
            "effective_generation": "",
            "attempted_at": NOW.isoformat(),
            "last_success_at": "",
            "row_count": 0,
            "represented_count": 0,
            "expected_count": 1,
            "completeness": "unavailable",
            "safe_error_code": "provider_unavailable",
            "safe_error_summary": "Cost refresh failed",
        },
    ]
    _publish_governance_generation(home, connection, datasets)
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])

    snapshot = api_runtime._load_governance_generation_snapshot(Scope({}))

    assert snapshot is not None
    assert snapshot.observed_at == ""


def test_governance_generation_reader_does_not_load_an_unauthorized_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    home = tmp_path / "aiops"
    connection_a = _connection("a", expires_at=None)
    connection_b = {
        **_connection("b", expires_at=None),
        "subscription_id": "sub-b",
    }
    _publish_governance_generation(
        home,
        connection_a,
        {
            **{
                f"entities/{entity_type}": []
                for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
            },
            "entities/RoleAssignment": [
                _assignment("a", principal="principal-a")
            ],
        },
    )
    _publish_governance_generation(
        home,
        connection_b,
        {
            **{
                f"entities/{entity_type}": []
                for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
            },
            "entities/RoleAssignment": [
                {
                    **_assignment("b", principal="principal-b"),
                    "subscriptionId": "sub-b",
                    "assignmentScope": "/subscriptions/sub-b",
                }
            ]
        },
    )
    monkeypatch.setattr(api_runtime, "aiops_home", lambda: home)
    monkeypatch.setattr(
        api_runtime,
        "_governance_connections",
        lambda: [connection_a, connection_b],
    )

    snapshot = api_runtime._load_governance_generation_snapshot(
        Scope({"subscription": {"sub-a"}})
    )

    assert snapshot is not None
    assert [row["principalId"] for row in snapshot.rows("RoleAssignment")] == [
        "principal-a"
    ]
    assert [row["connection_id"] for row in snapshot.connections] == ["conn-a"]


def test_default_runtime_wires_connection_scoped_governance_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "aiops"))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv(
        "AIOPS_API_TOKENS",
        json.dumps(
            {
                READER_TOKEN: {
                    "subject": "reader@example.com",
                    "grants": [{"role": "reader", "scope": {}}],
                }
            }
        ),
    )

    context = api_runtime.build_context()

    assert (
        context.governance_generation_provider
        is api_runtime._load_governance_generation_snapshot
    )


@pytest.mark.parametrize(
    ("declared_rows", "available"),
    [
        (api_runtime._MAX_GOVERNANCE_ROWS, True),
        (api_runtime._MAX_GOVERNANCE_ROWS + 1, False),
    ],
)
def test_governance_generation_reader_enforces_aggregate_row_bound_before_read(
    monkeypatch: pytest.MonkeyPatch,
    declared_rows: int,
    available: bool,
) -> None:
    connection = _connection("a", expires_at=None)
    reads: list[tuple[str, int]] = []

    class _Store:
        is_remote = False

        def __init__(self, _root: str) -> None:
            pass

    class _Resolver:
        def __init__(self, _store: _Store) -> None:
            pass

        def resolve(self) -> SimpleNamespace:
            return SimpleNamespace(active_generation="generation")

    empty_hash = api_runtime._governance_integrity_hash([])
    manifest = {
        "startedAt": NOW.isoformat(),
        "datasets": {
            f"entities/{entity_type}": {
                "rowCount": (
                    declared_rows if entity_type == "RoleAssignment" else 0
                ),
                "integrityHash": empty_hash,
            }
            for entity_type in api_runtime._GOVERNANCE_ENTITY_DATASETS
        },
    }

    monkeypatch.setattr("storage.datasets.DatasetStore", _Store)
    monkeypatch.setattr(
        api_runtime,
        "_governance_active_generation",
        lambda _store: "generation",
    )
    monkeypatch.setattr(
        api_runtime,
        "_read_governance_manifest",
        lambda _store, _generation: manifest,
    )
    monkeypatch.setattr(api_runtime, "_governance_connections", lambda: [connection])
    monkeypatch.setattr(
        api_runtime,
        "_read_governance_dataset",
        lambda _store, _generation, name, **kwargs: (
            reads.append((name, kwargs["expected_rows"])) or ([], 0)
        ),
    )

    snapshot = api_runtime._load_governance_generation_snapshot(
        Scope({"subscription": {"sub-a"}})
    )

    assert snapshot is not None
    assert snapshot.generation_available is available
    assert bool(reads) is available


def test_governance_dataset_reader_rejects_rows_beyond_manifest_count(tmp_path) -> None:
    generation = tmp_path / "generation"
    path = generation / "entities" / "RoleAssignment.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"id":"a"}\n{"id":"b"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="exceeds its declared row count"):
        api_runtime._read_governance_dataset(
            SimpleNamespace(is_remote=False),
            str(generation),
            "entities/RoleAssignment",
            expected_rows=1,
        )


@pytest.mark.parametrize("contents", [None, " \n" * 32])
def test_governance_zero_row_dataset_requires_bounded_artifact(
    tmp_path,
    contents: str | None,
) -> None:
    generation = tmp_path / "generation"
    path = generation / "entities" / "RoleAssignment.jsonl"
    path.parent.mkdir(parents=True)
    if contents is not None:
        path.write_text(contents, encoding="utf-8")

    if contents is None:
        with pytest.raises(FileNotFoundError):
            api_runtime._read_governance_dataset(
                SimpleNamespace(is_remote=False),
                str(generation),
                "entities/RoleAssignment",
                expected_rows=0,
                expected_integrity_hash=api_runtime._governance_integrity_hash([]),
            )
    else:
        with pytest.raises(ValueError, match="byte limit"):
            api_runtime._read_governance_dataset(
                SimpleNamespace(is_remote=False),
                str(generation),
                "entities/RoleAssignment",
                expected_rows=0,
                expected_integrity_hash=api_runtime._governance_integrity_hash([]),
                max_bytes=16,
            )


def test_identity_summary_returns_evidence_and_scope(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    response = client.get("/api/v1/governance/identity/summary", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    # The envelope carries evidence as a list of records.
    assert body["evidence"][0]["source_engine"].endswith("IdentityRiskEngine")
    assert body["evidence"][0]["source_table"] == "connection_generation_entities"
    assert "scope" in body


def test_identity_least_privilege_is_scoped_paginated_and_qualified(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())

    response = client.get(
        "/api/v1/governance/identity/least-privilege?subscription=sub-a&offset=0&limit=1",
        headers=_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["candidate_count"] == 1
    assert body["data"]["limit"] == 1
    assert body["data"]["effective_access"] == "not_evaluated"
    assert body["data"]["candidates"][0]["principal_id"] == "p-a"
    assert body["scope"]["subscription"] == ["sub-a"]
    assert body["evidence"][0]["source_engine"].endswith("IdentityRiskEngine")


@pytest.mark.parametrize("query", ["offset=-1", "limit=0", "limit=101"])
def test_identity_least_privilege_rejects_invalid_pagination(tmp_path, query):
    response = _client(tmp_path, snapshot=_snapshot()).get(
        f"/api/v1/governance/identity/least-privilege?{query}",
        headers=_headers(),
    )

    assert response.status_code == 400


def test_empty_identity_data_is_warned_about_not_silently_empty(tmp_path):
    client = _client(tmp_path, snapshot=GovernanceSnapshot([], observed_at="2026-01-01T00:00:00Z"))
    response = client.get("/api/v1/governance/identity/principals", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["count"] == 0
    assert any("not a statement" in warning.lower() for warning in body["warnings"])


def test_role_definitions_alone_do_not_claim_role_assignment_coverage(tmp_path):
    snapshot = GovernanceSnapshot([_entity("RoleDefinition", "/roles/reader", _definition("/roles/reader", "Reader"))])
    body = _client(tmp_path, snapshot).get("/api/v1/governance/identity/summary", headers=_headers()).json()
    assert body["data"]["assignment_count"] == 0
    assert any("No role assignment data" in warning for warning in body["warnings"])


def test_governance_snapshot_warnings_reach_finops_and_identity_routes(tmp_path):
    warning = "Governance data is unavailable for connection conn-b"
    client = _client(
        tmp_path,
        snapshot=GovernanceSnapshot(
            [],
            observed_at="2026-01-01T00:00:00Z",
            warnings=[warning],
        ),
    )

    finops = client.get("/api/v1/governance/finops/summary", headers=_headers())
    identity = client.get(
        "/api/v1/governance/identity/principals",
        headers=_headers(),
    )

    assert warning in finops.json()["warnings"]
    assert warning in identity.json()["warnings"]


def test_executive_export_cites_generation_and_connection_registry(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())

    response = client.get(
        "/api/v1/governance/exports/executive",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert {item["source_table"] for item in response.json()["evidence"]} == {
        "connection_generation_entities",
        "connection_registry",
    }


@pytest.mark.parametrize(
    ("kind", "source_table"),
    [
        ("network_design", "network_provider"),
        ("firewall_nsg", "network_provider"),
        ("vulnerability_exposure", "vulnerability_provider"),
        ("remediation", "remediation_provider"),
    ],
)
def test_independent_audit_exports_do_not_borrow_governance_freshness(
    tmp_path,
    kind: str,
    source_table: str,
) -> None:
    client = _client(tmp_path, snapshot=_snapshot())

    response = client.get(
        f"/api/v1/governance/exports/{kind}",
        headers=_headers(),
    )

    assert response.status_code == 200
    evidence = response.json()["evidence"][0]
    assert evidence["source_table"] == source_table
    assert evidence["timestamp"] == ""
    assert evidence["confidence"] == "unknown"


def test_finops_summary_exposes_unavailable_metrics(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    response = client.get("/api/v1/governance/finops/summary", headers=_headers())
    assert response.status_code == 200
    metrics = {item["metric"] for item in response.json()["data"]["unavailable_metrics"]}
    assert "actual_spend" in metrics


def test_access_review_pack_is_served_per_audience(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    for audience in ("service_owner", "security", "auditor"):
        response = client.get(
            f"/api/v1/governance/access-reviews/{audience}", headers=_headers()
        )
        assert response.status_code == 200
        assert response.json()["data"]["audience"] == audience


def test_unknown_access_review_audience_is_rejected_by_the_route(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    response = client.get(
        "/api/v1/governance/access-reviews/marketing", headers=_headers()
    )
    # The app translates validation failures onto its own error contract.
    assert response.status_code == 400


def test_audit_export_includes_provenance(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    response = client.get("/api/v1/governance/exports/identity", headers=_headers())
    assert response.status_code == 200
    assert response.json()["data"]["provenance"]["source_engines"]


def test_settings_can_be_read_by_a_reader(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/v1/governance/settings", headers=_headers())
    assert response.status_code == 200
    assert response.json()["data"]["agent_policy"]["require_human_approval"] is True


def test_settings_update_requires_write_permission(tmp_path):
    client = _client(tmp_path)
    response = client.patch(
        "/api/v1/governance/settings",
        json={"retention_policy": {"audit_log_days": 30}},
        headers=_headers(READER_TOKEN),
    )
    assert response.status_code == 403


def test_admin_can_update_settings(tmp_path):
    client = _client(tmp_path)
    response = client.patch(
        "/api/v1/governance/settings",
        json={"expected_revision": 0, "reason": "Review retention",
              "changes": {"retention_policy": {"audit_log_days": 30}}},
        headers=_headers(ADMIN_TOKEN),
    )
    assert response.status_code == 200
    assert response.json()["data"]["retention_policy"]["audit_log_days"] == 30


def test_invalid_settings_update_is_rejected_with_a_clear_error(tmp_path):
    client = _client(tmp_path)
    response = client.patch(
        "/api/v1/governance/settings",
        json={"expected_revision": 0, "reason": "Review retention",
              "changes": {"retention_policy": {"audit_log_days": 999999}}},
        headers=_headers(ADMIN_TOKEN),
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Subscription isolation: the criterion the whole feature must not weaken.
# --------------------------------------------------------------------------


def _scoped_client(tmp_path, subscription: str):
    """A reader whose grant is confined to a single subscription."""
    scoped = Scope({"subscription": frozenset({subscription})})
    principals = {
        READER_TOKEN: Principal(
            subject="scoped@example.com", grants=(Grant("reader", scoped),)
        ),
    }
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        governance_provider=lambda: _snapshot(),
        settings_store=EnterpriseSettingsStore(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def test_a_scoped_reader_never_sees_another_subscription(tmp_path):
    """sub-a's reader must not observe sub-b's principals through any route."""
    client = _scoped_client(tmp_path, "sub-a")
    response = client.get(
        "/api/v1/governance/identity/principals", headers=_headers()
    )
    assert response.status_code == 200
    principals = response.json()["data"]["principals"]
    seen = {row["principal_id"] for row in principals}
    assert "p-b" not in seen, "a scoped reader observed another subscription"
    assert seen == {"p-a"}


def test_scoped_isolation_holds_for_audit_exports(tmp_path):
    """An evidence pack is a bulk export: it must obey the same boundary."""
    client = _scoped_client(tmp_path, "sub-a")
    response = client.get("/api/v1/governance/exports/identity", headers=_headers())
    assert response.status_code == 200
    body = json.dumps(response.json())
    assert "p-b" not in body, "an export leaked another subscription's principal"
    assert "p-a" in body
