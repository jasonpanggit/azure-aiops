"""Context and search routes.

Every route here reads through the Semantic Knowledge Layer
(:class:`SemanticEngine`). No handler touches Fabric, the ontology tables, or
Azure Resource Graph directly — that constraint is what keeps the API a
projection of the knowledge layer rather than a second source of truth.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..dependencies import Context, ReadScope
from ..errors import not_found
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope, scope_attributes

router = APIRouter(prefix="/api/v1", tags=["context"])

SOURCE_ENGINE = "semantic.SemanticEngine"


def _evidence(
    context: dict[str, Any],
    *,
    source_table: str,
    resource_id: str = "",
    connection: str = "",
    confidence: str = CONFIDENCE_HIGH,
) -> Evidence:
    return Evidence.from_context(
        context,
        source_engine=SOURCE_ENGINE,
        source_table=source_table,
        resource_id=resource_id,
        subscription_connection=connection,
        confidence=confidence,
    )


_HIDDEN = object()


def _filter_scoped(value: Any, scope: Scope) -> Any:
    """Recursively remove public entities outside the caller's scope."""
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


def _scoped(context: dict[str, Any], scope: Scope) -> dict[str, Any]:
    """Filter all public entities in a context, including nested mappings."""
    filtered = _filter_scoped(context, scope)
    visible = filtered if isinstance(filtered, dict) else {}
    if not scope.is_unrestricted():
        for key in ("items", "results"):
            if isinstance(visible.get(key), list) and "count" in visible:
                visible["count"] = len(visible[key])
        sections = visible.get("sections")
        metadata = visible.get("section_metadata")
        if isinstance(sections, dict) and isinstance(metadata, dict):
            for name, rows in sections.items():
                if isinstance(rows, list) and isinstance(metadata.get(name), dict):
                    metadata[name] = {
                        "total": len(rows),
                        "returned": len(rows),
                        "truncated": False,
                    }
            visible["scope_limited"] = True
    return visible


def _authorize_subject(context: dict[str, Any], scope: Scope, subject: str) -> None:
    """Reject a singular out-of-scope subject without revealing its existence."""
    if scope.is_unrestricted():
        return
    value = context.get("subject") or context.get("root")
    if isinstance(value, dict):
        attributes = scope_attributes(value)
        if attributes and not scope.matches(attributes):
            raise not_found(subject)


def _respond(
    context: dict[str, Any],
    scope: Scope,
    *,
    source_table: str,
    resource_id: str = "",
    connection: str = "",
    confidence: str = CONFIDENCE_HIGH,
    subject_public: dict[str, str] | None = None,
) -> dict[str, Any]:
    scoped_context = context
    if subject_public and isinstance(context.get("subject"), dict):
        scoped_context = {
            **context,
            "subject": {**context["subject"], **subject_public},
        }
    _authorize_subject(scoped_context, scope, resource_id)
    visible = _scoped(scoped_context, scope)
    if not scope.is_unrestricted() and isinstance(visible.get("blast_radius"), dict):
        visible["blast_radius"] = {
            "application_count": len(visible.get("impacted_applications") or []),
            "business_service_count": len(
                visible.get("impacted_business_services") or []
            ),
            "service_count": len(visible.get("impacted_services") or []),
        }
        visible.pop("collection_metadata", None)
        visible["scope_limited"] = True
    return envelope(
        visible,
        evidence=_evidence(
            context,
            source_table=source_table,
            resource_id=resource_id,
            connection=connection,
            confidence=confidence,
        ),
        scope=scope.to_dict(),
        knowledge_version=str(context.get("knowledge_version") or ""),
        warnings=(
            context.get("warnings", [])
            if isinstance(context.get("warnings"), list)
            else []
        ),
    )


@router.get("/search", summary="Search operational context")
def search(
    context: Context,
    scope: ReadScope,
    q: str = Query(
        min_length=1,
        max_length=512,
        description=(
            "Intent-driven query. Supported: 'production applications'; "
            "'show list of VMs'; "
            "'applications owned by <owner>'; 'servers with failed patches'; "
            "'resources missing ownership'; 'applications missing ownership'; "
            "'resources related to business service <name>'; "
            "'critical infrastructure'. Unsupported phrases return 400 with the "
            "supported list rather than an empty result set."
        ),
    ),
) -> dict[str, Any]:
    subscription_ids = list(scope.values("subscription"))
    normalized_query = q.casefold().strip()
    live_search = normalized_query.startswith("show list of") and (
        "vm" in normalized_query or "server" in normalized_query
    )
    if context.hybrid_search_provider is not None and subscription_ids and live_search:
        result = context.hybrid_search_provider(q, subscription_ids)
    else:
        result = context.semantic().search(q)
    visible = _scoped(result, scope)
    return envelope(
        visible,
        evidence=_evidence(
            result,
            source_table="ontology_entities",
            # Search ranks across heterogeneous entities, so a hit is a strong
            # but not authoritative answer to the user's actual question.
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        knowledge_version=str(result.get("knowledge_version") or ""),
    )


@router.get("/business-services/{name}", summary="Business service context")
def business_service_context(
    name: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    subscription_ids = list(scope.values("subscription"))
    if context.hybrid_business_service_provider is not None and subscription_ids:
        result = context.hybrid_business_service_provider(name, subscription_ids)
    else:
        result = context.semantic().get_service_context(name, subject_type="BusinessService")
    return _respond(
        result,
        scope,
        source_table="ontology_entities",
        resource_id=name,
        subject_public=context.semantic().public_subject(
            name, types={"BusinessService"}
        ),
    )


@router.get("/applications/{name}", summary="Application context")
def application_context(name: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    result = context.semantic().get_application_context(name)
    return _respond(
        result,
        scope,
        source_table="ontology_entities",
        resource_id=name,
        subject_public=context.semantic().public_subject(name, types={"Application"}),
    )


@router.get("/environments/{name}", summary="Environment context")
def environment_context(name: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    result = context.semantic().get_environment_context(name)
    return _respond(
        result,
        scope,
        source_table="ontology_entities",
        resource_id=name,
        subject_public=context.semantic().public_subject(name, types={"Environment"}),
    )


@router.get("/subscriptions/{name}", summary="Subscription context")
def subscription_context(name: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    result = context.semantic().get_subscription_context(name)
    return _respond(
        result,
        scope,
        source_table="ontology_entities",
        resource_id=name,
        subject_public=context.semantic().public_subject(name, types={"Subscription"}),
    )


@router.get(
    "/subscription-connections/{name}/context",
    summary="Subscription connection context",
)
def subscription_connection_context(
    name: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    result = context.semantic().get_subscription_connection_context(name)
    return _respond(
        result,
        scope,
        source_table="ontology_entities",
        resource_id=name,
        connection=name,
        subject_public=context.semantic().public_subject(
            name, types={"SubscriptionConnection"}
        ),
    )


@router.get("/resources/{resource_id:path}", summary="Resource context")
def resource_context(
    resource_id: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    subscription_ids = list(scope.values("subscription"))
    if context.hybrid_resource_provider is not None and subscription_ids:
        result = context.hybrid_resource_provider(resource_id, subscription_ids)
    else:
        result = context.semantic().get_resource_context(resource_id)
    return _respond(
        result,
        scope,
        source_table="ontology_entities",
        resource_id=resource_id,
        subject_public=context.semantic().public_subject(resource_id),
    )


@router.get("/risk/{subject}", summary="Aggregated risk for a subject")
def risk_context(subject: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    subscription_ids = list(scope.values("subscription"))
    if context.hybrid_risk_provider is not None and subscription_ids:
        result = context.hybrid_risk_provider(subject, subscription_ids)
    else:
        result = context.semantic().get_risk_context(subject)
    return _respond(
        result,
        scope,
        source_table="ontology_entities",
        resource_id=subject,
        confidence=CONFIDENCE_MEDIUM,
    )


@router.get("/impact/{subject}", summary="Blast radius for a subject")
def impact_context(subject: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    subscription_ids = list(scope.values("subscription"))
    if context.hybrid_impact_provider is not None and subscription_ids:
        result = context.hybrid_impact_provider(subject, subscription_ids)
    else:
        result = context.semantic().get_impact_context(subject)
    return _respond(
        result,
        scope,
        source_table="ontology_relationships",
        resource_id=subject,
        confidence=CONFIDENCE_MEDIUM,
    )
