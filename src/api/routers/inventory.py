"""Scope-enforced OS inventory endpoints."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter

from intelligence.inventory.eol_repository import (
    CatalogRevisionConflict,
    DuplicateCatalogConfirmation,
)
from intelligence.inventory.mapping_repository import (
    MappingNotFound,
    MappingRevisionConflict,
    MappingStatusConflict,
)
from intelligence.inventory.eol_review import normalize_os_key
from intelligence.inventory.service import InventoryService

from ..dependencies import Context, OperatePrincipal, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope
from ..models import (
    EOLConfirmationRequest,
    SoftwareMappingDecisionRequest,
    SoftwareMappingPathDecisionRequest,
)

router = APIRouter(prefix="/api/v1", tags=["inventory"])
_GROUP_KEY = re.compile(r"^[^|/\\]{1,120}\|[^|/\\]{1,120}$")


def _service(context: Context) -> InventoryService:
    service = context.resolve_provider("inventory")
    if not isinstance(service, InventoryService):
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The inventory provider has no loaded snapshot",
            {"capability": "inventory", "provider_state": "unavailable"},
        )
    return service


def _evidence(service: InventoryService) -> Evidence:
    return Evidence(
        source_engine="intelligence.inventory.InventoryService",
        source_table="inventory/os_observations",
        timestamp=service.observed_at,
        confidence="high",
    )


def _software_evidence(service: InventoryService) -> Evidence:
    return Evidence(
        source_engine="intelligence.inventory.InventoryService",
        source_table="inventory/software_observations",
        timestamp=service.observed_at,
        confidence="high",
    )


def _lifecycle_evidence(service: InventoryService) -> Evidence:
    return Evidence(
        source_engine="intelligence.inventory.EOLReviewService",
        source_table="inventory/lifecycle_reviews",
        timestamp=service.observed_at,
        confidence="high",
    )


@router.get("/inventory/os", summary="Grouped operating-system inventory")
def os_inventory(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    service = _service(context)
    result = service.collection(scope, offset=page.offset, limit=page.limit)
    return envelope(
        result["data"],
        evidence=_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=result["data"]["query_version"],
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )


@router.get(
    "/inventory/os/{group_key:path}/lifecycle",
    summary="Review lifecycle candidates for an OS inventory group",
)
def os_lifecycle_review(
    group_key: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    if not _GROUP_KEY.fullmatch(group_key):
        raise ApiError(ErrorCode.INVALID_REQUEST, "Invalid OS inventory group key")
    service = _service(context)
    result = service.lifecycle_review(group_key, scope)
    if result is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No OS inventory group matches this scope")
    return envelope(
        result,
        evidence=_lifecycle_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=str(result.get("catalog_revision", "")),
    )


@router.post(
    "/inventory/os/{group_key:path}/lifecycle/confirm",
    summary="Confirm an OS lifecycle candidate or manual date",
)
def confirm_os_lifecycle(
    group_key: str,
    payload: EOLConfirmationRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    if not _GROUP_KEY.fullmatch(group_key):
        raise ApiError(ErrorCode.INVALID_REQUEST, "Invalid OS inventory group key")
    operate_scope = context.authorizer.effective_scope(principal, "operate", scope)
    service = _service(context)
    detail = service.detail(group_key, operate_scope)
    if detail is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No OS inventory group matches this scope")
    group = detail["data"]["group"]
    expected_key = normalize_os_key(group["os_name"], group["os_version"])
    if payload.normalized_os_key != expected_key:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "normalized_os_key must exactly match the reviewed OS",
        )
    try:
        result = service.eol_review.confirm(
            os_name=group["os_name"],
            os_version=group["os_version"],
            normalized_os_key=payload.normalized_os_key,
            expected_revision=payload.expected_revision,
            reviewer=principal.subject,
            candidate_id=payload.candidate_id,
            manual_date=payload.manual_date,
            support_channel=payload.support_channel,
        )
    except CatalogRevisionConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "The lifecycle catalog changed; refresh candidates before confirming",
            {"expected_revision": exc.expected, "current_revision": exc.current},
        ) from exc
    except DuplicateCatalogConfirmation as exc:
        raise ApiError(ErrorCode.CONFLICT, str(exc)) from exc
    return envelope(
        result.to_dict(),
        evidence=_lifecycle_evidence(service),
        scope=operate_scope.to_dict(),
        knowledge_version=str(result.catalog_revision),
    )


@router.get("/inventory/os/{group_key:path}", summary="Machines in an OS inventory group")
def os_inventory_detail(
    group_key: str, context: Context, scope: ReadScope, page: Page
) -> dict[str, Any]:
    if not _GROUP_KEY.fullmatch(group_key):
        raise ApiError(ErrorCode.INVALID_REQUEST, "Invalid OS inventory group key")
    service = _service(context)
    result = service.detail(group_key, scope, offset=page.offset, limit=page.limit)
    if result is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No OS inventory group matches this scope")
    return envelope(
        result["data"],
        evidence=_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=result["data"]["query_version"],
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )


@router.get("/inventory/software", summary="Grouped installed-software inventory")
def software_inventory(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    service = _service(context)
    result = service.software_collection(scope, offset=page.offset, limit=page.limit)
    return envelope(
        result["data"],
        evidence=_software_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=result["data"]["query_version"],
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )


@router.get(
    "/inventory/software/mappings",
    summary="List software normalization mappings for the authorized scope",
)
def software_mapping_list(
    context: Context, scope: ReadScope, page: Page
) -> dict[str, Any]:
    service = _service(context)
    result = service.mapping_collection(scope, offset=page.offset, limit=page.limit)
    return envelope(
        result["data"],
        evidence=_software_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=str(result["data"]["repository_revision"]),
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )


@router.get(
    "/inventory/software/mappings/{mapping_id:path}",
    summary="Get one authorized software normalization mapping",
)
def software_mapping_detail(
    mapping_id: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    service = _service(context)
    result = service.mapping_detail(mapping_id, scope)
    if result is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No software mapping matches this scope")
    return envelope(
        result["data"],
        evidence=_software_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=str(result["data"]["mapping"]["revision"]),
        warnings=result["warnings"],
    )


def _decide_mapping(
    decision: str,
    payload: SoftwareMappingDecisionRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    operate_scope = context.authorizer.effective_scope(principal, "operate", scope)
    service = _service(context)
    # The visibility check is deliberately before mutation so an operator
    # cannot probe or mutate a mapping outside the effective scope.
    if service.mapping_detail(payload.mapping_id, operate_scope) is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No software mapping matches this scope")
    try:
        mapping = service.mapping_repository.decide(
            payload.mapping_id,
            decision=decision,
            expected_revision=payload.expected_revision,
            actor=principal.subject,
            scope_snapshot=operate_scope.to_dict(),
            reason=payload.reason,
        )
    except MappingRevisionConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "The software mapping changed; refresh before deciding",
            {"mapping_id": exc.mapping_id, "expected_revision": exc.expected, "current_revision": exc.current},
        ) from exc
    except MappingStatusConflict as exc:
        raise ApiError(ErrorCode.CONFLICT, str(exc)) from exc
    except MappingNotFound as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "No software mapping matches this scope") from exc
    return envelope(
        mapping.to_dict(),
        evidence=_software_evidence(service),
        scope=operate_scope.to_dict(),
        knowledge_version=str(mapping.revision),
    )


@router.post(
    "/inventory/software/mappings/approve",
    summary="Approve a software normalization mapping",
)
def approve_software_mapping(
    payload: SoftwareMappingDecisionRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    return _decide_mapping("approved", payload, context, scope, principal)


@router.post(
    "/inventory/software/mappings/reject",
    summary="Reject a software normalization mapping",
)
def reject_software_mapping(
    payload: SoftwareMappingDecisionRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    return _decide_mapping("rejected", payload, context, scope, principal)


def _decide_mapping_by_path(
    decision: str,
    mapping_id: str,
    payload: SoftwareMappingPathDecisionRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    return _decide_mapping(
        decision,
        SoftwareMappingDecisionRequest(
            mapping_id=mapping_id,
            expected_revision=payload.expected_revision,
            reason=payload.reason,
        ),
        context,
        scope,
        principal,
    )


@router.post(
    "/inventory/software/mappings/{mapping_id:path}/approve",
    summary="Approve a software normalization mapping by id",
)
def approve_software_mapping_by_path(
    mapping_id: str,
    payload: SoftwareMappingPathDecisionRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    return _decide_mapping_by_path(
        "approved", mapping_id, payload, context, scope, principal
    )


@router.post(
    "/inventory/software/mappings/{mapping_id:path}/reject",
    summary="Reject a software normalization mapping by id",
)
def reject_software_mapping_by_path(
    mapping_id: str,
    payload: SoftwareMappingPathDecisionRequest,
    context: Context,
    scope: ReadScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    return _decide_mapping_by_path(
        "rejected", mapping_id, payload, context, scope, principal
    )


@router.get(
    "/inventory/software/{software_key:path}",
    summary="Machines with an exact installed software and version",
)
def software_inventory_detail(
    software_key: str, context: Context, scope: ReadScope, page: Page
) -> dict[str, Any]:
    if not _GROUP_KEY.fullmatch(software_key):
        raise ApiError(ErrorCode.INVALID_REQUEST, "Invalid software inventory key")
    software_name, software_version = software_key.split("|", 1)
    service = _service(context)
    result = service.software_detail(
        software_name,
        software_version,
        scope,
        offset=page.offset,
        limit=page.limit,
    )
    if result is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "No installed software and version matches this scope",
        )
    return envelope(
        result["data"],
        evidence=_software_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=result["data"]["query_version"],
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )
