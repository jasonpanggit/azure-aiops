"""Shared test fixtures and utilities for specialist agent contract validation.

Provides reusable finding generators, evidence/resource ID fixtures, and assertion
helpers for validating per-agent Foundry output contracts.
"""

from __future__ import annotations

from typing import Any

# Evidence reference fixtures
EVIDENCE_REFS = {
    "network-topo-1",
    "nsg-rule-1",
    "route-table-1",
    "traffic-capture-1",
    "firewall-log-1",
}

# Resource ID fixtures (valid Azure subscription-scoped IDs)
RESOURCE_IDS = {
    "/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/test-rg/providers/Microsoft.Network/virtualNetworks/vnet1",
    "/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/test-rg/providers/Microsoft.Network/networkSecurityGroups/nsg1",
    "/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/test-rg/providers/Microsoft.Compute/virtualMachines/vm1",
}

SINGLE_RESOURCE = {
    "/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/test-rg/providers/Microsoft.Network/virtualNetworks/vnet1",
}


def valid_network_finding() -> dict[str, Any]:
    """Generate valid network agent finding."""
    return {
        "finding_id": "NET-GAP-001",
        "resource_ids": list(RESOURCE_IDS)[:1],
        "check_id": "nsg_inbound_any",
        "policy_id": "firewall_least_privilege",
        "evidence_refs": list(EVIDENCE_REFS)[:2],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Verify new NSG rules are in place and test traffic flow",
        "summary": "NSG allows unrestricted inbound traffic from 0.0.0.0/0",
    }


def valid_vulnerability_finding() -> dict[str, Any]:
    """Generate valid vulnerability agent finding."""
    return {
        "finding_id": "VUL-CVE-001",
        "resource_ids": list(RESOURCE_IDS)[:1],
        "cve_id": "CVE-2024-12345",
        "evidence_refs": list(EVIDENCE_REFS)[:2],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Verify patch installation and vulnerability remediation",
        "summary": "Critical CVE-2024-12345 detected on vulnerable service",
    }


def valid_patch_finding() -> dict[str, Any]:
    """Generate valid patch agent finding."""
    return {
        "finding_id": "PATCH-KB-001",
        "resource_ids": list(RESOURCE_IDS)[:1],
        "kb_id": "KB-4567890",
        "evidence_refs": list(EVIDENCE_REFS)[:2],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Validate patch installation and system stability",
        "summary": "Critical security patch KB-4567890 pending installation",
    }


def valid_incident_finding() -> dict[str, Any]:
    """Generate valid incident agent finding (no resource_ids)."""
    return {
        "finding_id": "INC-001",
        "incident_id": "INC-2024-00123",
        "evidence_refs": list(EVIDENCE_REFS)[:2],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Validate root cause fix and monitor for recurrence",
        "summary": "Service outage caused by configuration drift in load balancer",
    }


def valid_change_finding() -> dict[str, Any]:
    """Generate valid change agent finding."""
    return {
        "finding_id": "CHG-001",
        "resource_ids": list(RESOURCE_IDS)[:1],
        "change_id": "CHG-2024-00456",
        "evidence_refs": list(EVIDENCE_REFS)[:2],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Monitor application performance metrics after change",
        "summary": "Database failover configuration changed 2 hours before outage",
    }


def valid_governance_finding() -> dict[str, Any]:
    """Generate valid governance agent finding."""
    return {
        "finding_id": "GOV-001",
        "resource_ids": list(RESOURCE_IDS)[:1],
        "owner_id": "team-platform",
        "evidence_refs": list(EVIDENCE_REFS)[:2],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Verify owner approval and policy exception documentation",
        "summary": "Resource lacks required owner tag and approval",
    }


def valid_remediation_finding() -> dict[str, Any]:
    """Generate valid remediation agent finding."""
    return {
        "finding_id": "REM-001",
        "resource_ids": list(RESOURCE_IDS)[:1],
        "remediation_id": "REM-2024-00789",
        "evidence_refs": list(EVIDENCE_REFS)[:2],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Review governed rollout in staging before production approval",
        "summary": "Governed action best protects the customer path",
        "pros": ["Reduces customer-facing exposure"],
        "cons": ["Requires maintenance-window coordination"],
        "urgency_reasoning": "Checkout is customer-facing and the evidence shows active exposure.",
    }


def valid_executive_summary_finding() -> dict[str, Any]:
    """Generate valid executive summary finding (no resource_ids)."""
    return {
        "finding_id": "EXEC-SUMMARY-001",
        "evidence_refs": list(EVIDENCE_REFS)[:3],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Review recommended actions and track outcomes",
        "summary": "Critical infrastructure issues require immediate attention; estimated impact: 2-hour window for resolution",
    }


def make_finding_json(agent_id: str) -> str:
    """Return valid finding JSON payload for agent type."""
    import json

    generators = {
        "network": valid_network_finding,
        "vulnerability": valid_vulnerability_finding,
        "patch": valid_patch_finding,
        "incident": valid_incident_finding,
        "change": valid_change_finding,
        "governance": valid_governance_finding,
        "remediation": valid_remediation_finding,
        "executive_summary": valid_executive_summary_finding,
    }
    generator = generators.get(agent_id.casefold())
    if not generator:
        raise ValueError(f"Unknown agent type: {agent_id}")

    finding = generator()
    payload = {"findings": [finding]}
    return json.dumps(payload)


def make_finding_with_missing_field(agent_id: str, missing_field: str) -> str:
    """Generate finding JSON with specified required field removed."""
    import json

    generators = {
        "network": valid_network_finding,
        "vulnerability": valid_vulnerability_finding,
        "patch": valid_patch_finding,
        "incident": valid_incident_finding,
        "change": valid_change_finding,
        "governance": valid_governance_finding,
        "remediation": valid_remediation_finding,
        "executive_summary": valid_executive_summary_finding,
    }
    generator = generators.get(agent_id.casefold())
    if not generator:
        raise ValueError(f"Unknown agent type: {agent_id}")

    finding = generator()
    del finding[missing_field]
    payload = {"findings": [finding]}
    return json.dumps(payload)


def make_finding_with_invalid_enum(agent_id: str, field: str, value: str) -> str:
    """Generate finding JSON with invalid enum value."""
    import json

    generators = {
        "network": valid_network_finding,
        "vulnerability": valid_vulnerability_finding,
        "patch": valid_patch_finding,
        "incident": valid_incident_finding,
        "change": valid_change_finding,
        "governance": valid_governance_finding,
        "remediation": valid_remediation_finding,
        "executive_summary": valid_executive_summary_finding,
    }
    generator = generators.get(agent_id.casefold())
    if not generator:
        raise ValueError(f"Unknown agent type: {agent_id}")

    finding = generator()
    finding[field] = value
    payload = {"findings": [finding]}
    return json.dumps(payload)


def make_finding_with_uncited_resource(agent_id: str) -> str:
    """Generate finding with resource not in provided resource_ids set."""
    import json

    generators = {
        "network": valid_network_finding,
        "vulnerability": valid_vulnerability_finding,
        "patch": valid_patch_finding,
        "incident": valid_incident_finding,
        "change": valid_change_finding,
        "governance": valid_governance_finding,
        "remediation": valid_remediation_finding,
        "executive_summary": valid_executive_summary_finding,
    }
    generator = generators.get(agent_id.casefold())
    if not generator:
        raise ValueError(f"Unknown agent type: {agent_id}")

    finding = generator()
    # Add a resource that's not in RESOURCE_IDS
    if "resource_ids" in finding:
        finding["resource_ids"].append(
            "/subscriptions/87654321-4321-4321-4321-210987654321/resourceGroups/other-rg/providers/Microsoft.Network/virtualNetworks/vnet2"
        )
    payload = {"findings": [finding]}
    return json.dumps(payload)


def make_finding_with_mutation_words(agent_id: str) -> str:
    """Generate finding with mutation instruction words."""
    import json

    generators = {
        "network": valid_network_finding,
        "vulnerability": valid_vulnerability_finding,
        "patch": valid_patch_finding,
        "incident": valid_incident_finding,
        "change": valid_change_finding,
        "governance": valid_governance_finding,
        "remediation": valid_remediation_finding,
        "executive_summary": valid_executive_summary_finding,
    }
    generator = generators.get(agent_id.casefold())
    if not generator:
        raise ValueError(f"Unknown agent type: {agent_id}")

    finding = generator()
    # Add mutation words to summary
    finding["summary"] += " DELETE this resource and CREATE a new one"
    payload = {"findings": [finding]}
    return json.dumps(payload)
