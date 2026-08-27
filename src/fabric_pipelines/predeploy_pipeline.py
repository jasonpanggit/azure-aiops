"""Fabric pre-deployment impact assessment pipeline."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from intelligence.predeploy import PreDeploymentImpactService

OUTPUT_TABLE = "assessment_predeploy_evaluations"
SOURCE_TAG = "fabric_pipeline:predeploy"


@dataclass(frozen=True)
class PredeployPipelineResult:
    table_name: str
    evaluations: list[dict[str, Any]]
    summary: dict[str, Any]


def run(
    *,
    proposed_changes: Iterable[Mapping[str, Any]],
    discovered: list[Mapping[str, Any]],
    vulnerability_index: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> PredeployPipelineResult:
    service = PreDeploymentImpactService()
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(proposed_changes):
        payload = dict(item.get("payload") or {})
        source = str(item.get("source") or "terraform_plan")
        assessment = service.assess(
            source=source,
            payload=payload,
            discovered=discovered,
            change_id=str(item.get("change_id") or f"fabric-predeploy-{index}"),
            vulnerability_index=vulnerability_index,
        )
        rows.append(_evaluation_row(assessment))
    return PredeployPipelineResult(
        table_name=OUTPUT_TABLE,
        evaluations=rows,
        summary={
            "evaluation_count": len(rows),
            "max_risk_score": max((row["risk_score"] for row in rows), default=0),
            "source": SOURCE_TAG,
        },
    )


def _evaluation_row(assessment: Mapping[str, Any]) -> dict[str, Any]:
    change = assessment.get("change") or {}
    risk = assessment.get("risk") or {}
    cab = assessment.get("cab_recommendation") or {}
    blast = assessment.get("blast_radius") or {}
    return {
        "assessment_id": str(assessment.get("assessment_id") or ""),
        "change_id": str(change.get("change_id") or ""),
        "source_system": str(change.get("source") or ""),
        "risk_score": int(risk.get("score") or 0),
        "risk_level": str(risk.get("level") or ""),
        "confidence": str(risk.get("confidence") or ""),
        "cab_verdict": str(cab.get("verdict") or ""),
        "cab_summary": str(cab.get("summary") or ""),
        "total_impacted_count": int(blast.get("total_impacted_count") or 0),
        "business_services": list(blast.get("business_services") or []),
        "state_consistent": bool((assessment.get("state_comparison") or {}).get("consistent")),
        "confirmed_cause": bool(assessment.get("confirmed_cause") or False),
        "source": SOURCE_TAG,
    }


__all__ = ["OUTPUT_TABLE", "SOURCE_TAG", "PredeployPipelineResult", "run"]
