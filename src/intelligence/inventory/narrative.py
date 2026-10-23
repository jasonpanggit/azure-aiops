"""Bounded, read-only risk narration over inventory aggregates.

The inventory service remains the only retrieval path.  This module turns its
scope-filtered aggregates into deterministic facts and optionally asks the
existing Foundry prompt agent to narrate those facts.  Model output is advisory:
the deterministic facts, source state, and citations always remain available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from api.scope import Scope
from operations.foundry_agent import FoundryAgentError

from .models import InventoryNarrativeCitation

if TYPE_CHECKING:
    from .service import InventoryService

MAX_NARRATIVE_CITATIONS = 24
MAX_NARRATIVE_FACT_CHARS = 4_000
SUPPORTED_CITATION_TABLES = frozenset(
    {"inventory/os_observations", "inventory/software_observations", "Resources", "ConfigurationData"}
)
_NARRATIVE_QUESTION = (
    "Write a short operator-facing narrative (2-4 plain sentences, no bullet "
    "list, no field-name citations, no 'OBSERVED FACT/DERIVED INFERENCE/UNKNOWN' "
    "labels) that synthesizes where the operational risk is concentrated in "
    "these scoped inventory aggregates and what to look at first. The facts "
    "panel above already lists the raw numbers verbatim, so do not restate "
    "them one-by-one -- weave the most material ones into your sentences and "
    "focus on what they mean together (e.g. concentration, blast radius, "
    "urgency). Use only the supplied facts, mention source degradation when "
    "present, and do not recommend or claim an action that is not supported. "
    "Unknown or incomplete source coverage never proves zero observations, "
    "absence of software, or absence of risk. Counts marked observed are lower "
    "bounds from retained rows, not complete estate totals."
)


def build_inventory_narrative(
    service: InventoryService,
    scope: Scope,
    foundry_agent: Any | None = None,
) -> dict[str, Any]:
    """Build facts and, when available, a bounded grounded model summary."""
    aggregates = service.narrative_aggregates(scope)
    os_groups = list(aggregates["os_groups"])
    software_groups = list(aggregates["software_groups"])
    statuses = _safe_source_status(aggregates["source_status"])
    facts, fact_items = _deterministic_facts(aggregates)
    citations = _citations(aggregates.get("evidence") or ())
    confidence = _confidence(statuses, bool(os_groups or software_groups))
    payload = {
        "facts": {
            "fact_summary": facts,
            "fact_items": fact_items,
            "confidence": confidence,
            "source_status": statuses,
            "citation_count": len(citations),
        },
        # This is intentionally aggregate-only. Do not add rows, resource IDs,
        # software identities, credentials, or browser-supplied prose here.
        "aggregate_limits": {
            "max_os_groups": len(os_groups),
            "max_software_groups": len(software_groups),
        },
    }
    narrated_summary: str | None = None
    warnings: list[str] = []
    narrated_by = ""
    model = ""
    if foundry_agent is None:
        warnings.append(
            "Risk narrative unavailable: no Foundry prompt agent is configured; "
            "showing deterministic inventory facts."
        )
    else:
        try:
            answer = foundry_agent.answer(
                question=_NARRATIVE_QUESTION,
                context=payload,
            )
            text = str(getattr(answer, "text", "") or "").strip()
            if not text:
                raise ValueError("Foundry returned an empty inventory narrative")
            if not bool(getattr(answer, "grounded", False)):
                raise ValueError("Foundry returned an ungrounded inventory narrative")
            narrated_summary = text[:MAX_NARRATIVE_FACT_CHARS]
            narrated_by = str(getattr(answer, "agent_name", "") or "")
            model = str(getattr(answer, "model", "") or "")
        except (
            FoundryAgentError,
            AttributeError,
            ConnectionError,
            TimeoutError,
            TypeError,
            ValueError,
        ):
            # Narration is optional and must never turn a usable inventory
            # response into a provider failure or an apparent zero-row result.
            warnings.append(
                "Risk narrative unavailable: the Foundry prompt agent failed; "
                "showing deterministic inventory facts."
            )

    return {
        "data": {
            "fact_summary": facts,
            "fact_items": fact_items,
            "narrated_summary": narrated_summary,
            "narrated_by": narrated_by,
            "model": model,
            "confidence": confidence,
            "citations": citations,
            "source_status": statuses,
            "requested_scope": {
                "dimensions": sorted(scope.to_dict()),
            },
            "status": "narrated" if narrated_summary else "fact_only",
        },
        "warnings": warnings + _source_warnings(statuses),
    }


def _deterministic_facts(
    aggregates: dict[str, Any],
) -> tuple[str, list[dict[str, str]]]:
    os_groups = aggregates["os_groups"]
    software_groups = aggregates["software_groups"]
    machine_count = aggregates["os_machine_count"]
    install_count = aggregates["software_install_count"]
    os_ready = _sources_ready(aggregates["os_source_status"])
    software_ready = _sources_ready(aggregates["software_source_status"])
    risk = aggregates["lifecycle_counts"]
    risk_text = (
        f"{risk.get('expired', 0)} expired, {risk.get('expiring', 0)} expiring within 90 days, "
        f"{risk.get('supported', 0)} supported, {risk.get('review', 0)} needs review"
    )
    if not os_ready:
        risk_text = f"Observed rows only: {risk_text}; overall risk unknown" if machine_count else "Unknown"
    top_os = ", ".join(
        f"{group['os_name']} {group['os_version']} ({group['machine_count']})"
        for group in os_groups[:3]
    ) or "none"
    top_software = ", ".join(
        f"{group['software_name']} {group['software_version']} ({group['install_count']})"
        for group in software_groups[:3]
    ) or "none"
    os_count = _qualified_count(machine_count, os_ready)
    os_group_count = _qualified_count(aggregates["os_group_count"], os_ready)
    software_count = _qualified_count(install_count, software_ready)
    software_group_count = _qualified_count(aggregates["software_group_count"], software_ready)
    os_summary = (
        f"{machine_count} machines across {aggregates['os_group_count']} OS groups."
        if os_ready else
        f"OS coverage is incomplete: {os_count} machines; {os_group_count} OS groups. "
        "Complete machine and OS-group counts are unknown."
    )
    software_summary = (
        f"{install_count} installed-software observations across "
        f"{aggregates['software_group_count']} software groups. Top software: {top_software}."
        if software_ready else
        f"Software coverage is incomplete: {software_count} observations; "
        f"{software_group_count} groups. Complete software counts and absence are unknown."
        + (f" Top observed software: {top_software}." if software_groups else "")
    )
    summary = (
        f"{os_summary} EOL risk: {risk_text}. "
        + (f"Top OS groups: {top_os}. " if os_ready or os_groups else "")
        + software_summary
    )
    return summary, [
        {"label": "Machines", "value": os_count},
        {"label": "OS groups", "value": os_group_count},
        {"label": "EOL risk", "value": risk_text},
        {"label": "Software observations", "value": software_count},
        {"label": "Software groups", "value": software_group_count},
    ]


def _sources_ready(statuses: dict[str, Any]) -> bool:
    return bool(statuses) and all(item.get("state") == "ready" for item in statuses.values())


def _qualified_count(count: int, ready: bool) -> str:
    if ready:
        return str(count)
    return f"{count} observed (incomplete)" if count else "Unknown"


def _safe_source_status(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(source): {
            "source_type": str(payload.get("source_type") or source),
            "state": str(payload.get("state") or "unknown"),
            "row_count": max(0, int(payload.get("row_count") or 0)),
            "observed_at": str(payload.get("observed_at") or ""),
            "query_version": str(payload.get("query_version") or ""),
        }
        for source, payload in raw.items()
        if isinstance(payload, dict)
    }


def _citations(raw: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        citation = InventoryNarrativeCitation(
            source_engine=str(item.get("source_engine") or "InventoryService"),
            source_table=str(item.get("source_table") or "inventory"),
            timestamp=str(item.get("timestamp") or ""),
        )
        if citation.source_table not in SUPPORTED_CITATION_TABLES:
            continue
        key = (citation.source_engine, citation.source_table, citation.timestamp)
        if key not in seen:
            seen.add(key)
            result.append(citation.to_dict())
        if len(result) >= MAX_NARRATIVE_CITATIONS:
            break
    return result


def _confidence(statuses: dict[str, dict[str, Any]], has_facts: bool) -> str:
    if not has_facts:
        return "unknown"
    return "medium" if any(item["state"] != "ready" for item in statuses.values()) else "high"


def _source_warnings(statuses: dict[str, dict[str, Any]]) -> list[str]:
    return [
        f"{source} inventory source is {payload['state']}; narrative facts may be incomplete."
        for source, payload in statuses.items()
        if payload["state"] != "ready"
    ]


__all__ = ["build_inventory_narrative"]
