from __future__ import annotations

import math
from typing import Any


class ModernizationEngine:
    """Produces advisory-only modernization priorities from catalog evidence."""

    def recommend(
        self,
        *,
        context: dict[str, Any],
        classification: dict[str, Any],
        risk: dict[str, Any],
        upgrade_path: str,
    ) -> dict[str, Any]:
        raw_score = risk.get("score")
        if (
            isinstance(raw_score, bool)
            or not isinstance(raw_score, int)
            or not 0 <= raw_score <= 100
        ):
            raise ValueError("Modernization risk score must be an integer from 0 to 100")
        score = raw_score
        if score >= 75:
            priority = "Priority 1"
        elif score >= 50:
            priority = "Priority 2"
        elif score >= 25:
            priority = "Priority 3"
        else:
            priority = "Priority 4"
        known_upgrade = bool(upgrade_path)
        action = (
            upgrade_path
            if upgrade_path.casefold().startswith("remain ")
            else f"Upgrade to {upgrade_path}"
            if known_upgrade
            else "Validate the product/version and establish an approved upgrade path"
        )
        age_years = self._major_gap(str(context.get("version") or ""), upgrade_path)
        complexity = "High" if age_years >= 3 else "Medium" if known_upgrade else "Unknown"
        business_impact = self._business_impact(context, str(risk.get("level") or "Low"))
        raw_confidence = classification.get("confidence")
        if (
            isinstance(raw_confidence, bool)
            or not isinstance(raw_confidence, (int, float))
            or not math.isfinite(raw_confidence)
            or not 0 <= raw_confidence <= 1
        ):
            raise ValueError("Modernization confidence must be finite from 0 to 1")
        confidence = round(
            min(
                float(raw_confidence)
                * (0.8 if context.get("ownership_coverage") else 0.65),
                1.0,
            ),
            2,
        )
        return {
            "priority": priority,
            "impact": business_impact,
            "risk_reduction": int(
                (risk.get("factors") or {}).get("support_timeline") or 0
            )
            if known_upgrade
            else 0,
            "complexity_estimate": complexity,
            "complexity_basis": (
                "High when the detected major-version/year gap is at least three; otherwise Medium."
                if known_upgrade
                else "Unavailable until product/version and upgrade path are validated."
            ),
            "recommended_action": action,
            "evidence": list(classification.get("evidence") or []),
            "lifecycle_status": classification.get("status", "Unknown"),
            "business_impact": business_impact,
            "confidence": confidence,
            "risk_drivers": list(risk.get("risk_drivers") or []),
            "advisory_only": True,
        }

    @staticmethod
    def _business_impact(context: dict[str, Any], risk_level: str) -> str:
        rank = {"low": 1, "moderate": 2, "medium": 2, "high": 3, "critical": 4}
        value = max(
            rank.get(str(context.get("business_criticality") or "").casefold(), 1),
            rank.get(risk_level.casefold(), 1),
        )
        return {1: "Low", 2: "Moderate", 3: "High", 4: "Critical"}[value]

    @staticmethod
    def _major_gap(version: str, upgrade_path: str) -> int:
        digits = [int(item) for item in version.replace(".", " ").split() if item.isdigit()]
        target = [
            int(item)
            for item in upgrade_path.replace(".", " ").split()
            if item.isdigit()
        ]
        if not digits or not target:
            return 0
        return max(target[0] - digits[0], 0)
