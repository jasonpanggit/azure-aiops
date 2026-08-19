from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar


class LifecycleSummaryEngine:
    REPORT_TYPES: ClassVar[set[str]] = {
        "executive_lifecycle_summary",
        "modernization_exposure_report",
        "business_risk_report",
        "application_risk_report",
        "technology_debt_report",
        "executive_modernization_brief",
    }

    def exposure(self, findings: list[dict[str, Any]]) -> dict[str, Any]:
        eol = [item for item in findings if item["lifecycle_status"] == "EOL"]
        within_12 = [
            item
            for item in findings
            if item.get("days_remaining") is not None
            and 0 <= int(item["days_remaining"]) <= 366
        ]
        no_plan = [
            item
            for item in findings
            if item["risk_score"] >= 25
            and item["modernization_recommendation"]["recommended_action"].startswith(
                "Validate the product/version"
            )
        ]
        lifecycle_debt_score = sum(
            {
                "EOL": 100,
                "Critical": 75,
                "Near EOL": 50,
                "Approaching EOL": 25,
                "Unknown": 50,
            }.get(str(item["lifecycle_status"]), 0)
            for item in findings
        )
        return {
            "total_eol_assets": len(eol),
            "assets_within_12_months_of_eol": len(within_12),
            "assets_with_no_upgrade_plan": len(no_plan),
            "lifecycle_debt_score": lifecycle_debt_score,
            "business_services_at_risk": len(
                {
                    item["business_service"]
                    for item in findings
                    if item["risk_score"] >= 50
                    and str(item.get("business_service") or "Unknown").casefold()
                    != "unknown"
                }
            ),
            "by_subscription": self._group(findings, "subscription"),
            "by_business_service": self._group(findings, "business_service"),
            "by_environment": self._group(findings, "environment"),
            "by_application": self._group(findings, "application"),
            "by_region": self._group(findings, "region"),
            "by_operating_system": self._group(findings, "product"),
        }

    def generate(
        self,
        report_type: str,
        *,
        findings: list[dict[str, Any]],
        exposure: dict[str, Any],
        trends: dict[str, Any],
        freshness: str,
    ) -> dict[str, Any]:
        normalized = report_type.strip().casefold().replace(" ", "_")
        if normalized not in self.REPORT_TYPES:
            raise ValueError("Unsupported lifecycle report type")
        high_risk = [item for item in findings if item["risk_score"] >= 50]
        headline = (
            f"{exposure['total_eol_assets']} EOL assets; "
            f"{exposure['business_services_at_risk']} business services at risk; "
            f"{len(high_risk)} high-risk modernization candidates."
        )
        focus = {
            "executive_lifecycle_summary": exposure,
            "modernization_exposure_report": [
                item["modernization_recommendation"] for item in high_risk
            ],
            "business_risk_report": exposure["by_business_service"],
            "application_risk_report": exposure["by_application"],
            "technology_debt_report": exposure["by_operating_system"],
            "executive_modernization_brief": {
                "headline": headline,
                "top_candidates": high_risk[:5],
                "trend": trends["90_day"],
            },
        }[normalized]
        return {
            "report_type": normalized,
            "headline": headline,
            "focus": focus,
            "exposure": exposure,
            "trends": trends,
            "priority_candidates": high_risk[:10],
            "freshness": freshness,
            "read_only": True,
        }

    @staticmethod
    def _group(
        findings: list[dict[str, Any]], field: str
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in findings:
            grouped[str(item.get(field) or "Unknown")].append(item)
        return sorted(
            (
                {
                    "name": name,
                    "asset_count": len(items),
                    "eol_asset_count": sum(
                        item["lifecycle_status"] == "EOL" for item in items
                    ),
                    "within_12_months": sum(
                        item.get("days_remaining") is not None
                        and 0 <= int(item["days_remaining"]) <= 366
                        for item in items
                    ),
                    "max_risk_score": max(int(item["risk_score"]) for item in items),
                }
                for name, items in grouped.items()
            ),
            key=lambda row: (-row["max_risk_score"], row["name"]),
        )
