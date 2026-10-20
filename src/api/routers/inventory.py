"""Scope-enforced OS inventory endpoints."""

from __future__ import annotations

import hmac
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Query, Request, Response

from intelligence.inventory.eol_repository import (
    CatalogRevisionConflict,
    DuplicateCatalogConfirmation,
)
from intelligence.inventory.eol_review import normalize_os_key
from intelligence.inventory.exports import (
    ExportCancel,
    ExportCreate,
    InventoryExportStore,
)
from intelligence.inventory.mapping_repository import (
    MappingNotFound,
    MappingRevisionConflict,
    MappingStatusConflict,
)
from intelligence.inventory.narrative import build_inventory_narrative
from intelligence.inventory.public_projection import (
    public_inventory_asset as _public_asset,
)
from intelligence.inventory.read_port import InventoryReadPort
from intelligence.inventory.service import InventoryService
from storage.onelake_documents import DocumentConflictError

from .. import inventory_refresh_runs
from ..dependencies import Context, CurrentPrincipal, OperatePrincipal, Page, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope
from ..models import (
    EOLConfirmationRequest,
    SoftwareMappingDecisionRequest,
    SoftwareMappingPathDecisionRequest,
)

router = APIRouter(prefix="/api/v1", tags=["inventory"])
_GROUP_KEY = re.compile(r"^[^|/\\]{1,120}\|[^|/\\]{1,120}$")
_PAAS_GROUP_KEY = re.compile(r"^[^|/\\]{1,160}\|[^|/\\]{1,120}\|[^|/\\]{1,120}$")


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


def _resource_evidence(service: InventoryService) -> Evidence:
    return Evidence(
        source_engine="intelligence.inventory.InventoryService",
        source_table="inventory/resource_observations",
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


def _authorize_trigger(request: Request) -> None:
    """Authorize a system-to-system refresh caller via the shared trigger secret."""

    expected = os.environ.get("AIOPS_REFRESH_TRIGGER_SECRET", "").strip()
    if not expected:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "AIOPS_REFRESH_TRIGGER_SECRET is not configured for this deployment",
            {"capability": "inventory", "provider_state": "unconfigured"},
        )
    provided = request.headers.get("x-aiops-trigger-secret", "")
    if not hmac.compare_digest(provided, expected):
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Invalid trigger secret")


@router.post(
    "/inventory/refresh",
    status_code=202,
    summary="Trigger an inventory acquisition/publication run",
)
def trigger_inventory_refresh(request: Request, response: Response) -> dict[str, Any]:
    """Start an inventory refresh across all registered subscriptions.

    Inventory remains the sole owner of acquisition/normalization/publication;
    this endpoint only exposes an authenticated trigger over
    `run_inventory_refresh_all_connections`, so a Fabric Data Pipeline (Web
    activity + schedule trigger) can invoke it as a real, schedulable
    Fabric-native artifact without duplicating acquisition or normalization
    logic inside Fabric. Every active `SubscriptionConnection` in the
    onboarding registry is refreshed independently (one subscription's
    failure does not block the others), then merged into one deduplicated
    snapshot before publishing to Fabric once.

    Authenticated separately from the Entra principal flow via a shared
    secret (``AIOPS_REFRESH_TRIGGER_SECRET``), because a Fabric Web activity
    calling this endpoint on a schedule is a system-to-system caller, not an
    interactive/gateway-authenticated user -- minting and refreshing an Entra
    app-role token for that one activity adds real operational fragility for
    no security benefit over a dedicated, rotatable trigger secret.

    The run executes on a worker thread and this returns ``202`` immediately
    with a ``run_id``. A full refresh outlives every HTTP client -- Container
    Apps terminates an ingress request at a fixed 240 seconds -- so a
    synchronous response could never report success, and the hourly Fabric
    pipeline failed with a stream timeout on every otherwise-healthy run.
    Poll ``GET /inventory/refresh/{run_id}`` for the outcome. Runs are
    single-flight: a trigger arriving while one is still publishing adopts
    that run rather than stacking a second acquisition on top of it -- and
    still answers ``202`` with that run's ``Location``, so an overlapping
    scheduled run waits on the in-flight outcome instead of succeeding early.
    """
    _authorize_trigger(request)

    config_path = os.environ.get("AIOPS_ARG_CONFIG", "").strip()
    if not config_path:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "AIOPS_ARG_CONFIG is not configured for this deployment",
            {"capability": "inventory", "provider_state": "unconfigured"},
        )
    fabric_config_path = os.environ.get("AIOPS_FABRIC_CONFIG", "").strip()

    def _run() -> dict[str, Any]:
        from api.inventory_orchestration import (
            run_inventory_refresh_all_connections,
        )

        return run_inventory_refresh_all_connections(
            config_path,
            fabric_config_path=fabric_config_path,
        )

    run, adopted = inventory_refresh_runs.start_refresh(_run)
    _set_poll_headers(request, response, run["run_id"])
    return {**run, "adopted_existing_run": adopted}


_TERMINAL_STATUS_CODES = {"succeeded": 200, "failed": 500}
_POLL_INTERVAL_SECONDS = "30"


def _set_poll_headers(request: Request, response: Response, run_id: str) -> None:
    """Advertise the asynchronous request-reply contract a Web activity follows.

    A Fabric/ADF Web activity that receives ``202`` with a ``Location`` header
    keeps polling that URL until it stops answering ``202``, and then takes the
    final status code as the activity outcome. That is what lets the pipeline
    report the *real* refresh result instead of succeeding on the trigger.

    The URL is resolved from the status route rather than the current request
    path, so polling an alias such as ``/inventory/refresh/latest`` advertises
    the run's own canonical URL instead of appending the id to the alias.
    """

    target = request.url_for("inventory_refresh_status", run_id=run_id)
    proto = request.headers.get("x-forwarded-proto", target.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", target.netloc))
    response.headers["Location"] = f"{proto}://{host}{target.path}"
    response.headers["Retry-After"] = _POLL_INTERVAL_SECONDS


def _trigger_authorized(request: Request) -> bool:
    try:
        _authorize_trigger(request)
    except ApiError:
        return False
    return True


@router.get(
    "/inventory/refresh/{run_id}",
    summary="Inventory refresh run status",
)
def inventory_refresh_status(request: Request, response: Response, run_id: str) -> dict[str, Any]:
    """Report a background refresh run's status, result or failure.

    Answers ``202`` while the run is in progress (re-advertising ``Location``),
    ``200`` once it succeeds and ``500`` once it fails, so a polling Web
    activity fails exactly when the refresh fails.

    A run id is an unguessable UUID that only the authorized trigger ever
    learns, so it doubles as a capability for status polling: Web activity
    async polling is not guaranteed to replay the trigger's custom headers.
    Without the trigger secret only the lifecycle fields are returned; the
    result payload, error detail and the ``latest``/``current`` aliases still
    require it.
    """

    authorized = _trigger_authorized(request)
    if run_id in {"latest", "current"}:
        _authorize_trigger(request)
        run = inventory_refresh_runs.latest_run()
    else:
        run = inventory_refresh_runs.get_run(run_id)
    if run is None:
        if not authorized:
            _authorize_trigger(request)
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Unknown inventory refresh run",
            {"capability": "inventory", "run_id": run_id},
        )
    if run["status"] == "running":
        response.status_code = 202
        _set_poll_headers(request, response, run["run_id"])
    else:
        response.status_code = _TERMINAL_STATUS_CODES.get(run["status"], 200)
    if not authorized:
        return {key: run[key] for key in ("run_id", "status", "started_at", "finished_at", "duration_seconds")}
    return run


@router.get("/inventory/os", summary="Grouped operating-system inventory")
def os_inventory(
    context: Context, scope: ReadScope, page: Page,
    q: str = Query("", max_length=256),
    os_name: str = Query("", max_length=120),
    os_version: str = Query("", max_length=120),
    source_type: str = Query("", pattern=r"^(|azure_vm|arc|logs)$"),
    lifecycle: str = Query("", pattern=r"^(|expired|expiring|supported|review)$"),
) -> dict[str, Any]:
    """Return server-filtered scoped OS groups with complete group facets."""
    service = _service(context)
    result = service.collection(scope, offset=page.offset, limit=page.limit, query=q, filters={
        "os_name": os_name, "os_version": os_version, "source_type": source_type, "lifecycle": lifecycle,
    })
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
def software_inventory(
    context: Context, scope: ReadScope, page: Page,
    q: str = Query("", max_length=256),
    software_name: str = Query("", max_length=256),
    publisher: str = Query("", max_length=256),
    source_type: str = Query("", pattern=r"^(|azure_vm|arc|logs|unlinked)$"),
) -> dict[str, Any]:
    """Return authorized installation-group facets and filters before paging."""
    service = _service(context)
    result = service.software_collection(scope, offset=page.offset, limit=page.limit, query=q, filters={
        "software_name": software_name, "publisher": publisher, "source_type": source_type,
    })
    return envelope(
        result["data"],
        evidence=_software_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=result["data"]["query_version"],
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )


@router.get(
    "/inventory/narrative",
    summary="Narrate scoped inventory risk aggregates",
)
def inventory_narrative(context: Context, scope: ReadScope) -> dict[str, Any]:
    """Return deterministic inventory facts plus optional Foundry narration."""
    service = _service(context)
    result = build_inventory_narrative(service, scope, context.foundry_agent())
    return envelope(
        result["data"],
        evidence=_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=service.query_version,
        warnings=result["warnings"],
    )


@router.get("/inventory/paas", summary="Grouped PaaS resource inventory")
def paas_inventory(
    context: Context, scope: ReadScope, page: Page,
    q: str = Query("", max_length=256),
    provider: str = Query("", max_length=256),
    resource_type: str = Query("", max_length=256),
    sku_tier: str = Query("", max_length=256),
) -> dict[str, Any]:
    """Return authorized type/SKU/tier groups, facets and matched summaries."""
    service = _service(context)
    result = service.paas_collection(scope, offset=page.offset, limit=page.limit, query=q, filters={
        "provider": provider, "resource_type": resource_type, "sku_tier": sku_tier,
    })
    return envelope(
        result["data"],
        evidence=_resource_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=result["data"]["query_version"],
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )


@router.get("/inventory/paas/{group_key:path}", summary="Resources in a PaaS inventory group")
def paas_inventory_detail(
    group_key: str, context: Context, scope: ReadScope, page: Page
) -> dict[str, Any]:
    if not _PAAS_GROUP_KEY.fullmatch(group_key):
        raise ApiError(ErrorCode.INVALID_REQUEST, "Invalid PaaS inventory group key")
    service = _service(context)
    result = service.paas_detail(group_key, scope, offset=page.offset, limit=page.limit)
    if result is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No PaaS inventory group matches this scope")
    return envelope(
        {
            **result["data"],
            "resources": [_public_asset(row) for row in result["data"]["resources"]],
        },
        evidence=_resource_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=result["data"]["query_version"],
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )


@router.get("/inventory/resources", summary="Scoped cross-family inventory resources")
def inventory_resources(
    context: Context,
    scope: ReadScope,
    page: Page,
    family: str | None = Query(None, max_length=64),
    resource_type: str | None = Query(None, max_length=256),
    resource_group: str | None = Query(None, max_length=256),
    q: str | None = Query(None, max_length=256),
) -> dict[str, Any]:
    """Filter the complete authorized published projection before pagination."""
    service = _service(context)
    result = InventoryReadPort(service).list_resources(
        scope,
        offset=page.offset,
        limit=page.limit,
        family=family,
        resource_type=resource_type,
        resource_group=resource_group,
        query=q,
    )
    family_counts = {item["value"]: item["count"] for item in result["facets"]["family"]}
    return envelope(
        {
            "resources": [_public_asset(row) for row in result["resources"]],
            "family_availability": {
                family: {**status, "row_count": family_counts.get(family, 0)}
                for family, status in result["family_availability"].items()
            },
            "requested_scope": scope.to_dict(),
            "query_version": service.query_version,
            "generation_id": service.generation_id,
            "facets": result["facets"],
            "represented_count": result["represented_count"],
            "aggregate_basis": "authorized_published_observations",
        },
        evidence=_resource_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=service.query_version,
        warnings=result["warnings"],
        pagination=page.to_dict(result["total"]),
    )


@router.get("/inventory/asset", summary="Resolve an exact authorized asset identity")
def inventory_asset(
    context: Context,
    scope: ReadScope,
    resource_id: str = Query(..., min_length=1, max_length=2048),
) -> dict[str, Any]:
    """Expose only normalized inventory fields, not raw provider payloads."""
    if any(ord(char) < 32 or ord(char) == 127 for char in resource_id):
        raise ApiError(ErrorCode.INVALID_REQUEST, "Invalid resource identity")
    service = _service(context)
    row = InventoryReadPort(service).get_resource(scope, resource_id)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No inventory asset matches this scope")
    return envelope(
        {"resource": _public_asset(row), "generation_id": service.generation_id, "query_version": service.query_version},
        evidence=_resource_evidence(service),
        scope=scope.to_dict(),
        knowledge_version=service.query_version,
    )


@contextmanager
def _export_store(context: Context) -> Iterator[InventoryExportStore]:
    store = context.inventory_export_store
    if store is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Durable inventory export storage is unavailable",
        )
    try:
        yield store
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, str(exc)) from exc


def _export_envelope(data: dict[str, Any], scope: ReadScope) -> dict[str, Any]:
    manifest = data.get("manifest") or data.get("export") or {}
    return envelope(
        data,
        scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="inventory.captured_export",
            source_table="inventory/resource_observations",
            timestamp=manifest.get("observed_at", ""),
            confidence="high" if manifest else "unknown",
        ),
        knowledge_version=manifest.get("query_version", ""),
    )


@router.post(
    "/inventory/exports",
    status_code=201,
    summary="Capture a bounded generation-pinned inventory export",
)
def create_inventory_export(
    payload: ExportCreate,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
) -> dict[str, Any]:
    """Capture one authorized provider instance, with no background job or live-page mixing."""
    with _export_store(context) as store:
        service = _service(context)
        if (
            not service.generation_id
            or service.generation_id != payload.expected_generation_id
        ):
            raise ApiError(
                ErrorCode.CONFLICT,
                "Inventory generation changed or is unreported; reload before capturing",
            )
        rows = service.resources(scope, limit=None)["data"]["resources"]
        manifest = store.create(
            principal.subject,
            scope.to_dict(),
            generation_id=service.generation_id,
            query_version=service.query_version,
            observed_at=service.observed_at,
            rows=rows,
        )
    return _export_envelope({"export": manifest}, scope)


@router.get(
    "/inventory/exports/current",
    summary="Find this principal's exact-scope export capture",
)
def current_inventory_export(
    context: Context, principal: CurrentPrincipal, scope: ReadScope
) -> dict[str, Any]:
    """Recover a durable capture after refresh, without requiring the active provider."""
    with _export_store(context) as store:
        manifest = store.current(principal.subject, scope.to_dict())
    return _export_envelope({"export": manifest}, scope)


@router.get(
    "/inventory/exports/{export_id}/batches",
    summary="Read an immutable inventory export batch",
)
def inventory_export_batch(
    export_id: str,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
    offset: int = Query(0, ge=0, le=49_999),
) -> dict[str, Any]:
    """Reauthorize exact caller scope for every bounded batch, including retries."""
    with _export_store(context) as store:
        batch = store.batch(principal.subject, scope.to_dict(), export_id, offset)
    return _export_envelope(batch, scope)


@router.post(
    "/inventory/exports/{export_id}/cancel",
    summary="Cancel an export and remove its captured rows",
)
def cancel_inventory_export(
    export_id: str,
    payload: ExportCancel,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
) -> dict[str, Any]:
    """Cancel only the reviewed revision; previously downloaded files cannot be revoked."""
    with _export_store(context) as store:
        manifest = store.cancel(
            principal.subject, scope.to_dict(), export_id, payload.expected_revision
        )
    return _export_envelope({"export": manifest}, scope)


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
