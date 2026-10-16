"""Network topology, traffic-flow and design-gap routes.

These front :class:`NetworkIntelligenceService`, which is built from the same
ontology snapshot the semantic layer reads. The service is resolved per request
through a provider callable so a refreshed snapshot is observed without a
restart, and when no provider is registered the routes report the capability as
unavailable rather than returning an empty result the UI would render as "no
network problems" -- a dangerous default for a security-facing view.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from time import perf_counter_ns
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query, Request, Response
from fastapi.routing import APIRoute

from network.design import (
    NetworkDesignPolicy,
    NetworkDesignPolicyDocumentError,
    NetworkDesignPolicyValidationError,
)
from network.flow import FlowQuery
from network.gaps import NetworkGapAnalyzer
from network.rule_engine import (
    SUPPORTED_OPERATORS,
    SUPPORTED_TARGET_NAMES,
    RuleValidationError,
    validate_rule_parameters,
)
from network.service import NetworkIntelligenceService, NetworkScope
from network.topology import TopologyDetail

from ..dependencies import (
    Context,
    Page,
    ReadScope,
    WritePrincipal,
    live_subscription_ids,
)
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope

HANDLER_TIMING_HEADER = "X-AIOPS-Handler-Ms"
_HANDLER_STARTED_STATE = "_aiops_network_topology_started_ns"


def _add_handler_timing_header(response: Response, started_ns: int) -> None:
    """Publish analysis + serialized-response time for the topology route."""
    elapsed_ms = max(0, perf_counter_ns() - started_ns) / 1_000_000
    response.headers[HANDLER_TIMING_HEADER] = f"{elapsed_ms:.3f}"


class _NetworkRoute(APIRoute):
    """Add timing only when an endpoint opts in after dependencies resolve."""

    def get_route_handler(
        self,
    ) -> Callable[[Request], Awaitable[Response]]:
        route_handler = super().get_route_handler()

        async def timed_route_handler(request: Request) -> Response:
            response = await route_handler(request)
            started_ns = getattr(
                request.state,
                _HANDLER_STARTED_STATE,
                None,
            )
            if started_ns is not None:
                _add_handler_timing_header(response, started_ns)
            return response

        return timed_route_handler


router = APIRouter(
    prefix="/api/v1/network",
    tags=["network"],
    route_class=_NetworkRoute,
)

SOURCE_ENGINE = "network.NetworkIntelligenceService"
SOURCE_TABLE = "ontology_entities"


def _service(context: Context, scope: Scope) -> NetworkIntelligenceService:
    subscription_ids = live_subscription_ids(context, scope, default_all=True)
    network_scope = _network_scope(scope)
    if context.hybrid_network_provider is not None:
        if not subscription_ids:
            raise ApiError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Network data is unavailable because no active subscription "
                "connection matches the authorized scope",
                {"capability": "network", "provider_state": "unavailable"},
            )
        if not scope.values("subscription"):
            network_scope = replace(
                network_scope,
                subscription_ids=tuple(subscription_ids),
            )
        if subscription_ids:
            try:
                service = context.hybrid_network_provider(subscription_ids)
            except (OSError, RuntimeError, ValueError) as exc:
                raise ApiError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    "Live network observations are unavailable",
                    {"capability": "network", "provider_state": "unavailable"},
                ) from exc
            return service.scoped(network_scope)
    service = context.resolve_provider("network")
    return service.scoped(network_scope)


def _network_scope(scope: Scope) -> NetworkScope:
    """Projects the platform scope onto the network engine's own filter.

    The API scope is the authorization boundary; this keeps the two aligned so
    a caller can never widen their view by choosing a network route.
    """
    return NetworkScope.from_dimensions(scope.dimensions)


def _evidence(
    service: NetworkIntelligenceService,
    *,
    resource_id: str = "",
    connection: str = "",
    confidence: str = CONFIDENCE_HIGH,
) -> Evidence:
    """Stamps the snapshot's observation time so freshness is banded honestly.

    When the ingested rows carry no observation stamp the timestamp stays
    empty, which the envelope reports as unknown freshness rather than fresh.
    """
    return Evidence(
        source_engine=SOURCE_ENGINE,
        source_table=SOURCE_TABLE,
        resource_id=resource_id,
        subscription_connection=connection,
        confidence=confidence,
        timestamp=service.snapshot.observed_at,
    )


@router.get("/topology", summary="Hub-spoke network topology")
def network_topology(
    context: Context,
    scope: ReadScope,
    detail: Annotated[TopologyDetail, Query()] = "full",
    request: Request = None,
) -> dict[str, Any]:
    if request is not None:
        setattr(request.state, _HANDLER_STARTED_STATE, perf_counter_ns())
    service = _service(context, scope)
    analysis = service.analyze()
    topology = analysis.topology.to_dict(detail=detail)
    summary = analysis.summary()
    if service.topology_build_duration_ms is not None:
        summary["topology_build_duration_ms"] = (
            service.topology_build_duration_ms
        )
    return envelope(
        {
            "topology": topology,
            "summary": summary,
        },
        # Topology is stitched from observed peering resources, so it is a
        # direct reading of the estate rather than an inference.
        evidence=_evidence(service),
        scope=scope.to_dict(),
    )


def _topology_resource_details(
    service: NetworkIntelligenceService,
    resource_id: str,
) -> tuple[str, str, list[dict[str, Any]]]:
    """Resolve drill-down data only from the already-scoped snapshot."""
    requested_id = f"/{resource_id.lstrip('/')}".casefold()
    snapshot = service.snapshot

    for nsg in snapshot.nsgs:
        if nsg.resource_id == requested_id:
            return (
                nsg.resource_id,
                "rules",
                [rule.to_dict() for rule in nsg.ordered_rules()],
            )
    for table in snapshot.route_tables:
        if table.resource_id == requested_id:
            return (
                table.resource_id,
                "routes",
                [route.to_dict() for route in table.routes],
            )
    for collection in snapshot.firewall_collections:
        if collection.resource_id == requested_id:
            return (
                collection.resource_id,
                "rules",
                [rule.to_dict() for rule in collection.rules],
            )
    for policy in snapshot.firewall_policies:
        if policy.resource_id == requested_id:
            collections = [
                collection.to_dict()
                for collection in snapshot.firewall_collections
                if collection.policy_id == policy.resource_id
            ]
            return policy.resource_id, "rule_collections", collections
    for firewall in snapshot.firewalls:
        if firewall.resource_id != requested_id:
            continue
        collections = [
            collection
            for collection in snapshot.firewall_collections
            if collection.firewall_id == firewall.resource_id
            or (
                firewall.policy_id
                and collection.policy_id == firewall.policy_id
            )
        ]
        rules = {
            rule.resource_id: rule.to_dict()
            for collection in collections
            for rule in collection.rules
        }
        return (
            firewall.resource_id,
            "rules",
            [rules[key] for key in sorted(rules)],
        )
    return requested_id, "", []


@router.get(
    "/topology/resources/{resource_id:path}/details",
    summary="Paginated topology resource details",
)
def topology_resource_details(
    resource_id: str,
    context: Context,
    scope: ReadScope,
    page: Page,
) -> dict[str, Any]:
    """Return summary-withheld details without bypassing request scope."""
    service = _service(context, scope)
    canonical_id, detail_type, items = _topology_resource_details(
        service,
        resource_id,
    )
    visible = items[page.offset : page.offset + page.limit]
    coverage = {
        "total": len(items),
        "returned": len(visible),
        "truncated": len(visible) < len(items),
    }
    return envelope(
        {
            "resource_id": canonical_id,
            "detail_type": detail_type,
            "items": visible,
            "coverage": coverage,
        },
        evidence=_evidence(service, resource_id=canonical_id),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(items)),
    )


def _hub_dependents(
    vnet_id: str,
    context: Context,
    scope: Scope,
) -> dict[str, Any]:
    """Resolve one exact hub identity against the authorized snapshot."""
    service = _service(context, scope)
    canonical_vnet_id = f"/{vnet_id.lstrip('/')}".casefold()
    if not any(
        vnet.resource_id == canonical_vnet_id
        for vnet in service.snapshot.vnets
    ):
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Hub VNet not found",
            details={"vnet_id": canonical_vnet_id},
        )
    result = service.hub_dependents(canonical_vnet_id)
    return envelope(
        result,
        evidence=_evidence(service, resource_id=canonical_vnet_id),
        scope=scope.to_dict(),
    )


@router.get("/topology/hubs/dependents", summary="Hub dependents")
def hub_dependents_query(
    context: Context,
    scope: ReadScope,
    vnet_id: Annotated[str, Query(min_length=1, max_length=2048)],
) -> dict[str, Any]:
    """Answers "what depends on the hub?" with a slash-safe query id."""
    return _hub_dependents(vnet_id, context, scope)


@router.get(
    "/topology/hubs/{vnet_id:path}/dependents",
    summary="Hub dependents (legacy path)",
)
def hub_dependents(vnet_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    """Compatibility adapter for clients using the legacy path contract."""
    return _hub_dependents(vnet_id, context, scope)


@router.get("/firewall-bypass", summary="Firewall-inspection bypass findings")
def firewall_bypass(context: Context, scope: ReadScope) -> dict[str, Any]:
    """Return route and public-IP findings that can bypass firewall inspection."""
    service = _service(context, scope)
    gaps = service.firewall_bypass_spokes()
    return envelope(
        {"gaps": [gap.to_dict() for gap in gaps], "count": len(gaps)},
        # A bypass is inferred from the absence of a default route to the
        # firewall, not from observed traffic.
        evidence=_evidence(service, confidence=CONFIDENCE_MEDIUM),
        scope=scope.to_dict(),
    )


@router.get("/traffic-flow", summary="Traffic-flow validation")
def traffic_flow(
    context: Context,
    scope: ReadScope,
    source: Annotated[str, Query(min_length=1, max_length=512)],
    destination: Annotated[str, Query(min_length=1, max_length=512)],
    port: Annotated[int | None, Query(ge=1, le=65535)] = None,
    protocol: Annotated[str, Query(max_length=16)] = "Tcp",
    environment_scope: Annotated[str, Query(max_length=128)] = "",
) -> dict[str, Any]:
    """Answers "can UAT reach PROD, and which rules decide it?".

    A verdict of ``indeterminate`` is a real answer: it means an endpoint or a
    higher-priority rule could not be resolved, so no claim is made in either
    direction. Callers must not read it as "allowed".
    """
    service = _service(context, scope)
    result = service.validate_flow(
        FlowQuery(
            source=source,
            destination=destination,
            port=port,
            protocol=protocol,
            environment_scope=environment_scope,
        )
    )
    return envelope(
        result.to_dict(),
        evidence=_evidence(
            service,
            resource_id=source,
            # The path is evaluated from configuration, never from flow logs,
            # so it describes what the rules permit rather than what happened.
            confidence=CONFIDENCE_HIGH if not result.unknowns else CONFIDENCE_MEDIUM,
        ),
        scope=scope.to_dict(),
    )


@router.get("/gaps", summary="Intended-design gap detection")
def network_gaps(
    context: Context,
    scope: ReadScope,
    page: Page,
    severity: Annotated[
        Literal["critical", "high", "medium", "low"] | None, Query()
    ] = None,
    category: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, Any]:
    service = _service(context, scope)
    analysis = service.analyze()
    gaps = [
        gap
        for gap in analysis.gaps
        if (severity is None or gap.severity == severity)
        and (category is None or gap.category == category)
    ]
    visible = gaps[page.offset : page.offset + page.limit]
    coverage = {
        "total": len(gaps),
        "returned": len(visible),
        "truncated": len(visible) < len(gaps),
    }
    return envelope(
        {
            "gaps": [gap.to_dict() for gap in visible],
            # An absent design policy is a reportable state, not an error: it
            # means conformance gaps cannot be assessed, only structural ones.
            "intended_design_declared": analysis.policy.is_declared,
            "summary": analysis.summary(),
            "coverage": coverage,
        },
        evidence=_evidence(service, confidence=CONFIDENCE_MEDIUM),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(gaps)),
        warnings=(
            [
                (
                    f"Showing {len(visible)} of {len(gaps)} inspection gaps; "
                    "use pagination for the complete result"
                )
            ]
            if coverage["truncated"]
            else []
        ),
        automatic_truncation_warning=False,
    )


@router.get("/rule-findings", summary="Firewall and NSG tightening analysis")
def rule_findings(
    context: Context,
    scope: ReadScope,
    page: Page,
    severity: Annotated[
        Literal["critical", "high", "medium", "low"] | None, Query()
    ] = None,
    category: Annotated[str | None, Query(max_length=128)] = None,
) -> dict[str, Any]:
    service = _service(context, scope)
    analysis = service.analyze()
    findings = [
        finding
        for finding in analysis.rule_findings
        if (severity is None or finding.severity == severity)
        and (category is None or finding.category == category)
    ]
    visible = findings[page.offset : page.offset + page.limit]
    coverage = {
        "total": len(findings),
        "returned": len(visible),
        "truncated": len(visible) < len(findings),
    }
    flow_logs_analyzed = (
        service.flow_log_provenance.get("state") == "analyzed"
    )
    return envelope(
        {
            "findings": [finding.to_dict() for finding in visible],
            "summary": analysis.summary(),
            "coverage": coverage,
        },
        # Structural findings remain configuration-derived. When Traffic
        # Analytics evidence was consumed, observation-backed findings carry
        # their bounded-window basis and the route can report direct evidence.
        evidence=_evidence(
            service,
            confidence=(
                CONFIDENCE_HIGH if flow_logs_analyzed else CONFIDENCE_MEDIUM
            ),
        ),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(findings)),
        warnings=(
            [
                (
                    f"Showing {len(visible)} of {len(findings)} rule findings; "
                    "use pagination for the complete result"
                )
            ]
            if coverage["truncated"]
            else []
        ),
        automatic_truncation_warning=False,
    )


@router.get("/summary", summary="Network intelligence summary")
def network_summary(context: Context, scope: ReadScope) -> dict[str, Any]:
    """The dashboard card payload."""
    service = _service(context, scope)
    analysis = service.analyze()
    return envelope(
        analysis.summary(),
        evidence=_evidence(service),
        scope=scope.to_dict(),
    )


def _policy_payload(policy: NetworkDesignPolicy) -> tuple[dict[str, Any], list[str]]:
    """Serialises a policy, marking which rules the analyzer actually checks.

    Evaluability is a property of the analyzer, not of the stored policy, so
    it is annotated at the edge. Without it the UI cannot distinguish a rule
    that is enforced from one that is merely stored.

    A rule is evaluated if it is either a built-in with a registered check or
    a declarative rule the engine can run. Declarative rules that fail
    validation are reported as ``invalid`` with the parse error, rather than
    as ``evaluated: false`` -- a broken rule and an unimplemented one need
    different fixes, and collapsing them hides which one you have.
    """
    evaluable = set(NetworkGapAnalyzer.evaluable_rule_ids())
    payload = policy.to_dict()

    annotated: list[dict[str, Any]] = []
    for rule in payload.get("rules", []):
        entry = dict(rule)
        parameters = entry.get("parameters")
        declarative = isinstance(parameters, dict) and bool(parameters.get("assert"))
        error = ""
        if declarative:
            try:
                validate_rule_parameters(parameters)
            except RuleValidationError as exc:
                error = str(exc)
        entry["declarative"] = declarative
        entry["evaluated"] = entry.get("rule_id") in evaluable or (
            declarative and not error
        )
        if error:
            entry["invalid_reason"] = error
        annotated.append(entry)

    payload["rules"] = annotated
    unevaluated = [
        rule["rule_id"]
        for rule in annotated
        if rule.get("enabled") and not rule["evaluated"]
    ]
    payload["unevaluated_rule_ids"] = unevaluated
    payload["invalid_rule_ids"] = [
        rule["rule_id"] for rule in annotated if rule.get("invalid_reason")
    ]
    payload["supported_targets"] = list(SUPPORTED_TARGET_NAMES)
    payload["supported_operators"] = list(SUPPORTED_OPERATORS)
    return payload, unevaluated


@router.get("/policy", summary="Read the rule-based network design policy")
def read_policy(context: Context, scope: ReadScope) -> dict[str, Any]:
    """The editable rule set gap analysis is checked against.

    Rules ship with sensible defaults (e.g. "internet egress must traverse
    the firewall") so a deployment with no store configured still reports a
    usable policy rather than an empty one.
    """
    store = context.network_policy_store
    try:
        policy = store.read() if store is not None else NetworkDesignPolicy()
    except NetworkDesignPolicyDocumentError as exc:
        raise _corrupt_policy_error() from exc
    # Whether a rule is actually inspected is a property of the analyzer, not
    # of the stored policy. Surfacing it here stops the UI from claiming a
    # custom rule is enforced when nothing evaluates it.
    payload, unevaluated = _policy_payload(policy)
    invalid = payload.get("invalid_rule_ids") or []
    return envelope(
        payload,
        evidence=Evidence(
            source_engine="network.NetworkDesignPolicyStore",
            source_table="network_design_policy",
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
        warnings=(
            []
            if store is not None
            else ["Policy is not persisted in this deployment; defaults are shown"]
        )
        + (
            [
                f"{len(unevaluated)} enabled rule(s) have no gap check and are not "
                "evaluated: " + ", ".join(unevaluated)
            ]
            if unevaluated
            else []
        )
        + (
            [
                f"{len(invalid)} rule(s) could not be parsed and did not run: "
                + ", ".join(invalid)
            ]
            if invalid
            else []
        ),
    )


def _corrupt_policy_error() -> ApiError:
    return ApiError(
        ErrorCode.PROVIDER_UNAVAILABLE,
        "Stored network policy is unavailable because its document is invalid",
        {"capability": "network_policy", "provider_state": "degraded"},
    )


def _declarative_rule_errors(
    changes: Mapping[str, Any],
) -> list[tuple[Mapping[str, Any], str]]:
    """Validation errors for declarative rule bodies in a proposed change.

    Operates on the raw request rather than a stored policy so a bad rule can
    be rejected before it is written.
    """
    rules = changes.get("rules")
    if not isinstance(rules, (list, tuple)):
        return []
    errors: list[tuple[Mapping[str, Any], str]] = []
    for rule in rules:
        if not isinstance(rule, Mapping):
            continue
        parameters = rule.get("parameters")
        if not isinstance(parameters, Mapping) or not parameters.get("assert"):
            continue
        try:
            validate_rule_parameters(parameters)
        except RuleValidationError as exc:
            errors.append((rule, str(exc)))
    return errors


@router.patch("/policy", summary="Update the rule-based network design policy")
def update_policy(
    principal: WritePrincipal,
    context: Context,
    scope: ReadScope,
    changes: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    store = context.network_policy_store
    if store is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Policy cannot be updated because no policy store is configured",
            {"capability": "network_policy", "provider_state": "unavailable"},
        )
    # Validate declarative rule bodies BEFORE persisting. Storing a rule and
    # then returning an error would leave the estate policy holding something
    # the caller was told was rejected.
    broken = [
        (str(rule.get("rule_id") or rule.get("id") or "?"), reason)
        for rule, reason in _declarative_rule_errors(changes)
    ]
    if broken:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "One or more rules are not valid: "
            + "; ".join(f"{rule_id}: {reason}" for rule_id, reason in broken),
            {"invalid_rule_ids": [rule_id for rule_id, _ in broken]},
        )
    try:
        policy = store.update(changes)
    except NetworkDesignPolicyDocumentError as exc:
        raise _corrupt_policy_error() from exc
    except NetworkDesignPolicyValidationError as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST, str(exc), {"section": sorted(changes)}
        ) from exc
    return envelope(
        _policy_payload(policy)[0],
        evidence=Evidence(
            source_engine="network.NetworkDesignPolicyStore",
            source_table="network_design_policy",
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
    )


@router.post("/policy/preview", summary="Preview a proposed network design policy")
def preview_policy(
    principal: WritePrincipal,
    context: Context,
    scope: ReadScope,
    changes: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Evaluate proposed policy changes against the current observed topology."""
    store = context.network_policy_store
    if store is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Policy preview is unavailable because no policy store is configured",
            {"capability": "network_policy", "provider_state": "unavailable"},
        )
    try:
        policy = store.preview(changes)
    except NetworkDesignPolicyDocumentError as exc:
        raise _corrupt_policy_error() from exc
    except NetworkDesignPolicyValidationError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc), {"section": sorted(changes)}) from exc
    service = _service(context, scope)
    preview_service = NetworkIntelligenceService(
        service.snapshot,
        policy=policy,
        semantic_relationships=service.semantic_relationships,
        flow_observations=service.flow_observations,
        peer_resolutions=service.peer_resolutions,
    )
    analysis = preview_service.analyze()
    payload = _policy_payload(policy)[0]
    invalid = payload.get("invalid_rule_ids") or []
    return envelope(
        {
            "policy": payload,
            "gaps": [gap.to_dict() for gap in analysis.gaps],
            "summary": analysis.summary(),
        },
        evidence=_evidence(service, confidence=CONFIDENCE_MEDIUM),
        scope=scope.to_dict(),
        # Preview is the dry-run seam: a rule author should see that a rule
        # is malformed here, before saving, rather than after.
        warnings=(
            [
                f"{len(invalid)} rule(s) could not be parsed and produced no gaps: "
                + ", ".join(invalid)
            ]
            if invalid
            else []
        ),
    )
