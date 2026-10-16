"""Context and search routes.

Every route here reads through the Semantic Knowledge Layer
(:class:`SemanticEngine`). No handler touches Fabric, the ontology tables, or
Azure Resource Graph directly — that constraint is what keeps the API a
projection of the knowledge layer rather than a second source of truth.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query

from intelligence.governance import IdentityRiskEngine

from ..dependencies import Context, ReadScope, live_subscription_ids
from ..errors import not_found
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope, scope_attributes

router = APIRouter(prefix="/api/v1", tags=["context"])

SOURCE_ENGINE = "semantic.SemanticEngine"
IDENTITY_ENGINE = "intelligence.governance.IdentityRiskEngine"
GOVERNANCE_SOURCE_TABLE = "connection_generation_entities"
_USER_ASSIGNED_MANAGED_IDENTITY_ID = re.compile(
    r"^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/"
    r"microsoft\.managedidentity/userassignedidentities/[^/]+/?$",
    flags=re.IGNORECASE,
)


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


def _is_identity_identifier(value: str) -> bool:
    """Return whether ``value`` is an exact Entra object or managed identity ID."""
    candidate = value.strip()
    if _USER_ASSIGNED_MANAGED_IDENTITY_ID.fullmatch(candidate):
        return True
    try:
        UUID(candidate)
    except ValueError:
        return False
    return True


def _identity_identifier_search(
    context: Context,
    scope: Scope,
    identifier: str,
) -> tuple[dict[str, Any], Evidence, list[str]]:
    """Search the bounded, scope-pinned identity projection by exact ID."""
    snapshot = context.governance_snapshot(scope)
    engine = IdentityRiskEngine(
        role_assignments=snapshot.rows("RoleAssignment"),
        role_definitions=snapshot.rows("RoleDefinition"),
        managed_identities=snapshot.rows("ManagedIdentity"),
    )
    expected = identifier.strip().casefold()
    candidates = [
        record.to_dict() for record in engine.principals()
    ] + engine.non_human_identities()
    matches: dict[str, dict[str, Any]] = {}
    for record in candidates:
        identifiers = {
            str(record.get(field) or "").strip().casefold()
            for field in ("principal_id", "resource_id")
        }
        if expected not in identifiers:
            continue
        principal_id = str(record.get("principal_id") or "")
        resource_id = str(record.get("resource_id") or "")
        key = resource_id.casefold() or principal_id.casefold()
        matches[key] = {
            **record,
            "id": resource_id or principal_id,
            "name": str(record.get("name") or principal_id),
            "entity_type": str(record.get("principal_type") or "IdentityPrincipal"),
            "source": GOVERNANCE_SOURCE_TABLE,
            "freshness": snapshot.observed_at,
        }
    results = list(matches.values())
    return (
        {
            "query": identifier,
            "intent": "identity_identifier_lookup",
            "results": results,
            "count": len(results),
            "freshness": snapshot.observed_at,
            "truncated": False,
        },
        Evidence(
            source_engine=IDENTITY_ENGINE,
            source_table=GOVERNANCE_SOURCE_TABLE,
            resource_id=identifier,
            confidence=CONFIDENCE_HIGH,
            timestamp=snapshot.observed_at,
        ),
        list(snapshot.warnings),
    )


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


@router.get("/search/capabilities", summary="Inspect supported search prerequisites")
def search_capabilities(context: Context, scope: ReadScope) -> dict[str, Any]:
    """Describe current search modes without hydrating deferred providers."""
    semantic_state = "configured" if context.semantic_provider is not None else "unavailable"
    semantic_queryable = context.semantic_provider is not None
    if context.provider_runtime is not None:
        semantic = context.provider_runtime.health(refresh=False).get("providers", {}).get("semantic", {})
        semantic_state = str(semantic.get("state") or "unavailable")
        semantic_queryable = bool(semantic.get("loaded"))
    live = context.hybrid_search_provider is not None and bool(live_subscription_ids(context, scope, default_all=True))
    return envelope({
        "live": {
            "state": "configured" if live else "unavailable",
            "can_query": live,
            "phrases": ["show list of VMs"],
            "prerequisite": "An authorized active subscription connection and live resource provider.",
        },
        "semantic": {
            "state": semantic_state,
            "can_query": semantic_queryable,
            "phrases": [
                "production applications", "applications owned by <owner>",
                "servers with failed patches", "resources missing ownership",
                "applications missing ownership",
                "resources related to business service <name>", "critical infrastructure",
            ],
            "prerequisite": "A loaded, published semantic snapshot; configured does not prove live reachability.",
        },
        "identity": {
            "state": "configured" if context.governance_generation_provider or context.governance_provider else "unavailable",
            "prerequisite": "An exact principal GUID or managed-identity resource ID and authorized governance evidence.",
        },
    }, scope=scope.to_dict())


def _search_exploration(
    result: dict[str, Any], *, offset: int, limit: int | None, entity_type: str, source: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Facet and page only already-authorized provider results, not estate totals."""
    if limit is None and not (offset or entity_type or source):
        return result, None
    limit = limit or 25
    key = "results" if isinstance(result.get("results"), list) else "items"
    rows = result.get(key) or []
    types = Counter(str(row.get("entity_type") or row.get("entityType") or row.get("kind") or row.get("type") or "Operational record") for row in rows)
    sources = Counter(str(row.get("source") or row.get("source_engine") or row.get("source_table") or "Unreported") for row in rows)
    filtered = [
        row for row in rows
        if (not entity_type or str(row.get("entity_type") or row.get("entityType") or row.get("kind") or row.get("type") or "Operational record") == entity_type)
        and (not source or str(row.get("source") or row.get("source_engine") or row.get("source_table") or "Unreported") == source)
    ]
    total = len(filtered)
    # Never expose another unpaged collection from a mixed-provider payload.
    visible = {name: value for name, value in result.items() if name not in {"items", "results"}}
    visible.update({
        key: filtered[offset:offset + limit], "count": total,
        "facets": {"entity_type": dict(sorted(types.items())), "source": dict(sorted(sources.items()))},
        "represented_count": len(rows), "aggregate_basis": "authorized_provider_results",
    })
    return visible, {
        "offset": offset, "limit": limit, "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
    }


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
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int | None = Query(default=None, ge=1, le=100),
    entity_type: str = Query(default="", max_length=128),
    source: str = Query(default="", max_length=256),
) -> dict[str, Any]:
    if _is_identity_identifier(q):
        result, evidence, warnings = _identity_identifier_search(context, scope, q)
        result, pagination = _search_exploration(
            _scoped(result, scope), offset=offset, limit=limit, entity_type=entity_type, source=source,
        )
        return envelope(
            result,
            evidence=evidence,
            scope=scope.to_dict(),
            warnings=warnings,
            pagination=pagination,
        )
    normalized_query = q.casefold().strip()
    live_search = normalized_query.startswith("show list of") and (
        "vm" in normalized_query or "server" in normalized_query
    )
    subscription_ids = (
        live_subscription_ids(context, scope, default_all=True)
        if live_search and context.hybrid_search_provider is not None
        else []
    )
    if context.hybrid_search_provider is not None and subscription_ids and live_search:
        result = context.hybrid_search_provider(q, subscription_ids)
    else:
        result = context.semantic().search(q)
    visible = _scoped(result, scope)
    visible, pagination = _search_exploration(
        visible, offset=offset, limit=limit, entity_type=entity_type, source=source,
    )
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
        pagination=pagination,
    )


@router.get("/business-services/{name}", summary="Business service context")
def business_service_context(
    name: str, context: Context, scope: ReadScope
) -> dict[str, Any]:
    subscription_ids = live_subscription_ids(context, scope, default_all=True)
    if context.hybrid_business_service_provider is not None and subscription_ids:
        result = context.hybrid_business_service_provider(name, subscription_ids)
        subject_public = None
    else:
        semantic = context.semantic()
        result = semantic.get_service_context(name, subject_type="BusinessService")
        subject_public = semantic.public_subject(
            name, types={"BusinessService"}
        )
    return _respond(
        result,
        scope,
        source_table="ontology_entities",
        resource_id=name,
        subject_public=subject_public,
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
    subscription_ids = live_subscription_ids(context, scope)
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
    subscription_ids = live_subscription_ids(context, scope, default_all=True)
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
    subscription_ids = live_subscription_ids(context, scope, default_all=True)
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
