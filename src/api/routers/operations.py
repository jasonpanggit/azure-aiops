"""Incident and remediation routes.

These front the existing intelligence engines. The engines are constructed per
request from the current knowledge snapshot via provider callables on the API
context, so a refreshed snapshot is observed without a restart. When no
provider is registered the route reports the capability as unavailable rather
than returning an empty result that the UI would render as "all clear".
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, status

from intelligence.remediation.approval_decisions import (
    CONTROLLED_PATCH_RECOVERY,
    ExecutionSnapshotError,
    build_execution_snapshot,
)
from operations.defender_configuration import DEFENDER_CONFIGURATION_ACTION_IDS

from ..dependencies import Context, OperatePrincipal, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from ..models import RemediationDecisionRequest
from ..scope import Scope, scope_attributes
from .patching import _service as _patching_service

router = APIRouter(prefix="/api/v1", tags=["operations"])


def _onboarded_subscription_ids(context: Context) -> list[str]:
    connections = context.onboarding.registry.list(include_disabled=False)
    seen: dict[str, None] = {}
    for connection in connections:
        seen.setdefault(str(connection.subscription_id), None)
    return list(seen)


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
    elif (
        capability == "remediation"
        and context.hybrid_remediation_provider is not None
        and scope.is_unrestricted()
    ):
        # No subscription picked in the operating-context selector: fall back
        # to every onboarded subscription instead of the static Fabric
        # snapshot, so "all subscriptions" shows live plans rather than 0.
        all_subscription_ids = _onboarded_subscription_ids(context)
        if all_subscription_ids:
            return context.hybrid_remediation_provider(all_subscription_ids)
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


def _plan_resource_key(row: dict[str, Any]) -> str:
    resource = row.get("resource") if isinstance(row.get("resource"), dict) else {}
    return str(
        row.get("resource_key")
        or resource.get("resource_key")
        or resource.get("id")
        or ""
    ).strip()


def _future_expiry(value: str, *, now: datetime | None = None) -> str:
    text = value.strip()
    if not text:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Approved remediation decisions must include expires_at (future-dated ISO-8601 timestamp); "
            "rejected and expired decisions must not include expires_at",
        )
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Approved remediation decision expires_at must be a valid ISO-8601 timestamp",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    if parsed <= (now or datetime.now(UTC)):
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Approved remediation decision expires_at must be in the future",
        )
    return parsed.isoformat().replace("+00:00", "Z")


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
def remediation_plans(
    context: Context, scope: ReadScope, page: Page, resource_key: str = ""
) -> dict[str, Any]:
    planner = _require(context, "remediation_provider", "remediation", scope)
    plans = planner.generate_plans()
    visible = _filter_rows(plans.get("plans"), scope)
    if not isinstance(visible, list):
        visible = []
    if resource_key:
        canonical = resource_key.strip().casefold()
        visible = [
            row
            for row in visible
            if _plan_resource_key(row).casefold() == canonical
        ]
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


@router.get("/remediation/defender-cases", summary="Defender-correlated remediation cases")
def defender_remediation_cases(
    context: Context, scope: ReadScope, page: Page
) -> dict[str, Any]:
    planner = _require(context, "remediation_provider", "remediation", scope)
    correlator = getattr(planner, "defender_correlator", None)
    if (
        correlator is None
        and context.hybrid_remediation_provider is not None
        and not list(scope.values("subscription"))
        and scope.is_unrestricted()
    ):
        subscription_ids = _onboarded_subscription_ids(context)
        if subscription_ids:
            live_planner = context.hybrid_remediation_provider(subscription_ids)
            correlator = getattr(live_planner, "defender_correlator", None)
    if correlator is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Defender remediation correlation is unavailable",
        )
    cases = correlator.cases(scope)
    visible = _filter_rows(cases, scope)
    if not isinstance(visible, list):
        visible = []
    warnings = sorted(
        {
            f"Defender source family '{source_type}' is {status.get('availability') or 'unknown'}"
            for case in visible
            for source_type, status in (case.get("source_family_status") or {}).items()
            if str(status.get("availability") or "unknown") != "available"
        }
    )
    public = {
        "cases": visible[page.offset : page.offset + page.limit],
        "read_only": True,
    }
    return envelope(
        public,
        evidence=Evidence(
            source_engine="intelligence.DefenderRemediationCorrelator",
            source_table="defender_remediation_cases",
            timestamp=str(getattr(correlator.vulnerability_service, "freshness", "") or ""),
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(visible)),
        warnings=warnings,
    )


@router.get("/remediation-plans/{plan_id}/decisions", summary="Read remediation decisions for a plan")
def read_remediation_decisions(
    plan_id: str,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    planner = _require(context, "remediation_provider", "remediation", scope)
    planner.generate_plans()  # Ensure plans are current
    plan = planner.repository.get(plan_id)
    if plan is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation plan not found",
            details={"plan_id": plan_id},
        )
    scoped_plan = _filter_scoped(plan, scope)
    if scoped_plan is _HIDDEN:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation plan not found",
            details={"plan_id": plan_id},
        )
    decisions = planner.repository.decisions.list(plan_id)
    return envelope(
        {"decisions": decisions, "plan_id": plan_id},
        evidence=Evidence(
            source_engine="intelligence.RemediationPlanner",
            source_table="remediation_approval_decisions",
            timestamp="",
            resource_id=plan_id,
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
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
    
    # Validate expires_at ONLY for approved decisions; reject/expired must be empty
    expires_at = ""
    revalidation_checks = [
        "plan_exists",
        "scope_authorized",
        "action_version_current",
        "execution_boundary_read_only",
        "defender_evidence_fresh",
    ]
    if request.decision == "approved":
        expires_at = _future_expiry(request.expires_at)
        revalidation_checks.append("approval_not_expired")
    elif request.decision in ("rejected", "expired"):
        # Reject decisions must not carry expires_at metadata
        if request.expires_at.strip():
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                f"Decision '{request.decision}' must not include expires_at; use empty string",
            )
        expires_at = ""

    execution_snapshot = None
    action_id = str(plan.get("action_id") or plan.get("opportunity_type") or "")
    if request.decision == "approved" and action_id == CONTROLLED_PATCH_RECOVERY:
        try:
            execution_snapshot = build_execution_snapshot(
                plan,
                _patching_service(context, operate_scope),
                scope=operate_scope,
            )
        except ExecutionSnapshotError as exc:
            raise ApiError(
                ErrorCode.CONFLICT,
                str(exc),
                {"reason": exc.reason, **exc.details},
            ) from exc
        if not hmac.compare_digest(
            request.preview_snapshot_hash,
            execution_snapshot["snapshot_hash"],
        ):
            raise ApiError(
                ErrorCode.CONFLICT,
                "The executable patch target changed after preview",
                {
                    "reason": "stale_execution_preview",
                    "plan_id": plan_id,
                },
            )
        revalidation_checks.append("execution_snapshot_current")
    elif (
        request.decision == "approved"
        and action_id in DEFENDER_CONFIGURATION_ACTION_IDS
    ):
        provider = getattr(context, "execution_provider", None)
        service = provider(operate_scope) if callable(provider) else None
        if service is None:
            raise ApiError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Defender configuration execution is not configured",
                {"capability": "defender_configuration"},
            )
        try:
            execution_snapshot = service.build_execution_snapshot(
                plan, scope=operate_scope
            )
        except ExecutionSnapshotError as exc:
            raise ApiError(
                ErrorCode.CONFLICT,
                str(exc),
                {"reason": exc.reason, **exc.details},
            ) from exc
        if not hmac.compare_digest(
            request.preview_snapshot_hash,
            execution_snapshot["snapshot_hash"],
        ):
            raise ApiError(
                ErrorCode.CONFLICT,
                "The executable Defender configuration changed after preview",
                {
                    "reason": "stale_execution_preview",
                    "plan_id": plan_id,
                },
            )
        revalidation_checks.append("execution_snapshot_current")

    decision = planner.repository.decisions.append(
        plan=plan,
        decision=request.decision,
        approver=principal.subject,
        reason=request.reason,
        scope=operate_scope.to_dict(),
        action_version=current_version,
        expires_at=expires_at,
        revalidation_checks=revalidation_checks,
        execution_snapshot=execution_snapshot,
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
