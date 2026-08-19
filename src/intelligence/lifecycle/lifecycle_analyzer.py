from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .eol_catalog import EOLCatalog
from .lifecycle_context_builder import LifecycleContextBuilder
from .lifecycle_risk_engine import LifecycleRiskEngine
from .modernization_engine import ModernizationEngine


class LifecycleAnalyzer:
    """Correlates catalog lifecycle state with governed operational context."""

    def __init__(
        self,
        catalog: EOLCatalog,
        context_builder: LifecycleContextBuilder,
        *,
        risk_engine: LifecycleRiskEngine | None = None,
        modernization_engine: ModernizationEngine | None = None,
        clock=time.monotonic,
        telemetry=None,
    ) -> None:
        self.catalog = catalog
        self.context_builder = context_builder
        self.risk_engine = risk_engine or LifecycleRiskEngine()
        self.modernization_engine = modernization_engine or ModernizationEngine()
        self.clock = clock
        self.telemetry = telemetry

    def analyze(
        self, *, now: datetime, include_internal_identity: bool = False
    ) -> list[dict[str, Any]]:
        findings = []
        for context in self.context_builder.all():
            entry = self.catalog.lookup(context["product"], context["version"])
            classification_model = self.catalog.classify_product(
                context["product"],
                context["version"],
                now=now,
                support_channel=context["support_channel"] or None,
            )
            classification = classification_model.to_dict()
            risk_started = self.clock()
            risk = self.risk_engine.calculate(
                context=context, classification=classification
            )
            if self.telemetry is not None:
                self.telemetry.risk_latency.record(self.clock() - risk_started)
            impact_started = self.clock()
            recommendation = self.modernization_engine.recommend(
                context=context,
                classification=classification,
                risk=risk,
                upgrade_path=entry.recommended_upgrade_path if entry else "",
            )
            if self.telemetry is not None:
                self.telemetry.business_impact_latency.record(
                    self.clock() - impact_started
                )
            public_context = {
                key: value for key, value in context.items() if not key.startswith("_")
            }
            public_context["support_channel"] = classification["support_channel"]
            finding = {
                    **public_context,
                    "lifecycle_status": classification["status"],
                    "lifecycle_classification": (
                        "Expired"
                        if classification["status"] == "EOL"
                        else classification["status"]
                    ),
                    "support_end": classification["support_end"],
                    "days_remaining": classification["days_remaining"],
                    "risk_score": risk["score"],
                    "risk_level": risk["level"],
                    "risk_factors": risk["factors"],
                    "risk_drivers": risk["risk_drivers"],
                    "risk_justification": risk["justification"],
                    "business_impact": recommendation["business_impact"],
                    "modernization_recommendation": recommendation,
                    "evidence": classification["evidence"],
                    "confidence": recommendation["confidence"],
                    "advisory_only": True,
                }
            if include_internal_identity:
                finding["_resource_key"] = context["_resource_key"]
            findings.append(finding)
        priority = {"Critical": 0, "High": 1, "Moderate": 2, "Low": 3}
        return sorted(
            findings,
            key=lambda item: (
                priority.get(str(item["risk_level"]), 4),
                -int(item["risk_score"]),
                str(item["resource"]["name"]),
            ),
        )
