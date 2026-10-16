"""Measured component requests and administrator-declared scoped objectives."""

from collections.abc import Callable

import httpx
from fastapi import APIRouter, Query
from pydantic import ValidationError

from intelligence.inventory.service import InventoryService
from operations.service_reliability import (
    ObjectiveRemoval,
    ObjectiveRequest,
    RequestAggregate,
    ServiceObjective,
    ServiceObjectiveStore,
    authorized_components,
    component_id,
    evaluate_requests,
)
from storage.onelake_documents import DocumentConflictError

from ..dependencies import Context, Page, ReadScope, WritePrincipal
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope

router = APIRouter(prefix="/api/v1/service-reliability", tags=["services"])


def _call(operation: Callable[[], dict]) -> dict:
    try:
        return operation()
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, "Service objectives changed; reload before continuing") from exc
    except ValidationError as exc:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Service reliability evidence could not be confirmed") from exc
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    except (OSError, RuntimeError, TypeError, KeyError, httpx.HTTPError) as exc:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Service reliability operation was not confirmed; reload before retrying") from exc


def _store(context: Context) -> ServiceObjectiveStore:
    if context.service_objective_store is None:
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Service objective storage is unavailable")
    return context.service_objective_store


def _inventory(context: Context) -> InventoryService:
    try:
        source = context.resolve_provider("inventory")
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Published component source could not be confirmed") from exc
    if not isinstance(source, InventoryService):
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Published component inventory is unavailable")
    return source


def _component(context: Context, scope: ReadScope, resource_id: str) -> dict:
    identity = component_id(resource_id)
    source = _inventory(context)
    found = next((row for row in authorized_components(source.snapshot.resource_observations, scope)
                  if row["resource_id"] == identity), None)
    if found is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Component is not present in the authorized published inventory")
    return found


def _policy_response(policy: dict, scope: ReadScope) -> dict:
    return envelope(
        policy, scope=scope.to_dict(),
        evidence=Evidence(source_engine="services.declared_objectives", source_table="state/service-objectives",
                          timestamp=policy["updated_at"], confidence="unknown"),
        warnings=["Administrator-declared exact-scope component objectives, not inherited defaults, contractual certification or execution approval."],
    )


@router.get("/components")
def components(context: Context, scope: ReadScope, page: Page, q: str = Query("", max_length=256)) -> dict:
    """Find authorized published App Insights components, not complete service coverage."""
    def read():
        source = _inventory(context)
        rows = authorized_components(source.snapshot.resource_observations, scope)
        if q:
            text = q.casefold()
            rows = [row for row in rows if any(text in row[key].casefold() for key in (
                "resource_id", "resource_name", "business_service",
            ))]
        return envelope(
            {"components": rows[page.offset:page.offset + page.limit]}, pagination=page.to_dict(len(rows)),
            scope=scope.to_dict(), evidence=Evidence(
                source_engine="inventory.declared_component_mapping", source_table="inventory/resource_observations",
                timestamp=source.observed_at, confidence="unknown",
            ),
            warnings=["Observed component tags supply declared service/scope mappings; absent mappings remain unknown. A component is not full-service coverage."],
        )

    return _call(read)


@router.get("/objectives")
def objectives(context: Context, scope: ReadScope) -> dict:
    """Recover shared exact-scope targets without acquiring Inventory or live telemetry."""
    return _policy_response(_call(lambda: _store(context).read(scope.to_dict())), scope)


@router.put("/objectives")
def save_objective(payload: ObjectiveRequest, context: Context, principal: WritePrincipal, scope: ReadScope) -> dict:
    """Authorize a current component mapping before saving an explicit administrator target."""
    def save():
        store = _store(context)
        if store.read(scope.to_dict())["revision"] != payload.expected_revision:
            raise DocumentConflictError("Service objectives changed")
        resource = _component(context, scope, payload.resource_id)
        if not resource["business_service"]:
            raise ValueError("The component needs a declared business-service tag before an objective can be saved")
        objective = ServiceObjective(
            resource_id=resource["resource_id"], business_service=resource["business_service"],
            success_target_basis_points=payload.success_target_basis_points, window_hours=payload.window_hours,
        )
        return store.update(scope.to_dict(), principal.subject, payload.expected_revision, objective=objective)

    return _policy_response(_call(save), scope)


@router.post("/objectives/remove")
def remove_objective(payload: ObjectiveRemoval, context: Context, principal: WritePrincipal, scope: ReadScope) -> dict:
    """Explicitly remove a reviewed objective; do not mutate or query its source resource."""
    def remove():
        try:
            return _store(context).update(
                scope.to_dict(), principal.subject, payload.expected_revision, remove=payload.resource_id,
            )
        except KeyError as exc:
            raise ApiError(ErrorCode.NOT_FOUND, "Service objective was not found in this exact scope") from exc

    return _policy_response(_call(remove), scope)


@router.get("/metrics")
def metrics(context: Context, scope: ReadScope, resource_id: str = Query(min_length=1, max_length=2048)) -> dict:
    """Query current component evidence against one read policy revision, never a default target."""
    def read():
        resource = _component(context, scope, resource_id)
        policy = _store(context).read(scope.to_dict())
        found = next((row for row in policy["objectives"] if row["resource_id"] == resource["resource_id"]), None)
        if found is None:
            raise ApiError(ErrorCode.NOT_FOUND, "No objective is configured for this component in the exact scope")
        objective = ServiceObjective.model_validate(found)
        if resource["business_service"] != objective.business_service:
            raise ApiError(ErrorCode.CONFLICT, "Component service mapping changed; review and replace its objective")
        if context.service_request_metrics is None:
            raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Component request telemetry is unavailable")
        try:
            raw = context.service_request_metrics(resource["resource_id"], objective.window_hours, resource["subscription_connection"])
            if not isinstance(raw, dict) or set(raw) != {"resource_id", "window_started_at", "window_finished_at", "aggregate"}:
                raise ValueError("Request telemetry schema is invalid")
            if raw["resource_id"] != resource["resource_id"]:
                raise ValueError("Request telemetry identity is invalid")
            result = evaluate_requests(
                RequestAggregate.model_validate(raw["aggregate"]), objective,
                started_at=raw["window_started_at"], finished_at=raw["window_finished_at"],
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("Measured request evidence could not be confirmed") from exc
        result["objective_policy_revision"] = policy["revision"]
        return envelope(result, scope=scope.to_dict(), evidence=Evidence(
            source_engine="Azure Monitor Logs", source_table="AppRequests",
            timestamp=raw["aggregate"]["last_observed_at"] or "", resource_id=resource["resource_id"],
            subscription_connection=resource["subscription_connection"], confidence="unknown",
        ), warnings=[result["interpretation"]])

    return _call(read)
