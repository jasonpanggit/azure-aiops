"""Low-cardinality ontology discovery metrics and exact alert metadata.

The alert signal intentionally carries only a closed rule identifier and closed
operational enums. Durable records, rather than telemetry dimensions, retain
scope, pair, principal, resource, and error details.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from opentelemetry import metrics

AlertTier = Literal["immediate", "page", "hour", "weekly"]
AlertOperator = Literal["GreaterThan", "GreaterThanOrEqual", "LessThan"]


@dataclass(frozen=True)
class AlertRule:
    """Safe metadata shared by metric emission, tests, and smoke validation."""

    tier: AlertTier
    threshold: float
    operator: AlertOperator
    window: str
    severity: int
    shadow_reset: bool
    metric_name: str = "ontology.discovery.alert.signal"
    action_group: str = "ontology-operations"


def _rule(
    tier: AlertTier,
    threshold: float,
    operator: AlertOperator,
    window: str,
    severity: int,
    *,
    shadow_reset: bool = False,
) -> AlertRule:
    return AlertRule(
        tier=tier,
        threshold=threshold,
        operator=operator,
        window=window,
        severity=severity,
        shadow_reset=shadow_reset,
    )


ALERT_RULES: Mapping[str, AlertRule] = MappingProxyType(
    {
        "scope_disclosure": _rule(
            "immediate", 0, "GreaterThan", "PT5M", 0, shadow_reset=True
        ),
        "unauthorized_mutation": _rule(
            "immediate", 0, "GreaterThan", "PT5M", 0, shadow_reset=True
        ),
        "successful_injection": _rule(
            "immediate", 0, "GreaterThan", "PT5M", 0, shadow_reset=True
        ),
        "invalid_edge_promotion": _rule(
            "immediate", 0, "GreaterThan", "PT5M", 0, shadow_reset=True
        ),
        "stale_writer_promotion": _rule(
            "immediate", 0, "GreaterThan", "PT5M", 0, shadow_reset=True
        ),
        "partial_active_generation": _rule(
            "immediate", 0, "GreaterThan", "PT5M", 0, shadow_reset=True
        ),
        "missing_audit": _rule(
            "immediate", 0, "GreaterThan", "PT5M", 0, shadow_reset=True
        ),
        "active_generation_unrecoverable": _rule(
            "immediate", 0, "GreaterThan", "PT5M", 0, shadow_reset=True
        ),
        "successful_run_gap": _rule("page", 30, "GreaterThan", "PT30M", 1),
        "active_generation_age": _rule(
            "page", 21_600, "GreaterThan", "PT15M", 1
        ),
        "fenced_publication_failures": _rule(
            "page", 2, "GreaterThanOrEqual", "PT15M", 1
        ),
        "critical_pending_edge_age": _rule(
            "page", 86_400, "GreaterThan", "PT15M", 1
        ),
        "nonterminal_run_age": _rule(
            "page", 2_700, "GreaterThan", "PT15M", 1
        ),
        "citation_validity": _rule("hour", 1, "LessThan", "PT1H", 2),
        "citation_freshness": _rule("hour", 0.99, "LessThan", "PT1H", 2),
        "post_repair_schema_validity": _rule(
            "hour", 1, "LessThan", "PT1H", 1
        ),
        "repair_rate": _rule("hour", 0.05, "GreaterThan", "PT1H", 2),
        "timeout_rate": _rule("hour", 0.01, "GreaterThan", "PT1H", 2),
        "model_latency_p95": _rule(
            "hour", 30, "GreaterThan", "PT15M", 2
        ),
        "attempt_duration_max": _rule(
            "hour", 60, "GreaterThan", "PT1H", 1
        ),
        "cap_violation": _rule("hour", 0, "GreaterThan", "PT1H", 1),
        "overall_precision": _rule(
            "weekly", 0.98, "LessThan", "P2D", 1, shadow_reset=True
        ),
        "critical_precision": _rule(
            "weekly", 0.95, "LessThan", "P2D", 1, shadow_reset=True
        ),
        "overall_recall": _rule(
            "weekly", 0.90, "LessThan", "P2D", 2, shadow_reset=True
        ),
        "critical_recall": _rule(
            "weekly", 0.85, "LessThan", "P2D", 2, shadow_reset=True
        ),
        "escalation_f1": _rule(
            "weekly", 0.95, "LessThan", "P2D", 1, shadow_reset=True
        ),
        "mandatory_review_recall": _rule(
            "weekly", 1, "LessThan", "P2D", 0, shadow_reset=True
        ),
        "pair_precision_wilson_lower_bound": _rule(
            "weekly", 0.98, "LessThan", "P2D", 1, shadow_reset=True
        ),
    }
)


class OntologyDiscoveryTelemetry:
    """Emit content-free measurements with a fixed cardinality ceiling."""

    def __init__(self, meter: object | None = None) -> None:
        resolved = meter or metrics.get_meter("aiops.ontology_discovery", "0.1.0")
        self.alert_signal = resolved.create_histogram(
            "ontology.discovery.alert.signal"
        )
        self.run_duration = resolved.create_histogram(
            "ontology.discovery.run.duration", unit="s"
        )
        self.stale_writer_blocked = resolved.create_counter(
            "ontology.discovery.publication.stale_writer_blocked"
        )

    def emit_alert_signal(
        self,
        rule_id: str,
        value: float,
        *,
        status: Literal["observed", "synthetic_violation"] = "observed",
    ) -> None:
        """Record one alert input without identifiers or caller-defined labels."""

        rule = ALERT_RULES.get(rule_id)
        if rule is None:
            raise ValueError("unknown ontology alert rule")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("ontology alert values must be finite")
        if status not in {"observed", "synthetic_violation"}:
            raise ValueError("unknown ontology alert status")
        self.alert_signal.record(
            number,
            {
                "rule": rule_id,
                "tier": rule.tier,
                "status": status,
                "reset_scope": "affected_pair" if rule.shadow_reset else "none",
            },
        )

    def record_run_duration(
        self,
        seconds: float,
        *,
        outcome: Literal["completed", "failed", "cancelled", "timed_out"],
    ) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("run duration must be a finite non-negative value")
        if outcome not in {"completed", "failed", "cancelled", "timed_out"}:
            raise ValueError("unknown run outcome")
        self.run_duration.record(float(seconds), {"outcome": outcome})

    def record_stale_writer_blocked(self) -> None:
        self.stale_writer_blocked.add(1)


def violating_smoke_value(rule: AlertRule) -> float:
    """Return a finite synthetic value guaranteed to cross ``rule``."""

    if rule.operator == "LessThan":
        return max(0.0, rule.threshold - 0.01)
    if rule.operator == "GreaterThanOrEqual":
        return rule.threshold
    return rule.threshold + max(0.01, abs(rule.threshold) * 0.01)


def emit_sanitized_alert_smoke(
    telemetry: OntologyDiscoveryTelemetry,
) -> tuple[str, ...]:
    """Emit exactly one sanitized violating measurement per production rule."""

    for rule_id, rule in ALERT_RULES.items():
        telemetry.emit_alert_signal(
            rule_id,
            violating_smoke_value(rule),
            status="synthetic_violation",
        )
    return tuple(ALERT_RULES)


__all__ = [
    "ALERT_RULES",
    "AlertRule",
    "OntologyDiscoveryTelemetry",
    "emit_sanitized_alert_smoke",
    "violating_smoke_value",
]
