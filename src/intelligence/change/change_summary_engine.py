from typing import Any, ClassVar


class ChangeSummaryEngine:
    REPORT_TYPES: ClassVar[set[str]] = {"change_intelligence_summary", "configuration_compliance_report", "change_risk_report", "incident_contribution_report", "executive_change_brief", "executive_governance_report"}

    def generate(self, report_type: str, *, findings: list[dict[str, Any]], compliance, trends, freshness, portfolio_summary=None):
        normalized = report_type.strip().casefold().replace(" ", "_")
        if normalized not in self.REPORT_TYPES: raise ValueError("Unsupported change intelligence report")
        high = [row for row in findings if row["risk_score"] >= 50]
        summary = portfolio_summary or {}
        headline = f"{int(summary.get('change_count', len(findings)))} changes analyzed; {int(summary.get('high_risk_change_count', len(high)))} high-risk; {int(summary.get('drifted_resource_count', sum(row['configuration_compliant'] is False for row in compliance)))} resources drifted."
        focus = {"change_intelligence_summary": findings, "configuration_compliance_report": compliance, "change_risk_report": high, "incident_contribution_report": [row for row in findings if row["incident_correlation"]["contribution_score"] >= 60], "executive_change_brief": {"headline": headline, "top_changes": high[:5], "trend": trends["30_day"]}, "executive_governance_report": {"headline": headline, "unapproved_changes": [row for row in findings if row["change"]["authorized"] is False][:5], "policy_and_security_deviations": sum(len(row["policy_deviations"])+len(row["security_deviations"]) for row in findings), "trend": trends["90_day"]}}[normalized]
        return {"report_type": normalized, "headline": headline, "focus": focus, "trends": trends, "freshness": freshness, "read_only": True}
