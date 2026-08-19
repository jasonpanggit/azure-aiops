from __future__ import annotations

from typing import Any


class RecommendationEngine:
    """Produces advisory-only recommendations from explicit observed factors."""

    def generate(
        self,
        *,
        risk: dict[str, Any],
        health: dict[str, Any],
        compliance: dict[str, Any],
        ownership: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not all(
            isinstance(item, dict)
            for item in (risk, health, compliance, ownership, context)
        ):
            raise TypeError("Operational recommendation inputs must be mappings")
        score = risk.get("score")
        if score is not None and (
            isinstance(score, bool)
            or not isinstance(score, int)
            or not 0 <= score <= 100
        ):
            raise ValueError("Operational recommendation risk score is invalid")
        if "compliant" in compliance and not isinstance(
            compliance["compliant"], bool
        ):
            raise TypeError("Operational compliant flag must be boolean")
        if not isinstance(context.get("sections") or {}, dict):
            raise TypeError("Operational recommendation sections must be a mapping")
        recommendations: list[dict[str, Any]] = []
        if ownership.get("coverage") == "Missing":
            recommendations.append(
                self._item(
                    "High",
                    "Restores operational accountability and escalation coverage.",
                    1.0,
                    "No owner relationship is present in the governed semantic snapshot.",
                    "Assign and validate a workload owner and support group.",
                    ["missing_owner"],
                )
            )
        if not compliance.get("compliant") and compliance.get("status") != "unknown":
            recommendations.append(
                self._item(
                    "High",
                    "Reduces exposure from confirmed patch noncompliance.",
                    1.0,
                    f"Patch evidence reports {compliance.get('status')} with "
                    f"{compliance.get('failed_patch_count', 0)} failed patches.",
                    "Review failed patches and schedule remediation through the approved change process.",
                    ["patch_noncompliance"],
                )
            )
        if (score or 0) >= 75:
            recommendations.append(
                self._item(
                    "Critical",
                    "Prioritizes review of a workload with multiple observed risk factors.",
                    1.0,
                    f"The Semantic Layer risk score is {risk.get('score')} ({risk.get('level')}).",
                    "Initiate an immediate cross-functional operational review and require approval before any change.",
                    list((risk.get("factors") or {}).keys()),
                )
            )
        sections = context.get("sections") or {}
        direct_cost = sections.get("cost") or []
        cost_context = sections.get("cost_context") or []
        cost = direct_cost or cost_context
        if cost:
            rationale = (
                "Governed semantic context contains cost facts; no savings amount is inferred."
                if direct_cost
                else "Governed semantic context contains cost-allocation evidence; no spend or savings amount is inferred."
            )
            suggested_action = (
                "Review cost trends and supported optimization recommendations with the workload owner."
                if direct_cost
                else "Validate cost allocation and request a supported cost optimization assessment with the workload owner."
            )
            recommendations.append(
                self._item(
                    "Low",
                    "Creates a governed review point for observed workload cost context.",
                    0.7,
                    rationale,
                    suggested_action,
                    ["cost" if direct_cost else "cost_context"],
                )
            )
        security = sections.get("security_findings") or []
        if not isinstance(security, list) or any(
            not isinstance(item, dict) for item in security
        ):
            raise TypeError("Security findings must be a list of mappings")
        if any(not self._meaningful_finding(item) for item in security):
            raise ValueError("Security finding lacks governed evidence")
        if security:
            recommendations.append(
                self._item(
                    "High",
                    "Reduces observed security exposure.",
                    0.9,
                    "Governed semantic context contains security findings.",
                    "Validate the findings with the security owner and plan risk treatment.",
                    ["security_findings"],
                )
            )
        governance = sections.get("governance_findings") or []
        if not isinstance(governance, list) or any(
            not isinstance(item, dict) for item in governance
        ):
            raise TypeError("Governance findings must be a list of mappings")
        if any(not self._meaningful_finding(item) for item in governance):
            raise ValueError("Governance finding lacks governed evidence")
        if governance:
            recommendations.append(
                self._item(
                    "Medium",
                    "Reduces observed governance-policy exposure.",
                    1.0,
                    f"Governed semantic context contains {len(governance)} governance finding(s).",
                    "Review governance findings with the accountable owner and plan approved corrective action.",
                    ["governance"],
                )
            )
        lifecycle = sections.get("lifecycle") or {}
        lifecycle_status = str(lifecycle.get("status") or "")
        advisor_names = [
            str(item.get("name") or "")
            for item in sections.get("advisor_findings") or []
            if isinstance(item, dict)
        ]
        lifecycle_advisor = next(
            (
                name
                for name in advisor_names
                if any(
                    marker in name.casefold()
                    for marker in (
                        "obsolete",
                        "deprecated",
                        "retire",
                        "end of life",
                        "eol",
                        "modernize",
                    )
                )
            ),
            "",
        )
        if lifecycle_status.casefold() in {
            "obsolete",
            "deprecated",
            "retiring",
        } or lifecycle_advisor:
            rationale = (
                f"Lifecycle status is {lifecycle_status}."
                if lifecycle_status.casefold()
                in {"obsolete", "deprecated", "retiring"}
                else "Advisor evidence identifies an obsolete, deprecated, end-of-life, or modernization condition."
            )
            recommendations.append(
                self._item(
                    "Medium",
                    "Reduces lifecycle and supportability risk.",
                    1.0,
                    rationale,
                    "Assess modernization options and create an approved migration plan.",
                    ["advisor_findings" if lifecycle_advisor else "lifecycle_status"],
                )
            )
        priority_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        return sorted(
            recommendations,
            key=lambda item: (
                priority_rank.get(str(item.get("priority")), 4),
                str(item.get("suggested_action")),
            ),
        )

    @staticmethod
    def _item(
        priority: str,
        impact: str,
        confidence: float,
        rationale: str,
        suggested_action: str,
        evidence: list[str],
    ) -> dict[str, Any]:
        return {
            "priority": priority,
            "impact": impact,
            "confidence": confidence,
            "rationale": rationale,
            "suggested_action": suggested_action,
            "evidence": evidence,
            "advisory_only": True,
        }

    @staticmethod
    def _meaningful_finding(row: dict[str, Any]) -> bool:
        for key in ("name", "title", "severity", "finding_id", "status"):
            if str(row.get(key) or "").strip():
                return True
        nested = row.get("findings")
        return isinstance(nested, list) and any(
            isinstance(item, dict)
            and any(str(value or "").strip() for value in item.values())
            for item in nested
        )
