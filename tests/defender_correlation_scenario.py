"""Fixture builder for Defender-correlated remediation case tests.

Provides a small, hand-authored set of Defender signal rows (assessment,
alert, attack path/node, secure-score control) plus matching resource
dictionaries with and without business-context mapping, reused by every
plan in this phase that exercises ``DefenderRemediationCorrelator``.
"""

from __future__ import annotations

from typing import Any

from intelligence.remediation.dependency_analyzer import DependencyAnalyzer
from intelligence.remediation.defender_correlation import DefenderRemediationCorrelator
from intelligence.vulnerability.service import VulnerabilityIntelligenceService

MAPPED_RESOURCE_ID = (
    "/subscriptions/sub-1/resourcegroups/rg-prod/providers/"
    "microsoft.compute/virtualmachines/vm-payments"
)
UNMAPPED_RESOURCE_ID = (
    "/subscriptions/sub-1/resourcegroups/rg-shadow/providers/"
    "microsoft.compute/virtualmachines/vm-shadow-it"
)
UNMATCHED_WEAKNESS_RESOURCE_ID = (
    "/subscriptions/sub-1/resourcegroups/rg-prod/providers/"
    "microsoft.compute/virtualmachines/vm-orphan"
)


def _resource(**overrides: Any) -> dict[str, Any]:
    base = {
        "resource_key": MAPPED_RESOURCE_ID,
        "name": "vm-payments",
        "entity_type": "VirtualMachine",
        "application": "Payments API",
        "business_service": "Checkout",
        "owner": "Payments Product Owner",
        "environment": "Production",
        "business_criticality": "Mission Critical",
        "upstream_dependencies": ["API Gateway"],
        "downstream_dependencies": ["Ledger Writer"],
    }
    base.update(overrides)
    return base


def defender_resources() -> list[dict[str, Any]]:
    """Return resources: one fully business-mapped, one unmapped, one with no matching catalog action."""
    return [
        _resource(),
        _resource(
            resource_key=UNMAPPED_RESOURCE_ID,
            name="vm-shadow-it",
            application="",
            business_service="",
            owner="",
            environment="",
            business_criticality="",
            upstream_dependencies=[],
            downstream_dependencies=[],
        ),
        _resource(
            resource_key=UNMATCHED_WEAKNESS_RESOURCE_ID,
            name="vm-orphan",
            application="Ledger",
            business_service="Ledger Services",
            owner="Ledger Owner",
        ),
    ]


def defender_assessments() -> list[dict[str, Any]]:
    return [
        {
            "assessment_id": "assess-001",
            "target_resource_id": MAPPED_RESOURCE_ID,
            "resource_name": "vm-payments",
            "resource_type": "virtualMachines",
            "severity": "high",
            "status": "Unhealthy",
            "recommendation": "Enable disk encryption",
            "description": "Disk encryption is not enabled on this VM.",
            "subscription_id": "sub-1",
            "business_service": "Checkout",
            "application": "Payments API",
            "owner": "Payments Product Owner",
            "environment": "Production",
            "last_assessed_at": "2026-08-18T09:00:00Z",
            "cve_id": "",
        },
        {
            "assessment_id": "assess-002",
            "target_resource_id": UNMAPPED_RESOURCE_ID,
            "resource_name": "vm-shadow-it",
            "resource_type": "virtualMachines",
            "severity": "critical",
            "status": "Unhealthy",
            "recommendation": "Enable disk encryption",
            "description": "Disk encryption is not enabled on this VM.",
            "subscription_id": "sub-1",
            "last_assessed_at": "2026-08-18T08:00:00Z",
            "cve_id": "",
        },
        {
            "assessment_id": "assess-003",
            "target_resource_id": UNMATCHED_WEAKNESS_RESOURCE_ID,
            "resource_name": "vm-orphan",
            "resource_type": "virtualMachines",
            "severity": "medium",
            "status": "Unhealthy",
            "recommendation": "Review orphaned network interface",
            "description": "No governed catalog action addresses this weakness.",
            "subscription_id": "sub-1",
            "business_service": "Ledger Services",
            "application": "Ledger",
            "owner": "Ledger Owner",
            "last_assessed_at": "2026-08-18T07:00:00Z",
            "cve_id": "",
        },
    ]


def defender_alerts() -> list[dict[str, Any]]:
    return [
        {
            "id": "alert-001",
            "status": "Active",
            "severity": "high",
            "title": "Suspicious process execution",
            "description": "A suspicious process executed on this host.",
            "timeGenerated": "2026-08-18T10:00:00Z",
            "resourceIds": [MAPPED_RESOURCE_ID],
            "subscription_id": "sub-1",
            "business_service": "Checkout",
            "application": "Payments API",
            "owner": "Payments Product Owner",
            "environment": "Production",
        },
    ]


def defender_attack_paths() -> list[dict[str, Any]]:
    return [
        {
            "id": "path-001",
            "title": "Internet exposed VM to key vault",
            "displayName": "Internet exposed VM to key vault",
            "resourceIds": [MAPPED_RESOURCE_ID],
            "targetNodeId": "node-002",
            "subscription_id": "sub-1",
            "business_service": "Checkout",
            "application": "Payments API",
            "owner": "Payments Product Owner",
            "environment": "Production",
        },
    ]


def defender_attack_path_nodes() -> list[dict[str, Any]]:
    return [
        {
            "id": "node-002",
            "name": "vm-payments",
            "attackPathId": "path-001",
            "nodeType": "VirtualMachine",
            "resourceId": MAPPED_RESOURCE_ID,
            "resolved": True,
        },
    ]


def defender_secure_score_controls() -> list[dict[str, Any]]:
    return [
        {
            "id": "control-001",
            "title": "Enable disk encryption",
            "currentScore": 2,
            "maxScore": 10,
            "unhealthyResourceCount": 1,
            "assessmentDefinitions": [MAPPED_RESOURCE_ID],
            "observedAt": "2026-08-18T06:00:00Z",
            "subscription_id": "sub-1",
        },
    ]


ACTION_CATALOG = [
    {
        "action_id": "enable-disk-encryption",
        "opportunity_type": "Disk encryption",
        "trigger": {"any": [{"field": "defender_recommendation", "equals": "Enable disk encryption"}]},
        "execution_steps": ["Enable disk encryption on the affected disk."],
        "preconditions": ["Confirm maintenance window."],
        "rollback_actions": ["Disable disk encryption."],
        "success_criteria": ["Disk encryption reports enabled."],
        "failure_criteria": ["Disk encryption reports disabled."],
        "deployment_stages": ["staging", "production"],
        "effectiveness": {"risk_reduction_percent": 40},
    },
]


def defender_correlator(**overrides: Any) -> DefenderRemediationCorrelator:
    resources = overrides.pop("resources", defender_resources())
    action_catalog = overrides.pop("action_catalog", ACTION_CATALOG)
    vulnerability_service = overrides.pop(
        "vulnerability_service",
        VulnerabilityIntelligenceService.from_rows(
            defender_assessments=defender_assessments(),
            defender_alerts=defender_alerts(),
            defender_attack_paths=defender_attack_paths(),
            defender_attack_path_nodes=defender_attack_path_nodes(),
            defender_secure_score_controls=defender_secure_score_controls(),
            freshness="2026-08-18T13:00:00Z",
        ),
    )
    dependency_analyzer = overrides.pop(
        "dependency_analyzer", DependencyAnalyzer()
    )
    return DefenderRemediationCorrelator(
        vulnerability_service=vulnerability_service,
        dependency_analyzer=dependency_analyzer,
        resource_lookup=resources,
        action_catalog=action_catalog,
        **overrides,
    )
