from __future__ import annotations

from typing import Any


class ConfigurationDriftEngine:
    def compare(self, expected: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
        if not expected:
            return {"drifted": None, "fields": [], "severity": "Unknown", "evidence_status": "Unknown"}
        fields = sorted(
            key for key, expected_value in expected.items()
            if key not in observed or observed.get(key) != expected_value
        )
        sensitive = {"publicnetworkaccess", "encryption", "firewall", "identity", "roleassignments"}
        severity = "Critical" if any(key.casefold() in sensitive for key in fields) else "High" if fields else "None"
        return {"drifted": bool(fields), "fields": fields, "severity": severity, "evidence_status": "Known"}

    def compliance_score(self, drift: dict[str, Any], *, policy_count: int, security_count: int) -> int | None:
        if drift["drifted"] is None and not policy_count and not security_count:
            return None
        score = 100
        if drift["drifted"]:
            score -= 30
        score -= min(policy_count * 15, 30)
        score -= min(security_count * 15, 30)
        return max(score, 0)
