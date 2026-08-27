"""Network topology, traffic-flow and design-gap routes.

These front :class:`NetworkIntelligenceService`, which is built from the same
ontology snapshot the semantic layer reads. The service is resolved per request
through a provider callable so a refreshed snapshot is observed without a
restart, and when no provider is registered the routes report the capability as
unavailable rather than returning an empty result the UI would render as "no
network problems" -- a dangerous default for a security-facing view.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query

from network.design import NetworkDesignPolicy, NetworkDesignPolicyValidationError
from network.flow import FlowQuery
from network.gaps import NetworkGapAnalyzer
from network.service import NetworkIntelligenceService, NetworkScope

from ..dependencies import Context, Page, ReadScope, WritePrincipal
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope

router = APIRouter(prefix="/api/v1/network", tags=["network"])

SOURCE_ENGINE = "network.NetworkIntelligenceService"
SOURCE_TABLE = "ontology_entities"


def _service(context: Context, scope: Scope) -> NetworkIntelligenceService:
    subscription_ids = list(scope.values("subscription"))
    if context.hybrid_network_provider is not None and subscription_ids:
        service = context.hybrid_network_provider(subscription_ids)
    else:
        service = context.resolve_provider("network")
    return service.scoped(_network_scope(scope))


def _network_scope(scope: Scope) -> NetworkScope:
    """Projects the platform scope onto the network engine's own filter.

    The API scope is the authorization boundary; this keeps the two aligned so
    a caller can never widen their view by choosing a network route.
    """
    return NetworkScope(
        connection_ids=tuple(scope.dimensions.get("subscription_connection", ())),
        subscription_ids=tuple(scope.dimensions.get("subscription", ())),
        environments=tuple(scope.dimensions.get("environment", ())),
        business_services=tuple(scope.dimensions.get("business_service", ())),
        applications=tuple(scope.dimensions.get("application", ())),
        owners=tuple(scope.dimensions.get("owner", ())),
    )


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
def network_topology(context: Context, scope: ReadScope) -> dict[str, Any]:
    service = _service(context, scope)
    analysis = service.analyze()
    return envelope(
        {
            "topology": analysis.topology.to_dict(),
            "summary": analysis.summary(),
        },
        # Topology is stitched from observed peering resources, so it is a
        # direct reading of the estate rather than an inference.
        evidence=_evidence(service),
        scope=scope.to_dict(),
    )


@router.get("/topology/hubs/{vnet_id:path}/dependents", summary="Hub dependents")
def hub_dependents(vnet_id: str, context: Context, scope: ReadScope) -> dict[str, Any]:
    """Answers "what depends on the hub?"."""
    service = _service(context, scope)
    result = service.hub_dependents(vnet_id)
    if not result.get("hub_name") and not result.get("dependent_count"):
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Hub VNet not found",
            details={"vnet_id": vnet_id},
        )
    return envelope(
        result,
        evidence=_evidence(service, resource_id=vnet_id),
        scope=scope.to_dict(),
    )


@router.get("/firewall-bypass", summary="Spokes that bypass the hub firewall")
def firewall_bypass(context: Context, scope: ReadScope) -> dict[str, Any]:
    """Answers "which spokes bypass the firewall?"."""
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
    return envelope(
        {
            "gaps": [gap.to_dict() for gap in visible],
            # An absent design policy is a reportable state, not an error: it
            # means conformance gaps cannot be assessed, only structural ones.
            "intended_design_declared": analysis.policy.is_declared,
            "summary": analysis.summary(),
        },
        evidence=_evidence(service, confidence=CONFIDENCE_MEDIUM),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(gaps)),
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
    return envelope(
        {
            "findings": [finding.to_dict() for finding in visible],
            "summary": analysis.summary(),
        },
        # "Unused" and "shadowed" are inferred structurally; no flow logs are
        # ingested, and every finding states that in its own basis.
        evidence=_evidence(service, confidence=CONFIDENCE_MEDIUM),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(findings)),
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
    """
    evaluable = set(NetworkGapAnalyzer.evaluable_rule_ids())
    payload = policy.to_dict()
    payload["rules"] = [
        {**rule, "evaluated": rule.get("rule_id") in evaluable}
        for rule in payload.get("rules", [])
    ]
    unevaluated = [
        rule["rule_id"]
        for rule in payload["rules"]
        if rule.get("enabled") and not rule["evaluated"]
    ]
    payload["unevaluated_rule_ids"] = unevaluated
    return payload, unevaluated


@router.get("/policy", summary="Read the rule-based network design policy")
def read_policy(context: Context, scope: ReadScope) -> dict[str, Any]:
    """The editable rule set gap analysis is checked against.

    Rules ship with sensible defaults (e.g. "internet egress must traverse
    the firewall") so a deployment with no store configured still reports a
    usable policy rather than an empty one.
    """
    store = context.network_policy_store
    policy = store.read() if store is not None else NetworkDesignPolicy()
    # Whether a rule is actually inspected is a property of the analyzer, not
    # of the stored policy. Surfacing it here stops the UI from claiming a
    # custom rule is enforced when nothing evaluates it.
    payload, unevaluated = _policy_payload(policy)
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
        ),
    )


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
    try:
        policy = store.update(changes)
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
