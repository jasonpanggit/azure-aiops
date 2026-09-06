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
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from api.errors import ApiError
from api.evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence
from api.exposure_query import ExposureFilter, ExposureQuery, ExposureSort
from api.scope import Scope, scope_attributes
from fabric.dataset_mapper import ONTOLOGY_RELATIONSHIP_TYPES
from intelligence.vulnerability.exposure_contracts import (
    ExposureApiPage,
    exposure_page_from_read_port,
)
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
        return [_bound(child, limit) for child in value[:limit]]
    if isinstance(value, dict):
        return {key: _bound(child, limit) for key, child in value.items()}
    return value


def _bound_disclosure(
    value: Any,
    limit: int = _MAX_ITEMS,
    *,
    path: str = "",
) -> str:
    """Describe every list the bounded payload helper will truncate."""
    truncated: dict[str, int] = {}

    def walk(candidate: Any, candidate_path: str) -> None:
        if isinstance(candidate, list):
            if len(candidate) > limit:
                key = candidate_path or "items"
                truncated[key] = max(truncated.get(key, 0), len(candidate))
            for item in candidate[:limit]:
                walk(item, candidate_path)
        elif isinstance(candidate, dict):
            for key, child in candidate.items():
                walk(
                    child,
                    f"{candidate_path}.{key}" if candidate_path else str(key),
                )

    walk(value, path)
    if not truncated:
        return ""
    details = "; ".join(
        f"{item_path} showing {limit} of {total}"
        for item_path, total in truncated.items()
    )
    return f"Agent result bound {limit}: {details}."


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
    read_only: bool = True


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
    principal: Any | None = None
    generation_selection: Any | None = None


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


def _resolve_vnet_id(service: Any, subject: str) -> str:
    """Resolve a free-text subject (name, partial name, or resource id) to a
    VNet ``resource_id``.

    Operators ask about VNets by friendly name ("demo vnet", "demo"), not by
    ARM resource id, and the name is rarely capitalized. Tool args therefore
    carry whatever text the question yielded; this resolves it against the
    scoped topology's known VNets before falling back to the raw text so an
    exact resource-id match still works unchanged.
    """
    needle = str(subject or "").strip().casefold()
    if not needle:
        return ""
    vnets = getattr(service.snapshot, "vnets", ())
    for vnet in vnets:
        if str(vnet.resource_id).casefold() == needle:
            return vnet.resource_id
    # Strip a trailing "vnet"/"virtual network" qualifier so "demo vnet"
    # matches a VNet literally named "demo".
    stripped = re.sub(r"\s*(virtual network|vnet)s?\s*$", "", needle).strip()
    for candidate in (needle, stripped):
        if not candidate:
            continue
        exact = [vnet for vnet in vnets if str(vnet.name).casefold() == candidate]
        if len(exact) == 1:
            return exact[0].resource_id
        partial = [vnet for vnet in vnets if candidate in str(vnet.name).casefold()]
        if len(partial) == 1:
            return partial[0].resource_id
    return subject


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
    if tool_context.generation_selection is not None and hasattr(
        provider, "for_generation"
    ):
        provider = provider.for_generation(tool_context.generation_selection)
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
        resolved_vnet_id = _resolve_vnet_id(service, vnet_id)
        result = service.hub_dependents(resolved_vnet_id)
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
        payload = {"gaps": gaps, "rule_findings": findings}
        return ToolResult(
            status=STATUS_OK,
            data=_bound(payload),
            evidence=(
                Evidence(
                    source_engine="network.NetworkIntelligenceService",
                    source_table="ontology_entities",
                    timestamp=service.snapshot.observed_at,
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
            warning=_bound_disclosure(payload),
        )

    return _provider_result(tool_context, "network", run)


def _tool_cve_exposure(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """CVE/KB exposure, optionally narrowed to a business service."""
    business_service = str(args.get("business_service") or "").strip().casefold()
    query_provider = getattr(
        tool_context.context, "exposure_query_provider", None
    )
    query_service = None
    if callable(query_provider):
        try:
            query_service = query_provider()
        except (LookupError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            _LOGGER.warning("exposure_query_provider_failed error=%s", exc)
            return ToolResult(
                status=STATUS_UNAVAILABLE,
                warning="The authoritative Exposure query failed to answer",
            )
    if query_service is not None:
        if tool_context.principal is None:
            return ToolResult(
                status=STATUS_DENIED,
                warning="Exposure query requires an authenticated principal",
            )
        try:
            filters = tuple(
                ExposureFilter(field, operator, value)
                for field, operator, value in (
                    (
                        "target_kind",
                        "eq",
                        str(args.get("target_kind") or "").strip(),
                    ),
                    (
                        "severity",
                        "eq",
                        str(args.get("severity") or "").strip(),
                    ),
                    (
                        "source_family",
                        "eq",
                        str(args.get("source_family") or "").strip(),
                    ),
                    (
                        "search",
                        "contains",
                        str(args.get("query") or "").strip(),
                    ),
                )
                if value
            )
            query = ExposureQuery(
                filters=filters,
                sort=ExposureSort(
                    str(args.get("sort_by") or "priority_score"),
                    str(args.get("sort_direction") or "desc"),
                ),
                page_size=_MAX_ITEMS,
            )
            authorization = query_service.authorization_for(
                tool_context.principal,
                tool_context.scope,
            )
            page = query_service.list_page(
                authorization,
                generation_id=(
                    str(args.get("generation") or "").strip() or None
                ),
                query=query,
            )
            contract = ExposureApiPage(
                total_count=page.total_count,
                items=page.items,
                next_cursor=page.next_cursor,
                generation=page.generation,
                applied_scope=page.applied_scope,
                applied_filters=page.applied_filters,
                applied_sort=page.applied_sort,
                facets=page.facets,
                completeness=page.completeness,
                freshness=page.freshness,
            )
            payload = contract.list_data()
            payload.update(
                {
                    "findings": payload["items"],
                    "read_model_generation_id": page.generation,
                    "returned_count": len(page.items),
                    "source_attribution": _source_attribution(page.items),
                }
            )
            return ToolResult(
                status=STATUS_OK if page.items else STATUS_EMPTY,
                data=_bound(payload),
                evidence=(
                    Evidence(
                        source_engine="api.ExposureQueryService",
                        source_table="gold_exposure_facts",
                        timestamp=str(page.freshness.get("as_of") or ""),
                        confidence=CONFIDENCE_HIGH,
                    ),
                ),
            )
        except PermissionError:
            return ToolResult(
                status=STATUS_DENIED,
                warning="Exposure query is outside the authenticated scope",
            )
        except (LookupError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            _LOGGER.warning("exposure_query_failed error=%s", exc)
            return ToolResult(
                status=STATUS_UNAVAILABLE,
                warning="The authoritative Exposure query failed to answer",
            )

    read_port_provider = getattr(
        tool_context.context, "exposure_read_port_provider", None
    )
    try:
        read_port = (
            read_port_provider()
            if callable(read_port_provider)
            else None
        )
    except (LookupError, RuntimeError, TypeError, AttributeError) as exc:
        _LOGGER.warning("exposure_read_port_failed error=%s", exc)
        return ToolResult(
            status=STATUS_UNAVAILABLE,
            warning="The authoritative Exposure provider failed to answer",
        )
    if read_port is not None:
        page = read_port.list_exposures(
            tool_context.scope,
            offset=0,
            limit=_MAX_ITEMS,
            business_service=business_service or None,
        )
        if not page["findings"]:
            return ToolResult(status=STATUS_EMPTY)
        generation_id = str(page.get("read_model_generation_id") or "")
        common_page = exposure_page_from_read_port(
            page,
            scope=tool_context.scope,
            filters=(
                ExposureFilter(
                    "search",
                    "contains",
                    business_service,
                ),
            )
            if business_service
            else (),
            sort={"field": "exposure_id", "direction": "asc"},
        )
        payload = {
            **page,
            "contract": common_page.contract_data(),
        }
        return ToolResult(
            status=STATUS_OK,
            data=_bound(payload),
            evidence=(
                Evidence(
                    source_engine="intelligence.vulnerability.ExposureReadPort",
                    source_table="gold_exposure_findings",
                    timestamp=generation_id,
                    confidence=CONFIDENCE_HIGH,
                ),
            ),
        )

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


def _source_attribution(
    rows: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        raw_families = row.get("source_families")
        families = (
            raw_families
            if isinstance(raw_families, list | tuple)
            else (row.get("source_family"),)
        )
        for raw_family in families:
            family = str(raw_family or "")
            if family:
                counts[family] = counts.get(family, 0) + 1
    return [
        {"source_family": family, "finding_count": count}
        for family, count in sorted(counts.items())
    ]


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



def _tool_defender_alerts(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """Active Defender alerts visible to the caller's scoped vulnerability view."""

    def run(vulnerability: Any) -> ToolResult:
        rows = vulnerability.security_alerts(tool_context.scope)
        if not rows:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(rows),
            evidence=(
                Evidence(
                    source_engine="intelligence.VulnerabilityIntelligenceService",
                    source_table="defender_alerts",
                    timestamp=str(getattr(vulnerability, "freshness", "") or ""),
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "vulnerability", run)



def _tool_defender_attack_paths(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """Scoped Defender attack paths with resolved nodes, bounded for prompt safety."""

    def run(vulnerability: Any) -> ToolResult:
        rows = vulnerability.defender_attack_paths_for_scope(tool_context.scope)
        if not rows:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(rows),
            evidence=(
                Evidence(
                    source_engine="intelligence.VulnerabilityIntelligenceService",
                    source_table="defender_attack_paths",
                    timestamp=str(getattr(vulnerability, "freshness", "") or ""),
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "vulnerability", run)



def _tool_defender_secure_score(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """Secure-score overview plus unhealthy controls for the caller's scoped estate."""

    def run(vulnerability: Any) -> ToolResult:
        overview = vulnerability.secure_score_overview(tool_context.scope)
        controls = vulnerability.secure_score_controls(tool_context.scope)
        if not overview and not controls:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound({"overview": overview, "controls": controls}),
            evidence=(
                Evidence(
                    source_engine="intelligence.VulnerabilityIntelligenceService",
                    source_table="defender_secure_scores",
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



def _tool_defender_remediation_cases(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """Correlated Defender remediation cases with optional business-service filter."""
    business_service = str(args.get("business_service") or "").strip().casefold()

    def run(planner: Any) -> ToolResult:
        correlator = getattr(planner, "defender_correlator", None)
        if correlator is None:
            return ToolResult(status=STATUS_UNAVAILABLE, warning="Defender remediation correlation is unavailable")
        cases = correlator.cases(tool_context.scope)
        if business_service:
            cases = [
                row for row in cases
                if str(row.get("business_service") or "").strip().casefold() == business_service
                or business_service in {
                    str(value).strip().casefold()
                    for value in (row.get("business_context") or {}).get("affected_services", [])
                }
            ]
        if not cases:
            return ToolResult(status=STATUS_EMPTY)
        return ToolResult(
            status=STATUS_OK,
            data=_bound(cases),
            evidence=(
                Evidence(
                    source_engine="intelligence.DefenderRemediationCorrelator",
                    source_table="defender_remediation_cases",
                    timestamp=str(getattr(getattr(correlator, "vulnerability_service", None), "freshness", "") or ""),
                    confidence=CONFIDENCE_MEDIUM,
                ),
            ),
        )

    return _provider_result(tool_context, "remediation", run)



def _tool_remediation_business_decision(tool_context: ToolContext, args: Mapping[str, Any]) -> ToolResult:
    """Business decision detail for a plan id or correlated case id."""
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolResult(status=STATUS_EMPTY, warning="A plan or case identifier is required")
    lookup = name.casefold()

    def run(planner: Any) -> ToolResult:
        repository = getattr(planner, "repository", None)
        plan = repository.get(name) if repository is not None and hasattr(repository, "get") else None
        if isinstance(plan, Mapping):
            decision = dict(plan.get("business_decision") or {})
            if not decision:
                return ToolResult(status=STATUS_EMPTY)
            return ToolResult(
                status=STATUS_OK,
                data=_bound({"plan_id": str(plan.get("plan_id") or name), "case_id": str(plan.get("case_id") or ""), "business_decision": decision}),
                evidence=(
                    Evidence(
                        source_engine="intelligence.BusinessDecisionEngine",
                        source_table="remediation_plans",
                        resource_id=str(plan.get("plan_id") or name),
                        confidence=CONFIDENCE_MEDIUM,
                    ),
                ),
            )
        correlator = getattr(planner, "defender_correlator", None)
        if correlator is None:
            return ToolResult(status=STATUS_EMPTY)
        for case in correlator.cases(tool_context.scope):
            case_id = str(case.get("case_id") or case.get("resource_key") or "")
            if lookup not in {case_id.casefold(), str(case.get("resource_key") or "").casefold()}:
                continue
            decision = {
                "disposition": case.get("disposition"),
                "urgency_rationale": case.get("urgency_rationale"),
                "confidence": case.get("confidence"),
                "review_requirements": [
                    "Business mapping review required"
                    if case.get("business_mapping_review_required")
                    else "Operator approval required before any governed action"
                ],
                "cost_of_action": case.get("cost_of_action"),
                "cost_of_inaction": case.get("cost_of_inaction"),
                "options": case.get("options") or [],
            }
            return ToolResult(
                status=STATUS_OK,
                data=_bound({"case_id": case_id, "resource_key": str(case.get("resource_key") or ""), "business_decision": decision}),
                evidence=(
                    Evidence(
                        source_engine="intelligence.DefenderRemediationCorrelator",
                        source_table="defender_remediation_cases",
                        resource_id=str(case.get("resource_key") or ""),
                        timestamp=str(getattr(getattr(correlator, "vulnerability_service", None), "freshness", "") or ""),
                        confidence=CONFIDENCE_MEDIUM,
                    ),
                ),
            )
        return ToolResult(status=STATUS_EMPTY)

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


def _ontology_provider(tool_context: ToolContext) -> Any | None:
    provider = getattr(tool_context.context, "ontology_evidence_provider", None)
    if callable(provider):
        return provider()
    return provider


def _generation_id(selection: Any | None) -> str:
    return str(getattr(selection, "generation_id", "") or "")


def _scoped_rows(
    value: Any,
    *,
    key: str,
    scope: Scope,
    limit: int,
) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        rows = value.get(key)
        if rows is None:
            rows = value.get("items")
    else:
        rows = value
    if not isinstance(rows, (list, tuple)):
        return []
    visible: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        filtered = _filter_scoped(dict(row), scope)
        if filtered is _HIDDEN or not isinstance(filtered, dict):
            continue
        visible.append(filtered)
        if len(visible) >= limit:
            break
    return visible


def _tool_list_changed_entities(
    tool_context: ToolContext,
    args: Mapping[str, Any],
) -> ToolResult:
    del args
    provider = _ontology_provider(tool_context)
    if provider is None or not hasattr(provider, "list_changed_entities"):
        return ToolResult(
            status=STATUS_UNAVAILABLE,
            warning="Ontology evidence is unavailable",
        )
    rows = provider.list_changed_entities(
        scope=tool_context.scope,
        generation=tool_context.generation_selection,
        limit=50,
    )
    visible = _scoped_rows(
        rows,
        key="changed_entities",
        scope=tool_context.scope,
        limit=50,
    )
    if not visible:
        return ToolResult(status=STATUS_EMPTY)
    return ToolResult(
        status=STATUS_OK,
        data={
            "changed_entities": visible,
            "generation_id": _generation_id(tool_context.generation_selection),
        },
    )


def _tool_get_entity_evidence(
    tool_context: ToolContext,
    args: Mapping[str, Any],
) -> ToolResult:
    entity_id = str(args.get("entity_id") or "").strip()
    if not entity_id:
        return ToolResult(status=STATUS_EMPTY, warning="An entity id is required")
    provider = _ontology_provider(tool_context)
    if provider is None or not hasattr(provider, "get_entity_evidence"):
        return ToolResult(
            status=STATUS_UNAVAILABLE,
            warning="Ontology evidence is unavailable",
        )
    rows = provider.get_entity_evidence(
        entity_id,
        scope=tool_context.scope,
        generation=tool_context.generation_selection,
        limit=40,
    )
    visible = _scoped_rows(
        rows,
        key="evidence_records",
        scope=tool_context.scope,
        limit=40,
    )
    if not visible:
        return ToolResult(status=STATUS_EMPTY)
    return ToolResult(
        status=STATUS_OK,
        data={
            "evidence_records": visible,
            "generation_id": _generation_id(tool_context.generation_selection),
        },
    )


def _tool_get_ontology_vocabulary(
    tool_context: ToolContext,
    args: Mapping[str, Any],
) -> ToolResult:
    del args
    relationship_types = [
        {
            "subject_type": subject_type,
            "predicate": predicate,
            "object_type": object_type,
        }
        for subject_type, predicate, object_type in ONTOLOGY_RELATIONSHIP_TYPES[:200]
    ]
    if not relationship_types:
        return ToolResult(status=STATUS_EMPTY)
    return ToolResult(
        status=STATUS_OK,
        data={
            "relationship_types": relationship_types,
            "generation_id": _generation_id(tool_context.generation_selection),
        },
    )


def _tool_search_relationship_history(
    tool_context: ToolContext,
    args: Mapping[str, Any],
) -> ToolResult:
    entity_id = str(args.get("entity_id") or "").strip()
    if not entity_id:
        return ToolResult(status=STATUS_EMPTY, warning="An entity id is required")
    provider = _ontology_provider(tool_context)
    if provider is None or not hasattr(provider, "search_relationship_history"):
        return ToolResult(
            status=STATUS_UNAVAILABLE,
            warning="Ontology relationship history is unavailable",
        )
    rows = provider.search_relationship_history(
        entity_id,
        scope=tool_context.scope,
        generation=tool_context.generation_selection,
        limit=200,
    )
    visible = _scoped_rows(
        rows,
        key="relationships",
        scope=tool_context.scope,
        limit=200,
    )
    if not visible:
        return ToolResult(status=STATUS_EMPTY)
    return ToolResult(
        status=STATUS_OK,
        data={
            "relationships": visible,
            "generation_id": _generation_id(tool_context.generation_selection),
        },
    )


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
            description=(
                "Scoped generation-pinned CVE/KB Exposure query with common "
                "evidence and completeness metadata."
            ),
            parameters={
                "business_service": (
                    "Legacy optional business service name during shadow rollout"
                ),
                "generation": "Optional retained Exposure generation",
                "target_kind": "Optional server or container_image target kind",
                "severity": "Optional severity filter",
                "source_family": "Optional source-family filter",
                "query": "Optional bounded search text",
                "sort_by": "Server-owned Exposure sort field",
                "sort_direction": "Sort direction: asc or desc",
            },
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
            name="defender_alerts",
            description="Active Defender alerts visible to the caller's scoped estate.",
            parameters={},
            handler=_tool_defender_alerts,
        ),
        ToolSpec(
            name="defender_attack_paths",
            description="Scoped Defender attack paths with resolved nodes and connections.",
            parameters={},
            handler=_tool_defender_attack_paths,
        ),
        ToolSpec(
            name="defender_secure_score",
            description="Secure-score overview together with unhealthy Defender controls.",
            parameters={},
            handler=_tool_defender_secure_score,
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
            name="defender_remediation_cases",
            description="Correlated Defender remediation cases with governed evidence and business context.",
            parameters={"business_service": "Optional business service name to narrow correlated cases"},
            handler=_tool_defender_remediation_cases,
        ),
        ToolSpec(
            name="remediation_business_decision",
            description="Business-decision detail for a remediation plan or correlated case identifier.",
            parameters={"name": "Remediation plan id or correlated case id"},
            handler=_tool_remediation_business_decision,
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
            name="list_changed_entities",
            description=(
                "List at most 50 changed ontology entities from the "
                "authenticated scope and selected immutable generation."
            ),
            parameters={},
            handler=_tool_list_changed_entities,
        ),
        ToolSpec(
            name="get_entity_evidence",
            description=(
                "Read at most 40 evidence records for one in-scope ontology entity."
            ),
            parameters={"entity_id": "Entity identifier already present in curator evidence"},
            handler=_tool_get_entity_evidence,
        ),
        ToolSpec(
            name="get_ontology_vocabulary",
            description=(
                "Read the authoritative bounded ontology relationship vocabulary."
            ),
            parameters={},
            handler=_tool_get_ontology_vocabulary,
        ),
        ToolSpec(
            name="search_relationship_history",
            description=(
                "Read at most 200 historical relationships for one in-scope entity."
            ),
            parameters={"entity_id": "Entity identifier already present in curator evidence"},
            handler=_tool_search_relationship_history,
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


def call_tool(
    name: str,
    args: Mapping[str, Any],
    *,
    context: Any,
    scope: Scope,
    principal: Any | None = None,
) -> ToolResult:
    """Invoke one governed tool by name.

    Unknown tool names are treated as a denial rather than an error: the agent
    must never be told a tool exists that it can call with different
    arguments, since that would encourage retrying with invented parameters.
    """
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return ToolResult(status=STATUS_DENIED, warning=f"Unknown tool {name!r}")
    resolver_provider = getattr(context, "generation_resolver_provider", None)
    try:
        resolver = resolver_provider() if callable(resolver_provider) else None
        generation_selection = resolver.resolve() if resolver is not None else None
    except (LookupError, OSError, RuntimeError, TypeError, ValueError) as exc:
        _LOGGER.warning("tool_generation_resolution_failed tool=%s error=%s", name, exc)
        return ToolResult(
            status=STATUS_UNAVAILABLE,
            warning="The ontology generation could not be resolved",
        )
    tool_context = ToolContext(
        context=context,
        scope=scope,
        principal=principal,
        generation_selection=generation_selection,
    )
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
    "FabricIQToolAdapter",
    "ToolContext",
    "ToolResult",
    "ToolSpec",
    "call_tool",
    "tool_catalog",
]
