"""OpenTelemetry metrics for Gold-grounding retrieval safety and health."""

from __future__ import annotations

from opentelemetry import metrics


class GoldGroundingMetrics:
    def __init__(self, meter=None) -> None:
        meter = meter or metrics.get_meter("aiops.gold_grounding", "0.1.0")
        self.queries = meter.create_counter("gold_grounding.queries")
        self.degraded = meter.create_counter(
            "gold_grounding.degraded",
            description="isError / unavailable / stale / deployment-blocked responses",
        )
        self.scope_violations_blocked = meter.create_counter(
            "gold_grounding.scope_violations.blocked"
        )
        self.citation_count = meter.create_histogram("gold_grounding.citations.count")
        self.freshness_age_seconds = meter.create_histogram(
            "gold_grounding.citation.freshness_age", unit="s"
        )
        self.circuit_open = meter.create_counter("gold_grounding.circuit_breaker.opened")
        self.preflight_rejected = meter.create_counter(
            "gold_grounding.publication.preflight_rejected"
        )
        self.inventory_conflict = meter.create_counter(
            "gold_grounding.inventory_conflict.flagged"
        )
        self.latency = meter.create_histogram("gold_grounding.query.duration", unit="ms")

    def record_query(
        self, *, degraded: bool, degraded_reason: str, citation_count: int, duration_ms: float
    ) -> None:
        attributes = {"degraded": str(degraded)}
        self.queries.add(1, attributes)
        self.latency.record(duration_ms, attributes)
        self.citation_count.record(citation_count)
        if degraded:
            self.degraded.add(1, {"reason": (degraded_reason or "unspecified")[:40]})
