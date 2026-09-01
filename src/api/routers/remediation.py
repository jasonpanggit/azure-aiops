"""Remediation plan read routes.

Fronts the existing :class:`intelligence.remediation.RemediationPlanner`
without duplicating any business logic. This router is additive: it mounts
under ``/api/v1/remediation/plans`` and never removes or renames the
pre-existing ``/remediation-plans``, ``/remediation-opportunities``,
``/remediation/defender-cases`` routes in :mod:`api.routers.operations`
that the web UI already calls.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from operations.patching.adapters import PatchExecutionUnavailable
from operations.patching.models import operation_for_kind
from operations.patching.service import PatchValidationError

from intelligence.remediation.execution_service import RemediationExecutionError

from ..dependencies import Context, OperatePrincipal, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope
from .operations import _HIDDEN, _filter_rows, _filter_scoped, _require

router = APIRouter(prefix="/api/v1/remediation", tags=["remediation"])

_CONTROLLED_PATCH_RECOVERY = "controlled-patch-recovery"


def _planner(context: Context, scope: Scope) -> Any:
    """Resolve the remediation planner exactly as ``operations.py`` does."""
    return _require(context, "remediation_provider", "remediation", scope)


def _get_scoped_plan(context: Context, scope: Scope, plan_id: str) -> dict[str, Any]:
    """Look up one plan, scope-filter it, and 404 rather than disclose it exists."""
    planner = _planner(context, scope)
    planner.generate_plans()  # Ensure plans are current, matching operations.py.
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
    return scoped_plan


def _evidence(plan_id: str, timestamp: str = "") -> Evidence:
    return Evidence(
        source_engine="intelligence.RemediationPlanner",
        source_table="remediation_plans",
        timestamp=timestamp,
        resource_id=plan_id,
        confidence=CONFIDENCE_MEDIUM,
    )


@router.get("/plans", summary="List remediation plans")
def list_plans(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    planner = _planner(context, scope)
    result = planner.generate_plans()
    visible = _filter_rows(result.get("plans"), scope)
    if not isinstance(visible, list):
        visible = []
    public = {**result, "plans": visible[page.offset : page.offset + page.limit]}
    if not scope.is_unrestricted():
        public = {
            "plans": public["plans"],
            "generated_at": result.get("generated_at", ""),
            "read_only": result.get("read_only", True),
            "execution_performed": result.get("execution_performed", False),
            "scope_limited": True,
        }
    return envelope(
        public,
        evidence=_evidence("", str(result.get("generated_at") or "")),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(visible)),
    )


@router.get("/plans/{plan_id}", summary="Get a remediation plan")
def get_plan(plan_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    plan = _get_scoped_plan(context, scope, plan_id)
    return envelope(
        plan,
        evidence=_evidence(plan_id, str(plan.get("action_version") or "")),
        scope=scope.to_dict(),
    )


@router.get("/plans/{plan_id}/preview", summary="Preview a remediation plan's execution")
def preview_plan(plan_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    plan = _get_scoped_plan(context, scope, plan_id)
    opportunity_type = str(plan.get("opportunity_type") or "")
    resource = plan.get("resource") or {}
    if opportunity_type == _CONTROLLED_PATCH_RECOVERY:
        inventory_kind = str(resource.get("entity_type") or "")
        operation = operation_for_kind(inventory_kind)
    else:
        operation = "not executable in this phase"
    rollback_plan = plan.get("rollback_plan") or {}
    risk_assessment = plan.get("risk_assessment") or {}
    preview = {
        "target": {
            "resource": resource,
            "resource_key": plan.get("resource_key", ""),
        },
        "operation": operation,
        "preconditions": rollback_plan.get("preconditions") or [],
        "expected_effect": {
            "business_impact": plan.get("business_impact"),
            "expected_secure_score_improvement": plan.get(
                "expected_secure_score_improvement"
            ),
        },
        "collateral_impact": {
            "risk_drivers": risk_assessment.get("overall_risk", {}).get(
                "drivers", []
            ),
            "dependencies": plan.get("dependencies"),
        },
    }
    return envelope(
        preview,
        evidence=_evidence(plan_id, str(plan.get("action_version") or "")),
        scope=scope.to_dict(),
    )


@router.get("/plans/{plan_id}/approvals", summary="Remediation plan approval requirements and decisions")
def plan_approvals(plan_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    plan = _get_scoped_plan(context, scope, plan_id)
    planner = _planner(context, scope)
    decisions = planner.repository.decisions.list(plan_id)
    return envelope(
        {
            "approval_requirements": plan.get("approval_requirements") or [],
            "decisions": decisions,
            "plan_id": plan_id,
        },
        evidence=_evidence(plan_id),
        scope=scope.to_dict(),
    )


@router.get("/plans/{plan_id}/business-decision", summary="Remediation plan business-decision context")
def plan_business_decision(
    plan_id: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    plan = _get_scoped_plan(context, scope, plan_id)
    return envelope(
        plan.get("business_decision") or {},
        evidence=_evidence(plan_id, str(plan.get("action_version") or "")),
        scope=scope.to_dict(),
    )


def _execution_service(context: Context) -> Any:
    service = getattr(context, "execution_provider", None)
    resolved = service() if callable(service) else None
    if resolved is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Remediation execution is not configured for this deployment",
            {"capability": "remediation_execution"},
        )
    return resolved


def _execution_evidence(execution_id: str) -> Evidence:
    return Evidence(
        source_engine="intelligence.RemediationExecutionService",
        source_table="remediation_executions",
        resource_id=execution_id,
        # A first-party execution record: HOG wrote it.
        confidence=CONFIDENCE_HIGH,
    )


@router.post(
    "/plans/{plan_id}/execute",
    status_code=202,
    summary="Execute an already-approved controlled-patch-recovery plan",
)
def execute_plan(
    plan_id: str, context: Context, principal: OperatePrincipal
) -> dict[str, Any]:
    # Narrow to what this principal may actually operate on before resolving
    # the plan, so an out-of-scope plan is indistinguishable from a
    # non-existent one -- matching create_patch_run's narrowing-before-
    # resolving pattern.
    write_scope = context.authorizer.effective_scope(principal, "operate")
    _get_scoped_plan(context, write_scope, plan_id)

    service = _execution_service(context)
    try:
        result = service.execute(plan_id, requested_by=getattr(principal, "subject", ""))
    except RemediationExecutionError as exc:
        raise ApiError(
            ErrorCode.CONFLICT, str(exc), {"reason": exc.reason, **exc.details}
        ) from exc
    except PatchValidationError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc), dict(exc.details)) from exc
    except PatchExecutionUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            str(exc),
            {"capability": getattr(exc, "capability", "patch_execution")},
        ) from exc

    return envelope(
        result,
        evidence=_execution_evidence(str(result.get("execution_id") or "")),
        scope=write_scope.to_dict(),
    )


@router.get("/executions/{execution_id}", summary="Poll a remediation plan execution")
def get_execution(execution_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    service = _execution_service(context)
    store = getattr(service, "_store", None)
    record = store.get(execution_id) if store is not None else None
    if record is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation execution not found",
            details={"execution_id": execution_id},
        )
    return envelope(
        record,
        evidence=_execution_evidence(execution_id),
        scope=scope.to_dict(),
    )


@router.get(
    "/plans/{plan_id}/executions", summary="List execution attempts for a remediation plan"
)
def list_plan_executions(
    plan_id: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    _get_scoped_plan(context, scope, plan_id)
    service = _execution_service(context)
    store = getattr(service, "_store", None)
    records = store.list_for_plan(plan_id) if store is not None else []
    return envelope(
        {"plan_id": plan_id, "executions": records},
        evidence=_execution_evidence(plan_id),
        scope=scope.to_dict(),
    )


@router.post(
    "/executions/{execution_id}/retry",
    status_code=202,
    summary="Retry a failed remediation execution (bounded, idempotent, revalidated)",
)
def retry_execution(
    execution_id: str, context: Context, principal: OperatePrincipal
) -> dict[str, Any]:
    service = _execution_service(context)
    store = getattr(service, "_store", None)
    record = store.get(execution_id) if store is not None else None
    if record is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation execution not found",
            details={"execution_id": execution_id},
        )
    # Narrow to what this principal may actually operate on before
    # resolving/retrying, matching execute_plan's narrowing-before-
    # resolving pattern.
    write_scope = context.authorizer.effective_scope(principal, "operate")
    _get_scoped_plan(context, write_scope, str(record.get("plan_id") or ""))

    try:
        result = service.retry(execution_id)
    except RemediationExecutionError as exc:
        raise ApiError(
            ErrorCode.CONFLICT, str(exc), {"reason": exc.reason, **exc.details}
        ) from exc
    except PatchValidationError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc), dict(exc.details)) from exc
    except PatchExecutionUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            str(exc),
            {"capability": getattr(exc, "capability", "patch_execution")},
        ) from exc

    return envelope(
        result,
        evidence=_execution_evidence(execution_id),
        scope=write_scope.to_dict(),
    )

