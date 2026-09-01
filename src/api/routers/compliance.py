"""Compliance posture routes: policy deviations, security baseline deviations,
configuration drift, and change-authorization compliance.

These front :class:`ChangeIntelligence`, which already emits `PolicyDeviation`,
`SecurityDeviation`, `ConfigurationDrift`, `AuthorizedChange`, and
`UnapprovedChange` ontology entities from the same knowledge snapshot the other
intelligence engines read. The compliance UI previously re-derived a client-side
approximation of these findings from network/vulnerability data with no
governed, evidence-backed posture record; this router exposes the engine's
findings directly so posture reflects the authoritative ontology-graph state.

The engine is resolved per request through a provider callable, mirroring the
network/incident/patching routers, so a refreshed snapshot is observed without
a restart. When no provider is registered the routes report the capability as
unavailable rather than returning an empty result the UI would render as
"fully compliant" -- a dangerous default for a compliance-facing view.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..dependencies import Context, Page, ReadScope
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope, scope_attributes

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])

SOURCE_ENGINE = "intelligence.change.ChangeIntelligence"

_HIDDEN = object()


def _service(context: Context, scope: Scope) -> Any:
    """Resolve the change-intelligence engine for this scope.

    Mirrors the incident/network routers: a hybrid (live) service is preferred
    when the caller pinned explicit subscriptions, otherwise the
    snapshot-backed provider is used.
    """
    subscription_ids = list(scope.values("subscription"))
    hybrid = getattr(context, "hybrid_change_provider", None)
    if callable(hybrid) and subscription_ids:
        return hybrid(subscription_ids)
    return context.resolve_provider("change")


def _filter_scoped(value: Any, scope: Scope) -> Any:
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


def _filter_rows(rows: Any, scope: Scope) -> Any:
    filtered = _filter_scoped(rows, scope)
    return [] if filtered is _HIDDEN else filtered


def _subscription_id(resource_key: str) -> str:
    parts = str(resource_key or "").split("/")
    try:
        return parts[parts.index("subscriptions") + 1]
    except (ValueError, IndexError):
        return ""


def _enriched_deviations(engine: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join deviation rows with resource business context for scope filtering.

    ``ChangeIntelligence.query()`` strips ``resource_key`` from deviation rows
    before returning them (it is an internal join key, not a public field), so
    scope narrowing must happen against an enriched copy that still carries
    the resource's business attributes.
    """
    enriched = []
    for row in rows:
        key = row.get("resource_key")
        context = engine.context_builder.get(key) if key else {}
        enriched.append(
            {
                **{k: v for k, v in row.items() if k != "resource_key"},
                "resource": context.get("resource", {}).get("name", "Unknown"),
                "application": context.get("application", "Unknown"),
                "business_service": context.get("business_service", "Unknown"),
                "environment": context.get("environment", "Unknown"),
                "business_criticality": context.get("business_criticality", "Unknown"),
                "subscription": _subscription_id(key),
            }
        )
    return enriched


def _evidence(engine: Any, source_table: str, confidence: str = CONFIDENCE_MEDIUM) -> Evidence:
    return Evidence(
        source_engine=SOURCE_ENGINE,
        source_table=source_table,
        timestamp=str(getattr(engine, "freshness", "") or ""),
        confidence=confidence,
    )


@router.get(
    "/posture",
    summary="Compliance posture: per-resource drift, policy, and security deviation counts",
)
def compliance_posture(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    engine = _service(context, scope)
    analysis = engine.analyze()
    rows = _filter_rows(analysis.get("compliance"), scope)
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(engine, "change_compliance_projection"),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
        warnings=list(analysis.get("warnings") or []),
    )


@router.get(
    "/policy-deviations",
    summary="Open policy deviations (PolicyDeviation ontology entities)",
)
def policy_deviations(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    engine = _service(context, scope)
    rows = _filter_rows(_enriched_deviations(engine, engine.policy), scope)
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(engine, "ontology_policy_deviation_entities"),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.get(
    "/security-deviations",
    summary="Open security baseline deviations (SecurityDeviation ontology entities)",
)
def security_deviations(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    engine = _service(context, scope)
    rows = _filter_rows(_enriched_deviations(engine, engine.security), scope)
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(engine, "ontology_security_deviation_entities"),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.get(
    "/configuration-drift",
    summary="Resources with configuration drift against their expected baseline",
)
def configuration_drift(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    engine = _service(context, scope)
    result = engine.query("show configuration drift")
    rows = _filter_rows(result.get("result"), scope)
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(engine, "ontology_configuration_drift_entities"),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.get(
    "/unapproved-changes",
    summary="Changes classified as unapproved (UnapprovedChange ontology entities)",
)
def unapproved_changes(context: Context, scope: ReadScope, page: Page) -> dict[str, Any]:
    engine = _service(context, scope)
    result = engine.query("show unapproved changes")
    rows = _filter_rows(result.get("result"), scope)
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(engine, "ontology_unapproved_change_entities"),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.get(
    "/summary",
    summary="Compliance intelligence summary: counts, trends, and per-scope rollups",
)
def compliance_summary(context: Context, scope: ReadScope) -> dict[str, Any]:
    engine = _service(context, scope)
    analysis = engine.analyze()
    summary = _filter_scoped(analysis.get("summary"), scope)
    if summary is _HIDDEN:
        summary = {}
    trends = analysis.get("trends")
    application_compliance = _filter_rows(analysis.get("application_compliance"), scope)
    business_service_compliance = _filter_rows(
        analysis.get("business_service_compliance"), scope
    )
    payload = {
        "summary": summary,
        "trends": trends,
        "application_compliance": application_compliance,
        "business_service_compliance": business_service_compliance,
    }
    return envelope(
        payload,
        evidence=_evidence(engine, "change_compliance_projection"),
        scope=scope.to_dict(),
    )
