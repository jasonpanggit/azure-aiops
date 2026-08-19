from __future__ import annotations

from typing import Any, ClassVar


class LifecycleRiskEngine:
    """Deterministic 0-100 lifecycle risk model with factor attribution."""

    STATUS_POINTS: ClassVar[dict[str, int]] = {
        "Supported": 0,
        "Approaching EOL": 10,
        "Near EOL": 20,
        "Critical": 30,
        "EOL": 40,
        "Unknown": 15,
    }
    CRITICALITY_POINTS: ClassVar[dict[str, int]] = {
        "critical": 15,
        "high": 10,
        "medium": 6,
        "low": 2,
    }

    def calculate(
        self, *, context: dict[str, Any], classification: dict[str, Any]
    ) -> dict[str, Any]:
        for field in ("internet_exposed", "ownership_coverage"):
            value = context.get(field, False)
            if not isinstance(value, bool):
                raise TypeError(f"{field} must be boolean")
        patch_value = context.get("patch_compliance")
        if patch_value is not None and (
            isinstance(patch_value, bool)
            or not isinstance(patch_value, int)
            or not 0 <= patch_value <= 100
        ):
            raise ValueError("patch_compliance must be an integer from 0 to 100")
        patch_score = (
            patch_value if patch_value is not None else None
        )
        factors = {
            "support_timeline": self.STATUS_POINTS.get(
                str(classification.get("status") or "Unknown"), 15
            ),
            "patch_noncompliance": (
                min((100 - patch_score) * 15 // 100, 15)
                if patch_score is not None
                else 0
            ),
            "external_exposure": 15 if context.get("internet_exposed") else 0,
            "business_criticality": self.CRITICALITY_POINTS.get(
                str(context.get("business_criticality") or "").casefold(), 0
            ),
            "ownership_gap": 0 if context.get("ownership_coverage") else 10,
            "production_environment": 5
            if str(context.get("environment") or "").casefold()
            in {"production", "prod", "live"}
            else 0,
            "catalog_match_missing": 15
            if classification.get("status") == "Unknown"
            else 0,
        }
        score = min(sum(factors.values()), 100)
        return {
            "score": score,
            "level": self.level_for(score),
            "factors": factors,
            "risk_drivers": [name for name, value in factors.items() if value],
            "justification": "; ".join(
                f"{name.replace('_', ' ')} +{value}"
                for name, value in factors.items()
                if value
            )
            or "No confirmed lifecycle risk factors are present.",
        }

    @staticmethod
    def level_for(score: int) -> str:
        if score >= 75:
            return "Critical"
        if score >= 50:
            return "High"
        if score >= 25:
            return "Moderate"
        return "Low"
