"""Governed toolset for the Operations Copilot agent.

The Foundry agent never touches Azure, Fabric, or the ontology directly. Every
fact it can retrieve comes from one of the callables in :data:`TOOL_REGISTRY`,
each of which:

1. Calls the same engines the REST API routes call (:class:`SemanticEngine`,
   :class:`NetworkIntelligenceService`, :class:`VulnerabilityIntelligenceService`,
   :class:`IncidentEngine`, :class:`RemediationPlanner`) — never a second data
   path into Azure or Fabric.
2. Applies the caller's :class:`Scope` before anything is returned, using the
   same recursive filter the routers use, so a tool call can never see more
   than the equivalent REST call would.
3. Returns a :class:`ToolResult`: a bounded JSON-safe payload plus an evidence
   list (source engine, freshness, confidence) and a status
   (``ok``/``empty``/``unavailable``/``denied``) so the agent can distinguish
   an observed answer from "the platform has nothing" from "a provider failed".

This is the "governed toolset" deliverable: a stable, narrow contract the
Foundry agent's tool-calling loop is built against, independent of how each
underlying engine is implemented.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from api.errors import ApiError
from api.evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence
from api.scope import Scope, scope_attributes
from network.flow import FlowQuery
from network.service import NetworkScope

_LOGGER = logging.getLogger(__name__)

# Tool result statuses. The agent must react differently to each: "empty" is a
# true fact ("no CVEs affect this service"); "unavailable" and "denied" must
# never be narrated as if they were "empty".
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"
STATUS_DENIED = "denied"

_HIDDEN = object()
# Bounds a single tool's JSON payload before it reaches the prompt. Mirrors the
# hard ceiling `foundry_agent._build_prompt` applies to the whole turn, but
# per-tool so one oversized call cannot crowd out every other tool's context.
_MAX_ITEMS = 25


def _filter_scoped(value: Any, scope: Scope) -> Any:
    """Recursively drop entities outside ``scope`` — identical semantics to
    the router-level filters, kept local so this module has no FastAPI import.
    """
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


def _bound(value: Any, limit: int = _MAX_ITEMS) -> Any:
    """Cap list-shaped payloads so a single tool call cannot dump the estate."""
    if isinstance(value, list):
        return value[:limit]
    if isinstance(value, dict):
        return {key: _bound(child, limit) for key, child in value.items()}
    return value


@dataclass(frozen=True)
class ToolResult:
    """What a tool call returns to the investigation loop.

    ``data`` is already scope-filtered and bounded. ``evidence`` follows the
    same contract used across the REST API. ``status`` lets the agent tell an
    observed empty result apart from a provider that could not answer.
    """

    status: str
    data: Any = None
    evidence: tuple[Evidence, ...] = ()
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "evidence": [item.to_dict() for item in self.evidence],
            "warning": self.warning,
        }


@dataclass(frozen=True)
class ToolSpec:
    """A single governed tool: its contract plus the callable that serves it."""

    name: str
    description: str
    parameters: Mapping[str, str]
    handler: Callable[[ToolContext, Mapping[str, Any]], ToolResult]


@dataclass
class ToolContext:
    """Everything a tool handler needs, already bound to one investigation.

    ``context`` is the API's :class:`ApiContext` — tools resolve providers
    through it exactly as REST routes do, so a provider outage is reported
    identically in both surfaces. ``scope`` is the caller's *effective* scope,
    already narrowed by RBAC — tools must never accept a wider one.
    """

    context: Any
    scope: Scope


@dataclass(frozen=True)
class FabricIQToolAdapter:
    """Small governed boundary for optional semantic graph enrichment.

    The bound source is deliberately a relationship/policy context source,
    never an inventory enumerator. The adapter stamps every response before it
    reaches the investigation ledger or a model.

    ``source`` names the surface that actually answered, and callers must set
    it to match: the current runtime binding answers from the OneLake ontology
    projection, while a Fabric IQ traversal binding would set ``"fabric-iq"``.
    Leaving the default in place while serving a different surface would put a
    false source on an evidence citation.
    """

    query: Callable[[str, Mapping[str, Any], Scope], Mapping[str, Any]]
    source: str = "fabric-iq"
    allowed_kinds: tuple[str, ...] = ("relationships", "topology", "policy")

    def run(self, kind: str, args: Mapping[str, Any], scope: Scope) -> ToolResult:
        if kind not in self.allowed_kinds:
            return ToolResult(status=STATUS_DENIED, warning="Fabric IQ operation is not allowlisted")
        try:
            raw = self.query(kind, args, scope)
        except PermissionError:
            return ToolResult(status=STATUS_DENIED, warning="Fabric IQ access is not authorized")
        except (LookupError, RuntimeError, TimeoutError, ValueError, TypeError) as exc:
            return ToolResult(status=STATUS_UNAVAILABLE, warning=f"Fabric IQ unavailable: {exc}")
        if not isinstance(raw, Mapping):
            return ToolResult(status=STATUS_UNAVAILABLE, warning="Fabric IQ returned an invalid result")
        payload = _filter_scoped(dict(raw.get("data") or {}), scope)
        if payload is _HIDDEN or not payload:
            return ToolResult(status=STATUS_EMPTY)
        metadata = {
            "source": self.source,
            "freshness": str(raw.get("freshness") or "unknown"),
            "authorization": str(raw.get("authorization") or "scope-checked"),
            "provenance": str(raw.get("provenance") or self.source),
            "identity_authority": False,
        }
        return ToolResult(status=STATUS_OK, data={"enrichment": _bound(payload), "metadata": metadata})


def _fabric_iq_result(tool_context: ToolContext, kind: str, args: Mapping[str, Any]) -> ToolResult:
    provider = getattr(tool_context.context, "fabric_iq_provider", None)
    adapter = provider() if callable(provider) else None
    if adapter is None:
        return ToolResult(status=STATUS_UNAVAILABLE, warning="Fabric IQ is unavailable")
    if not isinstance(adapter, FabricIQToolAdapter):
        return ToolResult(status=STATUS_UNAVAILABLE, warning="Fabric IQ provider is invalid")
    return adapter.run(kind, args, tool_context.scope)


def _network_scope(scope: Scope) -> NetworkScope:
    return NetworkScope(
        connection_ids=tuple(scope.dimensions.get("subscription_connection", ())),
        subscription_ids=tuple(scope.dimensions.get("subscription", ())),
        environments=tuple(scope.dimensions.get("environment", ())),
        business_services=tuple(scope.dimensions.get("business_service", ())),
        applications=tuple(scope.dimensions.get("application", ())),
        owners=tuple(scope.dimensions.get("owner", ())),
    )


def _provider_result(
    tool_context: ToolContext, name: str, loader: Callable[[Any], ToolResult]
) -> ToolResult:
    """Resolves a provider and converts any outage into a governed status.

    Centralizes the "provider missing / degraded" handling that would
    otherwise be repeated in every handler, and guarantees a failed provider
    is reported as ``unavailable`` rather than propagating a 503 out of the
    tool-calling loop or, worse, being swallowed into an empty result.
    """
    subscription_ids = list(tool_context.scope.values("subscription"))
    hybrid_provider = None
    hybrid_names = {"incidents": "hybrid_incident_provider"}
    if subscription_ids:
        hybrid_provider = getattr(
            tool_context.context,
            hybrid_names.get(name, f"hybrid_{name}_provider"),
            None,
        )
    if callable(hybrid_provider):
        try:
            return loader(hybrid_provider(subscription_ids))
        except (LookupError, ValueError) as exc:
            return ToolResult(status=STATUS_EMPTY, warning=str(exc) or "No matching context")
        except (RuntimeError, TypeError, AttributeError) as exc:
            _LOGGER.warning("tool_hybrid_provider_failed provider=%s error=%s", name, exc)
            return ToolResult(status=STATUS_UNAVAILABLE, warning=f"The live {name} provider failed to answer")
    try:
        provider = tool_context.context.resolve_provider(name)
    except ApiError as exc:
        return ToolResult(status=STATUS_UNAVAILABLE, warning=str(exc.message))
    if provider is None:
        return ToolResult(status=STATUS_UNAVAILABLE, warning=f"The {name} provider is not configured")
    try:
        return loader(provider)
    except (LookupError, ValueError) as exc:
        return ToolResult(status=STATUS_EMPTY, warning=str(exc) or "No matching context")
    except (RuntimeError, TypeError, AttributeError) as exc:
        _LOGGER.warning("tool_provider_failed provider=%s error=%s", name, exc)
        if tool_context.context.provider_runtime is not None:
            tool_context.context.provider_runtime.record_failure(name, exc)
        return ToolResult(status=STATUS_UNAVAILABLE, warning=f"The {name} provider failed to answer")


def _semantic_result(
    tool_context: ToolContext,
    *,
    source_table: str,
    confidence: str,
    loader: Callable[[Any], dict[str, Any]],
    subject_hint: Callable[[Any], Mapping[str, str]] | None = None,
) -> ToolResult:
    def run(semantic: Any) -> ToolResult:
        raw = loader(semantic)
        subject = raw.get("subject") if isinstance(raw, dict) else None
        hint = subject_hint(semantic) if subject_hint else None
        if isinstance(subject, Mapping) and hint:
            merged_subject: Mapping[str, Any] | None = {**subject, **hint}
        elif hint:
            # Some tools (e.g. impact_context) key their raw payload under
            # "root" rather than "subject" -- the hint alone is still enough
            # to check whether the caller-provided subject is in scope.
            merged_subject = hint
        else:
            merged_subject = subject
        if isinstance(merged_subject, Mapping):
            attributes = scope_attributes(merged_subject)
            if attributes and not tool_context.scope.matches(attributes):
                # The subject itself is out of the caller's scope: report a
                # denial rather than silently filtering nested rows, which
                # would otherwise still leak the subject's own identity.
                return ToolResult(status=STATUS_DENIED, warning="Subject is outside the caller's scope")
        filtered = _filter_scoped(raw, tool_context.scope)
        payload = filtered if isinstance(filtered, dict) else {}
        if not payload:
            return ToolResult(status=STATUS_EMPTY)
        evidence = Evidence.from_context(
            raw,
            source_engine="semantic.SemanticEngine",
            source_table=source_table,
            confidence=confidence,
        )
        return ToolResult(status=STATUS_OK, data=_bound(payload), evidence=(evidence,))

    return _provider_result(tool_context, "semantic", run)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _tool_business_service_context(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolResult(status=STATUS_EMPTY, warning="A business service name is required")
    return _semantic_result(
        tool_context,
        source_table="ontology_entities",
        confidence=CONFIDENCE_HIGH,
        loader=lambda semantic: semantic.get_service_context(name, subject_type="BusinessService"),
        subject_hint=lambda semantic: {"business_service": name},
    )


def _tool_application_context(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolResult(status=STATUS_EMPTY, warning="An application name is required")
    return _semantic_result(
        tool_context,
        source_table="ontology_entities",
        confidence=CONFIDENCE_HIGH,
        loader=lambda semantic: semantic.get_application_context(name),
        subject_hint=lambda semantic: {"application": name},
    )


def _tool_risk_context(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    subject = str(args.get("subject") or "").strip()
    if not subject:
        return ToolResult(status=STATUS_EMPTY, warning="A subject is required")
    return _semantic_result(
        tool_context,
        source_table="ontology_entities",
        confidence=CONFIDENCE_MEDIUM,
        loader=lambda semantic: semantic.get_risk_context(subject),
        subject_hint=lambda semantic: {"business_service": subject, "application": subject},
    )


def _tool_impact_context(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    subject = str(args.get("subject") or "").strip()
    if not subject:
        return ToolResult(status=STATUS_EMPTY, warning="A subject is required")
    return _semantic_result(
        tool_context,
        source_table="ontology_relationships",
        confidence=CONFIDENCE_MEDIUM,
        loader=lambda semantic: semantic.get_impact_context(subject),
        subject_hint=lambda semantic: {"business_service": subject, "application": subject},
    )


def _tool_topology(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    def run(network: Any) -> ToolResult:
        service = network.scoped(_network_scope(tool_context.scope))
        analysis = service.analyze()
        return ToolResult(
            status=STATUS_OK,
            data=_bound({"topology": analysis.topology.to_dict(), "summary": analysis.summary()}),
            evidence=(
                Evidence(
                    source_engine="network.NetworkIntelligenceService",
                    source_table="ontology_entities",
                    timestamp=service.snapshot.observed_at,
                    confidence=CONFIDENCE_HIGH,
                ),
            ),
        )

    return _provider_result(tool_context, "network", run)


def _tool_hub_dependents(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    vnet_id = str(args.get("vnet_id") or "").strip()
    if not vnet_id:
        return ToolResult(status=STATUS_EMPTY, warning="A hub VNet id is required")

    def run(network: Any) -> ToolResult:
        service = network.scoped(_network_scope(tool_context.scope))
        result = service.hub_dependents(vnet_id)
        if not result.get("hub_name") and not result.get("dependent_count"):
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(result),
            evidence=(
                Evidence(
                    source_engine="network.NetworkIntelligenceService",
                    source_table="ontology_entities",
                    resource_id=vnet_id,
                    timestamp=service.snapshot.observed_at,
                    confidence=CONFIDENCE_HIGH,
                ),
            ),
        )

    return _provider_result(tool_context, "network", run)


def _tool_traffic_flow(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    source = str(args.get("source") or "").strip()
    destination = str(args.get("destination") or "").strip()
    if not source or not destination:
        return ToolResult(status=STATUS_EMPTY, warning="A source and destination are required")

    def run(network: Any) -> ToolResult:
        service = network.scoped(_network_scope(tool_context.scope))
        result = service.validate_flow(
            FlowQuery(
                source=source,
                destination=destination,
                port=args.get("port"),
                protocol=str(args.get("protocol") or "Tcp"),
                environment_scope=str(args.get("environment_scope") or ""),
            )
        )
        payload = result.to_dict()
        return ToolResult(
            status=STATUS_OK,
            data=_bound(payload),
            evidence=(
                Evidence(
                    source_engine="network.NetworkIntelligenceService",
                    source_table="ontology_entities",
                    resource_id=source,
                    timestamp=service.snapshot.observed_at,
                    confidence=CONFIDENCE_HIGH if not payload.get("unknowns") else CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "network", run)


def _tool_firewall_nsg_gaps(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    def run(network: Any) -> ToolResult:
        service = network.scoped(_network_scope(tool_context.scope))
        analysis = service.analyze()
        gaps = [gap.to_dict() for gap in analysis.gaps]
        findings = [finding.to_dict() for finding in analysis.rule_findings]
        if not gaps and not findings:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound({"gaps": gaps, "rule_findings": findings}),
            evidence=(
                Evidence(
                    source_engine="network.NetworkIntelligenceService",
                    source_table="ontology_entities",
                    timestamp=service.snapshot.observed_at,
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "network", run)


def _tool_cve_exposure(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """CVE/KB exposure, optionally narrowed to a business service."""
    business_service = str(args.get("business_service") or "").strip().casefold()

    def run(vulnerability: Any) -> ToolResult:
        rows = vulnerability.exposures(tool_context.scope)
        if business_service:
            rows = [
                row
                for row in rows
                if str(row.get("business_service") or "").casefold() == business_service
            ]
        if not rows:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(rows),
            evidence=(
                Evidence(
                    source_engine="intelligence.VulnerabilityIntelligenceService",
                    source_table="vulnerability_projection",
                    timestamp=str(getattr(vulnerability, "freshness", "") or ""),
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "vulnerability", run)


def _tool_cve_detail(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """Full CVE detail: CVSS/EPSS/KEV, affected servers/applications/business
    services, and recommended patch -- the same ontology-derived blast radius
    shown on the CVE detail page, so the Copilot can explain a specific CVE's
    reach instead of only the aggregate exposure list."""
    cve_id = str(args.get("cve_id") or "").strip()
    if not cve_id:
        return ToolResult(status=STATUS_EMPTY, warning="A CVE id is required")

    def run(vulnerability: Any) -> ToolResult:
        detail = vulnerability.cve_detail(cve_id, tool_context.scope)
        if not detail:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(detail),
            evidence=(
                Evidence(
                    source_engine="intelligence.VulnerabilityIntelligenceService",
                    source_table="vulnerability_projection",
                    resource_id=cve_id,
                    timestamp=str(getattr(vulnerability, "freshness", "") or ""),
                    confidence=CONFIDENCE_HIGH,
                ),
            ),
        )

    return _provider_result(tool_context, "vulnerability", run)


def _tool_cve_attack_path(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """Multi-hop attack path graph for a CVE: which reachable resources and
    business services chain from this CVE through the ontology graph."""
    cve_id = str(args.get("cve_id") or "").strip()
    if not cve_id:
        return ToolResult(status=STATUS_EMPTY, warning="A CVE id is required")

    def run(vulnerability: Any) -> ToolResult:
        graph = vulnerability.attack_path(cve_id, tool_context.scope)
        if not graph:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(graph),
            evidence=(
                Evidence(
                    source_engine="intelligence.VulnerabilityIntelligenceService",
                    source_table="ontology_relationships",
                    resource_id=cve_id,
                    timestamp=str(getattr(vulnerability, "freshness", "") or ""),
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "vulnerability", run)


def _tool_incidents(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    incident_id = str(args.get("incident_id") or "").strip()

    def run(engine: Any) -> ToolResult:
        if incident_id:
            try:
                detail = engine.incident(incident_id)
            except ValueError:
                return ToolResult(status=STATUS_EMPTY)
            filtered = _filter_scoped(detail, tool_context.scope)
            if filtered is _HIDDEN or "finding" not in filtered:
                return ToolResult(status=STATUS_DENIED, warning="Incident is outside the caller's scope")
            return ToolResult(
                status=STATUS_OK,
                data=_bound(filtered),
                evidence=(
                    Evidence(
                        source_engine="intelligence.IncidentEngine",
                        source_table="incident_projection",
                        resource_id=incident_id,
                        timestamp=str(detail.get("detected_at") or ""),
                        confidence=CONFIDENCE_MEDIUM,
                    ),
                ),
            )
        report = engine.report()
        incidents = _filter_scoped(report.get("incidents"), tool_context.scope)
        if not isinstance(incidents, list):
            incidents = []
        if not incidents:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(incidents),
            evidence=(
                Evidence(
                    source_engine="intelligence.IncidentEngine",
                    source_table="incident_projection",
                    timestamp=str(report.get("generated_at") or report.get("freshness") or ""),
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "incidents", run)


def _tool_remediation_plans(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    def run(planner: Any) -> ToolResult:
        plans = planner.generate_plans()
        visible = _filter_scoped(plans.get("plans"), tool_context.scope)
        if not isinstance(visible, list):
            visible = []
        if not visible:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(visible),
            evidence=(
                Evidence(
                    source_engine="intelligence.RemediationPlanner",
                    source_table="remediation_plans",
                    timestamp=str(plans.get("generated_at") or ""),
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "remediation", run)


def _tool_remediation_opportunities(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    def run(planner: Any) -> ToolResult:
        result = planner.identify_opportunities()
        opportunities = _filter_scoped(result.get("opportunities"), tool_context.scope)
        if not isinstance(opportunities, list):
            opportunities = []
        if not opportunities:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(opportunities),
            evidence=(
                Evidence(
                    source_engine="intelligence.RemediationPlanner",
                    source_table="remediation_opportunities",
                    timestamp=str(result.get("generated_at") or ""),
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "remediation", run)


def _tool_inventory_resources(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    resource_type = str(args.get("resource_type") or "").strip()
    family = str(args.get("family") or "").strip() or None

    def run(port: Any) -> ToolResult:
        result = port.list_resources(
            tool_context.scope,
            family=family,
            resource_type=resource_type or None,
            limit=_MAX_ITEMS,
        )
        rows = result.get("resources") or []
        if not rows:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(
                {
                    "resources": rows,
                    "total": result.get("total", len(rows)),
                }
            ),
            evidence=(
                Evidence(
                    source_engine="intelligence.inventory.InventoryReadPort",
                    source_table="inventory/resource_observations",
                    confidence=CONFIDENCE_HIGH,
                ),
            ),
        )

    return _provider_result(tool_context, "inventory_read_port", run)


def _tool_search(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        return ToolResult(status=STATUS_EMPTY, warning="A search query is required")

    def run(semantic: Any) -> ToolResult:
        raw = semantic.search(query)
        filtered = _filter_scoped(raw, tool_context.scope)
        payload = filtered if isinstance(filtered, dict) else {}
        items = payload.get("items") or payload.get("results") or []
        if not items:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(payload),
            evidence=(
                Evidence.from_context(
                    raw,
                    source_engine="semantic.SemanticEngine",
                    source_table="ontology_entities",
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "semantic", run)


TOOL_REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="business_service_context",
            description="Business-service context: owned applications, environments, criticality.",
            parameters={"name": "Business service name"},
            handler=_tool_business_service_context,
        ),
        ToolSpec(
            name="application_context",
            description="Application context: hosting resources, dependencies, environment.",
            parameters={"name": "Application name"},
            handler=_tool_application_context,
        ),
        ToolSpec(
            name="risk_context",
            description="Aggregated risk score for a business service, application, or resource.",
            parameters={"subject": "Business service, application, or resource identifier"},
            handler=_tool_risk_context,
        ),
        ToolSpec(
            name="impact_context",
            description="Blast radius: what depends on a subject, transitively.",
            parameters={"subject": "Business service, application, subscription, or resource identifier"},
            handler=_tool_impact_context,
        ),
        ToolSpec(
            name="network_topology",
            description="Hub-spoke network topology and summary.",
            parameters={},
            handler=_tool_topology,
        ),
        ToolSpec(
            name="hub_dependents",
            description="What depends on a hub VNet.",
            parameters={"vnet_id": "Hub VNet resource id or name"},
            handler=_tool_hub_dependents,
        ),
        ToolSpec(
            name="traffic_flow",
            description="Whether traffic is allowed between a source and destination, and which rules decide it.",
            parameters={
                "source": "Source resource, subnet, or environment",
                "destination": "Destination resource, subnet, or environment",
                "port": "Optional port",
                "protocol": "Optional protocol (default Tcp)",
            },
            handler=_tool_traffic_flow,
        ),
        ToolSpec(
            name="firewall_nsg_gaps",
            description="Firewall bypasses and NSG tightening findings.",
            parameters={},
            handler=_tool_firewall_nsg_gaps,
        ),
        ToolSpec(
            name="cve_exposure",
            description="CVE/KB exposure, optionally narrowed to a business service.",
            parameters={"business_service": "Optional business service name to narrow results"},
            handler=_tool_cve_exposure,
        ),
        ToolSpec(
            name="cve_detail",
            description="Full detail for a single CVE: CVSS/EPSS/KEV signals, affected servers, applications, and business services, and recommended patch.",
            parameters={"cve_id": "CVE identifier, e.g. CVE-2024-12345"},
            handler=_tool_cve_detail,
        ),
        ToolSpec(
            name="cve_attack_path",
            description="Multi-hop attack path graph for a CVE: reachable resources and business services through the dependency graph.",
            parameters={"cve_id": "CVE identifier, e.g. CVE-2024-12345"},
            handler=_tool_cve_attack_path,
        ),
        ToolSpec(
            name="incidents",
            description="Correlated incidents, or a single incident's detail/timeline/root cause by id.",
            parameters={"incident_id": "Optional incident id for full detail"},
            handler=_tool_incidents,
        ),
        ToolSpec(
            name="remediation_plans",
            description="Generated remediation plans for open findings.",
            parameters={},
            handler=_tool_remediation_plans,
        ),
        ToolSpec(
            name="remediation_opportunities",
            description="Prioritized remediation opportunities.",
            parameters={},
            handler=_tool_remediation_opportunities,
        ),
        ToolSpec(
            name="inventory_resources",
            description="Scoped inventory resource listing (e.g. VMs, storage accounts), optionally filtered by ARM resource type or family.",
            parameters={
                "resource_type": "Optional ARM resource type, e.g. Microsoft.Compute/virtualMachines",
                "family": "Optional inventory family (e.g. os, paas)",
            },
            handler=_tool_inventory_resources,
        ),
        ToolSpec(
            name="search",
            description="Intent-driven search over operational context (same intents as /search).",
            parameters={"query": "A supported search phrase"},
            handler=_tool_search,
        ),
        ToolSpec(
            name="fabric_iq_relationships",
            description="Optional scope-checked semantic relationship context; never inventory identity. Cite the returned metadata.source, not Fabric IQ.",
            parameters={"subject": "Resource or domain subject already in caller evidence"},
            handler=lambda context, args: _fabric_iq_result(context, "relationships", args),
        ),
        ToolSpec(
            name="fabric_iq_topology",
            description="Optional semantic topology context; cite the returned metadata.source and freshness.",
            parameters={"subject": "Topology subject already in caller evidence"},
            handler=lambda context, args: _fabric_iq_result(context, "topology", args),
        ),
        ToolSpec(
            name="fabric_iq_policy_context",
            description="Optional semantic policy context; deterministic checks remain authoritative.",
            parameters={"subject": "Policy subject already in caller evidence"},
            handler=lambda context, args: _fabric_iq_result(context, "policy", args),
        ),
    )
}


def call_tool(name: str, args: Mapping[str, Any], *, context: Any, scope: Scope) -> ToolResult:
    """Invoke one governed tool by name.

    Unknown tool names are treated as a denial rather than an error: the agent
    must never be told a tool exists that it can call with different
    arguments, since that would encourage retrying with invented parameters.
    """
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return ToolResult(status=STATUS_DENIED, warning=f"Unknown tool {name!r}")
    tool_context = ToolContext(context=context, scope=scope)
    try:
        return spec.handler(tool_context, args)
    except (LookupError, ValueError, RuntimeError, TypeError, AttributeError) as exc:
        _LOGGER.warning("tool_call_failed tool=%s error=%s", name, exc)
        return ToolResult(status=STATUS_UNAVAILABLE, warning=f"{name} failed to answer")


def tool_catalog() -> list[dict[str, Any]]:
    """The tool contracts, for the agent's system context and for docs."""
    return [
        {"name": spec.name, "description": spec.description, "parameters": dict(spec.parameters)}
        for spec in TOOL_REGISTRY.values()
    ]


__all__ = [
    "STATUS_DENIED",
    "STATUS_EMPTY",
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "TOOL_REGISTRY",
    "ToolContext",
    "FabricIQToolAdapter",
    "ToolResult",
    "ToolSpec",
    "call_tool",
    "tool_catalog",
]
