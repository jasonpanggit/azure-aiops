"""Fabric lifecycle assessment pipeline.

Ports the Hermes lifecycle analysis surface to the API-triggered Fabric sync
path by reusing ``LifecycleIntelligence`` directly over Fabric/Lakehouse rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from intelligence.lifecycle.lifecycle_intelligence import LifecycleIntelligence

OUTPUT_TABLE = "assessment_lifecycle_findings"
SOURCE_TAG = "fabric_pipeline:lifecycle"


@dataclass(frozen=True)
class LifecyclePipelineResult:
    table_name: str
    findings: list[dict[str, Any]]
    summary: dict[str, Any]


def run(
    *,
    resources: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    history: list[dict[str, Any]],
    freshness: str,
    now: Any | None = None,
    **kwargs: Any,
) -> LifecyclePipelineResult:
    engine = LifecycleIntelligence.from_snapshot(
        resources=resources,
        catalog=catalog,
        history=history,
        freshness=freshness,
        now=now or (lambda: datetime.now(UTC)),
        **kwargs,
    )
    analysis = engine.analyze()
    findings = [_finding_row(row) for row in analysis["findings"]]
    return LifecyclePipelineResult(
        table_name=OUTPUT_TABLE,
        findings=findings,
        summary={
            "finding_count": len(findings),
            "freshness": analysis.get("freshness", ""),
            "read_only": analysis.get("read_only", True),
        },
    )


def _finding_row(row: Mapping[str, Any]) -> dict[str, Any]:
    resource = row.get("resource") or {}
    recommendation = row.get("modernization_recommendation") or {}
    return {
        "resource_id": str(row.get("resource_key") or resource.get("resource_id") or resource.get("name") or ""),
        "resource_name": str(resource.get("name") or ""),
        "product": str(row.get("product") or ""),
        "version": str(row.get("version") or ""),
        "lifecycle_status": str(row.get("lifecycle_status") or ""),
        "days_remaining": int(row.get("days_remaining") or 0),
        "risk_score": int(row.get("risk_score") or 0),
        "risk_level": str(row.get("risk_level") or ""),
        "business_impact": str(row.get("business_impact") or ""),
        "modernization_priority": str(recommendation.get("priority") or ""),
        "recommended_action": str(recommendation.get("recommended_action") or ""),
        "application": str(row.get("application") or ""),
        "business_service": str(row.get("business_service") or ""),
        "owner": str(row.get("owner") or ""),
        "support_team": str(row.get("support_team") or ""),
        "confidence": float(row.get("confidence") or 0.0),
        "source": SOURCE_TAG,
    }


__all__ = ["OUTPUT_TABLE", "SOURCE_TAG", "LifecyclePipelineResult", "run"]
