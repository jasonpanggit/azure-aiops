from __future__ import annotations

from typing import Any

from .configuration_drift_engine import ConfigurationDriftEngine


class DriftDetectionEngine(ConfigurationDriftEngine):
    """Detects named configuration, policy, security, network, identity, tag, and ownership drift."""

    def detect(self, *, expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
        comparison = self.compare(expected, observed)
        drift_types = []
        if expected.get("owner") and not observed.get("owner"):
            drift_types.append("Ownership Drift")
        expected_tags = expected.get("requiredTags") or {}
        observed_tags = observed.get("requiredTags") or {}
        if any(tag not in observed_tags for tag in expected_tags):
            drift_types.append("Required Tag Removal")
        if len(observed.get("nsgRules") or []) > len(expected.get("nsgRules") or []):
            drift_types.append("NSG Rule Added")
        if expected.get("firewallOpen") is False and observed.get("firewallOpen") is True:
            drift_types.append("Firewall Opened")
        if expected.get("managedIdentity") and not observed.get("managedIdentity"):
            drift_types.append("Managed Identity Removed")
        if expected.get("privateEndpoint") and not observed.get("privateEndpoint"):
            drift_types.append("Private Endpoint Removed")
        if expected.get("policyExemption") is False and observed.get("policyExemption") is True:
            drift_types.append("Policy Exemption")
        if comparison["drifted"] and not drift_types:
            drift_types.append("Configuration Drift")
        return {
            **comparison,
            "drift_types": drift_types,
            "previous_state": dict(expected),
            "current_state": dict(observed),
            "evidence": [
                f"Expected and observed values differ for {field}"
                for field in comparison["fields"]
            ],
            "read_only": True,
        }
