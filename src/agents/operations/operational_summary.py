from __future__ import annotations

from typing import Any


class OperationalSummary:
    def generate(self, analysis: dict[str, Any], *, executive: bool = False) -> dict[str, Any]:
        subject = analysis.get("subject") or {}
        risk = analysis.get("risk") or {}
        health = analysis.get("health") or {}
        recommendations = analysis.get("recommendations") or []
        headline = (
            f"{subject.get('name', 'Workload')} is {health.get('category', 'Unknown')} "
            f"with {risk.get('level', 'Unknown')} operational risk."
        )
        summary_type = (
            "Executive Risk Summary"
            if executive
            else {
                "Analyze Subscription": "Subscription Summary",
                "Analyze Application": "Application Summary",
                "Analyze Business Service": "Service Summary",
                "Analyze Patch Compliance": "Patch Compliance Summary",
                "Show Patch Compliance": "Patch Compliance Summary",
                "Analyze Operational Risk": "Risk Summary",
                "Show Operational Risk": "Risk Summary",
                "Analyze VM": "VM Summary",
                "Show Health Summary": "Health Summary",
                "Show Impact Summary": "Impact Summary",
                "Generate Incident Context": "Incident Summary",
            }.get(str(analysis.get("command") or ""), "Operational Summary")
        )
        return {
            "summary_type": summary_type,
            "headline": headline,
            "key_findings": [item.get("reasoning", "") for item in analysis.get("conclusions", [])],
            "priority_actions": [item["suggested_action"] for item in recommendations[:5]],
            "evidence_count": sum(
                len(item.get("evidence") or []) for item in analysis.get("conclusions", [])
            ),
            "read_only": True,
        }
