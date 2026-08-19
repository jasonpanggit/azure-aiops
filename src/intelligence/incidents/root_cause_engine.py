from __future__ import annotations


class RootCauseEngine:
    """Ranks evidence without asserting confirmed root cause."""

    def __init__(self, *, max_items: int = 50) -> None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
            raise ValueError("Root-cause item bound must be a positive integer")
        self.max_items = max_items

    def analyze(self, finding, timeline):
        causes = (finding.get("probable_causes") or [])[: self.max_items]
        contributing = (finding.get("contributing_factors") or [])[: self.max_items]
        top_confidence = max(
            [float(row.get("confidence") or 0) for row in [*causes, *contributing]],
            default=0.0,
        )
        return {
            "probable_causes": causes,
            "contributing_factors": contributing,
            "confidence": min(top_confidence, 0.95),
            "evidence": [
                row
                for cause in [*causes, *contributing]
                for row in cause.get("evidence", [])
            ][: self.max_items],
            "timeline": timeline[: self.max_items],
            "impacted_systems": [
                finding.get("resource"),
                *finding.get("impacted_applications", []),
            ][: self.max_items],
            "reasoning_chain": [
                "Select evidence on the same canonical resource",
                "Require evidence to precede the incident for causal eligibility",
                "Weight temporal proximity, severity, and explicit causal relevance",
                "Treat lifecycle and post-incident evidence as context, not confirmed cause",
            ][: self.max_items],
            "confirmed_cause": False,
            "conclusion": "Probable operational causes ranked for investigation; causality is not confirmed.",
        }
