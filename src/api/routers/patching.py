"""Patch inventory and operator-triggered patch runs.

Reads answer "what can be patched, and with what?"; the single write path
answers "install exactly this, on exactly this host, approved by this person".
Both enforcement points from :mod:`api.rbac` apply: the action gate plus scope
narrowing, so an operator can never trigger a run against a host outside their
grants.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..dependencies import Context, OperatePrincipal, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..models import PatchRunCreateRequest
from ..scope import Scope

router = APIRouter(prefix="/api/v1", tags=["patching"])


def _service(context: Context, scope: Scope) -> Any:
    """Resolve the patching service for this scope.

    Mirrors the vulnerability router: a hybrid (live) service is preferred when
    the caller pinned explicit subscriptions, otherwise the snapshot-backed
    provider is used.
    """
    subscription_ids = list(scope.values("subscription"))
    hybrid = getattr(context, "hybrid_patching_provider", None)
    if callable(hybrid) and subscription_ids:
        return hybrid(subscription_ids)
    return context.resolve_provider("patching")


def _evidence(service: Any, confidence: str = CONFIDENCE_MEDIUM) -> Evidence:
    return Evidence(
        source_engine="operations.patching.PatchingService",
        source_table="patch_assessment_projection",
        timestamp=str(getattr(service, "freshness", "") or ""),
        confidence=confidence,
    )


def _run_evidence(service: Any) -> Evidence:
    return Evidence(
        source_engine="operations.patching.PatchingService",
        source_table="patch_runs",
        timestamp=str(getattr(service, "freshness", "") or ""),
        # A run record is a first-party fact: HOG wrote it.
        confidence=CONFIDENCE_HIGH,
    )


@router.get("/patching/targets", summary="Patchable compute inventory with available patches")
def patch_targets(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    service = _service(context, scope)
    rows = [target.to_dict() for target in service.targets(scope)]
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(service),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
        warnings=_adapter_warnings(service),
    )


@router.get("/patching/runs", summary="Patch run history")
def patch_runs(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    service = _service(context, scope)
    rows = [run.to_dict() for run in service.runs(scope)]
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_run_evidence(service),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.post(
    "/patching/runs",
    status_code=202,
    summary="Trigger patch installation or an AKS node image upgrade",
)
def create_patch_run(
    payload: PatchRunCreateRequest,
    context: Context,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    from operations.patching.adapters import PatchExecutionUnavailable
    from operations.patching.service import PatchValidationError

    # Narrow to what this principal may actually operate on before resolving
    # the target, so an out-of-scope target is indistinguishable from a
    # non-existent one.
    write_scope = context.authorizer.effective_scope(principal, "operate")
    service = _service(context, write_scope)
    target = service.target(payload.target_id, write_scope)
    if target is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "No patch target matches this id in the caller's scope",
            {"target_id": payload.target_id},
        )

    try:
        run = service.trigger(
            target=target,
            patch_ids=payload.patch_ids,
            requested_by=getattr(principal, "subject", ""),
            approved_by=payload.approved_by,
            reason=payload.reason,
            reboot_setting=payload.reboot_setting,
            node_pool=payload.node_pool,
            dry_run=payload.dry_run,
        )
    except PatchValidationError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc), dict(exc.details)) from exc
    except PatchExecutionUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            str(exc),
            {"capability": getattr(exc, "capability", "patch_execution")},
        ) from exc

    return envelope(
        run.to_dict(),
        evidence=_run_evidence(service),
        scope=write_scope.to_dict(),
    )


# Declared last: the ``:path`` converter otherwise shadows /patching/runs.
@router.get("/patching/targets/{target_id:path}", summary="One patch target and its available patches")
def patch_target(target_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    service = _service(context, scope)
    target = service.target(target_id, scope)
    if target is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No patch target matches this id", {"target_id": target_id})
    return envelope(
        target.to_dict(),
        evidence=_evidence(service),
        scope=scope.to_dict(),
        warnings=_adapter_warnings(service),
    )


def _adapter_warnings(service: Any) -> list[str]:
    """Surface an unexecutable deployment as a warning, not a silent no-op."""
    if getattr(service, "adapter_name", "") == "unconfigured":
        return [
            (
                "No patch execution adapter is configured; patch runs can be "
                "validated (dry run) but not submitted to Azure."
            )
        ]
    return []
