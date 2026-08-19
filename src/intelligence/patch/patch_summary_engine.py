from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar


class PatchSummaryEngine:
    """Builds executive and operational read-only patch reports."""

    REPORT_TYPES: ClassVar[set[str]] = {
        "executive_patch_summary",
        "security_exposure_summary",
        "compliance_overview",
        "patch_risk_dashboard",
        "business_service_exposure_dashboard",
        "monthly_risk_report",
        "executive_brief",
    }

    def generate(
        self,
        report_type: str,
        *,
        findings: list[dict[str, Any]],
        compliance: dict[str, Any],
        exposure: dict[str, Any],
        trends: dict[str, Any],
        freshness: str,
    ) -> dict[str, Any]:
        normalized = report_type.strip().casefold().replace(" ", "_")
        if normalized not in self.REPORT_TYPES:
            raise ValueError("Unsupported patch report type")
        p1 = [item for item in findings if item.get("priority") == "Priority 1"]
        headline = (
            f"{len(p1)} Priority 1 workload(s); {exposure['exposed_resource_count']} exposed resource(s); "
            f"overall compliance {compliance['overall']['compliance_score']}."
        )
        focus = {
            "executive_patch_summary": {
                "headline": headline,
                "priority_1_count": len(p1),
            },
            "security_exposure_summary": exposure,
            "compliance_overview": compliance,
            "patch_risk_dashboard": [
                {
                    "resource": item["resource"],
                    "risk_score": item["risk_score"],
                    "priority": item["priority"],
                }
                for item in findings
            ],
            "business_service_exposure_dashboard": exposure[
                "business_exposure"
            ],
            "monthly_risk_report": trends["30_day"],
            "executive_brief": {
                "headline": headline,
                "top_business_exposure": exposure["business_exposure"][:3],
                "top_candidates": p1[:5],
            },
        }[normalized]
        return {
            "report_type": normalized,
            "headline": headline,
            "focus": focus,
            "overall": compliance["overall"],
            "priority_remediation_candidates": p1[:10],
            "security_exposure": exposure,
            "compliance": compliance,
            "trends": trends,
            "freshness": freshness,
            "read_only": True,
        }

    @staticmethod
    def exposure(findings: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(findings, list) or any(
            not isinstance(item, dict) for item in findings
        ):
            raise TypeError("Patch findings must be a list of mappings")
        exposed = [item for item in findings if int(item.get("risk_score") or 0) >= 50]
        services: dict[str, list[dict[str, Any]]] = defaultdict(list)
        applications: dict[str, list[dict[str, Any]]] = defaultdict(list)
        subscriptions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in findings:
            service = str(item.get("business_service") or "Unknown")
            application = str(item.get("application") or "Unknown")
            subscription = str(item.get("subscription") or "Unknown")
            if service.strip().casefold() not in {"", "unknown"}:
                services[service].append(item)
            if application.strip().casefold() not in {"", "unknown"}:
                applications[application].append(item)
            if subscription.strip().casefold() not in {"", "unknown"}:
                subscriptions[subscription].append(item)

        def ranked(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
            return sorted(
                (
                    {
                        "name": name,
                        "resource_count": len(items),
                        "exposed_resource_count": sum(int(item.get("risk_score") or 0) >= 50 for item in items),
                        "risk_score": max(int(item.get("risk_score") or 0) for item in items),
                        "compliance_score": round(sum(int(item.get("compliance_score") or 0) for item in items) / len(items), 2),
                    }
                    for name, items in groups.items()
                ),
                key=lambda item: (-item["risk_score"], item["compliance_score"], item["name"]),
            )

        return {
            "exposed_resource_count": len(exposed),
            "high_risk_workloads": [
                item["resource"] for item in exposed if int(item.get("risk_score") or 0) >= 75
            ],
            "security_patch_debt": sum(int(item.get("missing_security_updates") or 0) for item in findings),
            "compliance_debt": sum(
                int(item.get("compliance_debt") or 0) for item in findings
            ),
            "operational_exposure": sum(int(item.get("risk_score") or 0) for item in findings),
            "business_exposure": ranked(services),
            "vulnerable_applications": [
                item for item in ranked(applications) if item["risk_score"] >= 50
            ],
            "subscription_patch_risk": ranked(subscriptions),
        }
