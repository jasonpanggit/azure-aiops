from __future__ import annotations

from typing import Any, ClassVar


class IncidentSummaryEngine:
    REPORT_TYPES: ClassVar[set[str]] = {
        "incident_correlation_summary",
        "operational_causality_report",
        "business_impact_report",
        "recurring_pattern_report",
        "executive_incident_brief",
    }

    def generate(
        self,
        report_type: str,
        *,
        findings: list[dict[str, Any]],
        patterns: list[dict[str, Any]],
        freshness: str,
    ) -> dict[str, Any]:
        normalized = report_type.strip().casefold().replace(" ", "_")
        if normalized not in self.REPORT_TYPES:
            raise ValueError("Unsupported incident intelligence report")
        probable_count = sum(bool(item["probable_causes"]) for item in findings)
        services = sorted({service for item in findings for service in item["impacted_business_services"]})
        headline = f"{len(findings)} incidents analyzed; {probable_count} have ranked probable causes; {len(services)} business services exposed."
        focus = {
            "incident_correlation_summary": findings,
            "operational_causality_report": [
                {"incident": item["incident"], "probable_causes": item["probable_causes"]}
                for item in findings
            ],
            "business_impact_report": [
                {
                    "incident": item["incident"],
                    "business_services": item["impacted_business_services"],
                    "applications": item["impacted_applications"],
                    "blast_radius": item["blast_radius"],
                }
                for item in findings
            ],
            "recurring_pattern_report": patterns,
            "executive_incident_brief": {
                "headline": headline,
                "top_incidents": findings[:5],
                "recurring_patterns": patterns[:5],
            },
        }[normalized]
        return {
            "report_type": normalized,
            "headline": headline,
            "focus": focus,
            "evidence_summary": {
                "incident_count": len(findings),
                "ranked_cause_count": sum(len(item["probable_causes"]) for item in findings),
                "recurring_pattern_count": len(patterns),
            },
            "freshness": freshness,
            "read_only": True,
        }
