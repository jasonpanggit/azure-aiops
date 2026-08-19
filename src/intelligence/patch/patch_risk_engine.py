from __future__ import annotations

from typing import Any, ClassVar


class PatchRiskEngine:
    """Deterministic 0-100 patch exposure model with factor points."""

    _LEVEL_POINTS: ClassVar[dict[str, int]] = {
        "critical": 20,
        "high": 15,
        "medium": 8,
        "low": 3,
    }

    def calculate(
        self,
        *,
        context: dict[str, Any],
        compliance: dict[str, Any],
        security_findings: list[dict[str, Any]],
        advisor_recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(context, dict) or not isinstance(compliance, dict):
            raise TypeError("Patch risk context and compliance must be mappings")
        if not isinstance(security_findings, list) or not isinstance(
            advisor_recommendations, list
        ):
            raise TypeError("Patch risk finding collections must be lists")
        ownership = context.get("ownership_coverage", False)
        if not isinstance(ownership, bool):
            raise TypeError("Patch ownership_coverage must be boolean")
        age = self._count(compliance.get("patch_age_days"), "patch_age_days")
        missing = self._count(
            compliance.get("missing_critical_updates"), "missing_critical_updates"
        )
        factors = {
            "business_criticality": self._LEVEL_POINTS.get(
                str(context.get("business_criticality") or "").casefold(), 0
            ),
            "application_impact": min(
                self._LEVEL_POINTS.get(
                    str(context.get("application_impact") or "").casefold(), 0
                ),
                15,
            ),
            "patch_age": min(age // 10 * 3, 15),
            "patch_severity": self._LEVEL_POINTS.get(
                str(compliance.get("highest_severity") or "").casefold(), 0
            ),
            "missing_critical_patches": min(
                missing * 8, 15
            ),
            "security_findings": min(len(security_findings) * 5, 10),
            "advisor_recommendations": min(len(advisor_recommendations) * 3, 5),
            "ownership_gap": 0 if ownership else 5,
            "evidence_uncertainty": 25
            if compliance.get("evidence_coverage") != "Complete"
            else 0,
        }
        score = min(sum(factors.values()), 100)
        return {
            "score": score,
            "level": self.level_for(score),
            "factors": factors,
            "justification": "; ".join(
                f"{name.replace('_', ' ')} +{points}"
                for name, points in factors.items()
                if points
            )
            or "No confirmed patch-risk factors are present in the governed snapshot.",
        }

    @staticmethod
    def level_for(score: int) -> str:
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError("Patch risk score must be an integer from 0 to 100")
        if score >= 75:
            return "Critical"
        if score >= 50:
            return "High"
        if score >= 25:
            return "Moderate"
        return "Low"

    @staticmethod
    def _count(value: Any, field_name: str) -> int:
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Patch {field_name} must be a non-negative integer")
        return value
