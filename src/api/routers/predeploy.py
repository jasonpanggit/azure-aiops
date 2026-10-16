"""Pre-deployment change risk and impact assessment API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

# Imported from submodules rather than the package root: the package __init__
# imports modules that import ``api``, so routing through it here would make
# ``import intelligence.predeploy`` fail whenever it is imported before ``api``.
from intelligence.predeploy.discovery import project_discovered_resources
from intelligence.predeploy.intake import inspect_artifact
from intelligence.predeploy.models import CHANGE_SOURCES
from intelligence.predeploy.service import SOURCE_ENGINE, PreDeploymentImpactService
from intelligence.predeploy.simulation import SIMULATION_DOMAINS

from ..artifact_request import ArtifactRoute
from ..dependencies import Context, CurrentPrincipal, Page, ReadScope, WritePrincipal
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope
from ..models import ChangeAssessmentRequest
from ..scope import Scope
from .network import resolve_finding_review

router = APIRouter(prefix="/api/v1", tags=["predeploy"], route_class=ArtifactRoute)

# Assessments are user-submitted mutations rather than snapshot projections, so
# like the settings and risk-exception stores they live in a module-level
# handle rather than being rebuilt per request. Keeping them here also means an
# assessment stays readable after the snapshot it was derived from is replaced,
# but remains bounded process-local history, not a durable audit trail.
_SERVICE = PreDeploymentImpactService()


def _service(context: Context) -> PreDeploymentImpactService:
    override = getattr(context, "predeploy_service", None)
    if isinstance(override, PreDeploymentImpactService):
        return override
    if callable(override):
        resolved = override()
        if isinstance(resolved, PreDeploymentImpactService):
            return resolved
    return _SERVICE


def _evidence(assessment: dict[str, Any] | None = None) -> Evidence:
    risk = (assessment or {}).get("risk", {})
    change = (assessment or {}).get("change", {})
    return Evidence(
        source_engine=SOURCE_ENGINE,
        source_table="proposed_change_assessment",
        timestamp=str((assessment or {}).get("assessed_at") or ""),
        resource_id=str(change.get("change_id") or ""),
        confidence=str(risk.get("confidence") or "unknown"),
    )


@router.get("/changes/assessment-sources", summary="Supported change ingestion sources")
def assessment_sources(scope: ReadScope) -> dict[str, Any]:
    return envelope(
        {
            "sources": list(CHANGE_SOURCES),
            "simulation_domains": list(SIMULATION_DOMAINS),
            "verdicts": ["approve", "approve_with_conditions", "require_review"],
        },
        evidence=Evidence(
            source_engine=SOURCE_ENGINE,
            source_table="predeploy_capabilities",
            confidence="high",
        ),
        scope=scope.to_dict(),
    )


@router.post(
    "/changes/assess",
    status_code=201,
    summary="Assess a proposed change before deployment",
)
def assess_change(
    payload: ChangeAssessmentRequest,
    context: Context,
    principal: WritePrincipal,
    scope: ReadScope,
) -> dict[str, Any]:
    if payload.source not in CHANGE_SOURCES:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            f"Unsupported change source '{payload.source}'",
            details={"supported_sources": list(CHANGE_SOURCES)},
        )
    try:
        inspect_artifact(payload.source, payload.payload)
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc

    # Assessment reads the estate, so it runs under the caller's *read* scope
    # even though submitting is a write. A caller must not be able to widen the
    # estate view they see by submitting a change.
    review = (
        resolve_finding_review(context, scope, payload.network_review)
        if payload.network_review is not None else None
    )
    discovered = _discovered(context, scope)

    assessment = _service(context).assess(
        source=payload.source,
        payload=payload.payload,
        discovered=discovered,
        scope=scope,
        change_id=payload.change_id,
        network_review=review,
        reviewed_by=principal.subject,
    )
    assessment["submitted_by"] = getattr(principal, "subject", "")
    return envelope(
        assessment,
        evidence=_evidence(assessment),
        scope=scope.to_dict(),
    )


def _review_visible(assessment: dict | None, principal: CurrentPrincipal, scope: Scope) -> bool:
    return assessment is not None and (
        "network_review" not in assessment or (
            assessment.get("network_review_subject") == principal.subject
            and assessment.get("scope") == scope.to_dict()
        )
    )


@router.get("/changes/assessments", summary="List pre-deployment assessments")
def list_assessments(context: Context, scope: ReadScope, page: Page, principal: CurrentPrincipal) -> dict[str, Any]:
    service = _service(context)
    rows = [
        row for row in service.list_assessments(scope=scope)
        if _review_visible(service.get_assessment(row["assessment_id"]), principal, scope)
    ]
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.get(
    "/changes/assessments/{assessment_id}",
    summary="Read one pre-deployment assessment",
)
def get_assessment(
    assessment_id: str,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    service = _service(context)
    assessment = service.get_assessment(assessment_id)
    # Re-check visibility through the same listing filter rather than trusting
    # the id: a direct fetch must not become a way around scope isolation.
    visible = {row["assessment_id"] for row in service.list_assessments(scope=scope)}
    if assessment is None or assessment_id not in visible or not _review_visible(assessment, principal, scope):
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"Assessment '{assessment_id}' was not found in the authorized scope",
            details={"assessment_id": assessment_id},
        )
    return envelope(assessment, evidence=_evidence(assessment), scope=scope.to_dict())


@router.get(
    "/changes/assessments/{assessment_id}/explain",
    summary="Narratable briefing for one pre-deployment assessment",
)
def explain_assessment(
    assessment_id: str,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Answer "what might this change affect, and what is required first?".

    Copilot's question route grounds free text in the knowledge layer, which
    cannot supply a plan that has not been deployed. This returns the same
    stored assessment reduced to the handful of statements worth narrating,
    with every qualifier attached, so a summary cannot be produced by dropping
    them.
    """
    assessment = get_assessment(assessment_id, context, scope, principal)["data"]
    risk = assessment.get("risk", {})
    cab = assessment.get("cab_recommendation", {})
    blast = assessment.get("blast_radius", {})
    simulation = assessment.get("simulation", {})

    services = list(blast.get("business_services") or [])
    validations = [
        f"{effect.get('domain')}: {effect.get('detail')}"
        for effect in simulation.get("effects") or []
        if effect.get("requires_validation")
    ]

    return envelope(
        {
            "assessment_id": assessment.get("assessment_id"),
            "question": "What might this change affect before it is deployed?",
            "what_may_be_affected": blast.get("impacted_resources") or [],
            "business_services_affected": services,
            "why": risk.get("evidence") or [],
            "required_validation": validations,
            "required_approvals": cab.get("required_approvals") or [],
            "conditions": cab.get("conditions") or [],
            "verdict": cab.get("verdict"),
            "risk_score": risk.get("score"),
            "risk_level": risk.get("level"),
            "confidence": risk.get("confidence"),
            "unknowns": risk.get("unknowns") or [],
            # Repeated on the narration payload itself: a model summarizing
            # this must not be able to reach a causal claim by omitting the
            # qualifiers carried on the underlying stages.
            "interpretation": (
                "This describes dependency reach and declared configuration for a change that "
                "has not been deployed. It does not observe runtime behaviour and does not "
                "establish that any listed resource would be disrupted."
            ),
            "confirmed_cause": False,
            "network_review": assessment.get("network_review"),
        },
        evidence=_evidence(assessment),
        scope=scope.to_dict(),
    )


def _discovered(context: Context, scope: Scope) -> list[Any]:
    """Project discovered state, degrading to empty when no snapshot is loaded.

    A missing snapshot must not fail the request: the pipeline already reports
    an absent estate view as a declared unknown and drops confidence to
    ``unknown``, which correctly routes the change to human review instead of
    silently producing a confident-looking score.
    """
    try:
        engine = context.semantic()
    except ApiError:
        return []
    return project_discovered_resources(engine, scope=scope)
