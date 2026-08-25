"""Scope-enforced OS inventory endpoints."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter

from intelligence.inventory.service import InventoryService

from ..dependencies import Context, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope

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
