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
from intelligence.remediation.approval_gate import (
    authorize_role_attestation,
    requirement_satisfaction,
)
from operations.defender_configuration import DEFENDER_CONFIGURATION_ACTION_IDS

from ..dependencies import (
    ApprovePrincipal,
    Context,
    Page,
    ReadScope,
    live_subscription_ids,
)
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from ..models import RemediationDecisionRequest
from ..rbac import ROLE_ADMIN, ROLE_APPROVER
from ..scope import Scope, scope_attributes
from .patching import _service as _patching_service

router = APIRouter(prefix="/api/v1", tags=["operations"])


def _require(context: Context, attribute: str, capability: str, scope: Scope) -> Any:
    subscription_ids = live_subscription_ids(
        context,
        scope,
        default_all=(
            capability in {"incidents", "remediation"} and scope.is_unrestricted()
        ),
    )
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


def _resolve_approval_role_selection(
    *,
    plan_id: str,
    requirements: list[dict[str, Any]],
    existing_decisions: list[dict[str, Any]],
    current_version: str,
    current_snapshot_hash: str,
    policy_version: str,
    requested_role_id: str,
    principal: Any,
) -> tuple[str, bool]:
    """Resolve exactly which requirement row this decision attests.

    Phase 03.5 CR-05 fix: a decision satisfies at most one
    ``approval_requirements`` row. Returns ``(role_id, admin_override)`` --
    ``role_id`` is ``""`` when this plan has no requirements at all (a
    vacuous plan; no role concept applies) or when every requirement row
    is already satisfied (nothing left to attest; the decision is still
    recorded, e.g. a redundant re-approval, but attests no specific role).

    Raises ``ApiError`` (400 ``role_id`` not found on this plan; 400 role
    selection required when more than one unmet row is eligible for this
    principal; 403 when the principal is authorized for none of the unmet
    rows) rather than ever silently guessing.
    """
    if not requirements:
        return "", False

    def _row_role_id(row: dict[str, Any]) -> str:
        return str(row.get("role_id") or row.get("role") or "").strip()

    satisfaction = requirement_satisfaction(
        requirements,
        existing_decisions,
        current_action_version=current_version,
        current_snapshot_hash=current_snapshot_hash,
        policy_version=policy_version,
        now=datetime.now(UTC),
    )
    unmet = [row for row in satisfaction if not row.get("satisfied")]

    if requested_role_id:
        by_role_id = {_row_role_id(row).casefold(): row for row in satisfaction}
        row = by_role_id.get(requested_role_id.strip().casefold())
        if row is None:
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                "role_id does not match any approval requirement on this plan",
                details={"plan_id": plan_id, "role_id": requested_role_id},
            )
    elif not unmet:
        return "", False
    else:
        eligible_by_role_id: dict[str, dict[str, Any]] = {}
        for candidate in unmet:
            authorized, _ = authorize_role_attestation(
                role_id=_row_role_id(candidate),
                role_text=str(candidate.get("role") or ""),
                org_roles=principal.org_roles,
                rbac_roles=principal.roles(),
            )
            if authorized:
                eligible_by_role_id[_row_role_id(candidate).casefold()] = candidate
        if not eligible_by_role_id:
            raise ApiError(
                ErrorCode.FORBIDDEN,
                "Principal is not authorized for any unmet approval requirement on this plan",
                details={"plan_id": plan_id},
            )
        if len(eligible_by_role_id) > 1:
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                "Multiple unmet approval requirements are eligible for this principal; role_id must be specified",
                details={
                    "plan_id": plan_id,
                    "eligible_role_ids": sorted(eligible_by_role_id),
                },
            )
        row = next(iter(eligible_by_role_id.values()))

    role_id = _row_role_id(row)
    authorized, admin_override = authorize_role_attestation(
        role_id=role_id,
        role_text=str(row.get("role") or ""),
        org_roles=principal.org_roles,
        rbac_roles=principal.roles(),
    )
    if not authorized:
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Principal is not authorized to attest this approval requirement's role",
            details={"plan_id": plan_id, "role_id": role_id},
        )
    return role_id, admin_override


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
    principal: ApprovePrincipal,
) -> dict[str, Any]:
    approve_scope = context.authorizer.effective_scope(principal, "approve", scope)
    planner = _require(context, "remediation_provider", "remediation", approve_scope)
    plans = planner.generate_plans()
    plan = planner.repository.get(plan_id)
    if plan is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation plan not found",
            details={"plan_id": plan_id},
        )
    scoped_plan = _filter_scoped(plan, approve_scope)
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
                _patching_service(context, approve_scope),
                scope=approve_scope,
                selected_patch_ids=request.selected_patch_ids or None,
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
        service = provider(approve_scope) if callable(provider) else None
        if service is None:
            raise ApiError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Defender configuration execution is not configured",
                {"capability": "defender_configuration"},
            )
        try:
            execution_snapshot = service.build_execution_snapshot(
                plan, scope=approve_scope
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

    # Server-derived, never client-supplied (Phase 03.5, D-01/D-02;
    # T-03.5-14; CR-01 fix). approver_roles is retained only as a legacy
    # read-compatibility projection (RemediationDecisionStore.append()'s
    # own docstring) -- ``requirement_satisfaction()`` no longer keys
    # satisfaction on it for a decision recorded through this route
    # (CR-05 fix: see ``approval_role_id`` below instead).
    approver_roles = sorted(
        {
            ROLE_APPROVER,
            *(
                grant.role
                for grant in principal.grants
                if grant.role in {ROLE_APPROVER, ROLE_ADMIN}
            ),
        }
    )
    approval_policy_version = ""
    generator = getattr(planner, "generator", None)
    engine = getattr(generator, "approvals", None)
    if engine is not None:
        approval_policy_version = str(getattr(engine, "policy_version", "") or "")

    # CR-05 fix: one decision attests exactly one required role. For an
    # approved decision on a plan that carries real ``approval_requirements``,
    # resolve exactly which row this decision satisfies -- explicitly, via
    # ``request.role_id``, when the caller selected one; automatically, when
    # at most one currently-unmet row is eligible for this principal to
    # attest; refused (400/403) when the selection is ambiguous or this
    # principal holds no literal claim/override for any unmet row. Never
    # applies to 'rejected'/'expired' decisions (WR-04 precedent: role
    # attestation is only ever meaningful on an approved decision).
    approval_role_id = ""
    admin_override = False
    if request.decision == "approved":
        current_snapshot_hash = (
            str(execution_snapshot.get("snapshot_hash") or "")
            if execution_snapshot is not None
            else ""
        )
        approval_role_id, admin_override = _resolve_approval_role_selection(
            plan_id=plan_id,
            requirements=plan.get("approval_requirements") or [],
            existing_decisions=planner.repository.decisions.list(plan_id),
            current_version=current_version,
            current_snapshot_hash=current_snapshot_hash,
            policy_version=approval_policy_version,
            requested_role_id=str(request.role_id or "").strip(),
            principal=principal,
        )

    decision = planner.repository.decisions.append(
        plan=plan,
        decision=request.decision,
        approver=principal.subject,
        reason=request.reason,
        scope=approve_scope.to_dict(),
        action_version=current_version,
        expires_at=expires_at,
        revalidation_checks=revalidation_checks,
        execution_snapshot=execution_snapshot,
        approver_roles=approver_roles,
        approval_policy_version=approval_policy_version,
        approval_role_id=approval_role_id,
        admin_override=admin_override,
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
        scope=approve_scope.to_dict(),
    )
