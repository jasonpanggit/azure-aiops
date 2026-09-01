"""Read-only patch inventory and patch-run history.

State-changing patch operations are intentionally absent from this public
router. They are submitted internally only after a remediation plan's exact
execution snapshot has been approved.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..dependencies import Context, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
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
