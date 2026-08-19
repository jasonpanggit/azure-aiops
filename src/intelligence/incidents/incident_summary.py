from __future__ import annotations


class IncidentSummary:
    """Produces audience-specific evidence-backed incident summaries."""

    def __init__(self, *, max_items: int = 50) -> None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
            raise ValueError("Incident summary item bound must be a positive integer")
        self.max_items = max_items

    def audiences(self, findings, patterns):
        incident_count = len(findings)
        probable = sum(bool(finding.get("probable_causes")) for finding in findings)
        services = sorted(
            {service for finding in findings for service in finding.get("impacted_business_services", [])}
        )
        common_evidence = [
            {
                "incident_count": incident_count,
                "ranked_probable_cause_count": probable,
                "business_services": services[: self.max_items],
            }
        ]
        common = {
            "technical_summary": f"{incident_count} incidents were correlated against governed operational events, dependency paths, and timelines.",
            "executive_summary": f"{len(services)} business services are exposed across {incident_count} analyzed incidents.",
            "root_cause_summary": f"{probable} incidents have ranked probable causes; no cause is asserted as confirmed.",
        }
        summaries = {
            "engineer": {"summary": "Investigate ranked preceding evidence and dependency paths.", "evidence": common_evidence, "detail": findings[: self.max_items]},
            "manager": {"summary": f"{incident_count} incidents analyzed with {probable} ranked probable causes.", "evidence": common_evidence, "priorities": patterns[: self.max_items]},
            "director": {"summary": f"{len(services)} business services have incident exposure.", "evidence": common_evidence, "patterns": patterns[: self.max_items]},
            "cio": {"summary": "Operational causality remains probabilistic; prioritize chronic contributors and critical service exposure.", "evidence": common_evidence, "business_services": services[: self.max_items]},
        }
        return {audience: {**common, **summary} for audience, summary in summaries.items()}
