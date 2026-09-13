"""Operational digital twin routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from network.service import NetworkScope
from semantic.operational_twin import OperationalTwinComposer

from ..dependencies import Context, ReadScope, live_subscription_ids
from ..evidence import CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope

router = APIRouter(prefix="/api/v1/twin", tags=["operational-twin"])


def _resolve(
    context: Context,
    name: str,
    errors: list[dict[str, str]],
    generation: Any | None = None,
) -> Any | None:
    try:
        provider = context.resolve_provider(name, optional=True)
        if generation is not None and hasattr(provider, "for_generation"):
            return provider.for_generation(generation)
        return provider
    except Exception as exc:  # noqa: BLE001 - provider resolution must not crash the endpoint
        errors.append({"source": name, "error": exc.__class__.__name__})
        return None


def _composer(context: Context, scope: Scope) -> OperationalTwinComposer:
    subscription_ids = live_subscription_ids(context, scope)
    source_errors: list[dict[str, str]] = []
    generation = None
    resolver_provider = getattr(context, "generation_resolver_provider", None)
    if callable(resolver_provider):
        try:
            generation = resolver_provider().resolve()
        except Exception as exc:  # noqa: BLE001 - aggregate a failed optional source
            source_errors.append(
                {"source": "ontology_generation", "error": exc.__class__.__name__}
            )
    network = (
        context.hybrid_network_provider(subscription_ids)
        if context.hybrid_network_provider is not None and subscription_ids
        else _resolve(context, "network", source_errors, generation)
    )
    if generation is not None and hasattr(network, "for_generation"):
        network = network.for_generation(generation)
    if network is not None and hasattr(network, "scoped"):
        network = network.scoped(
            NetworkScope(
                connection_ids=tuple(scope.dimensions.get("subscription_connection", ())),
                subscription_ids=tuple(scope.dimensions.get("subscription", ())),
                environments=tuple(scope.dimensions.get("environment", ())),
                business_services=tuple(scope.dimensions.get("business_service", ())),
                applications=tuple(scope.dimensions.get("application", ())),
                owners=tuple(scope.dimensions.get("owner", ())),
            )
        )
    vulnerability = (
        context.hybrid_vulnerability_provider(subscription_ids)
        if context.hybrid_vulnerability_provider is not None and subscription_ids
        else _resolve(context, "vulnerability", source_errors, generation)
    )
    if generation is not None and hasattr(vulnerability, "for_generation"):
        vulnerability = vulnerability.for_generation(generation)
    incidents = (
        context.hybrid_incident_provider(subscription_ids)
        if context.hybrid_incident_provider is not None and subscription_ids
        else _resolve(context, "incident", source_errors, generation)
    )
    if generation is not None and hasattr(incidents, "for_generation"):
        incidents = incidents.for_generation(generation)
    remediation = (
        context.hybrid_remediation_provider(subscription_ids)
        if context.hybrid_remediation_provider is not None and subscription_ids
        else _resolve(context, "remediation", source_errors, generation)
    )
    if generation is not None and hasattr(remediation, "for_generation"):
        remediation = remediation.for_generation(generation)
    return OperationalTwinComposer(
        semantic=_resolve(context, "semantic", source_errors, generation),
        network=network,
        vulnerability=vulnerability,
        incidents=incidents,
        remediation=remediation,
        scope=scope.to_dict(),
        scope_filter=scope,
        source_errors=source_errors,
    )


def _respond(data: dict[str, Any], scope: Scope, *, resource_id: str = "") -> dict[str, Any]:
    payload = {
        **data,
        "live_observed_at": str(data.get("observed_at") or data.get("exported_at") or ""),
        "source_status": {
            "semantic_graph": "current",
            "live_operational_sources": "request_time",
            "snapshot_materialization": "disabled",
        },
    }
    return envelope(
        payload,
        evidence=Evidence(
            source_engine="semantic.OperationalTwinComposer",
            source_table="live_operational_twin",
            resource_id=resource_id,
            confidence=CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
        knowledge_version=str(data.get("version") or data.get("current_version") or ""),
        warnings=data.get("warnings", []),
    )


@router.get("", summary="Query the operational digital twin")
def query_twin(
    context: Context,
    scope: ReadScope,
    q: str = Query("", max_length=512, description="Optional entity or property search text"),
) -> dict[str, Any]:
    data = _composer(context, scope).query(q)
    return _respond(data, scope)


@router.get("/graph", summary="Current operational twin graph")
def graph(context: Context, scope: ReadScope) -> dict[str, Any]:
    data = _composer(context, scope).snapshot()
    return _respond(data, scope)


@router.get("/timeline", summary="Operational twin temporal history")
def timeline(context: Context, scope: ReadScope) -> dict[str, Any]:
    snapshot = _composer(context, scope).snapshot()
    data = {
        "version": snapshot["version"],
        "observed_at": snapshot["observed_at"],
        "timeline": snapshot["timeline"],
        "change_history": snapshot["temporal"]["change_history"],
        "risk_trend": snapshot["temporal"]["risk_trend"],
        "dependency_evolution": snapshot["temporal"]["dependency_evolution"],
    }
    return _respond(data, scope)


@router.get("/compare", summary="Compare current twin state with the prior revision")
def compare(context: Context, scope: ReadScope) -> dict[str, Any]:
    data = _composer(context, scope).compare()
    return _respond(data, scope)


@router.post("/scenarios", summary="Simulate a twin scenario")
def scenario(
    context: Context,
    scope: ReadScope,
    payload: dict[str, Any] = Body(default_factory=dict),  # noqa: B008 - FastAPI dependency pattern
) -> dict[str, Any]:
    scenario_type = str(payload.get("scenario") or payload.get("scenario_type") or "")
    target = str(payload.get("target") or "")
    data = _composer(context, scope).scenario(scenario_type, target)
    return _respond(data, scope, resource_id=target)


@router.get("/traverse/{resource_id:path}", summary="Traverse resource to business impact")
def traverse(resource_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    data = _composer(context, scope).traverse(resource_id)
    return _respond(data, scope, resource_id=resource_id)


@router.get("/export", summary="Export operational twin state")
def export(context: Context, scope: ReadScope) -> dict[str, Any]:
    data = _composer(context, scope).export()
    return _respond(data, scope)
