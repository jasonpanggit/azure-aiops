"""Incident and remediation routes.

These front the existing intelligence engines. The engines are constructed per
request from the current knowledge snapshot via provider callables on the API
context, so a refreshed snapshot is observed without a restart. When no
provider is registered the route reports the capability as unavailable rather
than returning an empty result that the UI would render as "all clear".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from ..dependencies import Context, OperatePrincipal, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from ..models import RemediationDecisionRequest
from ..scope import Scope, scope_attributes

router = APIRouter(prefix="/api/v1", tags=["operations"])


def _require(context: Context, attribute: str, capability: str, scope: Scope) -> Any:
    subscription_ids = list(scope.values("subscription"))
    if subscription_ids:
        if capability == "incidents" and context.hybrid_incident_provider is not None:
            return context.hybrid_incident_provider(subscription_ids)
        if (
            capability == "remediation"
            and context.hybrid_remediation_provider is not None
        ):
            return context.hybrid_remediation_provider(subscription_ids)
    return context.resolve_provider(capability)


_HIDDEN = object()


def _filter_scoped(value: Any, scope: Scope) -> Any:
    if scope.is_unrestricted():
        return value
    if isinstance(value, dict):
        attributes = scope_attributes(value)
        if attributes and not scope.matches(attributes):
            return _HIDDEN
        return {
            key: filtered
            for key, child in value.items()
            if (filtered := _filter_scoped(child, scope)) is not _HIDDEN
        }
    if isinstance(value, list):
        return [
            filtered
            for child in value
            if (filtered := _filter_scoped(child, scope)) is not _HIDDEN
        ]
    return value


def _filter_rows(rows: Any, scope: Scope) -> Any:
    filtered = _filter_scoped(rows, scope)
    return [] if filtered is _HIDDEN else filtered


@router.get("/incidents", summary="Correlated incidents")
def list_incidents(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    engine = _require(context, "incident_provider", "incidents", scope)
    report = engine.report()
    incidents = _filter_rows(report.get("incidents"), scope)
    visible = incidents[page.offset : page.offset + page.limit]
    public_report = {**report, "incidents": visible}
    if not scope.is_unrestricted():
        public_report.pop("audience_summaries", None)
        public_report.pop("operational_patterns", None)
        public_report["scope_limited"] = True
    return envelope(
        public_report,
        evidence=Evidence(
            source_engine="intelligence.IncidentEngine",
            source_table="incident_projection",
            timestamp=str(report.get("generated_at") or report.get("freshness") or ""),
            # Incidents are correlated from signals, not observed directly.
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(incidents)),
    )


@router.get("/incidents/{incident_id}", summary="Incident detail and timeline")
def incident_detail(
    incident_id: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    engine = _require(context, "incident_provider", "incidents", scope)
    detail = engine.incident(incident_id)
    if not detail:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Incident not found",
            details={"incident_id": incident_id},
        )
    original_had_finding = isinstance(detail, dict) and "finding" in detail
    detail = _filter_scoped(detail, scope)
    if detail is _HIDDEN or (
        original_had_finding and isinstance(detail, dict) and "finding" not in detail
    ):
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Incident not found",
            details={"incident_id": incident_id},
        )
    return envelope(
        detail,
        evidence=Evidence(
            source_engine="intelligence.IncidentEngine",
            source_table="incident_projection",
            timestamp=str(detail.get("detected_at") or ""),
            resource_id=incident_id,
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
    )


@router.get("/remediation-plans", summary="Remediation plans")
def remediation_plans(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    planner = _require(context, "remediation_provider", "remediation", scope)
    plans = planner.generate_plans()
    visible = _filter_rows(plans.get("plans"), scope)
    if not isinstance(visible, list):
        visible = []
    public = {**plans, "plans": visible[page.offset : page.offset + page.limit]}
    if not scope.is_unrestricted():
        public = {
            "plans": public["plans"],
            "generated_at": plans.get("generated_at", ""),
            "read_only": plans.get("read_only", True),
            "execution_performed": plans.get("execution_performed", False),
            "scope_limited": True,
        }
    return envelope(
        public,
        evidence=Evidence(
            source_engine="intelligence.RemediationPlanner",
            source_table="remediation_plans",
            timestamp=str(plans.get("generated_at") or ""),
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(visible)),
    )


@router.get("/remediation-opportunities", summary="Remediation opportunities")
def remediation_opportunities(
    context: Context, scope: ReadScope, page: Page
) -> dict[str, Any]:
    planner = _require(context, "remediation_provider", "remediation", scope)
    result = planner.identify_opportunities()
    opportunities = _filter_rows(result.get("opportunities"), scope)
    if not isinstance(opportunities, list):
        opportunities = []
    public = {
        **result,
        "opportunities": opportunities[page.offset : page.offset + page.limit],
    }
    if not scope.is_unrestricted():
        public = {
            "opportunities": public["opportunities"],
            "generated_at": result.get("generated_at", ""),
            "read_only": result.get("read_only", True),
            "scope_limited": True,
        }
    return envelope(
        public,
        evidence=Evidence(
            source_engine="intelligence.RemediationPlanner",
            source_table="remediation_opportunities",
            timestamp=str(result.get("generated_at") or ""),
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(opportunities)),
    )


@router.post(
    "/remediation-plans/{plan_id}/decisions",
    summary="Record a remediation recommendation decision",
    status_code=status.HTTP_201_CREATED,
)
def record_remediation_decision(
    plan_id: str,
    request: RemediationDecisionRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    operate_scope = context.authorizer.effective_scope(principal, "operate", scope)
    planner = _require(context, "remediation_provider", "remediation", operate_scope)
    plans = planner.generate_plans()
    plan = planner.repository.get(plan_id)
    if plan is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation plan not found",
            details={"plan_id": plan_id},
        )
    scoped_plan = _filter_scoped(plan, operate_scope)
    if scoped_plan is _HIDDEN:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation plan not found",
            details={"plan_id": plan_id},
        )
    current_version = str(plan.get("action_version") or "")
    if request.action_version != current_version:
        raise ApiError(
            ErrorCode.CONFLICT,
            "Remediation plan action version is stale",
            details={"plan_id": plan_id},
        )
    if not plan.get("read_only", True) or plan.get("execution_performed"):
        raise ApiError(
            ErrorCode.CONFLICT,
            "Remediation decisions cannot authorize or follow execution in this phase",
            details={"plan_id": plan_id},
        )
    if request.decision == "approved" and not request.expires_at.strip():
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Approved remediation decisions require expires_at",
            details={"plan_id": plan_id},
        )
    decision = planner.repository.decisions.append(
        plan=plan,
        decision=request.decision,
        approver=principal.subject,
        reason=request.reason,
        scope=operate_scope.to_dict(),
        action_version=current_version,
        expires_at=request.expires_at,
    )
    return envelope(
        decision,
        evidence=Evidence(
            source_engine="intelligence.RemediationPlanner",
            source_table="remediation_approval_decisions",
            timestamp=str(plans.get("generated_at") or ""),
            resource_id=plan_id,
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=operate_scope.to_dict(),
    )
