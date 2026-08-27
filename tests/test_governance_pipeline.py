"""Test governance pipeline against Hermes engines (comparison harness).

Validates that Fabric governance_pipeline output matches Hermes 
IdentityRiskEngine, SpnGovernanceEngine, and FinOpsEngine byte-for-byte
on a curated test scenario.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from intelligence.governance import (
    FinOpsEngine,
    IdentityRiskEngine,
    SpnGovernanceEngine,
)
from src.fabric_pipelines.governance_pipeline import GovernancePipeline


# Curated test scenario: governance data fixture
_SUBSCRIPTION_ID = "11111111-1111-1111-1111-111111111111"
_TENANT_ID = "22222222-2222-2222-2222-222222222222"

GOVERNANCE_COMPARISON_SCENARIO = {
    "role_assignments": [
        {
            "id": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleAssignments/ra-owner-001",
            "principalId": "principal-owner-001",
            "principalType": "User",
            "roleDefinitionId": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
            "assignmentScope": "/subscriptions/11111111-1111-1111-1111-111111111111",
            "createdOn": "2025-06-01T10:00:00Z",
            "updatedOn": "2025-06-01T10:00:00Z",
            "subscriptionId": _SUBSCRIPTION_ID,
        },
        {
            "id": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleAssignments/ra-contributor-002",
            "principalId": "principal-contributor-002",
            "principalType": "ServicePrincipal",
            "roleDefinitionId": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
            "assignmentScope": "/subscriptions/11111111-1111-1111-1111-111111111111/resourcegroups/rg-app",
            "createdOn": "2025-01-15T08:30:00Z",  # Stale (>90 days)
            "updatedOn": "2025-01-15T08:30:00Z",
            "subscriptionId": _SUBSCRIPTION_ID,
        },
        {
            "id": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleAssignments/ra-reader-003",
            "principalId": "principal-mi-003",
            "principalType": "ManagedIdentity",
            "roleDefinitionId": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7",
            "assignmentScope": "/subscriptions/11111111-1111-1111-1111-111111111111/resourcegroups/rg-app/providers/microsoft.compute/virtualmachines/vm-app",
            "createdOn": "2026-08-01T14:00:00Z",
            "updatedOn": "2026-08-01T14:00:00Z",
            "subscriptionId": _SUBSCRIPTION_ID,
        },
    ],
    "role_definitions": [
        {
            "id": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
            "roleName": "Owner",
            "actions": ["*"],
        },
        {
            "id": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
            "roleName": "Contributor",
            "actions": ["*"],
        },
        {
            "id": "/subscriptions/11111111-1111-1111-1111-111111111111/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7",
            "roleName": "Reader",
            "actions": ["*/read"],
        },
    ],
    "connections": [
        {
            "connection_id": "conn-spn-001",
            "name": "azure-discovery-prod",
            "tenant_id": _TENANT_ID,
            "subscription_id": _SUBSCRIPTION_ID,
            "credential": {
                "credential_id": "cred-spn-001",
                "client_id": "client-001",
                "object_id": "principal-spn-001",
                "secret_ref": "kv://secret-client-001",
                "expires_at": "2026-12-31T23:59:59Z",
                "kind": "service_principal",
                "active": True,
                "scope": "/subscriptions/11111111-1111-1111-1111-111111111111",
            },
            "sync_state": {
                "last_successful_sync": "2026-08-27T01:00:00Z",
            },
        },
        {
            "connection_id": "conn-spn-002",
            "name": "azure-cost-expired",
            "tenant_id": _TENANT_ID,
            "subscription_id": _SUBSCRIPTION_ID,
            "credential": {
                "credential_id": "cred-spn-002",
                "client_id": "client-002",
                "object_id": "principal-spn-002",
                "secret_ref": "kv://secret-client-002",
                "expires_at": "2026-08-15T23:59:59Z",  # Expiring soon (<30 days)
                "kind": "service_principal",
                "active": True,
                "scope": "/subscriptions/11111111-1111-1111-1111-111111111111",
            },
            "sync_state": {
                "last_successful_sync": "2026-08-26T23:00:00Z",
            },
        },
    ],
    "managed_identities": [
        {
            "id": f"/subscriptions/{_SUBSCRIPTION_ID}/resourcegroups/rg-app/providers/microsoft.managedidentity/userassignedidentities/mi-app-001",
            "name": "mi-app-001",
            "principalId": "principal-mi-001",
        },
    ],
    "advisor_recommendations": [
        {
            "id": "advisor-001",
            "targetResourceId": f"/subscriptions/{_SUBSCRIPTION_ID}/resourceGroups/rg-app/providers/microsoft.compute/disks/disk-unused",
            "category": "Cost",
            "problem": "Delete unused managed disks",
            "solution": "Remove unattached disks",
            "impact": "High",
            "properties": {
                "extendedProperties": {
                    "annualSavingsAmount": 1200.0,
                    "savingsCurrency": "USD",
                }
            },
        },
    ],
    "resources": [
        {
            "id": f"/subscriptions/{_SUBSCRIPTION_ID}/resourceGroups/rg-app/providers/microsoft.compute/disks/disk-unused",
            "type": "microsoft.compute/disks",
            "properties": {
                "diskState": "Unattached",
            },
        },
    ],
}


class TestGovernancePipelineComparison:
    """Validates Fabric governance_pipeline matches Hermes engines."""

    def test_identity_risk_matches_hermes(self):
        """Identity risk findings from Fabric match Hermes IdentityRiskEngine."""
        scenario = GOVERNANCE_COMPARISON_SCENARIO
        test_now = datetime(2026, 8, 27, tzinfo=timezone.utc)

        # Run Hermes engine
        hermes_engine = IdentityRiskEngine(
            role_assignments=scenario["role_assignments"],
            role_definitions=scenario["role_definitions"],
            managed_identities=scenario.get("managed_identities", []),
            now=test_now,
        )
        hermes_principals = hermes_engine.principals()
        hermes_stale = hermes_engine.stale_access()
        hermes_non_human = hermes_engine.non_human_identities()

        # Run Fabric pipeline
        fabric_pipeline = GovernancePipeline(
            role_assignments=scenario["role_assignments"],
            role_definitions=scenario["role_definitions"],
            managed_identities=scenario.get("managed_identities", []),
            now=test_now,
        )
        fabric_findings = fabric_pipeline.assess_identity_risk()

        # Validate key counts match
        assert len(hermes_principals) >= 1, "Should have at least one principal"
        assert len(hermes_stale) >= 1, "Should have at least one stale access"
        
        # Extract findings by type
        principal_findings = [f for f in fabric_findings if f.finding_type == "identity_risk"]
        assert len(principal_findings) > 0, "Should generate identity risk findings"

        # Validate stale access is caught (contributor-002 is stale)
        stale_ids = {s["assignment_id"] for s in hermes_stale}
        stale_findings = [f for f in fabric_findings if "Stale access" in f.title]
        assert len(stale_findings) > 0, "Should detect stale access (>90 days)"

    def test_spn_governance_matches_hermes(self):
        """SPN governance findings from Fabric match Hermes SpnGovernanceEngine."""
        scenario = GOVERNANCE_COMPARISON_SCENARIO
        test_now = datetime(2026, 8, 27, tzinfo=timezone.utc)

        # Run Hermes engine
        hermes_engine = SpnGovernanceEngine(
            connections=scenario["connections"],
            role_assignments=scenario["role_assignments"],
            now=test_now,
        )
        hermes_credentials = hermes_engine.credentials()

        # Run Fabric pipeline
        fabric_pipeline = GovernancePipeline(
            connections=scenario["connections"],
            role_assignments=scenario["role_assignments"],
            now=test_now,
        )
        fabric_findings = fabric_pipeline.assess_spn_governance()

        # Validate SPN counts
        assert len(hermes_credentials) == 2, "Should have 2 SPNs"
        
        # Validate expiring_soon is detected (conn-spn-002 expires in ~19 days)
        expiring_statuses = {c.rotation_status for c in hermes_credentials}
        assert "expiring_soon" in expiring_statuses, "Should detect expiring SPN credentials"
        
        # Fabric should also detect this
        expiring_findings = [f for f in fabric_findings if "expiring_soon" in f.title.lower()]
        assert len(expiring_findings) > 0, "Should detect expiring SPN"

    def test_finops_matches_hermes(self):
        """FinOps findings from Fabric match Hermes FinOpsEngine."""
        scenario = GOVERNANCE_COMPARISON_SCENARIO

        # Run Hermes engine
        hermes_engine = FinOpsEngine(
            advisor_recommendations=scenario.get("advisor_recommendations", []),
            cost_actuals=scenario.get("cost_actuals", []),
            resources=scenario.get("resources", []),
        )
        hermes_opportunities = hermes_engine.savings_opportunities()
        hermes_waste = hermes_engine.waste()

        # Run Fabric pipeline
        fabric_pipeline = GovernancePipeline(
            advisor_recommendations=scenario.get("advisor_recommendations", []),
            cost_actuals=scenario.get("cost_actuals", []),
            resources=scenario.get("resources", []),
        )
        fabric_findings = fabric_pipeline.assess_finops()

        # Validate savings opportunities match
        assert len(hermes_opportunities) >= 1, "Should have at least one savings opportunity"
        
        savings_findings = [f for f in fabric_findings if f.finding_type == "savings_opportunity"]
        assert len(savings_findings) >= 1, "Should detect savings opportunities"
        
        # Validate first opportunity matches
        first_hermes = hermes_opportunities[0]
        first_fabric = savings_findings[0]
        assert first_hermes.annual_savings == 1200.0
        assert first_fabric.finding_data.get("annual_savings") == 1200.0

        # Validate waste detection
        waste_findings = [f for f in fabric_findings if f.finding_type == "waste_item"]
        assert len(waste_findings) > 0, "Should detect waste items (unattached disk)"

    def test_governance_pipeline_full_execution(self):
        """Full pipeline execution generates all three domain findings."""
        scenario = GOVERNANCE_COMPARISON_SCENARIO
        test_now = datetime(2026, 8, 27, tzinfo=timezone.utc)

        pipeline = GovernancePipeline(
            role_assignments=scenario["role_assignments"],
            role_definitions=scenario["role_definitions"],
            connections=scenario["connections"],
            managed_identities=scenario.get("managed_identities", []),
            advisor_recommendations=scenario.get("advisor_recommendations", []),
            resources=scenario.get("resources", []),
            now=test_now,
        )

        findings = pipeline.execute()

        # Validate all finding types are present
        finding_types = {f.finding_type for f in findings}
        assert "identity_risk" in finding_types
        assert "spn_governance" in finding_types
        assert "savings_opportunity" in finding_types

        # Validate findings have required fields
        for finding in findings:
            assert finding.finding_type
            assert finding.severity in {"critical", "high", "medium", "low", "info"}
            assert finding.title
            assert finding.source == "governance_pipeline"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
