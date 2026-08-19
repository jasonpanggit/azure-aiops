from __future__ import annotations


class OperationalDebtEngine:
    """Calculates explainable patch, lifecycle, ownership, configuration, and security debt."""

    def profile(self, context, trend):
        ownership = context.get("ownership_coverage")
        known = context.get("_known_signals") or set()
        categories = {
            "patch_debt": min(int(context.get("patch_debt") or 0) * 5, 100) if "patch_debt" in known else None,
            "lifecycle_debt": min(int(context.get("lifecycle_risk_score") or 0), 100) if "lifecycle_risk_score" in known else None,
            "ownership_debt": 100 if ownership is False else 0 if ownership is True else None,
            "configuration_debt": min(int(context.get("configuration_drift_count") or 0) * 20, 100) if "configuration_drift_count" in known else None,
            "security_debt": min(int(context.get("security_finding_count") or 0) * 20, 100) if "security_finding_count" in known else None,
        }
        known = [value for value in categories.values() if value is not None]
        score = sum(known) // len(known) if known else None
        opportunities = [
            {
                "debt_type": name,
                "current_score": value,
                "preventive_action": f"Review governed {name.replace('_', ' ')} evidence and prioritize an approved reduction plan.",
                "advisory_only": True,
            }
            for name, value in categories.items()
            if value is not None and value >= 25
        ]
        return {
            "score": score,
            "level": self.level(score),
            "categories": categories,
            "trend": {
                "patch_debt_growth": self._trend_value(trend, "patch_debt_growth"),
                "lifecycle_debt_growth": self._trend_value(trend, "lifecycle_exposure_growth"),
                "configuration_debt_growth": self._trend_value(trend, "drift_growth"),
                "ownership_coverage_growth": self._trend_value(
                    trend, "ownership_coverage_growth"
                ),
                "security_debt_growth": self._trend_value(
                    trend, "security_debt_growth"
                ),
            },
            "reduction_opportunities": opportunities,
            "evidence_status": "Known" if len(known) == len(categories) else "Partial" if known else "Unknown",
        }

    @staticmethod
    def level(score):
        if score is None:
            return "Unknown"
        return "Critical" if score >= 75 else "High" if score >= 50 else "Moderate" if score >= 25 else "Low"

    @staticmethod
    def _trend_value(trend, name):
        value=trend.get(name)
        return int(value) if value is not None else None
