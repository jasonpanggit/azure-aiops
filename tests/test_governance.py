"""Tests for the enterprise governance engines and routes.

These lean deliberately on realistic row shapes -- ontology entities carrying
their source fields inside ``payload_json`` -- because the bug most likely to
ship in this area is a field that survives the engine but not the pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

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
    result = store.update({"retention_policy": {"audit_log_days": 30}})
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
        onboarding=SubscriptionOnboardingService(tmp_path / "hermes"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        governance_provider=lambda: snapshot,
        settings_store=EnterpriseSettingsStore(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _headers(token: str = READER_TOKEN) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_governance_routes_report_unavailable_before_any_sync(tmp_path):
    """No data must never be presented as a clean bill of health."""
    client = _client(tmp_path, snapshot=None)
    response = client.get("/api/v1/governance/identity/summary", headers=_headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_identity_summary_returns_evidence_and_scope(tmp_path):
    client = _client(tmp_path, snapshot=_snapshot())
    response = client.get("/api/v1/governance/identity/summary", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    # The envelope carries evidence as a list of records.
    assert body["evidence"][0]["source_engine"].endswith("IdentityRiskEngine")
    assert "scope" in body


def test_empty_identity_data_is_warned_about_not_silently_empty(tmp_path):
    client = _client(tmp_path, snapshot=GovernanceSnapshot([], observed_at="2026-01-01T00:00:00Z"))
    response = client.get("/api/v1/governance/identity/principals", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["count"] == 0
    assert any("not a statement" in warning.lower() for warning in body["warnings"])


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
        json={"retention_policy": {"audit_log_days": 30}},
        headers=_headers(ADMIN_TOKEN),
    )
    assert response.status_code == 200
    assert response.json()["data"]["retention_policy"]["audit_log_days"] == 30


def test_invalid_settings_update_is_rejected_with_a_clear_error(tmp_path):
    client = _client(tmp_path)
    response = client.patch(
        "/api/v1/governance/settings",
        json={"retention_policy": {"audit_log_days": 999999}},
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
        onboarding=SubscriptionOnboardingService(tmp_path / "hermes"),
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
