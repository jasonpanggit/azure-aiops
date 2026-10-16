"""Operational digital twin routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Path, Query
from pydantic import ValidationError

from network.service import NetworkScope
from semantic.operational_twin import OperationalTwinComposer
from semantic.twin_history import (
    TwinCapture,
    TwinCaptureRemoval,
    TwinCaptureRequest,
    TwinHistoryStore,
    capture_projection,
    compare_captures,
)
from storage.onelake_documents import DocumentConflictError

from ..dependencies import (
    Context,
    CurrentPrincipal,
    ReadScope,
    WritePrincipal,
    live_subscription_ids,
)
from ..errors import ApiError, ErrorCode
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
        if provider is None:
            errors.append({"source": name, "error": "Unavailable"})
        if generation is not None and hasattr(provider, "for_generation"):
            return provider.for_generation(generation)
        return provider
    except Exception as exc:  # noqa: BLE001 - provider resolution must not crash the endpoint
        errors.append({"source": name, "error": exc.__class__.__name__})
        return None


def _composer(context: Context, scope: Scope) -> OperationalTwinComposer:
    subscription_ids = (
        live_subscription_ids(context, scope, default_all=True)
        if any((
            context.hybrid_network_provider,
            context.hybrid_vulnerability_provider,
            context.hybrid_incident_provider,
            context.hybrid_remediation_provider,
        ))
        else []
    )
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
        network = network.scoped(NetworkScope.from_dimensions(scope.dimensions))
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
    warnings = data.get("warnings", [])
    unavailable_sources = {
        str(warning).split(" unavailable:", 1)[0]
        for warning in warnings
        if " unavailable:" in str(warning)
    }
    unavailable_live_sources = unavailable_sources.intersection(
        {"network", "vulnerability", "incident", "incidents", "remediation"}
    )
    incident_unavailable = bool(
        {"incident", "incidents"}.intersection(unavailable_sources)
    )
    unavailable_live_family_count = (
        int("network" in unavailable_sources)
        + int("vulnerability" in unavailable_sources)
        + int(incident_unavailable)
        + int("remediation" in unavailable_sources)
    )
    payload = {
        **data,
        "composed_at": str(data.get("observed_at") or data.get("exported_at") or ""),
        "live_observed_at": "",
        "source_status": {
            "semantic_graph": (
                "unavailable" if "semantic" in unavailable_sources else "current"
            ),
            "live_operational_sources": (
                "unavailable"
                if unavailable_live_family_count == 4
                else "partial"
                if unavailable_live_sources
                else "request_time"
            ),
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
        warnings=warnings,
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


@router.get("/compare", summary="Report whether a retained comparison baseline is selected")
def compare(context: Context, scope: ReadScope) -> dict[str, Any]:
    data = _composer(context, scope).compare()
    return _respond(data, scope)


@router.post("/scenarios", summary="Review bounded mapped dependencies for a hypothetical scenario")
def scenario(
    context: Context,
    scope: ReadScope,
    payload: dict[str, Any] = Body(default_factory=dict),  # noqa: B008 - FastAPI dependency pattern
) -> dict[str, Any]:
    scenario_type = payload.get("scenario", payload.get("scenario_type", ""))
    target = payload.get("target", "")
    if not isinstance(scenario_type, str) or not isinstance(target, str) or len(target) > 2048:
        raise ApiError(ErrorCode.INVALID_REQUEST, "Provide a scenario name and bounded resource ID")
    try:
        data = _composer(context, scope).scenario(scenario_type, target)
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except LookupError as exc:
        raise ApiError(ErrorCode.NOT_FOUND, str(exc)) from exc
    return _respond(data, scope, resource_id=target)


@router.get("/traverse/{resource_id:path}", summary="Traverse resource to business impact")
def traverse(resource_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    data = _composer(context, scope).traverse(resource_id)
    return _respond(data, scope, resource_id=resource_id)


@router.get("/export", summary="Export operational twin state")
def export(context: Context, scope: ReadScope) -> dict[str, Any]:
    data = _composer(context, scope).export()
    return _respond(data, scope)


def _history_store(context: Context) -> TwinHistoryStore:
    if context.twin_history_store is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Retained Twin snapshots are unavailable")
    return context.twin_history_store


def _history_call(operation: Callable[[], dict]) -> dict:
    try:
        return operation()
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, "Twin history changed; reload before continuing") from exc
    except KeyError as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "Retained Twin snapshot was not found in this personal scope") from exc
    except ValidationError as exc:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Twin projection could not be confirmed against its retained schema") from exc
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except (OSError, RuntimeError, TypeError) as exc:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Twin history operation was not confirmed; reload before retrying") from exc


def _history_response(data: dict, scope: Scope) -> dict:
    return envelope(
        data, scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="semantic.twin_history", source_table="state/twin-history",
            timestamp=str(data.get("updated_at", "")), confidence="unknown",
        ),
        warnings=["Personal exact-scope safe historical projections, not complete raw graphs, source authenticity, verified changes, causal impact or execution authority."],
    )


def _capture_by_id(history: dict, snapshot_id: str) -> TwinCapture:
    row = next((row for row in history["captures"] if row["snapshot_id"] == snapshot_id), None)
    if row is None:
        raise KeyError(snapshot_id)
    return TwinCapture.model_validate(row)


@router.get("/snapshots", summary="Read personal retained Twin snapshots without current providers")
def retained_snapshots(context: Context, principal: CurrentPrincipal, scope: ReadScope) -> dict:
    """Recover immutable safe captures only in the exact personal effective scope."""
    return _history_response(_history_call(
        lambda: _history_store(context).read(principal.subject, scope.to_dict())
    ), scope)


@router.post("/snapshots", status_code=201, summary="Capture a fresh server-composed Twin projection")
def capture_snapshot(
    payload: TwinCaptureRequest, context: Context, principal: WritePrincipal, scope: ReadScope,
) -> dict:
    """Capture fresh evidence, not a caller-supplied graph or an earlier displayed hash."""
    def capture():
        store = _history_store(context)
        history = store.read(principal.subject, scope.to_dict())
        if history["revision"] != payload.expected_revision:
            raise DocumentConflictError("Twin history changed")
        try:
            receipt = capture_projection(_composer(context, scope).snapshot(), scope.to_dict())
        except (KeyError, AttributeError) as exc:
            raise RuntimeError("Current Twin composition could not be retained") from exc
        return store.update(principal.subject, scope.to_dict(), payload.expected_revision, capture=receipt)

    return _history_response(_history_call(capture), scope)


@router.post("/snapshots/remove", summary="Explicitly remove one personal retained Twin snapshot")
def remove_snapshot(
    payload: TwinCaptureRemoval, context: Context, principal: WritePrincipal, scope: ReadScope,
) -> dict:
    """Remove only an identified capture from the reviewed revision; never evict silently."""
    return _history_response(_history_call(lambda: _history_store(context).update(
        principal.subject, scope.to_dict(), payload.expected_revision, remove=payload.snapshot_id,
    )), scope)


@router.get("/snapshots/compare", summary="Compare two selected safe retained Twin captures")
def compare_snapshots(
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
    baseline_id: str = Query(pattern=r"^[0-9a-f]{32}$"),
    candidate_id: str = Query(pattern=r"^[0-9a-f]{32}$"),
) -> dict:
    """Historical differences use no current provider or inferred previous revision."""
    def compare():
        history = _history_store(context).read(principal.subject, scope.to_dict())
        return compare_captures(
            _capture_by_id(history, baseline_id), _capture_by_id(history, candidate_id),
        )

    return _history_response(_history_call(compare), scope)


@router.get("/snapshots/{snapshot_id}/scenarios", summary="Review two scenarios against one immutable retained graph")
def retained_scenarios(
    context: Context, principal: CurrentPrincipal, scope: ReadScope,
    snapshot_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
    left: str = Query(min_length=1, max_length=64),
    right: str = Query(min_length=1, max_length=64),
    target: str = Query(min_length=1, max_length=2048),
) -> dict:
    """Both advisory projections share identical retained evidence and no current provider."""
    def review():
        if left == right:
            raise ValueError("Select two different scenarios")
        history = _history_store(context).read(principal.subject, scope.to_dict())
        capture = _capture_by_id(history, snapshot_id)
        projection = capture.projection
        snapshot = {
            "version": capture.snapshot_sha256,
            "entities": [row.model_dump() for row in projection.entities],
            "relationships": [row.model_dump() for row in projection.relationships],
            "warnings": projection.warnings,
        }
        return {
            "snapshot_id": capture.snapshot_id, "snapshot_sha256": capture.snapshot_sha256,
            "composed_at": projection.composed_at, "authority": "none",
            "left": OperationalTwinComposer.review_snapshot(snapshot, left, target),
            "right": OperationalTwinComposer.review_snapshot(snapshot, right, target),
            "interpretation": (
                "Both reviews use the same bounded mapped neighborhood. Scenario names change review "
                "questions, not measured outcomes. No causal failure propagation, calibrated risk delta, "
                "runtime validation, deployment approval or execution is established."
            ),
        }

    def guarded_review():
        try:
            return review()
        except LookupError as exc:
            raise KeyError("Retained target was not found") from exc

    return _history_response(_history_call(guarded_review), scope)
