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

from intelligence.remediation.approval_decisions import (
    ExecutionSnapshotError,
    build_execution_snapshot,
)
from intelligence.remediation.execution_service import RemediationExecutionError
from operations.patching.adapters import PatchExecutionUnavailable
from operations.patching.service import PatchValidationError

from ..dependencies import Context, OperatePrincipal, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope
from .operations import _HIDDEN, _filter_rows, _filter_scoped, _require
from .patching import _service as _patching_service

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
    visible = [_plan_with_eligibility(context, row) for row in visible]
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
        _plan_with_eligibility(context, plan),
        evidence=_evidence(plan_id, str(plan.get("action_version") or "")),
        scope=scope.to_dict(),
    )


@router.get("/plans/{plan_id}/preview", summary="Preview a remediation plan's execution")
def preview_plan(plan_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    plan = _get_scoped_plan(context, scope, plan_id)
    action_id = str(plan.get("action_id") or plan.get("opportunity_type") or "")
    resource = plan.get("resource") or {}
    execution_snapshot = None
    if action_id == _CONTROLLED_PATCH_RECOVERY:
        try:
            execution_snapshot = build_execution_snapshot(
                plan, _patching_service(context, scope), scope=scope
            )
        except ExecutionSnapshotError as exc:
            raise ApiError(
                ErrorCode.CONFLICT,
                str(exc),
                {"reason": exc.reason, **exc.details},
            ) from exc
        operation = execution_snapshot["operation"]
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
        "execution_snapshot": execution_snapshot,
        **_plan_eligibility(context, plan),
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


def _optional_execution_service(context: Context) -> Any | None:
    provider = getattr(context, "execution_provider", None)
    return provider() if callable(provider) else None


def _plan_eligibility(context: Context, plan: dict[str, Any]) -> dict[str, Any]:
    service = _optional_execution_service(context)
    if service is None:
        return {"executable": False, "ineligibility_reason": "execution_unavailable"}
    return service.plan_eligibility(str(plan.get("plan_id") or ""))


def _plan_with_eligibility(context: Context, plan: dict[str, Any]) -> dict[str, Any]:
    return {**plan, **_plan_eligibility(context, plan)}


def _execution_or_404(service: Any, execution_id: str) -> dict[str, Any]:
    record = service.get_execution(execution_id)
    if record is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation execution not found",
            details={"execution_id": execution_id},
        )
    return record


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
    record = _execution_or_404(service, execution_id)
    _get_scoped_plan(context, scope, str(record.get("plan_id") or ""))
    if record.get("status") == "running":
        record = service.poll_verification(execution_id)
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
    records = service.list_executions(plan_id)
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
    record = _execution_or_404(service, execution_id)
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


@router.post(
    "/executions/{execution_id}/cancel",
    summary="Cancel queued remediation work when cancellation is provably safe",
)
def cancel_execution(
    execution_id: str, context: Context, principal: OperatePrincipal
) -> dict[str, Any]:
    service = _execution_service(context)
    record = _execution_or_404(service, execution_id)
    write_scope = context.authorizer.effective_scope(principal, "operate")
    _get_scoped_plan(context, write_scope, str(record.get("plan_id") or ""))
    try:
        result = service.cancel(
            execution_id,
            requested_by=getattr(principal, "subject", ""),
        )
    except RemediationExecutionError as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            str(exc),
            {"reason": exc.reason, **exc.details},
        ) from exc
    return envelope(
        result,
        evidence=_execution_evidence(execution_id),
        scope=write_scope.to_dict(),
    )
