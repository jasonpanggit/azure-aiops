from __future__ import annotations

from typing import Any, ClassVar


class BaselineEngine:
    """Creates governed, auditable configuration baseline projections."""

    SUPPORTED_RESOURCE_TYPES: ClassVar[set[str]] = {
        "VirtualMachine",
        "ArcServer",
        "NetworkSecurityGroup",
        "VirtualNetwork",
        "Subnet",
        "AzureFirewall",
        "RouteTable",
        "ApplicationGateway",
        "KeyVault",
        "StorageAccount",
        "SqlDatabase",
        "AksCluster",
        "AzureLocal",
    }

    def create(
        self,
        *,
        baseline_id: str,
        resource_type: str,
        required_state: dict[str, Any],
        compliance_rules: list[str],
        ownership_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if resource_type not in self.SUPPORTED_RESOURCE_TYPES:
            raise ValueError("Unsupported configuration baseline resource type")
        if not baseline_id or not required_state or not compliance_rules:
            raise ValueError("Baseline requires identity, state, and compliance rules")
        return {
            "baseline_id": str(baseline_id)[:256],
            "entity_type": "ConfigurationBaseline",
            "resource_type": resource_type,
            "required_state": dict(required_state),
            "expected_configuration": dict(required_state),
            "compliance_rules": [str(rule)[:512] for rule in compliance_rules[:100]],
            "ownership_metadata": dict(ownership_metadata),
            "auditable": True,
            "read_only": True,
        }
