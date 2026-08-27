"""Fabric patch-compliance assessment pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from intelligence.patch.patch_intelligence import PatchIntelligence

OUTPUT_TABLE = "assessment_patch_compliance"
SOURCE_TAG = "fabric_pipeline:patch"


@dataclass(frozen=True)
class PatchPipelineResult:
    table_name: str
    findings: list[dict[str, Any]]
    compliance: dict[str, Any]
    summary: dict[str, Any]


def run(
    *,
    resources: list[dict[str, Any]],
    assessments: list[dict[str, Any]],
    installations: list[dict[str, Any]],
    history: list[dict[str, Any]],
    security_findings: list[dict[str, Any]],
    advisor_recommendations: list[dict[str, Any]],
    policies: list[dict[str, Any]],
    freshness: str,
    baselines: list[dict[str, Any]] | None = None,
    windows: list[dict[str, Any]] | None = None,
    now: Any | None = None,
    **kwargs: Any,
) -> PatchPipelineResult:
    engine = PatchIntelligence.from_semantic_snapshot(
        resources=resources,
        assessments=assessments,
        installations=installations,
        history=history,
        security_findings=security_findings,
        advisor_recommendations=advisor_recommendations,
        policies=policies,
        baselines=baselines or [],
        windows=windows or [],
        freshness=freshness,
        now=now or (lambda: datetime.now(UTC)),
        **kwargs,
    )
    analysis = engine.analyze()
    findings = [_finding_row(row) for row in analysis["findings"]]
    return PatchPipelineResult(
        table_name=OUTPUT_TABLE,
        findings=findings,
        compliance=analysis["compliance"],
        summary={
            "finding_count": len(findings),
            "freshness": analysis.get("freshness", ""),
            "read_only": analysis.get("read_only", True),
        },
    )


def _finding_row(row: Mapping[str, Any]) -> dict[str, Any]:
    resource = row.get("resource") or {}
    return {
        "resource_id": str(row.get("resource_key") or resource.get("name") or ""),
        "resource_name": str(resource.get("name") or ""),
        "status": str(row.get("status") or ""),
        "compliance_score": int(row.get("compliance_score") or 0),
        "patch_policy": str(row.get("patch_policy") or ""),
        "policy_compliant": row.get("policy_compliant"),
        "compliance_debt": int(row.get("compliance_debt") or 0),
        "risk_score": int(row.get("risk_score") or 0),
        "risk_level": str(row.get("risk_level") or ""),
        "missing_critical_updates": int(row.get("missing_critical_updates") or 0),
        "missing_security_updates": int(row.get("missing_security_updates") or 0),
        "patch_age_days": int(row.get("patch_age_days") or 0),
        "highest_severity": str(row.get("highest_severity") or ""),
        "priority": str(row.get("priority") or ""),
        "application": str(row.get("application") or ""),
        "business_service": str(row.get("business_service") or ""),
        "source": SOURCE_TAG,
    }


__all__ = ["OUTPUT_TABLE", "SOURCE_TAG", "PatchPipelineResult", "run"]
