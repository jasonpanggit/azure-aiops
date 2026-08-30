"""Fabric change-risk and drift assessment pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from intelligence.change.change_intelligence import ChangeIntelligence

OUTPUT_TABLE = "assessment_change_findings"
SOURCE_TAG = "fabric_pipeline:change"


@dataclass(frozen=True)
class ChangePipelineResult:
    table_name: str
    findings: list[dict[str, Any]]
    compliance: list[dict[str, Any]]
    summary: dict[str, Any]


def run(*, now: Any | None = None, **snapshot: Any) -> ChangePipelineResult:
    engine = ChangeIntelligence.from_snapshot(
        **snapshot,
        now=now or (lambda: datetime.now(UTC)),
    )
    analysis = engine.analyze()
    findings = [_finding_row(row) for row in analysis["findings"]]
    return ChangePipelineResult(
        table_name=OUTPUT_TABLE,
        findings=findings,
        compliance=analysis["compliance"],
        summary=analysis["summary"],
    )


def _finding_row(row: Mapping[str, Any]) -> dict[str, Any]:
    change = row.get("change") or {}
    incident = row.get("incident_correlation") or {}
    drift = row.get("configuration_drift") or {}
    return {
        "change_id": str(change.get("change_id") or ""),
        "resource_name": str((row.get("resource") or {}).get("name") or ""),
        "change_type": str(change.get("change_type") or ""),
        "category": str(change.get("category") or ""),
        "authorized": change.get("authorized"),
        "risk_score": int(row.get("risk_score") or 0),
        "risk_level": str(row.get("risk_level") or ""),
        "compliance_score": int(row.get("compliance_score") or 0),
        "configuration_drifted": drift.get("drifted"),
        "drift_fields": list(drift.get("fields") or []),
        "incident_id": str(incident.get("incident_id") or ""),
        "incident_contribution_score": int(incident.get("contribution_score") or 0),
        "application": str(row.get("application") or ""),
        "business_service": str(row.get("business_service") or ""),
        "confirmed_cause": bool(row.get("confirmed_cause") or False),
        "source": SOURCE_TAG,
    }


__all__ = ["OUTPUT_TABLE", "SOURCE_TAG", "ChangePipelineResult", "run"]
