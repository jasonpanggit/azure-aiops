"""Bounded, read-only risk narration over inventory aggregates.

The inventory service remains the only retrieval path.  This module turns its
scope-filtered aggregates into deterministic facts and optionally asks the
existing Foundry prompt agent to narrate those facts.  Model output is advisory:
the deterministic facts, source state, and citations always remain available.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from api.scope import Scope
from operations.foundry_agent import FoundryAgentError

from .models import InventoryNarrativeCitation

if TYPE_CHECKING:
    from .service import InventoryService

MAX_NARRATIVE_CITATIONS = 24
MAX_NARRATIVE_FACT_CHARS = 4_000
_NARRATIVE_QUESTION = (
    "Summarize the operational risk concentrations in these scoped inventory "
    "aggregates. Use only the supplied facts, mention source degradation when "
    "present, and do not recommend or claim an action that is not supported."
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
    facts, fact_items = _deterministic_facts(
        os_groups,
        software_groups,
        aggregates["os_machine_count"],
        aggregates["software_install_count"],
    )
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
        except (FoundryAgentError, AttributeError, TypeError, ValueError):
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
    os_groups: list[dict[str, Any]],
    software_groups: list[dict[str, Any]],
    machine_count: int,
    install_count: int,
) -> tuple[str, list[dict[str, str]]]:
    risk = Counter(_risk_bucket(group) for group in os_groups for _ in range(group["machine_count"]))
    risk_text = (
        f"{risk['expired']} expired, {risk['expiring']} expiring within 90 days, "
        f"{risk['supported']} supported, {risk['review']} needs review"
    )
    top_os = ", ".join(
        f"{group['os_name']} {group['os_version']} ({group['machine_count']})"
        for group in os_groups[:3]
    ) or "none"
    top_software = ", ".join(
        f"{group['software_name']} {group['software_version']} ({group['install_count']})"
        for group in software_groups[:3]
    ) or "none"
    summary = (
        f"{machine_count} machines across {len(os_groups)} OS groups. "
        f"EOL risk: {risk_text}. "
        f"Top OS groups: {top_os}. "
        f"{install_count} installed-software observations across "
        f"{len(software_groups)} software groups. Top software: {top_software}."
    )
    return summary, [
        {"label": "Machines", "value": str(machine_count)},
        {"label": "OS groups", "value": str(len(os_groups))},
        {"label": "EOL risk", "value": risk_text},
        {"label": "Software observations", "value": str(install_count)},
        {"label": "Software groups", "value": str(len(software_groups))},
    ]


def _risk_bucket(group: dict[str, Any]) -> str:
    if group.get("review_required") or str(group.get("lifecycle_status", "")).casefold() == "unknown":
        return "review"
    if str(group.get("lifecycle_status", "")).casefold() == "eol":
        return "expired"
    days = group.get("days_remaining")
    if isinstance(days, int) and 0 <= days <= 90:
        return "expiring"
    if str(group.get("lifecycle_status", "")).casefold() in {"supported", "extended"}:
        return "supported"
    return "review"


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
