from __future__ import annotations

from .change_incident_correlator import ChangeIncidentCorrelator
from .change_risk_engine import ChangeRiskEngine
from .configuration_drift_engine import ConfigurationDriftEngine


class ChangeAnalyzer:
    def __init__(self, context_builder, *, drift=None, risk=None, correlator=None, max_nested_items=100):
        self.context_builder = context_builder
        self.drift = drift or ConfigurationDriftEngine()
        self.risk = risk or ChangeRiskEngine()
        self.correlator = correlator or ChangeIncidentCorrelator()
        self.max_nested_items = max_nested_items

    def analyze(self, changes, policy, security, incidents):
        findings = []
        for change in changes:
            context = self.context_builder.get(change["resource_key"])
            if hasattr(self.drift, "detect"):
                drift = self.drift.detect(
                    expected=context["expected_configuration"],
                    observed=context["observed_configuration"],
                )
            else:
                drift = self.drift.compare(context["expected_configuration"], context["observed_configuration"])
            active = {"noncompliant", "deviated", "active", "open", "failed", "error"}
            policy_rows = [row for row in policy if row["resource_key"] == change["resource_key"] and str(row.get("status") or "").casefold() in active]
            security_rows = [row for row in security if row["resource_key"] == change["resource_key"] and str(row.get("status") or "").casefold() in active]
            correlation = self.correlator.correlate(change, incidents)
            risk = self.risk.calculate(change=change, context=context, drift=drift, deviations={"policy": len(policy_rows), "security": len(security_rows)}, incident_correlation=correlation)
            compliance = self.drift.compliance_score(drift, policy_count=len(policy_rows), security_count=len(security_rows))
            public = {key: value for key, value in context.items() if not key.startswith("_") and key not in {"expected_configuration", "observed_configuration"}}
            policy_rows = sorted(
                policy_rows, key=lambda row: str(row.get("deviation_id") or "")
            )
            security_rows = sorted(
                security_rows, key=lambda row: str(row.get("deviation_id") or "")
            )
            public_policy = [
                {key: value for key, value in row.items() if key != "resource_key"}
                for row in policy_rows[: self.max_nested_items]
            ]
            public_security = [
                {key: value for key, value in row.items() if key != "resource_key"}
                for row in security_rows[: self.max_nested_items]
            ]
            actor_known = bool(str(change["changed_by"]).strip()) and str(
                change["changed_by"]
            ).strip().casefold() != "unknown"
            evidence = [f"Change source: {change['source']}", *correlation["evidence"]]
            if actor_known:
                evidence.append(f"Actor: {change['changed_by']}")
            public_drift = {**drift, "fields": drift["fields"][: self.max_nested_items]}
            related = [correlation["incident_id"]] if correlation["incident_id"] else []
            impact = {
                "application": context["application"],
                "business_service": context["business_service"],
                "criticality": context["business_criticality"],
                "dependency_count": context.get("dependency_count", 0),
            }
            findings.append({"change": {key: change[key] for key in ("change_id", "change_type", "category", "changed_by", "changed_at", "source", "summary", "authorized", "approval_reference")}, **public, "previous_state": change["previous_state"], "current_state": change["current_state"], "actor_evidence_status": "Known" if actor_known else "Unknown", "configuration_drift": public_drift, "policy_deviations": public_policy, "security_deviations": public_security, "compliance_score": compliance, "risk_score": risk["score"], "risk_level": risk["level"], "risk_factors": risk["factors"], "risk_justification": risk["justification"], "reasoning": "The change is classified, compared with governed baseline state, scored using business/dependency context, and probabilistically correlated with subsequent incidents.", "business_impact": impact, "related_incidents": related, "incident_correlation": correlation, "confidence": min((risk["score"] + correlation["contribution_score"]) / 200, 0.95), "evidence": evidence, "recommended_action": {"suggested_action": "Validate the change evidence, expected configuration, and ownership context before deciding on any operational action.", "advisory_only": True}, "read_only": True})
        return sorted(findings, key=lambda row: (-row["risk_score"], row["change"]["change_id"]))
