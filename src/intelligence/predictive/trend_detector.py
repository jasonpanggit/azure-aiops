from __future__ import annotations

from .predictive_trend_engine import PredictiveTrendEngine


class TrendDetector(PredictiveTrendEngine):
    """Detects improving, stable, and degrading operational patterns."""

    @staticmethod
    def observed_patterns(trend):
        patterns = []
        mapping = (
            ("patch_debt_growth", "Patch debt growth", "Patch debt reduction"),
            ("lifecycle_exposure_growth", "Growing lifecycle exposure", "Lifecycle exposure reduction"),
            ("incident_growth", "Increasing incidents and recurring failures", "Incident reduction"),
            ("drift_growth", "Configuration drift growth", "Configuration drift reduction"),
        )
        for field, degrading, improving in mapping:
            value = int(trend.get(field) or 0)
            if value > 0:
                patterns.append(degrading)
            elif value < 0:
                patterns.append(improving)
        ownership = int(trend.get("ownership_coverage_growth") or 0)
        if ownership > 0:
            patterns.append("Ownership coverage improvement")
        elif ownership < 0:
            patterns.append("Ownership coverage degradation")
        security = int(trend.get("security_debt_growth") or 0)
        if security > 0:
            patterns.append("Security debt growth")
        elif security < 0:
            patterns.append("Security debt reduction")
        return patterns or ["No material trend observed"]
