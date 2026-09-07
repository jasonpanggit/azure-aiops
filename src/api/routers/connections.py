"""Subscription connection routes.

Fronts :class:`SubscriptionOnboardingService` without duplicating any of its
logic. Read routes are scope-filtered; mutating routes require the ``write``
role and operational routes require ``operate``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Response

from ..dependencies import Context, OperatePrincipal, Page, ReadScope, WritePrincipal
from ..errors import not_found
from ..evidence import CONFIDENCE_HIGH, Evidence, envelope
from ..models import (
    ConnectionCreateRequest,
    ConnectionMetadataRequest,
    ConnectionSyncRequest,
    ConnectionUpdateRequest,
    ConnectionValidateRequest,
)
from ..rbac import ACTION_OPERATE, ACTION_WRITE, Principal
from ..scope import Scope

router = APIRouter(prefix="/api/v1/subscription-connections", tags=["connections"])

SOURCE_ENGINE = "onboarding.SubscriptionOnboardingService"
SOURCE_TABLE = "connection_registry"


def _evidence(connection_id: str = "", timestamp: str = "") -> Evidence:
    return Evidence(
        source_engine=SOURCE_ENGINE,
        source_table=SOURCE_TABLE,
        timestamp=timestamp,
        subscription_connection=connection_id,
        # The registry is the system of record for connections, so a read of it
        # is authoritative rather than inferred.
        confidence=CONFIDENCE_HIGH,
    )


def _scope_row(row: dict[str, Any]) -> dict[str, str]:
    """Project a connection summary onto scope dimensions."""
    return {
        "subscription": str(row.get("subscription_id") or "").casefold(),
        "subscription_connection": str(row.get("connection_id") or "").casefold(),
        "business_service": str(row.get("business_service") or "").casefold(),
        "environment": str(row.get("environment") or "").casefold(),
        "criticality": str(row.get("criticality") or "").casefold(),
    }


def _authorize_connection(scope: Scope, detail: dict[str, Any]) -> None:
    """Ensure a single connection falls inside the caller's effective scope."""
    if not scope.is_unrestricted() and not scope.matches(_scope_row(detail)):
        # Report as not-found rather than forbidden: revealing that a
        # connection exists outside the caller's scope is itself a disclosure.
        raise not_found(detail.get("connection_id", ""), "subscription connection")


def _authorize_action(
    context: Context,
    principal: Principal,
    action: str,
    detail: dict[str, Any],
) -> Scope:
    scope = context.authorizer.effective_scope(principal, action)
    _authorize_connection(scope, detail)
    return scope


def _optional(value: str | None) -> str | None:
    return value or None


@router.get("", summary="List subscription connections")
def list_connections(
    context: Context,
    scope: ReadScope,
    page: Page,
    include_disabled: bool = Query(True),
) -> dict[str, Any]:
    rows = context.onboarding.list(include_disabled=include_disabled)
    visible = [row for row in rows if scope.is_unrestricted() or scope.matches(_scope_row(row))]
    return envelope(
        visible[page.offset : page.offset + page.limit],
        evidence=_evidence(),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(visible)),
    )


@router.post("", status_code=201, summary="Onboard a subscription connection")
def create_connection(
    payload: ConnectionCreateRequest,
    context: Context,
    principal: WritePrincipal,
) -> dict[str, Any]:
    scope = _authorize_action(
        context,
        principal,
        ACTION_WRITE,
        {
            "connection_id": payload.connection_id,
            "subscription_id": payload.subscription_id,
            **payload.metadata.model_dump(),
        },
    )
    lifecycle = context.onboarding.add_and_initialize(
        connection_id=payload.connection_id,
        name=payload.name,
        tenant_id=payload.tenant_id,
        subscription_id=payload.subscription_id,
        client_id=payload.credential.client_id,
        secret_ref=payload.credential.secret_ref,
        client_secret=payload.credential.client_secret,
        credential_id=payload.credential.credential_id,
        metadata=payload.metadata.model_dump(),
    )
    return envelope(
        lifecycle,
        evidence=_evidence(payload.connection_id),
        scope=scope.to_dict(),
    )


@router.get("/{connection_id}", summary="Get a subscription connection")
def get_connection(
    connection_id: str,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    detail = context.onboarding.detail(connection_id)
    _authorize_connection(scope, detail)
    return envelope(detail, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.patch("/{connection_id}", summary="Update a subscription connection")
def update_connection(
    connection_id: str,
    payload: ConnectionUpdateRequest,
    context: Context,
    principal: WritePrincipal,
) -> dict[str, Any]:
    scope = _authorize_action(
        context, principal, ACTION_WRITE, context.onboarding.detail(connection_id)
    )
    credential = payload.credential
    detail = context.onboarding.update(
        connection_id,
        name=payload.name,
        client_id=_optional(credential.client_id) if credential else None,
        secret_ref=_optional(credential.secret_ref) if credential else None,
        client_secret=_optional(credential.client_secret) if credential else None,
        credential_id=_optional(credential.credential_id) if credential else None,
    )
    return envelope(detail, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.put("/{connection_id}/metadata", summary="Map business metadata")
def map_metadata(
    connection_id: str,
    payload: ConnectionMetadataRequest,
    context: Context,
    principal: WritePrincipal,
) -> dict[str, Any]:
    current = context.onboarding.detail(connection_id)
    merged = {**current, **payload.metadata.model_dump()}
    scope = _authorize_action(context, principal, ACTION_WRITE, merged)
    detail = context.onboarding.map_metadata(
        connection_id, payload.metadata.model_dump()
    )
    return envelope(detail, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.post("/{connection_id}/disable", summary="Disable a connection")
def disable_connection(
    connection_id: str,
    context: Context,
    principal: WritePrincipal,
) -> dict[str, Any]:
    scope = _authorize_action(
        context, principal, ACTION_WRITE, context.onboarding.detail(connection_id)
    )
    return envelope(
        context.onboarding.disable(connection_id),
        evidence=_evidence(connection_id),
        scope=scope.to_dict(),
    )


@router.post("/{connection_id}/enable", summary="Re-enable a connection")
def enable_connection(
    connection_id: str,
    context: Context,
    principal: WritePrincipal,
) -> dict[str, Any]:
    scope = _authorize_action(
        context, principal, ACTION_WRITE, context.onboarding.detail(connection_id)
    )
    return envelope(
        context.onboarding.enable(connection_id),
        evidence=_evidence(connection_id),
        scope=scope.to_dict(),
    )


@router.delete("/{connection_id}", status_code=204, summary="Delete a connection")
def delete_connection(
    connection_id: str,
    context: Context,
    principal: WritePrincipal,
) -> Response:
    _authorize_action(
        context, principal, ACTION_WRITE, context.onboarding.detail(connection_id)
    )
    context.onboarding.delete(connection_id)
    return Response(status_code=204)


@router.post("/{connection_id}/validate", summary="Validate connection access")
def validate_connection(
    connection_id: str,
    context: Context,
    principal: OperatePrincipal,
    payload: ConnectionValidateRequest | None = None,
) -> dict[str, Any]:
    scope = _authorize_action(
        context, principal, ACTION_OPERATE, context.onboarding.detail(connection_id)
    )
    checks = tuple(payload.checks) if payload and payload.checks else None
    report = context.onboarding.validate(connection_id, checks=checks)
    return envelope(report, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.post("/{connection_id}/sync", summary="Start a connection-scoped sync")
def sync_connection(
    connection_id: str,
    context: Context,
    principal: OperatePrincipal,
    payload: ConnectionSyncRequest | None = None,
) -> dict[str, Any]:
    """Resync everything: restart inventory ingestion and enqueue a durable
    ontology refresh, then return immediately."""
    scope = _authorize_action(
        context, principal, ACTION_OPERATE, context.onboarding.detail(connection_id)
    )
    mode = payload.mode if payload else "manual"
    result = context.onboarding.enqueue_full_sync(
        connection_id,
        mode=mode,
        requested_by=principal.subject,
    )
    return envelope(result, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.get("/{connection_id}/health", summary="Connection health")
def connection_health(
    connection_id: str,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    detail = context.onboarding.detail(connection_id)
    _authorize_connection(scope, detail)
    report = context.onboarding.health_report(connection_id)
    return envelope(
        report,
        evidence=_evidence(connection_id, report.get("generated_at", "")),
        scope=scope.to_dict(),
    )
