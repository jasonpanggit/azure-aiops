"""Remediation plan read routes.

Fronts the existing :class:`intelligence.remediation.RemediationPlanner`
without duplicating any business logic. This router is additive: it mounts
under ``/api/v1/remediation/plans`` and never removes or renames the
pre-existing ``/remediation-plans``, ``/remediation-opportunities``,
``/remediation/defender-cases`` routes in :mod:`api.routers.operations`
that the web UI already calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query

from intelligence.governance.audit import (
    ExposureAuditUnavailable,
    append_exposure_audit,
    new_exposure_audit_event,
)
from intelligence.remediation.action_catalog import (
    PATCH_RECOVERY_ACTION_FAMILY,
    governed_action,
)
from intelligence.remediation.approval_decisions import (
    ExecutionSnapshotError,
    build_execution_snapshot,
)
from intelligence.remediation.approval_gate import (
    latest_decision_status,
    policy_version_for,
    requirement_satisfaction,
)
from intelligence.remediation.execution_service import RemediationExecutionError
from intelligence.remediation.execution_store import execution_scope_attributes
from intelligence.vulnerability.exposure_contracts import (
    EXPOSURE_CONTRACT_VERSION,
)
from operations.defender_configuration import DEFENDER_CONFIGURATION_ACTION_IDS
from operations.patching.adapters import PatchExecutionUnavailable
from operations.patching.service import PatchValidationError

from ..dependencies import (
    Context,
    CurrentPrincipal,
    OperatePrincipal,
    Page,
    ReadScope,
    WritePrincipal,
)
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..models import ExposureReviewHandoffRequest, SupersedeExecutionRequest
from ..scope import Scope, scope_attributes
from .operations import _HIDDEN, _filter_rows, _filter_scoped, _require
from .patching import _service as _patching_service

router = APIRouter(prefix="/api/v1/remediation", tags=["remediation"])


def _plan_resource_key(row: dict[str, Any]) -> str:
    resource = row.get("resource") if isinstance(row.get("resource"), dict) else {}
    return str(
        row.get("resource_key")
        or resource.get("resource_key")
        or resource.get("id")
        or ""
    ).strip()


def _planner(context: Context, scope: Scope) -> Any:
    """Resolve the remediation planner exactly as ``operations.py`` does."""
    return _require(context, "remediation_provider", "remediation", scope)


def _policy_version_for(planner: Any) -> str:
    """Read this plan's originating ApprovalEngine.policy_version, if reachable.

    Thin re-export of the shared ``approval_gate.policy_version_for`` (Phase
    03.5 WR-02 fix): both this route layer and the execution gate
    (``execution_service.py::_check_approval_gate``, wired via
    ``runtime.py::_execution_service_for_scope``) now consult the identical
    definition, so neither can independently drift. For planners exposing
    no single reachable engine (e.g. ``LiveRemediationPlanner``'s two
    per-family engines), this is a documented interim "" default
    (Phase 03.5-05/06), never an error.
    """
    return policy_version_for(planner)


def _can_act(
    context: Context,
    scope: Scope,
    principal: Any,
    action: str,
    plan: dict[str, Any],
) -> tuple[bool, str]:
    """Server-authoritative, scope-aware ``can_approve``/``can_operate`` (WR-01 fix).

    ``Authorizer.require`` alone only checks the principal holds ``action``
    *somewhere* -- it takes no scope parameter and cannot know whether
    *this specific plan* falls inside any of the qualifying grants' scopes.
    A principal holding an approver/operator grant scoped to one
    subscription, plus an unrestricted reader grant, would see
    ``can_approve``/``can_operate: true`` for a plan in a subscription
    their write grant does not reach, then get a confusing 404 on submit.

    Mirrors the narrowing ``record_remediation_decision``/``execute_plan``
    themselves perform via ``effective_scope(principal, action, scope)``,
    then checks the plan's own scope attributes fall within the narrowed
    result -- the exact same "attributes present but non-matching hides it"
    rule ``_filter_scoped`` already applies for read visibility, applied
    here for the write action instead.
    """
    try:
        narrowed = context.authorizer.effective_scope(principal, action, scope)
    except ApiError as exc:
        return False, str(exc.message)
    attributes = scope_attributes(plan)
    if attributes and not narrowed.matches(attributes):
        return False, (
            f"Principal {principal.subject!r} is not permitted the requested scope"
        )
    return True, ""


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


def _authorize_execution_scope(scope: Scope, record: dict[str, Any]) -> None:
    """404 an execution whose own scope attributes fall outside ``scope``.

    Authorizes off the execution record's own immutable scope attributes
    (D-02), never off the continued existence/scope of its originating plan,
    so a plan regenerating (or disappearing) after evidence changes cannot
    make an execution unreachable to a caller who was always in scope.
    Deliberately calls ``Scope.matches`` directly rather than
    ``_filter_scoped``'s permissive on-empty-attributes short-circuit: an
    unrestricted scope already matches unconditionally, so a restricted
    scope with empty/legacy scope attributes fails closed instead of
    defaulting to visible.
    """
    if not scope.matches(execution_scope_attributes(record)):
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Remediation execution not found",
            details={"execution_id": record.get("execution_id", "")},
        )


def _evidence(plan_id: str, timestamp: str = "") -> Evidence:
    return Evidence(
        source_engine="intelligence.RemediationPlanner",
        source_table="remediation_plans",
        timestamp=timestamp,
        resource_id=plan_id,
        confidence=CONFIDENCE_MEDIUM,
    )


@router.get("/plans", summary="List remediation plans")
def list_plans(
    context: Context, scope: ReadScope, page: Page, resource_key: str = ""
) -> dict[str, Any]:
    planner = _planner(context, scope)
    result = planner.generate_plans()
    visible = _filter_rows(result.get("plans"), scope)
    if not isinstance(visible, list):
        visible = []
    if resource_key:
        canonical = resource_key.strip().casefold()
        visible = [
            row
            for row in visible
            if _plan_resource_key(row).casefold() == canonical
        ]
    visible = [_plan_with_eligibility(context, scope, row) for row in visible]
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


@router.get(
    "/exposure-handoffs",
    summary="List governed Exposure review handoffs and no-safe-action results",
)
def exposure_handoffs(
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    provider = getattr(context, "exposure_remediation_provider", None)
    correlator = provider() if callable(provider) else None
    if correlator is None or not hasattr(correlator, "exposure_cases"):
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Exposure remediation review is unavailable",
            {"capability": "exposure_remediation"},
        )
    cases = correlator.exposure_cases(scope)
    warnings = sorted(
        {
            str(case.get("outcome_reason") or "")
            for case in cases
            if case.get("outcome") == "no_safe_action"
            and case.get("outcome_reason")
        }
    )
    return envelope(
        {
            "contract_version": EXPOSURE_CONTRACT_VERSION,
            "cases": cases,
            "read_only": True,
            "execution_transition": False,
        },
        evidence=Evidence(
            source_engine="intelligence.DefenderRemediationCorrelator",
            source_table="gold_exposure_findings",
            timestamp=str(
                next(
                    (
                        case.get("freshness", {}).get("as_of")
                        for case in cases
                        if case.get("freshness", {}).get("as_of")
                    ),
                    "",
                )
            ),
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
        knowledge_version=str(
            next(
                (
                    case.get("read_model_generation_id")
                    for case in cases
                    if case.get("read_model_generation_id")
                ),
                "",
            )
        ),
        warnings=warnings,
    )


@router.post(
    "/exposure-handoffs",
    status_code=201,
    summary="Create an audited non-executable Exposure review handoff",
)
def create_exposure_handoff(
    payload: ExposureReviewHandoffRequest,
    context: Context,
    principal: WritePrincipal,
) -> dict[str, Any]:
    write_scope = context.authorizer.effective_scope(principal, "write")
    provider = getattr(context, "exposure_remediation_provider", None)
    correlator = provider() if callable(provider) else None
    if correlator is None or not hasattr(correlator, "exposure_cases"):
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Exposure remediation review is unavailable",
            {"capability": "exposure_remediation"},
        )
    case = next(
        (
            row
            for row in correlator.exposure_cases(write_scope)
            if str(row.get("exposure_id") or "") == payload.exposure_id
        ),
        None,
    )
    if case is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Exposure finding not found",
            {"exposure_id": payload.exposure_id},
        )
    if (
        case.get("target_kind") != "container_image"
        or case.get("outcome") != "review_handoff"
        or case.get("direct_execution_supported") is not False
    ):
        raise ApiError(
            ErrorCode.CONFLICT,
            "Exposure finding is not eligible for a governed review handoff",
            {
                "exposure_id": payload.exposure_id,
                "reason": str(
                    case.get("outcome_reason_code") or "no_safe_action"
                ),
            },
        )
    risk_exception_id = payload.risk_exception_id.strip()
    if not payload.risk_acknowledged and not risk_exception_id:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Exposure review handoff requires risk acknowledgement or an active risk exception",
            {"exposure_id": payload.exposure_id},
        )
    if risk_exception_id:
        lister = getattr(context, "risk_exception_list", None)
        exception = next(
            (
                item
                for item in (lister() if callable(lister) else ())
                if str(getattr(item, "exception_id", "") or "")
                == risk_exception_id
            ),
            None,
        )
        if (
            exception is None
            or exception.is_expired(now_iso=datetime.now(UTC).isoformat())
            or str(getattr(exception, "cve_id", "") or "").casefold()
            != str(case.get("weakness_key") or "").casefold()
        ):
            raise ApiError(
                ErrorCode.CONFLICT,
                "Risk exception does not authorize this Exposure handoff",
                {
                    "exposure_id": payload.exposure_id,
                    "reason": "risk_exception_invalid",
                },
            )
    created_at = datetime.now(UTC).isoformat()
    evidence_refs = [
        dict(reference)
        for reference in case.get("evidence_refs") or ()
    ]
    if risk_exception_id:
        evidence_refs.append(
            {
                "risk_exception_id": risk_exception_id,
                "weakness_id": str(case.get("weakness_key") or ""),
            }
        )
    try:
        append_exposure_audit(
            context,
            new_exposure_audit_event(
                event_type="exposure.review_handoff_created",
                subject=str(getattr(principal, "subject", "") or ""),
                tenant_id=str(case.get("tenant_id") or ""),
                connection_ids=case.get("connection_ids") or (),
                scope=write_scope.to_dict(),
                target={
                    "target_kind": "container_image",
                    "target_id": str(case.get("resource_key") or ""),
                    "weakness_id": str(case.get("weakness_key") or ""),
                    "exposure_id": str(case.get("exposure_id") or ""),
                },
                generation=str(
                    case.get("read_model_generation_id") or ""
                ),
                evidence_refs=evidence_refs,
                decision="create_review_handoff",
                reason=payload.reason,
                result="recorded",
                timestamp=created_at,
            ),
        )
    except ExposureAuditUnavailable as exc:
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "Exposure audit is unavailable; review handoff was not created",
            {"capability": "exposure_audit"},
        ) from exc
    result = {
        **case,
        "handoff_reason": payload.reason,
        "created_by": str(getattr(principal, "subject", "") or ""),
        "created_at": created_at,
        "risk_acknowledged": bool(payload.risk_acknowledged),
        "risk_exception_id": risk_exception_id,
        "execution_transition": False,
    }
    return envelope(
        result,
        evidence=Evidence(
            source_engine="intelligence.ExposureAudit",
            source_table="exposure_review_handoffs",
            timestamp=created_at,
            resource_id=str(case.get("exposure_id") or ""),
            confidence=CONFIDENCE_HIGH,
        ),
        scope=write_scope.to_dict(),
        knowledge_version=str(
            case.get("read_model_generation_id") or ""
        ),
    )


@router.get("/plans/{plan_id}", summary="Get a remediation plan")
def get_plan(plan_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    plan = _get_scoped_plan(context, scope, plan_id)
    return envelope(
        _plan_with_eligibility(context, scope, plan),
        evidence=_evidence(plan_id, str(plan.get("action_version") or "")),
        scope=scope.to_dict(),
    )


@router.get("/plans/{plan_id}/preview", summary="Preview a remediation plan's execution")
def preview_plan(
    plan_id: str,
    context: Context,
    scope: ReadScope,
    patch_id: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    plan = _get_scoped_plan(context, scope, plan_id)
    action_id = str(plan.get("action_id") or plan.get("opportunity_type") or "")
    resource = plan.get("resource") or {}
    execution_snapshot = None
    if action_id == PATCH_RECOVERY_ACTION_FAMILY:
        try:
            execution_snapshot = build_execution_snapshot(
                plan,
                _patching_service(context, scope),
                scope=scope,
                selected_patch_ids=patch_id or None,
            )
        except ExecutionSnapshotError as exc:
            raise ApiError(
                ErrorCode.CONFLICT,
                str(exc),
                {"reason": exc.reason, **exc.details},
            ) from exc
        operation = execution_snapshot["operation"]
    elif action_id in DEFENDER_CONFIGURATION_ACTION_IDS:
        try:
            execution_snapshot = _execution_service(
                context, scope
            ).build_execution_snapshot(plan, scope=scope)
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
        **_plan_eligibility(context, scope, plan),
    }
    return envelope(
        preview,
        evidence=_evidence(plan_id, str(plan.get("action_version") or "")),
        scope=scope.to_dict(),
    )


@router.get("/plans/{plan_id}/approvals", summary="Remediation plan approval requirements and decisions")
def plan_approvals(
    plan_id: str, context: Context, scope: ReadScope, patch_id: Annotated[list[str] | None, Query()] = None
) -> dict[str, Any]:
    plan = _get_scoped_plan(context, scope, plan_id)
    planner = _planner(context, scope)
    decisions = planner.repository.decisions.list(plan_id)
    current_snapshot_hash = ""
    try:
        preview = preview_plan(plan_id, context, scope, patch_id)["data"]
        snapshot = preview.get("execution_snapshot") if preview else None
        if isinstance(snapshot, dict):
            current_snapshot_hash = str(snapshot.get("snapshot_hash") or "")
    except ApiError:
        current_snapshot_hash = ""
    requirements = requirement_satisfaction(
        plan.get("approval_requirements") or [],
        decisions,
        current_action_version=str(plan.get("action_version") or ""),
        current_snapshot_hash=current_snapshot_hash,
        policy_version=_policy_version_for(planner),
        now=datetime.now(UTC),
    )
    return envelope(
        {
            "approval_requirements": requirements,
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


# Phase 03.6 UI-SPEC "Blocker Vocabulary" table: maps every code to the
# step it affects at run-time arrival. `already_succeeded` is deliberately
# excluded (see "Excluded from Blockers"). Dual-sourced codes
# (`action_not_executable`, `target_not_found`, `patch_execution_unavailable`,
# `configuration_execution_unavailable`) map to their run-time step here;
# their review-time (`preview_error`) arrival always forces `step="review"`
# regardless of this table, per the synthesis rule.
BLOCKER_STEP_BY_CODE: dict[str, str] = {
    "plan_repository_unavailable": "review",
    "execution_unavailable": "review",
    "plan_not_found": "select",
    "disposition_not_executable": "review",
    "unsupported_configuration_action": "review",
    "configuration_target_not_supported": "review",
    "business_impact_unknown": "review",
    "review_required": "review",
    "decision_unknowns_present": "review",
    "decision_evidence_missing": "review",
    "plan_evidence_missing": "review",
    "no_patches_available": "review",
    "patch_ids_not_available": "review",
    "no_patches_selected": "review",
    "action_not_executable": "approve",
    "not_approved": "approve",
    "stale_approval": "approve",
    "approval_expired": "approve",
    "approval_requirements_unmet": "approve",
    "self_approval_not_permitted": "approve",
    "execution_snapshot_missing": "approve",
    "execution_snapshot_invalid": "approve",
    "execution_snapshot_changed": "run",
    "execution_snapshot_drift": "run",
    "store_not_configured": "run",
    "patch_execution_unavailable": "run",
    "defender_configuration_unavailable": "run",
    "configuration_execution_unavailable": "run",
    "azure_arm_token_unavailable": "run",
    "scope_not_authorized": "run",
    "target_not_found": "run",
    "execution_not_found": "verify",
    "execution_not_retryable": "verify",
    "submission_ambiguous": "verify",
    "verification_timed_out": "verify",
    "provider_not_cancellable": "verify",
    "max_attempts_exceeded": "verify",
    "execution_not_cancellable": "verify",
    "supersede_reason_required": "verify",
    "execution_active": "verify",
    "already_superseded": "verify",
}


def _collect_blockers(
    *,
    preview_error: str,
    plan_ineligibility_reason: str,
    action_executable: bool,
    latest_execution: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Assemble ``workflow.blockers[]`` -- code+step only; the client
    (Plan 03.6-04) supplies locked message/next_action from the vocabulary
    table when the server omits them."""
    rows: list[dict[str, str]] = []
    if preview_error:
        # Synthesis rule: forced to "review" regardless of the vocabulary
        # table's own step column for this code.
        rows.append({"code": preview_error, "step": "review"})
    if plan_ineligibility_reason:
        rows.append(
            {
                "code": plan_ineligibility_reason,
                "step": BLOCKER_STEP_BY_CODE.get(plan_ineligibility_reason, "review"),
            }
        )
    if not action_executable:
        rows.append({"code": "action_not_executable", "step": "approve"})
    if latest_execution is not None:
        execution_reason = str(latest_execution.get("ineligibility_reason") or "")
        if execution_reason and execution_reason != "already_succeeded":
            rows.append(
                {
                    "code": execution_reason,
                    "step": BLOCKER_STEP_BY_CODE.get(execution_reason, "verify"),
                }
            )
        if latest_execution.get("failure_class") == "verification_timed_out":
            rows.append({"code": "verification_timed_out", "step": "verify"})
    # Deduplicate by the exact (code, step) pair -- a plan-level and
    # preview-time occurrence of the identical code at the identical step
    # must not double-render.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        key = (row["code"], row["step"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _collect_degradation(context: Context, plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble ``workflow.degradation[]`` from business-decision source
    family status and (when available) provider runtime health -- never
    allowed to raise; degradation is diagnostic only."""
    degradation: list[dict[str, Any]] = []
    source_family_status = (
        plan.get("business_decision", {}).get("source_family_status", {})
        if isinstance(plan.get("business_decision"), dict)
        else {}
    )
    if isinstance(source_family_status, dict):
        for source_type, status in source_family_status.items():
            if not isinstance(status, dict):
                continue
            availability = str(status.get("availability") or "unknown")
            if availability == "available":
                continue
            normalized = (
                availability
                if availability in {"degraded", "unavailable", "partial"}
                else "degraded"
            )
            degradation.append(
                {
                    "source": f"{source_type} evidence",
                    "availability": normalized,
                    "reason": f"{source_type} evidence is {availability}.",
                    "freshness": str(status.get("freshness") or ""),
                }
            )
    provider_runtime = getattr(context, "provider_runtime", None)
    if provider_runtime is not None:
        try:
            health = provider_runtime.health(refresh=False)
        except Exception:  # noqa: BLE001 - degradation collection is diagnostic-only, must never crash the read path
            health = None
        if isinstance(health, dict):
            vulnerability_provider = health.get("providers", {}).get("vulnerability")
            if isinstance(vulnerability_provider, dict):
                state = str(vulnerability_provider.get("state") or "")
                if state in {"degraded", "unavailable", "partial"}:
                    degradation.append(
                        {
                            "source": "Vulnerability evidence (AUM/Defender)",
                            "availability": state,
                            "reason": str(
                                vulnerability_provider.get("degraded_reason")
                                or "Vulnerability evidence is currently degraded."
                            ),
                            "freshness": str(
                                vulnerability_provider.get("freshness") or ""
                            ),
                        }
                    )
    return degradation


@router.get(
    "/plans/{plan_id}/workflow",
    summary="Get the governed Select, Review, Approve, Run, Verify workflow",
)
def plan_workflow(
    plan_id: str,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
    patch_id: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    """Project the complete scoped workflow without introducing a mutation path."""
    plan = _get_scoped_plan(context, scope, plan_id)
    planner = _planner(context, scope)
    action_id = str(plan.get("action_id") or plan.get("opportunity_type") or "")
    action = governed_action(action_id)
    preview_error = ""
    try:
        preview = preview_plan(plan_id, context, scope, patch_id)["data"]
    except ApiError as exc:
        preview = None
        preview_error = str(
            (exc.details or {}).get("reason") or exc.code
        )
    decisions = planner.repository.decisions.list(plan_id)
    latest_decision = (
        max(decisions, key=lambda row: str(row.get("decided_at") or ""))
        if decisions
        else None
    )
    service = _optional_execution_service(context, scope)
    executions = service.list_executions(plan_id) if service is not None else []
    latest_execution = executions[-1] if executions else None
    if (
        service is not None
        and latest_execution is not None
        and latest_execution.get("status") == "running"
    ):
        latest_execution = service.poll_verification(
            str(latest_execution.get("execution_id") or "")
        )
        executions = [
            latest_execution
            if row.get("execution_id") == latest_execution.get("execution_id")
            else row
            for row in executions
        ]
    snapshot = preview.get("execution_snapshot") if preview else None
    current_snapshot_hash = (
        str(snapshot.get("snapshot_hash") or "") if isinstance(snapshot, dict) else ""
    )
    plan_with_eligibility = _plan_with_eligibility(context, scope, plan)
    policy_version = _policy_version_for(planner)
    latest_status = latest_decision_status(
        decisions,
        current_action_version=str(plan.get("action_version") or ""),
        current_snapshot_hash=current_snapshot_hash,
        policy_version=policy_version,
        now=datetime.now(UTC),
    )
    requirements = requirement_satisfaction(
        plan.get("approval_requirements") or [],
        decisions,
        current_action_version=str(plan.get("action_version") or ""),
        current_snapshot_hash=current_snapshot_hash,
        policy_version=policy_version,
        now=datetime.now(UTC),
    )
    # CR-04 fix: the plan's single overall-latest decision being fresh is
    # necessary but not sufficient -- a multi-role plan can have a fresh
    # latest decision for ONE role while other required rows remain
    # entirely unmet. Requiring every row satisfied here is what keeps this
    # projection truthful against `_check_approval_gate`'s own
    # `approval_requirements_unmet` refusal, so the UI can never show
    # "Approved"/an enabled Run button for a plan the server will
    # unconditionally 409 the moment the operator clicks through.
    approval_current = latest_status["status"] == "current" and all(
        row.get("satisfied") for row in requirements
    )
    can_approve, approve_ineligible_reason = _can_act(context, scope, principal, "approve", plan)
    can_operate, operate_ineligible_reason = _can_act(context, scope, principal, "operate", plan)
    latest_execution_status = str((latest_execution or {}).get("status") or "")
    latest_reconciliation_status = str(
        (latest_execution or {}).get("evidence_reconciliation", {}).get("status") or ""
    )
    verify_blocked = latest_execution is not None and (
        latest_execution_status in {"failed", "cancelled"}
        or (
            latest_execution_status == "succeeded"
            and latest_reconciliation_status in {"reconciled_incomplete", "unreconciled"}
        )
        or (
            latest_execution.get("remaining_attempts") == 0
            and latest_execution_status != "succeeded"
        )
    )
    verify_complete = latest_execution is not None and (
        latest_execution_status == "succeeded"
        and latest_reconciliation_status in {"", "reconciled_clean"}
    )
    if not action.executable:
        recommended_step = "manual_review"
    elif preview is None:
        recommended_step = "review"
    elif latest_execution is not None:
        recommended_step = "verify"
    elif approval_current:
        recommended_step = "run"
    else:
        recommended_step = "approve"
    steps = [
        {"id": "select", "label": "Select fix", "status": "complete"},
        {
            "id": "review",
            "label": "Review impact",
            "status": "complete" if preview is not None else "blocked",
        },
        {
            "id": "approve",
            "label": "Approve",
            "status": (
                "blocked"
                if not action.executable
                else "blocked"
                if preview is None
                else "complete"
                if approval_current
                else "current"
            ),
        },
        {
            "id": "run",
            "label": "Run",
            "status": (
                "blocked"
                if not action.executable
                else "complete"
                if latest_execution is not None
                else "current"
                if approval_current
                else "pending"
            ),
        },
        {
            "id": "verify",
            "label": "Verify",
            "status": (
                "blocked"
                if not action.executable
                else "blocked"
                if verify_blocked
                else "complete"
                if verify_complete
                else "current"
                if latest_execution is not None
                else "pending"
            ),
        },
    ]
    blockers = _collect_blockers(
        preview_error=preview_error,
        plan_ineligibility_reason=str(plan_with_eligibility.get("ineligibility_reason") or ""),
        action_executable=action.executable,
        latest_execution=latest_execution,
    )
    degradation = _collect_degradation(context, plan)
    return envelope(
        {
            "plan": plan_with_eligibility,
            "action": {
                "action_id": action.action_id,
                "family": action.family,
                "executable": action.executable,
                "manual_review_reason": action.manual_review_reason,
                "can_operate": can_operate,
                **(
                    {"operate_ineligible_reason": operate_ineligible_reason}
                    if not can_operate
                    else {}
                ),
            },
            "preview": preview,
            "preview_error": preview_error,
            "business_decision": plan.get("business_decision") or {},
            "approval": {
                "requirements": requirements,
                "decisions": decisions,
                "latest": latest_decision,
                "current": approval_current,
                "status": latest_status["status"],
                "stale_reasons": latest_status["stale_reasons"],
                "can_approve": can_approve,
                "allow_self_approval": bool(
                    service.allow_self_approval()
                ) if service is not None else False,
                **(
                    {"approve_ineligible_reason": approve_ineligible_reason}
                    if not can_approve
                    else {}
                ),
            },
            "execution": latest_execution,
            "executions": executions,
            "steps": steps,
            "recommended_step": recommended_step,
            "blockers": blockers,
            "degradation": degradation,
            "evidence": plan.get("evidence_citations") or [],
            "audit": {
                "decisions": decisions,
                "executions": executions,
            },
        },
        evidence=_evidence(plan_id, str(plan.get("action_version") or "")),
        scope=scope.to_dict(),
    )


def _execution_service(context: Context, scope: Scope) -> Any:
    service = getattr(context, "execution_provider", None)
    resolved = service(scope) if callable(service) else None
    if resolved is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Remediation execution is not configured for this deployment",
            {"capability": "remediation_execution"},
        )
    return resolved


def _optional_execution_service(context: Context, scope: Scope) -> Any | None:
    provider = getattr(context, "execution_provider", None)
    return provider(scope) if callable(provider) else None


def _plan_eligibility(context: Context, scope: Scope, plan: dict[str, Any]) -> dict[str, Any]:
    service = _optional_execution_service(context, scope)
    if service is None:
        return {"executable": False, "ineligibility_reason": "execution_unavailable"}
    return service.plan_eligibility(str(plan.get("plan_id") or ""))


def _plan_with_eligibility(context: Context, scope: Scope, plan: dict[str, Any]) -> dict[str, Any]:
    return {**plan, **_plan_eligibility(context, scope, plan)}


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


def _audit_execution_request(
    *,
    context: Context,
    principal: Any,
    scope: Scope,
    event_type: str,
    decision: str,
    record: dict[str, Any],
    reason: str,
) -> None:
    snapshot = (
        record.get("execution_snapshot")
        if isinstance(record.get("execution_snapshot"), dict)
        else {}
    )
    target_id = str(
        snapshot.get("target_id")
        or record.get("resource_key")
        or record.get("target_id")
        or ""
    )
    generation = str(
        record.get("read_model_generation_id")
        or snapshot.get("read_model_generation_id")
        or snapshot.get("generation")
        or ""
    )
    evidence_refs = (
        {
            "plan_id": str(record.get("plan_id") or ""),
            "action_version": str(
                record.get("action_version")
                or snapshot.get("action_version")
                or ""
            ),
            "snapshot_hash": str(
                record.get("snapshot_hash")
                or snapshot.get("snapshot_hash")
                or ""
            ),
        },
    )
    try:
        append_exposure_audit(
            context,
            new_exposure_audit_event(
                event_type=event_type,
                subject=str(getattr(principal, "subject", "") or ""),
                tenant_id=str(record.get("tenant_id") or ""),
                connection_ids=scope.values("subscription_connection"),
                scope=scope.to_dict(),
                target={
                    "target_kind": str(
                        record.get("target_kind") or "server"
                    ),
                    "target_id": target_id,
                    "action_id": str(
                        record.get("action_id")
                        or record.get("opportunity_type")
                        or ""
                    ),
                },
                generation=generation,
                evidence_refs=evidence_refs,
                decision=decision,
                reason=reason,
                result="requested",
            ),
        )
    except ExposureAuditUnavailable as exc:
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "Exposure audit is unavailable; remediation request was not accepted",
            {"capability": "exposure_audit"},
        ) from exc


@router.post(
    "/plans/{plan_id}/execute",
    status_code=202,
    summary="Execute an already-approved bounded remediation plan",
)
def execute_plan(
    plan_id: str, context: Context, principal: OperatePrincipal
) -> dict[str, Any]:
    # Narrow to what this principal may actually operate on before resolving
    # the plan, so an out-of-scope plan is indistinguishable from a
    # non-existent one -- matching create_patch_run's narrowing-before-
    # resolving pattern.
    write_scope = context.authorizer.effective_scope(principal, "operate")
    plan = _get_scoped_plan(context, write_scope, plan_id)

    service = _execution_service(context, write_scope)
    _audit_execution_request(
        context=context,
        principal=principal,
        scope=write_scope,
        event_type="remediation.execution_requested",
        decision="execute",
        record=plan,
        reason="approved remediation execution requested",
    )
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


@router.get(
    "/diagnostics/executions",
    summary="Report orphaned/legacy remediation executions",
)
def execution_diagnostics(context: Context, principal: OperatePrincipal) -> dict[str, Any]:
    # Narrow like every other route in this file before touching data
    # (CR-01): ``orphaned_executions()`` only ever returns records whose
    # ``execution_scope_attributes()`` is empty by definition, so
    # ``write_scope.matches(...)`` on those attributes always fails for any
    # restricted (non-unrestricted) caller -- the same fail-closed rule
    # ``_authorize_execution_scope`` already applies to a single legacy
    # execution. A restricted operator therefore sees no orphaned records;
    # only an unrestricted (system-wide) caller can see this diagnostic data.
    write_scope = context.authorizer.effective_scope(principal, "operate")
    service = _execution_service(context, Scope.unrestricted())
    orphans = service.orphaned_executions() if write_scope.is_unrestricted() else []
    return envelope(
        {"orphaned_executions": orphans},
        evidence=_execution_evidence("diagnostics"),
        scope=write_scope.to_dict(),
    )


@router.get("/executions/{execution_id}", summary="Poll a remediation plan execution")
def get_execution(execution_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    # poll_verification never touches self._plans/self._patching, so resolving
    # the execution service unrestricted is safe here (mirrors the existing
    # retry_execution/cancel_execution pattern below); authorization is done
    # separately from the execution record's own scope attributes, not by
    # requiring the originating plan to still exist (D-02).
    service = _execution_service(context, Scope.unrestricted())
    record = _execution_or_404(service, execution_id)
    _authorize_execution_scope(scope, record)
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
    service = _execution_service(context, scope)
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
    service = _execution_service(context, Scope.unrestricted())
    record = _execution_or_404(service, execution_id)
    # Narrow to what this principal may actually operate on before
    # resolving/retrying, matching execute_plan's narrowing-before-
    # resolving pattern.
    write_scope = context.authorizer.effective_scope(principal, "operate")
    _authorize_execution_scope(write_scope, record)
    service = _execution_service(context, write_scope)
    _audit_execution_request(
        context=context,
        principal=principal,
        scope=write_scope,
        event_type="remediation.execution_retry_requested",
        decision="retry",
        record=record,
        reason="bounded retry requested",
    )

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
    "/executions/{execution_id}/supersede",
    status_code=202,
    summary="Supersede an exhausted (but non-ambiguous) remediation execution",
)
def supersede_execution(
    execution_id: str,
    payload: SupersedeExecutionRequest,
    context: Context,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    service = _execution_service(context, Scope.unrestricted())
    record = _execution_or_404(service, execution_id)
    # Narrow to what this principal may actually operate on before
    # resolving/superseding, matching retry_execution's narrowing-before-
    # resolving pattern.
    write_scope = context.authorizer.effective_scope(principal, "operate")
    _authorize_execution_scope(write_scope, record)
    service = _execution_service(context, write_scope)
    _audit_execution_request(
        context=context,
        principal=principal,
        scope=write_scope,
        event_type="remediation.execution_supersede_requested",
        decision="supersede",
        record=record,
        reason=payload.reason,
    )

    try:
        result = service.supersede(
            execution_id,
            requested_by=getattr(principal, "subject", ""),
            reason=payload.reason,
        )
    except RemediationExecutionError as exc:
        if exc.reason == "execution_not_found":
            code = ErrorCode.NOT_FOUND
        elif exc.reason == "supersede_reason_required":
            code = ErrorCode.INVALID_REQUEST
        else:
            code = ErrorCode.CONFLICT
        raise ApiError(
            code, str(exc), {"reason": exc.reason, **exc.details}
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
    service = _execution_service(context, Scope.unrestricted())
    record = _execution_or_404(service, execution_id)
    write_scope = context.authorizer.effective_scope(principal, "operate")
    _authorize_execution_scope(write_scope, record)
    service = _execution_service(context, write_scope)
    _audit_execution_request(
        context=context,
        principal=principal,
        scope=write_scope,
        event_type="remediation.execution_cancel_requested",
        decision="cancel",
        record=record,
        reason="bounded cancellation requested",
    )
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
